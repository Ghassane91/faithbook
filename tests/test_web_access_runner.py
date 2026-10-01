"""Un blocage marchand ne déconnecte pas un compte et ne produit pas de faux succès."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.database import session_scope
from app.models import Account, AccountStatus, Run, RunStatus, Target, TriggerType
from app.services import capture, drive, fiches_liens, runner
from app.services.fiches_liens import Lien
from app.services.remote_browser import RemoteBrowserError
from app.services.web_challenges import WebChallenge


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [WebChallenge(), RemoteBrowserError("Le navigateur distant est indisponible.")],
    ids=["verification-humaine", "navigateur-distant"],
)
async def test_blocage_web_echoue_une_fois_sans_deconnecter_le_compte(monkeypatch, failure):
    last_verified = datetime(2026, 9, 1, tzinfo=timezone.utc)
    with session_scope() as session:
        account = Account(
            name="Compte toujours connecté",
            platform="facebook",
            profile_slug=f"web-access-{uuid4().hex}",
            status=AccountStatus.connected,
            last_error=None,
            last_verified_at=last_verified,
        )
        session.add(account)
        session.flush()
        target = Target(
            name="Fiche marchande bloquée",
            url="https://www.walmart.com/ip/example",
            account_id=account.id,
        )
        session.add(target)
        session.flush()
        run = Run(
            target_id=target.id,
            capture_date="2026-09-30",
            trigger=TriggerType.manual,
            status=RunStatus.pending,
        )
        session.add(run)
        session.flush()
        run_id, account_id = run.id, account.id

    attempt = AsyncMock(side_effect=failure)
    notify_failure = MagicMock()
    notify_session = MagicMock()
    monkeypatch.setattr(runner, "_attempt_once", attempt)
    monkeypatch.setattr(runner, "notify_failure", notify_failure)
    monkeypatch.setattr(runner, "notify_session_suspended", notify_session)
    monkeypatch.setattr(runner.settings, "max_attempts", 3)
    monkeypatch.setattr(runner.settings, "retry_backoff_seconds", 0)

    await runner.execute_run(run_id, force=True)

    with session_scope() as session:
        saved_run = session.get(Run, run_id)
        saved_account = session.get(Account, account_id)
        assert saved_run.status == RunStatus.failed
        assert saved_run.attempts == 1
        assert saved_run.error_message == str(failure)
        assert saved_run.finished_at is not None
        assert saved_run.session_status is None
        assert saved_run.screenshot_path is None
        assert saved_account.status == AccountStatus.connected
        assert saved_account.last_error is None
        # SQLite renvoie les DateTime sans tzinfo.
        assert saved_account.last_verified_at.replace(tzinfo=timezone.utc) == last_verified
    attempt.assert_awaited_once()
    notify_failure.assert_called_once()
    notify_session.assert_not_called()


@pytest.fixture
def product_capture_environment(monkeypatch, tmp_path):
    fake_drive = MagicMock()
    fake_drive.is_configured.return_value = True
    fake_drive.ensure_folder.side_effect = lambda name, parent=None: f"folder-{name}"
    monkeypatch.setattr(drive, "drive_client", fake_drive)
    monkeypatch.setattr(fiches_liens.settings, "screenshot_dir", str(tmp_path))
    monkeypatch.setattr(fiches_liens, "_journaliser", MagicMock())
    return fake_drive, tmp_path


def test_fiche_complete_avec_robot_et_notice_recaptcha_reste_exploitable():
    text = (
        "Robot trail camera accessory\n"
        + "Product specifications: waterproof case, battery life, resolution and warranty. " * 12
        + "\nThis site is protected by reCAPTCHA. Google Privacy Policy and Terms of Service apply."
    )
    assert len(text) > 300
    assert fiches_liens.est_bloquee(text) is False


@pytest.mark.parametrize("text", [None, "", "A short product description"])
def test_fiche_vide_ou_trop_courte_reste_ecartee(text):
    assert fiches_liens.est_bloquee(text) is True


@pytest.mark.asyncio
async def test_challenge_compte_comme_blocage_et_seule_la_bonne_fiche_est_envoyee(
    monkeypatch, product_capture_environment
):
    fake_drive, tmp_path = product_capture_environment
    blocked = Lien("Spypoint", "Flex", "WALMART", "https://www.walmart.com/ip/1")
    good = Lien("Spypoint", "Flex", "ACADEMY", "https://www.academy.com/p/flex")
    captured = []

    async def fake_capture(target, destination, **_kwargs):
        captured.append(target.url)
        # Même un fichier partiel laissé avant l'erreur doit être nettoyé.
        destination.write_bytes(b"image")
        if target.url == blocked.url:
            raise WebChallenge()
        return SimpleNamespace(body_text="Spypoint Flex trail camera specifications. " * 30)

    monkeypatch.setattr(capture, "capture_page", fake_capture)
    result = await fiches_liens.capturer_tout([blocked, good], "2026-09-30", pause_s=0)

    assert result == {"total": 2, "ok": 1, "bloquees": 1, "erreurs": 0}
    assert captured == [blocked.url, good.url]
    fake_drive.upload.assert_called_once()
    assert fake_drive.upload.call_args.args[1:] == ("folder-Academy", good.nom_fichier)
    assert not list(tmp_path.rglob("*.jpg"))


@pytest.mark.asyncio
async def test_echec_upload_compte_comme_erreur_et_ne_gonfle_pas_les_succes(
    monkeypatch, product_capture_environment
):
    fake_drive, tmp_path = product_capture_environment
    first = Lien("Spypoint", "Flex", "ACADEMY", "https://www.academy.com/p/flex")
    second = Lien("Browning", "Elite", "WALMART", "https://www.walmart.com/ip/2")

    async def fake_capture(_target, destination, **_kwargs):
        destination.write_bytes(b"image")
        return SimpleNamespace(body_text="Trail camera product description and specifications. " * 30)

    monkeypatch.setattr(capture, "capture_page", fake_capture)
    fake_drive.upload.side_effect = [RuntimeError("Drive indisponible"), None]
    result = await fiches_liens.capturer_tout([first, second], "2026-09-30", pause_s=0)

    assert result == {"total": 2, "ok": 1, "bloquees": 0, "erreurs": 1}
    assert fake_drive.upload.call_count == 2
    assert [call.args[2] for call in fake_drive.upload.call_args_list] == [
        first.nom_fichier,
        second.nom_fichier,
    ]
    assert not list(tmp_path.rglob("*.jpg"))
