from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_organization, current_user, organization_admin
from app.config import settings
from app.database import get_session
from app.models import Run, RunLog, RunStatus, Target, User
from app.schemas import DriveRetryOut, RunListOut, RunLogOut, RunOut, RunSummary
from app.services.capture import make_thumbnail, thumb_path
from app.services import audit, drive_sync, tenancy
from app.services.drive import drive_client
from app.services.s3 import s3_client
from app.services.request_ip import client_ip

router = APIRouter(
    prefix="/api/runs", tags=["Executions"], dependencies=[Depends(current_user)]
)


@router.get("", response_model=RunListOut, summary="Historique global des executions")
def list_runs(
    target_id: int | None = None,
    status: RunStatus | None = None,
    capture_date: str | None = Query(default=None, description="Filtre AAAA-MM-JJ"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    context: tenancy.OrganizationContext = Depends(current_organization),
    session: Session = Depends(get_session),
):
    filters = [Target.organization_id == context.organization.id]
    if target_id is not None:
        filters.append(Run.target_id == target_id)
    if status is not None:
        filters.append(Run.status == status)
    if capture_date is not None:
        filters.append(Run.capture_date == capture_date)

    total = session.scalar(
        select(func.count()).select_from(Run).join(Target).where(*filters)
    ) or 0
    rows = session.scalars(
        select(Run)
        .join(Target)
        .where(*filters)
        .order_by(Run.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return RunListOut(total=total, items=[RunSummary.model_validate(r) for r in rows])


def _owned_run(
    session: Session, run_id: int, context: tenancy.OrganizationContext
) -> Run:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Execution introuvable")
    target = session.get(Target, run.target_id)
    if target is None or target.organization_id != context.organization.id:
        raise HTTPException(status_code=403, detail="Exécution d'une autre organisation.")
    return run


@router.get("/{run_id}", response_model=RunOut, summary="Detail d'une execution (avec logs)")
def get_run(
    run_id: int,
    context: tenancy.OrganizationContext = Depends(current_organization),
    session: Session = Depends(get_session),
):
    run = _owned_run(session, run_id, context)
    out = RunOut.model_validate(run)
    # Capture reussie precedente de la meme cible (comparaison avant/apres).
    prev = session.scalars(
        select(Run)
        .where(
            Run.target_id == run.target_id,
            Run.id < run.id,
            Run.status == RunStatus.success,
            Run.screenshot_path.is_not(None),
        )
        .order_by(Run.id.desc())
    ).first()
    out.previous_run_id = prev.id if prev else None
    return out


@router.get("/{run_id}/logs", response_model=list[RunLogOut], summary="Logs d'une execution")
def get_run_logs(
    run_id: int,
    context: tenancy.OrganizationContext = Depends(current_organization),
    session: Session = Depends(get_session),
):
    run = _owned_run(session, run_id, context)
    return [RunLogOut.model_validate(entry) for entry in run.logs]


@router.get(
    "/{run_id}/thumbnail",
    summary="Vignette de la capture (leger, pour les listes)",
    response_class=FileResponse,
)
def get_run_thumbnail(
    run_id: int,
    context: tenancy.OrganizationContext = Depends(current_organization),
    session: Session = Depends(get_session),
):
    """Vignette JPEG. Retombe sur le PNG complet si elle n'existe pas encore."""
    run = _owned_run(session, run_id, context)
    if not run.screenshot_path:
        raise HTTPException(status_code=404, detail="Aucune capture pour cette execution")
    original = Path(run.screenshot_path)
    vignette = thumb_path(original)
    if vignette.is_file():
        return FileResponse(vignette, media_type="image/jpeg")
    if original.is_file():
        # Les captures antérieures à la v1.8.2 ont une ancienne vignette 4:3.
        # On recrée une fois le nouvel aperçu pleine hauteur à la demande.
        generated = make_thumbnail(original)
        if generated and generated.is_file():
            return FileResponse(generated, media_type="image/jpeg")
        return FileResponse(original, media_type="image/png")
    raise HTTPException(status_code=410, detail="Fichier de capture absent du disque")


@router.get("/{run_id}/screenshot", summary="Telecharger la capture", response_class=FileResponse)
def get_run_screenshot(
    run_id: int,
    context: tenancy.OrganizationContext = Depends(current_organization),
    session: Session = Depends(get_session),
):
    run = _owned_run(session, run_id, context)
    if not run.screenshot_path:
        raise HTTPException(status_code=404, detail="Aucune capture pour cette execution")
    path = Path(run.screenshot_path)
    if not path.is_file():
        raise HTTPException(status_code=410, detail="Fichier de capture absent du disque")
    return FileResponse(path, media_type="image/png", filename=path.name)


@router.post(
    "/{run_id}/drive/retry",
    response_model=DriveRetryOut,
    summary="Relancer l'envoi Google Drive sans refaire la capture",
)
async def retry_drive_upload(
    run_id: int,
    request: Request,
    user: User = Depends(current_user),
    context: tenancy.OrganizationContext = Depends(organization_admin),
    session: Session = Depends(get_session),
):
    if settings.storage_backend != "google_drive":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Le stockage Google Drive n'est pas activé.",
        )
    if not drive_client.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Drive n'est pas entièrement configuré.",
        )
    run = _owned_run(session, run_id, context)
    target = session.get(Target, run.target_id)
    path = Path(run.screenshot_path or "")
    if target is None or not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="La capture locale nécessaire à l'envoi est absente.",
        )

    try:
        run.drive_status = "pending"
        run.drive_attempts = (run.drive_attempts or 0) + 1
        session.commit()
        placement = await asyncio.to_thread(
            drive_sync.upload_capture,
            path,
            target,
            run.capture_date,
            path.name,
        )
        drive_sync.mark_success(run, placement)
        session.add(
            RunLog(
                run_id=run.id,
                step="drive",
                level="INFO",
                message="Envoi manuel réussi : " + "/".join(placement.folders),
                attempt=run.drive_attempts,
            )
        )
        audit.record(
            session,
            "run.drive_retry",
            user=user,
            detail=f"run #{run.id} fichier {placement.upload.file_id}",
            ip=client_ip(request),
        )
        session.commit()
    except Exception as exc:  # noqa: BLE001
        run.drive_attempts = max(0, (run.drive_attempts or 1) - 1)
        drive_sync.mark_failure(run, exc)
        session.add(
            RunLog(
                run_id=run.id,
                step="drive",
                level="ERROR",
                message=f"Envoi manuel échoué : {run.drive_last_error}",
                attempt=run.drive_attempts,
            )
        )
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Envoi Drive impossible : {run.drive_last_error}",
        ) from None

    return DriveRetryOut(
        run_id=run.id,
        drive_status=run.drive_status,
        drive_file_link=run.drive_file_link,
        detail="Capture envoyée sur Google Drive.",
    )


@router.get("/{run_id}/lien", summary="Lien vers la capture stockee a distance")
def get_run_remote_link(
    run_id: int,
    context: tenancy.OrganizationContext = Depends(current_organization),
    session: Session = Depends(get_session),
):
    """Renvoie un lien de lecture vers la capture distante.

    Sur S3 le lien est signe et expire : il est donc regenere a chaque
    appel a partir de la cle enregistree, jamais lu depuis la base. Sur
    Drive le lien est permanent et rendu tel quel.
    """
    run = _owned_run(session, run_id, context)
    if run.drive_status != "uploaded" or not run.drive_file_id:
        raise HTTPException(
            status_code=404,
            detail="Aucune capture distante pour cette execution.",
        )
    if settings.storage_backend == "s3":
        return {
            "url": s3_client.signed_url(run.drive_file_id),
            "expire_dans_secondes": settings.s3_signed_url_ttl_seconds,
        }
    return {"url": run.drive_file_link, "expire_dans_secondes": None}


@router.get("/planche/{capture_date}.pdf", summary="Planche du jour en PDF")
async def planche_du_jour(
    capture_date: str,
    context: tenancy.OrganizationContext = Depends(current_organization),
    session: Session = Depends(get_session),
):
    """Genere la planche du jour et la renvoie.

    Le document est aussi ecrit sur le disque, et depose sur le stockage
    distant s'il est configure : telecharger et archiver sont le meme geste.
    On ne peut pas obtenir l'un sans l'autre, donc on ne peut pas croire
    qu'une planche est archivee alors qu'elle a seulement ete affichee.
    """
    from app.services import planche as planche_service

    fichier = await planche_service.exporter(
        session,
        capture_date,
        context.organization.id,
        getattr(context.organization, "name", ""),
    )
    return FileResponse(fichier, media_type="application/pdf", filename=fichier.name)
