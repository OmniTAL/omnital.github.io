"""Requêtes suivies : recherches lancées depuis le site et confiées à l'agent.

Circuit (sans serveur) :
  1. sur le site, « Suivre cette recherche » ouvre une issue GitHub pré-remplie,
     étiquetée `veille:requete` (titre : « Requête de veille : <termes> ») ;
  2. chaque jour, l'agent lit les issues ouvertes portant cette étiquette ;
  3. il exécute chaque requête sur Hugging Face, GitHub, Zenodo, HAL, arXiv et theses.fr ;
  4. les résultats entrent dans l'historique (donc la carte et le catalogue) avec le tag
     `queries`, et l'agent commente l'issue au premier passage (« requête suivie »).
Fermer l'issue arrête le suivi.
"""
from __future__ import annotations

import os
import re
import time
import xml.etree.ElementTree as ET

NS = {"atom": "http://www.w3.org/2005/Atom"}
TITLE_RX = re.compile(r"^\s*(?:requête de veille|requete de veille|veille|query)\s*:\s*(.+)$", re.I)


def _gh_headers() -> dict:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if os.getenv("GITHUB_TOKEN"):
        h["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    return h


def fetch_queries(http, cfg: dict, store: dict, today: str) -> dict:
    """Synchronise data/requetes.json avec les issues GitHub ouvertes (étiquette configurée)."""
    repo = os.getenv("GITHUB_REPOSITORY")
    label = cfg["requetes"]["label"]
    if not repo:
        print("    [requêtes] GITHUB_REPOSITORY absent (exécution locale) : requêtes existantes conservées")
        return store
    issues = http.get(f"https://api.github.com/repos/{repo}/issues", headers=_gh_headers(), retries=1,
                      params={"labels": label, "state": "open", "per_page": 100}).json()
    active = {}
    for iss in issues if isinstance(issues, list) else []:
        # le champ « Requête » du formulaire fait foi ; à défaut, le titre « Requête de veille : … »
        body = re.search(r"###\s*Requête\s*\n+(.+?)(?:\n\s*\n|\n###|$)", iss.get("body") or "", re.S)
        m = TITLE_RX.match(iss.get("title", ""))
        q = (body.group(1) if body else m.group(1) if m else iss.get("title", "")).strip().strip("«»\"' ")
        if q.lower() in ("_no response_", ""):
            continue
        if not q or len(q) > 120:
            continue
        old = store.get(q, {})
        active[q] = {**old, "issue": iss["number"], "url": iss["html_url"], "added": old.get("added") or today,
                     "author": (iss.get("user") or {}).get("login")}
    for q in list(store):
        if q not in active:
            store.pop(q)  # issue fermée → suivi arrêté
    store.update(active)
    return store


def acknowledge(http, cfg: dict, q: str, entry: dict, n: int) -> None:
    """Commente l'issue au premier passage et ajoute l'étiquette « suivie »."""
    repo = os.getenv("GITHUB_REPOSITORY")
    if not repo or entry.get("acknowledged") or not entry.get("issue"):
        return
    site = cfg.get("site_url", "")
    body = (f"✅ Requête suivie par l'agent de veille ConnecTAL.\n\n"
            f"Premier passage : **{n} résultat(s)** ajoutés à la carte et au catalogue "
            f"([voir sur le site]({site}/#q={q.replace(' ', '%20')})).\n\n"
            "L'agent relance cette recherche chaque jour. Fermez l'issue pour arrêter le suivi.")
    try:
        http.s.post(f"https://api.github.com/repos/{repo}/issues/{entry['issue']}/comments",
                    headers=_gh_headers(), json={"body": body}, timeout=30).raise_for_status()
        http.s.post(f"https://api.github.com/repos/{repo}/issues/{entry['issue']}/labels",
                    headers=_gh_headers(), json={"labels": ["suivie"]}, timeout=30)
        entry["acknowledged"] = True
    except Exception as ex:
        print(f"    [requêtes] commentaire impossible sur #{entry['issue']} : {ex}")


def run_query(http, q: str, mk) -> list[dict]:
    """Exécute une requête sur les sources ouvertes ; chaque résultat porte `queries: [q]`."""
    out: list[dict] = []
    tag = {"queries": [q]}

    def safe(label, fn):
        try:
            fn()
        except Exception as ex:
            print(f"    [requête « {q} »] {label} : {str(ex)[:120]}")

    def hf():
        for kind, typ, prefix in (("datasets", "Corpus", "https://huggingface.co/datasets/"),
                                  ("models", "Model", "https://huggingface.co/")):
            for e in http.get(f"https://huggingface.co/api/{kind}", params={"search": q, "limit": 20, "sort": "downloads",
                                                                           "direction": -1}, retries=1).json():
                tags = e.get("tags") or []
                out.append(mk(id=f"hf:{kind}:{e['id']}", title=e["id"], type=typ, source="huggingface",
                              url=prefix + e["id"], date_s=e.get("createdAt"), summary=e.get("description") or "",
                              author=e.get("author") or e["id"].split("/")[0], extra_text=" ".join(tags),
                              languages=[t.split(":", 1)[1] for t in tags if t.startswith("language:")], **tag))

    def gh():
        data = http.get("https://api.github.com/search/repositories", headers=_gh_headers(), retries=1,
                        params={"q": q, "sort": "stars", "order": "desc", "per_page": 20}).json()
        for r in data.get("items", []):
            out.append(mk(id=f"gh:{r['full_name'].lower()}", title=r["full_name"], type="Tool", source="github",
                          url=r["html_url"], date_s=r.get("created_at"), summary=r.get("description") or "",
                          author=(r.get("owner") or {}).get("login", ""), extra_text=" ".join(r.get("topics") or []),
                          stars=r.get("stargazers_count"), **tag))

    def zenodo():
        data = http.get("https://zenodo.org/api/records", params={"q": q, "size": 20, "sort": "mostrecent"}, retries=1).json()
        for r in data.get("hits", {}).get("hits", []):
            m = r.get("metadata", {})
            rt = (m.get("resource_type") or {}).get("type")
            if rt not in ("dataset", "software", "publication"):
                continue
            creators = m.get("creators") or []
            out.append(mk(id=f"zenodo:{r.get('conceptrecid') or r['id']}", title=m.get("title", ""),
                          type={"dataset": "Corpus", "software": "Tool"}.get(rt, "Paper"), source="zenodo",
                          url=r.get("links", {}).get("self_html", ""), date_s=m.get("publication_date"),
                          summary=re.sub(r"<[^>]+>", " ", m.get("description") or "")[:500],
                          author=", ".join(c.get("name", "") for c in creators[:3]),
                          place_hint=next((c.get("affiliation") for c in creators if c.get("affiliation")), None), **tag))

    def hal():
        data = http.get("https://api.archives-ouvertes.fr/search/", retries=1, params={
            "q": q, "rows": 20, "sort": "submittedDate_tdate desc", "wt": "json",
            "fl": "halId_s,title_s,abstract_s,uri_s,submittedDate_s,authFullName_s,structCountry_s"}).json()
        for d in data.get("response", {}).get("docs", []):
            out.append(mk(id=f"hal:{d['halId_s']}", title=(d.get("title_s") or [""])[0], type="Paper", source="hal",
                          url=d.get("uri_s", ""), date_s=d.get("submittedDate_s"), summary=(d.get("abstract_s") or [""])[0],
                          author=", ".join((d.get("authFullName_s") or [])[:3]),
                          country=(d.get("structCountry_s") or [None])[0], **tag))

    def arxiv():
        time.sleep(3.5)
        terms = " AND ".join(f"all:{w}" for w in re.findall(r"[\w-]+", q)[:6])
        root = ET.fromstring(http.get("https://export.arxiv.org/api/query", retries=2, params={
            "search_query": terms, "max_results": 20, "sortBy": "submittedDate", "sortOrder": "descending"}).content)
        for e in root.findall("atom:entry", NS):
            link = e.findtext("atom:id", default="", namespaces=NS)
            m = re.search(r"abs/([\w.\-/]+?)(v\d+)?$", link)
            if m:
                out.append(mk(id=f"arxiv:{m.group(1)}", title=e.findtext("atom:title", default="", namespaces=NS),
                              type="Paper", source="arxiv", url=f"https://arxiv.org/abs/{m.group(1)}",
                              date_s=e.findtext("atom:published", default="", namespaces=NS),
                              summary=e.findtext("atom:summary", default="", namespaces=NS), **tag))

    for label, fn in (("Hugging Face", hf), ("GitHub", gh), ("Zenodo", zenodo), ("HAL", hal), ("arXiv", arxiv)):
        safe(label, fn)
        time.sleep(0.5)
    return out
