from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, User

logger = logging.getLogger(__name__)


def record(
    session: Session,
    action: str,
    *,
    user: User | None = None,
    detail: str | None = None,
    ip: str | None = None,
) -> None:
    """Consigne une action sensible.

    `detail` ne doit JAMAIS contenir de secret (mot de passe, cookie, jeton,
    code 2FA) : n'y mettre que des identifiants et des libellés.
    """
    session.add(
        AuditLog(
            action=action,
            detail=detail,
            ip=ip,
            user_id=user.id if user and user.id else None,
            user_email=user.email if user else None,
        )
    )
    session.commit()
    logger.info("AUDIT %s par %s : %s", action, user.email if user else "?", detail or "")


def recent(session: Session, limit: int = 100) -> list[AuditLog]:
    return list(
        session.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)).all()
    )
