"""Référentiel géographique partagé (catalogue + agent de veille).

- Langues peu dotées → région de référence (cf. languages.py) ;
- pays → centroïde (data/pays.json, généré depuis Wikidata) ;
- tout ce qui n'a pas de géographie connue reste non géolocalisé (lat/lng = None)
  plutôt que d'être empilé sur un point arbitraire.

Chaque position porte une `geo_precision` affichée sur le site :
  « lieu » (adresse/ville exacte), « organisation » (siège de l'organisme),
  « langue » (région où la langue est parlée), « pays » (centre du pays).
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from languages import LANGS, detect_languages

DATA = Path(__file__).resolve().parent.parent / "data"

REGIONS: dict[str, dict] = {l["region"]: {"lat": l["lat"], "lng": l["lng"], "city": l["region"]} for l in LANGS}


@lru_cache(maxsize=1)
def countries() -> dict:
    try:
        return json.loads((DATA / "pays.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


@lru_cache(maxsize=1)
def _country_names() -> dict:
    """nom (fr/en, minuscules, sans accents simples) → code ISO."""
    out = {}
    for iso, c in countries().items():
        for n in (c["fr"], c["en"]):
            out[n.lower()] = iso
    out.update({"uk": "GB", "usa": "US", "us": "US", "royaume-uni": "GB", "états-unis": "US", "etats-unis": "US",
                "england": "GB", "scotland": "GB", "south korea": "KR", "korea": "KR", "russia": "RU", "taiwan": "TW",
                "czech republic": "CZ", "the netherlands": "NL", "uae": "AE", "united arab emirates": "AE"})
    return out


US_STATES = set("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY "
                "NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split())
# Grandes villes fréquentes dans les offres, sans pays explicite
HUB_CITIES = {"new york": "US", "san francisco": "US", "seattle": "US", "boston": "US", "los angeles": "US",
              "palo alto": "US", "mountain view": "US", "austin": "US", "chicago": "US", "london": "GB",
              "cambridge, uk": "GB", "edinburgh": "GB", "paris": "FR", "lyon": "FR", "grenoble": "FR",
              "toulouse": "FR", "berlin": "DE", "munich": "DE", "münchen": "DE", "zurich": "CH", "zürich": "CH",
              "geneva": "CH", "amsterdam": "NL", "barcelona": "ES", "madrid": "ES", "milan": "IT", "rome": "IT",
              "toronto": "CA", "montreal": "CA", "montréal": "CA", "vancouver": "CA", "tel aviv": "IL",
              "dubai": "AE", "abu dhabi": "AE", "singapore": "SG", "tokyo": "JP", "bangalore": "IN", "bengaluru": "IN"}


def country_code(text: str | None) -> str | None:
    """Code ISO d'un pays nommé dans `text` (« München (Germany) », « Paris, France »…)."""
    if not text:
        return None
    t = text.lower()
    names = _country_names()
    for part in reversed(re.split(r"[,()\-–/|;]", t)):
        p = part.strip()
        if p in names:
            return names[p]
    for n, iso in sorted(names.items(), key=lambda x: -len(x[0])):
        if len(n) > 3 and re.search(rf"(?<!\w){re.escape(n)}(?!\w)", t):
            return iso
    for city, iso in HUB_CITIES.items():
        if re.search(rf"(?<!\w){re.escape(city)}(?!\w)", t):
            return iso
    # code final sur deux lettres : « Brussels, BE » (ISO) ou « Austin, TX » (État américain) ;
    # en cas d'ambiguïté (CA, DE, IN, IL, GA…) le code pays ISO l'emporte
    m = re.search(r",\s*([A-Z]{2})\s*$", text.strip())
    if m:
        code = m.group(1)
        if code in countries() and code != "UK":
            return code
        if code in US_STATES:
            return "US"
        if code == "UK":
            return "GB"
    return None


def country_geo(iso: str | None) -> dict | None:
    c = countries().get((iso or "").upper())
    if not c:
        return None
    return {"region": c["fr"], "city": c["fr"], "lat": c["lat"], "lng": c["lng"],
            "country": iso.upper(), "geo_precision": "pays"}


def detect_region(*texts: str | None, codes: list[str] | None = None) -> str | None:
    langs = detect_languages(" ".join(t for t in texts if t), codes)
    return langs[0]["region"] if langs else None


def region_from_country(pays: str | None) -> str | None:
    iso = country_code(pays)
    return countries()[iso]["fr"] if iso else None


def geo_fields(region: str | None) -> dict:
    """Champs géographiques normalisés pour le front."""
    if region and region in REGIONS:
        r = REGIONS[region]
        return {"region": region, "city": r["city"], "lat": r["lat"], "lng": r["lng"], "geo_precision": "langue"}
    if region:
        iso = country_code(region)
        g = country_geo(iso)
        if g:
            return g
    return {"region": "International", "city": None, "lat": None, "lng": None}
