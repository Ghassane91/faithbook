from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_organization, current_user, organization_admin
from app.config import settings
from app.database import engine, get_session
from app.models import Target
from app.scheduler import JOB_PREFIX, scheduler
from app.schemas import DriveCheckOut, HealthOut, JobOut
from app.services import ai_summary, run_queue, tenancy
from app.services.drive import DriveNotConfigured, drive_client

router = APIRouter(prefix="/api", tags=["Systeme"])

VERSION = "1.8.4"


@router.get("/health", response_model=HealthOut, summary="Etat du service")
def health(session: Session = Depends(get_session)):
    enabled = session.scalar(
        select(func.count()).select_from(Target).where(Target.enabled.is_(True))
    )
    queued = settings.queue_backend == "redis"
    redis_ok = run_queue.ping() if queued else True
    worker_ok = run_queue.worker_alive() if queued else True
    return HealthOut(
        status="ok" if redis_ok and worker_ok else "degraded",
        version=VERSION,
        timezone=settings.timezone,
        output_dir=settings.screenshot_dir,
        scheduler_running=scheduler.running,
        jobs=len([j for j in scheduler.get_jobs() if j.id.startswith(JOB_PREFIX)]),
        targets_enabled=enabled or 0,
        queue_backend=settings.queue_backend,
        redis_ok=redis_ok,
        worker_alive=worker_ok,
        queue_depth=run_queue.queue_depth() if queued and redis_ok else 0,
        database_backend=engine.dialect.name,
        storage_backend=settings.storage_backend,
        drive_configured=drive_client.is_configured(),
    )


@router.get(
    "/scheduler/jobs",
    response_model=list[JobOut],
    dependencies=[Depends(current_user)],
    summary="Taches planifiees et prochaines executions",
)
def list_jobs(
    context: tenancy.OrganizationContext = Depends(current_organization),
    session: Session = Depends(get_session),
):
    out: list[JobOut] = []
    for job in scheduler.get_jobs():
        if not job.id.startswith(JOB_PREFIX):
            continue
        target_id = int(job.id.removeprefix(JOB_PREFIX))
        target = session.get(Target, target_id)
        if target is None or target.organization_id != context.organization.id:
            continue
        out.append(
            JobOut(
                job_id=job.id,
                target_id=target_id,
                target_name=target.name if target else "(supprimee)",
                next_run_at=job.next_run_time,
                trigger=str(job.trigger),
            )
        )
    return out


@router.get(
    "/config",
    dependencies=[Depends(current_user)],
    summary="Configuration effective (sans secrets)",
)
def get_config():
    return {
        "timezone": settings.timezone,
        "output_dir": settings.screenshot_dir,
        "folder_date_format": settings.folder_date_format,
        "max_attempts": settings.max_attempts,
        "retry_backoff_seconds": settings.retry_backoff_seconds,
        "dedupe_mode": settings.dedupe_mode,
        "default_organization_quotas": {
            "accounts": settings.default_quota_accounts,
            "targets": settings.default_quota_targets,
            "daily_captures": settings.default_quota_daily_captures,
            "storage_bytes": settings.default_quota_storage_bytes,
            "retention_days": settings.run_retention_days,
        },
        "session_expiry_warning_days": settings.session_expiry_warning_days,
        "default_viewport": {
            "width": settings.default_viewport_width,
            "height": settings.default_viewport_height,
        },
        "full_page_scroll": {
            "enabled": settings.auto_scroll_full_page,
            "delay_ms": settings.auto_scroll_delay_ms,
            "max_steps": settings.auto_scroll_max_steps,
            "stable_rounds": settings.auto_scroll_stable_rounds,
        },
        "auth_enabled": bool(settings.api_key),
        "queue_backend": settings.queue_backend,
        "storage_backend": settings.storage_backend,
        "drive_configured": drive_client.is_configured(),
        "ai_summary": {
            "enabled": settings.ai_summary_enabled,
            "provider": settings.ai_summary_provider,
            "model": (
                settings.ollama_model
                if settings.ai_summary_provider == "ollama"
                else settings.ai_summary_model
            ),
            "configured": ai_summary.is_configured(),
        },
    }


@router.post(
    "/drive/check",
    response_model=DriveCheckOut,
    summary="Vérifier l'accès au dossier Google Drive",
)
async def check_drive(
    _context: tenancy.OrganizationContext = Depends(organization_admin),
):
    if settings.storage_backend != "google_drive":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="STORAGE_BACKEND n'est pas configuré sur google_drive.",
        )
    if not drive_client.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Google Drive incomplet : vérifiez service-account.json et "
                "GOOGLE_DRIVE_PARENT_FOLDER_ID."
            ),
        )
    try:
        meta = await asyncio.to_thread(drive_client.check_access)
    except DriveNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from None
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Google Drive inaccessible : {exc}",
        ) from None
    return DriveCheckOut(
        configured=True,
        writable=True,
        parent_name=meta.get("name"),
        shared_drive=bool(settings.google_drive_shared_drive_id),
        detail=f"Dossier « {meta.get('name', 'Drive')} » accessible en écriture.",
    )
