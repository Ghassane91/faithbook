from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.config import settings
from app.database import get_session
from app.models import Account, AccountStatus, Target, User, utcnow
from app.schemas import AccountCreate, AccountOut, LoginStatusOut, SessionTestOut
from app.services import audit, crypto, session_check
from app.services.capture import slugify
from app.services.login_browser import LoginBusy, login_manager

router = APIRouter(
    prefix="/api/accounts", tags=["Comptes connectés"], dependencies=[Depends(current_user)]
)

NOVNC_PATH = "/novnc/vnc.html?autoconnect=true&resize=remote&reconnect=true"
# Cookie qui porte le jeton noVNC : lu par nginx (auth_request) sur /novnc/ et
# /websockify, jamais par le JavaScript du frontend.
NOVNC_COOKIE = "faithbook_novnc"


def _pose_novnc_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=NOVNC_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.novnc_token_ttl_minutes * 60,
        path="/",
    )


def _owned(session: Session, account_id: int, user: User) -> Account:
    """Récupère un compte en vérifiant l'appartenance à l'utilisateur.

    Une session ne doit jamais être accessible à un autre utilisateur.
    """
    account = session.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Compte introuvable")
    if user.id and account.owner_id not in (None, user.id):
        raise HTTPException(status_code=403, detail="Ce compte appartient à un autre utilisateur.")
    return account


def _to_out(session: Session, account: Account) -> AccountOut:
    count = session.scalar(
        select(func.count()).select_from(Target).where(Target.account_id == account.id)
    )
    out = AccountOut.model_validate(account)
    out.has_session = bool(account.encrypted_state) or crypto.profile_exists(account.profile_slug)
    out.target_count = count or 0
    return out


@router.get("", response_model=list[AccountOut], summary="Lister les comptes connectés")
def list_accounts(user: User = Depends(current_user), session: Session = Depends(get_session)):
    stmt = select(Account).order_by(Account.id)
    if user.id:
        stmt = stmt.where((Account.owner_id == user.id) | (Account.owner_id.is_(None)))
    return [_to_out(session, a) for a in session.scalars(stmt).all()]


@router.post(
    "", response_model=AccountOut, status_code=status.HTTP_201_CREATED, summary="Créer un compte"
)
def create_account(
    payload: AccountCreate,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    slug = f"acct-{slugify(payload.name, 40)}-{secrets.token_hex(3)}"
    account = Account(
        name=payload.name,
        platform=payload.platform,
        profile_slug=slug,
        owner_id=user.id or None,
        status=AccountStatus.never,
    )
    session.add(account)
    session.commit()
    session.refresh(account)
    audit.record(
        session, "account.create", user=user, detail=f"compte #{account.id} {account.name}",
        ip=request.client.host if request.client else None,
    )
    return _to_out(session, account)


@router.delete(
    "/{account_id}", status_code=status.HTTP_204_NO_CONTENT,
    summary="Déconnecter et supprimer la session",
)
async def delete_account(
    account_id: int,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    account = _owned(session, account_id, user)
    # Ferme un login éventuellement en cours, puis efface le coffre chiffré.
    await login_manager.cancel(account_id)
    crypto.delete_vault(account.profile_slug)
    # Détache les cibles (ne pas les supprimer).
    for t in session.scalars(select(Target).where(Target.account_id == account_id)).all():
        t.account_id = None
    audit.record(
        session, "account.delete", user=user, detail=f"compte #{account_id} {account.name}",
        ip=request.client.host if request.client else None,
    )
    session.delete(account)
    session.commit()


# --- Connexion manuelle (noVNC) ------------------------------------------
@router.post(
    "/{account_id}/login/start", response_model=LoginStatusOut,
    summary="Ouvrir le navigateur de connexion manuelle",
)
async def login_start(
    account_id: int,
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    account = _owned(session, account_id, user)
    try:
        token = await login_manager.start(account_id, account.profile_slug, account.platform, user.id)
    except LoginBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Ouverture impossible : {exc}") from None

    # Le navigateur de connexion (noVNC) n'est accessible qu'avec ce jeton :
    # sans lui, /novnc/ et /websockify renvoient 403 (voir nginx.conf).
    _pose_novnc_cookie(response, token)

    audit.record(
        session, "account.login_start", user=user, detail=f"compte #{account_id}",
        ip=request.client.host if request.client else None,
    )
    return LoginStatusOut(
        active=True,
        account_id=account_id,
        platform=account.platform,
        novnc_path=NOVNC_PATH,
        detail="Connectez-vous dans le navigateur, validez la 2FA, puis cliquez « J'ai terminé ».",
    )


@router.get(
    "/{account_id}/login/status", response_model=LoginStatusOut,
    summary="État de la connexion manuelle en cours",
)
async def login_status(account_id: int, user: User = Depends(current_user)):
    probe = await login_manager.probe(account_id)
    return LoginStatusOut(
        active=probe.get("active", False),
        account_id=account_id,
        logged_in=probe.get("logged_in", False),
        current_url=probe.get("current_url"),
        novnc_path=NOVNC_PATH,
    )


@router.post(
    "/{account_id}/login/finish", response_model=SessionTestOut,
    summary="Valider et enregistrer la session",
)
async def login_finish(
    account_id: int,
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    account = _owned(session, account_id, user)
    try:
        result = await login_manager.finish(account_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    finally:
        # La connexion est terminee (succes ou echec) : le navigateur noVNC ne
        # doit plus etre atteignable.
        response.delete_cookie(NOVNC_COOKIE, path="/")

    if result["logged_in"]:
        account.encrypted_state = result["encrypted_state"]
        account.status = AccountStatus.connected
        account.last_verified_at = utcnow()
        account.last_error = None
        detail = "Compte connecté. La session est chiffrée et prête pour les captures."
    else:
        account.status = AccountStatus.error
        account.last_error = "Connexion non détectée : cookies de session absents."
        detail = "Connexion non détectée. Recommencez et vérifiez d'être bien connecté."
    session.commit()
    audit.record(
        session, "account.login_finish", user=user,
        detail=f"compte #{account_id} connecté={result['logged_in']}",
        ip=request.client.host if request.client else None,
    )
    return SessionTestOut(
        account_id=account_id, status=account.status,
        logged_in=result["logged_in"], final_url=None, detail=detail,
    )


@router.post(
    "/{account_id}/login/cancel", status_code=status.HTTP_204_NO_CONTENT,
    summary="Abandonner la connexion manuelle",
)
async def login_cancel(
    account_id: int,
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    await login_manager.cancel(account_id)
    response.delete_cookie(NOVNC_COOKIE, path="/")
    audit.record(
        session, "account.login_cancel", user=user, detail=f"compte #{account_id}",
        ip=request.client.host if request.client else None,
    )


# --- Autorisation noVNC (appelee par nginx via auth_request, jamais par le
# frontend) ------------------------------------------------------------------
@router.get(
    "/novnc/authorize", include_in_schema=False, status_code=status.HTTP_204_NO_CONTENT,
)
def novnc_authorize(request: Request, user: User = Depends(current_user)):
    """Verifie le jeton noVNC (cookie) avant que nginx ne relaie vers l'ecran.

    Ne journalise jamais le contenu du cookie : uniquement l'issue.
    """
    token = request.cookies.get(NOVNC_COOKIE)
    if not login_manager.authorize(token, user.id):
        raise HTTPException(status_code=403, detail="Acces noVNC refuse.")


# --- Test de session ------------------------------------------------------
@router.post(
    "/{account_id}/test", response_model=SessionTestOut, summary="Tester la session"
)
async def test_session(
    account_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    account = _owned(session, account_id, user)
    if login_manager.active_account_id == account_id:
        raise HTTPException(
            status_code=409, detail="Une connexion manuelle est en cours pour ce compte."
        )
    result = await session_check.check_account(account.profile_slug, account.platform)
    account.status = result["status"]
    account.last_verified_at = utcnow()
    account.last_error = result["detail"] if result["status"] == AccountStatus.error else None
    session.commit()
    return SessionTestOut(
        account_id=account_id,
        status=account.status,
        logged_in=result["logged_in"],
        final_url=result["final_url"],
        detail=result["detail"],
    )
