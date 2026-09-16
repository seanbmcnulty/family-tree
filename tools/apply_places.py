#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_places.py - merge the FamilySearch-resolved town coordinates
(fs_places.json) into every index.html copy, and add a town-level dot layer
to the Origins & Migration map.

Safety:
  - each index.html is backed up first
  - TOWN_LL merge is ADD-only: an existing town entry is never overwritten
  - the map patch is anchor-checked and idempotent; if the anchor is missing
    the file is left untouched and you are told
"""
import json, os
import fs_common as C

PLACES = os.path.join(C.HERE, "fs_places.json")

# a small helper injected before updateMap: groups birthplaces by town for a year
DOTS_FN = """function __placeDots(year, px){
  const groups = {};
  Object.values(P).forEach(p => {
    if (!p.birth || !p.birth.year || p.birth.year > year || !p.birth.place) return;
    const r = placeLL(p.birth.place, p.birth.country);
    if (!r || r.approx) return;
    const k = r.ll.join(",");
    (groups[k] = groups[k] || {ll: r.ll, n: 0, pl: p.birth.place.split(",")[0]}).n++;
  });
  return Object.values(groups).map(g => {
    const [x, y] = px(g.ll[1], g.ll[0]);
    const r = Math.min(6, 1.5 + Math.sqrt(g.n));
    return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${r.toFixed(1)}"
      fill="rgba(255,215,110,.55)" stroke="rgba(255,215,110,.9)" stroke-width=".5">
      <title>${esc(g.pl)}: ${g.n}</title></circle>`;
  }).join("");
}
"""

FN_ANCHOR = "function updateMap(year){"
DRAW_ANCHOR = '$("#bubbles").innerHTML = labeled.map'
DRAW_PATCHED = '$("#bubbles").innerHTML = __placeDots(year, px) + labeled.map'


def main():
    if not os.path.exists(PLACES):
        raise SystemExit("No fs_places.json - run fs_places.py first.")
    found = json.load(open(PLACES, encoding="utf-8"))
    towns = {k: v["ll"] for k, v in found.items()}
    if not towns:
        raise SystemExit("fs_places.json contains no resolved towns.")

    for t in C.INDEX_TARGETS:
        if not os.path.exists(t):
            continue
        rel = os.path.relpath(t, C.ROOT)
        C.backup_html(t, "places-" + C.TODAY)
        added = C.merge_js_dict(t, "TOWN_LL", towns)
        r1 = C.patch_once(t, FN_ANCHOR, DOTS_FN + FN_ANCHOR, "function __placeDots")
        r2 = C.patch_once(t, DRAW_ANCHOR, DRAW_PATCHED, "__placeDots(year, px) + labeled.map")
        print("  %s: +%d towns in TOWN_LL, dot layer: %s/%s" % (rel, added, r1, r2))
        if "missing" in (r1, r2):
            print("    ! map anchor not found in %s - gazetteer still merged, dots skipped." % rel)
    print("Done. Open the Origins & Migration map: town dots appear under the country bubbles,")
    print("and the ancestor Mapper now pins far more exact birthplaces.")


if __name__ == "__main__":
    main()
