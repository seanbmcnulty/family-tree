#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fs_places.py - fix the Origins & Migration map using the FamilySearch PLACES
authority (their curated gazetteer of historical place names with coordinates).

The app resolves a birthplace with placeLL(): exact town match in TOWN_LL, else
region in REGION_LL, else the whole-country fallback. Every place that currently
falls back to region/country level is looked up against FamilySearch Places and,
when FS returns confident coordinates, a precise town entry is proposed.

Writes fs_places.json + fs_places_report.txt. Nothing changes until you run
apply_places.py, which ADD-only merges the new towns into TOWN_LL in every
index.html copy (existing entries are never overwritten) and adds a place-level
dot layer to the migration map.

  python fs_places.py          # real run (login in browser)
  python fs_places.py --demo   # offline demo with a synthetic gazetteer
"""
from __future__ import annotations
import json, os, re, argparse
import fs_common as C

OUT_JSON = os.path.join(C.HERE, "fs_places.json")
OUT_TXT = os.path.join(C.HERE, "fs_places_report.txt")
CACHE = os.path.join(C.HERE, "fs_places_cache.json")

COUNTRY_TOKENS = {
    "Canada": ["canada"], "United States": ["united states", "usa"],
    "England": ["england"], "Ireland": ["ireland"], "Scotland": ["scotland"],
    "Wales": ["wales"], "Northern Ireland": ["ireland"], "United Kingdom": ["united kingdom", "england"],
    "Switzerland": ["switzerland", "schweiz", "suisse"], "Germany": ["germany", "deutschland", "prussia"],
    "Netherlands": ["netherlands", "holland"], "France": ["france"], "Belgium": ["belgium"],
    "South Korea": ["korea"],
}


def gather_places(P):
    """distinct (place, country) -> occurrence count, from births/deaths/events."""
    counts = {}
    for p in P.values():
        for slot in ("birth", "death"):
            e = p.get(slot) or {}
            if e.get("place"):
                counts[(e["place"], e.get("country"))] = counts.get((e["place"], e.get("country")), 0) + 1
        for e in p.get("events") or []:
            if e.get("place"):
                counts[(e["place"], e.get("country"))] = counts.get((e["place"], e.get("country")), 0) + 1
    return counts


def resolves_to_town(place, town_ll):
    segs = [s.strip().replace(".", "") for s in place.lower().split(",")]
    for s in segs:
        if s in town_ll:
            return True
    for s in segs:
        for k in town_ll:
            if len(k) > 4 and k in s:
                return True
    return False


def town_key(place):
    """The key placeLL() would need: the first (most specific) segment."""
    seg = place.split(",")[0].strip().lower().replace(".", "")
    seg = re.sub(r"^\d+\s+", "", seg)          # strip house numbers
    seg = seg.split(";")[0].strip()             # "Burnaby; Richmond" -> burnaby
    return seg


def parse_places_search(data):
    """Extract [(fullName, lat, lon)] from a places search response."""
    out = []
    for entry in (data or {}).get("entries", []) or []:
        gx = (entry.get("content") or {}).get("gedcomx") or {}
        for pl in gx.get("places", []) or []:
            lat, lon = pl.get("latitude"), pl.get("longitude")
            name = ((pl.get("display") or {}).get("fullName")
                    or (pl.get("names") or [{}])[0].get("value") or "")
            if lat is not None and lon is not None:
                out.append((name, float(lat), float(lon)))
    return out


def plausible(name, lat, lon, country):
    toks = COUNTRY_TOKENS.get(country or "", [])
    if toks and not any(t in name.lower() for t in toks):
        return False
    return -90 <= lat <= 90 and -180 <= lon <= 180


def run(args):
    d, P, F = C.load_data()
    idx = C.INDEX_TARGETS[0]
    town_ll = C.read_js_dict(idx, "TOWN_LL") or {}
    print("Existing TOWN_LL entries: %d" % len(town_ll))

    counts = gather_places(P)
    todo = {}
    for (place, country), n in counts.items():
        if resolves_to_town(place, town_ll):
            continue
        key = town_key(place)
        if not key or len(key) < 3 or key in town_ll:
            continue
        cur = todo.get(key)
        if not cur or n > cur["count"]:
            todo[key] = {"key": key, "place": place, "country": country, "count": n}
    todo = dict(sorted(todo.items(), key=lambda kv: -kv[1]["count"]))
    print("Distinct place strings: %d | not yet town-resolved: %d" % (len(counts), len(todo)))
    if args.limit:
        todo = dict(list(todo.items())[:args.limit])

    cache_path = CACHE.replace(".json", "_demo.json") if args.demo else CACHE
    cache = json.load(open(cache_path, encoding="utf-8")) if os.path.exists(cache_path) else {}
    fs = DemoFS() if args.demo else C.make_client()

    found, missed = {}, []
    for key, t in todo.items():
        q = t["place"] if len(t["place"]) < 120 else ", ".join(t["place"].split(",")[-3:])
        if key in cache:
            hits = cache[key]
        else:
            try:
                data = C.fs_get(fs, "/platform/places/search",
                                {"q": 'name:"%s"' % q.replace('"', ""), "count": 3},
                                accept="application/x-gedcomx-atom+json")
                hits = parse_places_search(data)
            except Exception as e:
                print("  ! %s: %s" % (key, e))
                hits = []
            cache[key] = hits
            json.dump(cache, open(cache_path, "w", encoding="utf-8"))
        pick = next(((nm, la, lo) for nm, la, lo in hits
                     if plausible(nm, la, lo, t["country"])), None)
        if pick:
            found[key] = {"ll": [round(pick[1], 4), round(pick[2], 4)],
                          "fs_name": pick[0], "from": t["place"],
                          "country": t["country"], "count": t["count"]}
            print("  + %-28s -> %s  (%s)" % (key, found[key]["ll"], pick[0][:60]))
        else:
            missed.append(t)

    json.dump(found, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    with open(OUT_TXT, "w", encoding="utf-8") as f:
        f.write("FamilySearch Places pass %s%s\n" % (C.TODAY, " (DEMO)" if args.demo else ""))
        f.write("Places needing town coords : %d\n" % (len(found) + len(missed)))
        f.write("Resolved via FS Places     : %d\n" % len(found))
        f.write("Still unresolved           : %d\n\n" % len(missed))
        for t in missed:
            f.write("  MISS  %-30s (%s, seen %dx)\n" % (t["key"], t["country"], t["count"]))
    print("\nResolved %d new towns (%d unresolved). Review fs_places_report.txt," % (len(found), len(missed)))
    print("then run apply_places.py (11_apply_places.bat) to update the maps.")


class DemoFS:
    """Answers every query with synthetic coordinates so the whole flow -
    including apply_places.py - can be tested offline."""
    def __init__(self):
        self._n = 0
    def _get(self, path, params=None, accept=None, **kw):
        self._n += 1
        if self._n % 4 == 0:            # leave some unresolved, like real life
            return {"entries": []}
        q = (params or {}).get("q", "").replace('name:', '').strip('"')
        lat = 40 + (hash(q) % 2000) / 100.0
        lon = -120 + (hash(q[::-1]) % 14000) / 100.0
        return {"entries": [{"content": {"gedcomx": {"places": [
            {"display": {"fullName": q}, "latitude": lat, "longitude": lon}]}}}]}
    def _throttle(self): pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    run(ap.parse_args())
