"""Tests du stockage compatible S3 (phase 3d).

Aucun appel reseau : on verifie la composition des cles et le routage du
client selon STORAGE_BACKEND.
"""

import pytest

from app.config import settings
from app.services import drive_sync
from app.services.drive import drive_client
from app.services.s3 import S3Client, s3_client


@pytest.fixture
def client_s3(monkeypatch):
    monkeypatch.setattr(settings, "storage_backend", "s3")
    monkeypatch.setattr(settings, "s3_bucket", "faithbook-test")
    monkeypatch.setattr(settings, "s3_access_key_id", "cle")
    monkeypatch.setattr(settings, "s3_secret_access_key", "secret")
    monkeypatch.setattr(settings, "s3_prefix", "")
    return S3Client()


def test_non_configure_sans_bucket(monkeypatch):
    monkeypatch.setattr(settings, "storage_backend", "s3")
    monkeypatch.setattr(settings, "s3_bucket", "")
    assert S3Client().is_configured() is False


def test_configure_avec_les_reglages(client_s3):
    assert client_s3.is_configured() is True


def test_ensure_folder_compose_le_prefixe(client_s3):
    p = client_s3.ensure_folder("2026-07-26", None)
    p = client_s3.ensure_folder("organization-3", p)
    p = client_s3.ensure_folder("facebook.com-spypoint.ca", p)
    assert p == "2026-07-26/organization-3/facebook.com-spypoint.ca"


def test_ensure_folder_respecte_le_prefixe_global(monkeypatch, client_s3):
    monkeypatch.setattr(settings, "s3_prefix", "captures/")
    assert client_s3.ensure_folder("2026-07-26", None) == "captures/2026-07-26"


def test_construction_de_la_cle(client_s3):
    assert S3Client._key("2026-07-26/organization-3", "capture.png") == (
        "2026-07-26/organization-3/capture.png"
    )


def test_routage_vers_s3(monkeypatch):
    monkeypatch.setattr(settings, "storage_backend", "s3")
    assert drive_sync._client() is s3_client


def test_routage_vers_drive(monkeypatch):
    monkeypatch.setattr(settings, "storage_backend", "google_drive")
    assert drive_sync._client() is drive_client


def test_routage_local_reste_sur_drive(monkeypatch):
    monkeypatch.setattr(settings, "storage_backend", "local")
    assert drive_sync._client() is drive_client