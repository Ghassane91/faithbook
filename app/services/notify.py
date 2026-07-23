from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.config import settings
from app.database import session_scope
from app.models import Account, AccountStatus, Run, RunStatus, Target, User, utcnow
from app.services import mailer, session_check
from app.services.login_browser import login_manager

logger = logging.getLogger(__name__)

# Libellés lisibles pour les mails.
STATUS_FR = {
    RunStatus.success: "réussie",
    RunStatus.failed: "échouée",
    RunStatus.skipped: "ignorée (doublon)",
    RunStatus.pending: "en attente",
    RunStatus.running: "en cours",
    RunStatus.suspended: "suspendue",
}
ACCOUNT_FR = {
    AccountStatus.connected: "connecté",
    AccountStatus.never: "jamais connecté",
    AccountStatus.expired: "session expirée",
    AccountStatus.verification_required: "vérification requise (2FA/checkpoint)",
    AccountStatus.error: "erreur",
}


def _recipient() -> str | None:
    """Destinataire des alertes : NOTIFY_EMAIL, sinon le premier utilisateur."""
    if settings.notify_email.strip():
        return settings.notify_email.strip()
    with session_scope() as s:
        user = s.scalars(select(User).where(User.is_active).order_by(User.id)).first()
        return user.email if user else None


def _send(subject: str, body: str) -> None:
    """Envoi best-effort : une alerte ne doit jamais casser une capture."""
    try:
        to = _recipient()
        if not to:
            logger.warning("Aucun destinataire de notification configure.")
            return
        mailer.send_email(to, subject, body)
    except Exception:  # noqa: BLE001
        logger.error("Envoi de notification impossible", exc_info=True)


# --- 1. Alerte immediate sur echec de capture ------------------------------
def notify_failure(target: Target, run: Run) -> None:
    if not settings.notify_on_failure:
        return
    lien = f"{settings.public_url.rstrip('/')}/#/historique"
    body = (
        f"La capture planifiée a échoué après {run.attempts} tentative(s).\n\n"
        f"Cible   : {target.name}\n"
        f"Adresse : {target.url}\n"
        f"Date    : {run.capture_date}\n"
        f"Erreur  : {(run.error_message or 'inconnue')[:500]}\n\n"
        f"Détail et journal complet : {lien}\n\n"
        f"— FaithBook"
    )
    _send(f"FaithBook — échec de capture : {target.name}", body)


# --- 1bis. Alerte quand une page suivie a changé ---------------------------
def notify_change(target: Target, run: Run, prev: Run) -> None:
    pct = round((run.change_ratio or 0) * 100, 1)
    lien = f"{settings.public_url.rstrip('/')}/#/historique"
    body = (
        f"La page suivie a changé depuis la dernière capture.\n\n"
        f"Cible      : {target.name}\n"
        f"Adresse    : {target.url}\n"
        f"Changement : {pct} % de la page\n"
        f"Date       : {run.capture_date}\n\n"
        f"Comparez les captures (avant / après) dans l'historique :\n{lien}\n\n"
        f"— FaithBook"
    )
    _send(f"FaithBook — « {target.name} » a changé ({pct} %)", body)


# --- 2. Verification quotidienne des sessions ------------------------------
async def check_all_sessions() -> None:
    """Teste chaque compte connecté et alerte si une session est à reconnecter.

    Un seul mail récapitulatif, uniquement s'il y a un problème.
    """
    problemes: list[str] = []
    with session_scope() as s:
        accounts = s.scalars(select(Account)).all()
        infos = [(a.id, a.name, a.profile_slug, a.platform) for a in accounts]

    for account_id, name, slug, platform in infos:
        if login_manager.active_account_id == account_id:
            continue  # connexion manuelle en cours : ne pas interférer
        try:
            result = await session_check.check_account(slug, platform)
        except Exception:  # noqa: BLE001
            logger.warning("Test de session impossible pour %s", name, exc_info=True)
            continue
        with session_scope() as s:
            account = s.get(Account, account_id)
            if account is None:
                continue
            account.status = result["status"]
            account.last_verified_at = utcnow()
            account.last_error = (
                result["detail"] if result["status"] == AccountStatus.error else None
            )
            s.commit()
        if result["status"] in (
            AccountStatus.expired,
            AccountStatus.verification_required,
            AccountStatus.error,
        ):
            problemes.append(f"- {name} : {ACCOUNT_FR[result['status']]} — {result['detail']}")
        logger.info("Session '%s' testee : %s", name, result["status"].value)

    if problemes:
        lien = f"{settings.public_url.rstrip('/')}/#/comptes"
        body = (
            "Le contrôle quotidien des comptes connectés a détecté :\n\n"
            + "\n".join(problemes)
            + f"\n\nReconnectez le(s) compte(s) ici : {lien}\n\n— FaithBook"
        )
        _send("FaithBook — session(s) à reconnecter", body)


# --- 3. Rapport quotidien ---------------------------------------------------
def daily_report() -> None:
    """Un seul mail le matin : les captures d'hier + l'état des sessions."""
    tz = ZoneInfo(settings.timezone)
    hier = (datetime.now(tz) - timedelta(days=1)).strftime("%Y-%m-%d")

    with session_scope() as s:
        runs = s.scalars(select(Run).where(Run.capture_date == hier)).all()
        targets = {t.id: t for t in s.scalars(select(Target)).all()}
        accounts = s.scalars(select(Account)).all()

        total = len(runs)
        ok = sum(1 for r in runs if r.status == RunStatus.success)
        skipped = sum(1 for r in runs if r.status == RunStatus.skipped)
        failed = [r for r in runs if r.status == RunStatus.failed]

        lignes = [f"Captures du {hier} : {ok} réussie(s), {skipped} ignorée(s), "
                  f"{len(failed)} échec(s) sur {total} exécution(s)."]

        if failed:
            lignes.append("\nÉchecs :")
            for r in failed:
                t = targets.get(r.target_id)
                nom = t.name if t else f"cible #{r.target_id}"
                lignes.append(f"- {nom} : {(r.error_message or 'erreur inconnue')[:160]}")

        if accounts:
            lignes.append("\nComptes connectés :")
            for a in accounts:
                lignes.append(f"- {a.name} : {ACCOUNT_FR.get(a.status, a.status.value)}")

        actives = sum(1 for t in targets.values() if t.enabled)
        lignes.append(f"\nCibles actives : {actives}")
        lignes.append(f"\nTableau de bord : {settings.public_url.rstrip('/')}\n\n— FaithBook")

    _send(f"FaithBook — rapport du {hier}", "\n".join(lignes))
