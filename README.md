# ConnecTAL

Tracker quotidien du **traitement automatique des langues (TAL)** : ressources ouvertes, revues, événements et opportunités (emplois, stages, thèses, formations), dans le monde entier. Il suit de près les **langues peu dotées** : les langues berbères, les langues méditerranéennes (catalan, basque, corse, sicilien, maltais, sarde, occitan…) et l'arabe dialectal.
Site statique hébergé sur GitHub Pages et mis à jour chaque matin par un agent de veille (GitHub Actions).

🌐 **https://omnital.github.io**

## Ce que fait le site

| Onglet | Contenu | Origine |
|---|---|---|
| **Veille** | Carte et liste des nouveautés : articles, corpus, modèles, outils, revues, appels à communications. Bandeaux « Échéances imminentes (14 j) », « Cette semaine », « Nouveautés du jour ». Recherche web en direct. | agent quotidien |
| **Catalogue** | Ressources de référence (classeurs Excel) et tout ce que l'agent a trouvé, chaque fiche avec sa notice. Les revues indiquent leurs dates limites. | `sources/*.xlsx` et agent |
| **Opportunités** | Emplois, stages, offres de thèse, postdocs, thèses françaises en cours ou soutenues, masters, licences, écoles d'été, sur une carte mondiale | agent quotidien et `config/formations.json` |

Le site est disponible en français, en anglais et en taqbaylit, en thème clair ou sombre, et s'adapte au mobile. Il publie aussi un **flux RSS** des nouveautés (`data/feed.xml`).

## Arborescence

```
index.html                 page unique (structure)
404.html                   page d'erreur
assets/css/input.css       source Tailwind + styles du site      → npm run build:css
assets/css/app.css         CSS compilé (généré, versionné)
assets/js/app.js           application (carte, filtres, i18n)
assets/img/favicon.svg
data/i18n.json             traductions FR / EN / KAB (à éditer à la main)
data/ressources.json       catalogue (généré depuis sources/*.xlsx)
data/radar.json            ce que lit le site (généré par l'agent)
data/feed.xml              flux RSS (généré)
data/veille_history.json   historique interne de l'agent (non publié)
data/geocache.json         cache de géocodage (non publié)
data/catalogue_auto.json   fiches ajoutées par l'agent + suivi des revues (interne)
data/catalogue.json        catalogue complet publié (chargé à l'ouverture de l'onglet Catalogue)
data/requetes.json         requêtes suivies (issues GitHub « veille:requete »)
data/langues.json          langues peu dotées suivies (généré par scripts/languages.py)
data/pays.json             centroïdes des pays (Wikidata, scripts/tools/build_pays.py)
config/formations.json     liste éditoriale des formations (masters, licences, écoles d'été)
sources/*.xlsx             classeurs maîtres du catalogue
config/veille.json         sources, mots-clés, rétention : réglages de l'agent
scripts/build_ressources.py
scripts/agent_veille_nlp.py
scripts/geo.py             référentiel géographique partagé
scripts/cfp.py             échéances des appels (WikiCFP, texte libre), numéros spéciaux
scripts/notices.py         rédaction des notices (gabarits FR/EN + option API Gemini)
scripts/catalogue.py       alimentation du catalogue par la veille
scripts/languages.py       langues suivies : codes ISO, mots-clés, région de référence
scripts/locate.py          géolocalisation de toute fiche (lieu, organisme, langue, pays)
scripts/collectors_extra.py Zenodo, ELG, DOAJ, emplois, thèses, formations
scripts/requetes.py        requêtes suivies (recherches confiées à l'agent)
.github/ISSUE_TEMPLATE/requete.yml  formulaire « Requête de veille »
.github/workflows/veille-deploy.yml
```

## L'agent de veille

Chaque jour à 05:17 UTC, il interroge les sources suivantes :

| Source | Ce qui est suivi | Rubrique |
|---|---|---|
| arXiv | flux quotidien `cs.CL` + requêtes ciblées (langues berbères, méditerranéennes, arabe dialectal, langues peu dotées) | Veille |
| HAL | dépôts récents du domaine *Informatique et langage* | Veille |
| Hugging Face | datasets, modèles et Spaces dans les 35 langues suivies (codes ISO) + **tendances** TAL du moment | Veille, Catalogue |
| GitHub | dépôts récents par langue suivie + dépôts TAL / LLM / parole populaires | Veille, Catalogue |
| Zenodo | jeux de données et logiciels (TAL, langues suivies) | Veille, Catalogue |
| European Language Grid | corpus, outils et modèles déclarés pour chaque langue suivie | Veille, Catalogue |
| DOAJ | revues en libre accès de linguistique informatique / TAL | Veille, Catalogue |
| WikiCFP | appels à communications (TAL, linguistique, parole, traduction, écoles d'été) | Veille, Catalogue |
| NLP People | offres d'emploi, de stage et de thèse en TAL (monde entier) | Opportunités |
| Greenhouse, Ashby, Lever | offres TAL publiées par des organisations du domaine (liste dans `config/veille.json`) | Opportunités |
| Remotive, Arbeitnow | offres en télétravail et en Europe, filtrées par mots-clés TAL | Opportunités |
| theses.fr | thèses françaises en TAL, en préparation ou soutenues | Opportunités |
| `config/formations.json` | masters, licences et écoles d'été en TAL ; liens vérifiés chaque semaine | Opportunités |
| Requêtes suivies | recherches confiées à l'agent depuis le site (voir plus bas) | Veille, Catalogue |

**Langues peu dotées suivies** (`scripts/languages.py`) :
- **berbère** : kabyle, chaoui, mozabite, tachelhit, tarifit, tamazight, touareg ;
- **langues méditerranéennes** : catalan, basque, galicien, asturien, aragonais, occitan, francoprovençal, corse, sarde, sicilien, napolitain, ligure, vénitien, frioulan, ladin, maltais, judéo-espagnol, arbëresh, dialectes grecs ;
- **arabe dialectal** : darija marocaine, darja algérienne, arabe tunisien, libyen, égyptien, levantin et du Golfe.

Ajouter une langue se fait sur une seule ligne : codes ISO, mots-clés et point de référence sur la carte.

### Localisation sur la carte

L'agent cherche une position pour chaque fiche (`scripts/locate.py`) et prend la première réponse obtenue, de la plus précise à la plus approximative. Le site affiche cette précision sur chaque fiche :

| Précision | Méthode |
|---|---|
| lieu exact | ville ou adresse d'un événement, d'une offre ou d'un établissement (Nominatim) |
| siège de l'organisme | localisation déclarée par le propriétaire GitHub ; organisation Hugging Face → Wikidata ; organisme dont le lien est le site officiel (Wikidata) ; siège de l'éditeur pour une revue |
| région de la langue | ressource dans une langue suivie (ex. corpus corse → Corse) |
| pays | pays déclaré (HAL, ELG, DOAJ, theses.fr) ou domaine national (.fr, .cat, .eus…) |

Les comptes personnels ne sont jamais localisés, par respect de la vie privée. Les recherches sont mises en cache (`data/geocache.json`) et limitées par des quotas quotidiens : la carte se complète donc au fil des jours.

### Rechercher depuis le site et suivre une requête

Le champ **« Chercher sur le web »** interroge directement depuis le navigateur Hugging Face, GitHub, Zenodo, HAL et theses.fr. Les résultats s'affichent aussitôt sur la carte et dans la liste. Ils sont aussi enregistrés dans le navigateur du visiteur : on les retrouve dans le catalogue, collection « Mes recherches ».

Le bouton **« Suivre cette recherche »** ouvre une issue GitHub pré-remplie (formulaire `requete.yml`, étiquette `veille:requete`). Ce qui se passe ensuite :
- le workflow démarre aussitôt ;
- l'agent exécute la recherche, enregistre les résultats pour tous les visiteurs, sur la carte et dans le catalogue, et répond dans l'issue ;
- il relance ensuite la recherche **chaque jour** ;
- fermer l'issue arrête le suivi.

Le site n'a pas de serveur : cette solution passe par GitHub. Il faut un compte GitHub (gratuit) pour suivre une recherche.

Chaque élément porte un **identifiant stable** (id arXiv, id HAL, dépôt HF…). L'historique (`veille_history.json`) mémorise la date de première détection (`first_seen`), ce qui permet d'afficher les nouveautés du jour sans doublons.

Si une source tombe en panne, les autres continuent : le statut de chaque source est affiché dans le panneau « État de l'agent » du site et dans le résumé du job GitHub Actions.

### Alimentation du catalogue

L'agent ne se contente pas de signaler : il **ajoute au catalogue** (collection « Ajouts de la veille ») chaque ressource détectée, avec une **notice** rédigée.

| Ressource détectée | Fiche du catalogue |
|---|---|
| Dataset, modèle, Space Hugging Face | notice (auteur, langue, tâche, taille, modèle de base, licence) |
| Dépôt GitHub | notice (langage, thèmes, description, licence) |
| **Appel à communications** (WikiCFP) | notice, **lieu**, dates, **date limite des résumés**, **date limite des articles**, notification, site officiel |
| **Numéro spécial de revue** | notice et date limite de soumission |
| **Revue du catalogue** (20 revues) | notice, soumission en continu et **numéros spéciaux ouverts avec leur date limite** |

**D'où viennent les échéances**
1. Les champs structurés de la page WikiCFP de l'appel. Elle est relue chaque semaine tant que l'appel est ouvert, car les dates sont souvent prolongées.
2. À défaut, le **texte de l'appel** (« Abstract submission: March 1, 2027 »). Le site signale ces dates d'un astérisque et invite à les vérifier sur le site officiel. Une date de résumés postérieure à celle des articles est jugée incohérente et écartée.
3. Si l'IA est activée, elle complète les échéances manquantes, mais **une date n'est retenue que si elle figure réellement dans le texte source** (garde-fou anti-hallucination).

**Qui rédige les notices**
- Par défaut, des **gabarits** déterministes en français et en anglais (`scripts/notices.py`), sans dépendance ni coût.
- **Option IA (Gemini)** : ajouter le secret `GEMINI_API_KEY` (clé Google AI Studio) dans *Settings → Secrets and variables → Actions*. L'agent fait alors rédiger les notices par l'API Gemini, 120 par exécution au maximum, à 10 requêtes par minute.
  - Les réglages sont dans `config/veille.json` → `llm`. Le modèle par défaut est `gemini-3.5-flash-lite`, avec des modèles de repli si Google le retire.
  - Chaque fiche n'est rédigée qu'une fois, et le site la marque « ✨ notice IA ».
  - Si la clé manque ou si le quota est atteint, l'agent revient aux gabarits.
  - L'offre gratuite de Gemini suffit pour ce volume.

Dans l'onglet Catalogue, deux réglages aident à exploiter ces fiches : le tri **« Prochaine échéance »** et le filtre **« Échéance à venir uniquement »**. Les comptes à rebours sont colorés : rouge à moins de 15 jours, orange à moins de 45 jours.

Les fiches sont stockées dans `data/catalogue_auto.json`, qui est persistant. Une conférence en double sur WikiCFP n'est gardée qu'une fois. Les événements terminés depuis plus de 30 jours sont retirés du catalogue.

**Rétention**
- Les articles arXiv généraux restent 21 jours, ceux de HAL 60 jours.
- Les éléments liés aux langues suivies sont conservés sans limite.
- Une offre d'emploi disparaît quand sa source ne la publie plus (`opportunites.ttl_days`).
- Une revue reste tant que le DOAJ la liste.

Tous les réglages sont dans `config/veille.json`.

### Bandeaux du site
- **Échéances imminentes (14 j)** : dates limites des résumés et des articles (événements, numéros spéciaux de revues), avec un compte à rebours.
- **Cette semaine** : événements en cours ou qui commencent dans les 7 jours.
- **Nouveautés du jour** : sur l'onglet Opportunités, les nouvelles offres.

## Mise en ligne sur `omnital.github.io` (organisation GitHub OmniTAL)

> Une adresse `xxx.github.io` correspond à un **compte ou une organisation GitHub nommé `xxx`**. Pour l'organisation `OmniTAL`, le dépôt doit s'appeler **`omnital.github.io`**, en minuscules comme toujours sur GitHub Pages. Le site sera alors servi à la racine de **https://omnital.github.io**.
> Si le dépôt porte un autre nom (par exemple `OmniTAL/connectal`), le site sera servi à `https://omnital.github.io/connectal/` et fonctionnera tel quel, car tous ses chemins sont relatifs. Il faut seulement mettre à jour `site_url` dans `config/veille.json`, ainsi que `robots.txt`, `sitemap.xml` et la balise canonique de `index.html`.

1. Dans l'organisation **OmniTAL**, créer un dépôt **public** nommé exactement `omnital.github.io`, sans README ni licence, pour que le premier push passe sans conflit.
2. Pousser le code depuis le dossier décompressé :
   ```bash
   git init && git add . && git commit -m "ConnecTAL : site + agent de veille"
   git branch -M main
   git remote add origin https://github.com/OmniTAL/omnital.github.io.git
   git push -u origin main
   ```
3. **Settings → Pages → Build and deployment → Source** : choisir **GitHub Actions**.
4. **Settings → Actions → General → Workflow permissions** : choisir **Read and write permissions** (l'agent commite les données et répond aux requêtes suivies). Dans une organisation, ce réglage peut être verrouillé au niveau de l'organisation : *Organization settings → Actions → General*.
5. **Settings → Secrets and variables → Actions → New repository secret** : nom `GEMINI_API_KEY`, valeur = la clé créée sur [Google AI Studio](https://aistudio.google.com/apikey). Ce réglage est facultatif : sans clé, les notices sont rédigées par gabarits.
6. **Issues → Labels** : créer l'étiquette `veille:requete`.
7. **Actions → Veille & déploiement → Run workflow** : lancer une première collecte complète (15 minutes environ).

Après chaque push sur `main`, le site est republié sans nouvelle collecte (2 minutes environ). La veille complète tourne une fois par jour.

## Développement local

```bash
pip install -r scripts/requirements.txt
python scripts/build_ressources.py          # catalogue
python scripts/agent_veille_nlp.py          # veille complète (≈ 15 min la première fois)
python scripts/agent_veille_nlp.py --only arxiv,wikicfp
python scripts/agent_veille_nlp.py --offline   # régénère radar.json sans réseau

npm install && npm run build:css            # après modification des classes Tailwind
npm run serve                               # http://localhost:8000
```

## Ajouter des ressources au catalogue

Éditer le classeur concerné dans `sources/`, sur sa feuille maîtresse : `Toutes_ressources`, `Tous_depots` ou `Toutes_donnees`. Les autres feuilles ne sont que des vues filtrées.
Pousser ensuite la modification : le workflow régénère `data/ressources.json`.

## Points d'attention

- **Traductions kabyles** : celles de `data/i18n.json` sont à faire relire par un locuteur natif.
- GitHub **désactive les workflows planifiés** d'un dépôt public après 60 jours sans activité. Les commits quotidiens de l'agent suffisent normalement à l'éviter. Vérifier l'onglet Actions en cas de doute.
- **Quotas de géolocalisation**, par exécution :
  - Nominatim : 1 requête par seconde au plus, 150 nouveaux lieux ;
  - Wikidata : 120 requêtes ;
  - comptes GitHub ou Hugging Face : 60.

  Tout est mis en cache, et les fiches non localisées sont retentées tous les 3 jours.
- **Formations** : la liste `config/formations.json` est éditoriale. Il n'existe pas d'API ouverte des masters. Un lien mort est signalé « ⚠ lien à vérifier » sur le site.
- **Offres d'emploi** : les grands sites d'offres (LinkedIn, Indeed, EURAXESS) n'ont pas d'API ouverte et bloquent la collecte automatique. L'agent s'appuie donc sur des sources ouvertes, que l'on peut compléter dans `config/veille.json` → `opportunites` (tableaux Greenhouse, Ashby ou Lever d'autres organisations).
- Le **flux RSS arXiv** est vide le week-end : c'est normal.
