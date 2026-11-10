"""Transforme une capture pleine page en PDF d'une page par ecran.

Une capture pleine page peut faire 1920 x 40000 pixels. Aucun visualiseur
d'images n'affiche cela correctement : le contenu est complet mais illisible.
Le meme contenu decoupe en pages de la hauteur d'un ecran redevient lisible,
et le PDF garde l'integralite de la page dans un seul fichier, y compris sur
telephone.

L'image d'origine n'est jamais modifiee : le PDF est un fichier distinct.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

# Bande commune a deux pages consecutives : evite qu'une ligne de texte soit
# coupee en deux sans qu'on puisse la lire nulle part.
RECOUVREMENT = 80


def _limites(hauteur: int, hauteur_page: int, recouvrement: int) -> list[tuple[int, int]]:
    pas = max(1, hauteur_page - recouvrement)
    limites: list[tuple[int, int]] = []
    y = 0
    while y < hauteur:
        bas = min(hauteur, y + hauteur_page)
        limites.append((y, bas))
        if bas >= hauteur:
            break
        y += pas
    # Une derniere page trop fine est fusionnee avec la precedente, sinon le
    # PDF se termine sur une bande quasi vide.
    if len(limites) >= 2:
        haut_dernier, bas_dernier = limites[-1]
        if bas_dernier - haut_dernier < hauteur_page / 3:
            limites[-2] = (limites[-2][0], bas_dernier)
            limites.pop()
    return limites


def pdf_par_ecran(
    source: Path,
    hauteur_page: int,
    destination: Path,
    recouvrement: int = RECOUVREMENT,
) -> int | None:
    """Ecrit `destination` (PDF) a partir de `source`. Renvoie le nombre de
    pages, ou None si la capture tient deja sur un ecran et ne gagne rien a
    etre paginee."""
    if hauteur_page <= 0:
        raise ValueError("hauteur_page doit etre positive")
    with Image.open(source) as image:
        largeur, hauteur = image.size
        if hauteur <= hauteur_page:
            return None
        cadre = image.convert("RGB") if image.mode != "RGB" else image
        limites = _limites(hauteur, hauteur_page, recouvrement)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.unlink(missing_ok=True)
        # Une page a la fois, ajoutee au fichier (append) : garder toutes les
        # pages decoupees en memoire doublait le poids de l'image source
        # (~300 Mo de plus pour une page de 48 000 px).
        for numero, (haut, bas) in enumerate(limites):
            page = cadre.crop((0, haut, largeur, bas))
            try:
                page.save(destination, "PDF", append=numero > 0, resolution=96.0)
            finally:
                page.close()
    return len(limites)
