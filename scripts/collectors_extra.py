"""Collecteurs complémentaires de l'agent de veille ConnecTAL.

Ressources ouvertes : Zenodo, European Language Grid (ELG), DOAJ (revues en libre accès).
Opportunités       : NLP People, tableaux d'offres d'organisations du TAL (Greenhouse, Ashby,
                     Lever), Remotive, Arbeitnow, theses.fr, formations (liste éditoriale).

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
    terms = sorted({l["en"].split(" (")[0] for l in LANGS if "/" not in l["en"] and l["code"] != "ar-dial"})
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


def collect_nlppeople(http, cfg, mk, previous: dict | None = None, **_) -> list[dict]:
    out = []
    budget = 40  # pages d'offres lues par exécution pour trouver le lieu (données structurées JSON-LD)
    for page in range(1, cfg["opportunites"]["nlppeople_pages"] + 1):
        url = "https://nlppeople.com/jobs/feed/" + (f"?paged={page}" if page > 1 else "")
        try:
            root = ET.fromstring(http.get(url, retries=1).content)
        except Exception as ex:
            if page == 1:
                raise
            print(f"    [NLP People] page {page} : {ex}")
            break
        for it in root.iter("item"):
            title = it.findtext("title") or ""
            desc = _txt(it.findtext("description"))
            link = (it.findtext("link") or "").split("?utm_")[0]
            pid = re.search(r"[?&]p=(\d+)", it.findtext("guid") or "") or re.search(r"/job/([^/]+)/", link)
            # « Société | Ville, Pays | hybride | … » en tête de description
            parts = [p.strip() for p in desc.split("|")]
            place = next((p for p in parts[:4] if re.search(r",\s*[A-Z]", p) and len(p) < 60), None)
            iid = f"nlppeople:{pid.group(1) if pid else link}"
            old = (previous or {}).get(iid) or {}
            place = place or old.get("location")
            checked = bool(old.get("page_checked"))
            if not place and not checked and budget > 0:
                budget -= 1
                checked = True
                try:
                    page = http.get(link, retries=0).text
                    loc = re.findall(r'"addressLocality"\s*:\s*"([^"]+)"', page)
                    ctry = re.findall(r'"addressCountry"\s*:\s*(?:\{[^}]*"name"\s*:\s*)?"([^"]+)"', page)
                    place = ", ".join(x for x in (loc[0] if loc else "", ctry[0] if ctry else "") if x) or None
                    if not place and re.search(r'"jobLocationType"\s*:\s*"TELECOMMUTE"', page):
                        place = "Remote"
                except Exception:
                    pass
                time.sleep(1)
            pub = it.findtext("pubDate")
            if place:
                place = re.sub(r"\s*\(\+\d+ others?\)", "", place).strip()
            out.append(mk(
                id=iid, title=title, type="Opportunity", source="nlppeople",
                url=link, date_s=parsedate_to_datetime(pub).date().isoformat() if pub else None,
                summary=desc[:400], author=parts[0][:60] if len(parts) > 1 else "",
                opp_kind=opp_kind(title, desc), location=place, place_hint=place,
                page_checked=checked or None))
        time.sleep(1.5)
    return out


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
    for q in cfg["opportunites"]["theses_queries"]:
        data = http.get("https://theses.fr/api/v1/theses/recherche/", retries=1,
                        params={"q": q, "debut": 0, "nombre": 50, "tri": "dateDesc"}).json()
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
