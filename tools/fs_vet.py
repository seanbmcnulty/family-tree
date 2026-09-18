#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fs_vet.py - automatic sense-check of the cousin proposals in fs_descendancy.json,
so you only add people we can be fairly certain about.

For every proposed person it checks, with evidence, not vibes:
  RECORDS    - how many actual historical records (birth/baptism/marriage/census/
               death/burial) FamilySearch has attached to that person. Unsourced
               user-tree entries score poorly; 2+ vital records score highly.
  CHRONOLOGY - child born when the parent was 13-60; death after birth; lifespan
               under 105; grandchildren consistent with their parent's dates.
  NAMES      - children carry the father's surname (spelling variants allowed);
               placeholder names ("Unknown", "Infant", initials-only) are rejected.
  GEOGRAPHY  - birthplace country consistent with where that family actually was.

Verdicts:
  ACCEPT (score >= 0.75, incl. at least one attached record) -> written straight
         into fs_descendancy_accepted.json, ready for 9_apply_cousins.bat
  REVIEW (0.45-0.75) -> left for your eyes in fs_vet_report.html
  REJECT (< 0.45 or a hard red flag) -> listed with the reason, not added

  python fs_vet.py             # real run (needs login: it fetches sources)
  python fs_vet.py --demo      # offline demo
  python fs_vet.py --threshold 0.85   # stricter
"""
from __future__ import annotations
import json, os, re, argparse, html, datetime
import fs_common as C
import fs_match as M

IN_JSON = os.path.join(C.HERE, "fs_descendancy.json")
OUT_ACC = os.path.join(C.HERE, "fs_descendancy_accepted.json")
OUT_HTML = os.path.join(C.HERE, "fs_vet_report.html")

VITAL = re.compile(r"birth|baptism|christen|marriage|banns|death|burial|census|"
                   r"probate|cemetery|obituar|civil registration|church record", re.I)
PLACEHOLDER = re.compile(r"^(unknown|unnamed|infant|baby|child|stillborn|n\.?n\.?|"
                         r"[a-z]\.?( [a-z]\.?)?)$", re.I)


def vital_record_count(sources):
    return sum(1 for s in sources
               if VITAL.search((s.get("title") or "") + " " + (s.get("citation") or "")))


def year_of(P, pid):
    return ((P.get(pid) or {}).get("birth") or {}).get("year")


def country_cluster(P, anchor_pid):
    """Countries this branch of the family actually lived in around the anchor."""
    out = set()
    a = P.get(anchor_pid) or {}
    for slot in ("birth", "death"):
        c = (a.get(slot) or {}).get("country")
        if c:
            out.add(c)
    return out


COUNTRY_HINTS = {
    "Canada": "canada", "United States": "united states", "England": "england",
    "Ireland": "ireland", "Scotland": "scotland", "Wales": "wales",
    "Germany": "germany", "Switzerland": "switzerland", "Netherlands": "netherlands",
    "France": "france", "Belgium": "belgium",
}


def vet_one(r, P, byfs, sources):
    """Return (score, notes:list, hard_reject:bool)."""
    notes, score = [], 0.0
    hard = False

    # RECORDS - the strongest signal (0 to 0.45)
    nrec = vital_record_count(sources)
    score += min(nrec, 3) * 0.15
    notes.append("%d vital record%s attached" % (nrec, "" if nrec == 1 else "s"))

    # NAME sanity
    given = (r.get("given") or "").strip()
    if not given or PLACEHOLDER.match(given):
        notes.append("placeholder given name")
        hard = True
    if not r.get("surname"):
        notes.append("no surname")
        score -= 0.1

    # BIRTH YEAR present at all?
    by = r.get("birth_year")
    if not by:
        notes.append("no birth year on FS")
        score -= 0.15
    dy = r.get("death_year")
    if by and dy:
        if dy < by:
            notes.append("dies before birth"); hard = True
        elif dy - by > 105:
            notes.append("lifespan %d years" % (dy - by)); hard = True
        else:
            score += 0.1

    # CHRONOLOGY vs the person they hang off
    dn = r.get("dnum", "")
    is_spouse = dn.endswith("-S")
    parent_by = None
    if is_spouse:
        partner = byfs.get(next((o["fs_id"] for o in byfs.values()
                                 if o.get("dnum") == dn[:-2]
                                 and o.get("anchor_fs") == r.get("anchor_fs")), ""))
        partner_by = (partner or {}).get("birth_year")
        if by and partner_by:
            if abs(by - partner_by) <= 20:
                score += 0.2
                notes.append("age fits their spouse")
            else:
                notes.append("%d-year age gap to spouse" % abs(by - partner_by))
                score -= 0.1
    if not is_spouse:
        parent_pid = r.get("parent_pid")
        if parent_pid:
            parent_by = year_of(P, parent_pid)
        if parent_by is None and r.get("parent_fs") in byfs:
            parent_by = byfs[r["parent_fs"]].get("birth_year")
        if parent_by is None and dn.count(".") == 1:
            parent_by = year_of(P, r.get("anchor_pid"))
        if by and parent_by:
            gap = by - parent_by
            if 13 <= gap <= 60:
                score += 0.2
                notes.append("parent aged %d at birth - plausible" % gap)
            else:
                notes.append("parent aged %d at birth" % gap)
                hard = True

    # SURNAME continuity (children only; mothers/spouses keep their own)
    if not is_spouse and r.get("surname"):
        anchor = P.get(r.get("anchor_pid")) or {}
        fam_sn = anchor.get("surname") or ""
        a, b = M.norm(r["surname"]), M.norm(fam_sn)
        ns = 1.0 if a == b else M._lev_ratio(a, b)
        if ns >= 0.8:
            score += 0.1
            notes.append("surname matches the %s line" % fam_sn)
        elif fam_sn:
            notes.append("surname %s vs family %s" % (r["surname"], fam_sn))
            score -= 0.05

    # GEOGRAPHY
    bp = (r.get("birth_place") or "").lower()
    if bp:
        cluster = country_cluster(P, r.get("anchor_pid"))
        hints = [COUNTRY_HINTS.get(c) for c in cluster if COUNTRY_HINTS.get(c)]
        if hints:
            if any(h in bp for h in hints):
                score += 0.15
                notes.append("birthplace in the family's country")
            else:
                # emigration is real - mild penalty only, era-aware bonus none
                notes.append("birthplace outside the family's countries")
                score -= 0.05

    return max(0.0, min(1.0, score)), notes, hard


def run(args):
    if not os.path.exists(IN_JSON):
        raise SystemExit("No fs_descendancy.json - run fs_descendancy.py (8_find_cousins.bat) first.")
    rows = json.load(open(IN_JSON, encoding="utf-8"))
    if not rows:
        raise SystemExit("fs_descendancy.json is empty - nothing to vet.")
    d, P, F = C.load_data()
    byfs = {r["fs_id"]: r for r in rows}
    if args.max_gen is not None:
        before = len(rows)
        rows = [r for r in rows
                if isinstance((P.get(r.get("anchor_pid")) or {}).get("generation"), int)
                and (P[r["anchor_pid"]]["generation"]) <= args.max_gen]
        print("Generation filter <= %d: %d of %d proposals kept." % (args.max_gen, len(rows), before))

    cache_path = os.path.join(C.HERE, "fs_vet_cache.json")
    cache = json.load(open(cache_path, encoding="utf-8")) if os.path.exists(cache_path) else {}
    need = [r for r in rows if r["fs_id"] not in cache]
    print("Vetting %d proposals: %d cached, %d to fetch (about %d min)."
          % (len(rows), len(rows) - len(need), len(need), max(1, round(len(need) / 120.0))))
    # no sign-in needed when every record lookup is already cached
    fs = (DemoFS() if args.demo else C.make_client()) if need else None

    accept, review, reject = [], [], []
    for i, r in enumerate(rows):
        if r["fs_id"] in cache:
            sources = cache[r["fs_id"]]
        else:
            try:
                sources = fs.get_sources(r["fs_id"]) or []
            except Exception:
                sources = []
            if not args.demo:
                cache[r["fs_id"]] = sources
                if i % 50 == 0:
                    json.dump(cache, open(cache_path, "w", encoding="utf-8"))
        score, notes, hard = vet_one(r, P, byfs, sources)
        r["_vet"] = {"score": round(score, 2), "notes": notes, "records": vital_record_count(sources)}
        if hard:
            r["_vet"]["verdict"] = "reject"
            reject.append(r)
        elif score >= args.threshold and r["_vet"]["records"] >= args.min_records:
            r["_vet"]["verdict"] = "accept"
            accept.append(r)
        elif score >= 0.45:
            r["_vet"]["verdict"] = "review"
            review.append(r)
        else:
            r["_vet"]["verdict"] = "reject"
            reject.append(r)

    if not args.demo:
        json.dump(cache, open(cache_path, "w", encoding="utf-8"))
    json.dump(accept, open(OUT_ACC, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    write_report(accept, review, reject, args)
    print("\nACCEPT : %3d  -> fs_descendancy_accepted.json (run 9_apply_cousins.bat)" % len(accept))
    print("REVIEW : %3d  -> fs_vet_report.html (tick + export to add any of these later)" % len(review))
    print("REJECT : %3d  -> listed in the report with reasons" % len(reject))


def _rowhtml(r, i, checkbox):
    v = r["_vet"]
    yrs = "%s-%s" % (r.get("birth_year") or "?", r.get("death_year") or "?")
    cb = ('<td><input type="checkbox" class="acc" data-i="%d"></td>' % i) if checkbox else ""
    return ('<tr>%s<td>%s<br><span class="small">%s · %s</span></td>'
            '<td><b>%.2f</b> · %d rec</td><td class="small">%s</td>'
            '<td>%s<br><a class="small" href="https://www.familysearch.org/tree/person/details/%s" target="_blank">%s</a></td></tr>'
            % (cb, html.escape(r.get("name") or "?"), yrs, html.escape(r.get("relation") or ""),
               v["score"], v["records"], html.escape("; ".join(v["notes"])),
               html.escape(r.get("anchor_name") or ""), html.escape(r["fs_id"]), html.escape(r["fs_id"])))


def write_report(accept, review, reject, args):
    rev_rows = "\n".join(_rowhtml(r, i, True) for i, r in enumerate(review))
    acc_rows = "\n".join(_rowhtml(r, 0, False) for r in accept)
    rej_rows = "\n".join(_rowhtml(r, 0, False) for r in reject)
    hdr_cb = "<tr><th></th><th>Person</th><th>Score</th><th>Evidence</th><th>Via / FS</th></tr>"
    hdr = "<tr><th>Person</th><th>Score</th><th>Evidence</th><th>Via / FS</th></tr>"
    doc = """<!doctype html><meta charset="utf-8"><title>Cousin vetting report</title>
<style>%s</style><h1>Automatic sense-check of proposed relatives%s</h1>
<p class="small">Threshold %.2f, minimum %d attached record(s). ACCEPTED rows are already in
fs_descendancy_accepted.json - just run <b>9_apply_cousins.bat</b>. The REVIEW section is the maybe pile:
tick any you're comfortable with, Export, and run 9 again (already-added people are skipped automatically).</p>
<h2>✅ Accepted automatically (%d)</h2><table>%s%s</table>
<h2>🤔 Needs a human (%d)</h2>
<button onclick="setAll(true)">Select all</button> <button onclick="setAll(false)">Select none</button>
<button onclick="exportAccepted('fs_descendancy_accepted.json')">Export ticked -&gt; fs_descendancy_accepted.json</button>
<table>%s%s</table>
<h2>❌ Rejected (%d)</h2><table>%s%s</table>
<script>const ROWS=%s;%s</script>""" % (
        C.REVIEW_CSS, " (DEMO)" if args.demo else "", args.threshold, args.min_records,
        len(accept), hdr, acc_rows,
        len(review), hdr_cb, rev_rows,
        len(reject), hdr, rej_rows,
        json.dumps(review), C.REVIEW_JS)
    open(OUT_HTML, "w", encoding="utf-8").write(doc)


class DemoFS:
    def get_sources(self, fs_id):
        # give some demo people records, others none
        if hash(fs_id) % 2:
            return [{"title": "England Births and Christenings", "citation": "demo"},
                    {"title": "1901 Census of Canada", "citation": "demo"}]
        return []
    def _throttle(self): pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--threshold", type=float, default=0.75)
    ap.add_argument("--min-records", type=int, default=1)
    ap.add_argument("--max-gen", type=int, default=None,
                    help="only vet cousins whose anchor is this close: 2=grandparents, 3=great-grandparents")
    run(ap.parse_args())
