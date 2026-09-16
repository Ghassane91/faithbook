# -*- coding: utf-8 -*-
"""Teste l'extraction sur une capture REELLE deja en base. Lecture seule.

Ce script ne fait que des SELECT. Il n'ecrit rien en base, ne touche a aucun
fichier, ne modifie aucune capture. Il sert a juger la qualite de l'extraction
sur vos propres pages avant de brancher quoi que ce soit sur le pipeline.

S'execute dans le conteneur backend, via ops/tester-extraction.sh.

  --lister              les dernieres captures exploitables
  --cible <id>          derniere capture reussie de cette cible
  --run <id>            une capture precise
  --regle catalogue|forfaits|editorial   (defaut : catalogue)
  --invite              montre l'invite envoyee, sans appeler le modele
                        (aucun cout, aucune connexion sortante)
"""

from __future__ import annotations

import argparse
import os
import sys
import textwrap

# Fonctionne aussi bien lance par ops/tester-extraction.sh (entree standard,
# depuis /app) qu'appele directement comme fichier depuis ops/.
_RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__ if "__file__" in dir() else ".")))
if _RACINE not in sys.path:
    sys.path.insert(0, _RACINE)

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Run, RunStatus, Target
from app.services import extraction as ex

# --------------------------------------------------------------------- regles
# Reprises de ops/REGLES-EXTRACTION.md. Les descriptions sont ce que le modele
# lit : c'est leur precision qui fait la qualite du resultat. Modifiez-les ici
# pour tester une formulation, puis reportez la bonne version dans le document.

CATALOGUE = ex.Regle(
    nom="catalogue",
    ligne="un produit propose a la vente sur la page",
    champs=(
        ex.Champ("modele", "Nom du modele tel qu affiche, sans la marque si elle est repetee partout",
                 "texte", obligatoire=True, verifiable=True),
        ex.Champ("prix", "Prix de vente affiche. Si un prix est barre a cote, prendre le prix courant, pas le barre",
                 "nombre"),
        ex.Champ("devise", "Code de la devise : USD, CAD, EUR, MAD", "texte"),
        ex.Champ("prix_barre", "Prix barre avant remise, uniquement s il apparait", "nombre"),
        ex.Champ("en_stock", "Le produit est-il annonce disponible", "booleen"),
        ex.Champ("reference", "Reference ou SKU, uniquement si affichee", "texte", verifiable=True),
    ),
)

FORFAITS = ex.Regle(
    nom="forfaits",
    ligne="un forfait de transmission propose",
    champs=(
        ex.Champ("forfait", "Nom commercial du forfait", "texte", obligatoire=True, verifiable=True),
        ex.Champ("prix_mensuel", "Prix par mois en facturation mensuelle", "nombre"),
        ex.Champ("prix_annuel", "Prix en facturation annuelle. Preciser dans note s il est par mois ou par an",
                 "nombre"),
        ex.Champ("devise", "Code de la devise : USD, CAD, EUR", "texte"),
        ex.Champ("photos_incluses", "Nombre de photos incluses par mois, ou illimite", "texte", verifiable=True),
        ex.Champ("note", "Condition particuliere : engagement, premiere annee, par camera", "texte"),
    ),
)

EDITORIAL = ex.Regle(
    nom="editorial",
    ligne="une annonce ou un article publie sur la page",
    champs=(
        ex.Champ("titre", "Titre de l annonce ou de l article", "texte", obligatoire=True, verifiable=True),
        ex.Champ("date_publication", "Date de publication si elle apparait", "date"),
        ex.Champ("sujet", "En cinq mots maximum : nouveau produit, promotion, mise a jour, recrutement, autre",
                 "texte"),
        ex.Champ("produit_cite", "Modele de camera cite, s il y en a un", "texte", verifiable=True),
    ),
)

REGLES = {r.nom: r for r in (CATALOGUE, FORFAITS, EDITORIAL)}


# --------------------------------------------------------------------- sortie

def tableau(regle: ex.Regle, lignes: list[dict]) -> None:
    noms = [c.nom for c in regle.champs]
    largeurs = {}
    for n in noms:
        vues = [len(str(l.get(n) if l.get(n) is not None else "-")) for l in lignes]
        largeurs[n] = max([len(n)] + vues + [3])
        largeurs[n] = min(largeurs[n], 34)

    def cell(v, n):
        t = "-" if v is None else str(v)
        return t[: largeurs[n]].ljust(largeurs[n])

    print("  " + " | ".join(n[: largeurs[n]].ljust(largeurs[n]) for n in noms))
    print("  " + "-+-".join("-" * largeurs[n] for n in noms))
    for l in lignes:
        print("  " + " | ".join(cell(l.get(n), n) for n in noms))


def lister(session, limite: int) -> None:
    q = (
        select(Run.id, Run.capture_date, Run.page_title, Target.id, Target.name, Target.url,
               Run.body_text)
        .join(Target, Target.id == Run.target_id)
        .where(Run.status == RunStatus.success, Run.body_text.is_not(None))
        .order_by(Run.id.desc())
        .limit(limite)
    )
    print(f"{'run':>7}  {'cible':>6}  {'date':<10}  {'texte':>8}  nom de la cible")
    print("-" * 78)
    for rid, date, _titre, tid, nom, _url, texte in session.execute(q):
        print(f"{rid:>7}  {tid:>6}  {date:<10}  {len(texte or ''):>8}  {(nom or '')[:40]}")
    print("\nRelancer avec :  --cible <cible>   ou   --run <run>")


def charger(session, cible: int | None, run_id: int | None):
    base = (
        select(Run, Target)
        .join(Target, Target.id == Run.target_id)
        .where(Run.status == RunStatus.success, Run.body_text.is_not(None))
    )
    if run_id:
        base = base.where(Run.id == run_id)
    elif cible:
        base = base.where(Target.id == cible)
    ligne = session.execute(base.order_by(Run.id.desc()).limit(1)).first()
    return ligne if ligne is None else (ligne[0], ligne[1])


def main() -> int:
    p = argparse.ArgumentParser(add_help=True)
    p.add_argument("--lister", action="store_true")
    p.add_argument("--limite", type=int, default=25)
    p.add_argument("--cible", type=int)
    p.add_argument("--run", type=int)
    p.add_argument("--regle", default="catalogue", choices=sorted(REGLES))
    p.add_argument("--invite", action="store_true",
                   help="montre l invite sans appeler le modele")
    a = p.parse_args()

    with SessionLocal() as session:
        if a.lister or not (a.cible or a.run):
            lister(session, a.limite)
            return 0

        trouve = charger(session, a.cible, a.run)
        if trouve is None:
            print("Aucune capture reussie avec du texte pour ce critere.")
            print("Lancer --lister pour voir ce qui est disponible.")
            return 1
        run, cible = trouve

    regle = REGLES[a.regle]
    texte = run.body_text or ""

    print("=" * 78)
    print(f"CIBLE {cible.id} — {cible.name}")
    print(f"  {cible.url}")
    print(f"  capture {run.id} du {run.capture_date} — {len(texte)} caracteres de texte")
    print(f"  regle : {regle.nom}")
    print("=" * 78)

    invite, tronque = ex.construire_invite(regle, texte, run.page_title, run.final_url or cible.url)
    if tronque:
        print(f"\n  ATTENTION : page tronquee a {ex.MAX_CARACTERES} caracteres.")

    if a.invite:
        print("\n--- INVITE (aucun appel au modele, aucun cout) ---\n")
        print(textwrap.indent(invite, "  "))
        return 0

    if not ex.is_configured():
        print("\nExtraction non configuree. Verifier dans .env :")
        print("  EXTRACTION_ENABLED=true")
        print("  ANTHROPIC_API_KEY=...   (ou AI_SUMMARY_PROVIDER=ollama)")
        print("\nL invite reste consultable avec --invite.")
        return 2

    fournisseur = ex._fournisseur()
    modele = ex._modele_deepseek() if fournisseur == "deepseek" else ex._modele()
    print(f"\nAppel de {fournisseur} (modele {modele}) ...")
    resultat = ex.extraire(regle, texte, run.page_title, run.final_url or cible.url)
    if resultat is None:
        print("Extraction indisponible. Le detail est dans les journaux du conteneur :")
        print("  docker compose logs --tail=40 backend")
        return 3

    print(f"\n{len(resultat.lignes)} ligne(s) retenue(s)\n")
    if resultat.lignes:
        tableau(regle, resultat.lignes)
    if resultat.anomalies:
        print("\nANOMALIES — valeurs ecartees ou signalees :")
        for an in resultat.anomalies:
            print("  - " + an)
    else:
        print("\nAucune anomalie.")
    print("\nRappel : rien n a ete ecrit en base.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
