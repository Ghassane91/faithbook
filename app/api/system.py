from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.config import settings
from app.database import get_session
from app.models import Target
from app.scheduler import JOB_PREFIX, scheduler
from app.schemas import HealthOut, JobOut

router = APIRouter(prefix="/api", tags=["Systeme"])

VERSION = "1.0.0"


@router.get("/health", response_model=HealthOut, summary="Etat du service")
def health(session: Session = Depends(get_session)):
    enabled = session.scalar(
        select(func.count()).select_from(Target).where(Target.enabled.is_(True))
    )
    return HealthOut(
        status="ok",
        version=VERSION,
        timezone=settings.timezone,
        output_dir=settings.screenshot_dir,
        scheduler_running=scheduler.running,
        jobs=len([j for j in scheduler.get_jobs() if j.id.startswith(JOB_PREFIX)]),
        targets_enabled=enabled or 0,
    )


@router.get(
    "/scheduler/jobs",
    response_model=list[JobOut],
    dependencies=[Depends(current_user)],
    summary="Taches planifiees et prochaines executions",
)
def list_jobs(session: Session = Depends(get_session)):
    out: list[JobOut] = []
    for job in scheduler.get_jobs():
        if not job.id.startswith(JOB_PREFIX):
            continue
        target_id = int(job.id.removeprefix(JOB_PREFIX))
        target = session.get(Target, target_id)
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
        "run_retention_days": settings.run_retention_days,
        "default_viewport": {
            "width": settings.default_viewport_width,
            "height": settings.default_viewport_height,
        },
        "auth_enabled": bool(settings.api_key),
    }


# --- Google Drive : EN SUSPEND ------------------------------------------
# La route POST /api/drive/check est retiree de l'API tant que l'option n'est
# pas reactivee. Le code du client Drive reste dans app/services/drive.py et
# ses tests dans tests/suspendu/. Voir README §2 pour la reactivation.
