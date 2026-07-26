from __future__ import annotations

import re
import hashlib
from datetime import timedelta
from pathlib import Path

import pytest

from app.config import settings
from app.database import session_scope
from app.models import Run, RunStatus, Target, TriggerType, utcnow
from app.services import drive_sync, runner
from app.services.capture import CaptureResult
from app.services.drive import (
    FOLDER_MIME,
    DriveClient,
    DriveNotConfigured,
    UploadResult,
    drive_client,
)

NAME_RE = re.compile(r"name = '((?:\\.|[^'\\])*)'")
PARENT_RE = re.compile(r"'([^']+)' in parents")


def _unescape(value: str) -> str:
    return value.replace("\\\\", "\x00").replace("\\'", "'").replace("\x00", "\\")


class FakeRequest:
    def __init__(self, result):
        self.result = result
        self.next_chunks = 0

    def execute(self, **_kwargs):
        return self.result

    def next_chunk(self, **_kwargs):
        self.next_chunks += 1
        return None, self.result


class FakeFiles:
    def __init__(self):
        self.store: dict[str, dict] = {}
        self.calls: list[tuple[str, dict]] = []
        self.next_id = 1

    def _id(self) -> str:
        value = f"id-{self.next_id}"
        self.next_id += 1
        return value

    def list(self, **kwargs):
        self.calls.append(("list", kwargs))
        query = kwargs.get("q", "")
        name_match = NAME_RE.search(query)
        parent_match = PARENT_RE.search(query)
        name = _unescape(name_match.group(1)) if name_match else None
        parent = parent_match.group(1) if parent_match else None
        want_folder = f"mimeType = '{FOLDER_MIME}'" in query
        hits = [
            {
                "id": file_id,
                "name": item["name"],
                "webViewLink": item.get("webViewLink", ""),
            }
            for file_id, item in self.store.items()
            if item["name"] == name
            and parent in item["parents"]
            and (item["mimeType"] == FOLDER_MIME) == want_folder
        ]
        return FakeRequest({"files": hits})

    def create(self, **kwargs):
        self.calls.append(("create", kwargs))
        body = kwargs["body"]
        file_id = self._id()
        self.store[file_id] = {
            "name": body["name"],
            "parents": body.get("parents", []),
            "mimeType": body.get("mimeType", "image/png"),
            "webViewLink": f"https://drive.google.com/file/d/{file_id}/view",
        }
        return FakeRequest(
            {"id": file_id, "webViewLink": self.store[file_id]["webViewLink"]}
        )

    def get(self, **kwargs):
        self.calls.append(("get", kwargs))
        item = self.store[kwargs["fileId"]]
        return FakeRequest(
            {
                "id": kwargs["fileId"],
                "name": item["name"],
                "mimeType": item["mimeType"],
                "capabilities": {
                    "canAddChildren": item.get("canAddChildren", True),
                },
            }
        )


class FakeService:
    def __init__(self, files: FakeFiles):
        self._files = files

    def files(self):
        return self._files


def _client(shared_drive: str = "") -> tuple[DriveClient, FakeFiles]:
    settings.google_drive_parent_folder_id = "PARENT"
    settings.google_drive_shared_drive_id = shared_drive
    fake = FakeFiles()
    client = DriveClient()
    client._service = FakeService(fake)
    return client, fake


def test_drive_cree_dossiers_dates_et_evite_doublon(tmp_path):
    client, fake = _client()
    date_id = client.ensure_folder("2026-07-25")
    assert client.ensure_folder("2026-07-25") == date_id

    site_id = client.ensure_folder("facebook", date_id)
    png = tmp_path / "capture.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 200)
    first = client.upload(png, site_id)
    second = client.upload(png, site_id)

    assert first.file_id == second.file_id
    assert second.deduplicated is True
    uploads = [
        call for call in fake.calls
        if call[0] == "create" and "media_body" in call[1]
    ]
    assert len(uploads) == 1
    assert uploads[0][1]["supportsAllDrives"] is True


def test_drive_partage_transmet_les_parametres():
    client, fake = _client(shared_drive="DRIVE-123")
    client.ensure_folder("2026-07-25")
    listing = next(call for call in fake.calls if call[0] == "list")
    assert listing[1]["corpora"] == "drive"
    assert listing[1]["driveId"] == "DRIVE-123"
    assert listing[1]["includeItemsFromAllDrives"] is True


def test_drive_check_refuse_un_parent_non_inscriptible():
    client, fake = _client()
    fake.store["PARENT"] = {
        "name": "Captures",
        "parents": [],
        "mimeType": FOLDER_MIME,
        "canAddChildren": False,
    }
    try:
        client.check_access()
    except DriveNotConfigured as exc:
        assert "ne peut pas écrire" in str(exc)
    else:
        raise AssertionError("Le dossier non inscriptible aurait dû être refusé")


def test_route_drive_check_pour_un_administrateur(auth_client, monkeypatch):
    monkeypatch.setattr(settings, "storage_backend", "google_drive")
    monkeypatch.setattr(drive_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        drive_client,
        "check_access",
        lambda: {
            "id": "PARENT",
            "name": "FaithBook",
            "mimeType": FOLDER_MIME,
            "capabilities": {"canAddChildren": True},
        },
    )

    response = auth_client.post("/api/drive/check")

    assert response.status_code == 200, response.text
    assert response.json()["writable"] is True
    assert response.json()["parent_name"] == "FaithBook"


def test_hierarchie_drive_commence_par_la_date():
    target = Target(
        name="Groupe",
        url="https://www.facebook.com/groups/test",
        run_time="09:00",
        organization_id=42,
        subfolder="Publications",
    )
    assert drive_sync.folder_names(target, "2026-07-25") == (
        "2026-07-25",
        "organization-42",
        "facebook.com-groups-test",
        "publications",
    )


def test_reprise_drive_ne_refait_pas_la_capture(tmp_path, monkeypatch):
    png = tmp_path / "capture.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"1" * 200)
    with session_scope() as session:
        target = Target(
            name="Reprise Drive",
            url="https://example.com/",
            run_time="09:00",
            organization_id=None,
        )
        session.add(target)
        session.commit()
        run = Run(
            target_id=target.id,
            trigger=TriggerType.manual,
            capture_date="2026-07-25",
            status=RunStatus.success,
            screenshot_path=str(png),
            drive_status="failed",
            drive_next_retry_at=utcnow() - timedelta(minutes=1),
        )
        session.add(run)
        session.commit()
        run_id = run.id

    monkeypatch.setattr(settings, "storage_backend", "google_drive")
    monkeypatch.setattr(
        drive_sync.drive_client,
        "is_configured",
        lambda: True,
    )
    calls: list[Path] = []

    def fake_upload(path, _target, _date, _filename):
        calls.append(path)
        return drive_sync.DrivePlacement(
            upload=UploadResult(
                file_id="drive-file",
                folder_id="drive-folder",
                web_link="https://drive.google.com/file/d/drive-file/view",
            ),
            folders=("2026-07-25", "organization-legacy", "example.com"),
        )

    monkeypatch.setattr(drive_sync, "upload_capture", fake_upload)
    stats = drive_sync.retry_due_uploads()

    assert stats.uploaded == 1
    assert calls == [png]
    with session_scope() as session:
        run = session.get(Run, run_id)
        assert run.drive_status == "uploaded"
        assert run.drive_file_id == "drive-file"


@pytest.mark.asyncio
async def test_echec_drive_conserve_la_capture_reussie(tmp_path, monkeypatch):
    with session_scope() as session:
        target = Target(
            name="Capture locale fiable",
            url="https://example.com/",
            run_time="09:00",
            organization_id=None,
        )
        session.add(target)
        session.flush()
        run = Run(
            target_id=target.id,
            trigger=TriggerType.manual,
            capture_date="2026-07-25",
            status=RunStatus.running,
        )
        session.add(run)
        session.commit()
        run_id = run.id

    monkeypatch.setattr(settings, "storage_backend", "google_drive")
    monkeypatch.setattr(settings, "screenshot_dir", str(tmp_path / "screenshots"))
    capture_calls = 0

    async def fake_capture(_target, destination, **_kwargs):
        nonlocal capture_calls
        capture_calls += 1
        payload = b"\x89PNG\r\n\x1a\n" + b"capture" * 40
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        return CaptureResult(
            path=destination,
            size_bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            page_title="Page",
            final_url="https://example.com/",
            scroll_steps=12,
            document_height=12000,
        )

    monkeypatch.setattr(runner, "capture_page", fake_capture)
    monkeypatch.setattr(runner, "make_thumbnail", lambda _path: None)
    monkeypatch.setattr(
        drive_sync,
        "upload_capture",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("Drive temporairement indisponible")
        ),
    )

    with session_scope() as session:
        run = session.get(Run, run_id)
        target = session.get(Target, run.target_id)
        await runner._attempt_once(session, run, target, 1, force=True)

    with session_scope() as session:
        run = session.get(Run, run_id)
        assert capture_calls == 1
        assert run.screenshot_path
        assert Path(run.screenshot_path).is_file()
        assert run.drive_status == "failed"
        assert run.drive_attempts == 1
        assert "temporairement indisponible" in (run.drive_last_error or "")
