#!/usr/bin/env python3
"""Génère data/pays.json : code ISO → nom FR/EN + coordonnées (Wikidata). À relancer rarement."""
import json
from pathlib import Path
import requests

Q = """SELECT ?iso ?fr ?en ?coord WHERE {
  ?c wdt:P297 ?iso ; wdt:P625 ?coord .
  FILTER NOT EXISTS { ?c wdt:P576 ?end }
  OPTIONAL { ?c rdfs:label ?fr FILTER(LANG(?fr)="fr") }
  OPTIONAL { ?c rdfs:label ?en FILTER(LANG(?en)="en") }
}"""
r = requests.get("https://query.wikidata.org/sparql", params={"query": Q},
                 headers={"Accept": "application/sparql-results+json",
                          "User-Agent": "ConnecTAL-veille/2.0 (+https://omnital.github.io)"}, timeout=120)
r.raise_for_status()
out = {}
for b in r.json()["results"]["bindings"]:
    iso = b["iso"]["value"].upper()
    if iso in out:
        continue
    lng, lat = b["coord"]["value"].removeprefix("Point(").rstrip(")").split()
    out[iso] = {"fr": b.get("fr", {}).get("value", iso), "en": b.get("en", {}).get("value", iso),
                "lat": round(float(lat), 3), "lng": round(float(lng), 3)}
p = Path(__file__).resolve().parents[2] / "data" / "pays.json"
p.write_text(json.dumps(dict(sorted(out.items())), ensure_ascii=False, indent=0), encoding="utf-8")
print(len(out), "pays →", p)
