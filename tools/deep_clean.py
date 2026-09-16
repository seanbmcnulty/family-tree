#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
deep_clean.py - run on YOUR machine. Thorough integrity cleanup + rebuild.

Fixes every flagged data error by correcting the offending DATE (never by cutting
a family link, so real branches stay attached), and removes the fragments that
aren't part of your tree:

  * parent shown as born AFTER a child (or under 13/14) -> clear the outlier birth year
  * child born after a parent's death                   -> clear that parent's death year
  * impossible lifespan (>110 yrs) or death before birth-> clear the death year
  * placeholder junk people (e.g. named "?")            -> remove
  * people not connected to your tree at all            -> remove (with their empty families)

Backs up family-data.json first, aborts on any broken link, writes every change to
deep_clean_report.txt, then rebuilds index.html (+ site/ + mcnulty-tree-website/).

  python deep_clean.py
"""
import json, os, re, shutil, datetime
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
DATA = os.path.join(ROOT, "family-data.json")
LIBJSON = os.path.join(ROOT, "library.json")
TARGETS = [os.path.join(ROOT, "index.html"), os.path.join(ROOT, "site", "index.html"),
           os.path.join(ROOT, "mcnulty-tree-website", "index.html")]
TODAY = datetime.date.today().isoformat()
report = []
def log(m): report.append(m)

by = lambda p: (p.get("birth") or {}).get("year")
dy = lambda p: (p.get("death") or {}).get("year")
def clr_birth(p):
    if p.get("birth"):
        p["birth"].pop("year", None)
        if not p["birth"]: p.pop("birth", None)
def clr_death(p):
    if p.get("death"):
        p["death"].pop("year", None)
        if not p["death"]: p.pop("death", None)

def find_blob(text, varname, required=True):
    m = re.search(r"const %s\s*=\s*" % re.escape(varname), text)
    if not m:
        if required: raise SystemExit("Could not find 'const %s =' in a site file." % varname)
        return None, None
    i = m.end(); oc = text[i]; cc = {"{":"}", "[":"]"}[oc]
    depth = 0; instr = False; esc = False; j = i
    while j < len(text):
        c = text[j]
        if instr:
            if esc: esc = False
            elif c == "\\": esc = True
            elif c == '"': instr = False
        else:
            if c == '"': instr = True
            elif c == oc: depth += 1
            elif c == cc:
                depth -= 1
                if depth == 0: break
        j += 1
    return i, j + 1

def atomic_write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text); fh.flush(); os.fsync(fh.fileno())
    os.replace(tmp, path)

def main():
    d = json.load(open(DATA, encoding="utf-8")); P, F = d["people"], d["families"]
    n0, f0 = len(P), len(F)
    log("Loaded %d people, %d families." % (n0, f0))
    shutil.copy(DATA, DATA + ".bak-deepclean-" + TODAY)
    counts = defaultdict(int)

    # 1. impossible parent age -> clear the outlier birth year
    for f in F.values():
        kids = [c for c in f.get("children", []) if c in P]
        for slot in ("husband", "wife"):
            par = f.get(slot)
            if not par or par not in P: continue
            pby = by(P[par])
            if pby is None: continue
            minage = 13 if slot == "wife" else 14
            dated = [c for c in kids if by(P[c]) is not None]
            bad = [c for c in dated if (by(P[c]) - pby) < minage]
            if not bad: continue
            if len(bad) == len(dated):
                log("  cleared birth year %s of %s (born after own children)" % (pby, P[par]["name"]))
                clr_birth(P[par]); counts["parent birth-year cleared"] += 1
            else:
                for c in bad:
                    log("  cleared birth year %s of %s (impossible vs parent %s)" % (by(P[c]), P[c]["name"], P[par]["name"]))
                    clr_birth(P[c]); counts["child birth-year cleared"] += 1

    # 2. children born after a parent's death -> clear that death year
    for f in F.values():
        dated = [c for c in f.get("children", []) if c in P and by(P[c]) is not None]
        for slot, grace in (("wife", 0), ("husband", 1)):
            par = f.get(slot)
            if not par or par not in P: continue
            pdy = dy(P[par])
            if pdy and any(by(P[c]) - pdy > grace for c in dated):
                log("  cleared death year %s of %s (had children born after)" % (pdy, P[par]["name"]))
                clr_death(P[par]); counts["death-year cleared (post-death kids)"] += 1

    # 3. impossible lifespan / death before birth -> clear death year
    for p in P.values():
        b, dd = by(p), dy(p)
        if b and dd and (dd < b or dd - b > 110):
            log("  cleared death year %s of %s (b.%s, implausible)" % (dd, p["name"], b))
            clr_death(p); counts["death-year cleared (lifespan)"] += 1

    # 4. remove junk + people not connected to P1
    junk = set(pid for pid, p in P.items()
               if not (p.get("name") or "").strip() or re.fullmatch(r"[\?\_\s]+", p.get("name", "") or ""))
    adj = defaultdict(set)
    for f in F.values():
        mem = [x for x in [f.get("husband"), f.get("wife")] + f.get("children", []) if x in P]
        for i, x in enumerate(mem):
            for y in mem[i+1:]: adj[x].add(y); adj[y].add(x)
    root = "P1" if "P1" in P else next(iter(P))
    seen = {root}; st = [root]
    while st:
        c = st.pop()
        for nb in adj[c]:
            if nb not in seen: seen.add(nb); st.append(nb)
    to_remove = [pid for pid in P if pid in junk or pid not in seen]
    for pid in to_remove:
        nm = P[pid].get("name", pid)
        for f in F.values():
            for s in ("husband", "wife"):
                if f.get(s) == pid: f[s] = None
            if pid in f.get("children", []): f["children"] = [x for x in f["children"] if x != pid]
        del P[pid]; counts["removed (disconnected/junk)"] += 1
        if counts["removed (disconnected/junk)"] <= 60: log("  removed %s (%s)" % (nm, pid))

    # 5. drop degenerate families (no parents and <=1 child) and integrity sweep
    for fid in list(F):
        f = F[fid]
        par = [x for x in [f.get("husband"), f.get("wife")] if x in P]
        ch = [c for c in f.get("children", []) if c in P]
        if not par and len(ch) <= 1:
            for c in ch:
                if P[c].get("famc") == fid: P[c]["famc"] = None
            del F[fid]; counts["degenerate family removed"] += 1
    for pid, p in P.items():
        if p.get("famc") and p["famc"] not in F: p["famc"] = None
        p["fams"] = [x for x in p.get("fams", []) if x in F]
    for f in F.values():
        for s in ("husband", "wife"):
            if f.get(s) and f[s] not in P: f[s] = None
        f["children"] = [c for c in f.get("children", []) if c in P]

    # 6. recompute generations / directAncestor / connected
    gen = {root: 0}; fr = [root]; anc = set()
    while fr:
        nx = []
        for pid in fr:
            fa = F.get((P.get(pid) or {}).get("famc"))
            if not fa: continue
            for pr in (fa.get("husband"), fa.get("wife")):
                if pr and pr in P and pr not in gen:
                    gen[pr] = gen[pid] + 1; anc.add(pr); nx.append(pr)
        fr = nx
    adj = defaultdict(set)
    for f in F.values():
        mem = [x for x in [f.get("husband"), f.get("wife")] + f.get("children", []) if x in P]
        for i, x in enumerate(mem):
            for y in mem[i+1:]: adj[x].add(y); adj[y].add(x)
    seen = {root}; st = [root]
    while st:
        c = st.pop()
        for nb in adj[c]:
            if nb not in seen: seen.add(nb); st.append(nb)
    for pid, p in P.items():
        if pid in gen: p["generation"] = gen[pid]
        else: p.pop("generation", None)
        p["directAncestor"] = pid in anc or pid == root
        p["connected"] = pid in seen

    broken = sum(1 for pid,p in P.items() if p.get("famc") and p["famc"] not in F) \
           + sum(1 for p in P.values() for x in p.get("fams",[]) if x not in F) \
           + sum(1 for f in F.values() for x in [f.get("husband"),f.get("wife")]+f.get("children",[]) if x and x not in P)
    if broken: raise SystemExit("ABORT: %d broken links; nothing saved (backup intact)." % broken)

    d.setdefault("meta", {}).setdefault("stats", {})
    d["meta"]["stats"]["individuals"] = len(P)
    d["meta"]["stats"]["families"] = len(F)
    d["meta"]["stats"]["directAncestors"] = len(anc)

    # library: drop links to removed people
    LIB = None
    if os.path.exists(LIBJSON):
        LIB = json.load(open(LIBJSON, encoding="utf-8"))
        for doc in LIB:
            doc["p"] = [pid for pid in doc.get("p", []) if pid in P]

    data_min = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
    if len(json.loads(data_min)["people"]) != len(P):
        raise SystemExit("Save verification failed; nothing written.")
    atomic_write(DATA, data_min)
    if LIB is not None: atomic_write(LIBJSON, json.dumps(LIB, ensure_ascii=False))
    lib_min = json.dumps(LIB, ensure_ascii=False, separators=(",", ":")) if LIB is not None else None

    built = 0
    for tgt in TARGETS:
        if not os.path.exists(tgt): continue
        t = open(tgt, encoding="utf-8").read()
        di, dj = find_blob(t, "DATA", required=False)
        if di is None:
            log("  ! %s has no DATA block - skipped" % os.path.relpath(tgt, ROOT)); continue
        t = t[:di] + data_min + t[dj:]
        if lib_min is not None:
            li, lj = find_blob(t, "LIBRARY", required=False)
            if li is not None: t = t[:li] + lib_min + t[lj:]
        atomic_write(tgt, t); built += 1
        log("Rebuilt " + os.path.relpath(tgt, ROOT))

    log("")
    log("SUMMARY: %d -> %d people (removed %d, %.1f%%), %d -> %d families."
        % (n0, len(P), n0 - len(P), 100*(n0-len(P))/n0, f0, len(F)))
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        log("  %-34s %d" % (k, v))
    open(os.path.join(ROOT, "deep_clean_report.txt"), "w", encoding="utf-8").write("\n".join(report))
    print("\n".join(l for l in report if l.startswith("SUMMARY") or l.startswith("  ") and not l.startswith("  cleared") and not l.startswith("  removed") or l.startswith("Rebuilt")))
    print("\nDone. Rebuilt %d site file(s). Full detail: deep_clean_report.txt. Backup: family-data.json.bak-deepclean-%s" % (built, TODAY))

if __name__ == "__main__":
    main()
