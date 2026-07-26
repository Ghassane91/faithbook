from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import session_scope
from app.models import OrganizationInvitation, User
from app.services import auth


def _token(invite_url: str) -> str:
    return parse_qs(urlparse(invite_url).query)["invite_token"][0]


def test_invitation_cree_un_utilisateur_et_une_adhesion(
    auth_client: TestClient, client: TestClient
):
    organization = auth_client.get("/api/organizations").json()[0]
    headers = {"X-Organization-ID": str(organization["id"])}
    created = auth_client.post(
        "/api/organizations/current/invitations",
        headers=headers,
        json={"email": "nouveau-invite@example.com", "role": "viewer"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["delivery"] == "logged"
    token = _token(created.json()["invite_url"])

    preview = client.get(f"/api/auth/invitations/{token}")
    assert preview.status_code == 200
    assert preview.json()["organization_name"] == organization["name"]
    assert preview.json()["user_exists"] is False

    weak = client.post(
        "/api/auth/invitations/accept",
        json={"token": token, "password": "court"},
    )
    assert weak.status_code == 422

    accepted = client.post(
        "/api/auth/invitations/accept",
        json={"token": token, "password": "Mot2Passe-Invite-Solide"},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["email"] == "nouveau-invite@example.com"

    organizations = client.get("/api/organizations").json()
    membership = next(item for item in organizations if item["id"] == organization["id"])
    assert membership["role"] == "viewer"
    assert client.get(f"/api/auth/invitations/{token}").status_code == 404


def test_invitation_utilisateur_existant_exige_son_mot_de_passe(
    auth_client: TestClient, client: TestClient
):
    email = "invite-existant@example.com"
    password = "Mot2Passe-Existant-Solide"
    with session_scope() as session:
        if session.scalars(select(User).where(User.email == email)).first() is None:
            session.add(User(email=email, password_hash=auth.hash_password(password)))

    organization = auth_client.post(
        "/api/organizations", json={"name": "Équipe invitation existante"}
    ).json()
    headers = {"X-Organization-ID": str(organization["id"])}
    created = auth_client.post(
        "/api/organizations/current/invitations",
        headers=headers,
        json={"email": email, "role": "member"},
    )
    token = _token(created.json()["invite_url"])
    assert client.get(f"/api/auth/invitations/{token}").json()["user_exists"] is True

    refused = client.post(
        "/api/auth/invitations/accept",
        json={"token": token, "password": "Mauvais2MotDePasse"},
    )
    assert refused.status_code == 401

    accepted = client.post(
        "/api/auth/invitations/accept",
        json={"token": token, "password": password},
    )
    assert accepted.status_code == 200


def test_invitation_revoquee_est_inutilisable(
    auth_client: TestClient, client: TestClient
):
    organization = auth_client.post(
        "/api/organizations", json={"name": "Équipe révocation"}
    ).json()
    headers = {"X-Organization-ID": str(organization["id"])}
    created = auth_client.post(
        "/api/organizations/current/invitations",
        headers=headers,
        json={"email": "invitation-revoquee@example.com", "role": "member"},
    )
    invitation_id = created.json()["id"]
    token = _token(created.json()["invite_url"])

    revoked = auth_client.delete(
        f"/api/organizations/current/invitations/{invitation_id}",
        headers=headers,
    )
    assert revoked.status_code == 204
    assert client.get(f"/api/auth/invitations/{token}").status_code == 404

    with session_scope() as session:
        stored = session.get(OrganizationInvitation, invitation_id)
        assert stored is not None
        assert stored.revoked_at is not None
        assert stored.token_hash != token
