from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import session_scope
from app.main import app
from app.models import MembershipRole, OrganizationMembership, User
from app.services import auth


def _target(name: str) -> dict:
    return {
        "name": name,
        "url": "https://example.com/",
        "run_time": "09:00",
    }


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


def test_organisations_isolent_les_cibles(
    auth_client: TestClient, public_example_dns
):
    default_org = auth_client.get("/api/organizations").json()[0]
    created = auth_client.post(
        "/api/organizations", json={"name": "Agence R&D"}
    )
    assert created.status_code == 201, created.text
    second_org = created.json()
    assert second_org["role"] == "owner"

    headers = {"X-Organization-ID": str(second_org["id"])}
    target = auth_client.post(
        "/api/targets", headers=headers, json=_target("Cible isolée")
    )
    assert target.status_code == 201, target.text

    default_targets = auth_client.get(
        "/api/targets", headers={"X-Organization-ID": str(default_org["id"])}
    ).json()
    second_targets = auth_client.get("/api/targets", headers=headers).json()
    assert target.json()["id"] not in {item["id"] for item in default_targets}
    assert target.json()["id"] in {item["id"] for item in second_targets}


def test_organisation_inaccessible_sans_adhesion(
    auth_client: TestClient, public_example_dns
):
    organization = auth_client.post(
        "/api/organizations", json={"name": "Organisation privée"}
    ).json()
    outsider_email = "outsider@example.com"
    outsider_password = "Mot2Passe-Outsider-Solide"
    _create_user(outsider_email, outsider_password)

    with TestClient(app) as outsider:
        login = outsider.post(
            "/api/auth/login",
            json={"email": outsider_email, "password": outsider_password},
        )
        assert login.status_code == 200
        response = outsider.get(
            "/api/targets",
            headers={"X-Organization-ID": str(organization["id"])},
        )
        assert response.status_code == 403


def test_viewer_est_en_lecture_seule(
    auth_client: TestClient, public_example_dns
):
    organization = auth_client.post(
        "/api/organizations", json={"name": "Espace lecture seule"}
    ).json()
    viewer_email = "viewer@example.com"
    viewer_password = "Mot2Passe-Viewer-Solide"
    viewer = _create_user(viewer_email, viewer_password)

    with session_scope() as session:
        session.add(
            OrganizationMembership(
                organization_id=organization["id"],
                user_id=viewer.id,
                role=MembershipRole.viewer,
            )
        )

    headers = {"X-Organization-ID": str(organization["id"])}
    with TestClient(app) as viewer_client:
        login = viewer_client.post(
            "/api/auth/login",
            json={"email": viewer_email, "password": viewer_password},
        )
        assert login.status_code == 200
        assert viewer_client.get("/api/targets", headers=headers).status_code == 200
        assert (
            viewer_client.post(
                "/api/targets", headers=headers, json=_target("Interdite")
            ).status_code
            == 403
        )
        assert (
            viewer_client.post(
                "/api/accounts",
                headers=headers,
                json={"name": "Facebook interdit", "platform": "facebook"},
            ).status_code
            == 403
        )
        assert (
            viewer_client.get(
                "/api/organizations/current/members", headers=headers
            ).status_code
            == 403
        )
