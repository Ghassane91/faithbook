from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    MembershipRole,
    OrganizationInvitation,
    OrganizationMembership,
    User,
)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def create(
    session: Session,
    *,
    organization_id: int,
    email: str,
    role: MembershipRole,
    invited_by_user_id: int,
) -> tuple[OrganizationInvitation, str]:
    now = datetime.now(timezone.utc)
    normalized = email.strip().lower()
    for pending in session.scalars(
        select(OrganizationInvitation).where(
            OrganizationInvitation.organization_id == organization_id,
            OrganizationInvitation.email == normalized,
            OrganizationInvitation.accepted_at.is_(None),
            OrganizationInvitation.revoked_at.is_(None),
        )
    ).all():
        pending.revoked_at = now

    token = secrets.token_urlsafe(48)
    invitation = OrganizationInvitation(
        organization_id=organization_id,
        email=normalized,
        role=role,
        token_hash=_hash(token),
        invited_by_user_id=invited_by_user_id,
        expires_at=now + timedelta(days=settings.invitation_days),
    )
    session.add(invitation)
    session.commit()
    session.refresh(invitation)
    return invitation, token


def resolve(session: Session, token: str) -> OrganizationInvitation | None:
    if not token:
        return None
    invitation = session.scalars(
        select(OrganizationInvitation).where(
            OrganizationInvitation.token_hash == _hash(token)
        )
    ).first()
    if invitation is None or invitation.accepted_at or invitation.revoked_at:
        return None
    expires = invitation.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= datetime.now(timezone.utc):
        return None
    return invitation


def accept(
    session: Session,
    invitation: OrganizationInvitation,
    user: User,
) -> OrganizationMembership:
    membership = session.scalars(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == invitation.organization_id,
            OrganizationMembership.user_id == user.id,
        )
    ).first()
    if membership is None:
        membership = OrganizationMembership(
            organization_id=invitation.organization_id,
            user_id=user.id,
            role=invitation.role,
        )
        session.add(membership)
    invitation.accepted_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(membership)
    return membership
