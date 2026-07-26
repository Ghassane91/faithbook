from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.database import session_scope
from app.models import (
    Account,
    AccountStatus,
    Run,
    RunStatus,
    Target,
    TriggerType,
)
from app.services import crypto, notify, runner, session_check
from app.services.capture import CaptureResult, SessionExpired
from app.services.profile_lock import get_profile_lock


@pytest.mark.asyncio
async def test_verrou_profil_serialise_deux_operations():
    lock = get_profile_lock("profil-test-verrou")
    entered: list[str] = []
    release_first = asyncio.Event()

    async def first():
        async with lock:
            entered.append("first")
            await release_first.wait()

    async def second():
        async with lock:
            entered.append("second")

    t1 = asyncio.create_task(first())
    await asyncio.sleep(0)
    t2 = asyncio.create_task(second())
    await asyncio.sleep(0)
    assert entered == ["first"]
    release_first.set()
    await asyncio.gather(t1, t2)
    assert entered == ["first", "second"]


@pytest.mark.asyncio
async def test_compte_sans_coffre_est_deconnecte():
    result = await session_check.check_account(
        "profil-qui-nexiste-pas", "facebook"
    )
    assert result["status"] == AccountStatus.disconnected
    assert result["logged_in"] is False


@pytest.mark.asyncio
async def test_capture_suspendue_sans_retry(monkeypatch):
    with session_scope() as session:
        account = Account(
            name="Compte suspendu",
            platform="facebook",
            profile_slug="profil-suspendu",
            status=AccountStatus.connected,
            encrypted_state=crypto.encrypt_text(
                json.dumps({"cookies": [{"name": "c_user", "value": "1"}], "origins": []})
            ),
        )
        session.add(account)
        session.flush()
        target = Target(
            name="Cible suspendue",
            url="https://example.com/page",
            account_id=account.id,
        )
        session.add(target)
        session.flush()
        run = Run(
            target_id=target.id,
            trigger=TriggerType.manual,
            capture_date="2026-07-24",
            status=RunStatus.pending,
        )
        session.add(run)
        session.flush()
        run_id = run.id
        account_id = account.id

    calls = 0

    async def blocked(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise SessionExpired("checkpoint Facebook", AccountStatus.verification_required)

    monkeypatch.setattr(runner, "_attempt_once", blocked)
    monkeypatch.setattr(runner, "notify_session_suspended", lambda *_args: None)
    await runner.execute_run(run_id)

    with session_scope() as session:
        saved_run = session.get(Run, run_id)
        saved_account = session.get(Account, account_id)
        assert saved_run.status == RunStatus.suspended
        assert saved_run.session_status == "verification_required"
        assert saved_account.status == AccountStatus.verification_required
    assert calls == 1


@pytest.mark.asyncio
async def test_capture_actualise_la_copie_chiffree(monkeypatch, tmp_path):
    initial = {"cookies": [{"name": "c_user", "value": "ancien"}], "origins": []}
    refreshed = {
        "cookies": [
            {
                "name": "c_user",
                "value": "nouveau",
                "domain": ".facebook.com",
                "expires": 4102444800,
            }
        ],
        "origins": [],
    }
    with session_scope() as session:
        account = Account(
            name="Compte rotation",
            platform="facebook",
            profile_slug="profil-rotation",
            status=AccountStatus.connected,
            encrypted_state=crypto.encrypt_text(json.dumps(initial)),
        )
        session.add(account)
        session.flush()
        target = Target(
            name="Cible rotation",
            url="https://example.com/rotation",
            account_id=account.id,
        )
        session.add(target)
        session.flush()
        run = Run(
            target_id=target.id,
            trigger=TriggerType.manual,
            capture_date="2026-07-24",
            status=RunStatus.running,
        )
        session.add(run)
        session.flush()
        run_id = run.id
        account_id = account.id
        target_id = target.id

    async def fake_capture(_target, destination, **kwargs):
        assert kwargs["account_profile_slug"] == "profil-rotation"
        assert kwargs["account_storage"] == initial
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"png")
        return CaptureResult(
            path=destination,
            size_bytes=3,
            sha256="a" * 64,
            page_title="Page",
            final_url="https://example.com/rotation",
            storage_state=refreshed,
        )

    monkeypatch.setattr(runner, "capture_page", fake_capture)
    monkeypatch.setattr(runner, "make_thumbnail", lambda *_args: None)
    monkeypatch.setattr(runner.settings, "screenshot_dir", str(tmp_path))
    monkeypatch.setattr(runner.settings, "storage_backend", "local")

    with session_scope() as session:
        await runner._attempt_once(
            session,
            session.get(Run, run_id),
            session.get(Target, target_id),
            attempt=1,
            force=True,
        )

    with session_scope() as session:
        account = session.get(Account, account_id)
        assert session_check.encrypted_state_to_storage(account.encrypted_state) == refreshed
        assert account.status == AccountStatus.connected
        assert isinstance(account.last_success_at, datetime)


@pytest.mark.asyncio
async def test_alerte_avant_expiration(monkeypatch):
    expiry = datetime.now(timezone.utc) + timedelta(days=2)
    state = {
        "cookies": [
            {
                "name": "xs",
                "value": "secret",
                "domain": ".facebook.com",
                "expires": expiry.timestamp(),
            }
        ],
        "origins": [],
    }
    encrypted = crypto.encrypt_text(json.dumps(state))
    with session_scope() as session:
        session.add(
            Account(
                name="Compte bientôt expiré",
                platform="facebook",
                profile_slug="profil-bientot-expire",
                status=AccountStatus.connected,
                encrypted_state=encrypted,
            )
        )

    async def fake_check(_slug, _platform):
        return {
            "status": AccountStatus.connected,
            "logged_in": True,
            "final_url": "https://www.facebook.com/",
            "detail": "Session active.",
            "encrypted_state": encrypted,
        }

    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(session_check, "check_account", fake_check)
    monkeypatch.setattr(notify, "_send", lambda subject, body: sent.append((subject, body)))
    monkeypatch.setattr(notify.settings, "session_expiry_warning_days", 7)

    await notify.check_all_sessions()

    assert sent
    assert "bientôt expirée" in sent[0][0]
    assert "Compte bientôt expiré" in sent[0][1]
