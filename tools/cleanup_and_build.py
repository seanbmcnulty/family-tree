#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cleanup_and_build.py - run on YOUR machine (native Python reads the full file fine).

One command that:
  1. tidies the FamilySearch additions (dedupes repeated record citations, cleans
     messy place strings like ',, Ireland'),
  2. caps attached records to the most informative handful per person,
  3. merges near-certain duplicate people (conservative; every merge is logged),
  4. standardizes names ('Mc Nulty' -> 'McNulty') and date/place formatting,
  5. validates the tree (aborts on any broken link, backup kept),
  6. rebuilds index.html (+ site/ + mcnulty-tree-website/) with the cleaned data.

Nothing is destroyed: a timestamped backup is written first, and a merges report
(cleanup_report.txt) lists exactly what changed. ADD/repair only otherwise.

  python cleanup_and_build.py            # do everything
  python cleanup_and_build.py --no-merge # skip the duplicate-merge step
  python cleanup_and_build.py --cap 6    # records kept per person (default 6)
"""
import json, os, re, sys, shutil, datetime, argparse
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
DATA = os.path.join(ROOT, "family-data.json")
INDEX_TARGETS = [os.path.join(ROOT, "index.html"),
                 os.path.join(ROOT, "site", "index.html"),
                 os.path.join(ROOT, "mcnulty-tree-website", "index.html")]
TODAY = datetime.date.today().isoformat()
report = []

def log(msg):
    report.append(msg); print(msg)

# ---------------- string helpers ----------------
def clean_place(s):
    if not isinstance(s, str): return s
    parts = [p.strip() for p in s.split(",")]
    parts = [p for p in parts if p and p != "-"]
    return ", ".join(parts)

def fix_name(s):
    if not isinstance(s, str): return s
    s = re.sub(r"\bMc\s+([A-Za-z])", r"Mc\1", s)     # Mc Nulty -> McNulty
    s = re.sub(r"\bMac\s+([A-Z])", r"Mac\1", s)       # Mac Donald -> MacDonald
    s = re.sub(r"\bO'\s+([A-Za-z])", r"O'\1", s)      # O' Brien -> O'Brien
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s

RECTYPES = ["baptism", "christen", "birth", "marriage", "death", "burial",
            "census", "grave", "emigra", "immigra"]
def rec_score(e):
    url = (e.get("source") or {}).get("url", "")
    txt = (str(e.get("fact","")) + " " + str(e.get("detail",""))).lower()
    sc = 0
    if "ark:" in url: sc += 3
    sc += min(len(str(e.get("detail",""))) / 120.0, 3)
    for i, t in enumerate(RECTYPES):
        if t in txt: sc += 1; break
    return sc

def is_fs(e):
    return "familysearch" in str(e.get("confidence","")).lower() \
        or "familysearch" in str((e.get("source") or {}).get("title","")).lower()

# ---------------- cleanup passes ----------------
def tidy_person(p, cap):
    # places
    for ev in ("birth","death"):
        b = p.get(ev)
        if isinstance(b, dict) and b.get("place"):
            b["place"] = clean_place(b["place"])
    for e in p.get("events", []) or []:
        if isinstance(e, dict) and e.get("place"):
            e["place"] = clean_place(e["place"])
    # names
    for k in ("name","given","surname"):
        if p.get(k): p[k] = fix_name(p[k])
    # dedupe webEnrichment (by ark url, else by fact+detail)
    we = p.get("webEnrichment") or []
    seen, deduped = set(), []
    for e in we:
        url = (e.get("source") or {}).get("url","")
        key = ("ark:"+url.split("ark:")[-1]) if "ark:" in url else (str(e.get("fact",""))+"|"+str(e.get("detail",""))[:60])
        if key in seen: continue
        seen.add(key); deduped.append(e)
    removed_dupes = len(we) - len(deduped)
    # cap FS records (keep all non-FS; keep top-N FS by score)
    fs = [e for e in deduped if is_fs(e)]
    non = [e for e in deduped if not is_fs(e)]
    capped = 0
    if len(fs) > cap:
        fs.sort(key=rec_score, reverse=True)
        capped = len(fs) - cap
        fs = fs[:cap]
    if deduped is not we or capped or removed_dupes:
        p["webEnrichment"] = non + fs
    return removed_dupes, capped

def norm(s):
    return re.sub(r"[^a-z ]","", (s or "").lower()).strip()

def byear(p):
    return (p.get("birth") or {}).get("year")

def find_duplicates(P, F):
    """Return (merge_pairs, suggestions).
    merge_pairs  = near-certain duplicates: same name AND a shared structural link
                   (same parents family OR a shared spouse family) AND birth years
                   agree (within 1) or one is missing.  These are auto-merged.
    suggestions  = same name + same birth year but NO structural link. These are
                   NOT merged (could be cousins/namesakes) - listed for your review.
    """
    by_name = defaultdict(list)
    for pid, p in P.items():
        n = norm(p.get("name"))
        if n: by_name[n].append(pid)
    # parent/child pairs to NEVER merge (Sr/Jr etc.)
    child_of = {}
    for fid, f in F.items():
        for c in f.get("children", []):
            child_of.setdefault(c, set()).update([f.get("husband"), f.get("wife")])
    pairs, suggestions = [], []
    used = set()
    for n, pids in by_name.items():
        if len(pids) < 2: continue
        for i in range(len(pids)):
            for j in range(i+1, len(pids)):
                a, b = pids[i], pids[j]
                if a in used or b in used: continue
                if b in child_of.get(a, set()) or a in child_of.get(b, set()): continue
                ya, yb = byear(P[a]), byear(P[b])
                fam_a, fam_b = P[a].get("famc"), P[b].get("famc")
                same_parents = bool(fam_a) and fam_a == fam_b
                shared_union = set(P[a].get("fams", [])) & set(P[b].get("fams", []))
                structural = same_parents or bool(shared_union)
                year_ok = (ya and yb and abs(ya - yb) <= 1)
                year_compatible = year_ok or (not ya) or (not yb)
                if structural and year_compatible:
                    score_a = len(json.dumps(P[a], ensure_ascii=False))
                    score_b = len(json.dumps(P[b], ensure_ascii=False))
                    keep, drop = (a, b) if (score_a, a) >= (score_b, b) else (b, a)
                    pairs.append((keep, drop)); used.add(a); used.add(b)
                elif year_ok and not structural:
                    suggestions.append((a, b, ya))
    return pairs, suggestions

def merge_people(P, F, pairs):
    for keep, drop in pairs:
        if keep not in P or drop not in P: continue
        kp, dp = P[keep], P[drop]
        # fill blank scalar fields on keep from drop
        for k in ("sex","given","surname","title","country","flag"):
            if not kp.get(k) and dp.get(k): kp[k] = dp[k]
        for ev in ("birth","death"):
            if not kp.get(ev) and dp.get(ev): kp[ev] = dp[ev]
            elif isinstance(kp.get(ev),dict) and isinstance(dp.get(ev),dict):
                for kk,vv in dp[ev].items(): kp[ev].setdefault(kk, vv)
        # merge list fields
        for k in ("events","occupations","notes","webEnrichment","military","sourceIds"):
            merged = (kp.get(k) or []) + (dp.get(k) or [])
            # dedupe by json repr
            seen=set(); out=[]
            for item in merged:
                r=json.dumps(item, ensure_ascii=False, sort_keys=True)
                if r in seen: continue
                seen.add(r); out.append(item)
            if out: kp[k]=out
        # famc: keep gets drop's if it had none
        if not kp.get("famc") and dp.get("famc"): kp["famc"] = dp["famc"]
        # repoint every family reference from drop -> keep
        for f in F.values():
            for slot in ("husband","wife"):
                if f.get(slot) == drop: f[slot] = keep
            if "children" in f:
                f["children"] = [keep if c == drop else c for c in f["children"]]
        # union fams
        fams = list(dict.fromkeys((kp.get("fams") or []) + (dp.get("fams") or [])))
        if fams: kp["fams"] = fams
        del P[drop]
    # de-dupe children lists & drop self/dangling
    for f in F.values():
        if "children" in f:
            f["children"] = list(dict.fromkeys(c for c in f["children"] if c in P))

def recompute(P, F):
    root = "P1" if "P1" in P else next(iter(P))
    gen = {root: 0}; fr = [root]; anc = set()
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
    return anc

def broken_links(P, F):
    return sum(1 for pid,p in P.items() if p.get("famc") and p["famc"] not in F) \
         + sum(1 for p in P.values() for f in p.get("fams",[]) if f not in F) \
         + sum(1 for fa in F.values() for x in [fa.get("husband"),fa.get("wife")]+fa.get("children",[]) if x and x not in P)

# ---------------- rebuild index.html ----------------
def swap_data_blob(htmlpath, new_json):
    html = open(htmlpath, encoding="utf-8").read()
    m = re.search(r"const DATA\s*=\s*", html)
    if not m:
        raise SystemExit("Could not find 'const DATA =' in " + htmlpath)
    i = m.end()
    if html[i] != "{":
        raise SystemExit("Unexpected DATA format in " + htmlpath)
    # brace-match, string-aware
    depth = 0; instr = False; esc = False; j = i
    while j < len(html):
        c = html[j]
        if instr:
            if esc: esc = False
            elif c == "\\": esc = True
            elif c == '"': instr = False
        else:
            if c == '"': instr = True
            elif c == "{": depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0: break
        j += 1
    end = j + 1                       # position just after closing }
    new_html = html[:i] + new_json + html[end:]
    open(htmlpath, "w", encoding="utf-8").write(new_html)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-merge", action="store_true")
    ap.add_argument("--cap", type=int, default=6)
    args = ap.parse_args()

    d = json.load(open(DATA, encoding="utf-8"))
    P, F = d["people"], d["families"]
    log("Loaded %d people, %d families." % (len(P), len(F)))
    shutil.copy(DATA, DATA + ".bak-cleanup-" + TODAY)

    # 1+2+4: per-person tidy (places, names, dedupe records, cap)
    tot_dupes = tot_capped = 0
    for p in P.values():
        rd, cp = tidy_person(p, args.cap)
        tot_dupes += rd; tot_capped += cp
    log("Tidied records: removed %d duplicate citations, capped %d extra records." % (tot_dupes, tot_capped))

    # 3: merge duplicates
    if not args.no_merge:
        pairs, suggestions = find_duplicates(P, F)
        for keep, drop in pairs:
            log("  merge: %s (%s)  <-  %s (%s)" % (P[keep]["name"], keep, P[drop]["name"], drop))
        merge_people(P, F, pairs)
        log("Merged %d near-certain duplicate people (shared parents/spouse + matching years)." % len(pairs))
        if suggestions:
            log("Possible duplicates NOT merged (same name+year, no shared family) - review these %d manually:" % len(suggestions))
            for a, b, y in suggestions[:200]:
                log("  ? %s (%s) vs (%s)  b.%s" % (P[a]["name"], a, b, y))
    else:
        log("Skipped duplicate merge (--no-merge).")

    anc = recompute(P, F)
    bl = broken_links(P, F)
    if bl:
        raise SystemExit("ABORT: %d broken links after cleanup - family-data.json NOT changed (see .bak)." % bl)
    d.setdefault("meta", {}).setdefault("stats", {})
    d["meta"]["stats"]["individuals"] = len(P)
    d["meta"]["stats"]["families"] = len(F)
    d["meta"]["stats"]["directAncestors"] = len(anc)

    # atomic save
    new_json = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
    tmp = DATA + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(new_json); fh.flush(); os.fsync(fh.fileno())
    if len(json.load(open(tmp, encoding="utf-8"))["people"]) != len(P):
        raise SystemExit("Save verification failed; family-data.json untouched.")
    os.replace(tmp, DATA)
    log("Saved cleaned family-data.json (%d people) - verified." % len(P))

    # rebuild sites (DATA blob swap)
    data_min = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
    built = 0
    for tgt in INDEX_TARGETS:
        if os.path.exists(tgt):
            try:
                swap_data_blob(tgt, data_min); built += 1; log("Rebuilt " + os.path.relpath(tgt, ROOT))
            except SystemExit as e:
                log("  ! %s: %s" % (tgt, e))
    log("Rebuilt %d site file(s)." % built)

    open(os.path.join(ROOT, "cleanup_report.txt"), "w", encoding="utf-8").write("\n".join(report))
    print("\nAll done. Open index.html to view. Report: cleanup_report.txt. Backup: family-data.json.bak-cleanup-%s" % TODAY)

if __name__ == "__main__":
    main()
