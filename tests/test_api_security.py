"""Tests d'integration (FastAPI TestClient) des correctifs de securite 1a.

Ne necessite ni Docker ni nginx : on frappe directement l'application ASGI.
Le relais nginx (auth_request) lui-meme n'est pas rejouable ici — il est
verifie manuellement (voir README §8) — mais la logique qu'il delegue au
backend (`/api/auth/check`, `/api/accounts/novnc/authorize`) l'est.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.database import session_scope
from app.main import app
from app.models import User
from app.models import AccountStatus
from app.services import auth
from app.services import audit as audit_service
from app.services import session_check
from app.services.login_browser import LoginSession, login_manager


# --- SSRF branche a la creation/modification de cible -----------------------
def test_creation_cible_url_interne_refusee(auth_client):
    resp = auth_client.post(
        "/api/targets", json={"name": "x", "url": "http://127.0.0.1/admin", "run_time": "09:00"}
    )
    assert resp.status_code == 422


def test_creation_cible_url_metadata_cloud_refusee(auth_client):
    resp = auth_client.post(
        "/api/targets",
        json={"name": "x", "url": "http://169.254.169.254/latest/meta-data/", "run_time": "09:00"},
    )
    assert resp.status_code == 422


def test_creation_cible_url_publique_acceptee(auth_client, public_example_dns):
    resp = auth_client.post(
        "/api/targets", json={"name": "site public", "url": "https://example.com/", "run_time": "09:00"}
    )
    assert resp.status_code == 201, resp.text


def test_modification_cible_vers_url_interne_refusee(auth_client, public_example_dns):
    created = auth_client.post(
        "/api/targets", json={"name": "cible", "url": "https://example.com/", "run_time": "09:00"}
    ).json()
    resp = auth_client.patch(f"/api/targets/{created['id']}", json={"url": "http://169.254.169.254/"})
    assert resp.status_code == 422


def test_creation_cible_sans_session_refusee(client):
    resp = client.post(
        "/api/targets", json={"name": "x", "url": "https://example.com/", "run_time": "09:00"}
    )
    assert resp.status_code == 401


# --- Audit des tentatives de connexion (M4 : brute-force sans aucune trace) --
def test_echec_login_journalise(client):
    from app.database import session_scope
    from app.services import audit as audit_service

    client.post("/api/auth/login", json={"email": "inconnu@example.com", "password": "peu-importe"})
    with session_scope() as session:
        entries = audit_service.recent(session, limit=10)
        assert any(
            e.action == "auth.login_failed" and e.detail == "email=inconnu@example.com"
            for e in entries
        )


# --- Gate de session sur /api/auth/check (protege /docs via nginx) ---------
def test_check_sans_session():
    from fastapi.testclient import TestClient

    from app.main import app

    resp = TestClient(app).get("/api/auth/check")
    assert resp.status_code == 401


def test_check_avec_session(auth_client):
    resp = auth_client.get("/api/auth/check")
    assert resp.status_code == 204


# --- Jeton noVNC : gate d'autorisation + isolation entre utilisateurs -------
def test_novnc_authorize_refuse_sans_cookie(auth_client):
    resp = auth_client.get("/api/accounts/novnc/authorize")
    assert resp.status_code == 403


def test_novnc_authorize_accepte_le_bon_jeton(auth_client):
    moi = auth_client.get("/api/auth/me").json()
    login_manager._active = LoginSession(
        account_id=1, profile_slug="p", platform="facebook",
        work_dir=None, pw=None, context=None,
        started_by_user_id=moi["id"], token="jeton-de-test",
        token_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    try:
        auth_client.cookies.set("faithbook_novnc", "jeton-de-test")
        resp = auth_client.get("/api/accounts/novnc/authorize")
        assert resp.status_code == 204
    finally:
        login_manager._active = None
        auth_client.cookies.delete("faithbook_novnc")


def test_novnc_authorize_refuse_mauvais_jeton(auth_client):
    moi = auth_client.get("/api/auth/me").json()
    login_manager._active = LoginSession(
        account_id=1, profile_slug="p", platform="facebook",
        work_dir=None, pw=None, context=None,
        started_by_user_id=moi["id"], token="jeton-de-test",
        token_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    try:
        auth_client.cookies.set("faithbook_novnc", "un-autre-jeton")
        resp = auth_client.get("/api/accounts/novnc/authorize")
        assert resp.status_code == 403
    finally:
        login_manager._active = None
        auth_client.cookies.delete("faithbook_novnc")


def test_novnc_authorize_refuse_un_autre_utilisateur_avec_le_bon_jeton():
    """Le coeur de C2/M3 : un second utilisateur, meme avec le jeton correct
    (vole ou devine), ne doit jamais pouvoir rejoindre l'ecran d'un autre."""
    email_a, mdp_a = "novnc-a@example.com", "Mot2Passe-Utilisateur-A"
    email_b, mdp_b = "novnc-b@example.com", "Mot2Passe-Utilisateur-B"
    with session_scope() as session:
        for email, mdp in ((email_a, mdp_a), (email_b, mdp_b)):
            if session.query(User).filter_by(email=email).first() is None:
                session.add(User(email=email, password_hash=auth.hash_password(mdp)))

    client_a = TestClient(app)
    client_b = TestClient(app)
    assert client_a.post("/api/auth/login", json={"email": email_a, "password": mdp_a}).status_code == 200
    assert client_b.post("/api/auth/login", json={"email": email_b, "password": mdp_b}).status_code == 200

    user_a_id = client_a.get("/api/auth/me").json()["id"]

    login_manager._active = LoginSession(
        account_id=1, profile_slug="p", platform="facebook",
        work_dir=None, pw=None, context=None,
        started_by_user_id=user_a_id, token="jeton-de-a",
        token_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    try:
        client_a.cookies.set("faithbook_novnc", "jeton-de-a")
        assert client_a.get("/api/accounts/novnc/authorize").status_code == 204

        client_b.cookies.set("faithbook_novnc", "jeton-de-a")  # B connait/vole le jeton de A
        assert client_b.get("/api/accounts/novnc/authorize").status_code == 403
    finally:
        login_manager._active = None


def test_controle_session_compte_est_audite(auth_client, monkeypatch):
    created = auth_client.post(
        "/api/accounts", json={"name": "Compte audit", "platform": "facebook"}
    )
    assert created.status_code == 201
    account_id = created.json()["id"]

    async def fake_check(_slug, _platform):
        return {
            "status": AccountStatus.connected,
            "logged_in": True,
            "final_url": "https://www.facebook.com/",
            "detail": "Session active.",
        }

    monkeypatch.setattr(session_check, "check_account", fake_check)
    response = auth_client.post(f"/api/accounts/{account_id}/test")
    assert response.status_code == 200

    with session_scope() as session:
        entries = audit_service.recent(session, limit=20)
        assert any(
            entry.action == "account.session_test"
            and f"compte #{account_id}" in (entry.detail or "")
            for entry in entries
        )
