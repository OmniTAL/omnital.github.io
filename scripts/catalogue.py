"""Alimentation du catalogue par l'agent de veille.

À chaque exécution :
  1. les ressources détectées (Hugging Face, GitHub, WikiCFP) deviennent des fiches du catalogue,
     avec une notice rédigée (IA si disponible, sinon gabarit) ;
  2. chaque événement reçoit sa localisation et ses échéances (résumés, articles, notification) ;
  3. chaque revue du catalogue reçoit une notice et la liste de ses numéros spéciaux ouverts
     (date limite de soumission), recoupés depuis WikiCFP.

Le magasin data/catalogue_auto.json est persistant : une fiche reste au catalogue même quand
l'élément sort de l'historique de veille (sauf les événements terminés depuis plus de 30 jours).
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, timedelta

from build_ressources import licence_class
from cfp import mentions_journal, search_special_issues
from notices import LANG_NAMES, rule_notice

ELIGIBLE_SOURCES = {"huggingface", "github", "wikicfp", "zenodo", "elg", "doaj"}
SPECIAL_ISSUE_RX = re.compile(r"special issue|numéro spécial|\bjournal\b|topical collection", re.I)
EVENT_KEYS = ("start", "end", "location", "abstract_deadline", "paper_deadline", "notification",
              "camera_ready", "website", "categories", "deadline_sources")


def kind_of(it: dict) -> str:
    if it["source"] == "huggingface":
        return {"Corpus": "hf_dataset", "Model": "hf_model"}.get(it["type"], "hf_space")
    if it["source"] == "github":
        return "github"
    if it["source"] == "wikicfp":
        return "special_issue" if SPECIAL_ISSUE_RX.search(it.get("title", "")) else "event"
    if it["source"] == "zenodo":
        return "zenodo_software" if it["type"] == "Tool" else "zenodo_dataset"
    if it["source"] == "elg":
        return {"Corpus": "elg_corpus", "Model": "elg_model"}.get(it["type"], "elg_tool")
    if it["source"] == "doaj":
        return "journal_oa"
    return "other"


CATEGORY = {"hf_dataset": "cat_Dataset", "hf_model": "cat_Model", "hf_space": "cat_Tool",
            "github": "cat_Tool", "event": "cat_Event", "special_issue": "cat_Journal",
            "zenodo_dataset": "cat_Dataset", "zenodo_software": "cat_Tool",
            "elg_corpus": "cat_Dataset", "elg_model": "cat_Model", "elg_tool": "cat_Tool", "journal_oa": "cat_Journal"}
TYPE_LABEL = {"hf_dataset": "Dataset (Hugging Face)", "hf_model": "Modèle (Hugging Face)",
              "hf_space": "Démo (Hugging Face Space)", "github": "Dépôt GitHub",
              "event": "Appel à communications", "special_issue": "Numéro spécial de revue",
              "zenodo_dataset": "Jeu de données (Zenodo)", "zenodo_software": "Logiciel (Zenodo)",
              "elg_corpus": "Corpus (European Language Grid)", "elg_model": "Modèle (European Language Grid)",
              "elg_tool": "Outil (European Language Grid)", "journal_oa": "Revue en libre accès (DOAJ)"}


def _upcoming(*isos: str | None, today: str) -> str | None:
    future = sorted(d for d in isos if d and d >= today)
    return future[0] if future else None


def _source_text(it: dict) -> str:
    return (it.get("event") or {}).get("cfp_text") or it.get("summary") or ""


def _notice(kind: str, it: dict, entry: dict, writer, meta: dict) -> None:
    """Rédige (ou réécrit) la notice d'une fiche. L'IA n'est appelée qu'une fois par fiche."""
    if entry.get("notice_by") == "ia" and not entry.get("_event_changed"):
        return
    rules = rule_notice(kind, it)
    entry["description"] = rules
    entry["notice_by"] = "règles"
    if writer and writer.available:
        res = writer.write(kind, meta, _source_text(it))
        if res:
            entry["description"] = {"fr": res["fr"], "en": res.get("en") or rules["en"]}
            entry["notice_by"] = "ia"
            ev = entry.get("event")
            if ev is not None:  # l'IA complète seulement les échéances manquantes (vérifiées dans le texte)
                for k in ("abstract_deadline", "paper_deadline", "location"):
                    if res.get(k) and not ev.get(k):
                        ev[k] = res[k]
                        ev.setdefault("deadline_sources", {})[k] = "IA (date vérifiée dans le texte)"


def entry_from_item(it: dict, old: dict | None, writer) -> dict:
    kind = kind_of(it)
    meta = it.get("meta") or {}
    langs = it.get("languages") or []
    entry = dict(old or {})
    entry.update({
        "id": it["id"], "nom": it["title"],
        "source": "veille", "origin": "veille", "provider": it["source"], "kind": kind,
        "categorie_key": CATEGORY.get(kind, "cat_Tool"), "type": TYPE_LABEL.get(kind),
        "langue": ", ".join(dict.fromkeys(LANG_NAMES.get(c, (c,))[0].capitalize() for c in langs[:4])) or None,
        "taille": meta.get("size"), "licence": meta.get("license"),
        "licence_class": licence_class(meta.get("license")) if meta.get("license") not in (None, "other", "unknown") else "unknown",
        "lien": it["url"], "added": entry.get("added") or it["first_seen"], "focus": it.get("focus", False),
        "region": it.get("region"), "city": it.get("city"), "lat": it.get("lat"), "lng": it.get("lng"),
        "pays": it.get("region") if it.get("region") not in (None, "International") else None,
        "geo_precision": it.get("geo_precision"), "geo_source": it.get("geo_source"),
        "lang_groups": it.get("lang_groups"), "lang_codes": it.get("lang_codes"),
        "queries": it.get("queries"), "trending": it.get("trending"),
    })
    entry = {k: v for k, v in entry.items() if v not in (None, [], "")}
    if kind == "journal_oa":
        entry["licence"] = meta.get("license") or "Open access"
        entry["licence_class"] = "open"
        entry["journal"] = {**(entry.get("journal") or {}), "submission": "continuous", "apc": meta.get("apc"),
                            "author_instructions": meta.get("author_instructions"), "publisher": meta.get("publisher"),
                            "review": meta.get("review"), "issn": meta.get("issn")}
    if kind in ("event", "special_issue"):
        ev_src = it.get("event") or {}
        new_ev = {k: ev_src.get(k) for k in EVENT_KEYS if ev_src.get(k)}
        new_ev.setdefault("start", it.get("date") or None)
        new_ev.setdefault("end", it.get("date_end"))
        new_ev.setdefault("location", it.get("location"))
        new_ev = {k: v for k, v in new_ev.items() if v}
        old_ev = (old or {}).get("event") or {}
        # on conserve ce que l'IA a complété lors d'un passage précédent
        for k in ("abstract_deadline", "paper_deadline", "location"):
            src = old_ev.get("deadline_sources", {}).get(k, "")
            if old_ev.get(k) and not new_ev.get(k) and src.startswith("IA"):
                new_ev[k] = old_ev[k]
                new_ev.setdefault("deadline_sources", {})[k] = src
        entry["_event_changed"] = {k: v for k, v in new_ev.items() if k != "deadline_sources"} != \
                                  {k: v for k, v in old_ev.items() if k != "deadline_sources"} and bool(old)
        entry["event"] = new_ev
        entry["cfp_url"] = it["url"]
        if new_ev.get("website"):
            entry["lien"] = new_ev["website"]  # site officiel de préférence
        it = {**it, "event": {**ev_src, **new_ev}}
        meta = {**meta, "titre": it["title"], "acronyme": it.get("acronym"), **{k: v for k, v in new_ev.items() if k != "deadline_sources"}}
    else:
        meta = {**meta, "nom": it["title"], "auteur": it.get("author"), "date": it.get("date"),
                "langues": langs, "description": it.get("summary"), "source": it["source"]}
    _notice(kind, it, entry, writer, meta)
    entry.pop("_event_changed", None)
    return entry


def update_catalogue(history: dict, curated: list[dict], store: dict, writer, http, today: str,
                     search_budget: int = 8, locator=None, cfg: dict | None = None) -> tuple[list[dict], dict, dict]:
    """Met à jour le magasin persistant et renvoie (fiches auto, enrichissements des revues, stats)."""
    entries: dict = store.setdefault("entries", {})
    journals: dict = store.setdefault("journals", {})
    duplicates: dict = store.setdefault("duplicates", {})  # id écarté → id conservé
    stats = {"added": 0, "updated": 0, "removed": 0, "journals": 0}

    cfg = cfg or {}
    eligible = set(cfg.get("eligible_sources") or ELIGIBLE_SOURCES)

    limit0 = (date.fromisoformat(today) - timedelta(days=30)).isoformat()

    def expired(it: dict) -> bool:
        ev = it.get("event") or {}
        if it["source"] != "wikicfp":
            return False
        if kind_of(it) == "special_issue":
            return bool(ev.get("paper_deadline")) and ev["paper_deadline"] < limit0
        end = ev.get("end") or it.get("date_end") or ev.get("start") or it.get("date") or ev.get("paper_deadline")
        return bool(end) and end < limit0

    # 1) Ressources et événements détectés par la veille → fiches
    for it in history.values():
        if it["source"] not in eligible or it["id"] in duplicates or expired(it):
            continue
        old = entries.get(it["id"])
        entries[it["id"]] = entry_from_item(it, old, writer)
        stats["updated" if old else "added"] += 1

    # 2) Événements terminés depuis > 30 jours : retirés du catalogue ; ressources « tendances »
    #    (hors langues suivies et hors requêtes) retirées au-delà de nonfocus_max_age_days
    limit = (date.fromisoformat(today) - timedelta(days=30)).isoformat()
    old_limit = (date.fromisoformat(today) - timedelta(days=cfg.get("nonfocus_max_age_days", 365))).isoformat()
    for k, e in list(entries.items()):
        if not e.get("focus") and not e.get("queries") and not e.get("event") and e.get("kind") != "journal_oa" \
                and (e.get("added") or today) < old_limit and k not in history:
            del entries[k]; stats["removed"] += 1
            continue
        ev = e.get("event") or {}
        end = ev.get("end") or ev.get("start") or ev.get("paper_deadline")
        if e.get("kind") == "event" and end and end < limit:
            del entries[k]; stats["removed"] += 1
        elif e.get("kind") == "special_issue" and ev.get("paper_deadline") and ev["paper_deadline"] < limit:
            del entries[k]; stats["removed"] += 1

    # 3) Revues du catalogue : notice + numéros spéciaux ouverts
    cfp_items = [i for i in history.values() if i["source"] == "wikicfp"]
    # Numéros spéciaux des revues DOAJ (recoupement avec les appels WikiCFP déjà captés)
    for e in entries.values():
        if e.get("kind") != "journal_oa":
            continue
        issues = []
        for c in cfp_items:
            if mentions_journal(f"{c['title']} {c.get('summary', '')}", e["nom"]):
                ev = c.get("event") or {}
                dl = ev.get("paper_deadline")
                if not dl or dl >= today:
                    issues.append({"title": c.get("summary") or c["title"], "deadline": dl,
                                   "abstract_deadline": ev.get("abstract_deadline"), "url": c["url"]})
        e["journal"]["special_issues"] = issues
        e["journal"]["next_deadline"] = _upcoming(*(d for i in issues for d in (i.get("abstract_deadline"), i.get("deadline"))), today=today)
        e["deadline_next"] = e["journal"]["next_deadline"]

    # Géolocalisation des fiches du catalogue éditorial (une fois, réessai mensuel si échec)
    cgeo: dict = store.setdefault("curated_geo", {})
    retry = (date.fromisoformat(today) - timedelta(days=30)).isoformat()
    if locator:
        for r in curated:
            if r.get("lat") is not None:
                continue
            g = cgeo.get(r["id"])
            if g and (g.get("lat") is not None or g.get("tried", "") >= retry):
                continue
            pub = r.get("pays") if r.get("categorie_key") == "cat_Journal" else None
            found = locator.locate(url=r.get("lien"), text=f"{r['nom']} {(r.get('description') or {}).get('fr', '')} {r.get('langue') or ''}",
                                   country=None if (r.get("pays") or "").startswith("International") else r.get("pays"),
                                   publisher=pub)
            cgeo[r["id"]] = found or {"lat": None, "tried": today}

    for r in curated:
        if r.get("categorie_key") != "cat_Journal":
            continue
        j = journals.setdefault(r["id"], {})
        if j.get("notice_by") != "ia":
            j["notice"] = rule_notice("journal", r)
            j["notice_by"] = "règles"
            if writer and writer.available:
                res = writer.write("journal", {k: r.get(k) for k in ("nom", "type", "pays", "licence", "lien", "langue")})
                if res:
                    j["notice"] = {"fr": res["fr"], "en": res.get("en") or j["notice"]["en"]}
                    j["notice_by"] = "ia"
        # reconstruit à chaque passage : résultats de recherche mémorisés + appels captés par la veille
        j["search_issues"] = [i for i in j.get("search_issues", []) if not i.get("deadline") or i["deadline"] >= today]
        issues = {i["url"]: i for i in j["search_issues"]}
        # a) appels déjà captés par la veille (flux RSS WikiCFP)
        for c in cfp_items:
            if mentions_journal(f"{c['title']} {c.get('summary', '')}", r["nom"]):
                ev = c.get("event") or {}
                dl = ev.get("paper_deadline")
                # appel sans aucune date et d'une année passée (« … 2021 : Special Issue ») : périmé
                years = [int(y) for y in re.findall(r"\b(20\d\d)\b", c["title"])]
                if not dl and not ev.get("abstract_deadline") and years and max(years) < int(today[:4]):
                    continue
                if not dl or dl >= today:
                    issues[c["url"]] = {"title": c.get("summary") or c["title"], "deadline": dl,
                                        "abstract_deadline": ev.get("abstract_deadline"), "url": c["url"]}
        # b) recherche WikiCFP ciblée, au plus une fois par semaine et par revue
        due = not j.get("searched") or j["searched"] < (date.fromisoformat(today) - timedelta(days=7)).isoformat()
        if http and due and search_budget > 0:
            search_budget -= 1
            try:
                found = search_special_issues(http, r["nom"], today)
                j["search_issues"] = found
                for s in found:
                    issues.setdefault(s["url"], s)
                j["searched"] = today
            except Exception as ex:
                print(f"    [revues] recherche « {r['nom']} » : {ex}")
        j["special_issues"] = sorted(issues.values(), key=lambda i: i.get("deadline") or "9999")
        j["submission"] = "continuous"
        j["next_deadline"] = _upcoming(*(d for i in j["special_issues"]
                                         for d in (i.get("abstract_deadline"), i.get("deadline"))), today=today)
        stats["journals"] += 1

    # 4) Doublons WikiCFP (même conférence publiée deux fois : « ALTA 2026 » / « ALTA 2026 2026 »)
    def ev_key(e: dict) -> str | None:
        ev = e.get("event") or {}
        if e.get("kind") != "event":
            return None
        if ev.get("website"):
            return "w:" + re.sub(r"^https?://(www\.)?", "", ev["website"].lower()).rstrip("/")
        acro = re.sub(r"[^a-z]", "", (e["nom"].split(":")[0]).lower())
        return f"a:{acro}:{ev.get('start')}" if ev.get("start") else None
    best: dict[str, str] = {}
    for k, e in sorted(entries.items()):
        key = ev_key(e)
        if not key:
            continue
        score = lambda x: sum(1 for f in ("abstract_deadline", "paper_deadline", "notification", "location")
                              if (x.get("event") or {}).get(f))
        if key in best:
            keep, drop = (k, best[key]) if score(e) > score(entries[best[key]]) else (best[key], k)
            entries.pop(drop, None); stats["removed"] += 1
            duplicates[drop] = keep
            best[key] = keep
        else:
            best[key] = k

    # 5) Échéance la plus proche de chaque fiche (tri « prochaine échéance » côté site)
    out = []
    for e in entries.values():
        ev = e.get("event") or {}
        if ev:
            e["deadline_next"] = _upcoming(ev.get("abstract_deadline"), ev.get("paper_deadline"), today=today)
        out.append(e)
    return out, journals, stats


def merge_curated(curated: list[dict], journals: dict, curated_geo: dict | None = None) -> list[dict]:
    """Injecte notices, échéances des revues et positions dans les fiches du catalogue manuel."""
    merged = []
    for r in curated:
        r = {**r, "origin": "curated"}
        g = (curated_geo or {}).get(r["id"])
        if r.get("lat") is None and g and g.get("lat") is not None:
            r.update({k: g[k] for k in ("lat", "lng", "city", "region", "geo_precision", "geo_source") if g.get(k) is not None})
        j = journals.get(r["id"])
        if j:
            r["notice"] = j.get("notice")
            r["notice_by"] = j.get("notice_by")
            r["journal"] = {"submission": j.get("submission", "continuous"),
                            "special_issues": j.get("special_issues", [])[:6],
                            "next_deadline": j.get("next_deadline")}
            r["deadline_next"] = j.get("next_deadline")
        merged.append(r)
    return merged


def stable_hash(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()[:10]
