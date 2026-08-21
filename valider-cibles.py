#!/usr/bin/env python3
"""Verifie chaque URL candidate et n'ecrit que celles qui repondent.

Une liste de cent cibles construite a la main contient toujours des chemins
morts. Plutot que de les decouvrir une par une dans FaithBook, on les elimine
ici : le fichier produit ne contient que des adresses joignables.

Usage :  python3 valider-cibles.py cibles-candidates.csv
Produit : cibles-validees.csv  et  cibles-rejetees.csv
"""
import csv, io, sys, time, urllib.request, urllib.error, ssl, re

SRC = sys.argv[1] if len(sys.argv) > 1 else "cibles-candidates.csv"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36")
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def teste(url, delai=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Language": "fr,en;q=0.8"})
    try:
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=delai, context=ctx) as r:
            corps = r.read(200000)
            ms = int((time.time() - t0) * 1000)
            titre = ""
            m = re.search(rb"<title[^>]*>(.{0,120}?)</title>", corps, re.S | re.I)
            if m:
                titre = m.group(1).decode("utf-8", "replace").strip().replace("\n", " ")
            return r.status, r.geturl(), len(corps), ms, titre, ""
    except urllib.error.HTTPError as e:
        return e.code, url, 0, 0, "", "HTTP %s" % e.code
    except Exception as e:  # noqa: BLE001
        return 0, url, 0, 0, "", type(e).__name__

lignes = list(csv.DictReader(io.open(SRC, encoding="utf-8")))
ok, ko = [], []
print("%d URL a verifier\n" % len(lignes))
for i, l in enumerate(lignes, 1):
    code, final, taille, ms, titre, err = teste(l["url"])
    bon = code == 200 and taille > 2000
    l2 = dict(l)
    l2.update({"code": code, "url_finale": final, "octets": taille,
               "ms": ms, "titre": titre, "erreur": err})
    (ok if bon else ko).append(l2)
    print("%3d/%d  %-4s %-58s %s" % (i, len(lignes), code or "ERR",
                                     l["url"][:58], "" if bon else (err or "trop court")))
    time.sleep(0.4)

champs = ["nom", "marque", "categorie", "rubrique", "url", "cadence",
          "code", "url_finale", "octets", "ms", "titre", "erreur"]
for nom, jeu in (("cibles-validees.csv", ok), ("cibles-rejetees.csv", ko)):
    with io.open(nom, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=champs)
        w.writeheader()
        w.writerows(jeu)

print("\n%d retenues, %d rejetees" % (len(ok), len(ko)))
if ok:
    moy = sum(l["octets"] for l in ok) / len(ok)
    print("page moyenne : %.0f Ko de HTML" % (moy / 1024))
