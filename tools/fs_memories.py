#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fs_memories.py - fetch FamilySearch MEMORIES (photos, documents, stories) for
everyone already matched to a FamilySearch id, and stage them for your review.

Read-only against FamilySearch and against your tree. Living people are skipped.
Photos are downloaded into familysearch/fs_memories_cache/ so the review page
can show real thumbnails. Nothing enters the app until you tick rows in
fs_memories_review.html and run apply_memories.py.

  python fs_memories.py            # real run (login in browser)
  python fs_memories.py --demo     # offline demo with synthetic memories
  python fs_memories.py --limit 50 # only the first 50 anchors (for a taste)
"""
from __future__ import annotations
import json, os, sys, argparse, html
import fs_common as C

CACHE = os.path.join(C.HERE, "fs_memories_cache")
OUT_JSON = os.path.join(C.HERE, "fs_memories.json")
OUT_HTML = os.path.join(C.HERE, "fs_memories_review.html")

IMG_TYPES = ("image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp")


def ext_for(mt, url):
    for t, e in (("jpeg", ".jpg"), ("png", ".png"), ("gif", ".gif"), ("webp", ".webp"), ("bmp", ".bmp")):
        if t in (mt or ""):
            return e
    for e in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
        if e in (url or "").lower():
            return ".jpg" if e == ".jpeg" else e
    return ".jpg"


def parse_memories(data):
    """Yield {kind, url, title, mediaType, id} from a /memories response."""
    for sd in (data or {}).get("sourceDescriptions", []) or []:
        mt = sd.get("mediaType") or ""
        url = sd.get("about") or ""
        # prefer an explicit image link if present (thumbnails live in links)
        links = sd.get("links") or {}
        for key in ("image", "image-thumbnail"):
            if key == "image" and isinstance(links.get(key), dict) and links[key].get("href"):
                url = links[key]["href"]
                break
        title = ""
        if sd.get("titles"):
            title = (sd["titles"][0] or {}).get("value") or ""
        if mt.startswith("image/") or (mt == "" and any(e in url.lower() for e in (".jpg", ".jpeg", ".png"))):
            yield {"kind": "photo", "url": url, "title": title, "mediaType": mt, "id": sd.get("id")}
        elif mt.startswith("text/"):
            yield {"kind": "story", "url": url, "title": title, "mediaType": mt, "id": sd.get("id")}
        # PDFs and everything else are listed but not fetched
        elif mt:
            yield {"kind": "other", "url": url, "title": title, "mediaType": mt, "id": sd.get("id")}


def run(args):
    d, P, F = C.load_data()
    anchors = C.fs_anchors(P)
    items = sorted(anchors.items(), key=lambda kv: (P[kv[0]].get("generation") is None,
                                                    P[kv[0]].get("generation") or 99))
    if args.limit:
        items = items[:args.limit]
    print("Anchors to check for memories: %d" % len(items))

    fs = DemoFS() if args.demo else C.make_client()
    os.makedirs(CACHE, exist_ok=True)

    rows, checked, with_mem = [], 0, 0
    for pid, fsid in items:
        p = P[pid]
        try:
            data = C.fs_get(fs, "/platform/tree/persons/%s/memories" % fsid)
        except Exception as e:
            print("  ! %s (%s): %s" % (p.get("name"), fsid, e))
            continue
        checked += 1
        found = list(parse_memories(data))
        if not found:
            continue
        with_mem += 1
        print("  %s (%s): %d memor%s" % (p.get("name"), fsid, len(found),
                                         "y" if len(found) == 1 else "ies"))
        for k, mem in enumerate(found):
            row = {"pid": pid, "name": p.get("name"), "fs_id": fsid,
                   "kind": mem["kind"], "title": mem["title"],
                   "mediaType": mem["mediaType"], "url": mem["url"],
                   "memory_id": mem.get("id")}
            if mem["kind"] == "photo" and mem["url"]:
                fn = "%s-%s%s" % (pid, k, ext_for(mem["mediaType"], mem["url"]))
                if C.fs_download(fs, mem["url"], os.path.join(CACHE, fn)):
                    row["cached"] = fn
            elif mem["kind"] == "story" and mem["url"]:
                try:
                    fs._throttle()
                    r = fs.session.get(mem["url"], timeout=30)
                    if r.status_code == 200:
                        row["text"] = r.text[:4000]
                except Exception:
                    pass
            rows.append(row)

    json.dump(rows, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    write_review(rows, checked, with_mem, args.demo)
    print("\nChecked %d people; %d had memories; %d items staged." % (checked, with_mem, len(rows)))
    print("Open fs_memories_review.html, tick what you want, export, then run apply_memories.py.")


def write_review(rows, checked, with_mem, demo):
    trs = []
    for i, r in enumerate(rows):
        if r["kind"] == "photo":
            body = ('<img class="mem" src="fs_memories_cache/%s">' % html.escape(r["cached"])) if r.get("cached") \
                   else '<span class="small">(image not downloadable - see link)</span>'
        elif r["kind"] == "story":
            body = '<div class="story">%s</div>' % html.escape(r.get("text") or "(story text not fetched)")
        else:
            body = '<span class="small">%s</span>' % html.escape(r.get("mediaType") or "other")
        trs.append(
            '<tr><td><input type="checkbox" class="acc" data-i="%d" %s></td>'
            '<td>%s<br><span class="small">%s</span></td><td>%s</td><td>%s<br>'
            '<a class="small" href="https://www.familysearch.org/tree/person/memories/%s" target="_blank">on FamilySearch</a></td></tr>'
            % (i, "checked" if r["kind"] in ("photo", "story") else "",
               html.escape(r.get("name") or ""), html.escape(r["pid"]),
               body, html.escape(r.get("title") or "(untitled)"), html.escape(r["fs_id"])))
    doc = """<!doctype html><meta charset="utf-8"><title>FamilySearch memories review</title>
<style>%s</style><h1>FamilySearch memories - review%s</h1>
<p class="small">Checked %d matched people; %d had memories. Tick the photos and stories you want in the
family app, then click Export and run <b>apply_memories.py</b> (7_apply_memories.bat).
Nothing is overwritten; photos are ADDED to the profile's Family archive, stories to
"From public records &amp; web research".</p>
<button onclick="setAll(true)">Select all</button> <button onclick="setAll(false)">Select none</button>
<button onclick="exportAccepted('fs_memories_accepted.json')">Export accepted -&gt; fs_memories_accepted.json</button>
<table><tr><th></th><th>Person</th><th>Memory</th><th>Title / link</th></tr>%s</table>
<script>const ROWS=%s;%s</script>""" % (
        C.REVIEW_CSS, " (DEMO)" if demo else "", checked, with_mem,
        "\n".join(trs), json.dumps(rows), C.REVIEW_JS)
    open(OUT_HTML, "w", encoding="utf-8").write(doc)


# a 1x1 transparent PNG so demo "downloads" produce a real file
DEMO_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d"
    "4944415478da63fcffffff030007000280a0c1a90000000049454e44ae426082")


class DemoFS:
    """Offline stand-in so the whole flow can be exercised with no API key.
    Every third anchor 'has' a photo + a story."""
    def __init__(self):
        self._n = 0

    class _R:
        status_code = 200
        text = "Grandpa kept this story: he walked to school every day, rain or shine."
        content = DEMO_PNG

    class _S:
        def get(self, url, **kw):
            return DemoFS._R()
    session = _S()

    def _throttle(self):
        pass

    def _get(self, path, params=None, accept=None, **kw):
        self._n += 1
        if self._n % 3:
            return {"sourceDescriptions": []}
        return {"sourceDescriptions": [
            {"id": "M1", "about": "https://demo/img1.jpg", "mediaType": "image/jpeg",
             "titles": [{"value": "Portrait, about 1930"}]},
            {"id": "M2", "about": "https://demo/story1.txt", "mediaType": "text/plain",
             "titles": [{"value": "A story about grandpa"}]}]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    run(ap.parse_args())
