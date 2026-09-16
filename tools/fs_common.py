#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fs_common.py - shared helpers for the FamilySearch toolkit (memories,
descendancy, places). Read by the new scripts; changes nothing on its own."""
from __future__ import annotations
import json, os, re, datetime, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
DATA = os.path.join(ROOT, "family-data.json")
CONF = os.path.join(HERE, "fs_config.json")
INDEX_TARGETS = [os.path.join(ROOT, "index.html"),
                 os.path.join(ROOT, "site", "index.html"),
                 os.path.join(ROOT, "mcnulty-tree-website", "index.html")]
ASSET_DIRS = [os.path.join(ROOT, "assets"),
              os.path.join(ROOT, "site", "assets"),
              os.path.join(ROOT, "mcnulty-tree-website", "assets")]
TODAY = datetime.date.today().isoformat()

FS_URL_RE = re.compile(r"familysearch\.org/tree/person/details/([A-Z0-9-]+)")


def load_data():
    d = json.load(open(DATA, encoding="utf-8"))
    return d, d["people"], d["families"]


def backup_data(tag):
    dst = DATA + ".bak-%s-%s" % (tag, TODAY)
    shutil.copy(DATA, dst)
    return dst


def save_data(d):
    tmp = DATA + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, DATA)


def is_living(p):
    y = (p.get("birth") or {}).get("year")
    return bool(y and y > datetime.date.today().year - 100 and not p.get("death"))


def fs_anchors(P):
    """pid -> FamilySearch person id, from webEnrichment links + fs_confirmed.json.
    Only deceased people are ever returned."""
    out = {}
    for pid, p in P.items():
        for we in p.get("webEnrichment") or []:
            m = FS_URL_RE.search(((we.get("source") or {}).get("url")) or "")
            if m:
                out[pid] = m.group(1)
                break
    cf = os.path.join(HERE, "fs_confirmed.json")
    if os.path.exists(cf):
        for row in json.load(open(cf, encoding="utf-8")):
            if row.get("pid") and row.get("fs_id"):
                out[row["pid"]] = row["fs_id"]
    return {pid: fid for pid, fid in out.items() if pid in P and not is_living(P[pid])}


def make_client():
    if not os.path.exists(CONF):
        raise SystemExit("Create fs_config.json first (copy fs_config.example.json).")
    import fs_client
    fs = fs_client.FamilySearch(json.load(open(CONF, encoding="utf-8")))
    fs.authenticate()
    return fs


def fs_get(fs, path, params=None, accept="application/x-fs-v1+json"):
    """GET an arbitrary platform path with a custom Accept header."""
    return fs._get(path, params, accept=accept)


def fs_download(fs, url, dest):
    """Download a memory artifact (auth'd, throttled). Returns True on success."""
    fs._throttle()
    try:
        r = fs.session.get(url, timeout=60, allow_redirects=True)
        if r.status_code != 200 or not r.content:
            return False
        with open(dest, "wb") as f:
            f.write(r.content)
        return True
    except Exception:
        return False


# ---------- index.html surgery (string-aware, anchor-checked) ----------

def _match_braces(s, i):
    """i points at '{'; return index just past the matching '}'."""
    depth = 0; instr = False; esc = False; j = i
    while j < len(s):
        c = s[j]
        if instr:
            if esc: esc = False
            elif c == "\\": esc = True
            elif c == '"': instr = False
        else:
            if c == '"': instr = True
            elif c == "{": depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0: return j + 1
        j += 1
    raise SystemExit("Brace matching ran off the end of the file.")


def swap_data_blob(htmlpath, new_json):
    """Replace the embedded `const DATA = {...}` blob (same as cleanup_and_build)."""
    html = open(htmlpath, encoding="utf-8").read()
    m = re.search(r"const DATA\s*=\s*", html)
    if not m:
        raise SystemExit("Could not find 'const DATA =' in " + htmlpath)
    i = m.end()
    if html[i] != "{":
        raise SystemExit("Unexpected DATA format in " + htmlpath)
    end = _match_braces(html, i)
    open(htmlpath, "w", encoding="utf-8").write(html[:i] + new_json + html[end:])


def _loads_js(txt):
    """json.loads that tolerates JS trailing commas."""
    return json.loads(re.sub(r",\s*([}\]])", r"\1", txt))


def read_js_dict(htmlpath, const_name):
    """Parse `const NAME = {...}` out of index.html (the gazetteers are JSON)."""
    html = open(htmlpath, encoding="utf-8").read()
    m = re.search(r"const %s\s*=\s*" % re.escape(const_name), html)
    if not m:
        return None
    i = m.end()
    end = _match_braces(html, i)
    txt = html[i:end].rstrip()
    if txt.endswith(";"):
        txt = txt[:-1]
    return _loads_js(txt)


def merge_js_dict(htmlpath, const_name, new_entries):
    """ADD-only merge of new_entries into `const NAME = {...}`. Never overwrites
    an existing key. Returns number of keys added."""
    html = open(htmlpath, encoding="utf-8").read()
    m = re.search(r"const %s\s*=\s*" % re.escape(const_name), html)
    if not m:
        raise SystemExit("Could not find 'const %s =' in %s" % (const_name, htmlpath))
    i = m.end()
    end = _match_braces(html, i)
    cur = _loads_js(html[i:end])
    added = 0
    for k, v in new_entries.items():
        if k not in cur:
            cur[k] = v
            added += 1
    blob = json.dumps(cur, ensure_ascii=False, separators=(",", ":"))
    open(htmlpath, "w", encoding="utf-8").write(html[:i] + blob + html[end:])
    return added


def patch_once(htmlpath, anchor, replacement, already):
    """Replace `anchor` with `replacement` unless `already` is present (idempotent).
    Refuses (returns 'missing') if the anchor cannot be found."""
    html = open(htmlpath, encoding="utf-8").read()
    if already in html:
        return "already"
    n = html.count(anchor)
    if n == 0:
        return "missing"
    if n > 1:
        return "ambiguous"
    open(htmlpath, "w", encoding="utf-8").write(html.replace(anchor, replacement, 1))
    return "patched"


def backup_html(htmlpath, tag):
    if os.path.exists(htmlpath):
        shutil.copy(htmlpath, htmlpath + ".bak-%s" % tag)


def reinject_all(d):
    """Push family-data.json back into every index.html copy that exists."""
    blob = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
    done = []
    for t in INDEX_TARGETS:
        if os.path.exists(t):
            swap_data_blob(t, blob)
            done.append(t)
    return done


# ---------- review page scaffolding (matches the fs_extend pattern) ----------

REVIEW_CSS = """
body{font-family:Segoe UI,system-ui,sans-serif;background:#0f1d2b;color:#e8eef4;margin:24px}
h1{font-size:20px} h2{font-size:16px;margin:26px 0 8px;color:#ffd76e}
table{border-collapse:collapse;width:100%;font-size:13.5px}
td,th{border:1px solid #2b3f55;padding:6px 8px;text-align:left;vertical-align:top}
th{background:#16293c} tr:nth-child(even){background:#132435}
img.mem{max-height:110px;max-width:160px;border-radius:4px}
.small{color:#9db2c4;font-size:12px} button{font-size:15px;padding:8px 14px;margin:14px 0;cursor:pointer}
.story{white-space:pre-wrap;max-width:520px;max-height:140px;overflow:auto;background:#101f30;padding:6px;border-radius:4px}
"""

REVIEW_JS = """
function exportAccepted(fname){
  const rows=[...document.querySelectorAll("input.acc:checked")].map(cb=>ROWS[+cb.dataset.i]);
  const blob=new Blob([JSON.stringify(rows,null,1)],{type:"application/json"});
  const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download=fname;a.click();
}
function setAll(v){document.querySelectorAll("input.acc").forEach(cb=>cb.checked=v)}
"""
