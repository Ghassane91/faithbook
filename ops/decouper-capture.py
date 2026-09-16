# -*- coding: utf-8 -*-
"""Decoupe une capture FaithBook tres longue en pages lisibles.

Une capture plein-page d'un site web peut faire 1440 x 20000 pixels : dans
l'outil Photos de Windows (ou n'importe quel visualiseur d'images), une image
avec un tel rapport largeur/hauteur s'affiche comme un ruban illisible, et
zoomer ne change rien au probleme -- l'image entiere ne tient jamais dans la
fenetre a une taille ou le texte est net.

Ce script ne touche a rien sur le serveur ni au pipeline de capture : il lit
une image existante et ecrit des pages a cote, dans un sous-dossier. La
capture d'origine n'est jamais modifiee ni supprimee.

Usage :
    python3 decouper-capture.py <fichier.jpg>
    python3 decouper-capture.py <dossier>              (traite chaque image)
    python3 decouper-capture.py <dossier> --tout        (meme les images deja
                                                          de taille normale)
    python3 decouper-capture.py <fichier.jpg> --hauteur 2400 --recouvrement 100

Pour chaque "nom.jpg", produit un dossier "nom_pages/" contenant
"nom_page01.jpg", "nom_page02.jpg", etc. -- ouvrable directement dans
l'outil Photos : les fleches gauche/droite font defiler les pages.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("Pillow n'est pas installe. Sur cette machine :")
    print("  python3 -m pip install --user Pillow")
    sys.exit(1)

EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

# Au-dela de ce rapport hauteur/largeur, une image est consideree "trop
# longue" et decoupee automatiquement en mode dossier. Une capture normale
# (un ecran, pas de defilement) reste sous ce seuil et n'est pas touchee.
SEUIL_RATIO = 2.5
SEUIL_HAUTEUR_MIN = 3000


def _devrait_etre_decoupee(largeur: int, hauteur: int) -> bool:
    return hauteur >= SEUIL_HAUTEUR_MIN and hauteur / max(1, largeur) >= SEUIL_RATIO


def decouper(chemin: Path, hauteur_page: int, recouvrement: int) -> Path | None:
    """Ecrit les pages dans <chemin_sans_extension>_pages/. Renvoie ce dossier."""
    with Image.open(chemin) as img:
        img = img.convert("RGB") if img.mode not in ("RGB", "L") else img.copy()
        largeur, hauteur = img.size

        if hauteur <= hauteur_page:
            print(f"  {chemin.name} : {largeur}x{hauteur}, deja lisible telle quelle -- ignoree.")
            return None

        dossier = chemin.with_name(chemin.stem + "_pages")
        dossier.mkdir(exist_ok=True)
        # Nettoie les pages d'une execution precedente : sinon relancer avec
        # d'autres parametres (--hauteur different) laisse des pages en trop.
        for ancien in dossier.glob(f"{chemin.stem}_page*.jpg"):
            ancien.unlink()

        pas = max(1, hauteur_page - recouvrement)
        limites = []
        y = 0
        while y < hauteur:
            bas = min(hauteur, y + hauteur_page)
            limites.append((y, bas))
            if bas >= hauteur:
                break
            y += pas

        # Fusionne une derniere page trop fine (moins d'un tiers de la hauteur
        # cible) avec la precedente plutot que de laisser une page quasi vide.
        if len(limites) >= 2:
            dernier_haut, dernier_bas = limites[-1]
            if dernier_bas - dernier_haut < hauteur_page / 3:
                avant_haut, _ = limites[-2]
                limites[-2] = (avant_haut, dernier_bas)
                limites.pop()

        largeur_num = len(str(len(limites)))
        for i, (haut, bas) in enumerate(limites, start=1):
            page = img.crop((0, haut, largeur, bas))
            nom = f"{chemin.stem}_page{i:0{largeur_num}d}.jpg"
            page.save(dossier / nom, quality=92, optimize=True)

        print(f"  {chemin.name} : {largeur}x{hauteur} -> {len(limites)} page(s) dans {dossier.name}/")
        return dossier


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cible", help="fichier image, ou dossier a traiter")
    p.add_argument("--hauteur", type=int, default=2400, help="hauteur max par page en pixels (defaut : 2400)")
    p.add_argument("--recouvrement", type=int, default=80, help="pixels partages entre deux pages consecutives (defaut : 80)")
    p.add_argument("--tout", action="store_true", help="en mode dossier, decoupe aussi les images de taille normale")
    a = p.parse_args()

    cible = Path(a.cible)
    if not cible.exists():
        print(f"Introuvable : {cible}", file=sys.stderr)
        return 1

    if cible.is_file():
        decouper(cible, a.hauteur, a.recouvrement)
        return 0

    fichiers = sorted(
        f for f in cible.rglob("*")
        if f.is_file() and f.suffix.lower() in EXTENSIONS and "_pages" not in f.parts
    )
    if not fichiers:
        print(f"Aucune image trouvee dans {cible}")
        return 0

    traitees = 0
    for f in fichiers:
        try:
            with Image.open(f) as img:
                largeur, hauteur = img.size
        except Exception as exc:
            print(f"  {f.name} : illisible ({exc}), ignoree.")
            continue
        if a.tout or _devrait_etre_decoupee(largeur, hauteur):
            decouper(f, a.hauteur, a.recouvrement)
            traitees += 1

    print(f"\n{traitees}/{len(fichiers)} image(s) decoupee(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
