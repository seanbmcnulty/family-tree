#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_descendancy.py - add the collateral relatives you ACCEPTED
(fs_descendancy_accepted.json) into the tree. ADD-only, backed up, validated.

Linking rules (never touches an existing link):
  - a CHILD of an anchor joins the anchor's existing family when the anchor has
    exactly one, otherwise a new family is created with just the anchor as parent
  - a SPOUSE gets a new family with their partner (if the partner was accepted
    too or already exists); otherwise they are added unlinked and flagged
  - a GRANDCHILD attaches to its parent the same way (the parent must exist in
    the tree or be among the accepted rows - otherwise the row is skipped)
Every new person carries a webEnrichment note with the FamilySearch link, and a
'provisional' badge note so the app shows where they came from.
"""
import json, os, glob, datetime
import fs_common as C


def find_accepted():
    local = os.path.join(C.HERE, "fs_descendancy_accepted.json")
    if os.path.exists(local):
        return local
    dl = os.path.join(os.path.expanduser("~"), "Downloads")
    cands = sorted(glob.glob(os.path.join(dl, "fs_descendancy_accepted*.json")),
                   key=os.path.getmtime, reverse=True)
    return cands[0] if cands else local


def new_ids(P, F):
    n = [1]
    def pid():
        while ("FSC%04d" % n[0]) in P: n[0] += 1
        v = "FSC%04d" % n[0]; n[0] += 1; return v
    m = [1]
    def fid():
        while ("FFC%04d" % m[0]) in F: m[0] += 1
        v = "FFC%04d" % m[0]; m[0] += 1; return v
    return pid, fid


def person_record(r, generation):
    p = {"id": None, "name": r["name"], "sex": {"MALE": "M", "FEMALE": "F"}.get(r.get("gender"), ""),
         "given": r.get("given") or "", "surname": r.get("surname") or "",
         "fams": [], "connected": True, "directAncestor": False,
         "collateral": True,
         "webEnrichment": [{
             "fact": "Added from FamilySearch descendancy of %s (%s) - %s. Verify before treating as proven."
                     % (r.get("anchor_name"), r.get("anchor_fs"), r.get("relation")),
             "source": {"url": "https://www.familysearch.org/tree/person/details/" + r["fs_id"],
                        "title": "FamilySearch person " + r["fs_id"]},
             "added": C.TODAY, "confidence": "provisional"}]}
    if generation is not None:
        p["generation"] = generation
    if r.get("birth_year"):
        p["birth"] = {"year": r["birth_year"], "date": str(r["birth_year"])}
        if r.get("birth_place"):
            p["birth"]["place"] = r["birth_place"]
    if r.get("death_year"):
        p["death"] = {"year": r["death_year"], "date": str(r["death_year"])}
    return p


def family_of_parent(parent_pid, P, F, newfid):
    """Family to attach a child to: the parent's only family, else a new one."""
    fams = (P.get(parent_pid) or {}).get("fams") or []
    if len(fams) == 1 and fams[0] in F:
        return fams[0], False
    fid = newfid()
    sex = (P.get(parent_pid) or {}).get("sex")
    F[fid] = {"id": fid, "children": [],
              ("husband" if sex == "M" else "wife"): parent_pid}
    P[parent_pid].setdefault("fams", []).append(fid)
    return fid, True


def main():
    acc_path = find_accepted()
    if not os.path.exists(acc_path):
        raise SystemExit("No fs_descendancy_accepted.json - export it from fs_descendancy_review.html first.")
    accepted = json.load(open(acc_path, encoding="utf-8"))
    # children before grandchildren before spouses (so parents/partners exist first)
    accepted.sort(key=lambda r: (r["dnum"].count("."), r["dnum"].endswith("-S")))

    d, P, F = C.load_data()
    bak = C.backup_data("cousins")
    print("Backed up data file -> %s" % os.path.basename(bak))
    newpid, newfid = new_ids(P, F)

    fs2pid = {}   # fs ids resolved this run (accepted rows + pre-existing anchors)
    for pid_, p_ in P.items():
        for we in p_.get("webEnrichment") or []:
            m = C.FS_URL_RE.search(((we.get("source") or {}).get("url")) or "")
            if m:
                fs2pid.setdefault(m.group(1), pid_)

    added = linked = skipped = 0
    unlinked = []
    for r in accepted:
        if r["fs_id"] in fs2pid:
            skipped += 1
            continue
        anchor_gen = (P.get(r["anchor_pid"]) or {}).get("generation")
        depth = r["dnum"].rstrip("-S").count(".")
        gen = (anchor_gen - depth) if isinstance(anchor_gen, int) else None
        pid = newpid()
        rec = person_record(r, gen)
        rec["id"] = pid
        P[pid] = rec
        fs2pid[r["fs_id"]] = pid
        added += 1

        if r["dnum"].endswith("-S"):
            # spouse: try to find the partner (same dnum without -S)
            partner_fs = None
            for other in accepted:
                if other["dnum"] == r["dnum"][:-2] and other["anchor_fs"] == r["anchor_fs"]:
                    partner_fs = other["fs_id"]
                    break
            partner_pid = fs2pid.get(partner_fs) or r.get("parent_pid")
            if partner_pid and partner_pid in P:
                fid = newfid()
                slot = "husband" if rec["sex"] == "M" else "wife"
                other_slot = "wife" if slot == "husband" else "husband"
                F[fid] = {"id": fid, "children": [], slot: pid, other_slot: partner_pid}
                P[pid]["fams"].append(fid)
                P[partner_pid].setdefault("fams", []).append(fid)
                linked += 1
            else:
                unlinked.append(rec["name"])
        else:
            parent_pid = r.get("parent_pid") or fs2pid.get(r.get("parent_fs")) \
                         or (r["anchor_pid"] if "." not in r["dnum"][2:] else None)
            if r["dnum"].count(".") == 1:
                parent_pid = parent_pid or r["anchor_pid"]
            if parent_pid and parent_pid in P:
                fid, created = family_of_parent(parent_pid, P, F, newfid)
                if pid not in F[fid].setdefault("children", []):
                    F[fid]["children"].append(pid)
                P[pid]["famc"] = fid
                linked += 1
            else:
                unlinked.append(rec["name"])

    # validation: every reference must resolve
    bad = []
    for pid, p in P.items():
        if p.get("famc") and p["famc"] not in F:
            bad.append((pid, "famc", p["famc"]))
        for f in p.get("fams") or []:
            if f not in F:
                bad.append((pid, "fams", f))
    for fid, f in F.items():
        for role in ("husband", "wife"):
            if f.get(role) and f[role] not in P:
                bad.append((fid, role, f[role]))
        for c in f.get("children") or []:
            if c not in P:
                bad.append((fid, "child", c))
    if bad:
        print("VALIDATION FAILED - not saving. Broken refs: %s" % bad[:10])
        raise SystemExit("Data untouched; backup remains at " + bak)

    C.save_data(d)
    for t in C.INDEX_TARGETS:
        C.backup_html(t, "cousins-" + C.TODAY)
    done = C.reinject_all(d)
    print("Added %d people (%d linked into families, %d skipped as already present)."
          % (added, linked, skipped))
    if unlinked:
        print("Added but not linked (no parent/partner in tree): %s" % ", ".join(unlinked[:12]))
    print("Data re-injected into: %s" % ", ".join(os.path.relpath(t, C.ROOT) for t in done))


if __name__ == "__main__":
    main()
