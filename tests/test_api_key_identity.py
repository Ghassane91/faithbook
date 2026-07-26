from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.config import settings
from app.database import session_scope
from app.main import app
from app.models import User
from app.services import auth
from app.services.login_browser import LoginSession, login_manager


def _ensure_user(email: str, password: str) -> int:
    with session_scope() as session:
        user = session.query(User).filter_by(email=email).first()
        if user is None:
            user = User(email=email, password_hash=auth.hash_password(password))
            session.add(user)
            session.commit()
            session.refresh(user)
        return user.id


def test_cle_api_agit_comme_un_utilisateur_reel_et_garde_novnc(client, monkeypatch):
    email = "api-owner@example.com"
    user_id = _ensure_user(email, "Mot2Passe-API")
    monkeypatch.setattr(settings, "api_key", "cle-api-de-test")
    monkeypatch.setattr(settings, "api_key_user_email", email)

    api = TestClient(app, headers={"X-API-Key": "cle-api-de-test"})
    me = api.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["id"] == user_id

    created = api.post(
        "/api/accounts", json={"name": "Facebook API", "platform": "facebook"}
    )
    assert created.status_code == 201, created.text
    account_id = created.json()["id"]

    login_manager._active = LoginSession(
        account_id=account_id,
        profile_slug="p",
        platform="facebook",
        work_dir=None,
        pw=None,
        context=None,
        started_by_user_id=user_id,
        token="jeton-api",
        token_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    try:
        api.cookies.set("faithbook_novnc", "jeton-api")
        assert api.get("/api/accounts/novnc/authorize").status_code == 204
    finally:
        login_manager._active = None


def test_cle_api_ne_voit_pas_le_compte_d_un_autre_utilisateur(monkeypatch):
    owner_email = "owner-isole@example.com"
    other_email = "api-isole@example.com"
    owner_password = "Mot2Passe-Owner"
    owner_id = _ensure_user(owner_email, owner_password)
    _ensure_user(other_email, "Mot2Passe-API-Isole")

    owner = TestClient(app)
    assert owner.post(
        "/api/auth/login", json={"email": owner_email, "password": owner_password}
    ).status_code == 200
    created = owner.post(
        "/api/accounts", json={"name": "Session privée", "platform": "facebook"}
    )
    assert created.status_code == 201
    account_id = created.json()["id"]

    monkeypatch.setattr(settings, "api_key", "cle-isolee")
    monkeypatch.setattr(settings, "api_key_user_email", other_email)
    api = TestClient(app, headers={"X-API-Key": "cle-isolee"})
    assert all(item["id"] != account_id for item in api.get("/api/accounts").json())
    assert api.delete(f"/api/accounts/{account_id}").status_code == 403

    with session_scope() as session:
        assert session.get(User, owner_id) is not None
