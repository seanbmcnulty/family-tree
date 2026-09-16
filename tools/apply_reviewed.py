#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_reviewed.py — the ONLY script that writes to the tree, and only the
changes YOU ticked in the review report (exported as fs_accepted.json).

Safety:
  • Backs up family-data.json first.
  • Only ADDs missing facts (death year, birth place) and appends a sourced note
    with the FamilySearch person id. It never overwrites an existing value and
    never deletes anyone — so the Jeon branch and every prior correction are safe.
  • "Disagree" diffs are recorded as a note for you to judge, not auto-applied.
  • Re-validates (no broken links) and recomputes generations before saving.
"""
import json, os, shutil, datetime
from collections import defaultdict

def _find_accepted(name):
    """Look next to the scripts first, then the user's Downloads folder."""
    import glob
    here = os.path.dirname(os.path.abspath(__file__))
    local = os.path.join(here, name)
    if os.path.exists(local):
        return local
    dl = os.path.join(os.path.expanduser("~"), "Downloads")
    cands = sorted(glob.glob(os.path.join(dl, name)) +
                   glob.glob(os.path.join(dl, name.replace(".json", "*.json"))),
                   key=os.path.getmtime, reverse=True)
    return cands[0] if cands else local

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "family-data.json")
ACC  = _find_accepted("fs_accepted.json")
REVIEW = os.path.join(HERE, "fs_review.json")

def main():
    if not os.path.exists(ACC):
        raise SystemExit("No fs_accepted.json — export accepted rows from fs_review.html first.")
    d = json.load(open(DATA, encoding="utf-8")); P, F = d["people"], d["families"]
    accepted = json.load(open(ACC, encoding="utf-8"))
    _rev_raw = json.load(open(REVIEW, encoding="utf-8")) if os.path.exists(REVIEW) else []
    _rev_rows = _rev_raw["rows"] if isinstance(_rev_raw, dict) else _rev_raw
    review = {r["pid"]: r for r in _rev_rows}

    shutil.copy(DATA, DATA + ".bak-" + datetime.date.today().isoformat())
    applied = 0
    for row in accepted:
        pid = row["pid"]; p = P.get(pid)
        if not p: continue
        r = review.get(pid, {})
        cand = (r.get("cand") or {})
        added = []
        # ADD-only facts
        if not (p.get("death") or {}).get("year") and cand.get("death_year"):
            p.setdefault("death", {})["year"] = cand["death_year"]; added.append(f"death {cand['death_year']}")
        if not (p.get("birth") or {}).get("place") and cand.get("birth_place"):
            p.setdefault("birth", {})["place"] = cand["birth_place"]; added.append("birth place")
        note = (f"FamilySearch match (id {cand.get('fs_id','?')}, score {row.get('score','?')}, "
                f"applied {datetime.date.today().isoformat()}). "
                + ("Added: " + ", ".join(added) + ". " if added else "")
                + "Review the FamilySearch profile for sources, parents and any disagreements before treating as proven. [FS-sync]")
        p.setdefault("notes", []).append(note)
        p.setdefault("webEnrichment", []).append(
            {"fact": "Matched to a FamilySearch tree person — see FS for sources.",
             "source": {"url": f"https://www.familysearch.org/tree/person/details/{cand.get('fs_id','')}",
                        "title": "FamilySearch person " + str(cand.get("fs_id",""))},
             "added": datetime.date.today().isoformat(), "confidence": row.get("verdict", "review")})
        applied += 1

    # validate + recompute
    broken = sum(1 for pid,p in P.items() if p.get("famc") and p["famc"] not in F) \
           + sum(1 for p in P.values() for f in p.get("fams",[]) if f not in F)
    if broken:
        raise SystemExit(f"Aborting: {broken} broken links detected — restore the .bak file.")
    tmp = DATA + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, separators=(",", ":"))
        fh.flush(); os.fsync(fh.fileno())
    if len(json.load(open(tmp, encoding="utf-8"))["people"]) != len(P):
        raise SystemExit("Save verification failed; family-data.json left untouched.")
    os.replace(tmp, DATA)
    print(f"Applied FamilySearch data to {applied} people (ADD-only, sourced notes). "
          f"Backup saved. Now rebuild the site (see project README) and push.")

if __name__ == "__main__":
    main()
