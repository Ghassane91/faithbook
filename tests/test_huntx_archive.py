"""HuntX archive contracts on installations with the optional capture module."""
import uuid
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select

from app import models
if not hasattr(models, "HuntxDriveArtifact"):
    pytest.skip("Optional HuntX archive model not installed", allow_module_level=True)

from app.config import settings
from app.database import session_scope
from app.models import HuntxDriveArtifact, MembershipRole, Organization, OrganizationMembership, Run, RunStatus, Target, TriggerType, User


@pytest.fixture
def archive_data(auth_client, user):
    key = uuid.uuid4().hex
    root = Path(settings.screenshot_dir) / key
    root.mkdir(parents=True)
    image = root / "row.jpg"
    Image.new("RGB", (240, 480), "white").save(image)
    metadata = root / "row.json"
    metadata.write_text('{"price": 99}', encoding="utf-8")
    with session_scope() as s:
        owner = s.scalar(select(User).where(User.email == user[0]))
        org = Organization(name="HuntX test", slug=key)
        private = Organization(name="Private test", slug=key+"-private")
        s.add_all([org, private]); s.flush()
        s.add(OrganizationMembership(user_id=owner.id, organization_id=org.id, role=MembershipRole.viewer))
        target = Target(organization_id=org.id, name="HuntX", url="https://example.test")
        hidden = Target(organization_id=private.id, name="Private", url="https://private.test")
        s.add_all([target, hidden]); s.flush()
        source = Run(target_id=target.id, status=RunStatus.success, trigger=TriggerType.manual, capture_date="2026-10-09")
        other_source = Run(target_id=hidden.id, status=RunStatus.success, trigger=TriggerType.manual, capture_date="2026-10-09")
        s.add_all([source, other_source]); s.flush()
        specs = [("a", "Browning", "2026-10-09", image, None),
                 ("a", "Browning", "2026-10-09", metadata, None),
                 ("a", "Browning", "2026-10-12", image, "Walmart"),
                 ("b", "Reconyx", "2026-10-09", metadata, None)]
        artifacts = []
        for i, (row_key, label, day, path, marketplace) in enumerate(specs):
            a = HuntxDriveArtifact(source_run_id=source.id, dedupe_key=f"{key}:{i}", capture_date=day,
                row_key=row_key, row_label=label, kind="product" if marketplace else "row",
                marketplace=marketplace, local_path=str(path), filename=path.name, drive_status="uploaded")
            s.add(a); s.flush(); artifacts.append(a.id)
        secret = HuntxDriveArtifact(source_run_id=other_source.id, dedupe_key=key+":hidden", capture_date="2030-01-01",
            row_key="private", row_label="Secret", kind="row", local_path=str(image), filename=image.name)
        s.add(secret); s.flush()
        yield_data = (org.id, private.id, artifacts, secret.id)
    return auth_client, yield_data


def test_archive_lists_all_dates_rows_and_metadata_without_tenant_leak(archive_data):
    client, (org, private, ids, secret) = archive_data
    headers = {"X-Organization-ID":str(org)}
    data = client.get("/api/huntx/archive?limit=1&offset=0", headers=headers).json()
    assert data["total"] == 3
    assert data["items"][0]["capture_date"] == "2026-10-12"
    assert [d["date"] for d in data["dates"]] == ["2026-10-12", "2026-10-09"]
    assert "local_path" not in str(data)
    page = client.get("/api/huntx/archive?capture_date=2026-10-09&query=browning", headers=headers).json()
    assert page["total"] == 1 and len(page["items"][0]["artifacts"]) == 2
    assert {a["image"] for a in page["items"][0]["artifacts"]} == {True, False}
    assert client.get(f"/api/huntx/files/{secret}",headers=headers).status_code == 404
    assert client.get("/api/huntx/archive",headers={"X-Organization-ID":str(private)}).status_code == 403
    assert client.get("/api/huntx/archive?limit=101",headers=headers).status_code == 422
    assert client.get("/api/huntx/archive?capture_date=invalid",headers=headers).status_code == 422


def test_archive_requires_authentication(client):
    assert client.get('/api/huntx/archive').status_code == 401
    assert client.get('/api/huntx/workspaces').status_code == 401
    assert client.get('/api/huntx/files/1').status_code == 401


def test_archive_viewer_can_read_image_and_thumbnail_and_missing_is_explicit(archive_data):
    client, (org, _, ids, _) = archive_data
    headers = {"X-Organization-ID":str(org)}
    response = client.get(f"/api/huntx/files/{ids[0]}?thumbnail=true",headers=headers)
    assert response.status_code == 200 and response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "private, no-store"
    meta = client.get(f"/api/huntx/files/{ids[1]}?download=true",headers=headers)
    assert meta.json() == {"price":99} and "attachment" in meta.headers["content-disposition"]
    with session_scope() as s:
        s.get(HuntxDriveArtifact,ids[0]).local_path = str(Path(settings.screenshot_dir)/"missing-archive.jpg")
    assert client.get(f"/api/huntx/files/{ids[0]}",headers=headers).status_code == 410
    with session_scope() as s:
        s.get(HuntxDriveArtifact,ids[1]).local_path = str(Path(settings.screenshot_dir).parent/"outside.json")
    assert client.get(f"/api/huntx/files/{ids[1]}",headers=headers).status_code == 404


def test_huntx_workspace_discovery_only_returns_memberships_with_archives(archive_data):
    client, (org, private, _, _) = archive_data
    data = client.get("/api/huntx/workspaces").json()
    ids = {item["organization_id"] for item in data}
    assert org in ids and private not in ids
