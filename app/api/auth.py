from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.config import settings
from app.database import get_session
from app.models import Organization, User
from app.schemas import (
    ForgotPasswordIn,
    InvitationAcceptIn,
    InvitationPreviewOut,
    LoginIn,
    PasswordChangeIn,
    ResetPasswordIn,
    UserOut,
)
from app.services import audit, auth, invitations, mailer
from app.services.request_ip import client_ip

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
    ip = client_ip(request) or "?"
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
        # `email` est un identifiant, jamais un secret : voir la regle de audit.record.
        audit.record(session, "auth.login_failed", user=None, detail=f"email={email}", ip=ip)
        raise HTTPException(status_code=401, detail="Identifiant ou mot de passe incorrect.")

    auth.reinitialiser_tentatives(cle)
    token, _ = auth.create_session(session, user, request.headers.get("user-agent"), ip)
    _pose_cookie(response, token)
    audit.record(session, "auth.login", user=user, ip=ip)
    return UserOut.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Se déconnecter")
def logout(request: Request, response: Response, session: Session = Depends(get_session)):
    token = request.cookies.get(auth.COOKIE_NAME)
    # Resout l'utilisateur AVANT de revoquer : apres, le jeton n'identifie plus personne.
    user = auth.resolve_session(session, token)
    auth.revoke_session(session, token)
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    if user is not None:
        audit.record(
            session, "auth.logout", user=user, ip=client_ip(request)
        )


@router.get("/check", include_in_schema=False, status_code=status.HTTP_204_NO_CONTENT)
def check(user: User = Depends(current_user)):
    """Verifie une session valide (ou une cle API) : utilise par nginx pour
    proteger /docs, /redoc et /openapi.json derriere une connexion."""


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
        session, frais, request.headers.get("user-agent"), client_ip(request)
    )
    _pose_cookie(response, token)
    audit.record(
        session, "auth.password_change", user=frais,
        ip=client_ip(request),
    )
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
    ip = client_ip(request) or "?"

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
        audit.record(session, "auth.password_forgot", user=user, ip=ip)
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
    audit.record(
        session, "auth.password_reset", user=user,
        ip=client_ip(request),
    )
    return {"detail": "Mot de passe réinitialisé. Vous pouvez maintenant vous connecter."}


# --- Invitations d'organisation -----------------------------------------
@router.get(
    "/invitations/{token}",
    response_model=InvitationPreviewOut,
    summary="Vérifier une invitation",
)
def preview_invitation(token: str, session: Session = Depends(get_session)):
    invitation = invitations.resolve(session, token)
    if invitation is None:
        raise HTTPException(status_code=404, detail="Invitation invalide ou expirée.")
    organization = session.get(Organization, invitation.organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Invitation invalide ou expirée.")
    user_exists = (
        session.scalars(select(User).where(User.email == invitation.email)).first()
        is not None
    )
    return InvitationPreviewOut(
        organization_name=organization.name,
        email=invitation.email,
        role=invitation.role,
        expires_at=invitation.expires_at,
        user_exists=user_exists,
    )


@router.post(
    "/invitations/accept",
    response_model=UserOut,
    summary="Accepter une invitation",
)
def accept_invitation(
    payload: InvitationAcceptIn,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
):
    invitation = invitations.resolve(session, payload.token)
    if invitation is None:
        raise HTTPException(status_code=400, detail="Invitation invalide ou expirée.")

    ip = client_ip(request) or "?"
    attempt_key = f"invite:{ip}:{invitation.token_hash[:16]}"
    if auth.trop_de_tentatives(attempt_key):
        raise HTTPException(
            status_code=429,
            detail="Trop de tentatives. Réessayez dans quelques minutes.",
        )

    user = session.scalars(
        select(User).where(User.email == invitation.email)
    ).first()
    if user is not None:
        if not user.is_active or not auth.verify_password(
            payload.password, user.password_hash
        ):
            auth.noter_echec(attempt_key)
            raise HTTPException(status_code=401, detail="Mot de passe incorrect.")
    else:
        problem = auth.password_problem(payload.password)
        if problem:
            raise HTTPException(status_code=422, detail=problem)
        user = User(
            email=invitation.email,
            password_hash=auth.hash_password(payload.password),
            must_change_password=False,
        )
        session.add(user)
        session.flush()

    invitations.accept(session, invitation, user)
    auth.reinitialiser_tentatives(attempt_key)
    session_token, _ = auth.create_session(
        session, user, request.headers.get("user-agent"), ip
    )
    _pose_cookie(response, session_token)
    audit.record(
        session,
        "organization.invitation_accept",
        user=user,
        detail=f"organisation #{invitation.organization_id}",
        ip=ip,
    )
    return UserOut.model_validate(user)
