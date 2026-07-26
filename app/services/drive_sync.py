from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import or_, select

from app.config import settings
from app.database import session_scope
from app.models import Run, RunLog, RunStatus, Target, utcnow
from app.services.capture import organization_folder, site_label, slugify
from app.services.drive import UploadResult, drive_client

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DrivePlacement:
    upload: UploadResult
    folders: tuple[str, ...]


@dataclass(frozen=True)
class DriveRetryStats:
    selected: int = 0
    uploaded: int = 0
    failed: int = 0


def date_folder_name(capture_date: str) -> str:
    try:
        return date.fromisoformat(capture_date).strftime(settings.folder_date_format)
    except (TypeError, ValueError):
        return capture_date


def folder_names(target: Target, capture_date: str) -> tuple[str, ...]:
    names = [
        date_folder_name(capture_date),
        organization_folder(target),
        site_label(target.url),
    ]
    if target.subfolder:
        names.append(slugify(target.subfolder))
    return tuple(names)


def upload_capture(
    path: Path,
    target: Target,
    capture_date: str,
    filename: str | None = None,
) -> DrivePlacement:
    """Crée AAAA-MM-JJ/organisation/site[/sous-dossier], puis envoie le PNG."""
    if not drive_client.is_configured():
        raise RuntimeError(
            "Google Drive non configuré : fichier de compte de service ou "
            "GOOGLE_DRIVE_PARENT_FOLDER_ID manquant."
        )
    names = folder_names(target, capture_date)
    parent_id: str | None = None
    for name in names:
        parent_id = drive_client.ensure_folder(name, parent_id)
    assert parent_id is not None
    upload = drive_client.upload(path, parent_id, filename or path.name)
    return DrivePlacement(upload=upload, folders=names)


def mark_success(run: Run, placement: DrivePlacement) -> None:
    run.drive_folder_id = placement.upload.folder_id
    run.drive_file_id = placement.upload.file_id
    run.drive_file_link = placement.upload.web_link
    run.drive_status = "uploaded"
    run.drive_last_error = None
    run.drive_uploaded_at = utcnow()
    run.drive_next_retry_at = None


def mark_failure(run: Run, exc: Exception) -> None:
    run.drive_attempts = (run.drive_attempts or 0) + 1
    run.drive_status = "failed"
    run.drive_last_error = str(exc)[:2000]
    base = max(1, settings.google_drive_retry_minutes)
    exponent = min(max(0, run.drive_attempts - 1), 6)
    delay = min(360, base * (2**exponent))
    run.drive_next_retry_at = utcnow() + timedelta(minutes=delay)


def _append_log(session, run: Run, level: str, message: str) -> None:
    session.add(
        RunLog(
            run_id=run.id,
            step="drive",
            level=level,
            message=message,
            attempt=run.drive_attempts or None,
        )
    )


def retry_due_uploads() -> DriveRetryStats:
    """Reprend un lot d'envois Drive sans refaire les captures."""
    if settings.storage_backend != "google_drive" or not drive_client.is_configured():
        return DriveRetryStats()

    now = utcnow()
    selected = uploaded = failed = 0
    with session_scope() as session:
        runs = session.scalars(
            select(Run)
            .where(
                Run.status == RunStatus.success,
                Run.screenshot_path.is_not(None),
                Run.drive_file_id.is_(None),
                Run.drive_status.in_(["pending", "failed"]),
                or_(
                    Run.drive_next_retry_at.is_(None),
                    Run.drive_next_retry_at <= now,
                ),
            )
            .order_by(Run.id)
            .limit(max(1, settings.google_drive_retry_batch_size))
        ).all()

        for run in runs:
            selected += 1
            target = session.get(Target, run.target_id)
            path = Path(run.screenshot_path or "")
            if target is None or not path.is_file():
                mark_failure(
                    run,
                    RuntimeError("Cible ou capture locale introuvable pour la reprise Drive."),
                )
                _append_log(session, run, "ERROR", run.drive_last_error or "Reprise impossible")
                failed += 1
                session.commit()
                continue
            try:
                run.drive_attempts = (run.drive_attempts or 0) + 1
                placement = upload_capture(path, target, run.capture_date, path.name)
                mark_success(run, placement)
                _append_log(
                    session,
                    run,
                    "INFO",
                    "Reprise Drive réussie : "
                    + "/".join(placement.folders)
                    + f" ({placement.upload.file_id})",
                )
                uploaded += 1
            except Exception as exc:  # noqa: BLE001
                # L'incrément a déjà été fait pour cette tentative.
                run.drive_attempts = max(0, (run.drive_attempts or 1) - 1)
                mark_failure(run, exc)
                _append_log(
                    session,
                    run,
                    "ERROR",
                    f"Reprise Drive échouée : {run.drive_last_error}",
                )
                failed += 1
            session.commit()

    if selected:
        logger.info(
            "Reprise Drive : %s sélectionnée(s), %s envoyée(s), %s échec(s)",
            selected,
            uploaded,
            failed,
        )
    return DriveRetryStats(selected=selected, uploaded=uploaded, failed=failed)
