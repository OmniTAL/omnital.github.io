"""Référentiel des langues suivies par OmniTAL.

Quatre groupes : langues berbères, langues régionales/minoritaires de Méditerranée,
arabe dialectal (groupes « focus » : collecte ciblée, conservation illimitée) et langues
nationales du bassin méditerranéen (groupe « nationales » : étiquetage et filtres seulement,
pas de collecte ciblée — elles noieraient la veille sous des milliers de ressources). Chaque langue a ses codes ISO 639 (pour les étiquettes Hugging Face,
ELG…), des mots-clés (texte libre, plusieurs langues) et un point de référence sur la
carte (région où la langue est parlée).

Exporté en data/langues.json pour le site (géolocalisation des résultats de recherche
côté navigateur) : `python scripts/languages.py`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

GROUPS = {
    "berbere":     {"fr": "Langues berbères", "en": "Berber languages"},
    "mediterranee": {"fr": "Langues méditerranéennes peu dotées", "en": "Low-resource Mediterranean languages"},
    "arabe":       {"fr": "Arabe dialectal", "en": "Dialectal Arabic"},
    "nationales":  {"fr": "Langues nationales de Méditerranée", "en": "Mediterranean national languages"},
}
# Groupes qui déclenchent la collecte ciblée et le « focus » (conservation sans limite)
FOCUS_GROUPS = ("berbere", "mediterranee", "arabe")

# code principal, [autres codes], fr, en, groupe, [mots-clés], région, lat, lng
_L = [
    # ── Berbère ──
    ("kab", [], "Kabyle", "Kabyle", "berbere", ["kabyle", "kabyl", "taqbaylit"], "Kabylie", 36.7118, 4.0459),
    ("shy", [], "Chaoui", "Shawiya", "berbere", ["chaoui", "chawi", "shawiya", "tachawit"], "Aurès", 35.5559, 6.1743),
    ("mzb", [], "Mozabite", "Mozabite", "berbere", ["mozabite", "tumzabt"], "Mzab", 32.4909, 3.6735),
    ("shi", [], "Tachelhit", "Tachelhit", "berbere", ["tachelhit", "tashelhit", "tashlhiyt", "tashelhiyt", "souss"], "Souss", 30.4278, -9.5981),
    ("rif", [], "Tarifit", "Tarifit", "berbere", ["tarifit", "riffian", "rifain"], "Rif", 35.2517, -3.9372),
    ("tzm", [], "Tamazight du Maroc central", "Central Atlas Tamazight", "berbere", ["central atlas tamazight", "tamazight (maroc)"], "Moyen Atlas", 32.9394, -5.6675),
    ("taq", ["thv", "tmh", "ttq", "thz"], "Touareg (tamasheq)", "Tuareg (Tamasheq)", "berbere", ["tuareg", "touareg", "tamasheq", "tamahaq", "tamajaq"], "Sahara", 22.785, 5.5228),
    ("siz", [], "Siwi", "Siwi", "berbere", ["siwi", "siwa berber", "jlan n isiwan"], "Siwa", 29.2032, 25.5195),
    ("gha", [], "Ghadamsi", "Ghadamès", "berbere", ["ghadamsi", "ghadames berber", "ghadamès"], "Ghadamès", 30.1337, 9.5007),
    ("jbn", [], "Nafusi", "Nafusi", "berbere", ["nafusi", "nefusa", "nafusa", "jebel nefusa"], "Djebel Nefoussa", 32.0636, 12.5286),
    ("zgh", ["ber", "tzg"], "Amazighe (tamazight)", "Amazigh (Tamazight)", "berbere", ["amazigh", "amazighe", "tamazight", "tamaziɣt", "tifinagh", "berber", "berbère"], "Tamazgha", 34.0209, -6.8416),
    # ── Méditerranée ──
    ("ca", ["cat"], "Catalan", "Catalan", "mediterranee", ["catalan", "català", "valencian", "valencià"], "Catalogne", 41.3874, 2.1686),
    ("eu", ["eus", "baq"], "Basque", "Basque", "mediterranee", ["basque", "euskara", "euskera"], "Pays basque", 43.263, -2.935),
    ("gl", ["glg"], "Galicien", "Galician", "mediterranee", ["galician", "galicien", "galego"], "Galice", 42.8782, -8.5448),
    ("ast", [], "Asturien", "Asturian", "mediterranee", ["asturian", "asturien", "asturianu"], "Asturies", 43.3614, -5.8593),
    ("an", ["arg"], "Aragonais", "Aragonese", "mediterranee", ["aragonese", "aragonais", "aragonés"], "Aragon", 42.1362, -0.4087),
    ("oc", ["oci"], "Occitan", "Occitan", "mediterranee", ["occitan", "provençal", "provencal", "gascon", "aranese", "aranais", "aranés"], "Occitanie", 43.6047, 1.4442),
    ("frp", [], "Francoprovençal", "Franco-Provençal", "mediterranee", ["arpitan", "francoprovençal", "franco-provençal", "francoprovencal"], "Val d'Aoste", 45.737, 7.3201),
    ("co", ["cos"], "Corse", "Corsican", "mediterranee", ["corsican", "corse ", "corsu", "langue corse"], "Corse", 42.3063, 9.15),
    ("sc", ["srd", "sro", "src"], "Sarde", "Sardinian", "mediterranee", ["sardinian", "sarde", "sardu", "logudorese", "campidanese"], "Sardaigne", 39.2238, 9.1217),
    ("scn", [], "Sicilien", "Sicilian", "mediterranee", ["sicilian", "sicilien", "sicilianu"], "Sicile", 38.1157, 13.3615),
    ("nap", [], "Napolitain", "Neapolitan", "mediterranee", ["neapolitan", "napolitain", "napulitano"], "Campanie", 40.8518, 14.2681),
    ("lij", [], "Ligure", "Ligurian", "mediterranee", ["ligurian", "ligure", "genoese", "monégasque", "monegasque", "munegascu"], "Ligurie", 44.4056, 8.9463),
    ("vec", [], "Vénitien", "Venetian", "mediterranee", ["venetian", "vénitien", "vèneto"], "Vénétie", 45.4408, 12.3155),
    ("fur", [], "Frioulan", "Friulian", "mediterranee", ["friulian", "frioulan", "furlan"], "Frioul", 46.0711, 13.2346),
    ("lld", [], "Ladin", "Ladin", "mediterranee", ["ladin dolomit", "ladin language"], "Dolomites", 46.5405, 11.8483),
    ("mt", ["mlt"], "Maltais", "Maltese", "mediterranee", ["maltese", "maltais", "malti"], "Malte", 35.8989, 14.5146),
    ("lad", [], "Judéo-espagnol", "Ladino", "mediterranee", ["ladino", "judeo-spanish", "judéo-espagnol", "judezmo"], "Istanbul / Thessalonique", 41.0082, 28.9784),
    ("aae", [], "Arbëresh", "Arbëresh", "mediterranee", ["arbëresh", "arberesh", "arbereshe"], "Calabre", 39.2983, 16.2538),
    ("cpg", [], "Dialectes grecs (chypriote, griko…)", "Greek dialects (Cypriot, Griko…)", "mediterranee", ["cypriot greek", "grec chypriote", "griko", "pontic greek", ], "Chypre", 35.1856, 33.3823),
    ("rup", [], "Aroumain", "Aromanian", "mediterranee", ["aromanian", "aroumain", "armãneashti", "vlach"], "Pinde", 39.7717, 21.1836),
    ("ruo", [], "Istro-roumain", "Istro-Romanian", "mediterranee", ["istro-romanian", "istro-roumain", "vlashki"], "Istrie", 45.25, 14.05),
    ("tsd", [], "Tsakonien", "Tsakonian", "mediterranee", ["tsakonian", "tsakonien"], "Tsakonie", 37.1667, 22.8667),
    ("pms", [], "Piémontais", "Piedmontese", "mediterranee", ["piedmontese", "piémontais", "piemontèis"], "Piémont", 45.0703, 7.6869),
    ("lmo", [], "Lombard", "Lombard", "mediterranee", ["lombard language", "lombard dialect", "lumbaart", "lombardo"], "Lombardie", 45.4642, 9.19),
    ("eml", ["egl", "rgn"], "Émilien-romagnol", "Emilian-Romagnol", "mediterranee", ["emilian", "romagnol", "émilien"], "Émilie-Romagne", 44.4949, 11.3426),
    ("mwl", [], "Mirandais", "Mirandese", "mediterranee", ["mirandese", "mirandais", "mirandés"], "Miranda do Douro", 41.4936, -6.2737),
    ("svm", [], "Croate molisan", "Molise Croatian", "mediterranee", ["molise croatian", "croate molisan", "na-našu"], "Molise", 41.8634, 14.7178),
    ("kmr", ["ku", "kur"], "Kurde (kurmandji)", "Kurdish (Kurmanji)", "mediterranee", ["kurmanji", "kurmandji", "kurdish", "kurde"], "Kurdistan", 37.9144, 40.2306),
    ("tru", ["syc", "aii", "cld"], "Araméen (turoyo, soureth)", "Aramaic (Turoyo, Sureth)", "mediterranee", ["turoyo", "aramaic", "araméen", "sureth", "neo-aramaic", "syriac"], "Tur Abdin", 37.4183, 41.3394),
    ("rmt", [], "Domari", "Domari", "mediterranee", ["domari"], "Levant (Domari)", 31.7767, 35.2345),
    # ── Arabe dialectal ──
    ("ary", [], "Darija marocaine", "Moroccan Arabic", "arabe", ["moroccan arabic", "darija marocaine", "moroccan darija", "darija"], "Maroc", 33.5731, -7.5898),
    ("arq", [], "Darja algérienne", "Algerian Arabic", "arabe", ["algerian arabic", "algerian dialect", "darja algérienne", "arabe algérien"], "Algérie", 36.7538, 3.0588),
    ("aeb", [], "Arabe tunisien", "Tunisian Arabic", "arabe", ["tunisian arabic", "tunisian dialect", "arabe tunisien", "derja", "tounsi"], "Tunisie", 36.8065, 10.1815),
    ("ayl", [], "Arabe libyen", "Libyan Arabic", "arabe", ["libyan arabic", "arabe libyen"], "Libye", 32.8872, 13.1913),
    ("arz", [], "Arabe égyptien", "Egyptian Arabic", "arabe", ["egyptian arabic", "arabe égyptien", "masri"], "Égypte", 30.0444, 31.2357),
    ("apc", ["ajp", "acm", "apd"], "Arabe levantin", "Levantine Arabic", "arabe", ["levantine arabic", "arabe levantin", "lebanese arabic", "syrian arabic", "palestinian arabic", "jordanian arabic"], "Levant", 33.8938, 35.5018),
    ("afb", ["acm", "ayp", "acq"], "Arabe du Golfe / irakien", "Gulf / Iraqi Arabic", "arabe", ["gulf arabic", "iraqi arabic", "yemeni arabic", "emirati arabic"], "Golfe", 25.2048, 55.2708),
    ("acy", [], "Arabe chypriote maronite", "Cypriot Maronite Arabic", "arabe", ["cypriot arabic", "cypriot maronite arabic", "sanna"], "Kormakitis", 35.3412, 33.0067),
    ("ar-dial", [], "Arabe dialectal (général)", "Dialectal Arabic", "arabe", ["dialectal arabic", "arabic dialect", "arabe dialectal", "arabizi", "nadi shared task", "maghrebi arabic", "north african arabic"], "Maghreb–Machrek", 33.0, 15.0),
    # ── Langues nationales du bassin méditerranéen (étiquetage seulement) ──
    ("el", ["ell", "gre", "grc"], "Grec", "Greek", "nationales", ["modern greek", "greek language", "greek nlp", "grec", "grec moderne", "ελληνικά"], "Grèce", 37.9838, 23.7275),
    ("tr", ["tur"], "Turc", "Turkish", "nationales", ["turkish", "turc", "türkçe", "langue turque"], "Turquie", 41.0082, 28.9784),
    ("he", ["heb", "iw"], "Hébreu", "Hebrew", "nationales", ["hebrew", "hébreu", "עברית"], "Israël", 32.0853, 34.7818),
    ("sq", ["sqi", "alb", "als", "aln"], "Albanais", "Albanian", "nationales", ["albanian", "albanais", "shqip"], "Albanie", 41.3275, 19.8187),
    ("hr", ["hrv"], "Croate", "Croatian", "nationales", ["croatian", "croate", "hrvatski"], "Croatie", 45.815, 15.9819),
    ("sl", ["slv"], "Slovène", "Slovenian", "nationales", ["slovenian", "slovene", "slovène", "slovenščina"], "Slovénie", 46.0569, 14.5058),
    ("sr", ["srp"], "Serbe", "Serbian", "nationales", ["serbian", "serbe", "srpski"], "Serbie", 44.7866, 20.4489),
    ("bs", ["bos"], "Bosniaque", "Bosnian", "nationales", ["bosnian", "bosniaque", "bosanski"], "Bosnie-Herzégovine", 43.8563, 18.4131),
    ("cnr", [], "Monténégrin", "Montenegrin", "nationales", ["montenegrin", "monténégrin", "crnogorski"], "Monténégro", 42.4304, 19.2594),
    ("mk", ["mkd", "mac"], "Macédonien", "Macedonian", "nationales", ["macedonian language", "macédonien", "македонски"], "Macédoine du Nord", 41.9981, 21.4254),
    ("it", ["ita"], "Italien", "Italian", "nationales", ["italian", "italien", "italiano"], "Italie", 41.9028, 12.4964),
    ("es", ["spa"], "Espagnol", "Spanish", "nationales", ["spanish", "espagnol", "español", "castilian"], "Espagne", 40.4168, -3.7038),
    ("ar", ["ara", "arb"], "Arabe standard", "Modern Standard Arabic", "nationales", ["modern standard arabic", "arabe standard", "arabic nlp", "arabic language"], "Monde arabe", 30.0444, 31.2357),
]

LANGS: list[dict] = []
for code, alt, fr, en, group, kws, region, lat, lng in _L:
    LANGS.append({"code": code, "codes": [code, *alt], "fr": fr, "en": en, "group": group,
                  "keywords": kws, "region": region, "lat": lat, "lng": lng, "focus": group in FOCUS_GROUPS})

BY_CODE = {c: l for l in LANGS for c in l["codes"]}
# Mots-clés en texte libre : bornes de mots ; ordre = spécifique avant générique (« darija » après « darija marocaine »)
_KW = [(re.compile(r"(?<![\w-])" + re.escape(k.strip()) + r"(?![\w-])", re.I), l)
       for l in sorted(LANGS, key=lambda x: (x["group"] == "nationales", x["code"] in ("zgh", "ar-dial"))) for k in l["keywords"]]


def all_codes(groups: tuple[str, ...] | list[str] | None = FOCUS_GROUPS) -> list[str]:
    """Codes à interroger (par défaut : groupes « focus » seulement)."""
    return [c for l in LANGS if not groups or l["group"] in groups for c in l["codes"] if "-" not in c]


def detect_languages(text: str = "", codes: list[str] | None = None) -> list[dict]:
    """Langues suivies détectées : d'abord par codes structurés (étiquettes), puis par mots-clés."""
    found: dict[str, dict] = {}
    for c in codes or []:
        c = c.lower().split("-")[0].split("_")[0]
        if c in BY_CODE:
            found.setdefault(BY_CODE[c]["code"], BY_CODE[c])
    for rx, l in _KW:
        if rx.search(text or ""):
            found.setdefault(l["code"], l)
    # langues peu dotées d'abord : elles donnent la région de la fiche ; les nationales ne servent que d'étiquette
    return sorted(found.values(), key=lambda l: not l["focus"])


def is_focus(langs: list[dict]) -> bool:
    return any(l["focus"] for l in langs)


def search_terms(group: str | None = None) -> list[str]:
    """Termes de recherche (noms anglais) pour les API plein texte — groupes « focus » seulement."""
    return [l["en"] for l in LANGS if (l["group"] == group if group else l["focus"])
            and "(" not in l["en"] and "/" not in l["en"]]


def export(path: Path) -> None:
    path.write_text(json.dumps({"groups": GROUPS, "languages": LANGS}, ensure_ascii=False, indent=0), encoding="utf-8")


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "data" / "langues.json"
    export(out)
    print(f"{len(LANGS)} langues → {out}")
