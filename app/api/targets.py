from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import (
    current_organization,
    current_user,
    organization_admin,
    organization_member,
)
from app.database import get_session
from app.models import Account, Run, RunStatus, Target, TriggerType, User
from app.services.metrics import LABELS as METRIC_LABELS
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
from app.services import audit, crypto, quotas, session_state, tenancy
from app.services.runner import trigger_target
from app.services.ssrf import UrlRejected, check_url
from app.services.request_ip import client_ip

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
    context: tenancy.OrganizationContext = Depends(current_organization),
    session: Session = Depends(get_session),
):
    stmt = (
        select(Target)
        .where(Target.organization_id == context.organization.id)
        .order_by(Target.id)
    )
    if enabled is not None:
        stmt = stmt.where(Target.enabled.is_(enabled))
    return [_to_out(session, t) for t in session.scalars(stmt).all()]


def _check_target_url(url: str) -> None:
    try:
        check_url(url)
    except UrlRejected as exc:
        raise HTTPException(status_code=422, detail=f"URL refusee : {exc}") from None


def _owned_target(
    session: Session, target_id: int, context: tenancy.OrganizationContext
) -> Target:
    target = session.get(Target, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Cible introuvable")
    if target.organization_id != context.organization.id:
        raise HTTPException(status_code=403, detail="Cible d'une autre organisation.")
    return target


def _check_account(
    session: Session,
    account_id: int | None,
    context: tenancy.OrganizationContext,
) -> None:
    if account_id is None:
        return
    account = session.get(Account, account_id)
    if account is None or account.organization_id != context.organization.id:
        raise HTTPException(status_code=422, detail="Compte connecté inaccessible.")


@router.post(
    "", response_model=TargetOut, status_code=status.HTTP_201_CREATED, summary="Creer une cible"
)
def create_target(
    payload: TargetCreate,
    request: Request,
    user: User = Depends(current_user),
    context: tenancy.OrganizationContext = Depends(organization_member),
    session: Session = Depends(get_session),
):
    _check_target_url(payload.url)
    _check_account(session, payload.account_id, context)
    try:
        quotas.enforce_target_creation(session, context.organization.id)
    except quotas.QuotaExceeded as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    target = Target(
        **payload.model_dump(),
        organization_id=context.organization.id,
    )
    session.add(target)
    session.commit()
    session.refresh(target)
    schedule_target(target)
    audit.record(
        session, "target.create", user=user, detail=f"cible #{target.id} {target.name}",
        ip=client_ip(request),
    )
    return _to_out(session, target)


@router.get("/{target_id}", response_model=TargetOut, summary="Detail d'une cible")
def get_target(
    target_id: int,
    context: tenancy.OrganizationContext = Depends(current_organization),
    session: Session = Depends(get_session),
):
    target = _owned_target(session, target_id, context)
    return _to_out(session, target)


@router.patch("/{target_id}", response_model=TargetOut, summary="Modifier une cible")
def update_target(
    target_id: int,
    payload: TargetUpdate,
    request: Request,
    user: User = Depends(current_user),
    context: tenancy.OrganizationContext = Depends(organization_member),
    session: Session = Depends(get_session),
):
    target = _owned_target(session, target_id, context)

    changes = payload.model_dump(exclude_unset=True)
    if "url" in changes:
        _check_target_url(changes["url"])
    if "account_id" in changes:
        _check_account(session, changes["account_id"], context)
    for field, value in changes.items():
        setattr(target, field, value)

    if target.enabled and not (target.run_time or target.cron_expression):
        raise HTTPException(
            status_code=422, detail="Une cible active doit avoir run_time ou cron_expression"
        )

    session.commit()
    session.refresh(target)
    schedule_target(target)
    audit.record(
        session, "target.update", user=user, detail=f"cible #{target.id} {target.name}",
        ip=client_ip(request),
    )
    return _to_out(session, target)


@router.delete(
    "/{target_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Supprimer une cible"
)
def delete_target(
    target_id: int,
    request: Request,
    user: User = Depends(current_user),
    context: tenancy.OrganizationContext = Depends(organization_admin),
    session: Session = Depends(get_session),
):
    target = _owned_target(session, target_id, context)
    unschedule_target(target_id)
    audit.record(
        session, "target.delete", user=user, detail=f"cible #{target_id} {target.name}",
        ip=client_ip(request),
    )
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
    context: tenancy.OrganizationContext = Depends(organization_member),
    session: Session = Depends(get_session),
):
    """Declenche immediatement une capture, sans attendre l'horaire planifie."""
    _owned_target(session, target_id, context)
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
def set_session(
    target_id: int,
    payload: SessionIn,
    request: Request,
    user: User = Depends(current_user),
    context: tenancy.OrganizationContext = Depends(organization_admin),
    session: Session = Depends(get_session),
):
    """Enregistre un `storage_state` Playwright produit par `scripts/login_session.py`.

    Aucun identifiant n'est stocke : uniquement les cookies issus d'une connexion
    que vous avez effectuee vous-meme dans un navigateur. Chiffre au repos
    (Fernet), au meme titre que les sessions des comptes connectes.
    """
    target = _owned_target(session, target_id, context)
    target.storage_state_json = crypto.encrypt_text(json.dumps(payload.storage_state))
    session.commit()
    audit.record(
        session, "target.session_set", user=user, detail=f"cible #{target_id} {target.name}",
        ip=client_ip(request),
    )
    return _session_status(target)


@router.get(
    "/{target_id}/session",
    response_model=SessionStatusOut,
    summary="Etat de la session (sans exposer les cookies)",
)
def get_session_status(
    target_id: int,
    context: tenancy.OrganizationContext = Depends(current_organization),
    session: Session = Depends(get_session),
):
    target = _owned_target(session, target_id, context)
    return _session_status(target)


@router.delete(
    "/{target_id}/session",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer la session enregistree",
)
def delete_session(
    target_id: int,
    request: Request,
    user: User = Depends(current_user),
    context: tenancy.OrganizationContext = Depends(organization_admin),
    session: Session = Depends(get_session),
):
    target = _owned_target(session, target_id, context)
    target.storage_state_json = None
    session.commit()
    audit.record(
        session, "target.session_delete", user=user, detail=f"cible #{target_id} {target.name}",
        ip=client_ip(request),
    )


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
    context: tenancy.OrganizationContext = Depends(current_organization),
    session: Session = Depends(get_session),
):
    _owned_target(session, target_id, context)
    runs = session.scalars(
        select(Run).where(Run.target_id == target_id).order_by(Run.id.desc()).limit(limit)
    ).all()
    return [RunSummary.model_validate(r) for r in runs]


@router.get("/{target_id}/metrics", summary="Série temporelle des métriques (abonnés…)")
def target_metrics(
    target_id: int,
    context: tenancy.OrganizationContext = Depends(current_organization),
    session: Session = Depends(get_session),
):
    """Historique des métriques relevées : une entrée par capture réussie qui en
    contient (la dernière capture du jour prime). Prêt à tracer un graphique."""
    _owned_target(session, target_id, context)
    runs = session.scalars(
        select(Run)
        .where(Run.target_id == target_id, Run.status == RunStatus.success, Run.metrics.is_not(None))
        .order_by(Run.id.asc())
    ).all()

    par_jour: dict[str, dict] = {}
    cles: set[str] = set()
    for run in runs:
        try:
            data = json.loads(run.metrics)
        except (TypeError, ValueError):
            continue
        if not isinstance(data, dict) or not data:
            continue
        cles.update(data.keys())
        par_jour[run.capture_date] = {"date": run.capture_date, **data}

    points = [par_jour[d] for d in sorted(par_jour)]
    return {"keys": sorted(cles), "points": points, "labels": METRIC_LABELS}
