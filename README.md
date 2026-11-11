# OmniTAL

> **Refonte v4 (Novembre 2026)** : Nouveau design *Swiss Modernism 2.0*, suivi de nouvelles ressources et langues.

**OmniTAL** est un tracker quotidien dédié au **Traitement Automatique des Langues (TAL)**. Il recense les ressources ouvertes, revues scientifiques, événements et opportunités académiques et professionnelles (emplois, stages, thèses, formations) à travers le monde.

Le projet accorde une attention particulière aux **langues peu dotées**, notamment :
* **Langues berbères** (kabyle, chaoui, mozabite, tachelhit, tarifit…)
* **Langues méditerranéennes** (catalan, basque, corse, sicilien, maltais, sarde, occitan…)
* **Arabe dialectal** (darija marocaine, darja algérienne, arabe tunisien, levantin…)

Le site statique est hébergé sur **GitHub Pages** et mis à jour quotidiennement de manière autonome via **GitHub Actions**.

**Accéder au site :** https://omnital.github.io

---

## Sommaire

- [Aperçu des fonctionnalités](#aperçu-des-fonctionnalités)
- [Fonctionnement de l'agent de veille](#fonctionnement-de-lagent-de-veille)
  - [Géolocalisation sur la carte](#géolocalisation-sur-la-carte)
  - [Recherche en direct & suivi de requêtes](#recherche-en-direct--suivi-de-requêtes)
  - [Alimentation du catalogue](#alimentation-du-catalogue)

---

## Aperçu des fonctionnalités

| Onglet | Description du contenu | Source des données |
|---|---|---|
| **Veille** | Carte interactive et fil d'actualités : articles, corpus, modèles, outils, revues et appels à communications. Inclut les bandeaux *« Échéances imminentes (14 j) »*, *« Cette semaine »* et *« Nouveautés du jour »*, ainsi qu'un moteur de recherche web. | Agent quotidien |
| **Catalogue** | Base de données de référence et découvertes de l'agent avec notices détaillées. Suivi des dates limites pour les revues scientifiques. | `sources/*.xlsx` & Agent |
| **Opportunités** | Cartographie mondiale des offres d'emploi, stages, thèses (françaises et internationales), postdocs, masters, licences et écoles d'été. | Agent quotidien & `config/formations.json` |

* **Internationalisation (i18n)** : Disponible en Français (FR), Anglais (EN) et Kabyle / Taqbaylit (KAB).
* **Interface** : Thèmes clair/sombre, design adaptatif mobile (*responsive*).
* **Syndication** : Flux RSS disponible sur `data/feed.xml`.

---

## Fonctionnement de l'agent de veille

L'agent de veille s'exécute automatiquement chaque jour (**02:41 UTC**, rattrapage à **05:23 UTC**) pour interroger et agréger les flux de données.

### Géolocalisation sur la carte

L'agent assigne une coordonnée géographique à chaque fiche (`scripts/locate.py`) selon une hiérarchie de précision strictement définie. L'indice de précision est restitué sur l'interface :

```text
[ Lieu exact ] ➔ Ville ou adresse précise de l'événement/établissement (Nominatim)
      ↓
[ Siège organisme ] ➔ Localisation GitHub, Wikidata (Hugging Face / Organisme) ou Éditeur
      ↓
[ Région langue ] ➔ Positionnement par défaut sur la région de la langue (ex: Corse)
      ↓
[ Pays ] ➔ Pays déclaré par les métadonnées de la source (HAL, DOAJ, TLD...)
