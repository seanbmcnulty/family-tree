#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fs_sync.py — the orchestrator. Runs on YOUR machine.

For each person in family-data.json it queries FamilySearch, scores the
candidates with fs_match, and writes a human review report (HTML + JSON).
It NEVER changes the tree — review the report, mark the changes you accept,
then run apply_reviewed.py.

GUARDRAILS (enforced here):
  • Living people (born <100 yrs ago with no death record) are SKIPPED — not sent
    to FamilySearch — to protect your family's privacy. The Jeon branch and your
    kids are never queried.
  • Only names/years/places are sent as search terms; your tree is never uploaded.
  • Output is a proposal only. Nothing is written back without your approval step.

Usage:
  python fs_sync.py                 # full run (needs fs_config.json + login)
  python fs_sync.py --demo          # offline demo: scores a few people against
                                    #   synthetic FS results, no key needed
  python fs_sync.py --only P34,P9001  # just these people
  python fs_sync.py --limit 50      # cap how many to process
"""
from __future__ import annotations
import json, os, sys, argparse, datetime, html
import fs_match as M

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "family-data.json")

def load_data():
    d = json.load(open(DATA, encoding="utf-8"))
    return d, d["people"], d["families"]

def is_living(p):
    y = (p.get("birth") or {}).get("year")
    return bool(y and y > datetime.date.today().year - 100 and not p.get("death"))

def candidates_for(view, fs):
    return fs.search_tree(
        given=view["given"], surname=view["surname"],
        birth_year=view["birth_year"], birth_place=view["birth_place"],
        father=(M.norm(view["parents"][0]).split()[-1] if view.get("parents") else None),
        spouse=(view["spouses"][0].split()[0] if view.get("spouses") else None))

def diff_fields(our, cand):
    """what FamilySearch could add or where it disagrees."""
    out = []
    if our.get("birth_year") and cand.get("birth_year") and our["birth_year"] != cand["birth_year"]:
        out.append(("birth year", our["birth_year"], cand["birth_year"], "disagree"))
    if not our.get("death_year") and cand.get("death_year"):
        out.append(("death year", "—", cand["death_year"], "ADD"))
    if not our.get("birth_place") and cand.get("birth_place"):
        out.append(("birth place", "—", cand["birth_place"], "ADD"))
    def last_tok(n):
        t = M.norm(n).split()
        return t[-1] if t else ""
    our_par = {last_tok(n) for n in our.get("parents", []) if n}
    cand_par = [n for n in cand.get("parents", []) if last_tok(n) and last_tok(n) not in our_par]
    for n in cand_par:
        out.append(("parent", "—", n, "ADD?"))
    return out

def run(args):
    d, P, F = load_data()
    ids = list(P.keys())
    if args.only:
        ids = [x.strip() for x in args.only.split(",") if x.strip() in P]
    skipped_living = 0
    results = []

    if args.demo:
        fs = DemoFS()
    else:
        import fs_client
        cfgp = os.path.join(HERE, "fs_config.json")
        if not os.path.exists(cfgp):
            sys.exit("Create fs_config.json (copy fs_config.example.json and add your client_id).")
        fs = fs_client.FamilySearch(json.load(open(cfgp)))
        fs.authenticate()

    processed = 0
    for pid in ids:
        p = P[pid]
        if is_living(p):
            skipped_living += 1; continue
        view = M.our_person_view(pid, P, F)
        if not view["surname"] and not view["birth_year"]:
            continue
        try:
            cands = candidates_for(view, fs)
        except Exception as e:
            print(f"  ! search failed for {pid} ({p['name']}): {e}")
            continue
        scored = []
        for c in cands:
            s, b = M.score_match(view, c)
            scored.append((s, M.classify(s), c, b, diff_fields(view, c)))
        scored.sort(key=lambda x: -x[0])
        top = scored[0] if scored else None
        if top and top[0] >= 0.5:
            results.append({"pid": pid, "name": p["name"], "our": view,
                            "score": top[0], "verdict": top[1], "cand": top[2],
                            "breakdown": top[3], "diffs": top[4]})
        processed += 1
        if processed % 25 == 0: print(f"  …{processed} processed")
        if args.limit and processed >= args.limit: break

    results.sort(key=lambda r: -r["score"])
    write_report(results, processed, skipped_living, args.demo)
    json.dump(results, open(os.path.join(HERE, "fs_review.json"), "w"),
              ensure_ascii=False, indent=1)
    print(f"\nDone. {len(results)} candidate matches from {processed} people "
          f"({skipped_living} living skipped).")
    print("Open fs_review.html to review; accepted rows feed apply_reviewed.py.")

def write_report(results, processed, skipped, demo):
    rows = []
    for i, r in enumerate(results):
        diffs = "".join(
            f"<div class='d {d[3].lower().replace('?','')}'>"
            f"<b>{html.escape(d[0])}</b>: ours <code>{html.escape(str(d[1]))}</code> → "
            f"FS <code>{html.escape(str(d[2]))}</code> <span class=tag>{d[3]}</span></div>"
            for d in r["diffs"]) or "<i>vitals agree; FS could confirm/source</i>"
        rows.append(f"""
        <tr class="{r['verdict']}">
          <td><input type=checkbox data-i="{i}"></td>
          <td><b>{html.escape(r['name'])}</b><br><small>{r['pid']} · b.{r['our'].get('birth_year') or '?'}</small></td>
          <td><span class=score>{r['score']:.2f}</span><br><small>{r['verdict']}</small></td>
          <td>{html.escape(r['cand'].get('given',''))} {html.escape(r['cand'].get('surname',''))}
              <br><small>FS id {html.escape(str(r['cand'].get('fs_id','—')))} · b.{r['cand'].get('birth_year') or '?'}</small></td>
          <td>{diffs}</td>
        </tr>""")
    doc = f"""<!doctype html><meta charset=utf-8><title>FamilySearch review</title>
<style>body{{font:14px Georgia,serif;max-width:1100px;margin:24px auto;color:#2b2620}}
h1{{color:#2e5339}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ddd;padding:8px;vertical-align:top;text-align:left}}
th{{background:#2e5339;color:#fff}}tr.confident{{background:#eef6ec}}tr.probable{{background:#fbf6e8}}tr.possible{{background:#fff}}
.score{{font-size:18px;color:#2e5339;font-weight:bold}}code{{background:#f1ece0;padding:1px 4px;border-radius:3px}}
.tag{{font-size:10px;background:#b08d3e;color:#fff;padding:1px 5px;border-radius:8px}}
.d.add .tag,.d.add_ .tag{{background:#2e7d32}}.d.disagree .tag{{background:#a3302d}}
.note{{background:#faf6ea;border-left:4px solid #b08d3e;padding:10px 14px;margin:14px 0}}
button{{background:#2e5339;color:#fff;border:none;padding:10px 18px;border-radius:8px;font-size:14px;cursor:pointer}}</style>
<h1>FamilySearch match review {'(DEMO — synthetic data)' if demo else ''}</h1>
<div class=note>{processed} people checked · {skipped} living skipped for privacy · {len(results)} candidate matches.
Tick the rows whose FamilySearch changes you accept, click <b>Export accepted</b>, save the file as
<code>fs_accepted.json</code> next to these scripts, then run <code>python apply_reviewed.py</code>.
Nothing changes in your tree until you do that.</div>
<p><button onclick="exp()">Export accepted</button></p>
<table><tr><th>✓</th><th>Our person</th><th>Score</th><th>FamilySearch candidate</th><th>What FS offers</th></tr>
{''.join(rows)}</table>
<script>
const R={json.dumps([{ 'pid':r['pid'],'fs_id':r['cand'].get('fs_id'),'diffs':r['diffs'],'score':r['score']} for r in results])};
function exp(){{const acc=[];document.querySelectorAll('input[type=checkbox]').forEach(c=>{{if(c.checked)acc.push(R[+c.dataset.i]);}});
const blob=new Blob([JSON.stringify(acc,null,1)],{{type:'application/json'}});const a=document.createElement('a');
a.href=URL.createObjectURL(blob);a.download='fs_accepted.json';a.click();}}
</script>"""
    open(os.path.join(HERE, "fs_review.html"), "w", encoding="utf-8").write(doc)

# ---------- offline demo source ----------
class DemoFS:
    """Returns plausible synthetic FamilySearch hits so you can see the pipeline
    work with no API key. Keyed to a few known people; everyone else gets a near-self."""
    SEED = {
        "Frederick Alexander McNulty": {"given":"Frederick A","surname":"McNulty","birth_year":1882,
            "birth_place":"North City, Dublin, Ireland","death_year":1965,
            "parents":["Laurence McNulty","Frances Thompson"],"spouses":["Mary Elsie Bellamy"],"fs_id":"L123-DEMO"},
        "Laurence Joseph McNulty": {"given":"Laurence","surname":"McNulty","birth_year":1840,
            "birth_place":"Dublin, Ireland","parents":["Thomas McNulty","Bridget Kelly"],
            "spouses":["Frances Thompson"],"fs_id":"L456-DEMO"},
    }
    def authenticate(self): pass
    def search_tree(self, given, surname, birth_year=None, **kw):
        for full, rec in self.SEED.items():
            if M.norm(surname) and M.norm(surname) in M.norm(full) and M.canon_given(given)[0] in M.norm(full):
                return [rec]
        # generic: echo a slightly-noisier self so most rows show "vitals agree"
        return [{"given":given, "surname":surname, "birth_year":birth_year,
                 "birth_place":None, "death_year":None, "parents":[], "spouses":[], "fs_id":"FS-DEMO"}]

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--only")
    ap.add_argument("--limit", type=int)
    run(ap.parse_args())
