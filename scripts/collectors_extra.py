"""Collecteurs complémentaires de l'agent de veille OmniTAL.

Ressources ouvertes : Zenodo, European Language Grid (ELG), DOAJ (revues en libre accès).
Opportunités       : NLP People (API JSON), tableaux d'offres d'organisations du TAL (Greenhouse,
                     Ashby, Lever), Remotive, Arbeitnow, Jobicy, Himalayas, We Work Remotely,
                     Hacker News « Who is hiring? », theses.fr, formations (liste éditoriale).

Chaque collecteur renvoie des éléments construits par `mk` (= make_item de l'agent) et ne
lève une exception que si la source entière est inaccessible : l'agent consigne alors
l'échec sans interrompre les autres sources.
"""
from __future__ import annotations

import html
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import date
from email.utils import parsedate_to_datetime
from pathlib import Path

from languages import LANGS, detect_languages

ROOT = Path(__file__).resolve().parent.parent
TYPE_ZENODO = {"dataset": "Corpus", "software": "Tool"}
ELG_PATH = {"Corpus": "corpus", "Tool/Service": "tool-service", "Lexical/Conceptual resource": "lcr",
            "Model": "ld", "Language description": "ld", "Grammar": "ld"}
ELG_TYPE = {"Corpus": "Corpus", "Tool/Service": "Tool", "Lexical/Conceptual resource": "Corpus", "Model": "Model"}


def _txt(s: str | None, limit: int | None = None) -> str:
    t = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    t = re.sub(r"\s+", " ", t).strip()
    return t[:limit] if limit else t


# ───────────────────────────── ressources ouvertes ─────────────────────────────

def collect_zenodo(http, cfg, mk, **_) -> list[dict]:
    z = cfg["zenodo"]
    queries = list(z.get("queries", []))
    if z.get("language_queries"):
        # une requête par groupe de langues : « (catalan OR basque …) AND (corpus OR dataset OR NLP) »
        for group in ("berbere", "mediterranee", "arabe"):
            names = [f'"{l["en"]}"' for l in LANGS if l["group"] == group and "(" not in l["en"] and "/" not in l["en"]]
            queries.append(f"({' OR '.join(names)}) AND (corpus OR dataset OR \"language model\" OR NLP OR speech)")
    out: dict[str, dict] = {}
    failures, calls = 0, 0
    for q in queries:
        for rtype in z["types"]:
            calls += 1
            try:
                data = http.get("https://zenodo.org/api/records", retries=1, params={
                    "q": q, "type": rtype, "sort": "mostrecent", "size": z["size"]}).json()
            except Exception as ex:
                print(f"    [Zenodo] {rtype} « {q[:40]}… » : {ex}")
                failures += 1
                continue
            for r in data.get("hits", {}).get("hits", []):
                m = r.get("metadata", {})
                rid = str(r.get("conceptrecid") or r.get("id"))
                if rid in out:
                    continue
                creators = m.get("creators") or []
                affil = next((c.get("affiliation") for c in creators if c.get("affiliation")), None)
                langs = [l for l in (m.get("language"),) if l]
                out[rid] = mk(
                    id=f"zenodo:{rid}", title=m.get("title", ""), type=TYPE_ZENODO.get(rtype, "Corpus"),
                    source="zenodo", url=r.get("links", {}).get("self_html") or r.get("doi_url", ""),
                    date_s=m.get("publication_date"), summary=_txt(m.get("description"), 600),
                    author=", ".join(c.get("name", "") for c in creators[:3]),
                    extra_text=" ".join(m.get("keywords") or []), languages=langs,
                    place_hint=affil, meta={"license": (m.get("license") or {}).get("id"),
                                            "keywords": (m.get("keywords") or [])[:8], "doi": r.get("doi")})
            time.sleep(1)
    if calls and failures == calls:
        raise RuntimeError("toutes les requêtes Zenodo ont échoué")
    return list(out.values())


def collect_elg(http, cfg, mk, **_) -> list[dict]:
    """European Language Grid : une recherche par langue méditerranéenne / berbère / arabe dialectale."""
    out: dict[str, dict] = {}
    terms = sorted({l["en"].split(" (")[0] for l in LANGS if l["focus"] and "/" not in l["en"] and l["code"] != "ar-dial"})
    for term in terms:
        try:
            data = http.get("https://live.european-language-grid.eu/catalogue_backend/api/registry/search/",
                            params={"search": term, "limit": cfg["elg"]["limit"], "ordering": "-creation_date"},
                            retries=1).json()
        except Exception as ex:
            print(f"    [ELG] {term} : {ex}")
            continue
        for r in data.get("results", []):
            if r.get("entity_type") != "LanguageResource":
                continue
            # la recherche ELG est plein texte : on exige que la langue figure dans les langues déclarées
            if not any(term.lower() in (x or "").lower() for x in r.get("languages") or []):
                continue
            rid = str(r["id"])
            if rid in out:
                continue
            rt = r.get("resource_type") or "Corpus"
            out[rid] = mk(
                id=f"elg:{rid}", title=r.get("resource_name", ""), type=ELG_TYPE.get(rt, "Tool"), source="elg",
                url=f"https://live.european-language-grid.eu/catalogue/{ELG_PATH.get(rt, 'corpus')}/{rid}",
                date_s=r.get("creation_date") or r.get("last_date_updated"), summary=_txt(r.get("description"), 600),
                author="European Language Grid", extra_text=" ".join(r.get("languages") or []) + " " + term,
                languages=r.get("languages") or [], country=(r.get("country_of_registration") or [None])[0],
                meta={"license": ", ".join(r.get("licence_short_name") or r.get("licences") or []) or None,
                      "access": ", ".join(r.get("condition_of_use") or []) or None,
                      "keywords": (r.get("keywords") or [])[:8], "resource_type": rt})
        time.sleep(0.6)
    return list(out.values())


def collect_doaj(http, cfg, mk, **_) -> list[dict]:
    """Revues en libre accès du domaine (classification LCC P98 : linguistique informatique / TAL)."""
    out = []
    for subj in cfg["doaj"]["subjects"]:
        page = 1
        while page <= 5:
            data = http.get(f'https://doaj.org/api/search/journals/bibjson.subject.code:"{subj}"', retries=1,
                            params={"page": page, "pageSize": cfg["doaj"]["page_size"]}).json()
            for r in data.get("results", []):
                b = r.get("bibjson", {})
                pub = b.get("publisher") or {}
                apc = b.get("apc") or {}
                out.append(mk(
                    id=f"doaj:{r['id']}", title=b.get("title", ""), type="Journal", source="doaj",
                    url=(b.get("ref") or {}).get("journal") or f"https://doaj.org/toc/{b.get('eissn') or b.get('pissn')}",
                    date_s=r.get("created_date"), summary=", ".join(b.get("keywords") or [])[:300],
                    author=pub.get("name", ""), country=pub.get("country"),
                    meta={"publisher": pub.get("name"), "country": pub.get("country"),
                          "license": ", ".join(l.get("type", "") for l in b.get("license") or []) or "Open access",
                          "apc": "oui" if apc.get("has_apc") else "non", "languages": b.get("language"),
                          "review": ", ".join((b.get("editorial") or {}).get("review_process") or []),
                          "author_instructions": (b.get("ref") or {}).get("author_instructions"),
                          "issn": b.get("eissn") or b.get("pissn")}))
            if page * cfg["doaj"]["page_size"] >= data.get("total", 0):
                break
            page += 1
            time.sleep(1)
    return out


# ───────────────────────────── opportunités ─────────────────────────────

def opp_kind(title: str, text: str = "") -> str:
    t = f"{title} {text[:200]}".lower()
    if re.search(r"\b(intern|internship|stage|stagiaire|praktikum|working student|werkstudent)\b", title.lower()):
        return "internship"
    if re.search(r"\b(post-?doc|postdoctoral|post-doctoral)", t):
        return "postdoc"
    if re.search(r"\b(ph\.?d|doctoral|doctorate|thèse|doctorant|doktorand)", t):
        return "phd"
    if re.search(r"\bsummer school|winter school|école d'été|spring school\b", t):
        return "school"
    return "job"


def _nlp_match(cfg, *texts: str) -> bool:
    blob = " ".join(t for t in texts if t).lower()
    return any(re.search(rf"(?<![a-z]){re.escape(k.strip())}(?![a-z])", blob) for k in cfg["opportunites"]["keywords"])


def _strict_nlp(cfg, title: str) -> bool:
    """Filtre resserré pour les tableaux généralistes (Jobicy, Himalayas, WWR, HN) : le titre doit
    viser le TAL (sinon « Translation Review Lead » ou « Full-stack engineer » passeraient)."""
    keys = cfg["opportunites"].get("strict_keywords") or [
        "nlp", "natural language", "language model", "llm", "computational linguist", "linguist",
        "speech", "asr", "tts", "machine translation", "conversational ai", "dialogue", "text mining",
        "information retrieval", "search relevance", "rag", "genai", "generative ai"]
    t = (title or "").lower()
    return any(re.search(rf"(?<![a-z]){re.escape(k)}(?![a-z])", t) for k in keys)


def collect_nlppeople(http, cfg, mk, **_) -> list[dict]:
    """NLP People — le site a abandonné son flux RSS (fin 2026) ; on lit son API JSON publique
    (lieu, pays et coordonnées fournis, plus besoin de lire chaque page d'offre)."""
    out: dict[str, dict] = {}
    pages = cfg["opportunites"].get("nlppeople_pages", 3)
    for page in range(1, pages + 1):
        try:
            jobs = http.get("https://nlppeople.com/api/v1/jobs", params={"limit": 50, "page": page}, retries=2).json()
        except Exception as ex:
            if page == 1:
                raise
            print(f"    [NLP People] page {page} : {ex}")
            break
        if not isinstance(jobs, list) or not jobs:
            break
        for j in jobs:
            if j.get("status") not in (None, "published") or not j.get("slug"):
                continue
            company = (j.get("company") or {}).get("name") or ""
            kinds = " ".join(j.get("type") or [])
            remote = re.search(r"remote", kinds, re.I)
            place = j.get("geoaddress") or ", ".join(x for x in (j.get("geocity"), j.get("geocountry")) if x) or None
            coords = (j.get("geocoordinates") or {}).get("coordinates") or []
            geo = {"lat": round(coords[1], 4), "lng": round(coords[0], 4), "city": j.get("geocity"),
                   "region": j.get("geocountry"), "geo_precision": "lieu"} if len(coords) == 2 else None
            desc = _txt(j.get("description"), 400)
            out[j["slug"]] = mk(
                id=f"nlppeople:{j['slug']}", title=j.get("title") or "", type="Opportunity", source="nlppeople",
                url=f"https://nlppeople.com/jobs/{j['slug']}", date_s=(j.get("date_created") or "")[:10] or None,
                summary=desc, author=company[:60], opp_kind=opp_kind(j.get("title") or "", desc),
                location=("Remote · " + place if remote and place else place or ("Remote" if remote else None)),
                place_hint=place, country=j.get("geocountry"), geo=geo,
                employment=", ".join(j.get("type") or []) or None, seniority=j.get("experience"),
                closing=(j.get("closing_date") or "")[:10] or None)
        time.sleep(1)
    return list(out.values())


def collect_job_boards(http, cfg, mk, **_) -> list[dict]:
    """Offres publiées par des organisations du TAL/IA (API publiques Greenhouse, Ashby, Lever)."""
    o = cfg["opportunites"]
    out = []
    for org in o.get("greenhouse", []):
        try:
            jobs = http.get(f"https://boards-api.greenhouse.io/v1/boards/{org}/jobs", retries=1).json().get("jobs", [])
        except Exception as ex:
            print(f"    [Greenhouse] {org} : {ex}")
            continue
        for j in jobs:
            if not _nlp_match(cfg, j.get("title")):
                continue
            loc = re.split(r"[;|]", (j.get("location") or {}).get("name") or "")[0].strip()
            out.append(mk(id=f"greenhouse:{org}:{j['id']}", title=j["title"], type="Opportunity", source="greenhouse",
                          url=j.get("absolute_url", ""), date_s=j.get("first_published") or j.get("updated_at"),
                          summary="", author=org.capitalize(), opp_kind=opp_kind(j["title"]),
                          location=loc or None, place_hint=loc or None))
        time.sleep(0.5)
    for org in o.get("ashby", []):
        try:
            jobs = http.get(f"https://api.ashbyhq.com/posting-api/job-board/{org}", retries=1).json().get("jobs", [])
        except Exception as ex:
            print(f"    [Ashby] {org} : {ex}")
            continue
        for j in jobs:
            if not j.get("isListed", True) or not _nlp_match(cfg, j.get("title"), j.get("team"), j.get("department")):
                continue
            loc = "Remote" if j.get("isRemote") and not j.get("location") else (j.get("location") or "")
            out.append(mk(id=f"ashby:{org}:{j['id']}", title=j["title"], type="Opportunity", source="ashby",
                          url=j.get("jobUrl") or j.get("applyUrl") or "", date_s=j.get("publishedAt"),
                          summary=_txt(j.get("descriptionPlain") or j.get("descriptionHtml"), 400),
                          author=org.capitalize(), opp_kind=opp_kind(j["title"]),
                          location=loc or None, place_hint=loc or None,
                          employment=j.get("employmentType")))
        time.sleep(0.5)
    for org in o.get("lever", []):
        try:
            jobs = http.get(f"https://api.lever.co/v0/postings/{org}", params={"mode": "json"}, retries=1).json()
        except Exception as ex:
            print(f"    [Lever] {org} : {ex}")
            continue
        for j in jobs if isinstance(jobs, list) else []:
            if not _nlp_match(cfg, j.get("text"), (j.get("categories") or {}).get("team")):
                continue
            loc = (j.get("categories") or {}).get("location") or ""
            out.append(mk(id=f"lever:{org}:{j['id']}", title=j.get("text", ""), type="Opportunity", source="lever",
                          url=j.get("hostedUrl", ""), date_s=None, summary=_txt(j.get("descriptionPlain"), 400),
                          author=org.capitalize(), opp_kind=opp_kind(j.get("text", "")),
                          location=loc or None, place_hint=loc or None))
    return out


def collect_remote_boards(http, cfg, mk, **_) -> list[dict]:
    """Remotive (télétravail, monde entier) et Arbeitnow (Europe), filtrés sur le TAL."""
    o = cfg["opportunites"]
    out: dict[str, dict] = {}
    for q in o.get("remotive_queries", []):
        try:
            jobs = http.get("https://remotive.com/api/remote-jobs", params={"search": q, "limit": 100}, retries=1).json().get("jobs", [])
        except Exception as ex:
            print(f"    [Remotive] {q} : {ex}")
            continue
        for j in jobs:
            desc = _txt(j.get("description"), 1500)
            if str(j["id"]) in out or not _nlp_match(cfg, j.get("title"), " ".join(j.get("tags") or [])):
                continue
            loc = j.get("candidate_required_location") or "Remote"
            out[str(j["id"])] = mk(
                id=f"remotive:{j['id']}", title=j["title"], type="Opportunity", source="remotive", url=j.get("url", ""),
                date_s=j.get("publication_date"), summary=desc[:400], author=j.get("company_name", ""),
                opp_kind=opp_kind(j["title"]), location=f"Télétravail · {loc}",
                place_hint=None if re.search(r"worldwide|anywhere", loc, re.I) else loc.split(",")[0],
                employment=j.get("job_type"), salary=j.get("salary") or None)
        time.sleep(1)
    if o.get("arbeitnow"):
        for page in (1, 2, 3):
            try:
                data = http.get("https://www.arbeitnow.com/api/job-board-api", params={"page": page}, retries=1).json()
            except Exception as ex:
                print(f"    [Arbeitnow] page {page} : {ex}")
                break
            for j in data.get("data", []):
                if not _nlp_match(cfg, j.get("title"), " ".join(j.get("tags") or [])):
                    continue
                out[j["slug"]] = mk(
                    id=f"arbeitnow:{j['slug']}", title=j["title"], type="Opportunity", source="arbeitnow",
                    url=j.get("url", ""), date_s=time.strftime("%Y-%m-%d", time.gmtime(j.get("created_at", 0))) if j.get("created_at") else None,
                    summary=_txt(j.get("description"), 400), author=j.get("company_name", ""),
                    opp_kind=opp_kind(j["title"]), location=j.get("location") or ("Remote" if j.get("remote") else None),
                    place_hint=j.get("location"))
            time.sleep(1)
    return list(out.values())


def collect_theses(http, cfg, mk, **_) -> list[dict]:
    """Thèses françaises en TAL (en préparation et soutenues) — API theses.fr."""
    out: dict[str, dict] = {}
    failures = 0
    queries = cfg["opportunites"]["theses_queries"]
    for q in queries:
        try:
            # theses.fr répond parfois lentement depuis les runners GitHub : délai de lecture long, 3 essais
            data = http.get("https://theses.fr/api/v1/theses/recherche/", retries=3, timeout=(20, 90),
                            params={"q": q, "debut": 0, "nombre": 50, "tri": "dateDesc"}).json()
        except Exception as ex:
            failures += 1
            print(f"    [theses.fr] « {q} » : {ex}")
            if failures == len(queries):
                raise
            continue
        for t in data.get("theses", []):
            if t["id"] in out:
                continue
            en_cours = t.get("status") == "enCours"
            d = t.get("dateSoutenance") or t.get("datePremiereInscriptionDoctorat")
            iso = "-".join(reversed(d.split("/"))) if d and "/" in d else d
            auteurs = ", ".join(f"{a.get('prenom', '')} {a.get('nom', '')}".strip() for a in t.get("auteurs") or [])
            directeurs = ", ".join(f"{a.get('prenom', '')} {a.get('nom', '')}".strip() for a in t.get("directeurs") or [])
            labs = [p["nom"] for p in t.get("partenairesDeRecherche") or [] if p.get("type") == "Laboratoire"]
            sujets = [s["libelle"] for s in t.get("sujets") or [] if s.get("langue") == "fr"][:6]
            out[t["id"]] = mk(
                id=f"theses:{t['id']}", title=t.get("titrePrincipal") or t.get("titreEN") or "", type="Opportunity",
                source="theses", url=f"https://theses.fr/{t['id']}", date_s=iso,
                summary=("Thèse en préparation" if en_cours else "Thèse soutenue") + f" — {t.get('discipline') or ''}"
                        + (f". Direction : {directeurs}" if directeurs else "") + (f". Laboratoire : {', '.join(labs)}" if labs else ""),
                author=auteurs, opp_kind="thesis", thesis_status="en cours" if en_cours else "soutenue",
                location=t.get("etabSoutenanceN"), place_hint=t.get("etabSoutenanceN"), country="FR",
                topics=sujets)
        time.sleep(1)
    return list(out.values())


def collect_formations(http, cfg, mk, today: str, previous: dict, **_) -> list[dict]:
    """Formations de la liste éditoriale config/formations.json, avec contrôle hebdomadaire des liens."""
    data = json.loads((ROOT / "config" / "formations.json").read_text(encoding="utf-8"))
    out = []
    for f in data["formations"]:
        fid = "formation:" + re.sub(r"[^a-z0-9]+", "-", f"{f['etablissement']} {f['intitule']}".lower()).strip("-")[:90]
        old = previous.get(fid) or {}
        status = old.get("link_status")
        checked = old.get("link_checked")
        if not checked or (date.fromisoformat(today) - date.fromisoformat(checked)).days >= 7:
            try:
                r = http.s.get(f["lien"], timeout=20, allow_redirects=True)
                status = r.status_code
            except Exception:
                status = 0
            checked = today
            time.sleep(0.5)
        place = ", ".join(x for x in (f["etablissement"].split(" – ")[0].split(" (")[0], f.get("ville"), f.get("pays")) if x)
        out.append(mk(
            id=fid, title=f["intitule"], type="Opportunity", source="formations", url=f["lien"], date_s=None,
            summary=f"{f['etablissement']}" + (f" — {f['ville']}" if f.get("ville") else "") + f". Langue(s) d'enseignement : {f['langues']}.",
            author=f["etablissement"], opp_kind=f["niveau"], location=f.get("ville") or "Lieu variable",
            place_hint=place if f.get("ville") else None, country=f.get("pays"),
            link_status=status, link_checked=checked, teaching_languages=f["langues"]))
    return out


def _loc_country(loc: str | None) -> str | None:
    from geo import country_code
    return country_code(loc)


def collect_jobicy(http, cfg, mk, **_) -> list[dict]:
    """Jobicy — offres en télétravail (API publique), filtrées sur le TAL."""
    out: dict[str, dict] = {}
    for tag in cfg["opportunites"].get("jobicy_tags", ["nlp", "machine learning", "ai"]):
        try:
            data = http.get("https://jobicy.com/api/v2/remote-jobs", params={"count": 50, "tag": tag}, retries=1).json()
        except Exception as ex:
            print(f"    [Jobicy] {tag} : {ex}")
            continue
        for j in data.get("jobs") or []:
            if str(j.get("id")) in out or not _strict_nlp(cfg, j.get("jobTitle")):
                continue
            geo = re.sub(r"\s+", " ", j.get("jobGeo") or "Anywhere").strip(" ,")
            first = geo.split(",")[0].strip()
            out[str(j["id"])] = mk(
                id=f"jobicy:{j['id']}", title=_txt(j.get("jobTitle")), type="Opportunity", source="jobicy",
                url=j.get("url", ""), date_s=(j.get("pubDate") or "")[:10] or None,
                summary=_txt(j.get("jobExcerpt"), 400), author=j.get("companyName", ""),
                opp_kind=opp_kind(j.get("jobTitle") or ""), location=f"Remote · {geo[:80]}",
                place_hint=None if re.search(r"anywhere|worldwide|europe|emea|latam", first, re.I) or "," in geo else first,
                country=None if "," in geo else first, employment=_txt(str(j.get("jobType") or "")).strip("[]'") or None)
        time.sleep(1)
    return list(out.values())


def collect_himalayas(http, cfg, mk, **_) -> list[dict]:
    """Himalayas — moteur d'offres en télétravail (API de recherche publique)."""
    out: dict[str, dict] = {}
    for q in cfg["opportunites"].get("himalayas_queries", ["natural language processing", "nlp", "computational linguistics", "speech recognition", "llm"]):
        for page in (1, 2):
            try:
                data = http.get("https://himalayas.app/jobs/api/search", params={"q": q, "page": page}, retries=1).json()
            except Exception as ex:
                print(f"    [Himalayas] {q} p{page} : {ex}")
                break
            jobs = data.get("jobs") or []
            for j in jobs:
                gid = j.get("guid") or j.get("applicationLink")
                if not gid or gid in out or not _strict_nlp(cfg, j.get("title")):
                    continue
                restr = j.get("locationRestrictions") or []
                if isinstance(restr, str):
                    restr = re.findall(r"'([^']+)'", restr) or [restr]
                loc = ", ".join(restr[:3]) if restr else "Anywhere"
                ts = j.get("pubDate")
                d = time.strftime("%Y-%m-%d", time.gmtime(int(ts))) if str(ts or "").isdigit() else None
                out[gid] = mk(
                    id=f"himalayas:{gid.rstrip('/').rsplit('/', 2)[-2]}:{gid.rstrip('/').rsplit('/', 1)[-1]}",
                    title=_txt(j.get("title")), type="Opportunity", source="himalayas", url=gid, date_s=d,
                    summary=_txt(j.get("excerpt"), 400), author=j.get("companyName", ""),
                    opp_kind=opp_kind(j.get("title") or ""), location=f"Remote · {loc}",
                    place_hint=restr[0] if len(restr) == 1 else None, country=restr[0] if len(restr) == 1 else None,
                    employment=j.get("employmentType"))
            if len(jobs) < 20:
                break
            time.sleep(1)
        time.sleep(1)
    return list(out.values())


def collect_weworkremotely(http, cfg, mk, **_) -> list[dict]:
    """We Work Remotely — flux RSS par catégorie, filtrés sur le TAL."""
    out: dict[str, dict] = {}
    for cat in cfg["opportunites"].get("wwr_categories", ["remote-programming-jobs", "remote-back-end-programming-jobs", "remote-full-stack-programming-jobs"]):
        try:
            root = ET.fromstring(http.get(f"https://weworkremotely.com/categories/{cat}.rss", retries=1).content)
        except Exception as ex:
            print(f"    [WWR] {cat} : {ex}")
            continue
        for it in root.iter("item"):
            full = it.findtext("title") or ""
            company, _, title = full.partition(": ")
            if not _strict_nlp(cfg, title or full):
                continue
            link = (it.findtext("link") or "").strip()
            region = it.findtext("region") or "Anywhere"
            pub = it.findtext("pubDate")
            wid = f"wwr:{link.rstrip('/').rsplit('/', 1)[-1]}"
            out[wid] = (mk(
                id=wid, title=title or full, type="Opportunity",
                source="weworkremotely", url=link, date_s=parsedate_to_datetime(pub).date().isoformat() if pub else None,
                summary=_txt(it.findtext("description"), 400), author=company,
                opp_kind=opp_kind(title or full), location=f"Remote · {region}",
                place_hint=None, country=None if re.search(r"anywhere|world", region, re.I) else region))
        time.sleep(1)
    return list(out.values())


def collect_hn_hiring(http, cfg, mk, **_) -> list[dict]:
    """Hacker News « Ask HN: Who is hiring? » (fil mensuel) — commentaires TAL via l'API Algolia."""
    stories = http.get("https://hn.algolia.com/api/v1/search_by_date",
                       params={"tags": "story,author_whoishiring", "hitsPerPage": 6}, retries=1).json().get("hits", [])
    story = next((h for h in stories if "who is hiring" in (h.get("title") or "").lower()), None)
    if not story:
        return []
    sid = story["objectID"]
    out: dict[str, dict] = {}
    for q in cfg["opportunites"].get("hn_queries", ["NLP", "LLM", "natural language", "speech", "linguist"]):
        try:
            hits = http.get("https://hn.algolia.com/api/v1/search", retries=1, params={
                "tags": f"comment,story_{sid}", "query": q, "hitsPerPage": 100}).json().get("hits", [])
        except Exception as ex:
            print(f"    [HN] {q} : {ex}")
            continue
        for h in hits:
            if str(h.get("parent_id")) != str(sid) or h["objectID"] in out:
                continue  # offres = commentaires de premier niveau
            text = html.unescape(h.get("comment_text") or "")
            first = _txt(re.split(r"<p>", text)[0], 300)
            parts = [p.strip() for p in first.split("|") if p.strip()]
            if len(parts) < 2 or not _nlp_match(cfg, text[:1500]):
                continue
            company = parts[0][:60]
            # « Société | Poste | Lieu | Remote | Salaire » — l'ordre varie d'une annonce à l'autre
            job_rx = re.compile(r"engineer|scientist|research|developer|lead|manager|founding|designer|intern|head of|"
                                r"director|analyst|architect|linguist|\bml\b|\bai\b|nlp|llm", re.I)
            loc_rx = re.compile(r"remote|onsite|on-site|in-office|hybrid|^[A-Z][a-zA-Z .]+(,|\s\()|\b(USA|UK|EU|US)\b")
            role = next((p for p in parts[1:] if job_rx.search(p) and not re.search(r"https?://", p)), parts[1])[:140]
            loc = next((p for p in parts[1:] if p != role and loc_rx.search(p) and len(p) < 70), None)
            out[h["objectID"]] = mk(
                id=f"hn:{h['objectID']}", title=f"{role} — {company}", type="Opportunity", source="hnhiring",
                url=f"https://news.ycombinator.com/item?id={h['objectID']}", date_s=(h.get("created_at") or "")[:10],
                summary=_txt(text, 400), author=company, opp_kind=opp_kind(role, text[:300]),
                location=loc, place_hint=re.sub(r"(?i)\b(remote|onsite|on-site|hybrid)\b[^,]*,?", "", loc or "").strip(" ,()") or None)
        time.sleep(1)
    return list(out.values())

