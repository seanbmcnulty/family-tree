#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
enhance_library.py - run on YOUR machine.

Cleans the family document library and weaves it into the tree:
  1. decodes HTML entities (&amp; &#39; ...) in titles/text,
  2. tidies vague/duplicate titles and MERGES near-duplicate documents,
  3. tags every document with a category (military, obituary, census, land,
     immigration, church, heraldry, newspaper, biography, ...),
  4. LINKS the orphaned documents (currently attached to nobody) to the right
     people by matching names + years, so they finally appear on those profiles,
  5. prints a MILITARY AUDIT (the exact shape of your `military` records + what
     military evidence exists) so the military-tab upgrade can be built precisely,
  6. rebuilds index.html (+ site/ + mcnulty-tree-website/) with the cleaned library.

Reads the current library straight out of index.html - no separate file needed.
People come from the authoritative family-data.json. Backups written first;
aborts on any broken link. Every merge and link is written to library_report.txt.

  python enhance_library.py            # do it
  python enhance_library.py --no-link  # clean only, don't auto-link orphans
"""
import json, os, re, html, shutil, datetime, argparse
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
DATA = os.path.join(ROOT, "family-data.json")
INDEX = os.path.join(ROOT, "index.html")
TARGETS = [os.path.join(ROOT, "index.html"),
           os.path.join(ROOT, "site", "index.html"),
           os.path.join(ROOT, "mcnulty-tree-website", "index.html")]
TODAY = datetime.date.today().isoformat()
report = []
def log(m): report.append(m); print(m)

# ---------- blob extraction (string-aware brace/bracket matcher) ----------
def find_blob(text, varname, required=True):
    m = re.search(r"const %s\s*=\s*" % re.escape(varname), text)
    if not m:
        if required: raise SystemExit("Could not find 'const %s =' in index.html" % varname)
        return None, None
    i = m.end(); open_c = text[i]; close_c = {"{":"}", "[":"]"}[open_c]
    depth = 0; instr = False; esc = False; j = i
    while j < len(text):
        c = text[j]
        if instr:
            if esc: esc = False
            elif c == "\\": esc = True
            elif c == '"': instr = False
        else:
            if c == '"': instr = True
            elif c == open_c: depth += 1
            elif c == close_c:
                depth -= 1
                if depth == 0: break
        j += 1
    return i, j + 1              # [start,end) of the literal

# ---------- text helpers ----------
def dec(s):
    if not isinstance(s, str): return s
    return re.sub(r"\s+\n", "\n", html.unescape(s)).strip()

def tidy_title(t):
    t = html.unescape(t or "").strip()
    t = re.sub(r"\.(html?|htm)$", "", t, flags=re.I)
    t = re.sub(r"\s{2,}", " ", t).strip(" -")
    return t

VAGUE = {"bio","biography","biografie","rev","history","declaration","census records",
         "christening","arms and crest","biographical facts","book sources","obituary",
         "note","notes","email","document","bio of c","capt., dr","biography - fag"}

CATS = [("military", r"regiment|batt(alion|le)|\barmy\b|\bnavy\b|soldier|veteran|enlist|militia|loyalist|\bwar\b|discharge|flying officer|cavalry|infantry|air force"),
        ("obituary", r"obituar|in memoriam|death notice|passed away|funeral|interred"),
        ("census",   r"\bcensus\b"),
        ("immigration", r"immigrat|emigrat|passenger|steamship|\bship\b|arrived in|port of"),
        ("land",     r"land grant|\bdeed\b|homestead|petition|acres|land record"),
        ("church",   r"baptis|christen|\bparish\b|communion|marriage record|register of"),
        ("heraldry", r"coat of arms|\bcrest\b|heraldic|armorial|blazon"),
        ("newspaper",r"transcript|gazette|\bherald\b|\btimes\b|chronicle|newspaper"),
        ("biography",r"\bbio\b|biograph|life of|history of|\bstory\b|was born|born in"),]
def categorize(doc):
    blob = (doc.get("t","") + " " + doc.get("x","")[:1200]).lower()
    for name, rx in CATS:
        if re.search(rx, blob): return name
    return "record"

def norm_name(s):
    return re.sub(r"[^a-z ]", "", (s or "").lower())
def norm_key(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-link", action="store_true")
    args = ap.parse_args()

    d = json.load(open(DATA, encoding="utf-8")); P, F = d["people"], d["families"]
    libpath = os.path.join(ROOT, "library.json")
    if os.path.exists(libpath):
        LIB = json.load(open(libpath, encoding="utf-8"))      # pristine / canonical source
        log("Loaded library from library.json.")
    else:
        htmltext = open(INDEX, encoding="utf-8").read()
        ls, le = find_blob(htmltext, "LIBRARY")
        LIB = json.loads(htmltext[ls:le])
        log("Loaded library from index.html.")
    log("Loaded %d people and %d library documents." % (len(P), len(LIB)))
    shutil.copy(DATA, DATA + ".bak-lib-" + TODAY)

    # 1. clean fields + categorize
    for doc in LIB:
        doc["t"] = tidy_title(doc.get("t",""))
        doc["x"] = dec(doc.get("x",""))
        if "f" in doc: doc["f"] = html.unescape(doc["f"])
        doc["cat"] = categorize(doc)
        doc.setdefault("p", [])

    # 2. merge near-duplicate docs (same normalized title + shared person or text overlap)
    groups = defaultdict(list)
    for doc in LIB: groups[norm_key(doc["t"])].append(doc)
    merged_ids = set(); merges = 0
    for k, docs in groups.items():
        if len(docs) < 2 or not k: continue
        docs.sort(key=lambda x: len(x.get("x","")), reverse=True)
        keep = docs[0]
        for dup in docs[1:]:
            a, b = set(keep.get("p",[])), set(dup.get("p",[]))
            overlap = a & b
            short = min(len(keep["x"]), len(dup["x"]))
            textsim = short and keep["x"][:200].lower() == dup["x"][:200].lower()
            if overlap or textsim or short < 40:
                keep["p"] = list(dict.fromkeys(keep.get("p",[]) + dup.get("p",[])))
                merged_ids.add(dup["id"]); merges += 1
                log("  merged doc %s '%s' into %s" % (dup["id"], dup["t"][:40], keep["id"]))
    LIB = [doc for doc in LIB if doc["id"] not in merged_ids]

    # 3. improve vague titles using the linked person
    for doc in LIB:
        if doc["t"].lower() in VAGUE or len(doc["t"]) < 4:
            names = [P[pid]["name"] for pid in doc.get("p",[]) if pid in P]
            if len(names) == 1:
                doc["t"] = "%s — %s" % (names[0], doc["t"]) if doc["t"] else names[0]

    # 4. link orphans by name + year (conservative)
    linked = 0
    by_full = defaultdict(list); by_sy = defaultdict(list)
    anc_by_surname = defaultdict(list)
    for pid, p in P.items():
        by_full[norm_name(p.get("name"))].append(pid)
        sn = norm_name(p.get("surname")); y = (p.get("birth") or {}).get("year")
        if sn and y: by_sy[(sn, y)].append(pid)
        if sn and p.get("directAncestor"): anc_by_surname[sn].append(pid)
    namepat = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z'.]+){1,3})\b")
    yearpat = re.compile(r"\b(1[5-9]\d\d|20\d\d)\b")
    fam_title = re.compile(r"^(?:the\s+)?([A-Z][a-z]+)\s+Family\b", re.I)
    if not args.no_link:
        for doc in LIB:
            if doc.get("p"): continue
            cands, why = [], ""
            tkey = norm_name(doc["t"])
            head = doc["t"]                       # only trust names in the TITLE (high precision)
            years = [int(y) for y in yearpat.findall(doc["t"] + " " + doc["x"][:200])]
            if tkey in by_full and len(by_full[tkey]) == 1:
                cands, why = by_full[tkey], "title=name"
            elif fam_title.match(doc["t"]):                       # "Brooks Family" -> Brooks ancestors
                sn = norm_name(fam_title.match(doc["t"]).group(1))
                if anc_by_surname.get(sn):
                    cands, why = anc_by_surname[sn][:5], "surname-of-ancestors"
            if not cands:                                          # unique name in text
                seen = set()
                for nm in namepat.findall(head)[:10]:
                    nk = norm_name(nm)
                    if nk in seen: continue
                    seen.add(nk)
                    if nk in by_full and len(by_full[nk]) == 1:
                        cands.append(by_full[nk][0]); why = "name-in-text"
                cands = list(dict.fromkeys(cands))[:4]
            if not cands:                                          # surname + year in text
                for nm in namepat.findall(head)[:10]:
                    toks = norm_name(nm).split()
                    if len(toks) < 2: continue
                    sn = toks[-1]
                    for y in years:
                        for yy in (y, y-1, y+1):
                            if (sn, yy) in by_sy and len(by_sy[(sn, yy)]) == 1:
                                cands.append(by_sy[(sn, yy)][0]); why = "surname+year"
                cands = list(dict.fromkeys(cands))[:4]
            if cands:
                doc["p"] = cands; linked += 1
                log("  linked orphan %s '%s' -> %s [%s]" % (
                    doc["id"], doc["t"][:34], ", ".join(P[c]["name"] for c in cands if c in P), why))

    # 5. military incorporation (conservative): flag people the evidence supports,
    #    so they appear in the Military Service tab. Two safe sources:
    #    (a) a military-category library doc whose text mentions the person's surname
    #        within 120 chars of a real service term; (b) the person's own records
    #        explicitly naming enlistment/regiment/discharge.
    STRONG = re.compile(r"enlist|regiment|battalion|discharged?|veteran|militia|expeditionary|"
                        r"\bR\.?A\.?F\b|infantry|cavalry|war service|served (?:in|with) the|"
                        r"first world war|second world war|\bWWI\b|\bWWII\b|loyalist", re.I)
    mil_flagged = mil_events = 0
    for doc in LIB:
        if doc.get("cat") != "military": continue
        low = doc.get("x", "").lower()
        for pid in doc.get("p", []):
            p = P.get(pid);
            if not p: continue
            sn = norm_name(p.get("surname"))
            if not sn: continue
            near = False
            for mm in STRONG.finditer(low):
                a = max(0, mm.start()-120); b = min(len(low), mm.end()+120)
                if sn in low[a:b]: near = True; break
            if not near: continue
            if not p.get("military"): p["military"] = True; mil_flagged += 1
            evs = p.setdefault("events", [])
            if not any(ev.get("type") == "military" and doc["t"] in str(ev.get("label","")) for ev in evs):
                evs.append({"type": "military",
                            "label": "Military service - see '%s' in the family archive" % doc["t"]})
                mil_events += 1
    for pid, p in P.items():
        blob = " ".join(str(e.get("fact",""))+" "+str(e.get("detail","")) for e in p.get("webEnrichment",[]))
        if STRONG.search(blob) and not p.get("military"):
            p["military"] = True; mil_flagged += 1
    if mil_flagged or mil_events:
        log("Military incorporation: flagged %d new people, added %d military notes." % (mil_flagged, mil_events))

    # 6. military audit (read-only; informs any further build)
    mil_people = [pid for pid,p in P.items() if p.get("military")]
    log("\n=== MILITARY AUDIT ===")
    log("people with a `military` field: %d" % len(mil_people))
    for pid in mil_people[:3]:
        log("  schema sample %s: %s" % (pid, json.dumps(P[pid]["military"], ensure_ascii=False)[:240]))
    MILRX = re.compile(r"milit|soldier|regiment|battalion|enlist|\barmy\b|\bnavy\b|air force|veteran|discharge|\bwar\b|loyalist", re.I)
    fs_mil = sum(1 for p in P.values() for e in p.get("webEnrichment",[])
                 if MILRX.search(str(e.get("fact",""))+" "+str(e.get("detail",""))))
    log("FamilySearch/web records mentioning military terms: %d" % fs_mil)
    milcat = [doc for doc in LIB if doc["cat"] == "military"]
    log("library docs categorized 'military': %d (%d now linked to people)"
        % (len(milcat), sum(1 for doc in milcat if doc.get("p"))))

    # category summary
    cc = Counter(doc["cat"] for doc in LIB)
    log("\nLibrary categories: " + ", ".join("%s=%d" % (k,v) for k,v in cc.most_common()))
    still_orphan = sum(1 for doc in LIB if not doc.get("p"))
    log("Docs merged: %d | orphans linked: %d | still unlinked: %d | total docs now: %d"
        % (merges, linked, still_orphan, len(LIB)))

    # 6. validate people links unchanged & save
    broken = sum(1 for pid,p in P.items() if p.get("famc") and p["famc"] not in F) \
           + sum(1 for fa in F.values() for x in [fa.get("husband"),fa.get("wife")]+fa.get("children",[]) if x and x not in P)
    if broken: raise SystemExit("ABORT: %d broken links; nothing saved." % broken)
    # drop any doc.p that point at unknown people
    for doc in LIB:
        doc["p"] = [pid for pid in doc.get("p",[]) if pid in P]

    def atomic_write(path, text):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text); fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp, path)

    data_min = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
    lib_min = json.dumps(LIB, ensure_ascii=False, separators=(",", ":"))

    # persist the source of truth: family-data.json (military flags/events) + a cleaned library.json
    if len(json.loads(data_min)["people"]) != len(P):
        raise SystemExit("Save verification failed; nothing written (backup intact).")
    atomic_write(DATA, data_min)
    atomic_write(os.path.join(ROOT, "library.json"), json.dumps(LIB, ensure_ascii=False))
    log("Saved family-data.json (%d people; military flags/events persisted) and library.json." % len(P))

    built = 0
    for tgt in TARGETS:
        if not os.path.exists(tgt): continue
        t = open(tgt, encoding="utf-8").read()
        di, dj = find_blob(t, "DATA", required=False)
        if di is None:
            log("  ! %s has no DATA block - skipped" % os.path.relpath(tgt, ROOT)); continue
        t = t[:di] + data_min + t[dj:]
        li, lj = find_blob(t, "LIBRARY", required=False)
        if li is not None:
            t = t[:li] + lib_min + t[lj:]
        else:
            log("  (note) %s has no LIBRARY block - updated its data only" % os.path.relpath(tgt, ROOT))
        atomic_write(tgt, t); built += 1
        log("Rebuilt " + os.path.relpath(tgt, ROOT))

    open(os.path.join(ROOT, "library_report.txt"), "w", encoding="utf-8").write("\n".join(report))
    print("\nDone. Rebuilt %d site file(s). Report: library_report.txt  Backup: family-data.json.bak-lib-%s" % (built, TODAY))

if __name__ == "__main__":
    main()
