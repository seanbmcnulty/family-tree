#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fs_descendancy.py - walk DOWN from your matched direct ancestors on FamilySearch
to find collateral relatives (siblings of ancestors, their spouses and children -
i.e. the great-aunts, great-uncles and cousins the tree is missing).

For each deceased direct ancestor with a confirmed FamilySearch id, this fetches
the FS descendancy (2 generations) and compares every person against your tree:
  - already in your tree (by FS id, or name+birth-year match)  -> nothing to do
  - not in your tree and deceased                              -> PROPOSED
  - living or possibly living                                  -> skipped
Writes fs_descendancy_review.html + fs_descendancy.json. Changes NOTHING until
you review and run apply_descendancy.py (ADD-only, backed up).

  python fs_descendancy.py            # real run (login in browser)
  python fs_descendancy.py --demo     # offline demo
  python fs_descendancy.py --limit 40 # only the deepest 40 ancestors
"""
from __future__ import annotations
import json, os, argparse, html, datetime
import fs_common as C
import fs_match as M

OUT_JSON = os.path.join(C.HERE, "fs_descendancy.json")
OUT_HTML = os.path.join(C.HERE, "fs_descendancy_review.html")


def _vitals(p):
    """Pull (birth_year, death_year, birth_place) out of a GEDCOM X person.
    The descendancy endpoint puts them in different places depending on whether
    personDetails was honoured, so try all of them: display.birthDate,
    display.lifespan ("1874-1951"), then the facts array."""
    import re as _re
    disp = p.get("display") or {}
    byr = _re.findall(r"\d{4}", disp.get("birthDate") or "")
    dyr = _re.findall(r"\d{4}", disp.get("deathDate") or "")
    place = disp.get("birthPlace")

    if not byr or not dyr:
        span = disp.get("lifespan") or ""
        parts = _re.findall(r"\d{4}", span)
        if parts:
            if not byr and not span.strip().startswith("-"):
                byr = [parts[0]]
            if not dyr and len(parts) > 1:
                dyr = [parts[-1]]

    if not byr or not dyr or not place:
        for f in p.get("facts") or []:
            t = (f.get("type") or "")
            orig = ((f.get("date") or {}).get("original") or "")
            pl = ((f.get("place") or {}).get("original") or "")
            if t.endswith("/Birth"):
                if not byr:
                    byr = _re.findall(r"\d{4}", orig)
                place = place or pl
            elif t.endswith("/Death") or t.endswith("/Burial"):
                if not dyr:
                    dyr = _re.findall(r"\d{4}", orig)
    return (int(byr[-1]) if byr else None,
            int(dyr[-1]) if dyr else None,
            place)


def parse_descendancy(data):
    """Return list of {dnum, fs_id, name, given, surname, birth_year, death_year,
    gender, birth_place} from a /platform/tree/descendancy response."""
    out = []
    for p in (data or {}).get("persons", []) or []:
        disp = p.get("display") or {}
        dnum = disp.get("descendancyNumber")
        if not dnum:
            continue
        name = disp.get("name") or ""
        by, dy, place = _vitals(p)
        out.append({
            "dnum": str(dnum), "fs_id": p.get("id"), "name": name,
            "given": name.rsplit(" ", 1)[0] if " " in name else name,
            "surname": name.rsplit(" ", 1)[-1] if " " in name else "",
            "birth_year": by, "death_year": dy, "birth_place": place,
            "gender": (disp.get("gender") or "").upper(),
        })
    return out


def fill_vitals(fs, v):
    """Last resort: fetch the person record itself for anyone still missing dates.
    Returns True if anything was filled."""
    try:
        data = C.fs_get(fs, "/platform/tree/persons/%s" % v["fs_id"],
                        accept="application/x-gedcomx-v1+json")
    except Exception:
        return False
    for p in (data or {}).get("persons", []) or []:
        if p.get("id") != v["fs_id"]:
            continue
        by, dy, place = _vitals(p)
        v["birth_year"] = v["birth_year"] or by
        v["death_year"] = v["death_year"] or dy
        v["birth_place"] = v["birth_place"] or place
        return bool(by or dy or place)
    return False


def relationship_label(anchor_gen, dnum):
    """Plain-English relationship to Sean, given the anchor's generation
    (2 = grandparent, 3 = great-grandparent, ...) and the descendancy number."""
    if dnum.endswith("-S"):
        return "married into the family"
    b = dnum.count(".")          # 1 = child of anchor, 2 = grandchild
    a = anchor_gen               # Sean's own distance from the same ancestor
    if not isinstance(a, int) or b < 1:
        return "descendant of anchor"
    cousin = min(a, b) - 1
    removed = abs(a - b)
    if cousin <= 0:
        # a direct child of the common ancestor: aunt/uncle line
        greats = max(0, removed - 1)
        return ("great-" * greats) + "aunt or uncle"
    ord_ = {1: "1st", 2: "2nd", 3: "3rd"}.get(cousin, "%dth" % cousin)
    if removed == 0:
        return "%s cousin" % ord_
    return "%s cousin %s removed" % (ord_, {1: "once", 2: "twice"}.get(removed, "%dx" % removed))


def probably_living(v):
    y = v.get("birth_year")
    dead = v.get("death_year")
    return bool(y and y > datetime.date.today().year - 100 and not dead)


def surname_index(P):
    idx = {}
    for pid, p in P.items():
        key = M.norm(p.get("surname") or "").replace(" ", "")
        idx.setdefault(key[:4], []).append(pid)
    return idx


def existing_match(v, P, fsid2pid, idx):
    """Is this FS person already in our tree?"""
    if v["fs_id"] in fsid2pid:
        return fsid2pid[v["fs_id"]]
    key = M.norm(v["surname"]).replace(" ", "")[:4]
    for pid in idx.get(key, []):
        p = P[pid]
        ns = M.name_score(M.norm(v["given"]), M.norm(v["surname"]),
                          M.norm(p.get("given") or ""), M.norm(p.get("surname") or ""))
        if ns < 0.75:
            continue
        oy = (p.get("birth") or {}).get("year")
        if v["birth_year"] and oy and abs(v["birth_year"] - oy) <= 3:
            return pid
        if not v["birth_year"] or not oy:
            if ns >= 0.9:
                return pid
    return None


def run(args):
    d, P, F = C.load_data()
    anchors = C.fs_anchors(P)
    fsid2pid = {fid: pid for pid, fid in anchors.items()}

    # Deceased direct ancestors within --max-gen of you. Generation 2 =
    # grandparents, 3 = great-grandparents, 4 = 2x-great-grandparents. Walking
    # two generations down from those gives aunts/uncles and 1st/2nd cousins -
    # the relatives close enough to be worth having. Closest anchors first.
    anc = [(pid, fid) for pid, fid in anchors.items() if P[pid].get("directAncestor")]
    anc = [(pid, fid) for pid, fid in anc
           if isinstance(P[pid].get("generation"), int)
           and 1 <= P[pid]["generation"] <= args.max_gen]
    anc.sort(key=lambda kv: P[kv[0]]["generation"])
    if args.limit:
        anc = anc[:args.limit]
    print("Matched direct ancestors within generation %d: %d" % (args.max_gen, len(anc)))
    for pid, fid in anc:
        print("   gen %d  %-34s %s" % (P[pid]["generation"], P[pid].get("name"), fid))
    if not anc:
        raise SystemExit(
            "\nNone of your ancestors that close have a FamilySearch match yet.\n"
            "Either raise --max-gen, or match more close ancestors first via fs_review.html.")
    print()

    fs = DemoFS() if args.demo else C.make_client()
    idx = surname_index(P)

    proposals, seen_fs = [], set()
    for pid, fsid in anc:
        p = P[pid]
        try:
            data = C.fs_get(fs, "/platform/tree/descendancy",
                            {"person": fsid, "generations": 2, "personDetails": "true"},
                            accept="application/x-gedcomx-v1+json")
        except Exception as e:
            print("  ! %s (%s): %s" % (p.get("name"), fsid, e))
            continue
        people = parse_descendancy(data)
        if not people:
            continue
        by_dnum = {v["dnum"]: v for v in people}
        fresh = 0
        for v in people:
            if v["dnum"] == "1" or v["fs_id"] in seen_fs or not v["fs_id"]:
                continue
            if probably_living(v):
                continue
            hit = existing_match(v, P, fsid2pid, idx)
            if hit:
                continue
            seen_fs.add(v["fs_id"])
            # the descendancy view often omits dates; fetch the person if so
            if not v["birth_year"] and not args.demo:
                fill_vitals(fs, v)
                if probably_living(v):
                    continue
            # figure out the FS parent in this descendancy (strip last .n / -S)
            dn = v["dnum"]
            if dn.endswith("-S"):
                partner = by_dnum.get(dn[:-2])
                rel = "married into the family (spouse of %s)" % (partner or {}).get("name", "?")
                parent_dnum = None
            else:
                parent_dnum = dn.rsplit(".", 1)[0] if "." in dn else None
                rel = relationship_label(p.get("generation"), dn)
            parent = by_dnum.get(parent_dnum) if parent_dnum else by_dnum.get("1")
            proposals.append({
                "anchor_pid": pid, "anchor_name": p.get("name"),
                "anchor_fs": fsid, "dnum": dn, "relation": rel,
                "fs_id": v["fs_id"], "name": v["name"], "given": v["given"],
                "surname": v["surname"], "gender": v["gender"],
                "birth_year": v["birth_year"], "death_year": v["death_year"],
                "birth_place": v.get("birth_place"),
                "parent_fs": (parent or {}).get("fs_id"),
                "parent_pid": fsid2pid.get((parent or {}).get("fs_id")),
                "spouse_dnum": dn[:-2] if dn.endswith("-S") else None,
            })
            fresh += 1
        if fresh:
            print("  %s: %d new collateral relative%s proposed"
                  % (p.get("name"), fresh, "" if fresh == 1 else "s"))

    json.dump(proposals, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    write_review(proposals, len(anc), args.demo)
    print("\n%d proposals from %d anchors. Open fs_descendancy_review.html." % (len(proposals), len(anc)))


def write_review(rows, n_anchors, demo):
    trs = []
    rows = sorted(rows, key=lambda r: (r.get("birth_year") is None, r.get("relation") or ""))
    for i, r in enumerate(rows):
        yrs = "%s-%s" % (r.get("birth_year") or "?", r.get("death_year") or "?")
        trs.append(
            '<tr><td><input type="checkbox" class="acc" data-i="%d"></td>'
            '<td>%s<br><span class="small">%s · %s</span></td>'
            '<td>%s</td><td>%s</td>'
            '<td><a class="small" href="https://www.familysearch.org/tree/person/details/%s" target="_blank">%s</a></td></tr>'
            % (i, html.escape(r["name"] or "?"), yrs, html.escape(r.get("birth_place") or ""),
               html.escape(r["relation"]), html.escape(r["anchor_name"] or ""),
               html.escape(r["fs_id"]), html.escape(r["fs_id"])))
    doc = """<!doctype html><meta charset="utf-8"><title>FamilySearch cousins review</title>
<style>%s</style><h1>Collateral relatives proposed from FamilySearch%s</h1>
<p class="small">Walked the FS descendancy of %d matched direct ancestors. Every row is a deceased person
FamilySearch knows about who is NOT in your tree - ancestors' other children, their spouses, and
grandchildren. Verify on FamilySearch (link in the last column), tick what you accept, Export, then run
<b>apply_descendancy.py</b> (9_apply_cousins.bat). ADD-only: existing people and families are never touched.</p>
<button onclick="setAll(true)">Select all</button> <button onclick="setAll(false)">Select none</button>
<button onclick="exportAccepted('fs_descendancy_accepted.json')">Export accepted -&gt; fs_descendancy_accepted.json</button>
<table><tr><th></th><th>Person</th><th>Relation</th><th>Via ancestor</th><th>FamilySearch</th></tr>%s</table>
<script>const ROWS=%s;%s</script>""" % (
        C.REVIEW_CSS, " (DEMO)" if demo else "", n_anchors,
        "\n".join(trs), json.dumps(rows), C.REVIEW_JS)
    open(OUT_HTML, "w", encoding="utf-8").write(doc)


class DemoFS:
    def _get(self, path, params=None, accept=None, **kw):
        if params and params.get("person"):
            return {"persons": [
                {"id": params["person"], "display": {"descendancyNumber": "1", "name": "Anchor Person",
                                                     "birthDate": "1850", "gender": "MALE"}},
                {"id": "DEMO-CH1", "display": {"descendancyNumber": "1.1", "name": "Margaret Demo",
                                               "birthDate": "1874", "deathDate": "1951",
                                               "birthPlace": "Dublin, Ireland", "gender": "FEMALE"}},
                {"id": "DEMO-SP1", "display": {"descendancyNumber": "1.1-S", "name": "Patrick Spouse",
                                               "birthDate": "1870", "deathDate": "1940", "gender": "MALE"}},
                {"id": "DEMO-GC1", "display": {"descendancyNumber": "1.1.1", "name": "Eileen Demo",
                                               "birthDate": "1899", "deathDate": "1980", "gender": "FEMALE"}},
            ]}
        return {"persons": []}
    def _throttle(self): pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-gen", type=int, default=4,
                    help="how far back to anchor: 2=grandparents, 3=great-grandparents, "
                         "4=2x-great-grandparents (default, yields up to 2nd cousins)")
    run(ap.parse_args())
