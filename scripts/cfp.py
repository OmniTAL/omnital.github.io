"""Extraction des échéances d'appels à communications (WikiCFP + texte libre).

- `fetch_event_details` lit la page WikiCFP d'un événement : lieu, dates, site officiel,
  texte de l'appel et échéances structurées (micro-données RDF « v:summary » / « v:startDate »).
- `find_dates_in_text` / `deadlines_from_text` repèrent les dates citées dans un texte libre :
  c'est le repli quand WikiCFP n'a pas renseigné la date limite des résumés, et c'est aussi
  le garde-fou anti-hallucination du rédacteur IA (une date n'est acceptée que si elle
  figure réellement dans le texte source).
- `search_special_issues` cherche les numéros spéciaux ouverts d'une revue sur WikiCFP.
"""
from __future__ import annotations

import html
import re
from datetime import date, datetime

MONTHS = {
    # anglais
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9,
    "september": 9, "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
    # français
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "août": 8, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11,
    "décembre": 12, "decembre": 12,
}
_M = "|".join(sorted(MONTHS, key=len, reverse=True))
DATE_PATTERNS = [
    # Oct 11, 2026 / October 11th, 2026
    re.compile(rf"\b(?P<m>{_M})\.?\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<y>20\d\d)\b", re.I),
    # 11 Oct 2026 / 11 octobre 2026 / 1er mars 2027
    re.compile(rf"\b(?P<d>\d{{1,2}})(?:st|nd|rd|th|er)?\s+(?P<m>{_M})\.?,?\s+(?P<y>20\d\d)\b", re.I),
    # 2026-10-11
    re.compile(r"\b(?P<y>20\d\d)-(?P<mn>\d{2})-(?P<d>\d{2})\b"),
]

ABSTRACT_RX = re.compile(r"abstract|résumé|resume|intention", re.I)
PAPER_RX = re.compile(r"(full|long|short)?\s*paper|submission|soumission|article|manuscript|communication", re.I)
NOTIF_RX = re.compile(r"notification|acceptance|acceptation", re.I)
CAMERA_RX = re.compile(r"camera|final version|version finale", re.I)


def _to_iso(m: re.Match) -> str | None:
    try:
        month = int(m.group("mn")) if "mn" in m.groupdict() and m.group("mn") else MONTHS[m.group("m").lower().rstrip(".")]
        return date(int(m.group("y")), month, int(m.group("d"))).isoformat()
    except (ValueError, KeyError):
        return None


def find_dates_in_text(text: str) -> list[tuple[int, str]]:
    """Toutes les dates du texte : liste de (position, AAAA-MM-JJ)."""
    found = []
    for rx in DATE_PATTERNS:
        for m in rx.finditer(text or ""):
            iso = _to_iso(m)
            if iso:
                found.append((m.start(), iso))
    return sorted(found)


def deadlines_from_text(text: str) -> dict:
    """Associe chaque date au libellé qui la précède (≈ 90 caractères de contexte)."""
    out: dict[str, str] = {}
    for pos, iso in find_dates_in_text(text):
        ctx = text[max(0, pos - 90):pos]
        # on ne regarde que la « ligne » courante pour ne pas hériter du libellé précédent
        ctx = re.split(r"[\n•;]|\s-\s|\.\s", ctx)[-1]
        if CAMERA_RX.search(ctx):
            key = "camera_ready"
        elif NOTIF_RX.search(ctx):
            key = "notification"
        elif ABSTRACT_RX.search(ctx):
            key = "abstract_deadline"
        elif PAPER_RX.search(ctx) or re.search(r"deadline|due|date limite", ctx, re.I):
            key = "paper_deadline"
        else:
            continue
        out.setdefault(key, iso)  # première occurrence = date d'origine (les reports suivent souvent)
    return out


def _clean(fragment: str) -> str:
    t = re.sub(r"<br\s*/?>|</p>|</li>", "\n", fragment, flags=re.I)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    t = re.sub(r"[ \t\xa0]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t).strip()


WIKICFP_LABELS = {
    "abstract registration due": "abstract_deadline",
    "submission deadline": "paper_deadline",
    "notification due": "notification",
    "final version due": "camera_ready",
}


def parse_event_page(page: str) -> dict:
    """Analyse une page event.showcfp de WikiCFP."""
    info: dict = {}
    # Échéances structurées (micro-données RDF)
    for label, iso in re.findall(
            r'property="v:summary"\s+content="([^"]+)".*?property="v:startDate"\s+content="(\d{4}-\d{2}-\d{2})',
            page, re.S):
        key = WIKICFP_LABELS.get(label.strip().lower())
        if key:
            info[key] = iso
    when = re.search(r"<th>When</th>\s*<td[^>]*>(.*?)</td>", page, re.S)
    if when:
        parts = [p.strip() for p in _clean(when.group(1)).split(" - ")]
        for key, p in zip(("start", "end"), parts):
            try:
                info[key] = datetime.strptime(p, "%b %d, %Y").date().isoformat()
            except ValueError:
                pass
    where = re.search(r"<th>Where</th>\s*<td[^>]*>(.*?)</td>", page, re.S)
    if where:
        w = _clean(where.group(1))
        if w and w.upper() != "N/A":
            info["location"] = w
    link = re.search(r"Link:\s*<a[^>]*href=\"([^\"]+)\"", page)
    if link:
        info["website"] = html.unescape(link.group(1))
    body = re.search(r'<div class="cfp"[^>]*>(.*?)</div>', page, re.S)
    if body:
        text = _clean(body.group(1))
        info["cfp_text"] = text[:6000]
        # Repli : échéances écrites dans le texte de l'appel
        for k, v in deadlines_from_text(text).items():
            if k not in info:
                info[k] = v
                info.setdefault("deadline_sources", {})[k] = "texte de l'appel"
        # Cohérence : des résumés attendus APRÈS les articles signalent une date mal attribuée
        if info.get("deadline_sources", {}).get("abstract_deadline") and info.get("paper_deadline") \
                and info["abstract_deadline"] > info["paper_deadline"]:
            info.pop("abstract_deadline")
            info["deadline_sources"].pop("abstract_deadline")
    tags = re.findall(r'href="(?:\.\./|/cfp/)call\?conference=([^"&]+)"', page)
    if tags:
        info["categories"] = sorted({html.unescape(t).replace("%20", " ") for t in tags})[:8]
    return info


def fetch_event_details(http, eventid: str) -> dict:
    url = f"http://www.wikicfp.com/cfp/servlet/event.showcfp?eventid={eventid}"
    # WikiCFP est en UTF-8 mais ne le déclare pas : requests décoderait en latin-1 (« MÃ¼nchen »)
    page = http.get(url, retries=1).content.decode("utf-8", errors="replace")
    return parse_event_page(page)


SEARCH_ROW = re.compile(
    r'<a href="/cfp/servlet/event\.showcfp\?eventid=(\d+)[^"]*">([^<]+)</a></td>\s*'
    r'<td[^>]*colspan="3">([^<]*)</td></tr>\s*<tr[^>]*>\s*'
    r'<td[^>]*>([^<]*)</td>\s*<td[^>]*>([^<]*)</td>\s*<td[^>]*>([^<]*)</td>', re.S)


def _norm(s: str) -> str:
    s = html.unescape(s).lower().replace("&", " and ")
    s = re.sub(r"\(.*?\)", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def search_special_issues(http, journal_name: str, today: str) -> list[dict]:
    """Numéros spéciaux d'une revue encore ouverts (date limite ≥ aujourd'hui)."""
    short = re.sub(r"\s*\(.*?\)\s*", " ", journal_name).strip()
    page = http.get("http://www.wikicfp.com/cfp/servlet/tool.search",
                    params={"q": short, "year": "f"}, retries=1).content.decode("utf-8", errors="replace")
    target = _norm(short)
    out = []
    for eid, acro, full, _when, _where, deadline in SEARCH_ROW.findall(page):
        text = _norm(f"{acro} {full}")
        if target not in text:
            continue  # la recherche WikiCFP est floue : on exige le nom complet de la revue
        try:
            dl = datetime.strptime(deadline.strip(), "%b %d, %Y").date().isoformat()
        except ValueError:
            dl = None
        if dl and dl < today:
            continue
        out.append({"title": html.unescape(full.strip() or acro.strip()), "deadline": dl,
                    "url": f"http://www.wikicfp.com/cfp/servlet/event.showcfp?eventid={eid}"})
    return out


# Un appel n'est rattaché à une revue que s'il s'agit explicitement d'un numéro spécial
# (« The International Conference on Artificial Intelligence » ≠ revue « Artificial Intelligence »)
JOURNAL_CONTEXT = re.compile(r"special issue|numéro spécial|topical collection|thematic issue|special section", re.I)


def journal_key(name: str) -> str:
    """Nom de revue normalisé, sans parenthèses (« Computer Speech & Language » → « computer speech and language »)."""
    return _norm(re.sub(r"\(.*?\)", " ", name))


def mentions_journal(text: str, journal_name: str) -> bool:
    """Vrai si `text` est un appel lié à la revue (numéro spécial…). Exige ≥ 2 mots pour éviter les faux positifs."""
    key = journal_key(journal_name)
    if len(key.split()) < 2 or not JOURNAL_CONTEXT.search(text or ""):
        return False
    return f" {key} " in f" {_norm(text)} "
