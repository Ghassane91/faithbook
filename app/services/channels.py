"""Canaux d alerte complementaires au mail : Telegram et webhook generique.

Chaque canal est independant : une panne de l un n empeche ni les autres
ni la capture. Tout reste inactif tant que les reglages sont vides.
"""

from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot%s/sendMessage"
# Telegram refuse les messages au-dela de 4096 caracteres.
TELEGRAM_MAX = 4000


def telegram_actif() -> bool:
    return bool(
        settings.notify_telegram_bot_token and settings.notify_telegram_chat_id
    )


def webhook_actif() -> bool:
    return bool(settings.notify_webhook_url)


def _envoyer_telegram(sujet: str, corps: str) -> None:
    texte = (sujet + "\n\n" + corps)[:TELEGRAM_MAX]
    reponse = httpx.post(
        TELEGRAM_API % settings.notify_telegram_bot_token,
        json={
            "chat_id": settings.notify_telegram_chat_id,
            "text": texte,
            "disable_web_page_preview": True,
        },
        timeout=settings.notify_channel_timeout_seconds,
    )
    reponse.raise_for_status()


def _envoyer_webhook(sujet: str, corps: str) -> None:
    """Charge utile comprise par Slack, Discord et n8n a la fois.

    Slack lit "text", Discord lit "content", n8n lit tout : les cles
    inconnues sont ignorees, donc un seul envoi couvre les trois.
    """
    texte = sujet + "\n\n" + corps
    reponse = httpx.post(
        settings.notify_webhook_url,
        json={"text": texte, "content": texte, "sujet": sujet, "corps": corps},
        timeout=settings.notify_channel_timeout_seconds,
    )
    reponse.raise_for_status()


CANAUX = (
    ("telegram", telegram_actif, _envoyer_telegram),
    ("webhook", webhook_actif, _envoyer_webhook),
)


def broadcast(sujet: str, corps: str) -> list[str]:
    """Diffuse sur tous les canaux actifs, renvoie ceux qui ont abouti."""
    envoyes: list[str] = []
    for nom, actif, envoyer in CANAUX:
        if not actif():
            continue
        try:
            envoyer(sujet, corps)
            envoyes.append(nom)
        except Exception:  # noqa: BLE001 - un canal casse n en bloque aucun autre
            logger.error("Alerte %s non envoyee", nom, exc_info=True)
    return envoyes