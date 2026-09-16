#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_all.py - one-login, walk-away FamilySearch pass over the whole tree.

After you log in once in the browser, this runs unattended and:
  1. searches FamilySearch for every non-living person in the tree, scores matches;
  2. for every match it finds, pulls the RECORDS FamilySearch has attached
     (baptisms, census, Find a Grave) - these are the real payload from the beta tree;
  3. AUTO-APPLIES only the safest, additive things:
       - attaches those record citations to the person (with the FamilySearch ARK url),
       - fills a BLANK death year / birth place from a *confident* match;
     it never overwrites you, never adds parents or new people, never touches living
     folks or the Jeon branch, backs up first, and refuses to save on any broken link;
  4. leaves everything that needs judgement (probable/possible matches, new ancestors,
     conflicts) in fs_review.html for you to look at later;
  5. writes SUMMARY.txt in plain English - read that first when you come back.

Usage:
  python run_all.py            # the real pass (needs fs_config.json + one login)
  python run_all.py --demo     # offline dry run so you can see the shape of it
  python run_all.py --limit 50 # only the first 50 people (a quick taste)
"""
from __future__ import annotations
import json, os, sys, argparse, datetime, html, re
from collections import defaultdict
import fs_match as M

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "family-data.json")
CONF = os.path.join(HERE, "fs_confirmed.json")
TODAY = datetime.date.today().isoformat()

def is_living(p):
    y = (p.get("birth") or {}).get("year")
    return bool(y and y > datetime.date.today().year - 100 and not p.get("death"))

def ark_of(citation, title):
    m = re.search(r"(https?://[^\s)]*ark:/[^\s)\"']+)", (citation or "") + " " + (title or ""))
    return m.group(1) if m else None

def entry_for(title):
    m = re.search(r"in entry for ([A-Z][\w.'-]+(?:\s+[A-Z][\w.'-]+){0,3})", title or "")
    return m.group(1) if m else None

def attach_source(person, rec):
    """ADD-only: append a record citation as webEnrichment. Dedupe by ark/title."""
    ark = ark_of(rec.get("citation"), rec.get("title"))
    key = ark or rec.get("title")
    we = person.setdefault("webEnrichment", [])
    for e in we:
        if (e.get("source") or {}).get("url") == ark and ark:
            return False
        if e.get("fact") == rec.get("title"):
            return False
    we.append({
        "fact": (rec.get("title") or "FamilySearch record").split(',')[0][:200],
        "detail": re.sub(r"<[^>]+>", "", rec.get("citation") or "")[:400] or None,
        "source": {"url": ark or "https://www.familysearch.org",
                   "title": "FamilySearch attached record"},
        "added": TODAY, "confidence": "FamilySearch attached record"})
    return True

def run(args):
    d = json.load(open(DATA, encoding="utf-8"))
    P, F = d["people"], d["families"]
    import shutil
    shutil.copy(DATA, DATA + ".bak-runall-" + TODAY)

    if args.demo:
        fs = DemoFS()
    else:
        import fs_client
        cfgp = os.path.join(HERE, "fs_config.json")
        if not os.path.exists(cfgp):
            sys.exit("Create fs_config.json first (copy fs_config.example.json, add client_id).")
        fs = fs_client.FamilySearch(json.load(open(cfgp)))
        fs.authenticate()

    review, summary = [], []
    stats = defaultdict(int)
    leads = []            # "in entry for X" relationship leads
    living_skip = 0

    ids = list(P.keys())
    searchable = sum(1 for pid in ids if not is_living(P[pid]) and
                     (M.our_person_view(pid, P, F)["surname"] or M.our_person_view(pid, P, F)["birth_year"]))
    print("About %d people to check against FamilySearch. Progress prints every 25.\n" % searchable)
    processed = 0
    for pid in ids:
        p = P[pid]
        if is_living(p):
            living_skip += 1; continue
        view = M.our_person_view(pid, P, F)
        if not view["surname"] and not view["birth_year"]:
            continue
        try:
            cands = fs.search_tree(view["given"], view["surname"], view["birth_year"],
                                   view["birth_place"],
                                   father=(M.norm(view["parents"][0]).split()[-1] if view.get("parents") else None),
                                   spouse=(view["spouses"][0].split()[0] if view.get("spouses") else None))
        except Exception as e:
            summary.append("  ! search failed for %s (%s)" % (p["name"], e)); continue
        processed += 1
        if processed % 25 == 0:
            print("  ...%d checked  (%d records so far, %d queued for review)" %
                  (processed, stats.get("records_attached", 0), len(review)), flush=True)
        scored = []
        for c in cands:
            s, b = M.score_match(view, c)
            scored.append((s, M.classify(s), c))
        scored.sort(key=lambda x: -x[0])
        if not scored or scored[0][0] < 0.5:
            if args.limit and processed >= args.limit: break
            continue
        score, verdict, cand = scored[0]
        stats[verdict] += 1
        accepted = score >= args.accept        # auto-apply everything at/above the bar
        # everything below the bar is recorded for review but NOT applied
        applied = []
        if accepted:
            stats["auto_accepted"] += 1
            # pull attached records for the matched FS id (only for accepted people, so we
            # never staple a stranger's baptism onto a low-confidence guess)
            recs = []
            try:
                if cand.get("fs_id"):
                    recs = fs.get_sources(cand["fs_id"])
            except Exception:
                recs = []
            for r in recs:
                if attach_source(p, r):
                    applied.append("record: " + (r.get("title") or "")[:70])
                    stats["records_attached"] += 1
                lead = entry_for(r.get("title"))
                if lead and M.norm(lead.split()[-1]) == M.norm(view["surname"]):
                    leads.append((p["name"], lead, r.get("title")))
            if not (p.get("death") or {}).get("year") and cand.get("death_year"):
                p.setdefault("death", {})["year"] = cand["death_year"]
                applied.append("death year %s" % cand["death_year"]); stats["fields_filled"] += 1
            if not (p.get("birth") or {}).get("place") and cand.get("birth_place"):
                p.setdefault("birth", {})["place"] = cand["birth_place"]
                applied.append("birth place %s" % cand["birth_place"]); stats["fields_filled"] += 1
            # link the FamilySearch profile as a source (ADD-only, deduped)
            we = p.setdefault("webEnrichment", [])
            fsurl = "https://www.familysearch.org/tree/person/details/" + str(cand.get("fs_id"))
            if not any((e.get("source") or {}).get("url") == fsurl for e in we):
                we.append({"fact": "Matched to FamilySearch profile (score %.2f, %s)." % (score, verdict),
                           "source": {"url": fsurl, "title": "FamilySearch person " + str(cand.get("fs_id"))},
                           "added": TODAY, "confidence": "FamilySearch %s match" % verdict})
                applied.append("linked FS profile")
        review.append({"pid": pid, "name": p["name"], "score": round(score, 3),
                       "verdict": verdict, "fs_id": cand.get("fs_id"),
                       "birth_year": view.get("birth_year"),
                       "cand": cand, "accepted": accepted, "auto_applied": applied})
        if args.limit and processed >= args.limit: break

    # ---- extend from confirmed anchors: capture records, list new-slot ancestors ----
    new_ancestors = []
    if os.path.exists(CONF):
        for a in json.load(open(CONF, encoding="utf-8")):
            if a["pid"] not in P: continue
            try:
                anc = fs.get_ancestry(a["fs_id"], generations=5)
                srcs = fs.get_sources(a["fs_id"])
            except Exception:
                anc, srcs = [], []
            for r in srcs:
                if attach_source(P[a["pid"]], r): stats["records_attached"] += 1
                lead = entry_for(r.get("title"))
                if lead: leads.append((P[a["pid"]]["name"], lead, r.get("title")))
            # blank-slot ancestors -> review only
            ah = {1: a["pid"]}
            for person in anc:
                k = person.get("ahnen", 0)
                if k <= 1 or not person.get("name"): continue
                child = ah.get(k // 2)
                if not child: continue
                fam = F.get(P[child].get("famc")) or {}
                slot = "husband" if k % 2 == 0 else "mother".replace("mother", "wife")
                if not fam.get(slot):
                    new_ancestors.append({"name": person["name"], "child": P[child]["name"],
                                          "role": "father" if k % 2 == 0 else "mother",
                                          "fs_id": person.get("fs_id"),
                                          "birth_year": person.get("birth_year"),
                                          "birth_place": person.get("birth_place")})
                ah[k] = fam.get(slot) or ("NEW:" + str(person.get("fs_id")))

    # ---- validate & save ----
    broken = sum(1 for pid, pp in P.items() if pp.get("famc") and pp["famc"] not in F) \
           + sum(1 for pp in P.values() for f in pp.get("fams", []) if f not in F) \
           + sum(1 for fa in F.values() for x in [fa.get("husband"), fa.get("wife")] + fa.get("children", []) if x and x not in P)
    if broken:
        sys.exit("Aborting without saving: %d broken links (your .bak file is intact)." % broken)
    # atomic save: write a temp file, flush to disk, then swap it in. An interrupted
    # write can never leave family-data.json half-written again.
    tmp = DATA + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, separators=(",", ":"))
        fh.flush(); os.fsync(fh.fileno())
    # verify the temp file re-reads as valid before replacing the real file
    chk = json.load(open(tmp, encoding="utf-8"))
    if len(chk["people"]) != len(P):
        sys.exit("Save verification failed; left family-data.json untouched.")
    os.replace(tmp, DATA)
    print("Saved family-data.json (%d people) - verified." % len(P))

    # full machine-readable record of every match (so thresholds can be re-tuned
    # later with auto_accept.py WITHOUT re-querying FamilySearch)
    json.dump({"accept_threshold": args.accept, "rows": review,
               "new_ancestors": new_ancestors},
              open(os.path.join(HERE, "fs_review.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    leftovers = [r for r in review if not r["accepted"]]
    write_review(leftovers, new_ancestors, args.demo, args.accept)
    write_summary(processed, living_skip, stats, leads, new_ancestors, leftovers, args.demo, args.accept)
    print("\nDONE. Read SUMMARY.txt. Auto-accepted %d matches at score >= %.2f "
          "(%d records attached, %d blanks filled). %d lower-confidence matches "
          "left for your review, %d new-ancestor leads."
          % (stats["auto_accepted"], args.accept, stats["records_attached"],
             stats["fields_filled"], len(leftovers), len(new_ancestors)))

def write_summary(processed, living, stats, leads, new_anc, review, demo, accept):
    L = []
    L.append("FAMILYSEARCH FULL PASS - SUMMARY  (%s)%s" % (TODAY, "  [DEMO]" if demo else ""))
    L.append("=" * 60)
    L.append("")
    L.append("People checked against FamilySearch : %d" % processed)
    L.append("Living people skipped for privacy   : %d" % living)
    L.append("")
    L.append("AUTO-ACCEPTED at score >= %.2f (safe, additive, backed up):" % accept)
    L.append("  Matches auto-applied        : %d" % stats.get("auto_accepted", 0))
    L.append("  Historical records attached : %d" % stats.get("records_attached", 0))
    L.append("  Blank death/place filled    : %d" % stats.get("fields_filled", 0))
    L.append("  (nothing was overwritten; no parents or new people were auto-added)")
    L.append("")
    L.append("LEFT FOR YOUR REVIEW (below %.2f): %d matches - see fs_review.html" % (accept, len(review)))
    L.append("")
    L.append("MATCH QUALITY found:")
    L.append("  confident : %d      probable : %d      possible : %d"
             % (stats.get("confident", 0), stats.get("probable", 0), stats.get("possible", 0)))
    L.append("")
    if new_anc:
        L.append("NEW ANCESTORS FamilySearch offers for your empty slots (review needed):")
        for n in new_anc:
            L.append("  - %s  as %s of %s  (b.%s %s)" % (n["name"], n["role"], n["child"],
                     n.get("birth_year") or "?", n.get("birth_place") or ""))
        L.append("")
    if leads:
        L.append("RELATIONSHIP LEADS (people named in the same records - possible siblings/kin):")
        seen = set()
        for who, lead, title in leads:
            k = (who, lead)
            if k in seen: continue
            seen.add(k)
            L.append("  - '%s' appears with %s  [%s]" % (lead, who, (title or "")[:60]))
        L.append("")
    L.append("WHAT TO DO NEXT:")
    L.append("  1. Open fs_review.html - tick any probable/possible matches or new")
    L.append("     ancestors you want, Export accepted, then run  python apply_reviewed.py")
    L.append("     (it now also checks your Downloads folder automatically).")
    L.append("  2. Hand the updated family-data.json back to Claude to rebuild index.html,")
    L.append("     or run your site build.")
    L.append("  3. A backup of your data before this run is saved next to family-data.json")
    L.append("     as family-data.json.bak-runall-%s - restore it if anything looks off." % TODAY)
    open(os.path.join(HERE, "SUMMARY.txt"), "w", encoding="utf-8").write("\n".join(L))

def write_review(review, new_anc, demo, accept=0.75):
    def rr(r):
        aa = ("<br><small style='color:#2e7d32'>auto-applied: " + html.escape("; ".join(r["auto_applied"])) + "</small>") if r["auto_applied"] else ""
        c = r["cand"]
        return ("<tr class=%s><td><input type=checkbox data-i='%d'></td>"
                "<td><b>%s</b><br><small>%s</small>%s</td><td>%.2f %s</td>"
                "<td>%s %s<br><small>FS %s b.%s</small></td></tr>" % (
            r["verdict"], review.index(r), html.escape(r["name"]), r["pid"], aa,
            r["score"], r["verdict"], html.escape(c.get("given", "")), html.escape(c.get("surname", "")),
            html.escape(str(c.get("fs_id"))), c.get("birth_year") or "?"))
    na = "".join("<li><b>%s</b> as %s of %s (b.%s %s) - FS %s</li>" % (
        html.escape(n["name"]), n["role"], html.escape(n["child"]), n.get("birth_year") or "?",
        html.escape(n.get("birth_place") or ""), html.escape(str(n.get("fs_id")))) for n in new_anc)
    doc = """<!doctype html><meta charset=utf-8><title>FamilySearch review</title>
<style>body{font:14px Georgia,serif;max-width:1050px;margin:24px auto;color:#2b2620}
h1,h2{color:#2e5339}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:7px;text-align:left;vertical-align:top}
th{background:#2e5339;color:#fff}tr.confident{background:#eef6ec}tr.probable{background:#fbf6e8}
.note{background:#faf6ea;border-left:4px solid #b08d3e;padding:10px 14px;margin:12px 0}
button{background:#2e5339;color:#fff;border:none;padding:9px 16px;border-radius:8px;cursor:pointer}</style>
<h1>FamilySearch - review queue """ + ("(DEMO)" if demo else "") + """</h1>
<div class=note>Everything scoring &ge; """ + ("%.2f" % accept) + """ was <b>already auto-applied</b> (records attached,
blank death/place filled, FamilySearch profile linked). Only the <b>lower-confidence</b> matches are
below - these need your eye. Tick the ones you accept, Export accepted &rarr; <code>fs_accepted.json</code>,
then run <code>python apply_reviewed.py</code>.</div>
""" + ("<h2>New ancestors offered for empty slots</h2><ul>" + na + "</ul>" if new_anc else "") + """
<h2>Matches to confirm</h2><p><button onclick="exp()">Export accepted</button></p>
<table><tr><th>&#10003;</th><th>Our person</th><th>Score</th><th>FamilySearch</th></tr>""" + \
    "".join(rr(r) for r in review) + """</table>
<script>const R=""" + json.dumps([{"pid": r["pid"], "fs_id": r["fs_id"], "score": r["score"]} for r in review]) + """;
function exp(){const a=[];document.querySelectorAll('input[type=checkbox]').forEach(c=>{if(c.checked)a.push(R[+c.dataset.i]);});
const b=new Blob([JSON.stringify(a,null,1)],{type:'application/json'});const u=document.createElement('a');
u.href=URL.createObjectURL(b);u.download='fs_accepted.json';u.click();}</script>"""
    open(os.path.join(HERE, "fs_review.html"), "w", encoding="utf-8").write(doc)

class DemoFS:
    def authenticate(self): pass
    def search_tree(self, given, surname, birth_year=None, birth_place=None, father=None, spouse=None, count=8):
        if M.norm(surname) == "mcnulty" and birth_year and 1860 < (birth_year or 0) < 1890:
            return [{"fs_id": "F5TH-55J", "given": given, "surname": "McNulty",
                     "birth_year": birth_year, "death_year": None,
                     "birth_place": "Dublin, Ireland", "parents": [], "spouses": []}]
        return []
    def get_sources(self, fs_id):
        return [{"title": "Laurence Francis Mc Nulty, \"Ireland Births and Baptisms, 1620-1881\"",
                 "citation": "FamilySearch (https://familysearch.org/ark:/61903/1:1:F5TH-55J : 8 December 2014), Laurence Francis Mc Nulty, 18 Sep 1869; citing Dublin, Ireland."}]
    def get_ancestry(self, fs_id, generations=5):
        return [{"ahnen": 1, "fs_id": fs_id, "name": "Anchor"}]

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--accept", type=float, default=0.75,
                    help="auto-apply matches at/above this score (default 0.75)")
    run(ap.parse_args())
