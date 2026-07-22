from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.database import get_session
from app.models import Run, RunStatus
from app.schemas import RunListOut, RunLogOut, RunOut, RunSummary
from app.services.capture import thumb_path

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
    session: Session = Depends(get_session),
):
    filters = []
    if target_id is not None:
        filters.append(Run.target_id == target_id)
    if status is not None:
        filters.append(Run.status == status)
    if capture_date is not None:
        filters.append(Run.capture_date == capture_date)

    total = session.scalar(select(func.count()).select_from(Run).where(*filters)) or 0
    rows = session.scalars(
        select(Run).where(*filters).order_by(Run.id.desc()).limit(limit).offset(offset)
    ).all()
    return RunListOut(total=total, items=[RunSummary.model_validate(r) for r in rows])


@router.get("/{run_id}", response_model=RunOut, summary="Detail d'une execution (avec logs)")
def get_run(run_id: int, session: Session = Depends(get_session)):
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Execution introuvable")
    return RunOut.model_validate(run)


@router.get("/{run_id}/logs", response_model=list[RunLogOut], summary="Logs d'une execution")
def get_run_logs(run_id: int, session: Session = Depends(get_session)):
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Execution introuvable")
    return [RunLogOut.model_validate(entry) for entry in run.logs]


@router.get(
    "/{run_id}/thumbnail",
    summary="Vignette de la capture (leger, pour les listes)",
    response_class=FileResponse,
)
def get_run_thumbnail(run_id: int, session: Session = Depends(get_session)):
    """Vignette JPEG. Retombe sur le PNG complet si elle n'existe pas encore."""
    run = session.get(Run, run_id)
    if run is None or not run.screenshot_path:
        raise HTTPException(status_code=404, detail="Aucune capture pour cette execution")
    original = Path(run.screenshot_path)
    vignette = thumb_path(original)
    if vignette.is_file():
        return FileResponse(vignette, media_type="image/jpeg")
    if original.is_file():
        return FileResponse(original, media_type="image/png")
    raise HTTPException(status_code=410, detail="Fichier de capture absent du disque")


@router.get("/{run_id}/screenshot", summary="Telecharger la capture", response_class=FileResponse)
def get_run_screenshot(run_id: int, session: Session = Depends(get_session)):
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Execution introuvable")
    if not run.screenshot_path:
        raise HTTPException(status_code=404, detail="Aucune capture pour cette execution")
    path = Path(run.screenshot_path)
    if not path.is_file():
        raise HTTPException(status_code=410, detail="Fichier de capture absent du disque")
    return FileResponse(path, media_type="image/png", filename=path.name)
