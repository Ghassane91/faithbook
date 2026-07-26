import secrets

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_session
from app.models import MembershipRole, User
from app.services import auth, tenancy


def current_user(
    request: Request,
    session: Session = Depends(get_session),
    x_api_key: str | None = Header(default=None),
) -> User:
    """Exige une session ouverte, ou la cle machine-a-machine liee a un compte.

    La cle API conserve l'acces aux comptes connectes et a noVNC, mais agit au
    nom d'un utilisateur reel : les memes controles de propriete s'appliquent.
    """
    if (
        settings.api_key
        and x_api_key
        and secrets.compare_digest(x_api_key, settings.api_key)
    ):
        email = (settings.api_key_user_email or settings.admin_email).strip().lower()
        user = session.scalars(select(User).where(User.email == email)).first()
        if user is None or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Clé API valide mais compte associé introuvable ou inactif.",
            )
        return user

    user = auth.resolve_session(session, request.cookies.get(auth.COOKIE_NAME))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Connexion requise.",
        )
    return user


def optional_user(
    request: Request,
    session: Session = Depends(get_session),
) -> User | None:
    return auth.resolve_session(session, request.cookies.get(auth.COOKIE_NAME))


def current_organization(
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
    x_organization_id: int | None = Header(default=None, alias="X-Organization-ID"),
) -> tenancy.OrganizationContext:
    organization_id = x_organization_id
    if organization_id is None:
        raw_cookie = request.cookies.get("faithbook_org")
        try:
            organization_id = int(raw_cookie) if raw_cookie else None
        except ValueError:
            organization_id = None
    context = tenancy.resolve_organization(session, user, organization_id)
    if context is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organisation inaccessible.",
        )
    return context


def organization_member(
    context: tenancy.OrganizationContext = Depends(current_organization),
) -> tenancy.OrganizationContext:
    """Autorise les membres qui peuvent modifier et lancer des captures."""
    if context.membership.role == MembershipRole.viewer:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Le rôle lecture seule ne peut pas effectuer cette action.",
        )
    return context


def organization_admin(
    context: tenancy.OrganizationContext = Depends(current_organization),
) -> tenancy.OrganizationContext:
    """Réserve les comptes connectés et l'administration aux admins."""
    if context.membership.role not in (MembershipRole.owner, MembershipRole.admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Rôle administrateur requis.",
        )
    return context
