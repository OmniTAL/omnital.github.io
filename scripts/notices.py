"""Rédaction des notices du catalogue.

Deux rédacteurs :
  • `rule_notice`  — gabarits FR/EN déterministes, toujours disponibles (aucune dépendance) ;
  • `LLMWriter`    — rédaction en langage naturel par l'API Gemini (Google) si le secret
                     GEMINI_API_KEY est défini. Il peut aussi extraire les échéances
                     d'un appel à communications, mais une date n'est retenue que si elle
                     apparaît réellement dans le texte source (garde-fou anti-hallucination).

Les échéances restent des champs structurés : la notice les reprend, elle ne les invente pas.
"""
from __future__ import annotations

import json
import re
from datetime import date

from cfp import find_dates_in_text

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]

HF_TASKS_FR = {
    "automatic-speech-recognition": "reconnaissance de la parole", "text-to-speech": "synthèse vocale",
    "translation": "traduction automatique", "text-classification": "classification de textes",
    "token-classification": "étiquetage de séquences", "text-generation": "génération de texte",
    "text2text-generation": "génération texte-à-texte", "fill-mask": "modèle de langue masqué",
    "feature-extraction": "plongements (embeddings)", "sentence-similarity": "similarité de phrases",
    "audio-classification": "classification audio", "image-to-text": "OCR / image vers texte",
    "question-answering": "questions-réponses", "summarization": "résumé automatique",
    "image-text-to-text": "vision-langage", "zero-shot-classification": "classification zero-shot",
}
LANG_NAMES = {
    "kab": ("kabyle", "Kabyle"), "zgh": ("amazighe standard marocain", "Standard Moroccan Tamazight"),
    "tzm": ("tamazight du Maroc central", "Central Atlas Tamazight"), "shi": ("tachelhit", "Tachelhit"),
    "rif": ("tarifit", "Tarifit"), "taq": ("tamasheq", "Tamasheq"), "ber": ("berbère", "Berber"),
    "thv": ("tamahaq", "Tamahaq"), "fr": ("français", "French"), "en": ("anglais", "English"),
    "ar": ("arabe", "Arabic"), "ary": ("darija marocaine", "Moroccan Arabic"), "arq": ("darija algérienne", "Algerian Arabic"),
}


def fdate(iso: str | None, lang: str = "fr") -> str:
    if not iso:
        return ""
    try:
        d = date.fromisoformat(iso[:10])
    except ValueError:
        return iso
    return f"{d.day} {MOIS[d.month - 1]} {d.year}" if lang == "fr" else f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def _langs(codes: list[str], lang: str) -> str:
    names = [LANG_NAMES.get(c, (c, c))[0 if lang == "fr" else 1] for c in codes[:5]]
    return ", ".join(dict.fromkeys(names))


def _first_sentence(text: str, limit: int = 220) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    t = re.sub(r"^(dataset card for|model card for)\s+\S+\s*", "", t, flags=re.I)
    m = re.match(r"(.{30,%d}?[.!?])\s" % limit, t + " ")
    s = m.group(1) if m else t[:limit].rsplit(" ", 1)[0] + ("…" if len(t) > limit else "")
    return s


# ───────────────────────────── gabarits ─────────────────────────────

def rule_notice(kind: str, it: dict) -> dict:
    """Notice courte {fr, en} construite à partir des métadonnées."""
    meta = it.get("meta") or {}
    langs = it.get("languages") or []
    desc = _first_sentence(it.get("summary") or "")

    if kind in ("hf_dataset", "hf_model", "hf_space"):
        what_fr = {"hf_dataset": "Jeu de données", "hf_model": "Modèle", "hf_space": "Application de démonstration (Space)"}[kind]
        what_en = {"hf_dataset": "Dataset", "hf_model": "Model", "hf_space": "Demo application (Space)"}[kind]
        task = meta.get("task") or meta.get("pipeline")
        fr = [f"{what_fr} publié sur Hugging Face par {it.get('author') or 'un contributeur'} le {fdate(it.get('date'))}."]
        en = [f"{what_en} published on Hugging Face by {it.get('author') or 'a contributor'} on {fdate(it.get('date'), 'en')}."]
        if langs:
            fr.append(f"Langue(s) : {_langs(langs, 'fr')}.")
            en.append(f"Language(s): {_langs(langs, 'en')}.")
        if task:
            fr.append(f"Tâche : {HF_TASKS_FR.get(task, task.replace('-', ' '))}.")
            en.append(f"Task: {task.replace('-', ' ')}.")
        if meta.get("base_model"):
            fr.append(f"Dérivé de {meta['base_model']}.")
            en.append(f"Fine-tuned from {meta['base_model']}.")
        if meta.get("size"):
            fr.append(f"Taille : {meta['size']}.")
            en.append(f"Size: {meta['size']}.")
        if desc and not desc.lower().startswith(it.get("title", "").lower()[:20]):
            fr.append(desc); en.append(desc)
        return {"fr": " ".join(fr), "en": " ".join(en)}

    if kind in ("zenodo_dataset", "zenodo_software"):
        what_fr, what_en = ("Jeu de données", "Dataset") if kind == "zenodo_dataset" else ("Logiciel", "Software")
        fr = f"{what_fr} déposé sur Zenodo le {fdate(it.get('date'))}" + (f" par {it['author']}" if it.get("author") else "") + "."
        en = f"{what_en} deposited on Zenodo on {fdate(it.get('date'), 'en')}" + (f" by {it['author']}" if it.get("author") else "") + "."
        if langs or it.get("lang_codes"):
            names = _langs(it.get("lang_codes") or langs, "fr")
            fr += f" Langue(s) : {names}."; en += f" Language(s): {_langs(it.get('lang_codes') or langs, 'en')}."
        if meta.get("license"):
            fr += f" Licence : {meta['license']}."; en += f" License: {meta['license']}."
        if desc:
            fr += f" {desc}"; en += f" {desc}"
        return {"fr": fr, "en": en}

    if kind.startswith("elg_"):
        rt = meta.get("resource_type") or "ressource"
        fr = f"Ressource linguistique ({rt}) référencée dans le catalogue European Language Grid."
        en = f"Language resource ({rt}) listed in the European Language Grid catalogue."
        if langs:
            fr += f" Langue(s) : {', '.join(langs[:5])}."; en += f" Language(s): {', '.join(langs[:5])}."
        if meta.get("access"):
            fr += f" Conditions d'usage : {meta['access']}."; en += f" Terms of use: {meta['access']}."
        if desc:
            fr += f" {desc}"; en += f" {desc}"
        return {"fr": fr, "en": en}

    if kind == "journal_oa":
        pub = meta.get("publisher")
        fr = f"Revue scientifique en libre accès" + (f" publiée par {pub}" if pub else "") + ", indexée par le DOAJ."
        en = f"Open-access scholarly journal" + (f" published by {pub}" if pub else "") + ", indexed in DOAJ."
        if meta.get("review"):
            fr += f" Évaluation : {meta['review'].lower()}."; en += f" Review: {meta['review'].lower()}."
        fr += " Frais de publication (APC) : " + ("oui." if meta.get("apc") == "oui" else "aucun.")
        en += " Article processing charges: " + ("yes." if meta.get("apc") == "oui" else "none.")
        if it.get("summary"):
            fr += f" Mots-clés : {it['summary']}."; en += f" Keywords: {it['summary']}."
        fr += " Soumissions ouvertes en continu."; en += " Submissions open year-round."
        return {"fr": fr, "en": en}

    if kind == "github":
        lang_fr = f" écrit en {meta['language']}" if meta.get("language") else ""
        lang_en = f" written in {meta['language']}" if meta.get("language") else ""
        fr = f"Dépôt GitHub{lang_fr}, créé le {fdate(it.get('date'))} par {it.get('author')}."
        en = f"GitHub repository{lang_en}, created on {fdate(it.get('date'), 'en')} by {it.get('author')}."
        if desc:
            fr += f" {desc}"; en += f" {desc}"
        if meta.get("topics"):
            fr += f" Thèmes : {', '.join(meta['topics'][:5])}."
            en += f" Topics: {', '.join(meta['topics'][:5])}."
        return {"fr": fr, "en": en}

    if kind in ("event", "special_issue"):
        ev = it.get("event") or {}
        name = it.get("summary") or it.get("title")
        acro = it.get("acronym") or ""
        if kind == "special_issue":
            fr = [f"Appel à contributions pour un numéro spécial : « {name} »."]
            en = [f"Call for papers for a special issue: “{name}”."]
        else:
            # Présentation : 1-2 premières phrases de l'appel (son objet), sinon le nom complet
            # FR : phrase structurée (pas d'extrait anglais dans une notice française).
            # EN : ouverture de l'appel quand elle est exploitable, sinon la même structure.
            low = f"{acro} {name}".lower()
            nature = next((fr_ for k, fr_ in (("workshop", "de l'atelier"), ("symposium", "du symposium"),
                           ("summer school", "de l'école d'été"), ("conference", "de la conférence"),
                           ("congress", "du congrès"), ("meeting", "de la rencontre"), ("track", "de la session"))
                           if k in low), "de l'événement")
            topics = ev.get("categories") or []
            sujet_fr = f", consacré à : {', '.join(topics[:4])}" if topics else ""
            label = f"{name} ({acro})" if acro and acro.split()[0] not in name else name
            fr = [f"Appel à communications {nature} « {label} »{sujet_fr}."]
            intro = _cfp_intro(ev.get("cfp_text") or "")
            en = [intro or f"Call for papers: “{label}”."]
            loc = ev.get("location") or it.get("location")
            if ev.get("start"):
                when_fr = f"du {fdate(ev['start'])} au {fdate(ev.get('end'))}" if ev.get("end") and ev["end"] != ev["start"] else f"le {fdate(ev['start'])}"
                when_en = f"from {fdate(ev['start'], 'en')} to {fdate(ev.get('end'), 'en')}" if ev.get("end") and ev["end"] != ev["start"] else f"on {fdate(ev['start'], 'en')}"
                fr.append(f"L'événement se tiendra {'en ligne' if _online(loc) else 'à ' + loc} {when_fr}." if loc else f"L'événement aura lieu {when_fr}.")
                en.append(f"The event takes place {'online' if _online(loc) else 'in ' + loc} {when_en}." if loc else f"The event takes place {when_en}.")
        if ev.get("abstract_deadline"):
            fr.append(f"Résumés attendus avant le {fdate(ev['abstract_deadline'])}.")
            en.append(f"Abstracts due by {fdate(ev['abstract_deadline'], 'en')}.")
        if ev.get("paper_deadline"):
            fr.append(f"Date limite de soumission des articles : {fdate(ev['paper_deadline'])}.")
            en.append(f"Paper submission deadline: {fdate(ev['paper_deadline'], 'en')}.")
        if ev.get("notification"):
            fr.append(f"Notification aux auteurs : {fdate(ev['notification'])}.")
            en.append(f"Author notification: {fdate(ev['notification'], 'en')}.")
        if ev.get("categories") and kind == "special_issue":
            fr.append(f"Thématiques : {', '.join(ev['categories'][:5])}.")
            en.append(f"Topics: {', '.join(ev['categories'][:5])}.")
        return {"fr": " ".join(fr), "en": " ".join(en)}

    if kind == "journal":
        publisher = re.search(r"\((?:editeur\s+)?([^)]+)\)", it.get("pays") or "")
        pub = publisher.group(1) if publisher else None
        scope = (it.get("type") or "").rstrip(".")
        oa = (it.get("licence") or "").lower()
        fr = f"{it['nom']} est une revue scientifique à comité de lecture" + (f" publiée par {pub}" if pub else "") + "."
        en = f"{it['nom']} is a peer-reviewed journal" + (f" published by {pub}" if pub else "") + "."
        if scope:
            # minuscule initiale sauf sigle (« IA fondamentale », « NLP… »)
            sc = scope if scope[:2].isupper() else scope[0].lower() + scope[1:]
            fr += f" Ligne éditoriale : {sc}."
            en += f" Scope: {sc}."
        if "oui" in oa or "open" in oa:
            fr += " Articles en libre accès."; en += " Open-access articles."
        elif "partiel" in oa or "hybride" in oa:
            fr += " Modèle hybride : libre accès optionnel (frais de publication)."; en += " Hybrid model: optional open access (APC)."
        fr += " Les soumissions régulières sont ouvertes en continu ; seuls les numéros spéciaux ont une date limite."
        en += " Regular submissions are open year-round; only special issues have deadlines."
        return {"fr": fr, "en": en}

    return {"fr": desc or it.get("title", ""), "en": desc or it.get("title", "")}


def _cfp_intro(text: str, limit: int = 300) -> str:
    """Phrases d'ouverture d'un appel, sans les formules creuses (« We are pleased to announce… »)."""
    t = re.sub(r"\s+", " ", text or "").strip()
    if not t:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", t)
    keep, size = [], 0
    for sent in sentences[:6]:
        if re.search(r"call for papers|we (are|'re) (pleased|happy|delighted)|dear colleagues|apologies for|"
                     r"cross-?post|^\*+|^=+|^-{3,}", sent, re.I) and not keep:
            continue
        if size + len(sent) > limit and keep:
            break
        keep.append(sent); size += len(sent)
    out = " ".join(keep)
    if re.search(r"\*{3,}|={3,}|(\s-\s.*){3,}|https?://", out) or len(out) < 40:
        return ""  # listes à puces, bannières, URL : pas une présentation lisible
    return out if len(out) <= limit + 40 else out[:limit].rsplit(" ", 1)[0] + "…"


def _online(loc: str | None) -> bool:
    return bool(loc) and bool(re.search(r"online|virtual|en ligne", loc, re.I))


# ───────────────────────────── rédaction IA (optionnelle) ─────────────────────────────

SYSTEM_PROMPT = """Tu rédiges les notices du catalogue ConnecTAL, un portail de ressources en traitement automatique des langues (TAL).
Règles :
- 2 à 4 phrases, ton neutre et informatif, sans superlatifs ni formule promotionnelle.
- Uniquement les faits présents dans les MÉTADONNÉES et le TEXTE SOURCE fournis. N'invente rien (ni date, ni lieu, ni chiffre, ni licence).
- Mentionne la langue traitée, la tâche, l'origine et l'intérêt pour la recherche quand c'est connu.
- Pour un événement ou un appel : lieu, dates, date limite des résumés, date limite des articles — seulement si fournis.
- Réponds UNIQUEMENT par un objet JSON valide :
{"fr": "notice en français", "en": "notice in English",
 "abstract_deadline": "AAAA-MM-JJ ou null", "paper_deadline": "AAAA-MM-JJ ou null", "location": "lieu ou null"}"""


class LLMWriter:
    """Rédacteur IA — API Gemini de Google (requête HTTP directe, sans SDK).

    Clé : variable d'environnement GEMINI_API_KEY (secret GitHub). Modèle et quotas :
    config/veille.json → llm. Si le modèle principal n'existe plus (404), les modèles de
    repli sont essayés dans l'ordre ; sur un quota atteint (429), la rédaction IA s'arrête
    pour l'exécution et l'agent revient aux gabarits.
    """

    ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self, http, cfg: dict, api_key: str | None):
        self.http, self.cfg, self.key = http, cfg, api_key
        self.budget = cfg.get("max_per_run", 60) if (api_key and cfg.get("enabled", True)) else 0
        self.models = [cfg.get("model", "gemini-3.5-flash-lite"), *cfg.get("fallback_models", [])]
        self.delay = 60.0 / max(1, cfg.get("requests_per_minute", 10))
        self.used = 0
        self.errors = 0
        self._last = 0.0

    @property
    def available(self) -> bool:
        return self.budget > 0 and self.errors < 3 and bool(self.models)

    def _call(self, prompt: str) -> str:
        """Appelle Gemini et renvoie le texte de la réponse (JSON attendu)."""
        import time
        wait = self.delay - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)  # respect du quota par minute (offre gratuite comprise)
        body = {
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1024,
                                 "responseMimeType": "application/json"},
        }
        while self.models:
            self._last = time.time()
            r = self.http.s.post(self.ENDPOINT.format(model=self.models[0]), json=body, timeout=60,
                                 headers={"x-goog-api-key": self.key, "content-type": "application/json"})
            if r.status_code == 404:
                print(f"    [IA] modèle « {self.models[0]} » indisponible, essai du suivant")
                self.models.pop(0)
                continue
            if r.status_code == 429:
                print("    [IA] quota Gemini atteint : retour aux gabarits pour cette exécution")
                self.budget = 0
                raise RuntimeError("quota")
            r.raise_for_status()
            cand = (r.json().get("candidates") or [{}])[0]
            return "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []))
        raise RuntimeError("aucun modèle Gemini disponible")

    def write(self, kind: str, meta: dict, source_text: str = "") -> dict | None:
        if not self.available:
            return None
        self.budget -= 1
        user = (f"TYPE : {kind}\nMÉTADONNÉES :\n{json.dumps(meta, ensure_ascii=False, default=str)[:3000]}\n\n"
                f"TEXTE SOURCE :\n{(source_text or '(aucun)')[:5000]}")
        try:
            text = self._call(user)
            data = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
        except Exception as ex:
            if str(ex) != "quota":
                self.errors += 1
                print(f"    [IA] notice non rédigée ({kind}) : {str(ex)[:160]}")
            return None
        self.used += 1
        out = {"fr": str(data.get("fr") or "").strip(), "en": str(data.get("en") or "").strip()}
        if not out["fr"]:
            return None
        # Garde-fou : une échéance proposée par l'IA doit figurer dans le texte source
        known = {iso for _, iso in find_dates_in_text(source_text)} | {
            v for v in meta.values() if isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v)}
        for k in ("abstract_deadline", "paper_deadline"):
            v = data.get(k)
            if isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) and v in known:
                out[k] = v
        if isinstance(data.get("location"), str) and data["location"].lower() not in ("null", "none", ""):
            if data["location"].split(",")[0].strip().lower() in (source_text + json.dumps(meta, ensure_ascii=False)).lower():
                out["location"] = data["location"].strip()
        return out
