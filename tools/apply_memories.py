#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_memories.py - bring the FamilySearch memories you ACCEPTED into the app.

ADD-only, backed up, idempotent:
  - accepted PHOTOS  -> copied to assets/fs-memories/, listed under the person's
                        "Family archive" strip (p.memories)
  - accepted STORIES -> appended to the person's webEnrichment, so they appear
                        under "From public records & web research" with a link
  - family-data.json is backed up, then re-injected into every index.html copy
  - a one-line, anchor-checked patch teaches the profile page to show p.memories
    (skipped automatically if already applied)
Never deletes, never overwrites an existing photo or fact.
"""
import json, os, shutil, glob
import fs_common as C

CACHE = os.path.join(C.HERE, "fs_memories_cache")

PHOTO_ANCHOR = "const photos = PHOTOS[pid] || [];"
PHOTO_PATCHED = ('const photos = (PHOTOS[pid] || []).concat('
                 '((P[pid]||{}).memories || []).map(m => [m.file, m.caption || "FamilySearch memory"]));')


def find_accepted():
    local = os.path.join(C.HERE, "fs_memories_accepted.json")
    if os.path.exists(local):
        return local
    dl = os.path.join(os.path.expanduser("~"), "Downloads")
    cands = sorted(glob.glob(os.path.join(dl, "fs_memories_accepted*.json")),
                   key=os.path.getmtime, reverse=True)
    return cands[0] if cands else local


def main():
    acc_path = find_accepted()
    if not os.path.exists(acc_path):
        raise SystemExit("No fs_memories_accepted.json - export it from fs_memories_review.html first.")
    accepted = json.load(open(acc_path, encoding="utf-8"))
    d, P, F = C.load_data()

    bak = C.backup_data("memories")
    print("Backed up data file -> %s" % os.path.basename(bak))

    photos_added = stories_added = skipped = 0
    for r in accepted:
        p = P.get(r.get("pid"))
        if not p:
            skipped += 1
            continue
        if r["kind"] == "photo" and r.get("cached"):
            src = os.path.join(CACHE, r["cached"])
            if not os.path.exists(src):
                skipped += 1
                continue
            fn = "fs-memories/" + r["cached"]
            for adir in C.ASSET_DIRS:
                if os.path.isdir(adir):
                    os.makedirs(os.path.join(adir, "fs-memories"), exist_ok=True)
                    shutil.copy(src, os.path.join(adir, "fs-memories", r["cached"]))
            mems = p.setdefault("memories", [])
            entry = {"file": "assets/" + fn,
                     "caption": r.get("title") or "FamilySearch memory",
                     "source": "https://www.familysearch.org/tree/person/memories/" + r["fs_id"],
                     "added": C.TODAY}
            if not any(m.get("file") == entry["file"] for m in mems):
                mems.append(entry)
                photos_added += 1
        elif r["kind"] == "story":
            text = (r.get("text") or "").strip()
            if not text:
                skipped += 1
                continue
            fact = "FamilySearch memory%s: %s" % (
                (" - " + r["title"]) if r.get("title") else "", text[:1500])
            we = p.setdefault("webEnrichment", [])
            if not any(w.get("fact") == fact for w in we):
                we.append({"fact": fact,
                           "source": {"url": "https://www.familysearch.org/tree/person/memories/" + r["fs_id"],
                                      "title": "FamilySearch memories for " + r["fs_id"]},
                           "added": C.TODAY, "confidence": "user-contributed"})
                stories_added += 1
        else:
            skipped += 1

    C.save_data(d)
    print("Photos added: %d   Stories added: %d   Skipped: %d" % (photos_added, stories_added, skipped))

    # push the data into every site copy, then apply the one-line profile patch
    for t in C.INDEX_TARGETS:
        if not os.path.exists(t):
            continue
        C.backup_html(t, "memories-" + C.TODAY)
    done = C.reinject_all(d)
    for t in done:
        res = C.patch_once(t, PHOTO_ANCHOR, PHOTO_PATCHED, 'memories || []).map')
        print("  %s: data re-injected, photo patch %s" % (os.path.relpath(t, C.ROOT), res))
        if res == "missing":
            print("    ! anchor not found - photos will not display until patched; tell Claude.")
    print("Done. Open index.html and check a profile with new memories.")


if __name__ == "__main__":
    main()
