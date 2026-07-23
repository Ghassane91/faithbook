from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from app.services import crypto

logger = logging.getLogger(__name__)

# Cookies porteurs de la session Facebook : leur expiration determine la
# duree de vie utile du storage_state.
FACEBOOK_SESSION_COOKIES = {"c_user", "xs"}


def parse_state(raw: str | None) -> dict | None:
    """Dechiffre puis parse le storage_state d'une cible.

    Point de lecture unique : `raw` est chiffre (Fernet) depuis la migration
    de securisation. Le repli sur `raw` en clair couvre une donnee legacy qui
    aurait echappe a la migration (jamais produite par du code a jour).
    """
    if not raw:
        return None
    texte = crypto.decrypt_text(raw)
    if texte is None:
        logger.warning("storage_state_json non dechiffrable : utilise tel quel (legacy ?)")
        texte = raw
    try:
        return json.loads(texte)
    except json.JSONDecodeError:
        return None


def session_expiry(raw: str | None) -> tuple[int, datetime | None]:
    """Retourne (nombre de cookies, date d'expiration la plus proche des cookies de session).

    Les cookies de session (expires = -1) sont ignores : ils n'ont pas de date fixe.
    """
    state = parse_state(raw)
    if not state:
        return 0, None

    cookies = state.get("cookies") or []
    names = {c.get("name") for c in cookies}
    watched = FACEBOOK_SESSION_COOKIES & names or names

    expiries = [
        c["expires"]
        for c in cookies
        if c.get("name") in watched and isinstance(c.get("expires"), (int, float)) and c["expires"] > 0
    ]
    if not expiries:
        return len(cookies), None
    return len(cookies), datetime.fromtimestamp(min(expiries), tz=timezone.utc)


def describe(raw: str | None, profile: str | None) -> tuple[bool, datetime | None, bool, str]:
    """(session_presente, expiration, expiree, message lisible)."""
    count, expires = session_expiry(raw)
    if not count and not profile:
        return False, None, False, "Aucune session enregistree (capture en visiteur anonyme)"
    if not count and profile:
        return (
            False,
            None,
            False,
            f"Profil persistant '{profile}' utilise, aucun storage_state d'amorcage",
        )
    if expires is None:
        return True, None, False, f"{count} cookie(s) enregistres, sans date d'expiration connue"

    expired = expires <= datetime.now(timezone.utc)
    if expired:
        return True, expires, True, f"Session EXPIREE depuis le {expires:%d/%m/%Y}"
    days = (expires - datetime.now(timezone.utc)).days
    return True, expires, False, f"Session valide jusqu'au {expires:%d/%m/%Y} ({days} jours)"
