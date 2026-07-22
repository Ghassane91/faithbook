from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.config import settings

logger = logging.getLogger(__name__)


def smtp_configured() -> bool:
    return bool(settings.smtp_host)


def send_email(to: str, subject: str, body: str) -> bool:
    """Envoie un e-mail texte. Retourne True si un envoi a bien eu lieu.

    Sans configuration SMTP (`SMTP_HOST` vide), rien n'est envoyé : le contenu
    est écrit dans les journaux. Cela permet de tester la réinitialisation en
    local sans serveur mail — le lien apparaît dans `docker compose logs`.
    """
    if not smtp_configured():
        logger.warning(
            "\n"
            "==========================================================\n"
            "  E-MAIL NON ENVOYÉ (SMTP non configuré)\n"
            "  Destinataire : %s\n"
            "  Sujet        : %s\n"
            "  ---\n"
            "%s\n"
            "==========================================================",
            to,
            subject,
            body,
        )
        return False

    expediteur = settings.smtp_from or settings.smtp_user or "no-reply@faithbook.local"
    message = EmailMessage()
    message["From"] = expediteur
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
            if settings.smtp_starttls:
                smtp.starttls(context=ssl.create_default_context())
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)
        logger.info("E-mail envoyé à %s (%s)", to, subject)
        return True
    except Exception:  # noqa: BLE001
        # On ne fait jamais échouer la requête HTTP sur une erreur d'envoi :
        # côté utilisateur, la réponse reste neutre (voir l'endpoint /forgot).
        logger.error("Échec de l'envoi de l'e-mail à %s", to, exc_info=True)
        return False
