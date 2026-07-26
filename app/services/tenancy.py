from __future__ import annotations

import re
import secrets
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    Account,
    MembershipRole,
    Organization,
    OrganizationMembership,
    Target,
    User,
)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class OrganizationContext:
    user: User
    organization: Organization
    membership: OrganizationMembership


def _slug(name: str) -> str:
    base = _SLUG_RE.sub("-", name.lower()).strip("-")[:70] or "organisation"
    return f"{base}-{secrets.token_hex(3)}"


def create_organization(
    session: Session, user: User, name: str, *, commit: bool = True
) -> OrganizationContext:
    organization = Organization(
        name=name.strip(),
        slug=_slug(name),
        created_by_user_id=user.id,
        quota_accounts=max(0, settings.default_quota_accounts),
        quota_targets=max(0, settings.default_quota_targets),
        quota_daily_captures=max(0, settings.default_quota_daily_captures),
        quota_storage_bytes=max(0, settings.default_quota_storage_bytes),
        retention_days=max(0, settings.run_retention_days),
    )
    session.add(organization)
    session.flush()
    membership = OrganizationMembership(
        organization_id=organization.id,
        user_id=user.id,
        role=MembershipRole.owner,
    )
    session.add(membership)
    if commit:
        session.commit()
        session.refresh(organization)
        session.refresh(membership)
    return OrganizationContext(user, organization, membership)


def ensure_user_organization(session: Session, user: User) -> OrganizationContext:
    membership = session.scalars(
        select(OrganizationMembership)
        .where(OrganizationMembership.user_id == user.id)
        .order_by(OrganizationMembership.id)
        .limit(1)
    ).first()
    if membership is not None:
        organization = session.get(Organization, membership.organization_id)
        assert organization is not None
        return OrganizationContext(user, organization, membership)
    return create_organization(session, user, f"Espace de {user.email.split('@')[0]}")


def ensure_legacy_organizations(session: Session) -> None:
    """Crée un espace par utilisateur et rattache les données pré-Phase 2a."""
    users = session.scalars(select(User).order_by(User.id)).all()
    contexts = {u.id: ensure_user_organization(session, u) for u in users}
    fallback = next(iter(contexts.values()), None)

    for account in session.scalars(
        select(Account).where(Account.organization_id.is_(None))
    ).all():
        context = contexts.get(account.owner_id) or fallback
        if context:
            account.organization_id = context.organization.id

    account_orgs = {
        account.id: account.organization_id
        for account in session.scalars(select(Account)).all()
    }
    for target in session.scalars(
        select(Target).where(Target.organization_id.is_(None))
    ).all():
        target.organization_id = account_orgs.get(target.account_id) or (
            fallback.organization.id if fallback else None
        )
    session.commit()


def resolve_organization(
    session: Session, user: User, organization_id: int | None
) -> OrganizationContext | None:
    if organization_id is None:
        return ensure_user_organization(session, user)
    membership = session.scalars(
        select(OrganizationMembership).where(
            OrganizationMembership.user_id == user.id,
            OrganizationMembership.organization_id == organization_id,
        )
    ).first()
    if membership is None:
        return None
    organization = session.get(Organization, organization_id)
    if organization is None:
        return None
    return OrganizationContext(user, organization, membership)
