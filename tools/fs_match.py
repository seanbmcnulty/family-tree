#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fs_match.py — the reusable, API-free matching core.

This module does NOT touch the network or any credentials. It scores how well a
person from our tree (`family-data.json`) matches a candidate person returned by
the FamilySearch API (GEDCOM X JSON). It is unit-testable on its own — see the
__main__ self-test at the bottom, runnable today with no API key.

Design: be conservative. A high score means "very likely the same person";
nothing here ever writes to the tree — it only proposes.
"""
from __future__ import annotations
import re, unicodedata, json

# ---------- normalization ----------
def norm(s):
    if not s: return ""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    s = s.lower()
    s = re.sub(r"\(.*?\)", " ", s)               # drop parentheticals e.g. "(Fanny)"
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

# common given-name variants so "Fred"~"Frederick", "Lily"~"Lillian"
NICK = {
 "fred":"frederick","freddy":"frederick","will":"william","bill":"william","willy":"william",
 "jack":"john","johnny":"john","tom":"thomas","tommy":"thomas","jim":"james","jimmy":"james",
 "joe":"joseph","harry":"henry","hal":"henry","dick":"richard","rick":"richard","bob":"robert",
 "rob":"robert","ned":"edward","ted":"edward","sandy":"alexander","alex":"alexander",
 "lily":"lillian","lil":"lillian","fanny":"frances","franny":"frances","betty":"elizabeth",
 "beth":"elizabeth","liz":"elizabeth","peggy":"margaret","meg":"margaret","maggie":"margaret",
 "molly":"mary","polly":"mary","nan":"ann","nancy":"ann","kate":"katherine","katie":"katherine",
 "patty":"patrick","pat":"patrick","mike":"michael","danny":"daniel","dan":"daniel","sam":"samuel",
}
def canon_given(g):
    g = norm(g)
    first = g.split(" ")[0] if g else ""
    return NICK.get(first, first), set(g.split())

def name_score(our_given, our_surname, cand_given, cand_surname):
    """0..1 on name agreement."""
    osur, csur = norm(our_surname), norm(cand_surname)
    sur = 0.0
    if osur and csur:
        if osur == csur: sur = 1.0
        elif osur in csur or csur in osur: sur = 0.7
        elif _lev_ratio(osur, csur) > 0.8: sur = 0.6
    og1, ogset = canon_given(our_given)
    cg1, cgset = canon_given(cand_given)
    giv = 0.0
    if og1 and cg1:
        if og1 == cg1: giv = 1.0
        elif og1 in cgset or cg1 in ogset: giv = 0.7
        elif _lev_ratio(og1, cg1) > 0.82: giv = 0.6
    # bonus if any middle name overlaps
    mids = (ogset & cgset) - {og1, cg1}
    if mids: giv = min(1.0, giv + 0.1)
    return 0.6 * sur + 0.4 * giv

def _lev_ratio(a, b):
    if not a or not b: return 0.0
    la, lb = len(a), len(b)
    d = list(range(lb + 1))
    for i in range(1, la + 1):
        prev, d[0] = d[0], i
        for j in range(1, lb + 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j-1] + 1, prev + (a[i-1] != b[j-1]))
            prev = cur
    return 1 - d[lb] / max(la, lb)

def year_score(our_y, cand_y, tol=3):
    if not our_y or not cand_y: return None      # unknown -> neutral
    diff = abs(int(our_y) - int(cand_y))
    if diff == 0: return 1.0
    if diff <= tol: return 1.0 - 0.15 * diff
    if diff <= tol * 2: return 0.3
    return 0.0

def place_score(our_pl, cand_pl):
    if not our_pl or not cand_pl: return None
    o = set(norm(our_pl).split()); c = set(norm(cand_pl).split())
    o -= {"of","co","county","city"}; c -= {"of","co","county","city"}
    if not o or not c: return None
    overlap = len(o & c) / min(len(o), len(c))
    return min(1.0, overlap)

def rel_name_overlap(our_names, cand_names):
    """fraction of our relatives' surnames+given-firsts found among candidate's."""
    if not our_names or not cand_names: return None
    o = {canon_given(n)[0] for n in our_names if n} | {norm(n).split()[-1] for n in our_names if norm(n)}
    c = {canon_given(n)[0] for n in cand_names if n} | {norm(n).split()[-1] for n in cand_names if norm(n)}
    o.discard(""); c.discard("")
    if not o: return None
    return len(o & c) / len(o)

# ---------- top-level scorer ----------
def score_match(our, cand):
    """
    our:  {given, surname, birth_year, death_year, birth_place, parents:[names], spouses:[names]}
    cand: same shape, extracted from a FamilySearch person.
    Returns (score 0..1, breakdown dict).
    """
    b = {}
    b["name"] = name_score(our.get("given"), our.get("surname"), cand.get("given"), cand.get("surname"))
    b["birth"] = year_score(our.get("birth_year"), cand.get("birth_year"))
    b["death"] = year_score(our.get("death_year"), cand.get("death_year"))
    b["place"] = place_score(our.get("birth_place"), cand.get("birth_place"))
    b["parents"] = rel_name_overlap(our.get("parents"), cand.get("parents"))
    b["spouses"] = rel_name_overlap(our.get("spouses"), cand.get("spouses"))
    # weighted average over the signals that are present
    weights = {"name":3.0, "birth":2.0, "death":1.0, "place":1.0, "parents":2.0, "spouses":1.5}
    num = den = 0.0
    for k, w in weights.items():
        v = b.get(k)
        if v is not None:
            num += w * v; den += w
    score = num / den if den else 0.0
    # hard gate: a real match needs a decent name agreement
    if b["name"] < 0.5: score = min(score, 0.4)
    return round(score, 3), b

def classify(score):
    if score >= 0.85: return "confident"
    if score >= 0.65: return "probable"
    if score >= 0.5:  return "possible"
    return "weak"

# ---------- our-tree extraction ----------
def our_person_view(pid, P, F):
    p = P[pid]
    def fam_names(fid, roles):
        f = F.get(fid) or {}
        out = []
        for r in roles:
            x = f.get(r)
            if isinstance(x, list):
                out += [P[c]["name"] for c in x if c in P]
            elif x and x in P:
                out.append(P[x]["name"])
        return out
    parents = fam_names(p.get("famc"), ["husband","wife"])
    spouses = []
    for fid in p.get("fams", []):
        f = F.get(fid) or {}
        sp = f.get("wife") if f.get("husband") == pid else f.get("husband")
        if sp and sp in P: spouses.append(P[sp]["name"])
    return {
        "given": p.get("given") or p["name"].rsplit(" ", 1)[0],
        "surname": p.get("surname") or (p["name"].rsplit(" ", 1)[-1] if " " in p["name"] else ""),
        "birth_year": (p.get("birth") or {}).get("year"),
        "death_year": (p.get("death") or {}).get("year"),
        "birth_place": (p.get("birth") or {}).get("place"),
        "parents": parents, "spouses": spouses,
    }

# ---------- self-test (run today, no API needed) ----------
if __name__ == "__main__":
    import sys, os
    # 1. unit checks on the scorer
    fred_ours = {"given":"Frederick Alexander","surname":"McNulty","birth_year":1882,
                 "birth_place":"Dublin, Ireland","parents":["Laurence Joseph McNulty","Frances Thompson"],"spouses":["Mary Elsie Bellamy"]}
    fred_fs   = {"given":"Fred","surname":"McNulty","birth_year":1882,
                 "birth_place":"North City, Dublin","parents":["Laurence McNulty","Fanny Thompson"],"spouses":["Elsie Bellamy"]}
    s, b = score_match(fred_ours, fred_fs)
    print("Frederick self-ish match:", s, classify(s), b)
    assert s >= 0.85, "should be confident"

    stranger = {"given":"Patrick","surname":"Duffy","birth_year":1876,"parents":["x"],"spouses":[]}
    s2, _ = score_match(fred_ours, stranger)
    print("Frederick vs stranger:", s2, classify(s2))
    assert s2 < 0.5, "should not match"

    # 2. if family-data.json is present, prove every person matches THEMSELVES strongly
    here = os.path.dirname(os.path.abspath(__file__))
    data = os.path.join(here, "..", "family-data.json")
    if os.path.exists(data):
        d = json.load(open(data, encoding="utf-8"))
        P, F = d["people"], d["families"]
        import random
        ids = [k for k in P if (P[k].get("birth") or {}).get("year")]
        sample = random.sample(ids, min(200, len(ids)))
        ok = 0
        for pid in sample:
            v = our_person_view(pid, P, F)
            cand = dict(v)  # identical candidate = should score ~1.0
            s, _ = score_match(v, cand)
            if s >= 0.85: ok += 1
        print(f"self-match sanity: {ok}/{len(sample)} scored confident against an identical candidate")
        assert ok >= len(sample) * 0.9
    print("ALL MATCH TESTS PASSED")
