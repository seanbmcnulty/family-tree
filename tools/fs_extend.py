#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fs_extend.py - grow the tree from CONFIRMED FamilySearch matches.

For each anchor (a person we confirmed maps to a FamilySearch id), this fetches
that person's ancestry and attached sources from FamilySearch, then walks the
pedigree: at each ancestor slot it looks at the SAME slot in our own tree.
  - slot empty in ours + FS has a person  -> propose a NEW ancestor to add
  - slot filled + names agree             -> confirmation (nothing to do)
  - slot filled + names differ            -> CONFLICT, flagged for your eyes
It also lists the record sources FamilySearch has attached to each anchor
(baptisms etc.) - those are your manual research leads.

Writes fs_extend_review.html + fs_extend.json. Changes NOTHING until you review
and run apply_extend.py. Living people are never involved (anchors are ancestors).

  python fs_extend.py          # real run (needs fs_config.json + login)
  python fs_extend.py --demo   # offline demo with synthetic ancestry
"""
from __future__ import annotations
import json, os, sys, argparse, html, datetime
import fs_match as M

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "family-data.json")
CONF = os.path.join(HERE, "fs_confirmed.json")

def load_data():
    d = json.load(open(DATA, encoding="utf-8"))
    return d, d["people"], d["families"]

def parent_slots(pid, P, F):
    """Return (father_pid_or_None, mother_pid_or_None) for a person in our tree."""
    f = F.get((P.get(pid) or {}).get("famc"))
    if not f:
        return (None, None)
    return (f.get("husband"), f.get("wife"))

def name_agrees(a, b):
    return M.name_score(M.norm(a).rsplit(" ", 1)[0], (M.norm(a).rsplit(" ", 1)[-1] if " " in M.norm(a) else ""),
                        M.norm(b).rsplit(" ", 1)[0], (M.norm(b).rsplit(" ", 1)[-1] if " " in M.norm(b) else "")) >= 0.55

def run(args):
    d, P, F = load_data()
    if not os.path.exists(CONF):
        sys.exit("Missing fs_confirmed.json (list of {fs_id, pid} anchors).")
    anchors = json.load(open(CONF, encoding="utf-8"))

    if args.demo:
        fs = DemoFS()
    else:
        import fs_client
        cfgp = os.path.join(HERE, "fs_config.json")
        if not os.path.exists(cfgp):
            sys.exit("Create fs_config.json first.")
        fs = fs_client.FamilySearch(json.load(open(cfgp)))
        fs.authenticate()

    proposals, confirmations, conflicts, sources = [], [], [], []
    for a in anchors:
        anchor_pid, anchor_fs = a["pid"], a["fs_id"]
        if anchor_pid not in P:
            continue
        try:
            anc = fs.get_ancestry(anchor_fs, generations=5)
            srcs = fs.get_sources(anchor_fs)
        except Exception as e:
            print("  ! ancestry/sources failed for %s (%s): %s" % (anchor_fs, P[anchor_pid]["name"], e))
            continue
        for s in srcs:
            sources.append({"anchor": P[anchor_pid]["name"], "anchor_pid": anchor_pid,
                            "title": s.get("title"), "citation": s.get("citation")})
        # map ascendancy number -> our pid, starting from the anchor (ahnen 1)
        ah2pid = {1: anchor_pid}
        for person in anc:
            k = person["ahnen"]
            if k == 1:
                continue
            child_ahnen = k // 2
            child_pid = ah2pid.get(child_ahnen)
            role = "father" if k % 2 == 0 else "mother"
            fsname = person.get("name") or ""
            if not fsname:
                continue
            if child_pid is None:
                continue  # child not yet resolved in our tree; skip this branch
            fa, mo = parent_slots(child_pid, P, F)
            existing = fa if role == "father" else mo
            if existing and existing in P:
                if name_agrees(P[existing]["name"], fsname):
                    ah2pid[k] = existing  # confirmed, keep walking up this branch
                    confirmations.append({"our": P[existing]["name"], "our_pid": existing,
                                          "fs": fsname, "fs_id": person["fs_id"]})
                else:
                    conflicts.append({"child": P[child_pid]["name"], "role": role,
                                      "our": P[existing]["name"], "fs": fsname, "fs_id": person["fs_id"]})
            else:
                # empty slot -> NEW ancestor to propose
                proposals.append({
                    "ahnen": k, "child_pid": child_pid, "child_name": P[child_pid]["name"],
                    "role": role, "fs_id": person["fs_id"], "name": fsname,
                    "given": person.get("given"), "surname": person.get("surname"),
                    "birth_year": person.get("birth_year"), "birth_place": person.get("birth_place"),
                    "death_year": person.get("death_year"), "gender": person.get("gender"),
                })
                # a proposed person can itself be a child for the next generation up:
                # give it a temporary key so its parents (2k, 2k+1) can attach on accept
                ah2pid[k] = "NEW:%s" % person["fs_id"]

    proposals.sort(key=lambda x: x["ahnen"])
    out = {"proposals": proposals, "confirmations": confirmations,
           "conflicts": conflicts, "sources": sources}
    json.dump(out, open(os.path.join(HERE, "fs_extend.json"), "w"),
              ensure_ascii=False, indent=1)
    write_report(out, args.demo)
    print("\nDone. %d NEW ancestors proposed, %d confirmations, %d conflicts, %d attached sources."
          % (len(proposals), len(confirmations), len(conflicts), len(sources)))
    print("Open fs_extend_review.html to review; accepted rows feed apply_extend.py.")

def write_report(out, demo):
    def rows(props):
        r = []
        for i, p in enumerate(props):
            r.append("<tr><td><input type=checkbox data-i='%d'></td>"
                     "<td><b>%s</b><br><small>b.%s %s</small></td>"
                     "<td>%s of <b>%s</b></td>"
                     "<td><small>FS %s</small></td></tr>" % (
                i, html.escape(p["name"]), p.get("birth_year") or "?",
                html.escape(p.get("birth_place") or ""), html.escape(p["role"]),
                html.escape(p["child_name"]), html.escape(str(p.get("fs_id")))))
        return "".join(r)
    conf = "".join("<li>%s = FS <i>%s</i></li>" % (html.escape(c["our"]), html.escape(c["fs"]))
                   for c in out["confirmations"])
    confl = "".join("<li><b>%s</b>'s %s: ours <b>%s</b> vs FS <b>%s</b></li>" % (
        html.escape(c["child"]), html.escape(c["role"]), html.escape(c["our"]), html.escape(c["fs"]))
        for c in out["conflicts"])
    srcs = "".join("<li><b>%s</b> - %s <small>%s</small></li>" % (
        html.escape(s["anchor"]), html.escape(s.get("title") or "(untitled source)"),
        html.escape((s.get("citation") or "")[:160])) for s in out["sources"])
    doc = """<!doctype html><meta charset=utf-8><title>FamilySearch - extend tree</title>
<style>body{font:14px Georgia,serif;max-width:1000px;margin:24px auto;color:#2b2620}
h1,h2{color:#2e5339}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:8px;text-align:left}
th{background:#2e5339;color:#fff}.note{background:#faf6ea;border-left:4px solid #b08d3e;padding:10px 14px;margin:14px 0}
.warn{background:#fbeceb;border-left:4px solid #a3302d;padding:10px 14px}button{background:#2e5339;color:#fff;border:none;padding:10px 18px;border-radius:8px;cursor:pointer}
li{margin:4px 0}</style>
<h1>FamilySearch - grow the tree """ + ("(DEMO)" if demo else "") + """</h1>
<div class=note>These are ancestors FamilySearch has in slots your tree leaves <b>empty</b>. Tick the ones you
accept, click <b>Export accepted</b>, save as <code>fs_extend_accepted.json</code>, then run
<code>python apply_extend.py</code>. Nothing changes until you do.</div>
<h2>New ancestors to add (""" + str(len(out["proposals"])) + """)</h2>
<p><button onclick="exp()">Export accepted</button></p>
<table><tr><th>&#10003;</th><th>Person</th><th>Position</th><th>Source</th></tr>""" + rows(out["proposals"]) + """</table>
""" + ("<h2>Conflicts to check</h2><div class=warn><ul>" + confl + "</ul></div>" if out["conflicts"] else "") + """
<h2>Confirmations (already in your tree, verified)</h2><ul>""" + (conf or "<li>none</li>") + """</ul>
<h2>Records FamilySearch has attached (research leads)</h2><ul>""" + (srcs or "<li>none</li>") + """</ul>
<script>
const R=""" + json.dumps(out["proposals"]) + """;
function exp(){const a=[];document.querySelectorAll('input[type=checkbox]').forEach(c=>{if(c.checked)a.push(R[+c.dataset.i]);});
const b=new Blob([JSON.stringify(a,null,1)],{type:'application/json'});const u=document.createElement('a');
u.href=URL.createObjectURL(b);u.download='fs_extend_accepted.json';u.click();}
</script>"""
    open(os.path.join(HERE, "fs_extend_review.html"), "w", encoding="utf-8").write(doc)

class DemoFS:
    """Synthetic ancestry so you can see extension work with no key: pretends
    FamilySearch has Thomas McNulty's wife and John Arthur Thompson's wife."""
    def authenticate(self): pass
    def get_sources(self, fs_id):
        if fs_id == "LRF8-Y6T":
            return [{"title": "Ireland, Civil Registration Births, 1882 - Frederick McNulty",
                     "citation": "GRO Dublin North, 1882"}]
        return []
    def get_ancestry(self, fs_id, generations=5):
        if fs_id != "LRF8-Y6T":
            return [{"ahnen": 1, "fs_id": fs_id, "name": "Anchor"}]
        return [
            {"ahnen": 1, "fs_id": "LRF8-Y6T", "name": "Frederick Alexander McNulty"},
            {"ahnen": 2, "fs_id": "96QC-H74", "name": "Laurence Joseph McNulty"},
            {"ahnen": 3, "fs_id": "LFRA-N1", "name": "Lavinia Frances Thompson"},
            {"ahnen": 4, "fs_id": "M8LT-ZTK", "name": "Thomas McNulty"},
            {"ahnen": 5, "fs_id": "DEMO-WIFE1", "name": "Mary Byrne", "given": "Mary",
             "surname": "Byrne", "birth_year": 1822, "birth_place": "Dublin, Ireland", "gender": "FEMALE"},
            {"ahnen": 6, "fs_id": "DEMO-JAT", "name": "John Arthur Thompson"},
            {"ahnen": 7, "fs_id": "DEMO-WIFE2", "name": "Letitia Kane", "given": "Letitia",
             "surname": "Kane", "birth_year": 1825, "birth_place": "Dublin, Ireland", "gender": "FEMALE"},
        ]

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    run(ap.parse_args())
