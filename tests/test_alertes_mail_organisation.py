"""Interrupteur « alertes par e-mail » de chaque organisation."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import session_scope
from app.main import app
from app.models import MembershipRole, Organization, OrganizationMembership, User
from app.services import auth, notify


def _create_user(email: str, password: str) -> User:
    with session_scope() as session:
        user = session.scalars(select(User).where(User.email == email)).first()
        if user is None:
            user = User(email=email, password_hash=auth.hash_password(password))
            session.add(user)
            session.commit()
            session.refresh(user)
        session.expunge(user)
        return user


def test_alertes_mail_actives_par_defaut_et_desactivables(auth_client: TestClient):
    org = auth_client.post("/api/organizations", json={"name": "Espace alertes"}).json()
    assert org["email_notifications"] is True
    headers = {"X-Organization-ID": str(org["id"])}

    off = auth_client.patch(
        "/api/organizations/current/settings",
        headers=headers,
        json={"email_notifications": False},
    )
    assert off.status_code == 200, off.text
    assert off.json()["email_notifications"] is False
    current = auth_client.get("/api/organizations/current", headers=headers).json()
    assert current["email_notifications"] is False

    on = auth_client.patch(
        "/api/organizations/current/settings",
        headers=headers,
        json={"email_notifications": True},
    )
    assert on.json()["email_notifications"] is True


def test_seul_un_admin_peut_changer_les_alertes(auth_client: TestClient):
    org = auth_client.post("/api/organizations", json={"name": "Espace membre"}).json()
    email, password = "membre-alertes@example.com", "Mot2Passe-Membre-Solide"
    member = _create_user(email, password)
    with session_scope() as session:
        session.add(
            OrganizationMembership(
                organization_id=org["id"], user_id=member.id, role=MembershipRole.member
            )
        )
    with TestClient(app) as client:
        assert client.post(
            "/api/auth/login", json={"email": email, "password": password}
        ).status_code == 200
        response = client.patch(
            "/api/organizations/current/settings",
            headers={"X-Organization-ID": str(org["id"])},
            json={"email_notifications": False},
        )
        assert response.status_code == 403


import pytest


@pytest.fixture(autouse=True)
def _reactiver_les_alertes():
    """La base de test est partagee : ne pas laisser d'organisation muette."""
    yield
    with session_scope() as session:
        for org in session.query(Organization).filter(
            Organization.email_notifications.is_(False)
        ):
            org.email_notifications = True
        session.commit()


def _org(enabled: bool) -> int:
    with session_scope() as session:
        org = Organization(
            name=f"Org {enabled}", slug=f"org-alertes-{enabled}-{uuid.uuid4().hex[:12]}",
            email_notifications=enabled,
        )
        session.add(org)
        session.commit()
        return org.id


def _capter(monkeypatch):
    mails, canaux = [], []
    monkeypatch.setattr(notify, "_recipient", lambda: "alertes@example.com")
    monkeypatch.setattr(
        notify.mailer, "send_email", lambda to, sujet, corps: mails.append(sujet)
    )
    monkeypatch.setattr(notify.channels, "broadcast", lambda s, c: canaux.append(s))
    return mails, canaux


def _echec(org_id):
    cible = SimpleNamespace(name="Cible test", url="https://example.com", organization_id=org_id)
    run = SimpleNamespace(attempts=1, capture_date="2026-11-06", error_message="défi")
    return cible, run


def test_echec_sans_mail_si_organisation_desactivee(monkeypatch):
    mails, canaux = _capter(monkeypatch)
    notify.notify_failure(*_echec(_org(False)))
    assert mails == []
    assert len(canaux) == 1  # Telegram / webhook restent servis


def test_echec_avec_mail_si_organisation_active(monkeypatch):
    mails, canaux = _capter(monkeypatch)
    notify.notify_failure(*_echec(_org(True)))
    assert len(mails) == 1 and len(canaux) == 1


def test_cible_sans_organisation_garde_le_mail(monkeypatch):
    mails, _ = _capter(monkeypatch)
    notify.notify_failure(*_echec(None))
    assert len(mails) == 1


def test_rapport_du_matin_sans_les_espaces_muets(monkeypatch):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from app.models import Run, RunStatus, Target, TriggerType

    hier = (datetime.now(ZoneInfo(notify.settings.timezone)) - timedelta(days=1)).strftime(
        "%Y-%m-%d"
    )
    muette, active = _org(False), _org(True)
    with session_scope() as session:
        for org_id, nom in ((muette, "Cible-muette-rapport"), (active, "Cible-active-rapport")):
            cible = Target(name=nom, url="https://example.com", organization_id=org_id)
            session.add(cible)
            session.flush()
            session.add(
                Run(
                    target_id=cible.id,
                    status=RunStatus.failed,
                    trigger=TriggerType.scheduled,
                    capture_date=hier,
                    error_message="défi",
                )
            )
        session.commit()

    corps_mail, corps_canaux = [], []
    monkeypatch.setattr(notify, "_recipient", lambda: "alertes@example.com")
    monkeypatch.setattr(
        notify.mailer, "send_email", lambda to, s, c: corps_mail.append(c)
    )
    monkeypatch.setattr(notify.channels, "broadcast", lambda s, c: corps_canaux.append(c))

    notify.daily_report()

    assert len(corps_mail) == 1 and len(corps_canaux) == 1
    assert "Cible-active-rapport" in corps_mail[0]
    assert "Cible-muette-rapport" not in corps_mail[0]
    assert "Cible-muette-rapport" in corps_canaux[0]
