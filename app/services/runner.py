from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import session_scope
from app.models import Account, Run, RunLog, RunStatus, Target, TriggerType, utcnow
from app.services.capture import build_filename, capture_page, make_thumbnail, slugify
from app.services.drive import DriveNotConfigured, drive_client
from app.services.session_check import encrypted_state_to_storage

logger = logging.getLogger(__name__)

# Une seule capture a la fois : Chromium est gourmand, et cela evite
# deux executions concurrentes sur la meme cible.
_capture_semaphore = asyncio.Semaphore(1)
_running_targets: set[int] = set()


class DuplicateRun(Exception):
    """Une execution reussie existe deja pour cette cible et cette date."""


def target_tz(target: Target) -> ZoneInfo:
    try:
        return ZoneInfo(target.timezone_name or settings.timezone)
    except Exception:  # fuseau invalide -> repli UTC
        logger.warning("Fuseau invalide pour la cible %s, repli sur UTC", target.id)
        return ZoneInfo("UTC")


def local_now(target: Target) -> datetime:
    return datetime.now(target_tz(target))


def log_step(
    session: Session, run: Run, step: str, message: str, level: str = "INFO", attempt: int | None = None
) -> None:
    session.add(
        RunLog(run_id=run.id, step=step, message=message, level=level, attempt=attempt)
    )
    session.commit()
    logger.log(
        getattr(logging, level, logging.INFO),
        "run=%s target=%s step=%s %s",
        run.id,
        run.target_id,
        step,
        message,
    )


def find_existing_success(session: Session, target_id: int, capture_date: str) -> Run | None:
    return session.scalars(
        select(Run)
        .where(
            Run.target_id == target_id,
            Run.capture_date == capture_date,
            Run.status == RunStatus.success,
        )
        .order_by(Run.id.desc())
        .limit(1)
    ).first()


def find_by_hash(session: Session, target_id: int, sha256: str) -> Run | None:
    return session.scalars(
        select(Run)
        .where(
            Run.target_id == target_id,
            Run.content_sha256 == sha256,
            Run.status == RunStatus.success,
        )
        .order_by(Run.id.desc())
        .limit(1)
    ).first()


def create_run(
    session: Session, target: Target, trigger: TriggerType, capture_date: str
) -> Run:
    run = Run(
        target_id=target.id,
        trigger=trigger,
        capture_date=capture_date,
        status=RunStatus.pending,
        idempotency_key=f"{target.id}:{capture_date}:{trigger.value}:{utcnow().timestamp():.0f}",
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


async def execute_run(run_id: int, force: bool = False) -> None:
    """Execute une capture de bout en bout : Playwright -> disque -> Drive.

    Chaque etape est journalisee. En cas d'echec, on reessaie avec un backoff
    exponentiel jusqu'a MAX_ATTEMPTS avant de marquer l'execution en echec.
    """
    async with _capture_semaphore:
        with session_scope() as session:
            run = session.get(Run, run_id)
            if run is None:
                logger.error("Execution %s introuvable", run_id)
                return
            target = session.get(Target, run.target_id)
            if target is None:
                run.status = RunStatus.failed
                run.error_message = "Cible supprimee"
                run.finished_at = utcnow()
                return

            run.status = RunStatus.running
            session.commit()
            log_step(session, run, "start", f"Demarrage pour {target.url}")

            # --- Deduplication (avant tout travail couteux) ---------------
            if not force and settings.dedupe_mode in ("per_day", "both"):
                existing = find_existing_success(session, target.id, run.capture_date)
                if existing and existing.id != run.id:
                    run.status = RunStatus.skipped
                    run.skipped_reason = (
                        f"Capture deja reussie le {run.capture_date} (execution #{existing.id})"
                    )
                    run.drive_file_id = existing.drive_file_id
                    run.drive_file_link = existing.drive_file_link
                    run.drive_folder_id = existing.drive_folder_id
                    run.finished_at = utcnow()
                    run.duration_ms = _elapsed_ms(run)
                    log_step(session, run, "dedupe", run.skipped_reason)
                    return

            started = datetime.now(timezone.utc)
            last_error: Exception | None = None

            for attempt in range(1, settings.max_attempts + 1):
                run.attempts = attempt
                session.commit()
                try:
                    await _attempt_once(session, run, target, attempt, force=force)
                    run.status = RunStatus.success
                    run.error_message = None
                    run.finished_at = utcnow()
                    run.duration_ms = int(
                        (datetime.now(timezone.utc) - started).total_seconds() * 1000
                    )
                    session.commit()
                    log_step(
                        session, run, "done", f"Termine en {run.duration_ms} ms", attempt=attempt
                    )
                    return
                except DuplicateRun as exc:
                    run.status = RunStatus.skipped
                    run.skipped_reason = str(exc)
                    run.finished_at = utcnow()
                    run.duration_ms = int(
                        (datetime.now(timezone.utc) - started).total_seconds() * 1000
                    )
                    session.commit()
                    log_step(session, run, "dedupe", str(exc), attempt=attempt)
                    return
                except Exception as exc:  # noqa: BLE001 - on journalise tout
                    last_error = exc
                    log_step(
                        session,
                        run,
                        "error",
                        f"Tentative {attempt}/{settings.max_attempts} echouee : {exc}",
                        level="ERROR",
                        attempt=attempt,
                    )
                    if attempt < settings.max_attempts:
                        delay = settings.retry_backoff_seconds * (2 ** (attempt - 1))
                        log_step(
                            session, run, "retry", f"Nouvel essai dans {delay}s", attempt=attempt
                        )
                        await asyncio.sleep(delay)

            run.status = RunStatus.failed
            run.error_message = str(last_error) if last_error else "Echec inconnu"
            run.finished_at = utcnow()
            run.duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
            session.commit()
            log_step(
                session,
                run,
                "failed",
                f"Abandon apres {settings.max_attempts} tentatives",
                level="ERROR",
            )


def _elapsed_ms(run: Run) -> int:
    end = run.finished_at or utcnow()
    start = run.started_at
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return int((end - start).total_seconds() * 1000)


async def _attempt_once(
    session: Session, run: Run, target: Target, attempt: int, force: bool
) -> None:
    # --- 1. Capture -------------------------------------------------------
    now = local_now(target)
    stamp = now.strftime("%H%M%S")
    filename = build_filename(target, run.capture_date, stamp)

    # Dossier date, identique en local et sur Drive.
    folder_name = now.strftime(settings.folder_date_format)
    destination = Path(settings.screenshot_dir) / folder_name
    if target.subfolder:
        destination = destination / slugify(target.subfolder)
    destination = destination / filename

    # Session d'un compte connecté (facultatif) : capture en étant connecté.
    account_storage = None
    if target.account_id:
        account = session.get(Account, target.account_id)
        if account is None:
            log_step(session, run, "capture", "Compte lié introuvable : capture anonyme",
                     level="WARNING", attempt=attempt)
        elif not account.encrypted_state:
            log_step(session, run, "capture",
                     f"Compte « {account.name} » sans session enregistrée : capture anonyme",
                     level="WARNING", attempt=attempt)
        else:
            account_storage = encrypted_state_to_storage(account.encrypted_state)
            if account_storage is None:
                log_step(session, run, "capture",
                         f"Session du compte « {account.name} » illisible (clé changée ?) : capture anonyme",
                         level="WARNING", attempt=attempt)
            else:
                log_step(session, run, "capture",
                         f"Session du compte « {account.name} » chargée", attempt=attempt)

    log_step(session, run, "capture", f"Ouverture de {target.url}", attempt=attempt)
    result = await capture_page(target, destination, account_storage=account_storage)

    await asyncio.to_thread(make_thumbnail, destination)

    run.screenshot_path = str(result.path)
    run.screenshot_bytes = result.size_bytes
    run.content_sha256 = result.sha256
    run.page_title = result.page_title
    run.final_url = result.final_url
    session.commit()
    log_step(
        session,
        run,
        "capture",
        f"Capture OK ({result.size_bytes} octets, sha256={result.sha256[:12]}...)",
        attempt=attempt,
    )

    # --- 2. Deduplication par contenu ------------------------------------
    if not force and settings.dedupe_mode in ("content_hash", "both"):
        twin = find_by_hash(session, target.id, result.sha256)
        if twin and twin.id != run.id:
            run.drive_file_id = twin.drive_file_id
            run.drive_file_link = twin.drive_file_link
            run.drive_folder_id = twin.drive_folder_id
            session.commit()
            destination.unlink(missing_ok=True)
            raise DuplicateRun(
                f"Contenu identique a l'execution #{twin.id} (sha256 {result.sha256[:12]}) "
                "- upload evite"
            )

    # --- 3. Envoi vers Google Drive (optionnel) --------------------------
    if settings.storage_backend != "google_drive":
        log_step(
            session,
            run,
            "upload",
            f"Enregistre dans le dossier '{folder_name}' : {destination}",
            attempt=attempt,
        )
        return

    if not drive_client.is_configured():
        raise DriveNotConfigured(
            "Google Drive non configure (service-account.json ou "
            "GOOGLE_DRIVE_PARENT_FOLDER_ID manquant)"
        )

    log_step(session, run, "drive", f"Dossier du jour : {folder_name}", attempt=attempt)

    folder_id = await asyncio.to_thread(drive_client.ensure_folder, folder_name)
    if target.subfolder:
        folder_id = await asyncio.to_thread(
            drive_client.ensure_folder, target.subfolder, folder_id
        )

    upload = await asyncio.to_thread(drive_client.upload, destination, folder_id, filename)
    run.drive_folder_id = upload.folder_id
    run.drive_file_id = upload.file_id
    run.drive_file_link = upload.web_link
    session.commit()
    log_step(
        session,
        run,
        "upload",
        ("Fichier deja present sur Drive (aucun doublon cree) : " if upload.deduplicated else "Envoye sur Drive : ")
        + f"{filename} -> {upload.file_id}",
        attempt=attempt,
    )


async def trigger_target(
    target_id: int, trigger: TriggerType, force: bool = False
) -> tuple[int, RunStatus, str]:
    """Cree une execution et la lance en tache de fond. Retourne (run_id, statut, detail)."""
    if target_id in _running_targets:
        raise RuntimeError("Une execution est deja en cours pour cette cible")

    with session_scope() as session:
        target = session.get(Target, target_id)
        if target is None:
            raise LookupError("Cible introuvable")
        capture_date = local_now(target).strftime("%Y-%m-%d")

        if not force and settings.dedupe_mode in ("per_day", "both"):
            existing = find_existing_success(session, target_id, capture_date)
            if existing:
                return (
                    existing.id,
                    RunStatus.skipped,
                    f"Capture deja realisee aujourd'hui (execution #{existing.id}). "
                    "Utilisez force=true pour relancer.",
                )

        run = create_run(session, target, trigger, capture_date)
        run_id = run.id

    _running_targets.add(target_id)

    async def _wrapper() -> None:
        try:
            await execute_run(run_id, force=force)
        finally:
            _running_targets.discard(target_id)

    asyncio.create_task(_wrapper())
    return run_id, RunStatus.pending, "Execution lancee"
