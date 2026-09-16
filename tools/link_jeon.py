#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
link_jeon.py - native patcher for the main site (run on your machine):
  1. adds "Jeon Heritage" as an IN-APP view (button + <section id="v-jeon"> iframe),
  2. upgrades the South Korea flag to a proper taegeukgi,
  3. removes the "How are we related?" tab (hides the nav button; keeps its code so
     nothing breaks),
  4. copies the full heritage page into the publish folders.
Idempotent and safe: each edit either matches and applies, or no-ops.
"""
import os, re, shutil

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
TARGETS = [os.path.join(ROOT, "index.html"), os.path.join(ROOT, "site", "index.html"),
           os.path.join(ROOT, "mcnulty-tree-website", "index.html")]

BTN = '    <button data-v="jeon">\U0001F1F0\U0001F1F7 Jeon Heritage 족보</button>'
SECTION = ('  <section class="view" id="v-jeon"><iframe src="jeon-heritage.html" '
           'title="Jeon Heritage" style="width:100%;height:82vh;border:none;'
           'background:#faf7f0;border-radius:8px"></iframe></section>')

# a proper taegeukgi: white field, S-curve taegeuk, four corner trigrams
KFLAG = ('<rect width="60" height="40" fill="#fff"/>'
 '<g transform="translate(30 20)"><circle r="9.6" fill="#0047a0"/>'
 '<path d="M0 -9.6a9.6 9.6 0 0 1 0 19.2a4.8 4.8 0 0 1 0 -9.6a4.8 4.8 0 0 0 0 -9.6z" fill="#cd2e3a"/></g>'
 '<g fill="#141414">'
 '<g transform="translate(13 8.5) rotate(33.7)"><rect x="-4.3" y="-2.5" width="8.6" height="1.2"/><rect x="-4.3" y="-0.6" width="8.6" height="1.2"/><rect x="-4.3" y="1.3" width="8.6" height="1.2"/></g>'
 '<g transform="translate(47 8.5) rotate(-33.7)"><rect x="-4.3" y="-2.5" width="8.6" height="1.2"/><rect x="-4.3" y="-0.6" width="3.5" height="1.2"/><rect x="0.8" y="-0.6" width="3.5" height="1.2"/><rect x="-4.3" y="1.3" width="8.6" height="1.2"/></g>'
 '<g transform="translate(13 31.5) rotate(-33.7)"><rect x="-4.3" y="-2.5" width="3.5" height="1.2"/><rect x="0.8" y="-2.5" width="3.5" height="1.2"/><rect x="-4.3" y="-0.6" width="8.6" height="1.2"/><rect x="-4.3" y="1.3" width="3.5" height="1.2"/><rect x="0.8" y="1.3" width="3.5" height="1.2"/></g>'
 '<g transform="translate(47 31.5) rotate(33.7)"><rect x="-4.3" y="-2.5" width="3.5" height="1.2"/><rect x="0.8" y="-2.5" width="3.5" height="1.2"/><rect x="-4.3" y="-0.6" width="3.5" height="1.2"/><rect x="0.8" y="-0.6" width="3.5" height="1.2"/><rect x="-4.3" y="1.3" width="3.5" height="1.2"/><rect x="0.8" y="1.3" width="3.5" height="1.2"/></g>'
 '</g>')
NEW_FLAG = 'FLAG_DRAW["South Korea"]=()=>`' + KFLAG + '`;'

# receives a click from the heritage iframe and opens that person's profile
LISTENER = ('<script>/*jeon-nav*/window.addEventListener("message",function(e){try{'
 'var n=e.data&&e.data.jeonPerson;if(!n)return;'
 'var pp=(typeof P!=="undefined")?P:(typeof DATA!=="undefined"&&DATA.people);if(!pp)return;'
 'var hit=Object.values(pp).find(function(x){return x.name===n||(x.ko||"")===n||(x._ko||"")===n;});'
 'if(hit&&typeof openProfile==="function"){if(typeof showView==="function")showView("tree");openProfile(hit.id);}'
 '}catch(_){}});</script>')

OLD_NAV = re.compile(r'\s*<(?:button|a)\b[^>]*(?:jeon-heritage\.html|data-v="jeon")[^>]*>.*?</(?:button|a)>', re.S)
OLD_SEC = re.compile(r'\s*<section[^>]*id="v-jeon".*?</section>', re.S)
FLAG_RE = re.compile(r'FLAG_DRAW\["South Korea"\]=\(\)=>`[^`]*`;')
RELBTN_RE = re.compile(r'(<button\b[^>]*data-v="rel")([^>]*>)')

def main():
    done = 0
    for tgt in TARGETS:
        if not os.path.exists(tgt):
            continue
        html = open(tgt, encoding="utf-8").read()
        orig = html
        # (1) in-app Jeon view
        html = OLD_NAV.sub("", html)
        html = OLD_SEC.sub("", html)
        if "</nav>" in html:
            html = html.replace("</nav>", BTN + "\n  </nav>", 1)
            html = html.replace("</nav>", "</nav>\n" + SECTION, 1)
        # (2) better Korean flag
        if FLAG_RE.search(html):
            html = FLAG_RE.sub(lambda m: NEW_FLAG, html)
        # (3) hide the "How are we related?" tab (keep code intact)
        if 'style="display:none"' not in (RELBTN_RE.search(html).group(0) if RELBTN_RE.search(html) else ""):
            html = RELBTN_RE.sub(r'\1 style="display:none"\2', html, count=1)
        # (4) listener so clicking a heritage name opens that person in the tree
        if "/*jeon-nav*/" not in html and "</body>" in html:
            html = html.replace("</body>", LISTENER + "\n</body>", 1)
        if html != orig:
            shutil.copyfile(tgt, tgt + ".bak-jeonpatch")   # safety net
            tmp = tgt + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(html); fh.flush(); os.fsync(fh.fileno())
            os.replace(tmp, tgt); done += 1
            print("patched", os.path.relpath(tgt, ROOT), "(backup: .bak-jeonpatch)")
        else:
            print("already current:", os.path.relpath(tgt, ROOT))

    src = os.path.join(ROOT, "jeon-heritage.html")
    if os.path.exists(src):
        for sub in ("site", "mcnulty-tree-website"):
            dd = os.path.join(ROOT, sub)
            if os.path.isdir(dd):
                shutil.copyfile(src, os.path.join(dd, "jeon-heritage.html"))
                print("synced jeon-heritage.html ->", sub)
    print("Done. Updated %d file(s): in-app Jeon view, Korean flag, hidden 'how related' tab." % done)

if __name__ == "__main__":
    main()
