#!/usr/bin/env python3
"""Agent de veille TAL de ConnecTAL — exécuté chaque jour par GitHub Actions.

Sources suivies (configurables dans config/veille.json) :
  • arXiv      — flux RSS quotidien cs.CL + requêtes ciblées (langues berbères…) via l'API
  • HAL        — dépôts récents du domaine « Informatique et langage » (info.info-cl)
  • Hugging Face — datasets, modèles et Spaces en langues berbères
  • GitHub     — dépôts récents liés au TAL berbère
  • WikiCFP    — appels à communications TAL (géocodés pour la carte)

Principes :
  • identifiants STABLES (arXiv id, id HF, nom GitHub…) → pas de doublons d'un jour à l'autre ;
  • historique persistant data/veille_history.json avec `first_seen` → on sait ce qui est NOUVEAU ;
  • une source en panne n'empêche pas les autres (statut consigné dans radar.json) ;
  • sorties : data/radar.json (site), data/feed.xml (RSS des nouveautés).

Usage : python scripts/agent_veille_nlp.py [--offline] [--only arxiv,hal,...]
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from typing import Callable, Iterable
from xml.sax.saxutils import escape as xml_escape

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from geo import detect_region, geo_fields  # noqa: E402
from languages import LANGS, all_codes, detect_languages, search_terms  # noqa: E402
from catalogue import merge_curated, update_catalogue  # noqa: E402
from cfp import fetch_event_details  # noqa: E402
from notices import LLMWriter  # noqa: E402
import collectors_extra as cx  # noqa: E402
from locate import Locator  # noqa: E402
import requetes as rq  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CONFIG_PATH = ROOT / "config" / "veille.json"
HISTORY_PATH = DATA / "veille_history.json"
RESSOURCES_PATH = DATA / "ressources.json"
GEOCACHE_PATH = DATA / "geocache.json"
OUTPUT_PATH = DATA / "radar.json"
FEED_PATH = DATA / "feed.xml"
CATALOGUE_AUTO_PATH = DATA / "catalogue_auto.json"
REQUETES_PATH = DATA / "requetes.json"
CATALOGUE_PATH = DATA / "catalogue.json"
# Champs ajoutés après la collecte (enrichissement) : conservés d'une exécution à l'autre
ENRICHED_KEYS = ("event", "details_checked", "geo_tried", "geo_precision", "geo_source", "queries", "page_checked")
OPPORTUNITY_SOURCES = {"nlppeople", "greenhouse", "ashby", "lever", "remotive", "arbeitnow", "theses", "formations"}

TODAY = datetime.now(timezone.utc).date()
FOCUS_KW: list[str] = []  # complété depuis config/veille.json au démarrage
OPP_TTL: dict = {}
TODAY_S = TODAY.isoformat()
NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom",
      "dc": "http://purl.org/dc/elements/1.1/"}


# ───────────────────────────── utilitaires ─────────────────────────────

def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: Path, data, indent: int | None = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=indent), encoding="utf-8")
    tmp.replace(path)  # écriture atomique : jamais de JSON tronqué en ligne


def squash(text: str | None, limit: int | None = None) -> str:
    if not text:
        return ""
    t = html.unescape(re.sub(r"<[^>]+>", " ", text))
    t = re.sub(r"\s+", " ", t).strip()
    if limit and len(t) > limit:
        t = t[: limit - 1].rsplit(" ", 1)[0] + "…"
    return t


def classify_topic(text: str) -> str | None:
    """Thème dominant d'une publication (affiché en étiquette, ne remplace pas le type)."""
    t = text.lower()
    rules = [
        ("Corpus", ["corpus", "dataset", "annotation", "benchmark", "treebank"]),
        ("Speech", ["speech", "asr", "tts", "spoken", "audio"]),
        ("Translation", ["translation", "machine translation", "mt "]),
        ("LLM", ["llm", "large language model", "instruction", "fine-tun", "rlhf"]),
        ("Tool", ["toolkit", "library", "framework", "pipeline", "open-source tool"]),
    ]
    for label, keys in rules:
        if any(k in t for k in keys):
            return label
    return None


class Http:
    """Session HTTP polie : User-Agent explicite, délais, reprise sur 429/5xx."""

    def __init__(self, user_agent: str):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = user_agent

    def get(self, url: str, *, params=None, headers=None, retries: int = 3, timeout: int = 40) -> requests.Response:
        delay = 5
        for attempt in range(retries + 1):
            try:
                r = self.s.get(url, params=params, headers=headers, timeout=timeout)
                if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                    wait = int(r.headers.get("Retry-After", delay)) if str(r.headers.get("Retry-After", "")).isdigit() else delay
                    print(f"    ↻ HTTP {r.status_code} sur {url.split('?')[0]} — nouvel essai dans {wait}s")
                    time.sleep(wait)
                    delay *= 3
                    continue
                r.raise_for_status()
                return r
            except requests.RequestException:
                if attempt >= retries:
                    raise
                time.sleep(delay)
                delay *= 3
        raise RuntimeError("unreachable")


class Geocoder:
    """Géocodage Nominatim avec cache disque (politique d'usage : 1 req/s, UA identifiable)."""

    def __init__(self, http: Http, cfg: dict):
        self.http, self.cfg = http, cfg
        self.cache: dict = load_json(GEOCACHE_PATH, {})
        self.budget = cfg.get("max_new_lookups_per_run", 40) if cfg.get("enabled", True) else 0
        self.dirty = False

    def lookup(self, query: str, country_code: str | None = None) -> dict | None:
        key = f"country:{country_code}" if country_code else query.strip().lower()
        if not key:
            return None
        if key in self.cache:
            return self.cache[key]
        if self.budget <= 0:
            return None
        self.budget -= 1
        params = {"format": "json", "limit": 1, "accept-language": "fr"}
        params.update({"country": country_code} if country_code else {"q": query})
        try:
            time.sleep(1.1)
            data = self.http.get(self.cfg["endpoint"], params=params, retries=1).json()
            res = {"lat": round(float(data[0]["lat"]), 4), "lng": round(float(data[0]["lon"]), 4),
                   "label": data[0].get("name") or query} if data else None
        except Exception as ex:  # le géocodage ne doit jamais faire échouer la veille
            print(f"    [geo] {query or country_code}: {ex}")
            return None
        self.cache[key] = res
        self.dirty = True
        return res

    def save(self):
        if self.dirty:
            write_json(GEOCACHE_PATH, dict(sorted(self.cache.items())))


def make_item(*, id: str, title: str, type: str, source: str, url: str, date_s: str | None,
              summary: str = "", author: str = "", focus_kw: list[str] | None = None, extra_text: str = "",
              region: str | None = None, geo: dict | None = None, force_focus: bool = False,
              languages: list[str] | None = None, **extra) -> dict:
    """Élément normalisé (veille, catalogue, opportunité).

    Langues peu dotées détectées par codes structurés (étiquettes HF, ELG…) puis par
    mots-clés ; elles donnent le « focus », les groupes de langues et une position
    par défaut (région où la langue est parlée)."""
    blob = f"{title} {summary} {extra_text}"
    langs = detect_languages(blob, [c for c in (languages or []) if isinstance(c, str)])
    kw = focus_kw if focus_kw is not None else FOCUS_KW
    focus = force_focus or bool(langs) or any(k in blob.lower() for k in kw)
    region = region or (langs[0]["region"] if langs else None)
    fields = geo_fields(region)
    if geo and (fields["lat"] is None or fields.get("geo_precision") != "lieu"):  # géocodage explicite (lieu, pays)
        fields = {"region": geo.get("region") or geo.get("label") or fields["region"], "city": geo.get("label") or geo.get("city"),
                  "lat": geo["lat"], "lng": geo["lng"], "geo_precision": geo.get("geo_precision", "lieu")}
    item = {
        "id": id, "title": squash(title, 300), "type": type, "source": source, "url": url,
        # un appel à communications sans date reste sans date (pas de « aujourd'hui » inventé)
        "date": (date_s or ("" if type in ("Event", "Opportunity", "Journal") else TODAY_S))[:10],
        "summary": squash(summary, 320), "author": squash(author, 120), "focus": focus, **fields,
    }
    if langs:
        item["lang_codes"] = [l["code"] for l in langs][:6]
        item["lang_groups"] = sorted({l["group"] for l in langs})
    if languages:
        item["languages"] = [c for c in languages if isinstance(c, str)][:8]
    topic = classify_topic(blob) if type == "Paper" else None
    if topic:
        item["topic"] = topic
    item.update({k: v for k, v in extra.items() if v not in (None, "", [], {})})
    return item


# ───────────────────────────── collecteurs ─────────────────────────────

def collect_arxiv(http: Http, cfg: dict, focus_kw: list[str], **_) -> list[dict]:
    out: dict[str, dict] = {}
    # 1) Flux RSS quotidien (vide le week-end : c'est normal)
    for cat in cfg["arxiv"]["rss_categories"]:
        r = http.get(f"https://rss.arxiv.org/rss/{cat}")
        root = ET.fromstring(r.content)
        for it in root.iter("item"):
            ann = (it.findtext("arxiv:announce_type", default="", namespaces=NS) or "").strip()
            if ann.startswith("replace"):
                continue  # on ne suit que les nouveautés (new / cross)
            link = (it.findtext("link") or "").strip()
            m = re.search(r"abs/([\w.\-/]+?)(v\d+)?$", link)
            if not m:
                continue
            aid = m.group(1)
            desc = it.findtext("description") or ""
            abstract = desc.split("Abstract:", 1)[-1]
            pub = it.findtext("pubDate")
            d = parsedate_to_datetime(pub).date().isoformat() if pub else TODAY_S
            out[aid] = make_item(id=f"arxiv:{aid}", title=it.findtext("title") or "", type="Paper",
                                 source="arxiv", url=f"https://arxiv.org/abs/{aid}", date_s=d,
                                 summary=abstract, author=it.findtext("dc:creator", namespaces=NS) or "",
                                 focus_kw=focus_kw, category=cat)
        time.sleep(1)
    # 2) Requêtes ciblées via l'API (thématiques prioritaires, y compris hors cs.CL)
    for q in cfg["arxiv"]["api_queries"]:
        time.sleep(3.5)  # règle d'usage arXiv : ≥ 3 s entre requêtes
        try:
            r = http.get("https://export.arxiv.org/api/query", params={
                "search_query": q, "start": 0, "max_results": cfg["arxiv"]["api_max_results"],
                "sortBy": "submittedDate", "sortOrder": "descending"}, retries=3)
        except Exception as ex:
            print(f"    [arXiv API] « {q} » : {ex}")
            continue
        root = ET.fromstring(r.content)
        for e in root.findall("atom:entry", NS):
            link = e.findtext("atom:id", default="", namespaces=NS)
            m = re.search(r"abs/([\w.\-/]+?)(v\d+)?$", link)
            if not m or m.group(1) in out:
                continue
            aid = m.group(1)
            authors = [a.findtext("atom:name", default="", namespaces=NS) for a in e.findall("atom:author", NS)]
            out[aid] = make_item(id=f"arxiv:{aid}", title=e.findtext("atom:title", default="", namespaces=NS),
                                 type="Paper", source="arxiv", url=f"https://arxiv.org/abs/{aid}",
                                 date_s=e.findtext("atom:published", default="", namespaces=NS),
                                 summary=e.findtext("atom:summary", default="", namespaces=NS),
                                 author=", ".join(authors[:3]) + (" et al." if len(authors) > 3 else ""),
                                 focus_kw=focus_kw)
    return list(out.values())


def collect_hal(http: Http, cfg: dict, focus_kw: list[str], geocoder: Geocoder, **_) -> list[dict]:
    r = http.get("https://api.archives-ouvertes.fr/search/", params={
        "q": "*:*", "fq": f"domainAllCode_s:{cfg['hal']['domain']}", "sort": "submittedDate_tdate desc",
        "rows": cfg["hal"]["rows"], "wt": "json",
        "fl": "halId_s,title_s,abstract_s,uri_s,submittedDate_s,docType_s,authFullName_s,structCountry_s,language_s"})
    items = []
    for d in r.json().get("response", {}).get("docs", []):
        title = (d.get("title_s") or [""])[0]
        authors = d.get("authFullName_s") or []
        countries = d.get("structCountry_s") or []
        geo = None
        if countries and not detect_region(title):
            geo = geocoder.lookup("", country_code=countries[0])
        items.append(make_item(
            id=f"hal:{d['halId_s']}", title=title, type="Paper", source="hal", url=d.get("uri_s", ""),
            date_s=d.get("submittedDate_s"), summary=(d.get("abstract_s") or [""])[0],
            author=", ".join(authors[:3]) + (" et al." if len(authors) > 3 else ""),
            focus_kw=focus_kw, geo=geo, doc_type=d.get("docType_s"),
            lang=",".join(d.get("language_s") or [])))
    return items


def collect_huggingface(http: Http, cfg: dict, focus_kw: list[str], **_) -> list[dict]:
    hf = cfg["huggingface"]
    type_map = {"datasets": "Corpus", "models": "Model", "spaces": "Tool"}
    url_prefix = {"datasets": "https://huggingface.co/datasets/", "models": "https://huggingface.co/",
                  "spaces": "https://huggingface.co/spaces/"}
    seen: dict[str, dict] = {}

    def tag_value(tags: list[str], prefix: str) -> str | None:
        return next((t.split(":", 1)[1] for t in tags if t.startswith(prefix + ":")), None)

    def run(kind: str, params: dict):
        base = {"sort": "createdAt", "direction": -1, "limit": hf["limit"]}
        term = params.get("search", "").lower()
        try:
            data = http.get(f"https://huggingface.co/api/{kind}", params={**base, **params}, retries=2).json()
        except Exception as ex:
            print(f"    [HF] {kind} {params}: {ex}")
            return
        for e in data:
            rid = e.get("id")
            if not rid or e.get("private") or f"{kind}:{rid}" in seen:
                continue
            tags = e.get("tags") or []
            owner, _, name = rid.partition("/")
            # Recherche plein texte : le terme doit viser la ressource, pas seulement le pseudo
            # de son auteur (ex. « SAadettin-BERber » remontait pour « berber »).
            if term and term not in f"{name} {e.get('description') or ''} {' '.join(tags)}".lower():
                continue
            langs = [t.split(":", 1)[1] for t in tags if t.startswith("language:")] or \
                    [t for t in tags if t in hf["languages"]]
            base_model = next((t.split(":", 1)[1] for t in tags if t.startswith("base_model:")
                               and t.count(":") == 1), None)
            meta = {"task": tag_value(tags, "task_categories") or e.get("pipeline_tag"),
                    "size": tag_value(tags, "size_categories"), "license": tag_value(tags, "license"),
                    "library": e.get("library_name"), "base_model": base_model}
            seen[f"{kind}:{rid}"] = make_item(
                id=f"hf:{kind}:{rid}", title=rid, type=type_map[kind], source="huggingface",
                url=url_prefix[kind] + rid, date_s=e.get("createdAt"),
                summary=e.get("description") or "", author=e.get("author") or owner,
                focus_kw=focus_kw, extra_text=" ".join(tags), languages=langs[:8], force_focus=True,
                likes=e.get("likes"), downloads=e.get("downloads"),
                meta={k: v for k, v in meta.items() if v})
        time.sleep(0.4)

    lang_codes = all_codes() if hf["languages"] == "auto" else hf["languages"]
    terms = (search_terms() + ["kabyle", "taqbaylit", "tifinagh", "darija"]) if hf["search_terms"] == "auto" else hf["search_terms"]
    for kind in hf["kinds"]:
        if kind != "spaces":  # les Spaces n'ont pas de filtre de langue
            for lang in lang_codes:
                run(kind, {"filter": f"language:{lang}" if kind == "datasets" else lang})
        for term in terms:
            run(kind, {"search": term.lower()})
    # Tendances : ressources TAL les plus suivies du moment, toutes langues confondues
    focus_ids = set(seen)
    text_tasks = re.compile(r"text|token|translation|summari|question|fill-mask|sentence|feature-extraction|"
                            r"automatic-speech|text-to-speech|conversational|zero-shot|table-question")
    for kind, n in (hf.get("trending") or {}).items():
        try:
            data = http.get(f"https://huggingface.co/api/{kind}", params={"sort": "trendingScore", "limit": n}, retries=1).json()
        except Exception as ex:
            print(f"    [HF] tendances {kind}: {ex}")
            continue
        for e in data:
            rid, tags = e.get("id"), e.get("tags") or []
            task = e.get("pipeline_tag") or tag_value(tags, "task_categories") or ""
            if not rid or f"{kind}:{rid}" in focus_ids or not (text_tasks.search(task) or "modality:text" in tags):
                continue
            langs = [t.split(":", 1)[1] for t in tags if t.startswith("language:")]
            seen[f"{kind}:{rid}"] = make_item(
                id=f"hf:{kind}:{rid}", title=rid, type=type_map[kind], source="huggingface",
                url=url_prefix[kind] + rid, date_s=e.get("createdAt"), summary=e.get("description") or "",
                author=e.get("author") or rid.split("/")[0], extra_text=" ".join(tags), languages=langs[:8],
                likes=e.get("likes"), downloads=e.get("downloads"), trending=True,
                meta={k: v for k, v in {"task": task, "license": tag_value(tags, "license"),
                                        "size": tag_value(tags, "size_categories"), "library": e.get("library_name")}.items() if v})
        time.sleep(0.4)
    return list(seen.values())


def collect_github(http: Http, cfg: dict, focus_kw: list[str], **_) -> list[dict]:
    gh = cfg["github"]
    since = (TODAY - timedelta(days=gh["lookback_days"])).isoformat()
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if os.getenv("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    out: dict[str, dict] = {}
    queries = ([f'"{t}" nlp' for t in search_terms()] + ["kabyle", "taqbaylit", "tifinagh", "darija nlp"]
               if gh["queries"] == "auto" else list(gh["queries"]))
    targeted = len(queries)
    queries += gh.get("extra_queries", [])
    for qi, q in enumerate(queries):
        r = http.get("https://api.github.com/search/repositories", headers=headers, retries=1, params={
            "q": f"{q} created:>={since} fork:false", "sort": "stars" if qi >= targeted else "updated",
            "order": "desc", "per_page": 30})
        for repo in r.json().get("items", []):
            name = repo["full_name"]
            if name in out:
                continue
            out[name] = make_item(
                id=f"gh:{name.lower()}", title=name, type="Tool", source="github", url=repo["html_url"],
                date_s=repo.get("created_at"), summary=repo.get("description") or "",
                author=repo.get("owner", {}).get("login", ""), focus_kw=focus_kw,
                extra_text=" ".join(repo.get("topics") or []) + (" " + q if qi < targeted else ""),
                force_focus=qi < targeted,
                stars=repo.get("stargazers_count"), language=repo.get("language"),
                meta={k: v for k, v in {"language": repo.get("language"), "topics": repo.get("topics"),
                      "license": (repo.get("license") or {}).get("spdx_id")}.items() if v})
        time.sleep(2 if "Authorization" in headers else 7)  # 10 req/min sans jeton
    return list(out.values())


CFP_DESC = re.compile(r"\[([^\[\]]*)\]\s*\[([^\[\]]*)\]\s*$")


def _parse_cfp_dates(s: str) -> tuple[str | None, str | None]:
    parts = [p.strip() for p in s.split(" - ")]
    out = []
    for p in parts[:2]:
        try:
            out.append(datetime.strptime(p, "%b %d, %Y").date().isoformat())
        except ValueError:
            out.append(None)
    while len(out) < 2:
        out.append(out[0] if out else None)
    return out[0], out[1]


def collect_wikicfp(http: Http, cfg: dict, focus_kw: list[str], geocoder: Geocoder, **_) -> list[dict]:
    out: dict[str, dict] = {}
    for feed in cfg["wikicfp"]["feeds"]:
        r = http.get(feed, retries=2)
        root = ET.fromstring(r.content)
        for it in root.iter("item"):
            link = (it.findtext("link") or "").strip()
            m = re.search(r"eventid=(\d+)", link)
            if not m or m.group(1) in out:
                continue
            title = it.findtext("title") or ""
            desc = it.findtext("description") or ""
            loc, start, end = None, None, None
            dm = CFP_DESC.search(desc)
            if dm:
                loc = dm.group(1).strip()
                start, end = _parse_cfp_dates(dm.group(2))
            if end and end < (TODAY - timedelta(days=1)).isoformat():
                continue  # événement terminé
            online = not loc or re.search(r"online|virtual|n/?a|tba|hybrid", loc, re.I)
            geo = None if online else geocoder.lookup(loc)
            if geo:  # région affichée = pays (dernier segment du lieu : « Bergamo - Italy » → « Italy »)
                geo = {**geo, "region": re.split(r"[,\-–]", loc)[-1].strip() or None}
            acronym, _, fullname = title.partition(" : ")
            out[m.group(1)] = make_item(
                id=f"wikicfp:{m.group(1)}", title=title, type="Event", source="wikicfp",
                url=f"http://www.wikicfp.com/cfp/servlet/event.showcfp?eventid={m.group(1)}",
                date_s=start, summary=fullname or desc, author="WikiCFP", focus_kw=focus_kw,
                geo=geo, date_end=end, location=loc or "Online", acronym=acronym.strip())
        time.sleep(1.5)
    return list(out.values())


def enrich_events(history: dict, http: Http, geocoder: Geocoder, budget: int) -> int:
    """Lit la page WikiCFP de chaque appel : lieu, site officiel, échéances (résumés, articles…).

    Pages lues : nouveaux appels, puis ré-vérification hebdomadaire des appels encore ouverts
    (les dates limites sont souvent prolongées)."""
    week_ago = (TODAY - timedelta(days=7)).isoformat()
    todo = [it for it in history.values() if it["source"] == "wikicfp" and (
        not it.get("details_checked") or (
            it["details_checked"] < week_ago and
            ((it.get("event") or {}).get("paper_deadline") or it.get("date") or "9999") >= TODAY_S))]
    todo.sort(key=lambda i: i.get("details_checked") or "")  # jamais lus d'abord
    done = 0
    for it in todo[:budget]:
        eid = it["id"].split(":", 1)[1]
        try:
            time.sleep(1.5)
            ev = fetch_event_details(http, eid)
        except Exception as ex:
            print(f"    [WikiCFP] détails {eid} : {ex}")
            continue
        it["event"] = ev
        it["details_checked"] = TODAY_S
        it["date"] = ev.get("start") or it.get("date")
        if ev.get("end"):
            it["date_end"] = ev["end"]
        loc = ev.get("location")
        if loc:
            it["location"] = loc
            if it.get("lat") is None and not re.search(r"online|virtual|tba", loc, re.I):
                geo = geocoder.lookup(loc)
                if geo:
                    it.update({"lat": geo["lat"], "lng": geo["lng"], "city": geo.get("label"),
                               "region": re.split(r"[,\-–(]", loc)[-1].strip(" )") or it.get("region")})
        done += 1
    return done


COLLECTORS: dict[str, Callable] = {
    # publications
    "arxiv": collect_arxiv,
    "hal": collect_hal,
    # ressources ouvertes
    "huggingface": collect_huggingface,
    "github": collect_github,
    "zenodo": cx.collect_zenodo,
    "elg": cx.collect_elg,
    # revues et événements
    "doaj": cx.collect_doaj,
    "wikicfp": collect_wikicfp,
    # opportunités (emplois, stages, thèses, formations)
    "nlppeople": cx.collect_nlppeople,
    "jobboards": cx.collect_job_boards,
    "remote": cx.collect_remote_boards,
    "theses": cx.collect_theses,
    "formations": cx.collect_formations,
}


# ───────────────────────────── historique & sorties ─────────────────────────────

def merge_history(history: dict, fresh: Iterable[dict], bootstrap: bool) -> list[dict]:
    """Ajoute les nouveaux éléments (first_seen = aujourd'hui) et rafraîchit les existants."""
    new_items = []
    for it in fresh:
        it["last_seen"] = TODAY_S
        old = history.get(it["id"])
        if old:
            it["first_seen"] = old["first_seen"]
            for k in ENRICHED_KEYS:
                if k in old and k not in it:
                    it[k] = old[k]
            if it.get("location") and it.get("location") != old.get("location") and it.get("lat") is None:
                it.pop("geo_tried", None)  # nouveau lieu connu : on retente la géolocalisation
            if old.get("queries") and it.get("queries"):
                it["queries"] = sorted(set(old["queries"]) | set(it["queries"]))
            if old.get("focus"):
                it["focus"] = True  # une ressource ciblée le reste (même si revue via les tendances)
            # on garde une géoloc déjà obtenue si la nouvelle passe n'en a pas (budget géocodage)
            if it.get("lat") is None and old.get("lat") is not None:
                for k in ("lat", "lng", "city", "region"):
                    it[k] = old.get(k)
        else:
            # Premier passage : on date la découverte à la publication pour ne pas
            # présenter tout l'historique comme « nouveau aujourd'hui ».
            it["first_seen"] = min(it["date"] or TODAY_S, TODAY_S) if bootstrap else TODAY_S
            if not bootstrap or it["first_seen"] == TODAY_S:
                new_items.append(it)
        history[it["id"]] = it
    return new_items


def prune(history: dict, retention: dict) -> int:
    before = len(history)
    for k, it in list(history.items()):
        if it["type"] == "Opportunity":
            # une offre disparaît quand la source ne la publie plus depuis N jours
            ttl = OPP_TTL.get(it["source"], OPP_TTL.get("default", 45))
            if (it.get("last_seen") or it["first_seen"]) < (TODAY - timedelta(days=ttl)).isoformat():
                del history[k]
            continue
        if it["type"] == "Journal":
            # une revue reste tant que sa source (DOAJ) la liste
            if (it.get("last_seen") or it["first_seen"]) < (TODAY - timedelta(days=30)).isoformat():
                del history[k]
            continue
        if it["type"] == "Event":
            end = it.get("date_end") or it.get("date") or \
                (date.fromisoformat(it["first_seen"]) + timedelta(days=180)).isoformat()
            if end < (TODAY - timedelta(days=30)).isoformat():
                del history[k]
            continue
        if it.get("focus"):
            continue  # les ressources prioritaires (berbère…) sont conservées
        days = retention.get(it["source"], retention.get("default", 120))
        if it["first_seen"] < (TODAY - timedelta(days=days)).isoformat():
            del history[k]
    return before - len(history)


def write_feed(items: list[dict], site_url: str) -> None:
    latest = sorted(items, key=lambda i: (i["first_seen"], i["date"]), reverse=True)[:100]
    entries = []
    for it in latest:
        pub = datetime.fromisoformat(it["first_seen"]).replace(tzinfo=timezone.utc)
        entries.append(f"""    <item>
      <title>{xml_escape(f"[{it['type']}] {it['title']}")}</title>
      <link>{xml_escape(it['url'])}</link>
      <guid isPermaLink="false">{xml_escape(it['id'])}</guid>
      <pubDate>{format_datetime(pub)}</pubDate>
      <category>{xml_escape(it['source'])}</category>
      <description>{xml_escape(it.get('summary') or '')}</description>
    </item>""")
    FEED_PATH.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>ConnecTAL — veille TAL</title>
    <link>{site_url}/</link>
    <atom:link href="{site_url}/data/feed.xml" rel="self" type="application/rss+xml"/>
    <description>Nouvelles ressources en traitement automatique des langues (arXiv, HAL, Hugging Face, GitHub, WikiCFP).</description>
    <language>fr</language>
    <lastBuildDate>{format_datetime(datetime.now(timezone.utc))}</lastBuildDate>
{chr(10).join(entries)}
  </channel>
</rss>
""", encoding="utf-8")


def step_summary(lines: list[str]) -> None:
    """Résumé lisible dans l'onglet Actions de GitHub."""
    path = os.getenv("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


def enrich_locations(history: dict, locator: Locator, budget: int) -> int:
    """Géolocalise les éléments qui n'ont pas encore de position (réessai tous les 14 jours)."""
    retry = (TODAY - timedelta(days=3)).isoformat()
    todo = [it for it in history.values()
            if it.get("lat") is None and it["source"] not in ("arxiv",) and (not it.get("geo_tried") or it["geo_tried"] < retry)]
    # priorité : opportunités et événements (lieu explicite), puis ressources ciblées
    todo.sort(key=lambda i: (i["type"] not in ("Opportunity", "Event"), not i.get("focus")))
    done = 0
    for it in todo[:budget]:
        g = locator.locate(place=it.get("location") or it.get("place_hint"), url=it.get("url"),
                           text=f"{it['title']} {it.get('summary', '')}", lang_codes=it.get("languages"),
                           country=it.get("country"), publisher=(it.get("meta") or {}).get("publisher"))
        it["geo_tried"] = TODAY_S
        if g:
            it.update({k: g.get(k) for k in ("lat", "lng", "city", "region", "geo_precision", "geo_source") if g.get(k) is not None})
            done += 1
    return done


def slim_entry(e: dict) -> dict:
    """Fiche du catalogue allégée pour le site (traduction anglaise omise si identique)."""
    e = {k: v for k, v in e.items() if v not in (None, "", [], {}) and k not in ("provider_meta",)}
    for key in ("description", "notice"):
        d = e.get(key)
        if isinstance(d, dict) and d.get("en") == d.get("fr"):
            e[key] = {"fr": d.get("fr")}
    return e


def collect_deadlines(cat_items: list[dict], notices: list[dict]) -> list[dict]:
    """Échéances à venir (événements, numéros spéciaux de revues) — bandeau « échéances imminentes »."""
    out, seen = [], set()

    def add(id_, title, iso, which, url, place=""):
        if iso and iso >= TODAY_S and (url, which) not in seen:
            seen.add((url, which))
            out.append({"id": id_, "title": title, "date": iso, "which": which, "url": url, "place": place or ""})
    for n in notices:
        ev = n.get("event") or {}
        add(n["id"], n["title"], ev.get("abstract_deadline"), "dl_abstract", n["url"], ev.get("location"))
        add(n["id"], n["title"], ev.get("paper_deadline"), "dl_paper", n["url"], ev.get("location"))
    for r in cat_items:
        for i in (r.get("journal") or {}).get("special_issues", []):
            add(r["id"], f"{r['nom']} — {i['title']}", i.get("abstract_deadline") or i.get("deadline"),
                "dl_abstract" if i.get("abstract_deadline") else "dl_paper", i["url"])
    return sorted(out, key=lambda d: d["date"])[:200]


def split_payload_items(items: list[dict]) -> tuple[list[dict], list[dict]]:
    """Veille (publications, ressources, événements) / opportunités (emplois, stages, thèses, formations).
    Les écoles d'été annoncées sur WikiCFP figurent dans les deux."""
    notices, opps = [], []
    for i in items:
        if i["type"] == "Opportunity":
            opps.append(i)
        else:
            notices.append(i)
            if i["type"] == "Event" and re.search(r"\b(summer|winter|spring|autumn) school\b|école d'été", i["title"], re.I):
                opps.append({**i, "opp_kind": "school"})
    return notices, opps


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="ne collecte rien, régénère seulement radar.json")
    ap.add_argument("--only", help="liste de sources séparées par des virgules")
    args = ap.parse_args()

    cfg = load_json(CONFIG_PATH, None)
    if cfg is None:
        print(f"[ERREUR] configuration introuvable : {CONFIG_PATH}")
        return 1
    focus_kw = [k.lower() for k in cfg["focus_keywords"]]
    FOCUS_KW[:] = focus_kw
    OPP_TTL.update(cfg.get("opportunites", {}).get("ttl_days", {}))
    http = Http(cfg["user_agent"])
    geocoder = Geocoder(http, cfg.get("geocoding", {}))
    locator = Locator(http, geocoder, cfg.get("locate", {}))

    store = load_json(HISTORY_PATH, {"version": 2, "items": {}, "runs": []})
    history: dict = store["items"]
    bootstrap = not history

    selected = args.only.split(",") if args.only else list(COLLECTORS)
    status, new_items = {}, []
    for name in ([] if args.offline else [n for n in selected if n in COLLECTORS]):
        t0 = time.time()
        print(f"[…] {name}")
        try:
            fresh = COLLECTORS[name](http=http, cfg=cfg, focus_kw=focus_kw, geocoder=geocoder,
                                     mk=make_item, today=TODAY_S, previous=history)
            added = merge_history(history, fresh, bootstrap)
            new_items += added
            status[name] = {"ok": True, "fetched": len(fresh), "new": len(added)}
            print(f"[OK] {name}: {len(fresh)} récupérés, {len(added)} nouveaux ({time.time() - t0:.0f}s)")
        except Exception as ex:
            status[name] = {"ok": False, "error": f"{type(ex).__name__}: {str(ex)[:200]}"}
            print(f"[WARN] {name} en échec : {ex}")

    # Requêtes suivies (issues GitHub « veille:requete ») : exécutées chaque jour
    req_store = load_json(REQUETES_PATH, {})
    if not args.offline and (not args.only or "requetes" in selected):
        try:
            req_store = rq.fetch_queries(http, cfg, req_store, TODAY_S)
            for q, entry in list(req_store.items())[: cfg["requetes"].get("max_queries", 40)]:
                fresh = rq.run_query(http, q, make_item)
                added = merge_history(history, fresh, bootstrap=False)
                new_items += added
                entry.update({"last_run": TODAY_S, "results": len(fresh), "new": len(added)})
                rq.acknowledge(http, cfg, q, entry, len(fresh))
                print(f"[OK] requête « {q} » : {len(fresh)} résultats, {len(added)} nouveaux")
            status["requetes"] = {"ok": True, "fetched": len(req_store), "new": sum(e.get("new", 0) for e in req_store.values())}
        except Exception as ex:
            status["requetes"] = {"ok": False, "error": f"{type(ex).__name__}: {str(ex)[:200]}"}
            print(f"[WARN] requêtes suivies : {ex}")
        write_json(REQUETES_PATH, req_store)

    # Détails des appels à communications (lieu, échéances) — page WikiCFP de chaque événement
    cat_cfg = cfg.get("catalogue", {})
    if not args.offline and (not args.only or "wikicfp" in selected):
        n = enrich_events(history, http, geocoder, cat_cfg.get("event_details_per_run", 60))
        print(f"[OK] événements : {n} fiches détaillées (lieu, échéances)")

    # Géolocalisation de tout ce qui n'est pas encore sur la carte
    if not args.offline:
        n = enrich_locations(history, locator, cfg.get("locate", {}).get("items_per_run", 600))
        print(f"[OK] localisation : {n} éléments placés sur la carte ({locator.stats})")

    pruned = prune(history, cfg["retention_days"])

    # Alimentation du catalogue : fiches + notices (IA Gemini si GEMINI_API_KEY, sinon gabarits)
    writer = None if args.offline else LLMWriter(http, cfg.get("llm", {}), os.getenv("GEMINI_API_KEY"))
    cat_store = load_json(CATALOGUE_AUTO_PATH, {"version": 1, "entries": {}, "journals": {}})
    curated = load_json(RESSOURCES_PATH, {"items": []}).get("items", [])
    auto_entries, journals, cat_stats = update_catalogue(
        history, curated, cat_store, writer, None if args.offline else http, TODAY_S,
        search_budget=cat_cfg.get("journal_searches_per_run", 8),
        locator=None if args.offline else locator, cfg=cat_cfg)
    write_json(CATALOGUE_AUTO_PATH, cat_store)
    print(f"[OK] catalogue : +{cat_stats['added']} fiches, {cat_stats['updated']} mises à jour, "
          f"{cat_stats['removed']} retirées, {cat_stats['journals']} revues suivies"
          + (f", {writer.used} notices rédigées par IA" if writer and writer.used else ""))
    geocoder.save()

    # Historique des exécutions (60 dernières) pour le suivi de santé de l'agent
    if not args.offline:
        store["runs"] = ([{"date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                           "new": len(new_items), "sources": status}] + store.get("runs", []))[:60]
    store["items"] = dict(sorted(history.items()))
    write_json(HISTORY_PATH, store)

    # Charge utile du site : focus d'abord, puis les plus récents
    items = sorted(history.values(), key=lambda i: (i["first_seen"], i["date"]), reverse=True)
    cap = cfg.get("max_items_payload", 3000)
    if len(items) > cap:
        keep = [i for i in items if i.get("focus") or i["type"] in ("Opportunity", "Event", "Journal") or i.get("queries")]
        rest = [i for i in items if i not in keep][: max(0, cap - len(keep))]
        items = sorted(keep + rest, key=lambda i: (i["first_seen"], i["date"]), reverse=True)
    # Le texte intégral des appels sert à la rédaction ; inutile côté site
    items = [{**i, "event": {k: v for k, v in i["event"].items() if k != "cfp_text"}} if i.get("event") else i
             for i in items]
    # Allègement de la charge utile : champs internes retirés, résumés raccourcis
    DROP = ("geo_tried", "meta", "languages", "likes", "downloads", "last_seen", "place_hint", "details_checked",
            "link_checked", "category", "doc_type", "lang", "acronym", "page_checked")
    items = [{k: v for k, v in i.items() if k not in DROP} for i in items]
    for i in items:
        if len(i.get("summary") or "") > 240:
            i["summary"] = i["summary"][:239].rsplit(" ", 1)[0] + "…"
    notices, opportunites = split_payload_items(items)

    ressources = load_json(RESSOURCES_PATH, {"total": 0, "sources": [], "counts": {}, "items": []})
    curated_items = merge_curated(ressources.get("items", []), journals, cat_store.get("curated_geo", {}))
    auto_sorted = sorted(auto_entries, key=lambda e: (e.get("added") or "", e["id"]), reverse=True)
    cat_items = [slim_entry(e) for e in curated_items + auto_sorted]
    deadlines = collect_deadlines(cat_items, notices)
    # Catalogue complet dans un fichier à part (chargé à l'ouverture de l'onglet Catalogue) ;
    # radar.json n'embarque que le catalogue éditorial (couche « catalogue » de la carte).
    write_json(CATALOGUE_PATH, {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                "total": len(cat_items), "items": cat_items}, indent=None)
    ressources = {**{k: v for k, v in ressources.items() if k != "items"},
                  "items": [slim_entry(e) for e in curated_items], "total": len(cat_items), "curated": len(curated_items),
                  "sources": [s for s in ressources.get("sources", []) if s.get("id") != "veille"] + [
                      {"id": "veille", "label": "Ajouts de la veille", "count": len(auto_entries)}]}
    by_source, by_type, by_group = {}, {}, {}
    for i in items:
        by_source[i["source"]] = by_source.get(i["source"], 0) + 1
        by_type[i["type"]] = by_type.get(i["type"], 0) + 1
        for g in i.get("lang_groups", []):
            by_group[g] = by_group.get(g, 0) + 1
    last_run = store["runs"][0] if store.get("runs") else {}
    # Dernier statut connu de CHAQUE source (une exécution partielle --only n'efface pas les autres)
    source_status: dict = {}
    for run in store.get("runs", []):
        for name, st in run.get("sources", {}).items():
            source_status.setdefault(name, {**st, "date": run["date"]})
    payload = {
        "last_updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "today": TODAY_S,
        "repo": os.getenv("GITHUB_REPOSITORY") or cfg.get("repo"),
        "stats": {
            "total": len(items),
            "new_today": sum(1 for i in items if i["first_seen"] == TODAY_S),
            "new_7d": sum(1 for i in items if i["first_seen"] >= (TODAY - timedelta(days=7)).isoformat()),
            "focus": sum(1 for i in items if i.get("focus")),
            "located": sum(1 for i in items if i.get("lat") is not None),
            "by_source": by_source, "by_type": by_type, "by_group": by_group,
        },
        "agent": {"last_run": last_run.get("date"),
                  "sources": {k: source_status[k] for k in [*COLLECTORS, "requetes"] if k in source_status}},
        "requetes": [{"q": q, **{k: v for k, v in e.items() if k in ("url", "added", "last_run", "results")}}
                     for q, e in req_store.items()],
        "notices": {"total": len(notices), "items": notices},
        "opportunites": {"total": len(opportunites), "items": opportunites},
        "deadlines": deadlines,
        "ressources": ressources,
    }
    write_json(OUTPUT_PATH, payload, indent=None)
    write_feed(items, cfg["site_url"])

    ok = sum(1 for s in status.values() if s.get("ok"))
    msg = (f"[OK] veille : {len(new_items)} nouveautés, {len(notices)} éléments de veille, "
           f"{len(opportunites)} opportunités, {pruned} archivés, sources OK {ok}/{len(status)}")
    print(msg)
    step_summary([f"## Veille ConnecTAL — {TODAY_S}", "", f"**{len(new_items)}** nouveautés · "
                  f"{len(notices)} éléments de veille · {len(opportunites)} opportunités · {pruned} archivés · "
                  f"catalogue +{cat_stats['added']} fiches", "",
                  "| Source | Statut | Récupérés | Nouveaux |",
                  "|---|---|---|---|"] + [
        f"| {k} | {'✅' if v.get('ok') else '❌ ' + v.get('error', '')} | {v.get('fetched', '–')} | {v.get('new', '–')} |"
        for k, v in status.items()] + ["", "### Nouveautés"] + [
        f"- [{i['type']}] [{i['title']}]({i['url']})" for i in new_items[:60]])

    # Échec du job uniquement si TOUTES les sources sont tombées (pas sur une panne isolée)
    return 1 if status and ok == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
