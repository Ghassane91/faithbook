"""Les trois regles d extraction et le choix de la regle selon les etiquettes.

Decisions prises (voir ops/REGLES-EXTRACTION.md) :
- prix courant et prix barre sont deux champs distincts, suivis separement ;
- toute variation de prix compte, sans seuil ;
- la devise reste celle de la page, sans conversion ;
- toutes les cibles etiquetees sont concernees.

Les descriptions sont lues telles quelles par le modele : leur precision fait
la qualite de l extraction.
"""

from __future__ import annotations

from app.services.extraction import Champ, Regle

CATALOGUE = Regle(
    nom="catalogue",
    ligne="un produit propose a la vente sur la page",
    champs=(
        Champ(
            "modele",
            "Nom du modele tel qu'affiche, sans la marque si elle est repetee partout",
            obligatoire=True,
            verifiable=True,
        ),
        Champ(
            "prix",
            "Prix de vente actuel, celui que le client paie aujourd'hui. "
            "Jamais le prix barre.",
            type="nombre",
        ),
        Champ(
            "devise",
            "Devise du prix telle qu'affichee sur la page (code ou symbole : "
            "USD, CAD, EUR, MAD, $, €). Ne jamais convertir.",
        ),
        Champ(
            "prix_barre",
            "Ancien prix barre affiche a cote du prix actuel, uniquement s'il "
            "apparait. Sinon null.",
            type="nombre",
        ),
        Champ(
            "en_stock",
            "true si le produit est annonce disponible, false s'il est annonce "
            "epuise ou en rupture, null si rien n'est indique",
            type="booleen",
        ),
        Champ(
            "reference",
            "Reference ou SKU du produit, uniquement si elle est affichee",
            verifiable=True,
        ),
    ),
)

TARIFS = Regle(
    nom="tarifs",
    ligne="un forfait ou abonnement propose (transmission photo, donnees)",
    champs=(
        Champ("forfait", "Nom commercial du forfait", obligatoire=True, verifiable=True),
        Champ("prix_mensuel", "Prix par mois en facturation mensuelle", type="nombre"),
        Champ(
            "prix_annuel",
            "Prix en facturation annuelle ; preciser dans 'note' s'il s'agit "
            "d'un prix par mois ou par an",
            type="nombre",
        ),
        Champ(
            "devise",
            "Devise telle qu'affichee sur la page (USD, CAD, EUR, $, €). Ne jamais convertir.",
        ),
        Champ(
            "photos_incluses",
            "Nombre de photos incluses par mois, ou « illimite », tel qu'affiche",
            verifiable=True,
        ),
        Champ(
            "note",
            "Condition particuliere : engagement, premiere annee, prix par camera",
        ),
    ),
    max_lignes=20,
)

EDITORIAL = Regle(
    nom="editorial",
    ligne="une annonce, un article ou une offre mise en avant sur la page",
    champs=(
        Champ(
            "titre",
            "Titre de l'annonce ou de l'article, recopie tel quel",
            obligatoire=True,
            verifiable=True,
        ),
        Champ("date_publication", "Date de publication si elle apparait", type="date"),
        Champ(
            "sujet",
            "Un seul mot parmi : nouveau-produit, promotion, mise-a-jour, "
            "evenement, recrutement, autre",
        ),
        Champ(
            "produit_cite",
            "Modele de camera cite dans l'annonce, s'il y en a un",
            verifiable=True,
        ),
    ),
    max_lignes=30,
)

REGLES = {r.nom: r for r in (CATALOGUE, TARIFS, EDITORIAL)}

# Etiquette de rubrique -> regle. Les etiquettes de categorie (marque,
# revendeur, media) ne suffisent pas seules, sauf « revendeur ».
_PAR_ETIQUETTE = {
    "tarifs": TARIFS,
    "catalogue": CATALOGUE,
    "catalogue-2": CATALOGUE,
    "revendeur": CATALOGUE,
    "editorial": EDITORIAL,
    "actualites": EDITORIAL,
    "accueil": EDITORIAL,
}

# Ordre de priorite quand une cible porte plusieurs etiquettes : la plus
# precise l emporte (une page de tarifs chez un revendeur reste des tarifs).
_PRIORITE = ("tarifs", "catalogue", "catalogue-2", "editorial", "actualites", "accueil", "revendeur")


def etiquettes(brut: str | None) -> set[str]:
    """Meme normalisation que app.api.targets.etiquettes_de."""
    if not brut:
        return set()
    return {p.strip().casefold() for p in brut.split(",") if p.strip()}


def regle_pour(tags: str | None) -> Regle | None:
    """Regle a appliquer a une cible, ou None (support, cible non etiquetee)."""
    presentes = etiquettes(tags)
    for nom in _PRIORITE:
        if nom in presentes:
            return _PAR_ETIQUETTE[nom]
    return None
