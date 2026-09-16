#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
add_jeon.py - run on YOUR machine. Adds Yumi's 30-generation Damyang Jeon paternal
line (from jeon_lineage.json) into family-data.json, linked above Yumi, then rebuilds.

- Finds Yumi in the tree (by Korean or romanized name).
- Builds her father (29세 Ho-yeol) -> grandfather (28세 Byeong-mun) -> ... -> founder
  (1세 Jeon Deuk-si) as a linked parent-child chain of ancestors.
- Adds the modern relatives with dates: mother, grandmother, brother, sister,
  uncle + his wife and children (cousins).
- Every added person carries: English name, Korean (ko), hanja, generation note,
  birth/death where known, a clan note, and origin=Korea (flag).
- ADD-only, backs up, aborts on broken links, rebuilds index.html (+ site copies).

  python add_jeon.py
"""
import json, os, re, shutil, datetime
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
DATA = os.path.join(ROOT, "family-data.json")
LIN = os.path.join(HERE, "jeon_lineage.json")
TARGETS = [os.path.join(ROOT, "index.html"), os.path.join(ROOT, "site", "index.html"),
           os.path.join(ROOT, "mcnulty-tree-website", "index.html")]
TODAY = datetime.date.today().isoformat()
log = []

JEON_EVENTS = {
 1: "Goryeo's cultural golden age of celadon and Buddhism; the 1126 Yi Ja-gyeom revolt shook the court.",
 2: "The 1170 military coup ended civilian rule, beginning Korea's century of military strongmen.",
 3: "The Choe military house seized power (1196), ruling Goryeo from behind the throne.",
 4: "The Mongol invasions of Korea began in 1231, opening decades of war.",
 5: "With Mongols ravaging the land, the court sheltered on Ganghwa Island and carved the Tripitaka Koreana.",
 6: "Goryeo submitted to the Mongol Yuan (1270); Korean troops joined the failed 1274 invasion of Japan.",
 7: "Goryeo endured as a Yuan son-in-law kingdom under Mongol overlordship.",
 8: "The Mongol Yuan weakened as reform-minded Goryeo kings sought greater autonomy.",
 9: "Red Turban invasions and relentless Japanese pirate raids battered a declining Goryeo.",
 10: "Yi Seong-gye founded the Joseon dynasty (1392) and moved the capital to Hanyang (Seoul).",
 11: "The celebrated golden reign of King Sejong the Great (1418-1450).",
 12: "Sejong's scholars created the Hangeul alphabet (1443); the 1453 coup brought King Sejo to power.",
 13: "King Seongjong completed the Gyeongguk Daejeon law code, cementing the Confucian state.",
 14: "The literati purges (sahwa) of 1498-1519 devastated reform-minded scholars.",
 15: "The age of the great Neo-Confucian philosophers Yi Hwang (Toegye) and Yi I (Yulgok).",
 16: "Court factions formed in 1575, beginning centuries of factional strife.",
 17: "The Imjin War (1592-98): Hideyoshi's invasions, repelled with Admiral Yi Sun-sin's navy and Jeolla's grain.",
 18: "The Manchu Qing invasion of 1636 forced King Injo's surrender.",
 19: "Recovery under King Hyeonjong amid the bitter 'ritual controversy' between factions.",
 20: "King Sukjong's turbulent reign of factional purges and slow economic revival.",
 21: "King Yeongjo (1724-76) launched the Tangpyeong policy against factionalism and eased taxes.",
 22: "Yeongjo's long reign; in 1762 he had his son, Prince Sado, sealed in a rice chest to die.",
 23: "King Jeongjo's enlightened reign - Silhak scholarship, Suwon fortress, and Catholicism's arrival (1784).",
 24: "The corrupt in-law (sedo) politics and harsh Catholic persecutions of the early 1800s.",
 25: "Peasant unrest and the birth of the Donghak movement (1860) as old Joseon decayed.",
 26: "Korea forced open (1876); the 1894 Donghak Peasant Revolution and Gabo Reforms swept his home Jeolla.",
 27: "The Russo-Japanese War, the 1905 protectorate, and Japan's 1910 annexation ended Korean independence.",
 28: "Born under Japanese colonial rule; lived through liberation (1945) and the Korean War (1950-53).",
 29: "Came of age in Park Chung-hee's industrial drive and Korea's 1987 democratization.",
 30: "A citizen of democratic, prosperous Korea - the 1988 Seoul Olympics and the global Korean Wave.",
}

def find_blob(t, v, required=True):
    m = re.search(r"const %s\s*=\s*" % re.escape(v), t)
    if not m:
        if required: raise SystemExit("no const %s" % v);
        return None, None
    i = m.end(); oc = t[i]; cc = {"{":"}", "[":"]"}[oc]
    depth = 0; s = False; e = False; j = i
    while j < len(t):
        c = t[j]
        if s:
            if e: e = False
            elif c == "\\": e = True
            elif c == '"': s = False
        else:
            if c == '"': s = True
            elif c == oc: depth += 1
            elif c == cc:
                depth -= 1
                if depth == 0: break
        j += 1
    return i, j + 1

def atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text); fh.flush(); os.fsync(fh.fileno())
    os.replace(tmp, path)

def yr(s):
    if not s: return None
    m = re.match(r"(\d{4})", str(s))
    return int(m.group(1)) if m else None

def main():
    d = json.load(open(DATA, encoding="utf-8")); P, F = d["people"], d["families"]
    lin = json.load(open(LIN, encoding="utf-8"))
    shutil.copy(DATA, DATA + ".bak-jeon-" + TODAY)

    # idempotent: remove anything a previous run of this script added, so re-running
    # gives a clean, current result instead of duplicating the line.
    for pid in [x for x in list(P) if x.startswith("JEON")]:
        for f in F.values():
            for s in ("husband", "wife"):
                if f.get(s) == pid: f[s] = None
            if pid in f.get("children", []): f["children"] = [x for x in f["children"] if x != pid]
        del P[pid]
    for fid in [x for x in list(F) if x.startswith("FJEON")]:
        for c in F[fid].get("children", []):
            if c in P and P[c].get("famc") == fid: P[c]["famc"] = None
        del F[fid]
    for pid, p in P.items():
        if p.get("famc") and p["famc"] not in F: p["famc"] = None
        p["fams"] = [x for x in p.get("fams", []) if x in F]

    # locate Yumi
    def norm(s): return re.sub(r"[^a-z]", "", (s or "").lower())
    yumi = None
    for pid, p in P.items():
        nm = norm(p.get("name")); ko = p.get("ko") or p.get("_ko") or ""
        if "유미" in (p.get("name","")+ko) or ("yumi" in nm and ("jeon" in nm or "jun" in nm or True)):
            if "yumi" in nm or "유미" in (p.get("name","")+ko):
                yumi = pid; break
    if not yumi:
        raise SystemExit("Could not find Yumi in the tree. Open family-data.json and tell me her id.")
    log.append("Found Yumi: %s (%s)" % (P[yumi]["name"], yumi))

    newid_n = [1]
    def nid():
        while ("JEON%03d" % newid_n[0]) in P: newid_n[0] += 1
        i = "JEON%03d" % newid_n[0]; newid_n[0] += 1; return i

    def mkperson(rec, sex, gen_label, is_jeon=True):
        pid = nid()
        rom = rec["rom"]
        kotxt = rec.get("ko") or ""
        if is_jeon:
            fullname = rom if rom.startswith("Jeon ") else "Jeon " + rom
            given = rom[5:] if rom.startswith("Jeon ") else rom
            surname = "Jeon"
            ko_full = ("전" + kotxt) if kotxt else ""          # e.g. 전호열, 전유미
        else:
            base = re.sub(r"\s*\(.*\)", "", rom).strip()        # "Park Ye-sun (Miryang clan)" -> "Park Ye-sun"
            toks = base.split()
            surname = toks[0] if toks else ""
            given = " ".join(toks[1:]) if len(toks) > 1 else ""
            fullname = base
            ko_full = kotxt.split()[-1] if kotxt else ""        # "밀양 박예선" -> 박예선 ; "광산 김씨" -> 김씨
        p = {"id": pid, "name": fullname, "given": given, "surname": surname,
             "sex": sex, "ko": ko_full, "hanja": rec.get("hanja"),
             "country": "South Korea", "flag": "kr", "connected": True, "directAncestor": False,
             "notes": []}
        b = yr(rec.get("born"));  dd = yr(rec.get("died"))
        if b or rec.get("born"): p["birth"] = {"year": b} if b else {}
        elif is_jeon and rec.get("gen") and rec["gen"] <= 27:
            est = 1934 - (28 - rec["gen"]) * 30      # ~30 yrs/generation back from dated ancestors
            p["birth"] = {"year": est, "estimated": True}
            p["notes"].append("Birth year ~%d is an ESTIMATE (about 30 years per generation back from the dated ancestors); the jokbo records no date for this generation." % est)
        if rec.get("buried"): p.setdefault("birth", {}); p.setdefault("events", []).append(
            {"type": "burial", "place": rec["buried"]})
        if dd: p["death"] = {"year": dd}
        note = "%s generation of the Damyang Jeon clan (담양 전씨)." % gen_label
        if rec.get("role"): note += " " + rec["role"] + "."
        if rec.get("hangryeol"): note += " Generation name character 항렬자 '%s'." % rec["hangryeol"]
        p["notes"].append(note)
        if is_jeon and rec.get("gen") in JEON_EVENTS:
            p["notes"].append("Korea in this era: " + JEON_EVENTS[rec["gen"]])
        P[pid] = p
        return pid

    def newfam():
        fid = "F" + nid()
        F[fid] = {"id": fid, "children": []}
        return fid

    def set_parents(child_pid, father_pid=None, mother_pid=None):
        fid = P[child_pid].get("famc")
        if not fid:
            fid = newfam(); P[child_pid]["famc"] = fid; F[fid]["children"].append(child_pid)
        fam = F[fid]
        if father_pid and not fam.get("husband"):
            fam["husband"] = father_pid; P[father_pid].setdefault("fams", []).append(fid)
        if mother_pid and not fam.get("wife"):
            fam["wife"] = mother_pid; P[mother_pid].setdefault("fams", []).append(fid)
        return fid

    dl = {r["gen"]: r for r in lin["direct_line"]}
    # gen 30 is Yumi (already in tree). Build 29..1 as chain of fathers.
    child = yumi; ordinal = {30:"30th",29:"29th",28:"28th",27:"27th",26:"26th",25:"25th",
        24:"24th",23:"23rd",22:"22nd",21:"21st",20:"20th",19:"19th",18:"18th",17:"17th",
        16:"16th",15:"15th",14:"14th",13:"13th",12:"12th",11:"11th",10:"10th",9:"9th",
        8:"8th",7:"7th",6:"6th",5:"5th",4:"4th",3:"3rd",2:"2nd",1:"1st"}
    added = 0
    for gen in range(29, 0, -1):
        rec = dl[gen]
        father = mkperson(rec, "M", ordinal[gen]); added += 1
        set_parents(child, father_pid=father)
        # spouse of this father (mother of child) where recorded
        if rec.get("spouse"):
            mrec = {"rom": rec["spouse"].get("rom","(wife)"), "ko": rec["spouse"].get("ko"),
                    "born": rec["spouse"].get("born")}
            wife = mkperson(mrec, "F", ordinal[gen] + " (by marriage)", is_jeon=False); added += 1
            set_parents(child, mother_pid=wife)
        log.append("  gen %d: %s (%s)" % (gen, P[father]["name"], rec.get("ko")))
        child = father

    # mother of Yumi = wife of gen29 (already added above via spouse on gen29).
    # modern relatives
    father29 = None
    # find gen29 father we just created (father of Yumi)
    fam = F.get(P[yumi].get("famc")) or {}
    father29 = fam.get("husband")
    rel_map = {"Ho-yeol": father29}
    for rec in lin.get("modern_relatives", []):
        rel = rec.get("rel", "")
        sex = "F" if rec["rom"] in ("Hye-rim","Ji-hye") or "sister" in rel else "M"
        if "sister" in rel: sex = "F"
        if "brother" in rel or "uncle" in rel or "cousin" in rel and rec["rom"] in ("Jeong-hyeon",): sex = "M"
        if rec["rom"] in ("Hye-rim","Ji-hye"): sex = "F"
        pid = mkperson(rec, sex, "%d세" % rec["gen"]); added += 1
        # Yumi's siblings are FULL siblings: add them as children of Yumi's own
        # parents' family (father Ho-yeol + mother), not a separate father-only family.
        if rec.get("father") == "Ho-yeol" and P[yumi].get("famc"):
            yf = P[yumi]["famc"]
            if pid not in F[yf]["children"]: F[yf]["children"].append(pid)
            P[pid]["famc"] = yf
        rel_map[rec["rom"]] = pid
    # uncle Yeong-gil is a brother of Ho-yeol -> shares grandfather (gen28)
    gp_fam = F.get(P.get(father29, {}).get("famc")) if father29 else None
    if gp_fam and "Yeong-gil" in rel_map:
        # add uncle as child of the gen28 grandfather family
        F[gp_fam["id"] if "id" in gp_fam else P[father29]["famc"]]["children"].append(rel_map["Yeong-gil"])
        P[rel_map["Yeong-gil"]]["famc"] = P[father29]["famc"]
    # uncle's spouse + children
    for rec in lin.get("modern_relatives", []):
        if rec["rom"] == "Yeong-gil" and rec.get("spouse"):
            wife = mkperson({"rom": rec["spouse"]["rom"], "ko": rec["spouse"].get("ko"),
                             "born": rec["spouse"].get("born")}, "F", "by marriage", is_jeon=False); added += 1
            # uncle+wife family
            uf = newfam(); F[uf]["husband"] = rel_map["Yeong-gil"]; F[uf]["wife"] = wife
            P[rel_map["Yeong-gil"]].setdefault("fams", []).append(uf)
            P[wife].setdefault("fams", []).append(uf)
            for c in lin["modern_relatives"]:
                if c.get("father") == "Yeong-gil" and c["rom"] in rel_map:
                    F[uf]["children"].append(rel_map[c["rom"]]); P[rel_map[c["rom"]]]["famc"] = uf

    # recompute connectivity/generation from P1
    root = "P1" if "P1" in P else next(iter(P))
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
        p["connected"] = pid in seen

    broken = sum(1 for pid,p in P.items() if p.get("famc") and p["famc"] not in F) \
           + sum(1 for p in P.values() for x in p.get("fams",[]) if x not in F) \
           + sum(1 for f in F.values() for x in [f.get("husband"),f.get("wife")]+f.get("children",[]) if x and x not in P)
    if broken: raise SystemExit("ABORT: %d broken links; nothing saved." % broken)

    d.setdefault("meta", {}).setdefault("stats", {})["individuals"] = len(P)
    data_min = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
    if len(json.loads(data_min)["people"]) != len(P):
        raise SystemExit("save verify failed")
    atomic(DATA, data_min)

    built = 0
    for tgt in TARGETS:
        if not os.path.exists(tgt): continue
        t = open(tgt, encoding="utf-8").read()
        di, dj = find_blob(t, "DATA", required=False)
        if di is None: continue
        t = t[:di] + data_min + t[dj:]
        # make Korean mode use each person's real Korean name (p.ko) instead of a
        # phonetic transliteration. Idempotent (won't re-match once patched).
        t = t.replace("p._ko = koizeName(p.name);",
                      "p._ko = p.ko ? p.ko : koizeName(p.name);")
        t = t.replace('p._kog = p.given ? koizeName(p.given) : "";',
                      'p._kog = p.ko ? p.ko : (p.given ? koizeName(p.given) : "");')
        t = t.replace('p._kos = p.surname ? (KO_NAMES[p.surname] || p.surname) : "";',
                      'p._kos = p.ko ? (p.surname==="Jeon"?"전":(KO_NAMES[p.surname]||p.surname)) : (p.surname ? (KO_NAMES[p.surname] || p.surname) : "");')
        atomic(tgt, t); built += 1

    log.append("\nAdded %d Jeon people (30-generation line + modern relatives). Rebuilt %d site file(s)." % (added, built))
    log.append("Korean mode now shows real Korean names (전호열, 전유미, 박예선 …).")
    log.append("Yumi now traces to founder 田得時 (전득시), 1st generation of the Damyang Jeon clan.")
    open(os.path.join(ROOT, "jeon_add_report.txt"), "w", encoding="utf-8").write("\n".join(log))
    print("\n".join(log))
    print("Backup: family-data.json.bak-jeon-%s" % TODAY)

if __name__ == "__main__":
    main()
