"""Comparaison de deux extractions successives d une meme cible.

Decisions appliquees :
- toute variation du prix courant est signalee, sans seuil ;
- le prix barre est suivi a part : apparition (debut de promotion),
  disparition (fin de promotion), changement ;
- la devise est celle de la page, jamais convertie ;
- un prix inconnu d un cote (null) n est pas une variation : il ne fait
  pas d alerte, pour ne pas confondre une lecture ratee avec un changement.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

# Champ qui identifie une ligne d une capture a l autre, selon la regle.
CLES = {"catalogue": "modele", "tarifs": "forfait", "editorial": "titre"}

# Au-dela de cette proportion de lignes disparues d un coup, on suppose une
# page cassee ou une lecture ratee plutot qu un vrai retrait massif.
SEUIL_DISPARITION_SUSPECTE = 0.8


@dataclass(frozen=True)
class Evenement:
    type: str
    ligne: str
    detail: str

    def texte(self) -> str:
        return f"- {self.ligne} : {self.detail}"


def _cle(valeur: Any) -> str:
    texte = unicodedata.normalize("NFKD", str(valeur or ""))
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", texte.casefold()).strip()


def _index(regle: str, lignes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    champ = CLES.get(regle)
    index: dict[str, dict[str, Any]] = {}
    if not champ:
        return index
    for ligne in lignes:
        cle = _cle(ligne.get(champ))
        if cle and cle not in index:  # doublon : la premiere occurrence fait foi
            index[cle] = ligne
    return index


def _montant(valeur: Any, devise: Any) -> str:
    if valeur is None:
        return "?"
    nombre = f"{valeur:,.2f}".replace(",", " ") if isinstance(valeur, (int, float)) else str(valeur)
    return f"{nombre} {devise}".strip() if devise else nombre


def _variation(avant: float, apres: float) -> str:
    if not avant:
        return ""
    pct = (apres - avant) / avant * 100
    return f" ({pct:+.1f} %)"


def _prix(type_: str, nom: str, libelle: str, avant: dict, apres: dict, champ: str) -> list[Evenement]:
    a, b = avant.get(champ), apres.get(champ)
    if a is None or b is None or a == b:
        return []
    devise = apres.get("devise") or avant.get("devise")
    return [Evenement(
        type_, nom,
        f"{libelle} {_montant(a, devise)} -> {_montant(b, devise)}{_variation(a, b)}",
    )]


def _comparer_catalogue(nom: str, avant: dict, apres: dict) -> list[Evenement]:
    evts = _prix("prix_change", nom, "prix", avant, apres, "prix")
    devise = apres.get("devise") or avant.get("devise")
    barre_a, barre_b = avant.get("prix_barre"), apres.get("prix_barre")
    if barre_a is None and barre_b is not None:
        evts.append(Evenement("promo_debut", nom,
                              f"promotion, prix barre {_montant(barre_b, devise)}"))
    elif barre_a is not None and barre_b is None and apres.get("prix") is not None:
        # Fin de promotion seulement si le prix courant a bien ete lu : sinon
        # c est probablement la ligne entiere qui a ete mal lue.
        evts.append(Evenement("promo_fin", nom,
                              f"fin de promotion (prix barre {_montant(barre_a, devise)} retire)"))
    else:
        evts += _prix("prix_barre_change", nom, "prix barre", avant, apres, "prix_barre")
    stock_a, stock_b = avant.get("en_stock"), apres.get("en_stock")
    if stock_a is True and stock_b is False:
        evts.append(Evenement("rupture", nom, "passe en rupture de stock"))
    elif stock_a is False and stock_b is True:
        evts.append(Evenement("retour_stock", nom, "de nouveau disponible"))
    return evts


def _comparer_tarifs(nom: str, avant: dict, apres: dict) -> list[Evenement]:
    return (
        _prix("prix_change", nom, "mensuel", avant, apres, "prix_mensuel")
        + _prix("prix_change", nom, "annuel", avant, apres, "prix_annuel")
    )


def comparer(regle: str, avant: list[dict[str, Any]], apres: list[dict[str, Any]]) -> list[Evenement]:
    """Evenements a signaler entre deux extractions de la meme regle."""
    ia, ib = _index(regle, avant), _index(regle, apres)
    champ = CLES.get(regle)
    if not champ:
        return []

    def nom(ligne: dict) -> str:
        return str(ligne.get(champ) or "").strip()

    if regle == "editorial":
        # Seules les nouvelles annonces interessent ; une annonce qui sort de
        # la page d accueil n est pas une information.
        return [Evenement("annonce", nom(ib[c]), "nouvelle annonce") for c in ib if c not in ia]

    retires = [c for c in ia if c not in ib]
    if ia and (not ib or len(retires) / len(ia) >= SEUIL_DISPARITION_SUSPECTE) and len(ia) >= 3:
        return [Evenement(
            "lecture_suspecte", "Page",
            f"{len(retires)} ligne(s) sur {len(ia)} ont disparu d un coup : page modifiee "
            "en profondeur ou lecture ratee, a verifier sur la capture",
        )]

    evts: list[Evenement] = []
    libelle = "produit" if regle == "catalogue" else "forfait"
    for c, ligne in ib.items():
        if c not in ia:
            devise = ligne.get("devise")
            prix = ligne.get("prix") if regle == "catalogue" else ligne.get("prix_mensuel")
            suffixe = f", {_montant(prix, devise)}" if prix is not None else ""
            evts.append(Evenement("ajout", nom(ligne), f"nouveau {libelle}{suffixe}"))
    for c in retires:
        evts.append(Evenement("retrait", nom(ia[c]), f"{libelle} retire de la page"))
    for c in ib:
        if c in ia:
            comparateur = _comparer_catalogue if regle == "catalogue" else _comparer_tarifs
            evts += comparateur(nom(ib[c]), ia[c], ib[c])
    return evts
