#!/usr/bin/env python3
import json, sys, shutil, datetime
sys.path.insert(0, '.')
from cleanup_and_build import merge_people, recompute, broken_links

HERE_DATA = "../family-data.json"
d = json.load(open(HERE_DATA, encoding="utf-8"))
P, F = d["people"], d["families"]
TODAY = datetime.date.today().isoformat()

# (keep, drop, conflict_note_or_None)
decisions = [
    ("I270048035432", "I270048035425",
     "Alternate source (merged duplicate I270048035425) claimed father as Thomas Armstrong "
     "instead of Henry Armstrong + Sarah Murphy — same person (matching death date/place, spouse "
     "Mary Anne/Ann McAvoy), parentage conflict unresolved, needs a primary record."),
    ("I270055047514", "I270069114463",
     "Alternate source (merged duplicate I270069114463) spelled parents as George Smyth + Sarah "
     "Smyth rather than George Smith + Sarah Ann Bourne — same person (matching birth/death dates), "
     "minor spelling variant most likely, not flagged as a real conflict."),
    ("I270066601463", "I270066600806", None),
    ("I270067842704", "I270066977312", None),
    ("I270066977536", "I270067844405",
     "Alternate source (merged duplicate I270067844405) claimed parents as Hans Wymann + Barbara "
     "Von Rufs instead of Conrad Wymann + Anna Brunner — same person (matching birth/death dates/"
     "places), parentage conflict unresolved, needs a primary record."),
    ("I270067826251", "I270067844730", None),
]

shutil.copy(HERE_DATA, HERE_DATA + ".bak-dupmerge-" + TODAY)

for keep, drop, note in decisions:
    if note:
        P[drop].setdefault("notes", []).append("[Duplicate-merge review 2026-09-16] " + note)
    print("merging", P[drop]["name"], drop, "into", P[keep]["name"], keep)

merge_people(P, F, [(k, dr) for k, dr, _ in decisions])

bl = broken_links(P, F)
if bl:
    raise SystemExit(f"ABORT: {bl} broken links after merge - not saved.")

d.setdefault("meta", {}).setdefault("stats", {})
d["meta"]["stats"]["individuals"] = len(P)
d["meta"]["stats"]["families"] = len(F)

tmp = HERE_DATA + ".tmp"
json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
if len(json.load(open(tmp, encoding="utf-8"))["people"]) != len(P):
    raise SystemExit("verification failed, not saved")
import os
os.replace(tmp, HERE_DATA)
print("Saved. People now:", len(P))
