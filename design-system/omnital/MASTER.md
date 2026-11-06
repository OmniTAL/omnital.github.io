# OmniTAL — Design system (MASTER)

Généré avec le skill **ui-ux-pro-max** (`search.py "research knowledge platform academic directory map dashboard" --design-system -p OmniTAL --variance 4 --motion 4 --density 7`), puis ajusté au projet. Ce fichier fait foi pour toute nouvelle page ; une page peut le surcharger dans `pages/<page>.md`.

## Direction
- **Style** : *Swiss Modernism 2.0* — grille rationnelle, hiérarchie nette, espacements réguliers, peu d'ornements. Clair et sombre.
- **Motif** : grille filtrable « contenu d'abord » (portail de ressources) ; la carte est un outil secondaire, réduite et collante au **centre-gauche**, les résultats occupent la colonne principale.
- **Densité** : moyenne-haute (7/10) ; **mouvement** : standard (4/10) ; **variance** : 4/10.

## Couleurs (tokens CSS, `assets/css/input.css`)
| Rôle | Clair | Sombre | Variable |
|---|---|---|---|
| Fond | `#F6F8FB` | `#0B1220` | `--bg-app` |
| Surface | `#FFFFFF` | `#111A2B` | `--bg-surface` |
| Texte | `#0F172A` | `#E6EDF7` | `--text-primary` |
| Texte secondaire | `#334155` | `#B6C3D6` | `--text-secondary` |
| Texte discret (≥ 4,5:1) | `#526178` | `#93A5BF` | `--text-muted` |
| Bordure | `#D5DDE8` | `#26354F` | `--border-color` |
| Primaire institutionnel | `#1E3A5F` | — | `--primary` (logo, pied de page) |
| Accent interactif (bleu méditerranéen) | `#1E4E8C` | `#7DB3F5` | `--accent` |
| Accent chaud (terracotta) | `#B4532A` | `#F0956A` | `--warm` (échéances, langues suivies) |
| Olive | `#55702A` | `#A9C77A` | `--olive` (« nouveau ») |

Types de ressources (marqueurs + puces, toujours doublés d'un libellé texte) : Corpus `#3F8A2C`, Publication `#1E6FD9`, Modèle `#C27C0E`, Outil `#B4447A`, Événement `#6D4BC4`, Revue `#8A5A1C`, Opportunité `#0F8A80`.

## Typographie
- Titres : **Crimson Pro** 500–700 (paire « Academic/Research » du skill).
- Texte : **Atkinson Hyperlegible** 400/700 — lisibilité maximale, base 16 px, interligne 1,5.
- Données (dates, compteurs, sources) : **JetBrains Mono**.

## Composants
- Barre d'outils collante : recherche unique avec portée **OmniTAL / Web**, période (segmenté), bouton **Filtres** (compteur), puces des filtres actifs (retrait en un clic, « Tout effacer »).
- Panneau de filtres : grille sur ordinateur, **tiroir bas** sur mobile (bouton flottant).
- Cartes de résultats : rayon 14 px, survol = élévation + bordure accent ; la fiche survolée fait pulser son marqueur.
- Indicateurs : 6 tuiles à comptage animé.
- Pied de page : 4 colonnes (à propos, sections, langues suivies, projet) + barre de crédits.

## Mouvement
- 150–300 ms, `cubic-bezier(.22,1,.36,1)` ; apparition échelonnée des cartes (28 ms) ; `prefers-reduced-motion` respecté partout.

## Règles (pré-livraison)
- Icônes SVG (Lucide) — pas d'emoji comme icône.
- Cibles tactiles ≥ 44 px ; focus visible ; contraste ≥ 4,5:1.
- Pas de défilement horizontal à 375 px ; points de rupture 375 / 768 / 1024 / 1440.
- La couleur ne porte jamais seule une information.
