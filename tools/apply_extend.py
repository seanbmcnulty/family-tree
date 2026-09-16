#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_extend.py - add the FamilySearch ancestors you accepted (fs_extend_accepted.json)
into the tree, linking each to its child. ADD-only, backed up, validated.

Never overwrites or deletes; only fills empty parent slots. Processes nearest
generations first so a new person exists before its own parent attaches.
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
ACC  = _find_accepted("fs_extend_accepted.json")

FLAG = {"MALE": ("M",), "FEMALE": ("F",)}

def main():
    if not os.path.exists(ACC):
        raise SystemExit("No fs_extend_accepted.json - export accepted rows from fs_extend_review.html first.")
    d = json.load(open(DATA, encoding="utf-8")); P, F = d["people"], d["families"]
    accepted = json.load(open(ACC, encoding="utf-8"))
    accepted.sort(key=lambda x: x.get("ahnen", 999))
    shutil.copy(DATA, DATA + ".bak-extend-" + datetime.date.today().isoformat())

    n = 1
    def newpid():
        nonlocal n
        while ("FS%04d" % n) in P: n += 1
        pid = "FS%04d" % n; n += 1; return pid
    fsid2pid = {}   # fs_id of a just-added person -> its new pid
    added = 0

    for a in accepted:
        child_ref = a["child_pid"]
        child_pid = fsid2pid.get(child_ref[4:]) if str(child_ref).startswith("NEW:") else child_ref
        if not child_pid or child_pid not in P:
            print("  ! skip %s: child not resolved (%s)" % (a["name"], child_ref)); continue
        role = a["role"]  # father | mother
        # get or create the child's parents-family
        fid = P[child_pid].get("famc")
        if not fid:
            fid = "F" + newpid()
            F[fid] = {"id": fid, "children": [child_pid]}
            P[child_pid]["famc"] = fid
        fam = F[fid]
        slot = "husband" if role == "father" else "wife"
        if fam.get(slot):
            print("  ! skip %s: %s slot already filled for %s" % (a["name"], slot, P[child_pid]["name"])); continue
        pid = newpid()
        sex = "M" if role == "father" else "F"
        person = {"id": pid, "name": a["name"],
                  "given": a.get("given") or a["name"].rsplit(" ", 1)[0],
                  "surname": a.get("surname") or (a["name"].rsplit(" ", 1)[-1] if " " in a["name"] else ""),
                  "sex": sex, "connected": True, "directAncestor": False}
        if a.get("birth_year") or a.get("birth_place"):
            b = {}
            if a.get("birth_year"): b["year"] = a["birth_year"]
            if a.get("birth_place"): b["place"] = a["birth_place"]
            person["birth"] = b
        if a.get("death_year"):
            person["death"] = {"year": a["death_year"]}
        person["fams"] = [fid]
        person["notes"] = ["Added from FamilySearch (person %s) as the %s of %s, filling a slot our tree left empty. Confirm sources on the FamilySearch profile before treating as fully proven. [FS-extend %s]"
                           % (a.get("fs_id"), role, P[child_pid]["name"], datetime.date.today().isoformat())]
        person["webEnrichment"] = [{"fact": "Ancestor supplied by a FamilySearch tree - see FS for sources.",
                                    "source": {"url": "https://www.familysearch.org/tree/person/details/" + str(a.get("fs_id")),
                                               "title": "FamilySearch person " + str(a.get("fs_id"))},
                                    "added": datetime.date.today().isoformat(), "confidence": "FamilySearch tree; verify"}]
        P[pid] = person
        fam[slot] = pid
        fsid2pid[a.get("fs_id")] = pid
        added += 1
        print("  + %s  ->  %s of %s" % (a["name"], role, P[child_pid]["name"]))

    # recompute generations / connectivity
    ROOT = "P1"; gen = {ROOT: 0}; fr = [ROOT]; anc = set()
    while fr:
        nx = []
        for pid in fr:
            fa = F.get((P.get(pid) or {}).get("famc"))
            if not fa: continue
            for par in (fa.get("husband"), fa.get("wife")):
                if par and par in P and par not in gen:
                    gen[par] = gen[pid] + 1; anc.add(par); nx.append(par)
        fr = nx
    adj = defaultdict(set)
    for fa in F.values():
        mem = [x for x in [fa.get("husband"), fa.get("wife")] + fa.get("children", []) if x and x in P]
        for i, x in enumerate(mem):
            for y in mem[i+1:]: adj[x].add(y); adj[y].add(x)
    seen = {ROOT}; st = [ROOT]
    while st:
        c = st.pop()
        for nb in adj[c]:
            if nb not in seen: seen.add(nb); st.append(nb)
    for pid, p in P.items():
        if pid in gen: p["generation"] = gen[pid]
        else: p.pop("generation", None)
        p["directAncestor"] = pid in anc or pid == ROOT
        p["connected"] = pid in seen

    broken = sum(1 for pid, p in P.items() if p.get("famc") and p["famc"] not in F) \
           + sum(1 for p in P.values() for f in p.get("fams", []) if f not in F) \
           + sum(1 for fa in F.values() for x in [fa.get("husband"), fa.get("wife")] + fa["children"] if x and x not in P)
    if broken:
        raise SystemExit("Aborting: %d broken links - restore the .bak file." % broken)
    d["meta"]["stats"]["individuals"] = len(P)
    d["meta"]["stats"]["directAncestors"] = len(anc)
    json.dump(d, open(DATA, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("\nAdded %d FamilySearch ancestors. Backup saved. Rebuild the site (or hand family-data.json to Claude)." % added)

if __name__ == "__main__":
    main()
