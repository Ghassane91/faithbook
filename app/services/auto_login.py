"""Connexion automatique a un site protege par un formulaire (ex. HuntX).

Principe : la capture ouvre la page voulue. Si le site affiche a la place un
formulaire de connexion (champ mot de passe visible), FaithBook le remplit
avec les identifiants chiffres du compte, valide, puis revient a la page
voulue. Les cookies obtenus sont ensuite conserves dans le coffre du compte,
comme pour une connexion manuelle : la connexion n est refaite que lorsque
la session a expire.

Jamais utilise pour Facebook, qui reste en connexion manuelle.
Les identifiants ne sont jamais journalises ni renvoyes par l API.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from app.services import crypto

logger = logging.getLogger(__name__)

# Valeurs par defaut, suffisantes pour la plupart des formulaires simples.
CHAMP_IDENTIFIANT = (
    'input[type="email"], input[autocomplete="username"], input[name*="email" i], '
    'input[name*="user" i], input[name*="login" i], input[type="text"]'
)
CHAMP_MOT_DE_PASSE = 'input[type="password"]'
BOUTON_VALIDER = 'button[type="submit"], input[type="submit"]'


@dataclass(frozen=True)
class Identifiants:
    utilisateur: str
    mot_de_passe: str
    login_url: str | None = None
    champ_identifiant: str = CHAMP_IDENTIFIANT
    champ_mot_de_passe: str = CHAMP_MOT_DE_PASSE
    bouton_valider: str = BOUTON_VALIDER

    def __repr__(self) -> str:  # jamais le mot de passe dans un journal
        return f"Identifiants(utilisateur={self.utilisateur!r}, mot_de_passe=***)"


class ConnexionRefusee(RuntimeError):
    """Le site a refuse les identifiants ou le formulaire est introuvable."""


def chiffrer(utilisateur: str, mot_de_passe: str) -> str:
    return crypto.encrypt_text(json.dumps({"u": utilisateur, "p": mot_de_passe}))


def charger(account) -> Identifiants | None:
    """Identifiants dechiffres du compte, ou None s il n en a pas."""
    brut = crypto.decrypt_text(getattr(account, "encrypted_credentials", None))
    if not brut:
        return None
    try:
        donnees = json.loads(brut)
    except ValueError:
        logger.error("Identifiants du compte %s illisibles.", getattr(account, "id", "?"))
        return None
    if not donnees.get("u") or not donnees.get("p"):
        return None
    selecteurs: dict = {}
    if getattr(account, "login_selectors", None):
        try:
            selecteurs = json.loads(account.login_selectors) or {}
        except ValueError:
            selecteurs = {}
    return Identifiants(
        utilisateur=donnees["u"],
        mot_de_passe=donnees["p"],
        login_url=getattr(account, "login_url", None) or None,
        champ_identifiant=selecteurs.get("username") or CHAMP_IDENTIFIANT,
        champ_mot_de_passe=selecteurs.get("password") or CHAMP_MOT_DE_PASSE,
        bouton_valider=selecteurs.get("submit") or BOUTON_VALIDER,
    )


async def formulaire_visible(page, ident: Identifiants) -> bool:
    """Vrai si la page affiche un champ mot de passe visible."""
    try:
        champ = page.locator(ident.champ_mot_de_passe).first
        return await champ.count() > 0 and await champ.is_visible()
    except Exception:  # noqa: BLE001
        return False


async def se_connecter(page, ident: Identifiants, timeout_ms: int = 30000) -> None:
    """Remplit et valide le formulaire affiche. Leve ConnexionRefusee sinon."""
    identifiant = page.locator(ident.champ_identifiant).first
    mot_de_passe = page.locator(ident.champ_mot_de_passe).first
    try:
        await identifiant.wait_for(state="visible", timeout=10000)
        await mot_de_passe.wait_for(state="visible", timeout=10000)
    except Exception as exc:
        raise ConnexionRefusee("Formulaire de connexion introuvable sur la page.") from exc

    await identifiant.fill(ident.utilisateur)
    await mot_de_passe.fill(ident.mot_de_passe)
    bouton = page.locator(ident.bouton_valider).first
    if await bouton.count() > 0:
        await bouton.click()
    else:
        await mot_de_passe.press("Enter")

    # Connexion reussie = le champ mot de passe disparait. S il reste, le site
    # a refuse (mauvais identifiants, captcha, compte bloque).
    try:
        await mot_de_passe.wait_for(state="hidden", timeout=timeout_ms)
    except Exception as exc:
        raise ConnexionRefusee(
            "Le site a refusé la connexion automatique (identifiants incorrects, "
            "compte bloqué ou vérification supplémentaire)."
        ) from exc
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:  # noqa: BLE001 - une page qui ne se calme jamais reste utilisable
        pass
    logger.info("Connexion automatique reussie pour %s", ident.utilisateur)


async def connecter_si_besoin(page, ident: Identifiants, url_cible: str, wait_until: str,
                              timeout_ms: int) -> bool:
    """Se connecte si la page affiche un formulaire, puis revient a url_cible.

    Renvoie True si une connexion a ete faite.
    """
    if not await formulaire_visible(page, ident):
        return False
    await se_connecter(page, ident, timeout_ms=timeout_ms)
    await page.goto(url_cible, wait_until=wait_until, timeout=timeout_ms)
    if await formulaire_visible(page, ident):
        raise ConnexionRefusee(
            "Connexion faite, mais le site redemande les identifiants sur la page cible."
        )
    return True
