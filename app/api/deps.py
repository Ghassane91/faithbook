from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_session
from app.models import User
from app.services import auth


def current_user(
    request: Request,
    session: Session = Depends(get_session),
    x_api_key: str | None = Header(default=None),
) -> User:
    """Exige une session ouverte, ou la cle machine-a-machine.

    La cle API sert aux scripts (tests, integrations) et donne acces a l'API
    sans compte. Elle est desactivee tant qu'API_KEY est vide.
    """
    if settings.api_key and x_api_key == settings.api_key:
        return User(id=0, email="api-key", password_hash="", is_active=True)

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
