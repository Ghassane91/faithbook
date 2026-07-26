from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_organization, current_user, organization_admin
from app.config import settings
from app.database import get_session
from app.models import (
    MembershipRole,
    Organization,
    OrganizationInvitation,
    OrganizationMembership,
    User,
)
from app.schemas import (
    OrganizationCreate,
    OrganizationInvitationCreate,
    OrganizationInvitationOut,
    OrganizationMemberAdd,
    OrganizationMemberOut,
    OrganizationMemberUpdate,
    OrganizationOut,
    OrganizationUsageOut,
    QuotaMetricOut,
)
from app.services import audit, invitations, mailer, quotas, tenancy
from app.services.request_ip import client_ip

router = APIRouter(
    prefix="/api/organizations",
    tags=["Organisations"],
    dependencies=[Depends(current_user)],
)


def _out(organization: Organization, membership: OrganizationMembership) -> OrganizationOut:
    return OrganizationOut(
        id=organization.id,
        name=organization.name,
        slug=organization.slug,
        role=membership.role,
        created_at=organization.created_at,
        quota_accounts=organization.quota_accounts,
        quota_targets=organization.quota_targets,
        quota_daily_captures=organization.quota_daily_captures,
        quota_storage_bytes=organization.quota_storage_bytes,
        retention_days=organization.retention_days,
    )


def _metric(metric: quotas.UsageMetric) -> QuotaMetricOut:
    return QuotaMetricOut(
        used=metric.used,
        limit=metric.limit,
        remaining=metric.remaining,
        percent=metric.percent,
        unlimited=metric.unlimited,
    )


@router.get("", response_model=list[OrganizationOut])
def list_organizations(
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    tenancy.ensure_user_organization(session, user)
    memberships = session.scalars(
        select(OrganizationMembership)
        .where(OrganizationMembership.user_id == user.id)
        .order_by(OrganizationMembership.id)
    ).all()
    return [
        _out(session.get(Organization, membership.organization_id), membership)
        for membership in memberships
    ]


@router.post("", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED)
def create_organization(
    payload: OrganizationCreate,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    context = tenancy.create_organization(session, user, payload.name)
    audit.record(
        session,
        "organization.create",
        user=user,
        detail=f"organisation #{context.organization.id} {context.organization.name}",
        ip=client_ip(request),
    )
    return _out(context.organization, context.membership)


@router.get("/current", response_model=OrganizationOut)
def current(context: tenancy.OrganizationContext = Depends(current_organization)):
    return _out(context.organization, context.membership)


@router.get(
    "/current/usage",
    response_model=OrganizationUsageOut,
    summary="Consommation et quotas de l'organisation active",
)
def current_usage(
    context: tenancy.OrganizationContext = Depends(current_organization),
    session: Session = Depends(get_session),
):
    usage = quotas.organization_usage(session, context.organization.id)
    return OrganizationUsageOut(
        organization_id=usage.organization_id,
        billing_date=usage.billing_date,
        accounts=_metric(usage.accounts),
        targets=_metric(usage.targets),
        daily_captures=_metric(usage.daily_captures),
        storage_bytes=_metric(usage.storage_bytes),
        retention_days=usage.retention_days,
    )


@router.get("/current/members", response_model=list[OrganizationMemberOut])
def list_members(
    context: tenancy.OrganizationContext = Depends(organization_admin),
    session: Session = Depends(get_session),
):
    memberships = session.scalars(
        select(OrganizationMembership)
        .where(OrganizationMembership.organization_id == context.organization.id)
        .order_by(OrganizationMembership.id)
    ).all()
    return [
        OrganizationMemberOut(
            membership_id=membership.id,
            user_id=membership.user_id,
            email=session.get(User, membership.user_id).email,
            role=membership.role,
            created_at=membership.created_at,
        )
        for membership in memberships
    ]


@router.post(
    "/current/members",
    response_model=OrganizationMemberOut,
    status_code=status.HTTP_201_CREATED,
)
def add_member(
    payload: OrganizationMemberAdd,
    request: Request,
    context: tenancy.OrganizationContext = Depends(organization_admin),
    session: Session = Depends(get_session),
):
    email = payload.email.strip().lower()
    user = session.scalars(select(User).where(User.email == email)).first()
    if user is None:
        raise HTTPException(
            status_code=404,
            detail="Utilisateur introuvable. Envoyez plutôt une invitation par e-mail.",
        )
    existing = session.scalars(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == context.organization.id,
            OrganizationMembership.user_id == user.id,
        )
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Utilisateur déjà membre.")
    if payload.role == MembershipRole.owner:
        raise HTTPException(status_code=422, detail="Un second propriétaire n'est pas autorisé.")
    membership = OrganizationMembership(
        organization_id=context.organization.id,
        user_id=user.id,
        role=payload.role,
    )
    session.add(membership)
    session.commit()
    session.refresh(membership)
    audit.record(
        session,
        "organization.member_add",
        user=context.user,
        detail=f"organisation #{context.organization.id} utilisateur={email} rôle={payload.role.value}",
        ip=client_ip(request),
    )
    return OrganizationMemberOut(
        membership_id=membership.id,
        user_id=user.id,
        email=user.email,
        role=membership.role,
        created_at=membership.created_at,
    )


@router.patch("/current/members/{membership_id}", response_model=OrganizationMemberOut)
def update_member(
    membership_id: int,
    payload: OrganizationMemberUpdate,
    request: Request,
    context: tenancy.OrganizationContext = Depends(organization_admin),
    session: Session = Depends(get_session),
):
    membership = session.get(OrganizationMembership, membership_id)
    if membership is None or membership.organization_id != context.organization.id:
        raise HTTPException(status_code=404, detail="Membre introuvable.")
    if membership.role == MembershipRole.owner or payload.role == MembershipRole.owner:
        raise HTTPException(status_code=422, detail="Le rôle propriétaire ne peut pas être modifié.")
    membership.role = payload.role
    session.commit()
    user = session.get(User, membership.user_id)
    audit.record(
        session,
        "organization.member_update",
        user=context.user,
        detail=(
            f"organisation #{context.organization.id} utilisateur={user.email} "
            f"rôle={payload.role.value}"
        ),
        ip=client_ip(request),
    )
    return OrganizationMemberOut(
        membership_id=membership.id,
        user_id=user.id,
        email=user.email,
        role=membership.role,
        created_at=membership.created_at,
    )


@router.delete(
    "/current/members/{membership_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_member(
    membership_id: int,
    request: Request,
    context: tenancy.OrganizationContext = Depends(organization_admin),
    session: Session = Depends(get_session),
):
    membership = session.get(OrganizationMembership, membership_id)
    if membership is None or membership.organization_id != context.organization.id:
        raise HTTPException(status_code=404, detail="Membre introuvable.")
    if membership.role == MembershipRole.owner:
        raise HTTPException(status_code=422, detail="Le propriétaire ne peut pas être supprimé.")
    removed_user = session.get(User, membership.user_id)
    audit.record(
        session,
        "organization.member_remove",
        user=context.user,
        detail=f"organisation #{context.organization.id} utilisateur={removed_user.email}",
        ip=client_ip(request),
    )
    session.delete(membership)
    session.commit()


def _invitation_out(
    invitation: OrganizationInvitation,
    *,
    delivery: str | None = None,
    invite_url: str | None = None,
) -> OrganizationInvitationOut:
    return OrganizationInvitationOut(
        id=invitation.id,
        email=invitation.email,
        role=invitation.role,
        created_at=invitation.created_at,
        expires_at=invitation.expires_at,
        accepted_at=invitation.accepted_at,
        revoked_at=invitation.revoked_at,
        delivery=delivery,
        invite_url=invite_url,
    )


@router.get(
    "/current/invitations",
    response_model=list[OrganizationInvitationOut],
)
def list_invitations(
    context: tenancy.OrganizationContext = Depends(organization_admin),
    session: Session = Depends(get_session),
):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = session.scalars(
        select(OrganizationInvitation)
        .where(
            OrganizationInvitation.organization_id == context.organization.id,
            OrganizationInvitation.accepted_at.is_(None),
            OrganizationInvitation.revoked_at.is_(None),
            OrganizationInvitation.expires_at > now,
        )
        .order_by(OrganizationInvitation.id.desc())
    ).all()
    return [_invitation_out(row) for row in rows]


@router.post(
    "/current/invitations",
    response_model=OrganizationInvitationOut,
    status_code=status.HTTP_201_CREATED,
)
def create_invitation(
    payload: OrganizationInvitationCreate,
    request: Request,
    context: tenancy.OrganizationContext = Depends(organization_admin),
    session: Session = Depends(get_session),
):
    if payload.role == MembershipRole.owner:
        raise HTTPException(
            status_code=422,
            detail="Le rôle propriétaire ne peut pas être attribué par invitation.",
        )
    email = payload.email.strip().lower()
    existing_user = session.scalars(select(User).where(User.email == email)).first()
    if existing_user is not None:
        existing_member = session.scalars(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == context.organization.id,
                OrganizationMembership.user_id == existing_user.id,
            )
        ).first()
        if existing_member is not None:
            raise HTTPException(status_code=409, detail="Utilisateur déjà membre.")

    invitation, token = invitations.create(
        session,
        organization_id=context.organization.id,
        email=email,
        role=payload.role,
        invited_by_user_id=context.user.id,
    )
    invite_url = f"{settings.public_url.rstrip('/')}/?invite_token={token}"
    body = (
        f"Bonjour,\n\n"
        f"Vous êtes invité à rejoindre l'organisation « {context.organization.name} » "
        f"sur FaithBook avec le rôle {payload.role.value}.\n\n"
        f"Ouvrez ce lien dans les {settings.invitation_days} jours :\n\n"
        f"{invite_url}\n\n"
        f"Si vous n'attendiez pas cette invitation, ignorez ce message.\n"
    )
    sent = mailer.send_email(
        email,
        f"FaithBook — invitation à {context.organization.name}",
        body,
    )
    audit.record(
        session,
        "organization.invitation_create",
        user=context.user,
        detail=(
            f"organisation #{context.organization.id} email={email} "
            f"rôle={payload.role.value}"
        ),
        ip=client_ip(request),
    )
    return _invitation_out(
        invitation,
        delivery="sent" if sent else "logged",
        invite_url=None if sent else invite_url,
    )


@router.delete(
    "/current/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_invitation(
    invitation_id: int,
    request: Request,
    context: tenancy.OrganizationContext = Depends(organization_admin),
    session: Session = Depends(get_session),
):
    invitation = session.get(OrganizationInvitation, invitation_id)
    if (
        invitation is None
        or invitation.organization_id != context.organization.id
        or invitation.accepted_at is not None
    ):
        raise HTTPException(status_code=404, detail="Invitation introuvable.")
    invitation.revoked_at = datetime.now(timezone.utc)
    session.commit()
    audit.record(
        session,
        "organization.invitation_revoke",
        user=context.user,
        detail=f"organisation #{context.organization.id} email={invitation.email}",
        ip=client_ip(request),
    )
