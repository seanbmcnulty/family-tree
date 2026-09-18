#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fs_client.py - FamilySearch API client (OAuth2 + search + ancestry + sources).
Runs on YOUR machine. Authorization-code flow only; your password is never stored."""
from __future__ import annotations
import time, webbrowser, threading, urllib.parse, http.server, sys, re

try:
    import requests
except ImportError:
    sys.exit("Please `pip install requests` first.")

ENV = {
    "production":  {"api": "https://api.familysearch.org",
                    "ident": "https://ident.familysearch.org/cis-web/oauth2/v3"},
    "beta":        {"api": "https://apibeta.familysearch.org",
                    "ident": "https://identbeta.familysearch.org/cis-web/oauth2/v3"},
    "integration": {"api": "https://api-integ.familysearch.org",
                    "ident": "https://identint.familysearch.org/cis-web/oauth2/v3"},
}

def _year(s):
    m = re.findall(r"\b(\d{4})\b", s or "")
    return int(m[-1]) if m else None

def _display_name(p):
    try:
        return p["names"][0]["nameForms"][0]["fullText"]
    except Exception:
        return ""

def _coarse_place(pl):
    if not pl:
        return pl
    parts = [x.strip() for x in pl.split(",") if x.strip()]
    parts = [re.sub(r"^\d+\s+", "", p) for p in parts]
    return ", ".join(parts[-2:]) if len(parts) > 2 else ", ".join(parts)

class FamilySearch:
    def __init__(self, cfg):
        self.client_id = cfg["client_id"]
        self.redirect_uri = cfg.get("redirect_uri", "http://localhost:8765/callback")
        self.env = ENV[cfg.get("environment", "beta")]
        self.client_secret = cfg.get("client_secret")
        self.token = None
        self.session = requests.Session()
        self.session.headers["Accept"] = "application/x-gedcomx-v1+json"
        self.min_interval = 1.0 / cfg.get("requests_per_second", 2)
        self._last = 0.0

    def authenticate(self):
        code_holder = {}
        port = urllib.parse.urlparse(self.redirect_uri).port or 8765
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                q = urllib.parse.urlparse(self.path).query
                code_holder["code"] = urllib.parse.parse_qs(q).get("code", [None])[0]
                self.send_response(200); self.end_headers()
                self.wfile.write(b"<h2>FamilySearch authorization received. You can close this tab.</h2>")
            def log_message(self, *a): pass
        srv = http.server.HTTPServer(("localhost", port), H)
        t = threading.Thread(target=srv.handle_request, daemon=True); t.start()
        auth_url = (self.env["ident"] + "/authorization?response_type=code"
                    + "&client_id=" + urllib.parse.quote(self.client_id)
                    + "&redirect_uri=" + urllib.parse.quote(self.redirect_uri))
        print("Opening your browser to sign in to FamilySearch...")
        print("If it does not open, paste this URL:\n  " + auth_url)
        webbrowser.open(auth_url)
        t.join(timeout=300)
        code = code_holder.get("code")
        if not code:
            sys.exit("Did not receive an authorization code (timed out).")
        data = {"grant_type": "authorization_code", "code": code,
                "client_id": self.client_id, "redirect_uri": self.redirect_uri}
        if self.client_secret:
            data["client_secret"] = self.client_secret
        r = self.session.post(self.env["ident"] + "/token", data=data)
        r.raise_for_status()
        self.token = r.json()["access_token"]
        self.session.headers["Authorization"] = "Bearer " + self.token
        print("Authenticated with FamilySearch.")

    def _throttle(self):
        dt = time.time() - self._last
        if dt < self.min_interval:
            time.sleep(self.min_interval - dt)
        self._last = time.time()

    def _get(self, path, params=None, accept=None):
        self._throttle()
        headers = {"Accept": accept} if accept else None
        for attempt in range(4):
            r = self.session.get(self.env["api"] + path, params=params, headers=headers, timeout=30)
            if r.status_code == 429:
                time.sleep(2 ** attempt); continue
            if r.status_code == 401:
                sys.exit("Token expired/invalid - re-run to re-authenticate.")
            if r.status_code in (204, 404):
                return None
            if 400 <= r.status_code < 500:
                body = (r.text or "")[:300].replace("\n", " ")
                raise RuntimeError("HTTP %d from FamilySearch: %s | %s"
                                   % (r.status_code, body or "(no body)", r.url))
            r.raise_for_status()
            return r.json()
        return None

    def search_tree(self, given, surname, birth_year=None, birth_place=None,
                    father=None, mother=None, spouse=None, count=8):
        params = {"count": count}
        if given:   params["q.givenName"] = given
        if surname: params["q.surname"] = surname
        if birth_year:
            params["q.birthLikeDate.from"] = str(birth_year - 3)
            params["q.birthLikeDate.to"] = str(birth_year + 3)
        cp = _coarse_place(birth_place)
        if cp: params["q.birthLikePlace"] = cp
        if father:  params["q.fatherSurname"] = father
        if spouse:  params["q.spouseGivenName"] = spouse
        data = self._get("/platform/tree/search", params,
                         accept="application/x-gedcomx-atom+json")
        return self._parse_search(data)

    def get_ancestry(self, fs_id, generations=4):
        """Return the ancestral pedigree of a person as a list of ancestor views,
        each with an 'ahnen' ascendancy number (1=self, 2=father, 3=mother, ...)."""
        data = self._get("/platform/tree/ancestry",
                         {"person": fs_id, "generations": generations})
        out = []
        if not data:
            return out
        for p in data.get("persons", []):
            disp = p.get("display", {}) or {}
            ahnen = disp.get("ascendancyNumber")
            try:
                ahnen = int(ahnen)
            except (TypeError, ValueError):
                continue
            out.append({
                "ahnen": ahnen, "fs_id": p.get("id"),
                "name": disp.get("name") or _display_name(p),
                "given": (disp.get("name") or "").rsplit(" ", 1)[0],
                "surname": (disp.get("name") or "").rsplit(" ", 1)[-1] if " " in (disp.get("name") or "") else "",
                "birth_year": _year(disp.get("birthDate")),
                "birth_place": disp.get("birthPlace"),
                "death_year": _year(disp.get("deathDate")),
                "gender": (disp.get("gender") or "").upper(),
            })
        out.sort(key=lambda x: x["ahnen"])
        return out

    def get_sources(self, fs_id):
        """Return attached source descriptions (titles/citations) for a person."""
        data = self._get("/platform/tree/persons/%s/sources" % fs_id)
        out = []
        if not data:
            return out
        for sd in data.get("sourceDescriptions", []):
            title = ""
            if sd.get("titles"):
                title = sd["titles"][0].get("value", "")
            cite = ""
            if sd.get("citations"):
                cite = sd["citations"][0].get("value", "")
            out.append({"title": title, "citation": cite,
                        "about": sd.get("about"), "id": sd.get("id")})
        return out

    def _parse_search(self, data):
        out = []
        if not data:
            return out
        for entry in data.get("entries", []):
            gx = (entry.get("content", {}) or {}).get("gedcomx", {}) or {}
            persons = gx.get("persons", [])
            if not persons:
                continue
            out.append(self._person_view(persons[0], gx))
        return out

    def _person_view(self, person, gx):
        names = person.get("names", [])
        given = surname = ""
        if names:
            for part in names[0].get("nameForms", [{}])[0].get("parts", []):
                if part.get("type", "").endswith("Given"): given = part.get("value", "")
                if part.get("type", "").endswith("Surname"): surname = part.get("value", "")
        by = dy = bplace = None
        for f in person.get("facts", []):
            t = f.get("type", "")
            if t.endswith("/Birth"):
                by = _year((f.get("date") or {}).get("original") or "")
                bplace = (f.get("place") or {}).get("original")
            if t.endswith("/Death"):
                dy = _year((f.get("date") or {}).get("original") or "")
        parents, spouses = [], []
        idmap = {p["id"]: _display_name(p) for p in gx.get("persons", []) if p.get("id")}
        for rel in gx.get("relationships", []):
            rt = rel.get("type", "")
            p1 = (rel.get("person1") or {}).get("resourceId")
            p2 = (rel.get("person2") or {}).get("resourceId")
            if rt.endswith("ParentChild") and p2 == person.get("id") and p1 in idmap:
                parents.append(idmap[p1])
            if rt.endswith("Couple"):
                other = p2 if p1 == person.get("id") else (p1 if p2 == person.get("id") else None)
                if other in idmap: spouses.append(idmap[other])
        return {"fs_id": person.get("id"), "given": given, "surname": surname,
                "birth_year": by, "death_year": dy, "birth_place": bplace,
                "parents": parents, "spouses": spouses}
