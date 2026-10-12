"""Authenticated access to the durable HuntX archive, grouped by date and row."""
from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import current_organization, current_user
from app.config import settings
from app.database import get_session
from app.models import OrganizationMembership, Run, Target

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
