"""Authenticated access to the durable HuntX archive, grouped by date and row."""
from __future__ import annotations

import mimetypes
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import current_organization, current_user
from app.config import settings
from app.database import get_session
from app.models import OrganizationMembership, Run, RunStatus, Target

router = APIRouter(prefix="/api/huntx", tags=["Archives HuntX"], dependencies=[Depends(current_user)])
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
FILE_SUFFIXES = IMAGE_SUFFIXES | {".json", ".csv", ".md", ".xlsx"}


def artifact_model():
    # Older installations without the optional HuntX module still start normally.
    from app import models
    model = getattr(models, "HuntxDriveArtifact", None)
    if model is None:
        raise HTTPException(503, "Les archives HuntX ne sont pas installées sur ce serveur.")
    return model


def scoped_query(model, organization_id):
    return select(model).join(Run, Run.id == model.source_run_id).join(Target, Target.id == Run.target_id).where(Target.organization_id == organization_id)


def recovered_runs(session, organization_id, runs):
    """Only a successful result of the SAME merchant job resolves an attempt.

    A success from another campaign/date must not fill a historical gap.
    """
    from app import models
    job_model = getattr(models, "BrowserLinkJob", None)
    if job_model is None:
        return {}
    attempts = {}
    for run in runs:
        if run.status not in (RunStatus.failed, RunStatus.suspended, RunStatus.skipped):
            continue
        key = run.idempotency_key or ""
        match = re.fullmatch(r"chrome:\d+:link-(\d+)(?:-a\d+|:history-\d+|:hist-\d{8}T\d{6}Z)?", key) or re.fullmatch(r"(?:zyte|brightdata|brightdata:invalid-zone:\d+:brightdata):job:(\d+)(?::.*)?", key)
        if match:
            attempts[run.id] = (run, int(match[1]))
    if not attempts:
        return {}
    results = session.execute(select(job_model, Run).join(Target, Target.id == job_model.target_id)
        .join(Run, Run.id == job_model.result_run_id)
        .where(Target.organization_id == organization_id,
               job_model.id.in_({job_id for _, job_id in attempts.values()}),
               Run.target_id == job_model.target_id,
               Run.status == RunStatus.success)).all()
    successes = {job.id: result for job, result in results
                 if job.finished_at and result.screenshot_path and Path(result.screenshot_path).is_file()}
    recovered = {}
    for run_id, (attempt, job_id) in attempts.items():
        result = successes.get(job_id)
        if result and result.id > attempt.id and result.target_id == attempt.target_id:
            recovered[run_id] = dict(run_id=result.id, capture_date=result.capture_date,
                                     captured_at=result.finished_at, final_url=result.final_url)
    return recovered


@router.get("/recoveries")
def recoveries(run_ids: str = Query(max_length=4000), context=Depends(current_organization),
               session: Session = Depends(get_session)):
    parts = run_ids.split(',') if run_ids else []
    if len(parts) > 500 or any(not part.isdecimal() or len(part) > 12 for part in parts):
        raise HTTPException(422, "Identifiants d'exécution invalides.")
    ids = [int(part) for part in parts]
    runs = session.scalars(select(Run).join(Target).where(Target.organization_id == context.organization.id,
                          Run.id.in_(ids))).all() if ids else []
    return recovered_runs(session, context.organization.id, runs)


@router.get("/workspaces")
def workspaces(user=Depends(current_user), session: Session = Depends(get_session)):
    from app import models
    model = getattr(models, "HuntxDriveArtifact", None)
    if model is None:
        return []
    rows = session.execute(select(Target.organization_id, func.count(model.id))
        .select_from(model).join(Run, Run.id == model.source_run_id).join(Target, Target.id == Run.target_id)
        .join(OrganizationMembership, OrganizationMembership.organization_id == Target.organization_id)
        .where(OrganizationMembership.user_id == user.id).group_by(Target.organization_id)).all()
    return [dict(organization_id=org_id, files=count) for org_id, count in rows]


@router.get("/brightdata")
def brightdata_status(context=Depends(current_organization)):
    scoped = getattr(settings, "brightdata_organization_id", 0) == context.organization.id
    configured = False
    browser_configured = False
    if scoped:
        from app.services.brightdata_capture import api_key
        from app.services.brightdata_browser import configured as browser_ready
        configured = bool(api_key() and settings.brightdata_zone.strip())
        browser_configured = browser_ready()
    return dict(enabled=scoped and getattr(settings, "brightdata_enabled", False),
                configured=configured or (browser_configured and settings.brightdata_browser_enabled),
                browser_api=dict(enabled=scoped and settings.brightdata_browser_enabled,
                                 configured=browser_configured,
                                 daily_session_limit=settings.brightdata_browser_daily_limit if scoped else None),
                daily_limit=settings.brightdata_daily_limit if scoped else None,
                mode="fallback", reserved_requests_per_capture=2)


@router.get("/zyte")
def zyte_status(context=Depends(current_organization)):
    """Read-only provider status; never expose credentials or another tenant's setup."""
    scoped = getattr(settings, "zyte_organization_id", 0) == context.organization.id
    configured = False
    if scoped:
        from app.services.zyte_capture import api_key
        configured = bool(api_key())
    return dict(enabled=scoped and getattr(settings, "zyte_enabled", False),
                configured=configured,
                daily_limit=getattr(settings, "zyte_daily_limit", None) if scoped else None,
                mode="fallback", attempts_per_link=1)


def artifact_out(artifact, session):
    suffix = Path(artifact.filename).suffix.lower()
    run = session.get(Run, artifact.result_run_id) if artifact.result_run_id else None
    return dict(id=artifact.id, filename=artifact.filename, kind=artifact.kind,
                marketplace=artifact.marketplace, image=suffix in IMAGE_SUFFIXES,
                drive_status=artifact.drive_status, drive_url=artifact.drive_file_link,
                folder_url=f"https://drive.google.com/drive/folders/{artifact.drive_folder_id}" if artifact.drive_folder_id else None,
                result_run_id=artifact.result_run_id, source_run_id=artifact.source_run_id,
                status=run.status.value if run else None,
                error=run.error_message or run.skipped_reason if run else None)


@router.get("/archive")
def archive(capture_date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
            query: str = Query("", max_length=200), limit: int = Query(20, ge=1, le=100),
            offset: int = Query(0, ge=0), context=Depends(current_organization),
            session: Session = Depends(get_session)):
    model = artifact_model()
    base = scoped_query(model, context.organization.id)
    dates = session.execute(base.with_only_columns(model.capture_date, func.count()).group_by(model.capture_date).order_by(model.capture_date.desc())).all()
    filtered = base
    if capture_date:
        filtered = filtered.where(model.capture_date == capture_date)
    if query.strip():
        term = query.strip().lower()
        filtered = filtered.where(or_(func.lower(model.row_label).contains(term, autoescape=True),
                                      func.lower(model.marketplace).contains(term, autoescape=True),
                                      func.lower(model.filename).contains(term, autoescape=True)))
    groups = filtered.where(model.row_key.is_not(None)).with_only_columns(model.capture_date, model.row_key, func.max(model.row_label).label("row_label")).group_by(model.capture_date, model.row_key)
    total = session.scalar(select(func.count()).select_from(groups.subquery())) or 0
    selected = session.execute(groups.order_by(model.capture_date.desc(), func.max(model.row_label), model.row_key).limit(limit).offset(offset)).all()
    items = []
    for day, key, label in selected:
        # Return the whole row once it matches, including all its merchants.
        artifacts = session.scalars(base.where(model.capture_date == day, model.row_key == key).order_by(model.kind.desc(), model.marketplace, model.id)).all()
        items.append(dict(capture_date=day, row_key=key, row_label=label or key,
                          artifacts=[artifact_out(a, session) for a in artifacts]))
    exports = session.scalars(filtered.where(model.row_key.is_(None)).order_by(model.capture_date.desc(), model.id.desc())).all()
    return dict(total=total, items=items, dates=[dict(date=day, files=count) for day, count in dates],
                exports=[dict(capture_date=a.capture_date, **artifact_out(a, session)) for a in exports])


def owned_artifact(artifact_id, context, session):
    model = artifact_model()
    artifact = session.scalar(scoped_query(model, context.organization.id).where(model.id == artifact_id))
    if artifact is None:
        raise HTTPException(404, "Fichier HuntX introuvable dans cet espace.")
    return artifact


@router.get("/files/{artifact_id}")
def file(artifact_id: int, thumbnail: bool = False, download: bool = False,
         context=Depends(current_organization), session: Session = Depends(get_session)):
    artifact = owned_artifact(artifact_id, context, session)
    path = Path(artifact.local_path).resolve()
    root = Path(settings.screenshot_dir).resolve()
    suffix = Path(artifact.filename).suffix.lower()
    if not path.is_relative_to(root) or suffix not in FILE_SUFFIXES:
        raise HTTPException(404, "Fichier HuntX indisponible.")
    if not path.is_file():
        raise HTTPException(410, "Copie locale absente. Ouvrez la copie Google Drive de ce fichier.")
    if thumbnail and suffix in IMAGE_SUFFIXES:
        from app.services.capture import make_thumbnail, thumb_path
        preview = thumb_path(path)
        if not preview.is_file():
            preview = make_thumbnail(path)
        if preview and preview.is_file():
            path = preview
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, filename=artifact.filename if download else None,
                        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
