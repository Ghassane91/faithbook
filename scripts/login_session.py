"""Ouvre un navigateur visible pour que VOUS vous connectiez vous-meme,
puis enregistre uniquement les cookies de session pour le backend.

Aucun identifiant n'est demande, saisi ni stocke par ce script : vous tapez
vos identifiants directement dans le navigateur, comme d'habitude.

Prerequis (sur votre poste, une seule fois) :
    pip install playwright
    playwright install chromium

Usage :
    python scripts/login_session.py                       # -> secrets/session.json
    python scripts/login_session.py --url https://www.facebook.com/ --out secrets/fb.json
    python scripts/login_session.py --push 1              # envoie la session a la cible #1
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("Playwright manquant. Installez-le :  pip install playwright && playwright install chromium")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://www.facebook.com/", help="Page de connexion")
    parser.add_argument("--out", default="secrets/session.json", help="Fichier de sortie")
    parser.add_argument("--push", type=int, default=None, help="ID de cible a mettre a jour")
    parser.add_argument("--api", default="http://localhost:3000", help="URL publique via nginx")
    parser.add_argument("--api-key", default=None, help="Valeur de l'en-tete X-API-Key")
    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print("\n=== Enregistrement de session ===")
    print("1. Une fenetre de navigateur va s'ouvrir.")
    print("2. Connectez-vous VOUS-MEME dans cette fenetre (le script ne voit pas vos identifiants).")
    print("3. Naviguez jusqu'a une page prouvant que vous etes connecte.")
    print("4. Revenez ici et appuyez sur Entree.\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(args.url)

        input("Appuyez sur Entree une fois connecte... ")

        state = context.storage_state()
        current_url = page.url
        context.close()
        browser.close()

    cookies = state.get("cookies", [])
    if not cookies:
        print("ERREUR : aucun cookie recupere. La connexion a-t-elle abouti ?")
        return 1

    names = {c["name"] for c in cookies}
    if "facebook" in args.url and not {"c_user", "xs"} & names:
        print("AVERTISSEMENT : cookies de session Facebook (c_user, xs) absents.")
        print("               La connexion n'a probablement pas abouti.")

    expiries = [c["expires"] for c in cookies if c.get("expires", -1) > 0]
    if expiries:
        soonest = datetime.fromtimestamp(min(expiries), tz=timezone.utc)
        print(f"\nExpiration la plus proche : {soonest:%d/%m/%Y}")

    out_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(f"Session enregistree : {out_path}  ({len(cookies)} cookies, derniere page {current_url})")
    print("ATTENTION : ce fichier vaut un acces a votre compte. Ne le partagez pas, ne le versionnez pas.")

    if args.push is not None:
        import urllib.error
        import urllib.request

        body = json.dumps({"storage_state": state}).encode()
        req = urllib.request.Request(
            f"{args.api}/api/targets/{args.push}/session",
            data=body,
            method="PUT",
            headers={"Content-Type": "application/json"},
        )
        if args.api_key:
            req.add_header("X-API-Key", args.api_key)
        try:
            with urllib.request.urlopen(req) as resp:
                print(f"Envoye a la cible #{args.push} : {json.load(resp)['detail']}")
        except urllib.error.HTTPError as exc:
            print(f"Echec de l'envoi ({exc.code}) : {exc.read().decode()}")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
