"""Géolocalisation de n'importe quelle fiche (ressource, revue, événement, opportunité).

Stratégie, de la plus précise à la plus grossière (la première qui répond gagne) :
  1. lieu explicite (ville, adresse d'un événement ou d'une offre)  → Nominatim       « lieu »
  2. dépôt GitHub : localisation déclarée par le propriétaire          → API GitHub      « organisation »
  3. site web : organisme dont c'est le site officiel (siège)          → Wikidata P856   « organisation »
  4. langue peu dotée traitée par la ressource                         → languages.py    « langue »
  5. pays déclaré / domaine national (.fr, .cat, .eus…)                → data/pays.json  « pays »

Tous les appels réseau passent par un cache disque (data/geocache.json) et des quotas
par exécution : la carte se complète au fil des jours sans surcharger les services.
"""
from __future__ import annotations

import os
import re
import time
from urllib.parse import urlparse

from geo import country_code, country_geo
from languages import detect_languages

GENERIC_TLDS = {"com", "org", "net", "io", "ai", "co", "me", "info", "dev", "app", "edu", "gov", "int", "eu",
                "tv", "xyz", "site", "tech", "online", "science", "page", "space", "cloud", "github", "ly"}
# Domaines nationaux / régionaux (en plus des ccTLD à deux lettres)
SPECIAL_TLDS = {"cat": ("Catalogne", 41.3874, 2.1686), "eus": ("Pays basque", 43.263, -2.935),
                "gal": ("Galice", 42.8782, -8.5448), "corsica": ("Corse", 42.3063, 9.15),
                "bzh": ("Bretagne", 48.1173, -1.6778), "scot": ("Écosse", 55.9533, -3.1883)}
# Sièges des principaux éditeurs scientifiques (revues) — repli quand le site n'est pas dans Wikidata
PUBLISHERS = {
    "elsevier": ("Amsterdam", 52.3676, 4.9041), "springer": ("Berlin", 52.52, 13.405),
    "mit press": ("Cambridge (Massachusetts)", 42.3601, -71.0942), "cambridge": ("Cambridge (Royaume-Uni)", 52.2053, 0.1218),
    "oxford": ("Oxford", 51.752, -1.2577), "ieee": ("New York", 40.7128, -74.006), "acm": ("New York", 40.7128, -74.006),
    "bmc": ("Londres", 51.5072, -0.1276), "wiley": ("Hoboken (New Jersey)", 40.744, -74.0324),
    "taylor": ("Abingdon (Royaume-Uni)", 51.6709, -1.283), "de gruyter": ("Berlin", 52.52, 13.405),
    "benjamins": ("Amsterdam", 52.3676, 4.9041), "mdpi": ("Bâle", 47.5596, 7.5886), "frontiers": ("Lausanne", 46.5197, 6.6323),
    "plos": ("San Francisco", 37.7749, -122.4194), "sage": ("Thousand Oaks (Californie)", 34.1706, -118.8376),
    "association for computational linguistics": ("Stroudsburg (Pennsylvanie)", 40.9868, -75.1946),
}
# Plateformes d'hébergement : leur siège ne dit rien de la ressource → on ne s'en sert pas
PLATFORMS = {"huggingface.co", "github.com", "github.io", "kaggle.com", "zenodo.org", "figshare.com", "drive.google.com",
             "docs.google.com", "sites.google.com", "arxiv.org", "doi.org", "wikicfp.com", "medium.com",
             "linkedin.com", "twitter.com", "x.com", "youtube.com", "gitlab.com", "bitbucket.org",
             "sourceforge.net", "osf.io", "researchgate.net", "academia.edu", "paperswithcode.com",
             "live.european-language-grid.eu", "european-language-grid.eu", "remotive.com", "arbeitnow.com",
             "nlppeople.com", "theses.fr", "hal.science", "archives-ouvertes.fr", "openreview.net"}


class _Skip(Exception):
    """Quota d'un service atteint : abandon sans mise en cache."""


class Locator:
    def __init__(self, http, geocoder, cfg: dict | None = None):
        self.http, self.geocoder = http, geocoder
        self.cache = geocoder.cache  # même fichier que le géocodage Nominatim
        cfg = cfg or {}
        self.budget = {"wikidata": cfg.get("wikidata_per_run", 80), "github": cfg.get("github_owner_per_run", 40)}
        self.stats = {"lieu": 0, "organisation": 0, "langue": 0, "pays": 0, "aucune": 0}

    # ── briques ──
    def place(self, text: str | None) -> dict | None:
        """Ville / adresse en clair → coordonnées (Nominatim)."""
        if not text or re.search(r"\b(online|virtual|remote|en ligne|tba|n/a|anywhere|worldwide)\b", text, re.I):
            return None
        g = self.geocoder.lookup(text)
        if g:
            return {"lat": g["lat"], "lng": g["lng"], "city": g.get("label") or text,
                    "region": self._region_label(text), "geo_precision": "lieu"}
        return None

    def _region_label(self, text: str) -> str:
        iso = country_code(text)
        g = country_geo(iso)
        return g["region"] if g else text.split(",")[-1].strip()

    def github_owner(self, url: str) -> dict | None:
        m = re.match(r"https?://(?:www\.)?github\.com/([^/#?]+)", url or "")
        if not m:
            return None
        owner = m.group(1).lower()
        key = f"gh:{owner}"
        if key not in self.cache:
            if self.budget["github"] <= 0:
                return None
            self.budget["github"] -= 1
            headers = {"Accept": "application/vnd.github+json"}
            if os.getenv("GITHUB_TOKEN"):
                headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
            try:
                data = self.http.get(f"https://api.github.com/users/{owner}", headers=headers, retries=0).json()
                self.cache[key] = {"location": (data.get("location") or "").strip() or None,
                                   "name": data.get("name") or owner}
            except Exception as ex:
                # 404 = compte supprimé : on mémorise ; autre erreur (quota, réseau) : on réessaiera plus tard
                if "404" in str(ex):
                    self.cache[key] = None
                else:
                    return None
            self.geocoder.dirty = True
            time.sleep(0.3)
        info = self.cache.get(key)
        if info and info.get("location"):
            g = self.place(info["location"])
            if g:
                return {**g, "geo_precision": "organisation", "geo_source": f"GitHub · {info['name']}"}
        return None

    def hf_owner(self, url: str) -> dict | None:
        """Organisation Hugging Face → nom complet (API HF) → siège (Wikidata). Les comptes
        personnels ne sont jamais localisés (vie privée)."""
        m = re.match(r"https?://huggingface\.co/(?:datasets/|spaces/)?([^/#?]+)/", url or "")
        if not m:
            return None
        owner = m.group(1)
        key = f"hf:{owner.lower()}"
        if key not in self.cache:
            if self.budget["github"] <= 0:  # même quota que les comptes GitHub
                return None
            self.budget["github"] -= 1
            try:
                r = self.http.s.get(f"https://huggingface.co/api/organizations/{owner}/overview", timeout=20)
                self.cache[key] = {"fullname": (r.json().get("fullname") or "").strip(" _")} if r.status_code == 200 else None
            except Exception:
                return None
            self.geocoder.dirty = True
            time.sleep(0.3)
        info = self.cache.get(key)
        if not info or not info.get("fullname"):
            return None
        g = self.wikidata_name(info["fullname"])
        if g:
            return {**g, "geo_precision": "organisation", "geo_source": f"Hugging Face · {info['fullname']}"}
        return None

    def wikidata_name(self, name: str) -> dict | None:
        """Organisme (entreprise, université, institut…) trouvé par son nom dans Wikidata → siège."""
        norm = re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()
        key = f"wdn:{norm}"
        if key in self.cache:
            return self.cache[key]
        if self.budget["wikidata"] <= 0 or len(norm) < 3:
            return None
        self.budget["wikidata"] -= 1
        q = f"""SELECT ?item ?itemLabel ?enLabel ?coord ?hqcoord ?hqLabel ?cLabel WHERE {{
          SERVICE wikibase:mwapi {{ bd:serviceParam wikibase:endpoint "www.wikidata.org"; wikibase:api "EntitySearch";
            mwapi:search "{name.replace('"', ' ')}"; mwapi:language "en". ?item wikibase:apiOutputItem mwapi:item.
            ?num wikibase:apiOrdinal true. }}
          FILTER(?num < 3)
          ?item wdt:P31/wdt:P279* wd:Q43229 .
          OPTIONAL {{ ?item rdfs:label ?enLabel FILTER(LANG(?enLabel) = "en") }}
          OPTIONAL {{ ?item wdt:P17 ?c }}
          OPTIONAL {{ ?item wdt:P625 ?coord }} OPTIONAL {{ ?item wdt:P159 ?hq . ?hq wdt:P625 ?hqcoord }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "fr,en". }} }} LIMIT 6"""
        try:
            time.sleep(1.5)
            r = self.http.s.get("https://query.wikidata.org/sparql", params={"query": q}, timeout=40,
                                headers={"Accept": "application/sparql-results+json"})
            if r.status_code == 429:
                self.budget["wikidata"] = 0
                return None
            r.raise_for_status()
            rows = r.json()["results"]["bindings"]
        except Exception as ex:
            print(f"    [wikidata] « {name} » : {str(ex)[:100]}")
            return None
        res = None
        def n(x: str) -> str:
            return re.sub(r"[^a-z0-9]+", " ", (x or "").lower()).strip()
        for b in rows:
            coord = b.get("coord") or b.get("hqcoord")
            labels = {n(b.get("itemLabel", {}).get("value")), n(b.get("enLabel", {}).get("value"))} - {""}
            # le nom doit correspondre (« Mistral AI » ≠ « Poste Air Cargo » renvoyé par la recherche floue)
            if not coord or not any(l == norm or (len(norm) > 5 and (norm in l or l in norm) and len(l) > 5) for l in labels):
                continue
            lng, lat = coord["value"].removeprefix("Point(").rstrip(")").split()[:2]
            org = b.get("itemLabel", {}).get("value", name)
            res = {"lat": round(float(lat), 4), "lng": round(float(lng), 4),
                   "city": b.get("hqLabel", {}).get("value") or org,
                   "region": b.get("cLabel", {}).get("value") or org, "geo_source": f"Wikidata · {org}"}
            break
        self.cache[key] = res
        self.geocoder.dirty = True
        return res

    def wikidata_site(self, url: str) -> dict | None:
        """Organisme dont `url` est le site officiel (P856) → coordonnées du siège (Wikidata)."""
        host = (urlparse(url or "").hostname or "").lower().removeprefix("www.")
        if not host or any(host == p or host.endswith("." + p) for p in PLATFORMS):
            return None
        # on essaie le domaine complet puis ses parents : direct.mit.edu → mit.edu
        parts = host.split(".")
        candidates = [".".join(parts[i:]) for i in range(len(parts) - 1)]
        for dom in candidates:
            key = f"wd:{dom}"
            if key not in self.cache:
                if self.budget["wikidata"] <= 0:
                    return None
                self.budget["wikidata"] -= 1
                try:
                    self.cache[key] = self._wikidata_query(dom)
                except _Skip:
                    return None  # rien n'est mis en cache : on réessaiera
                self.geocoder.dirty = True
            if self.cache.get(key):
                return {**self.cache[key], "geo_precision": "organisation"}
        return None

    def _wikidata_query(self, dom: str) -> dict | None:
        variants = " ".join(f"<{s}://{w}{dom}{e}>" for s in ("https", "http") for w in ("", "www.") for e in ("", "/"))
        q = f"""SELECT ?item ?itemLabel ?coord ?hq ?hqLabel ?hqcoord ?loccoord ?ccoord ?cLabel WHERE {{
          VALUES ?url {{ {variants} }} ?item wdt:P856 ?url .
          OPTIONAL {{ ?item wdt:P625 ?coord }}
          OPTIONAL {{ ?item wdt:P159 ?hq . ?hq wdt:P625 ?hqcoord }}
          OPTIONAL {{ ?item wdt:P131 ?loc . ?loc wdt:P625 ?loccoord }}
          OPTIONAL {{ ?item wdt:P17 ?c . ?c wdt:P625 ?ccoord }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "fr,en". }} }} LIMIT 5"""
        try:
            time.sleep(1.5)
            r = self.http.s.get("https://query.wikidata.org/sparql", params={"query": q}, timeout=40,
                                headers={"Accept": "application/sparql-results+json"})
            if r.status_code == 429:
                # quota Wikidata atteint : on arrête pour cette exécution (reprise demain grâce au cache)
                print("    [wikidata] quota atteint, reprise à la prochaine exécution")
                self.budget["wikidata"] = 0
                raise _Skip()
            r.raise_for_status()
            rows = r.json()["results"]["bindings"]
        except _Skip:
            raise
        except Exception as ex:
            print(f"    [wikidata] {dom}: {str(ex)[:120]}")
            return None
        for field, label_field in (("coord", "itemLabel"), ("hqcoord", "hqLabel"), ("loccoord", "itemLabel"), ("ccoord", "itemLabel")):
            for b in rows:
                if field in b:
                    lng, lat = b[field]["value"].removeprefix("Point(").rstrip(")").split()[:2]
                    org = b.get("itemLabel", {}).get("value", dom)
                    place = b.get(label_field, {}).get("value") if label_field == "hqLabel" else None
                    return {"lat": round(float(lat), 4), "lng": round(float(lng), 4),
                            "city": place or org,
                            "region": b.get("cLabel", {}).get("value", org),
                            "geo_source": f"Wikidata · {org}", "_coarse": field == "ccoord"}
        return None

    @staticmethod
    def publisher(name: str | None) -> dict | None:
        low = (name or "").lower()
        for key, (city, lat, lng) in PUBLISHERS.items():
            if key in low:
                return {"lat": lat, "lng": lng, "city": city, "region": city, "geo_precision": "organisation",
                        "geo_source": f"siège de l'éditeur"}
        return None

    def tld(self, url: str) -> dict | None:
        host = (urlparse(url or "").hostname or "").lower()
        tld = host.rsplit(".", 1)[-1] if "." in host else ""
        if tld in SPECIAL_TLDS:
            name, lat, lng = SPECIAL_TLDS[tld]
            return {"lat": lat, "lng": lng, "city": name, "region": name, "geo_precision": "pays"}
        if len(tld) == 2 and tld not in GENERIC_TLDS:
            return country_geo({"uk": "GB"}.get(tld, tld.upper()))
        return None

    # ── point d'entrée ──
    def locate(self, *, place: str | None = None, url: str | None = None, text: str = "",
               lang_codes: list[str] | None = None, country: str | None = None,
               publisher: str | None = None) -> dict | None:
        """Renvoie {lat, lng, city, region, geo_precision[, geo_source]} ou None."""
        g = self.place(place) if place else None
        if not g and url:
            g = self.github_owner(url) or self.hf_owner(url)
        if not g:
            langs = detect_languages(text, lang_codes)
            if langs:
                l = langs[0]
                g = {"lat": l["lat"], "lng": l["lng"], "city": l["region"], "region": l["region"],
                     "geo_precision": "langue", "geo_source": l["fr"]}
        if not g and publisher:
            g = self.publisher(publisher)
        if not g and url:
            g = self.wikidata_site(url)
            if g and g.pop("_coarse", False):
                g["geo_precision"] = "pays"
        if not g and country:
            g = country_geo(country if len(country) == 2 else country_code(country))
        if not g and url:
            g = self.tld(url)
        if g:
            g.pop("_coarse", None)
        self.stats[g["geo_precision"] if g else "aucune"] += 1
        return g
