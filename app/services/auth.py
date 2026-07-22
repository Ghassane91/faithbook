from __future__ import annotations

import hashlib
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone

import bcrypt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AuthSession, PasswordResetToken, User, utcnow

logger = logging.getLogger(__name__)

COOKIE_NAME = "planche_session"
MIN_PASSWORD_LEN = 10


# --- Mots de passe -------------------------------------------------------
def hash_password(clair: str) -> str:
    """bcrypt sur l'empreinte SHA-256 du mot de passe.

    bcrypt ignore silencieusement tout ce qui depasse 72 octets : passer par
    un SHA-256 garantit qu'un mot de passe long reste integralement pris en
    compte, quelle que soit sa taille.
    """
    empreinte = hashlib.sha256(clair.encode("utf-8")).hexdigest().encode("ascii")
    return bcrypt.hashpw(empreinte, bcrypt.gensalt()).decode("ascii")


def verify_password(clair: str, hache: str) -> bool:
    empreinte = hashlib.sha256(clair.encode("utf-8")).hexdigest().encode("ascii")
    try:
        return bcrypt.checkpw(empreinte, hache.encode("ascii"))
    except (ValueError, TypeError):
        return False


def password_problem(mdp: str) -> str | None:
    """Retourne un message si le mot de passe est refuse, sinon None."""
    if len(mdp) < MIN_PASSWORD_LEN:
        return f"Le mot de passe doit faire au moins {MIN_PASSWORD_LEN} caracteres."
    if mdp.isdigit() or mdp.isalpha():
        return "Mélangez lettres et chiffres."
    return None


# --- Limitation des tentatives ------------------------------------------
# Simple compteur en memoire : suffisant pour une instance unique et sans
# dependance supplementaire. A remplacer par Redis le jour du multi-instance.
_ECHECS: dict[str, list[float]] = {}
MAX_ECHECS = 5
FENETRE_SECONDES = 300


def trop_de_tentatives(cle: str) -> bool:
    maintenant = time.time()
    recents = [t for t in _ECHECS.get(cle, []) if maintenant - t < FENETRE_SECONDES]
    _ECHECS[cle] = recents
    return len(recents) >= MAX_ECHECS


def noter_echec(cle: str) -> None:
    _ECHECS.setdefault(cle, []).append(time.time())


def reinitialiser_tentatives(cle: str) -> None:
    _ECHECS.pop(cle, None)


# --- Sessions ------------------------------------------------------------
def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def create_session(
    session: Session, user: User, user_agent: str | None, ip: str | None
) -> tuple[str, datetime]:
    """Cree une session et retourne (jeton en clair, expiration).

    Le jeton en clair n'est jamais stocke : il ne sortira que dans le cookie.
    """
    token = secrets.token_urlsafe(48)
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.session_hours)
    session.add(
        AuthSession(
            user_id=user.id,
            token_hash=_hash_token(token),
            expires_at=expire,
            user_agent=(user_agent or "")[:300] or None,
            ip=(ip or "")[:60] or None,
        )
    )
    user.last_login_at = utcnow()
    session.commit()
    return token, expire


def resolve_session(session: Session, token: str | None) -> User | None:
    if not token:
        return None
    auth = session.scalars(
        select(AuthSession).where(AuthSession.token_hash == _hash_token(token))
    ).first()
    if auth is None:
        return None

    expire = auth.expires_at
    if expire.tzinfo is None:
        expire = expire.replace(tzinfo=timezone.utc)
    if expire <= datetime.now(timezone.utc):
        session.delete(auth)
        session.commit()
        return None

    user = session.get(User, auth.user_id)
    return user if user and user.is_active else None


def revoke_session(session: Session, token: str | None) -> None:
    if not token:
        return
    auth = session.scalars(
        select(AuthSession).where(AuthSession.token_hash == _hash_token(token))
    ).first()
    if auth:
        session.delete(auth)
        session.commit()


def revoke_all_sessions(session: Session, user_id: int) -> None:
    for auth in session.scalars(select(AuthSession).where(AuthSession.user_id == user_id)).all():
        session.delete(auth)
    session.commit()


def purge_expired_sessions(session: Session) -> int:
    maintenant = datetime.now(timezone.utc).replace(tzinfo=None)
    expirees = session.scalars(select(AuthSession).where(AuthSession.expires_at < maintenant)).all()
    for auth in expirees:
        session.delete(auth)
    if expirees:
        session.commit()
    return len(expirees)


# --- Reinitialisation de mot de passe -----------------------------------
def create_reset_token(session: Session, user: User) -> str:
    """Cree un jeton de reinitialisation et retourne sa valeur en clair.

    Les jetons non utilises precedents sont invalides : un seul lien vivant a la
    fois. Seule l'empreinte est stockee.
    """
    now = datetime.now(timezone.utc)
    # Invalide les anciens jetons encore valides de cet utilisateur.
    for ancien in session.scalars(
        select(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
        )
    ).all():
        ancien.used_at = now

    token = secrets.token_urlsafe(48)
    session.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=_hash_token(token),
            expires_at=now + timedelta(minutes=settings.reset_token_minutes),
        )
    )
    session.commit()
    return token


def consume_reset_token(session: Session, token: str, new_password: str) -> User | None:
    """Valide un jeton et applique le nouveau mot de passe. None si invalide.

    Un jeton expire, deja utilise ou inconnu est refuse. En cas de succes, le
    jeton est marque comme utilise et toutes les sessions ouvertes tombent.
    """
    if not token:
        return None
    entry = session.scalars(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == _hash_token(token))
    ).first()
    if entry is None or entry.used_at is not None:
        return None

    expire = entry.expires_at
    if expire.tzinfo is None:
        expire = expire.replace(tzinfo=timezone.utc)
    if expire <= datetime.now(timezone.utc):
        return None

    user = session.get(User, entry.user_id)
    if user is None or not user.is_active:
        return None

    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    entry.used_at = datetime.now(timezone.utc)
    session.commit()
    # Un mot de passe reinitialise doit deconnecter tous les appareils.
    revoke_all_sessions(session, user.id)
    return user


def purge_expired_reset_tokens(session: Session) -> int:
    maintenant = datetime.now(timezone.utc).replace(tzinfo=None)
    vieux = session.scalars(
        select(PasswordResetToken).where(PasswordResetToken.expires_at < maintenant)
    ).all()
    for entry in vieux:
        session.delete(entry)
    if vieux:
        session.commit()
    return len(vieux)


# --- Amorcage du premier compte -----------------------------------------
def ensure_first_user(session: Session) -> None:
    """Cree le compte initial au premier demarrage.

    Si ADMIN_PASSWORD n'est pas fourni, un mot de passe aleatoire est genere et
    affiche UNE SEULE FOIS dans les journaux : rien de devinable n'est mis par
    defaut, et le changement est impose a la premiere connexion.
    """
    if session.scalars(select(User).limit(1)).first() is not None:
        return

    email = (settings.admin_email or "admin@local").strip().lower()
    fourni = bool(settings.admin_password)
    mdp = settings.admin_password or secrets.token_urlsafe(12)

    session.add(
        User(
            email=email,
            password_hash=hash_password(mdp),
            must_change_password=not fourni,
        )
    )
    session.commit()

    if fourni:
        logger.info("Compte initial cree pour %s (mot de passe issu de ADMIN_PASSWORD)", email)
    else:
        logger.warning(
            "\n"
            "==========================================================\n"
            "  COMPTE INITIAL CREE\n"
            "  Identifiant : %s\n"
            "  Mot de passe : %s\n"
            "  Ce mot de passe n'est affiche qu'une fois.\n"
            "  Il devra etre change a la premiere connexion.\n"
            "==========================================================",
            email,
            mdp,
        )
