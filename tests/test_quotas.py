from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from app.config import settings
from app.database import session_scope
from app.models import Organization, Run, RunStatus, TriggerType, utcnow
from app.services import quotas, runner
from app.services.capture import thumb_path


def _organization(auth_client, name: str) -> dict:
    response = auth_client.post(
        "/api/organizations",
        json={"name": f"{name} {uuid4().hex[:8]}"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _target(auth_client, organization_id: int, name: str) -> dict:
    response = auth_client.post(
        "/api/targets",
        headers={"X-Organization-ID": str(organization_id)},
        json={
            "name": f"{name} {uuid4().hex[:8]}",
            "url": "https://example.com/",
            "enabled": False,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _set_quotas(organization_id: int, **values: int) -> None:
    with session_scope() as session:
        organization = session.get(Organization, organization_id)
        assert organization is not None
        for name, value in values.items():
            setattr(organization, name, value)


def test_usage_expose_les_limites_et_la_consommation(auth_client):
    organization = _organization(auth_client, "Usage")
    response = auth_client.get(
        "/api/organizations/current/usage",
        headers={"X-Organization-ID": str(organization["id"])},
    )

    assert response.status_code == 200, response.text
    usage = response.json()
    assert usage["organization_id"] == organization["id"]
    assert usage["accounts"] == {
        "used": 0,
        "limit": settings.default_quota_accounts,
        "remaining": settings.default_quota_accounts,
        "percent": 0.0,
        "unlimited": False,
    }
    assert usage["targets"]["used"] == 0
    assert usage["daily_captures"]["used"] == 0
    assert usage["storage_bytes"]["used"] == 0
    assert usage["retention_days"] == settings.run_retention_days


def test_quota_comptes_refuse_la_creation_suivante(auth_client):
    organization = _organization(auth_client, "Quota comptes")
    _set_quotas(organization["id"], quota_accounts=1)
    headers = {"X-Organization-ID": str(organization["id"])}

    first = auth_client.post(
        "/api/accounts",
        headers=headers,
        json={"name": "Facebook 1", "platform": "facebook"},
    )
    second = auth_client.post(
        "/api/accounts",
        headers=headers,
        json={"name": "Facebook 2", "platform": "facebook"},
    )

    assert first.status_code == 201, first.text
    assert second.status_code == 409
    assert "Quota de comptes connectés atteint" in second.json()["detail"]


def test_quota_cibles_refuse_la_creation_suivante(
    auth_client, public_example_dns
):
    organization = _organization(auth_client, "Quota cibles")
    _set_quotas(organization["id"], quota_targets=1)
    headers = {"X-Organization-ID": str(organization["id"])}

    first = auth_client.post(
        "/api/targets",
        headers=headers,
        json={
            "name": "Cible 1",
            "url": "https://example.com/",
            "enabled": False,
        },
    )
    second = auth_client.post(
        "/api/targets",
        headers=headers,
        json={
            "name": "Cible 2",
            "url": "https://example.com/",
            "enabled": False,
        },
    )

    assert first.status_code == 201, first.text
    assert second.status_code == 409
    assert "Quota de cibles atteint" in second.json()["detail"]


@pytest.mark.asyncio
async def test_quota_quotidien_bloque_avant_la_mise_en_file(
    auth_client, public_example_dns
):
    organization = _organization(auth_client, "Quota quotidien")
    target = _target(
        auth_client, organization["id"], "Cible quota quotidien"
    )
    _set_quotas(organization["id"], quota_daily_captures=1)
    with session_scope() as session:
        session.add(
            Run(
                target_id=target["id"],
                trigger=TriggerType.manual,
                capture_date=utcnow().date().isoformat(),
                status=RunStatus.failed,
                started_at=utcnow(),
            )
        )

    with pytest.raises(quotas.QuotaExceeded, match="captures quotidiennes"):
        await runner.trigger_target(
            target["id"], TriggerType.manual, force=True
        )


@pytest.mark.asyncio
async def test_quota_stockage_bloque_avant_la_mise_en_file(
    auth_client, public_example_dns
):
    organization = _organization(auth_client, "Quota stockage")
    target = _target(auth_client, organization["id"], "Cible quota stockage")
    _set_quotas(organization["id"], quota_storage_bytes=100)
    with session_scope() as session:
        session.add(
            Run(
                target_id=target["id"],
                trigger=TriggerType.manual,
                capture_date=utcnow().date().isoformat(),
                # Un second worker doit déjà compter un PNG écrit par une
                # exécution encore en cours.
                status=RunStatus.running,
                started_at=utcnow() - timedelta(days=1),
                screenshot_path=str(
                    Path(settings.screenshot_dir) / "capture-en-cours.png"
                ),
                screenshot_bytes=100,
            )
        )

    with pytest.raises(quotas.QuotaExceeded, match="stockage"):
        await runner.trigger_target(
            target["id"], TriggerType.manual, force=True
        )


def test_retention_est_isolee_par_organisation(
    auth_client, public_example_dns
):
    short_org = _organization(auth_client, "Rétention courte")
    long_org = _organization(auth_client, "Rétention longue")
    short_target = _target(
        auth_client, short_org["id"], "Cible rétention courte"
    )
    long_target = _target(
        auth_client, long_org["id"], "Cible rétention longue"
    )
    _set_quotas(short_org["id"], retention_days=1)
    _set_quotas(long_org["id"], retention_days=30)

    root = Path(settings.screenshot_dir)
    short_png = root / f"retention-{uuid4().hex}" / "short.png"
    long_png = root / f"retention-{uuid4().hex}" / "long.png"
    for path in (short_png, long_png):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"png")
        thumb_path(path).write_bytes(b"thumb")

    old = utcnow() - timedelta(days=10)
    with session_scope() as session:
        short_run = Run(
            target_id=short_target["id"],
            trigger=TriggerType.manual,
            capture_date=old.date().isoformat(),
            status=RunStatus.success,
            started_at=old,
            screenshot_path=str(short_png),
            screenshot_bytes=short_png.stat().st_size,
            drive_file_id="drive-conserve",
        )
        long_run = Run(
            target_id=long_target["id"],
            trigger=TriggerType.manual,
            capture_date=old.date().isoformat(),
            status=RunStatus.success,
            started_at=old,
            screenshot_path=str(long_png),
            screenshot_bytes=long_png.stat().st_size,
        )
        session.add_all([short_run, long_run])
        session.commit()
        short_run_id = short_run.id
        long_run_id = long_run.id

    with session_scope() as session:
        removed_runs, removed_files = quotas.purge_expired_runs(
            session, now=utcnow()
        )

    assert removed_runs >= 1
    assert removed_files >= 2
    with session_scope() as session:
        assert session.get(Run, short_run_id) is None
        assert session.get(Run, long_run_id) is not None
    assert not short_png.exists()
    assert not thumb_path(short_png).exists()
    assert long_png.exists()
    assert thumb_path(long_png).exists()
