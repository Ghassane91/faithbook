from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.database import get_session
from app.models import Run, Target, TriggerType
from app.scheduler import next_run_for, schedule_target, unschedule_target
from app.schemas import (
    RunSummary,
    SessionIn,
    SessionStatusOut,
    TargetCreate,
    TargetOut,
    TargetUpdate,
    TriggerRunResponse,
)
from app.services import session_state
from app.services.runner import trigger_target

router = APIRouter(prefix="/api/targets", tags=["Cibles"], dependencies=[Depends(current_user)])


def _to_out(session: Session, target: Target) -> TargetOut:
    last = session.scalars(
        select(Run).where(Run.target_id == target.id).order_by(Run.id.desc()).limit(1)
    ).first()
    out = TargetOut.model_validate(target)
    out.next_run_at = next_run_for(target.id)
    out.last_run = RunSummary.model_validate(last) if last else None
    has_session, expires, _, _ = session_state.describe(
        target.storage_state_json, target.session_profile
    )
    out.has_session = has_session
    out.session_expires_at = expires
    return out


@router.get("", response_model=list[TargetOut], summary="Lister les cibles")
def list_targets(
    enabled: bool | None = Query(default=None, description="Filtrer par etat actif"),
    session: Session = Depends(get_session),
):
    stmt = select(Target).order_by(Target.id)
    if enabled is not None:
        stmt = stmt.where(Target.enabled.is_(enabled))
    return [_to_out(session, t) for t in session.scalars(stmt).all()]


@router.post(
    "", response_model=TargetOut, status_code=status.HTTP_201_CREATED, summary="Creer une cible"
)
def create_target(payload: TargetCreate, session: Session = Depends(get_session)):
    target = Target(**payload.model_dump())
    session.add(target)
    session.commit()
    session.refresh(target)
    schedule_target(target)
    return _to_out(session, target)


@router.get("/{target_id}", response_model=TargetOut, summary="Detail d'une cible")
def get_target(target_id: int, session: Session = Depends(get_session)):
    target = session.get(Target, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Cible introuvable")
    return _to_out(session, target)


@router.patch("/{target_id}", response_model=TargetOut, summary="Modifier une cible")
def update_target(
    target_id: int, payload: TargetUpdate, session: Session = Depends(get_session)
):
    target = session.get(Target, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Cible introuvable")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(target, field, value)

    if target.enabled and not (target.run_time or target.cron_expression):
        raise HTTPException(
            status_code=422, detail="Une cible active doit avoir run_time ou cron_expression"
        )

    session.commit()
    session.refresh(target)
    schedule_target(target)
    return _to_out(session, target)


@router.delete(
    "/{target_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Supprimer une cible"
)
def delete_target(target_id: int, session: Session = Depends(get_session)):
    target = session.get(Target, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Cible introuvable")
    unschedule_target(target_id)
    session.delete(target)
    session.commit()


@router.post(
    "/{target_id}/run",
    response_model=TriggerRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Lancer une capture manuellement",
)
async def run_now(
    target_id: int,
    force: bool = Query(
        default=False, description="Ignorer la deduplication et forcer une nouvelle capture"
    ),
):
    """Declenche immediatement une capture, sans attendre l'horaire planifie."""
    try:
        run_id, run_status, detail = await trigger_target(
            target_id, TriggerType.manual, force=force
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="Cible introuvable") from None
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return TriggerRunResponse(run_id=run_id, status=run_status, detail=detail)


@router.put(
    "/{target_id}/session",
    response_model=SessionStatusOut,
    summary="Enregistrer la session (cookies) d'une cible",
)
def set_session(target_id: int, payload: SessionIn, session: Session = Depends(get_session)):
    """Enregistre un `storage_state` Playwright produit par `scripts/login_session.py`.

    Aucun identifiant n'est stocke : uniquement les cookies issus d'une connexion
    que vous avez effectuee vous-meme dans un navigateur.
    """
    import json

    target = session.get(Target, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Cible introuvable")
    target.storage_state_json = json.dumps(payload.storage_state)
    session.commit()
    return _session_status(target)


@router.get(
    "/{target_id}/session",
    response_model=SessionStatusOut,
    summary="Etat de la session (sans exposer les cookies)",
)
def get_session_status(target_id: int, session: Session = Depends(get_session)):
    target = session.get(Target, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Cible introuvable")
    return _session_status(target)


@router.delete(
    "/{target_id}/session",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer la session enregistree",
)
def delete_session(target_id: int, session: Session = Depends(get_session)):
    target = session.get(Target, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Cible introuvable")
    target.storage_state_json = None
    session.commit()


def _session_status(target: Target) -> SessionStatusOut:
    has_session, expires, expired, detail = session_state.describe(
        target.storage_state_json, target.session_profile
    )
    count, _ = session_state.session_expiry(target.storage_state_json)
    return SessionStatusOut(
        target_id=target.id,
        has_session=has_session,
        session_profile=target.session_profile,
        cookie_count=count,
        expires_at=expires,
        expired=expired,
        detail=detail,
    )


@router.get(
    "/{target_id}/runs", response_model=list[RunSummary], summary="Historique d'une cible"
)
def target_runs(
    target_id: int,
    limit: int = Query(default=50, ge=1, le=500),
    session: Session = Depends(get_session),
):
    if session.get(Target, target_id) is None:
        raise HTTPException(status_code=404, detail="Cible introuvable")
    runs = session.scalars(
        select(Run).where(Run.target_id == target_id).order_by(Run.id.desc()).limit(limit)
    ).all()
    return [RunSummary.model_validate(r) for r in runs]
