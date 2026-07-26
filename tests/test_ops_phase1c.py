from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from scripts import backup, restore


def _database(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE marker (value TEXT NOT NULL)")
        connection.execute("INSERT INTO marker VALUES (?)", (value,))


def _marker(path: Path) -> str:
    with sqlite3.connect(path) as connection:
        return connection.execute("SELECT value FROM marker").fetchone()[0]


def test_sauvegarde_coherente_et_manifest(tmp_path):
    project = tmp_path / "project"
    _database(project / "data" / "app.db", "source")
    (project / "data" / "profiles").mkdir(parents=True)
    (project / "data" / "profiles" / "compte.tar.enc").write_bytes(b"coffre")
    (project / "data" / ".session_key").write_text("cle", encoding="utf-8")
    (project / ".env").write_text("SESSION_ENCRYPTION_KEY=secret", encoding="utf-8")

    archive = backup.create_backup(project, tmp_path / "backup.zip")

    with zipfile.ZipFile(archive) as zipped:
        names = set(zipped.namelist())
        assert "data/app.db" in names
        assert "data/profiles/compte.tar.enc" in names
        assert "data/.session_key" in names
        assert ".env" in names
        manifest = json.loads(zipped.read("manifest.json"))
    assert manifest["application"] == "FaithBook"
    assert manifest["format"] == backup.BACKUP_FORMAT
    assert any(item["path"] == "data/app.db" for item in manifest["files"])


def test_verification_detecte_un_fichier_modifie(tmp_path):
    project = tmp_path / "project"
    _database(project / "data" / "app.db", "source")
    archive = backup.create_backup(project, tmp_path / "backup.zip")
    extracted = tmp_path / "extracted"
    with zipfile.ZipFile(archive) as zipped:
        zipped.extractall(extracted)
    (extracted / "data" / "app.db").write_bytes(b"corrompu")

    with pytest.raises(ValueError, match="corrompu"):
        restore.verify_backup(extracted)


def test_sauvegarde_chiffree_roundtrip(tmp_path):
    project = tmp_path / "project"
    _database(project / "data" / "app.db", "secret")
    encrypted = backup.create_backup(
        project,
        tmp_path / "backup.fbk",
        passphrase="mot-de-passe-tres-solide",
    )
    assert backup.is_encrypted_backup(encrypted)
    decrypted = tmp_path / "decrypted.zip"
    backup.decrypt_archive(
        encrypted,
        decrypted,
        "mot-de-passe-tres-solide",
    )
    with zipfile.ZipFile(decrypted) as zipped:
        assert "data/app.db" in zipped.namelist()


def test_sauvegarde_postgresql_utilise_pg_dump(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(
        backup,
        "_compose_service_running",
        lambda _project, service: service == "db",
    )
    monkeypatch.setattr(
        backup,
        "_dump_postgres",
        lambda _project, destination: (
            destination.parent.mkdir(parents=True, exist_ok=True),
            destination.write_bytes(b"PGDMP-test"),
        ),
    )

    archive = backup.create_backup(project, tmp_path / "postgres.zip")

    with zipfile.ZipFile(archive) as zipped:
        assert "data/postgres.dump" in zipped.namelist()
        assert "data/app.db" not in zipped.namelist()
        manifest = json.loads(zipped.read("manifest.json"))
        assert manifest["database"] == "postgresql"


def test_restauration_garde_env_et_cree_retour_arriere(tmp_path, monkeypatch):
    source = tmp_path / "source"
    _database(source / "data" / "app.db", "sauvegarde")
    (source / "data" / "profiles").mkdir(parents=True)
    (source / "data" / "profiles" / "compte.tar.enc").write_bytes(b"profil")
    (source / ".env").write_text("VALEUR=archive", encoding="utf-8")
    archive = backup.create_backup(source, tmp_path / "backup.zip")

    target = tmp_path / "target"
    _database(target / "data" / "app.db", "courant")
    (target / ".env").write_text("VALEUR=courante", encoding="utf-8")
    monkeypatch.setattr(restore, "_stack_running", lambda _root: False)

    rollback = restore.restore_backup(target, archive)

    assert _marker(target / "data" / "app.db") == "sauvegarde"
    assert (target / ".env").read_text(encoding="utf-8") == "VALEUR=courante"
    assert (target / "data" / "profiles" / "compte.tar.enc").read_bytes() == b"profil"
    assert rollback is not None and rollback.is_file()


def test_compose_attend_les_services_sains():
    root = Path(__file__).resolve().parents[1]
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
    assert compose.count("condition: service_healthy") == 9
    assert "faithbook-worker" in compose
    assert "faithbook-redis" in compose
    assert "faithbook-db" in compose
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY scripts ./scripts" in dockerfile
    workflow = root / ".github" / "workflows" / "ci.yml"
    assert workflow.is_file()
    text = workflow.read_text(encoding="utf-8")
    assert "python -m pytest tests/ -q" in text
    assert "npm run build" in text


def test_entree_docker_attend_vnc_reellement():
    root = Path(__file__).resolve().parents[1]
    entrypoint = (root / "docker-entrypoint.sh").read_text(encoding="utf-8")
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY docker-entrypoint.sh ./docker-entrypoint.sh" in dockerfile
    assert "port_listening 5900" in entrypoint
    assert "VNC_READY" in entrypoint
    assert "Serveur VNC indisponible" in entrypoint
    assert 'port_listening "${NOVNC_PORT:-6080}"' in entrypoint
