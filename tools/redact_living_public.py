#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
redact_living_public.py — builds a privacy-redacted copy of the DATA blob
and PHOTOS map for the PUBLIC (site/) deploy only. The root/ offline copy
(the "zip it and email to family" one per README.md) is left untouched with
full data, since it's not published to the open internet.

Heuristic for "living": no recorded death (year or date) AND (no birth year,
or birth year within the last 100 years). Conservative on purpose — unknown
defaults to redacted, not shown.

What gets redacted for a living person, in the PUBLIC copy only:
  - name/given/surname -> given name + surname initial (e.g. "Leon M.")
  - birth/death date, place, country -> removed entirely
  - notes, webEnrichment, events, occupations, sourceIds -> removed
  - entries in the PHOTOS map keyed by their id -> removed
Family links (famc/fams), sex, generation, directAncestor/connected flags
are KEPT so tree shape and navigation still work.

Known gap: the LIBRARY document array (374 attached records, each with a
"p" badge list of linked person ids) is NOT scrubbed by this script — it's
a large non-JSON JS array literal and out of scope for this pass. A living
person's name could still appear in an attached document's citation text.
Flagging this rather than silently claiming full coverage.
"""
import json, re, os, shutil, datetime, copy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
DATA_PATH = os.path.join(ROOT, "family-data.json")
SITE_HTML = os.path.join(ROOT, "site", "index.html")
CUR_YEAR = datetime.date.today().year

def is_living(p):
    dth = p.get("death") or {}
    if dth.get("year") or dth.get("date"):
        return False
    b = p.get("birth") or {}
    by = b.get("year")
    if not by and b.get("date"):
        m = re.search(r"(1[5-9]\d{2}|20\d{2})", str(b["date"]))
        if m: by = int(m.group(1))
    if by is None:
        return True
    return by >= CUR_YEAR - 100

def redact_person(p):
    q = {
        "id": p.get("id"), "sex": p.get("sex"),
        "famc": p.get("famc"), "fams": p.get("fams"),
        "generation": p.get("generation"),
        "directAncestor": p.get("directAncestor"),
        "connected": p.get("connected"),
        "flag": p.get("flag"), "country": None,
        "given": p.get("given", "").split(" ")[0] if p.get("given") else "Living",
        "surname": ((p.get("surname") or "")[:1] + ".") if p.get("surname") else "",
    }
    q["name"] = (q["given"] + " " + q["surname"]).strip()
    return q

def extract_blob(html, varname):
    m = re.search(r"const " + varname + r"\s*=\s*", html)
    if not m:
        return None, None, None
    i = m.end()
    if html[i] != "{":
        return None, None, None
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
    return i, j + 1, html[i:j+1]

def strip_photos_for_living(photos_blob_text, living_ids):
    # top-level KEY:[[...]] segments in a non-JSON JS object literal
    out = []
    i = 1  # skip leading {
    n = len(photos_blob_text)
    end = n - 1  # trailing }
    while i < end:
        while i < end and photos_blob_text[i] in " \n\t,":
            i += 1
        if i >= end: break
        m = re.match(r"[A-Za-z0-9_]+", photos_blob_text[i:])
        if not m:
            break
        key = m.group(0)
        i += len(key)
        assert photos_blob_text[i] == ":"
        i += 1
        vstart = i
        depth = 0; instr = False; esc = False
        while i < end:
            c = photos_blob_text[i]
            if instr:
                if esc: esc = False
                elif c == "\\": esc = True
                elif c == '"': instr = False
            else:
                if c == '"': instr = True
                elif c in "[{": depth += 1
                elif c in "]}":
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
            i += 1
        value = photos_blob_text[vstart:i]
        if key not in living_ids:
            out.append(key + ":" + value)
    return "{" + ",".join(out) + "}"

def main():
    d = json.load(open(DATA_PATH, encoding="utf-8"))
    P = d["people"]
    living_ids = {pid for pid, p in P.items() if is_living(p)}
    print("living (redact) ids:", len(living_ids), "of", len(P))

    pub = copy.deepcopy(d)
    for pid in living_ids:
        pub["people"][pid] = redact_person(pub["people"][pid])
    pub_json = json.dumps(pub, ensure_ascii=False, separators=(",", ":"))

    html = open(SITE_HTML, encoding="utf-8").read()
    shutil.copy(SITE_HTML, SITE_HTML + ".bak-prepriv-" + datetime.date.today().isoformat())

    di, de, _ = extract_blob(html, "DATA")
    if di is None:
        raise SystemExit("DATA blob not found in " + SITE_HTML)
    html = html[:di] + pub_json + html[de:]

    pi, pe, photos_blob = extract_blob(html, "PHOTOS")
    if pi is not None:
        new_photos = strip_photos_for_living(photos_blob, living_ids)
        html = html[:pi] + new_photos + html[pe:]
        print("PHOTOS entries stripped for living ids (if any had photos)")
    else:
        print("PHOTOS blob not found - skipped")

    open(SITE_HTML, "w", encoding="utf-8").write(html)
    print("Wrote redacted PUBLIC copy to", SITE_HTML)
    print("root/index.html left untouched (full data, per README's offline-family-copy design)")

if __name__ == "__main__":
    main()
