from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.config import settings
from app.database import get_session
from app.models import User
from app.schemas import (
    ForgotPasswordIn,
    LoginIn,
    PasswordChangeIn,
    ResetPasswordIn,
    UserOut,
)
from app.services import auth, mailer

router = APIRouter(prefix="/api/auth", tags=["Authentification"])


def _pose_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=auth.COOKIE_NAME,
        value=token,
        httponly=True,  # inaccessible au JavaScript : protege d'un vol par XSS
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.session_hours * 3600,
        path="/",
    )


@router.post("/login", response_model=UserOut, summary="Se connecter")
def login(
    payload: LoginIn,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
):
    email = payload.email.strip().lower()
    ip = request.client.host if request.client else "?"
    cle = f"{ip}:{email}"

    if auth.trop_de_tentatives(cle):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Trop de tentatives. Réessayez dans quelques minutes.",
        )

    user = session.scalars(select(User).where(User.email == email)).first()
    # Message identique dans les deux cas : ne pas reveler quels comptes existent.
    if user is None or not user.is_active or not auth.verify_password(payload.password, user.password_hash):
        auth.noter_echec(cle)
        raise HTTPException(status_code=401, detail="Identifiant ou mot de passe incorrect.")

    auth.reinitialiser_tentatives(cle)
    token, _ = auth.create_session(session, user, request.headers.get("user-agent"), ip)
    _pose_cookie(response, token)
    return UserOut.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Se déconnecter")
def logout(request: Request, response: Response, session: Session = Depends(get_session)):
    auth.revoke_session(session, request.cookies.get(auth.COOKIE_NAME))
    response.delete_cookie(auth.COOKIE_NAME, path="/")


@router.get("/me", response_model=UserOut, summary="Compte connecté")
def me(user: User = Depends(current_user)):
    return UserOut.model_validate(user)


@router.post("/password", response_model=UserOut, summary="Changer son mot de passe")
def change_password(
    payload: PasswordChangeIn,
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    if not auth.verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Mot de passe actuel incorrect.")

    probleme = auth.password_problem(payload.new_password)
    if probleme:
        raise HTTPException(status_code=422, detail=probleme)
    if payload.new_password == payload.current_password:
        raise HTTPException(status_code=422, detail="Le nouveau mot de passe doit être différent.")

    frais = session.get(User, user.id)
    assert frais is not None
    frais.password_hash = auth.hash_password(payload.new_password)
    frais.must_change_password = False
    session.commit()

    # Toutes les autres sessions tombent : un mot de passe change doit
    # deconnecter les appareils deja ouverts.
    auth.revoke_all_sessions(session, frais.id)
    token, _ = auth.create_session(
        session, frais, request.headers.get("user-agent"), request.client.host if request.client else None
    )
    _pose_cookie(response, token)
    return UserOut.model_validate(frais)


# --- Mot de passe oublié -------------------------------------------------
_MESSAGE_NEUTRE = (
    "Si un compte correspond à cette adresse, un lien de réinitialisation vient "
    "d'être envoyé. Vérifiez votre boîte mail."
)


@router.post("/forgot", summary="Demander un lien de réinitialisation")
def forgot_password(
    payload: ForgotPasswordIn, request: Request, session: Session = Depends(get_session)
):
    email = payload.email.strip().lower()
    ip = request.client.host if request.client else "?"

    # Limitation : empeche de sonder des adresses ou de spammer une boite.
    cle = f"forgot:{ip}"
    if auth.trop_de_tentatives(cle):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Trop de demandes. Réessayez dans quelques minutes.",
        )
    auth.noter_echec(cle)

    user = session.scalars(select(User).where(User.email == email)).first()
    # Reponse identique que le compte existe ou non : on ne revele rien.
    if user is not None and user.is_active:
        token = auth.create_reset_token(session, user)
        lien = f"{settings.public_url.rstrip('/')}/?reset_token={token}"
        minutes = settings.reset_token_minutes
        corps = (
            f"Bonjour,\n\n"
            f"Une réinitialisation du mot de passe FaithBook a été demandée pour "
            f"{user.email}.\n\n"
            f"Ouvrez ce lien pour choisir un nouveau mot de passe "
            f"(valable {minutes} minutes) :\n\n{lien}\n\n"
            f"Si vous n'êtes pas à l'origine de cette demande, ignorez ce message : "
            f"votre mot de passe reste inchangé.\n"
        )
        mailer.send_email(user.email, "FaithBook — réinitialisation du mot de passe", corps)

    return {"detail": _MESSAGE_NEUTRE}


@router.post("/reset", summary="Réinitialiser le mot de passe via un lien")
def reset_password(
    payload: ResetPasswordIn, request: Request, session: Session = Depends(get_session)
):
    probleme = auth.password_problem(payload.new_password)
    if probleme:
        raise HTTPException(status_code=422, detail=probleme)

    user = auth.consume_reset_token(session, payload.token, payload.new_password)
    if user is None:
        raise HTTPException(
            status_code=400,
            detail="Lien invalide ou expiré. Demandez-en un nouveau.",
        )
    return {"detail": "Mot de passe réinitialisé. Vous pouvez maintenant vous connecter."}
