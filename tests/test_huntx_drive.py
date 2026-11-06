"""Contrats d'archivage : dates réelles, lignes partagées et reprise Drive."""
import json
import asyncio
import io
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models import (Base, BrowserDevice, BrowserLinkJob, BrowserTarget,
    HuntxDriveArtifact, Organization, Run, RunStatus, Target, TriggerType, User, utcnow)
from app.services import huntx_drive
from app.services.drive import UploadResult


@pytest.fixture
def archive(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/archive.db")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)

    @contextmanager
    def scope():
        with sessions() as session:
            yield session
            session.commit()

    monkeypatch.setattr(huntx_drive, "session_scope", scope)
    monkeypatch.setattr(huntx_drive.settings, "screenshot_dir", str(tmp_path / "captures"))
    monkeypatch.setattr(huntx_drive.settings, "google_drive_parent_folder_id", "drive-parent")
    monkeypatch.setattr(huntx_drive.settings, "google_drive_retry_batch_size", 100)
    monkeypatch.setattr(huntx_drive.settings, "storage_backend", "s3")
    with scope() as session:
        org = Organization(name="novostok", slug="novostok")
        session.add(org); session.flush()
        target = Target(organization_id=org.id, name="HuntX", url="https://huntx.example.com/app/cameras",
            enabled=True, capture_row_links=True, timezone_name="Africa/Casablanca")
        session.add(target); session.flush()
        source = Run(target_id=target.id, capture_date="2026-10-08", status=RunStatus.success, trigger=TriggerType.manual)
        session.add(source); session.flush()
        identifiers = (org.id, target.id, source.id)
    yield scope, identifiers
    engine.dispose()


class FakeDrive:
    def __init__(self):
        self.folders = {}
        self.files = {}
        self.upload_calls = []
        self.ensure_calls = []
        self.fail_before = False
        self.fail_after = False

    def is_configured(self):
        return True

    def ensure_folder(self, name, parent=None):
        key = (parent, name)
        self.ensure_calls.append(key)
        self.folders.setdefault(key, f"folder-{len(self.folders) + 1}")
        return self.folders[key]

    def upload(self, path, folder, filename):
        self.upload_calls.append((path, folder, filename))
        if self.fail_before:
            self.fail_before = False
            raise RuntimeError("Drive temporairement indisponible")
        key = (folder, filename)
        existing = key in self.files
        self.files.setdefault(key, f"file-{len(self.files) + 1}")
        if self.fail_after:
            self.fail_after = False
            raise TimeoutError("Réponse réseau perdue après l'envoi")
        return UploadResult(self.files[key], folder, "https://drive.example/file", existing)


def row_image(tmp_path, row_id="17"):
    path = tmp_path / ("row-" + row_id + ".jpg")
    path.write_bytes(b"actual-row-image")
    return {"id": row_id, "marque": "Browning", "modele": "Same camera", "fichier": str(path),
        "nom": "Browning - Same camera.jpg", "captured_at": "2026-10-08T23:30:00+00:00"}


def add_job(scope, identifiers, tmp_path, references, status=RunStatus.success):
    org_id, source_target_id, source_run_id = identifiers
    path = tmp_path / "product.jpg"
    path.write_bytes(b"real-product-image")
    with scope() as session:
        user = User(email=f"device-{source_run_id}@example.com", password_hash="hashed")
        session.add(user); session.flush()
        device = BrowserDevice(organization_id=org_id, user_id=user.id, name="Chrome",
            token_hash=f"hash-{source_run_id}", expires_at=datetime.now(timezone.utc) + timedelta(days=10))
        session.add(device); session.flush()
        target = Target(organization_id=org_id, name="Product", url="https://www.amazon.com/dp/one", enabled=True)
        session.add(target); session.flush()
        session.add(BrowserTarget(target_id=target.id, device_id=device.id, source_target_id=source_target_id))
        session.flush()
        job = BrowserLinkJob(target_id=target.id, source_run_id=source_run_id,
            row_references=json.dumps(references))
        run = Run(target_id=target.id, capture_date="2026-10-09", status=status,
            trigger=TriggerType.manual, finished_at=utcnow(), screenshot_path=str(path) if status == RunStatus.success else None,
            error_message="Validation humaine demandée" if status == RunStatus.suspended else None)
        session.add_all([job, run]); session.flush()
        return job.id, run.id


def test_every_row_keeps_its_capture_and_actual_date(archive, tmp_path, monkeypatch):
    scope, identifiers = archive
    with scope() as session:
        session.get(Target, identifiers[1]).timezone_name = "Europe/Paris"
    prices = [{"id": "17", "marque": "Browning", "modele": "Same camera", "cellules": {
        "AMAZON": {"texte": "$29.99", "url": "https://www.amazon.com/dp/one", "date": "2026-10-08"}},
        "captured_at": "2026-10-08T23:30:00+00:00"},
        {"id": "18", "marque": "Browning", "modele": "Same camera", "cellules": {}}]
    rows = [row_image(tmp_path, "17"), row_image(tmp_path, "18")]
    with scope() as session:
        first = huntx_drive.register_source_artifacts(session, identifiers[2], rows, prices, "2026-10-08")
        again = huntx_drive.register_source_artifacts(session, identifiers[2], rows, prices, "2026-10-08")
        assert [item.id for item in first] == [item.id for item in again]
        assert len(first) == 5  # each row JSON + image and the CSV
        assert all(item.capture_date == "2026-10-09" for item in first)
        assert len({item.row_label for item in first if item.row_label}) == 2
        metadata = next(item for item in first if item.filename.endswith(".json") and item.row_key == "17")
        assert json.loads(Path(metadata.local_path).read_text(encoding="utf-8"))["cellules"]["AMAZON"]["url"]
        assert all(Path(item.local_path).is_file() for item in first)
    fake = FakeDrive()
    monkeypatch.setattr(huntx_drive, "drive_client", fake)
    stats = huntx_drive.retry_due_artifacts()
    assert stats.uploaded == 5 and stats.failed == 0
    assert any(name == "2026-10-09" for _, name in fake.folders)
    assert any(name == f"novostok [org-{identifiers[0]}]" for _, name in fake.folders)
    assert all(Path(row["fichier"]).is_file() for row in rows)


def test_drive_failure_survives_and_retry_does_not_duplicate(archive, tmp_path, monkeypatch):
    scope, identifiers = archive
    with scope() as session:
        artifact = huntx_drive.register_source_artifacts(session, identifiers[2], [row_image(tmp_path)], [], "2026-10-08")[0]
        artifact_id = artifact.id
    fake = FakeDrive(); fake.fail_after = True
    monkeypatch.setattr(huntx_drive, "drive_client", fake)
    assert huntx_drive.retry_due_artifacts().failed == 1
    assert len(fake.ensure_calls) == 8  # failure invalidates the four cached folders
    with scope() as session:
        artifact = session.get(HuntxDriveArtifact, artifact_id)
        assert artifact.drive_status == "failed" and artifact.attempts == 1
        assert artifact.next_retry_at and "réseau" in artifact.last_error
        assert Path(artifact.local_path).is_file()
        artifact.next_retry_at = utcnow() - timedelta(seconds=1)
    assert huntx_drive.retry_due_artifacts().uploaded == 1
    assert len(fake.files) == 2  # one JSON + one JPG, despite response lost
    assert huntx_drive.retry_due_artifacts().selected == 0
    with scope() as session:
        artifact = session.get(HuntxDriveArtifact, artifact_id)
        assert artifact.drive_status == "uploaded" and artifact.attempts == 2
        assert artifact.next_retry_at is None and artifact.last_error is None
        assert Path(artifact.local_path).is_file()


def test_folder_lookups_are_shared_by_json_and_photo_in_one_batch(archive, tmp_path, monkeypatch):
    scope, identifiers = archive
    with scope() as session:
        huntx_drive.register_source_artifacts(session, identifiers[2], [row_image(tmp_path)], [], "2026-10-08")
    fake = FakeDrive(); monkeypatch.setattr(huntx_drive, "drive_client", fake)
    result = huntx_drive.retry_due_artifacts()
    assert result.uploaded == 2 and result.failed == 0
    assert len(fake.ensure_calls) == 4  # organization, HuntX, date and row each once
    assert len(set(fake.ensure_calls)) == 4
    assert fake.upload_calls[0][1] == fake.upload_calls[1][1]


def test_shared_product_is_archived_for_every_referenced_row(archive, tmp_path, monkeypatch):
    scope, identifiers = archive
    references = [{"id": "17", "marque": "Brand", "modele": "First", "colonne": "AMAZON"},
        {"id": "18", "marque": "Brand", "modele": "Second", "colonne": "AMAZON"}]
    job_id, run_id = add_job(scope, identifiers, tmp_path, references)
    with scope() as session:
        artifacts = huntx_drive.register_product_artifacts(session, session.get(BrowserLinkJob, job_id), session.get(Run, run_id))
        assert len(artifacts) == 4
        assert len({item.row_key for item in artifacts}) == 2
        assert all(item.capture_date == "2026-10-09" for item in artifacts)
        photos = [item for item in artifacts if item.filename.endswith(".jpg")]
        assert len({item.local_path for item in photos}) == 1  # durable file is shared locally
        assert len({item.filename for item in photos}) == 2
        again = huntx_drive.register_product_artifacts(session, session.get(BrowserLinkJob, job_id), session.get(Run, run_id))
        assert [item.id for item in again] == [item.id for item in artifacts]
    fake = FakeDrive(); monkeypatch.setattr(huntx_drive, "drive_client", fake)
    assert huntx_drive.retry_due_artifacts().uploaded == 4
    assert any(name == "Ligne 17 - Brand First" for _, name in fake.folders)
    assert any(name == "Ligne 18 - Brand Second" for _, name in fake.folders)


def test_failed_page_is_status_document_not_successful_photo(archive, tmp_path):
    scope, identifiers = archive
    job_id, run_id = add_job(scope, identifiers, tmp_path, [{"id": "17", "colonne": "AMAZON"}], RunStatus.suspended)
    with scope() as session:
        artifacts = huntx_drive.register_product_artifacts(session, session.get(BrowserLinkJob, job_id), session.get(Run, run_id))
        assert len(artifacts) == 1 and artifacts[0].filename.endswith(".json")
        document = json.loads(Path(artifacts[0].local_path).read_text(encoding="utf-8"))
        assert document["status"] == "suspended" and not document["capture_available"]
        assert document["reason"] == "Validation humaine demandée"


def test_organizations_with_same_label_cannot_share_folder(archive, tmp_path):
    scope, identifiers = archive
    with scope() as session:
        one = huntx_drive.register_source_artifacts(session, identifiers[2], [row_image(tmp_path)], [], "2026-10-08")[0]
        other_org = Organization(name="novostok", slug="other-novostok")
        session.add(other_org); session.flush()
        other_target = Target(organization_id=other_org.id, name="HuntX", url="https://huntx.example.com/", enabled=True)
        session.add(other_target); session.flush()
        other_run = Run(target_id=other_target.id, capture_date="2026-10-08", status=RunStatus.success, trigger=TriggerType.manual)
        session.add(other_run); session.flush()
        two = huntx_drive.register_source_artifacts(session, other_run.id, [row_image(tmp_path)], [], "2026-10-08")[0]
        assert huntx_drive.folder_names(session, one)[0] != huntx_drive.folder_names(session, two)[0]
        assert one.local_path != two.local_path


def test_cross_tenant_product_is_rejected_before_writing(archive, tmp_path):
    scope, identifiers = archive
    job_id, run_id = add_job(scope, identifiers, tmp_path, [{"id": "17"}])
    with scope() as session:
        other_org = Organization(name="Other", slug="other")
        session.add(other_org); session.flush()
        run = session.get(Run, run_id)
        session.get(Target, run.target_id).organization_id = other_org.id
        with pytest.raises(ValueError, match="hors de l'organisation"):
            huntx_drive.register_product_artifacts(session, session.get(BrowserLinkJob, job_id), run)
        assert not session.scalars(select(HuntxDriveArtifact)).all()


def test_legacy_payload_without_row_id_is_preserved(archive, tmp_path):
    scope, identifiers = archive
    row = row_image(tmp_path); row.pop("id"); row.pop("marque"); row.pop("modele"); row.pop("captured_at")
    with scope() as session:
        artifacts = huntx_drive.register_source_artifacts(session, identifiers[2], [row], [], "2026-10-08")
        assert len(artifacts) == 2
        assert all(item.capture_date == "2026-10-08" for item in artifacts)
        assert "Browning - Same camera" in artifacts[0].row_label


def test_missing_file_is_retained_as_retryable_error(archive, tmp_path, monkeypatch):
    scope, identifiers = archive
    row = row_image(tmp_path)
    with scope() as session:
        artifacts = huntx_drive.register_source_artifacts(session, identifiers[2], [row], [], "2026-10-08")
        image = next(item for item in artifacts if item.filename.endswith(".jpg"))
        image_id = image.id
        # Une perte réelle après l'enregistrement reste visible et réessayable.
        Path(image.local_path).unlink()
    fake = FakeDrive(); monkeypatch.setattr(huntx_drive, "drive_client", fake)
    stats = huntx_drive.retry_due_artifacts()
    assert stats.uploaded == 1 and stats.failed == 1
    with scope() as session:
        image = session.get(HuntxDriveArtifact, image_id)
        assert image.drive_status == "failed" and "introuvable" in image.last_error
        assert image.next_retry_at is not None


@pytest.mark.parametrize("permanent", [False, True])
def test_row_capture_retries_and_continues_to_next_row(tmp_path, permanent, archive, monkeypatch):
    from app.services.fiches_liens import capturer_lignes
    buffer = io.BytesIO()
    Image.new("RGB", (20, 10), "white").save(buffer, format="PNG")
    picture = buffer.getvalue()

    class Locator:
        first = property(lambda self: self)

        def __init__(self, kind="table", row=0, cell=0):
            self.kind, self.row, self.cell = kind, row, cell
            self.attempts = 0

        async def count(self):
            return 2 if self.kind == "rows" else 1

        def locator(self, selector):
            return Locator({"thead": "header", "tbody tr[data-id]": "rows", "td": "cells"}[selector], self.row)

        def nth(self, index):
            return row_locators[index] if self.kind == "rows" else Locator("cell", self.row, index)

        async def inner_text(self):
            return "Same brand" if self.cell == 0 else "Same model"

        async def get_attribute(self, _name):
            return str(self.row + 17)

        async def scroll_into_view_if_needed(self):
            pass

        async def screenshot(self, **_kwargs):
            self.attempts += 1
            if self.kind == "row" and self.row == 0 and (permanent or self.attempts < 3):
                raise RuntimeError("Ligne temporairement détachée")
            return picture

    row_locators = [Locator("row", 0), Locator("row", 1)]

    class Page:
        def locator(self, _selector):
            return Locator()

    rows = asyncio.run(capturer_lignes(Page(), tmp_path / "rows"))
    assert len(rows) == 2 and {item["id"] for item in rows} == {"17", "18"}
    assert row_locators[0].attempts == 3
    assert all(item["captured_at"] for item in rows)
    assert Path(rows[1]["fichier"]).is_file()
    assert bool(rows[0].get("capture_error")) == permanent
    assert Path(rows[0]["fichier"]).is_file() != permanent
    scope, identifiers = archive
    with scope() as session:
        artifacts = huntx_drive.register_source_artifacts(session, identifiers[2], rows, [], "2026-10-08")
        photos = [item for item in artifacts if item.filename.endswith(".jpg")]
        assert len(photos) == (1 if permanent else 2)
        document = next(item for item in artifacts if item.row_key == "17" and item.filename.endswith(".json"))
        metadata = json.loads(Path(document.local_path).read_text(encoding="utf-8"))
        assert metadata["row_capture_available"] != permanent
        if permanent:
            assert "détachée" in metadata["capture_error"]
    fake = FakeDrive(); monkeypatch.setattr(huntx_drive, "drive_client", fake)
    result = huntx_drive.retry_due_artifacts()
    assert result.failed == 0 and result.uploaded == (3 if permanent else 4)
    assert huntx_drive.retry_due_artifacts().selected == 0


@pytest.mark.parametrize("empty", [False, True])
def test_product_without_image_uploads_only_status_document(archive, tmp_path, monkeypatch, empty):
    scope, identifiers = archive
    job_id, run_id = add_job(scope, identifiers, tmp_path, [{"id": "17"}])
    with scope() as session:
        run = session.get(Run, run_id)
        if empty:
            Path(run.screenshot_path).write_bytes(b"")
        else:
            Path(run.screenshot_path).unlink()
        artifacts = huntx_drive.register_product_artifacts(session, session.get(BrowserLinkJob, job_id), run)
        assert len(artifacts) == 1 and artifacts[0].filename.endswith(".json")
        metadata = json.loads(Path(artifacts[0].local_path).read_text(encoding="utf-8"))
        assert not metadata["capture_available"]
        assert "absente" in metadata["reason"]
    fake = FakeDrive(); monkeypatch.setattr(huntx_drive, "drive_client", fake)
    result = huntx_drive.retry_due_artifacts()
    assert result.failed == 0 and result.uploaded == 1
