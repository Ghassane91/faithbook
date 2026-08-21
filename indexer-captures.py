#!/usr/bin/env python3
"""Range les captures FaithBook dans une arborescence lisible et tient un index.

FaithBook ecrit ses fichiers sous
    /var/captures/organization-<id>/<site-slug>/<site>_<date>_<heure>.<ext>
ce qui est correct pour la machine mais impraticable des qu il y a cent cibles.

Ce script construit en parallele
    /var/captures-index/<AAAA-MM-JJ>/<marque>__<site>__<heure>.<ext>
et un fichier index.csv listant tout.

Il utilise des LIENS PHYSIQUES : aucun octet n est duplique, l arborescence
lisible ne coute rien en disque. Supprimer un lien ne supprime pas la capture
d origine tant que l autre nom existe.

Usage :
    python3 indexer-captures.py                    # indexe tout
    python3 indexer-captures.py --depuis 2026-08-10
    python3 indexer-captures.py --marques marques.csv
"""
import argparse, csv, io, os, re, sys
from pathlib import Path

SOURCE = Path("/var/captures")
CIBLE = Path("/var/captures-index")
MOTIF = re.compile(r"^(?P<site>.+)_(?P<date>\d{4}-\d{2}-\d{2})_(?P<heure>\d{6})\.(?P<ext>[a-z0-9]+)$")

def charger_marques(chemin):
    """Associe un slug de site a un nom de marque lisible, depuis le CSV de cibles."""
    table = {}
    if not chemin or not Path(chemin).exists():
        return table
    for l in csv.DictReader(io.open(chemin, encoding="utf-8")):
        url = l.get("url", "")
        hote = re.sub(r"^https?://(www\.)?", "", url).split("/")[0].lower()
        if hote:
            table[hote] = l.get("marque", "").strip() or hote
    return table

def marque_de(site_slug, table):
    # le slug commence par l hote, points remplaces ou non selon les versions
    for hote, marque in table.items():
        if site_slug.startswith(hote) or site_slug.startswith(hote.replace(".", "-")):
            return re.sub(r"[^A-Za-z0-9]+", "-", marque).strip("-").lower()
    return site_slug.split("-")[0]

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--depuis", help="ne traiter que les captures a partir de cette date (AAAA-MM-JJ)")
    p.add_argument("--marques", default="cibles-validees.csv", help="CSV des cibles, pour nommer les marques")
    p.add_argument("--sec", action="store_true", help="montrer sans rien creer")
    a = p.parse_args()

    if not SOURCE.exists():
        sys.exit("introuvable : %s" % SOURCE)
    table = charger_marques(a.marques)
    lignes, crees, existants, ignores = [], 0, 0, 0

    for fichier in sorted(SOURCE.rglob("*")):
        if not fichier.is_file() or ".thumb" in fichier.name:
            continue
        m = MOTIF.match(fichier.name)
        if not m:
            ignores += 1
            continue
        d = m.groupdict()
        if a.depuis and d["date"] < a.depuis:
            continue
        org = ""
        for part in fichier.parts:
            if part.startswith("organization-"):
                org = part.replace("organization-", "")
        marque = marque_de(d["site"], table)
        heure = "%s-%s-%s" % (d["heure"][:2], d["heure"][2:4], d["heure"][4:6])
        nom = "%s__%s__%s.%s" % (marque, d["site"], heure, d["ext"])
        dossier = CIBLE / d["date"]
        lien = dossier / nom

        if not a.sec:
            dossier.mkdir(parents=True, exist_ok=True)
            if lien.exists():
                existants += 1
            else:
                try:
                    os.link(fichier, lien)
                    crees += 1
                except OSError:
                    # systemes de fichiers differents : on retombe sur un lien symbolique
                    lien.symlink_to(fichier)
                    crees += 1
        lignes.append({
            "date": d["date"], "heure": heure.replace("-", ":"), "marque": marque,
            "site": d["site"], "organisation": org, "extension": d["ext"],
            "octets": fichier.stat().st_size,
            "chemin_lisible": str(lien), "chemin_origine": str(fichier),
        })

    if not a.sec:
        CIBLE.mkdir(parents=True, exist_ok=True)
        with io.open(CIBLE / "index.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["date", "heure", "marque", "site",
                                              "organisation", "extension", "octets",
                                              "chemin_lisible", "chemin_origine"])
            w.writeheader()
            w.writerows(sorted(lignes, key=lambda x: (x["date"], x["heure"], x["marque"])))

    total = sum(l["octets"] for l in lignes)
    print("%d captures indexees  (%d liens crees, %d deja presents, %d fichiers ignores)"
          % (len(lignes), crees, existants, ignores))
    print("volume reel : %.1f Mo" % (total / 1048576))
    if lignes:
        print("poids moyen : %.2f Mo" % (total / len(lignes) / 1048576))
        par_jour = {}
        for l in lignes:
            par_jour[l["date"]] = par_jour.get(l["date"], 0) + 1
        derniers = sorted(par_jour.items())[-5:]
        print("captures par jour (5 derniers) : " + ", ".join("%s=%d" % j for j in derniers))
    if not a.sec:
        print("index : %s" % (CIBLE / "index.csv"))

if __name__ == "__main__":
    main()
