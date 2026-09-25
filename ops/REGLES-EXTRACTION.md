# Règles d'extraction — à valider

Trois règles, dérivées de vos 102 cibles réelles. Chacune définit ce qu'est **une ligne** et quels champs la composent. Corrigez les descriptions : c'est elles que le modèle lit, leur précision fait la qualité de l'extraction.

---

## Règle 1 — Catalogue produits

**S'applique à :** les 36 pages `catalogue` et les 22 cibles `revendeur`.
**Une ligne =** un produit proposé à la vente sur la page.

| Champ | Type | Obligatoire | Vérifié | Description donnée au modèle |
|---|---|---|---|---|
| `modele` | texte | oui | oui | Nom du modèle tel qu'affiché, sans la marque si elle est répétée partout |
| `prix` | nombre | non | non | Prix de vente affiché. Si un prix est barré à côté, prendre le prix courant, pas le barré |
| `devise` | texte | non | non | Code de la devise : USD, CAD, EUR, MAD |
| `prix_barre` | nombre | non | non | Prix barré avant remise, uniquement s'il apparaît |
| `en_stock` | booléen | non | non | Le produit est-il annoncé disponible |
| `reference` | texte | non | oui | Référence ou SKU, uniquement si affichée |

**Vérifié** signifie : la valeur doit apparaître littéralement dans le texte de la page, sinon elle est écartée et l'anomalie est consignée. C'est le garde-fou contre l'invention. À activer sur tout ce qui est recopié, à laisser inactif sur ce qui est déduit ou normalisé.

---

## Règle 2 — Forfaits de transmission

**S'applique à :** les 4 pages `tarifs`. Ce ne sont pas des prix de caméras mais des abonnements cellulaires — `photo-transmission-plans`, `data-plans`.
**Une ligne =** un forfait proposé.

| Champ | Type | Obligatoire | Vérifié | Description |
|---|---|---|---|---|
| `forfait` | texte | oui | oui | Nom commercial du forfait |
| `prix_mensuel` | nombre | non | non | Prix par mois en facturation mensuelle |
| `prix_annuel` | nombre | non | non | Prix par mois ou par an en facturation annuelle, préciser lequel dans `note` |
| `devise` | texte | non | non | USD, CAD, EUR |
| `photos_incluses` | texte | non | oui | Nombre de photos incluses par mois, ou « illimité » |
| `note` | texte | non | non | Condition particulière : engagement, première année, par caméra |

---

## Règle 3 — Synthèse éditoriale

**S'applique à :** les 16 cibles `editorial`, 11 `actualites`, 28 `accueil`.
**Une ligne =** une annonce ou un article publié depuis la veille.

| Champ | Type | Obligatoire | Vérifié | Description |
|---|---|---|---|---|
| `titre` | texte | oui | oui | Titre de l'annonce ou de l'article |
| `date_publication` | date | non | non | Date de publication si elle apparaît |
| `sujet` | texte | non | non | En cinq mots maximum : nouveau produit, promotion, mise à jour, recrutement, autre |
| `produit_cite` | texte | non | oui | Modèle de caméra cité, s'il y en a un |

---

## Décisions prises (septembre 2026)

| Point | Décision |
|---|---|
| Prix courant et prix barré | Deux champs distincts (`prix`, `prix_barre`), alertes séparées |
| Seuil d'alerte | Toute variation de prix, sans seuil |
| Devise | Celle de la page, jamais convertie |
| Cibles concernées | Toutes les cibles étiquetées |
| Fournisseur | Gemini, offre gratuite, modèle `gemini-2.5-flash` (API native) |

## Choix de la règle selon les étiquettes

| Étiquette | Règle |
|---|---|
| `tarifs` | Règle 2 (prioritaire) |
| `catalogue`, `catalogue-2`, `revendeur` | Règle 1 |
| `editorial`, `actualites`, `accueil` | Règle 3 |
| `support`, sans étiquette | Aucune extraction |

Code : `app/services/regles_extraction.py`. La règle 3 porte désormais sur les annonces mises en avant sur la page ; la nouveauté est détectée par comparaison avec la capture précédente, pas par le modèle.
