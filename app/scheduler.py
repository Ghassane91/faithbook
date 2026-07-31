from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.config import settings
from app.database import session_scope
from app.models import Run, RunStatus, Target, TriggerType
from app.services import drive_sync, notify, quotas
from app.services.catchup import cibles_a_rattraper
from app.services.runner import trigger_target

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone=settings.timezone)

JOB_PREFIX = "target-"
PURGE_JOB_ID = "purge-old-runs"
SESSION_CHECK_JOB_ID = "session-check"
DAILY_REPORT_JOB_ID = "daily-report"
DRIVE_RETRY_JOB_ID = "drive-retry"
CATCHUP_JOB_ID = "catchup-missed"


def job_id_for(target_id: int) -> str:
    return f"{JOB_PREFIX}{target_id}"


def build_trigger(target: Target) -> CronTrigger:
    tz = ZoneInfo(target.timezone_name or settings.timezone)
    if target.cron_expression:
        return CronTrigger.from_crontab(target.cron_expression, timezone=tz)
    hour, minute = target.run_time.split(":")
    return CronTrigger(hour=int(hour), minute=int(minute), timezone=tz)


async def _run_scheduled(target_id: int) -> None:
    try:
        run_id, status, detail = await trigger_target(target_id, TriggerType.scheduled)
        logger.info("Cible %s planifiee -> run=%s %s (%s)", target_id, run_id, status, detail)
    except Exception:
        logger.exception("Echec du declenchement planifie pour la cible %s", target_id)


def schedule_target(target: Target) -> None:
    """(Re)programme une cible. Supprime le job si la cible est desactivee."""
    jid = job_id_for(target.id)
    if scheduler.get_job(jid):
        scheduler.remove_job(jid)

    if not target.enabled or not (target.run_time or target.cron_expression):
        logger.info("Cible %s non planifiee (desactivee ou sans horaire)", target.id)
        return

    scheduler.add_job(
        _run_scheduled,
        trigger=build_trigger(target),
        args=[target.id],
        id=jid,
        name=target.name,
        replace_existing=True,
        misfire_grace_time=3600,  # rattrape jusqu'a 1h de retard (redemarrage, VPS occupe)
        coalesce=True,            # une seule execution meme si plusieurs echeances manquees
        max_instances=1,
    )
    job = scheduler.get_job(jid)
    # APScheduler ne renseigne next_run_time que si le planificateur tourne :
    # sans ce garde-fou, programmer une cible plante quand il est arrete.
    logger.info("Cible %s planifiee, prochaine execution : %s", target.id, getattr(job, "next_run_time", None))


def unschedule_target(target_id: int) -> None:
    jid = job_id_for(target_id)
    if scheduler.get_job(jid):
        scheduler.remove_job(jid)


def next_run_for(target_id: int) -> datetime | None:
    job = scheduler.get_job(job_id_for(target_id))
    return getattr(job, "next_run_time", None) if job else None


def _purge_old_runs() -> None:
    with session_scope() as session:
        removed_runs, removed_files = quotas.purge_expired_runs(session)
    if removed_runs or removed_files:
        logger.info(
            "Purge par organisation : %s exécution(s), %s fichier(s)",
            removed_runs,
            removed_files,
        )


async def _session_check_job() -> None:
    try:
        await notify.check_all_sessions()
    except Exception:
        logger.exception("Verification des sessions en erreur")


def _daily_report_job() -> None:
    try:
        notify.daily_report()
    except Exception:
        logger.exception("Rapport quotidien en erreur")


def _drive_retry_job() -> None:
    try:
        drive_sync.retry_due_uploads()
    except Exception:
        logger.exception("Reprise automatique Google Drive en erreur")


def _cron_at(hhmm: str) -> CronTrigger | None:
    """Trigger quotidien depuis 'HH:MM', None si vide ou invalide."""
    hhmm = (hhmm or "").strip()
    if not hhmm:
        return None
    try:
        hour, minute = hhmm.split(":")
        return CronTrigger(hour=int(hour), minute=int(minute),
                           timezone=ZoneInfo(settings.timezone))
    except (ValueError, TypeError):
        logger.warning("Horaire invalide '%s' (attendu HH:MM) : tache desactivee", hhmm)
        return None


def load_all_targets() -> int:
    with session_scope() as session:
        targets = session.scalars(select(Target).where(Target.enabled.is_(True))).all()
        for target in targets:
            try:
                schedule_target(target)
            except Exception:
                logger.exception("Impossible de planifier la cible %s", target.id)
    return len(scheduler.get_jobs())


async def _catchup_job() -> None:
    """Relance au demarrage les captures dont l echeance est passee sans suite."""
    if not settings.catchup_missed_runs:
        return
    for target_id in cibles_a_rattraper():
        await _run_scheduled(target_id)


def start_scheduler() -> None:
    if scheduler.running:
        return
    scheduler.start()
    scheduler.add_job(
        _purge_old_runs,
        trigger=CronTrigger(hour=3, minute=30, timezone=ZoneInfo(settings.timezone)),
        id=PURGE_JOB_ID,
        replace_existing=True,
    )
    # Controle quotidien des sessions des comptes connectes (alerte si souci).
    trig = _cron_at(settings.session_check_time)
    if trig:
        scheduler.add_job(
            _session_check_job, trigger=trig, id=SESSION_CHECK_JOB_ID,
            replace_existing=True, misfire_grace_time=3600, coalesce=True,
        )
        logger.info("Controle des sessions planifie a %s", settings.session_check_time)
    # Rapport quotidien recapitulatif.
    trig = _cron_at(settings.daily_report_time)
    if trig:
        scheduler.add_job(
            _daily_report_job, trigger=trig, id=DAILY_REPORT_JOB_ID,
            replace_existing=True, misfire_grace_time=3600, coalesce=True,
        )
        logger.info("Rapport quotidien planifie a %s", settings.daily_report_time)
    if settings.storage_backend == "google_drive":
        scheduler.add_job(
            _drive_retry_job,
            trigger="interval",
            minutes=max(1, settings.google_drive_retry_minutes),
            id=DRIVE_RETRY_JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        logger.info(
            "Reprise Google Drive planifiée toutes les %s minute(s)",
            max(1, settings.google_drive_retry_minutes),
        )
    count = load_all_targets()
    if settings.catchup_missed_runs:
        # Differe de quelques secondes : la base et le worker doivent etre prets.
        attente = max(5, settings.catchup_delay_seconds)
        scheduler.add_job(
            _catchup_job,
            trigger="date",
            run_date=datetime.now(ZoneInfo(settings.timezone))
            + timedelta(seconds=attente),
            id=CATCHUP_JOB_ID,
            replace_existing=True,
        )
        logger.info("Rattrapage des captures manquees prevu dans %s s", attente)
    logger.info("Planificateur demarre (%s cibles, fuseau %s)", count, settings.timezone)


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)


def mark_interrupted_runs() -> None:
    """Au demarrage, les executions restees 'running' viennent d'un arret brutal."""
    if settings.queue_backend == "redis":
        # Le worker possède une file fiable et réinsère les messages réservés
        # après un redémarrage. Marquer ici les runs comme échoués créerait une
        # course entre l'API et le worker.
        return
    with session_scope() as session:
        stale = session.scalars(
            select(Run).where(Run.status.in_([RunStatus.running, RunStatus.pending]))
        ).all()
        for run in stale:
            run.status = RunStatus.failed
            run.error_message = "Interrompue par un redemarrage du service"
        if stale:
            logger.warning("%s executions interrompues marquees en echec", len(stale))
