"""Vérifie puis restaure une sauvegarde FaithBook.

La plateforme doit être arrêtée avant la restauration :
    docker compose down
    python scripts/restore.py backups/faithbook-AAAAMMJJ-HHMMSS.zip

Le fichier .env et le dossier secrets ne sont restaurés que sur demande
explicite. Une sauvegarde de sécurité de l'état courant est créée avant toute
écriture.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import subprocess
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

if __package__:
    from .backup import (
        BACKUP_FORMAT,
        create_backup,
        decrypt_archive,
        is_encrypted_backup,
        sha256_file,
    )
else:
    from backup import (
        BACKUP_FORMAT,
        create_backup,
        decrypt_archive,
        is_encrypted_backup,
        sha256_file,
    )


def _stack_running(project_root: Path) -> bool:
    try:
        result = subprocess.run(
            ["docker", "compose", "ps", "--status", "running", "-q"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _safe_members(archive: zipfile.ZipFile) -> None:
    for item in archive.infolist():
        path = PurePosixPath(item.filename)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"Chemin dangereux dans l'archive : {item.filename}")


def verify_backup(extracted: Path) -> dict:
    manifest_path = extracted / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("manifest.json absent de la sauvegarde")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != BACKUP_FORMAT:
        raise ValueError(f"Format de sauvegarde non supporté : {manifest.get('format')}")
    if manifest.get("application") != "FaithBook":
        raise ValueError("Cette archive n'est pas une sauvegarde FaithBook")
    for item in manifest.get("files", []):
        relative = PurePosixPath(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Chemin dangereux dans le manifeste : {item['path']}")
        path = extracted.joinpath(*relative.parts)
        if not path.is_file():
            raise ValueError(f"Fichier manquant : {item['path']}")
        if path.stat().st_size != item["size"] or sha256_file(path) != item["sha256"]:
            raise ValueError(f"Fichier corrompu : {item['path']}")
    if not (
        (extracted / "data" / "app.db").is_file()
        or (extracted / "data" / "postgres.dump").is_file()
    ):
        raise ValueError("La sauvegarde ne contient aucune base FaithBook")
    return manifest


def _env_value(project_root: Path, key: str, default: str) -> str:
    env_file = project_root / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                name, value = stripped.split("=", 1)
                if name.strip() == key and value.strip():
                    return value.strip()
    return default


def _start_database(project_root: Path) -> None:
    subprocess.run(
        ["docker", "compose", "up", "-d", "db"],
        cwd=project_root,
        check=True,
        timeout=180,
    )
    user = _env_value(project_root, "POSTGRES_USER", "faithbook")
    database = _env_value(project_root, "POSTGRES_DB", "faithbook")
    for _ in range(30):
        ready = subprocess.run(
            ["docker", "compose", "exec", "-T", "db", "pg_isready", "-U", user, "-d", database],
            cwd=project_root,
            capture_output=True,
            timeout=15,
            check=False,
        )
        if ready.returncode == 0:
            return
        time.sleep(2)
    raise RuntimeError("PostgreSQL n'est pas devenu prêt.")


def _restore_postgres(project_root: Path, dump: Path) -> None:
    user = _env_value(project_root, "POSTGRES_USER", "faithbook")
    database = _env_value(project_root, "POSTGRES_DB", "faithbook")
    with dump.open("rb") as stream:
        result = subprocess.run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "db",
                "pg_restore",
                "-U",
                user,
                "-d",
                database,
                "--clean",
                "--if-exists",
                "--no-owner",
                "--no-privileges",
            ],
            cwd=project_root,
            stdin=stream,
            capture_output=True,
            timeout=600,
            check=False,
        )
    if result.returncode != 0:
        raise RuntimeError(
            "Restauration PostgreSQL impossible : "
            + result.stderr.decode("utf-8", errors="replace")
        )


def restore_backup(
    project_root: Path,
    archive_path: Path,
    *,
    restore_env: bool = False,
    restore_secrets: bool = False,
    restore_captures: bool = False,
    force: bool = False,
    passphrase: str | None = None,
) -> Path | None:
    project_root = project_root.resolve()
    archive_path = archive_path.resolve()
    if not archive_path.is_file():
        raise FileNotFoundError(f"Sauvegarde introuvable : {archive_path}")
    if _stack_running(project_root) and not force:
        raise RuntimeError(
            "FaithBook tourne encore. Exécutez `docker compose down` avant la restauration."
        )

    with tempfile.TemporaryDirectory(prefix="faithbook-restore-") as temp:
        temp_root = Path(temp)
        zip_path = archive_path
        if is_encrypted_backup(archive_path):
            if not passphrase:
                raise ValueError("Mot de passe requis pour cette sauvegarde chiffrée.")
            zip_path = temp_root / "decrypted.zip"
            decrypt_archive(archive_path, zip_path, passphrase)
        extracted = temp_root / "extracted"
        extracted.mkdir()
        with zipfile.ZipFile(zip_path) as archive:
            _safe_members(archive)
            archive.extractall(extracted)
        verify_backup(extracted)

        rollback = None
        postgres_dump = extracted / "data" / "postgres.dump"
        if postgres_dump.is_file():
            _start_database(project_root)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            suffix = ".fbk" if passphrase else ".zip"
            rollback = project_root / "backups" / f"pre-restore-{stamp}{suffix}"
            create_backup(project_root, rollback, passphrase=passphrase)
            _restore_postgres(project_root, postgres_dump)

        current_db = project_root / "data" / "app.db"
        if not postgres_dump.is_file() and current_db.is_file():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            suffix = ".fbk" if passphrase else ".zip"
            rollback = project_root / "backups" / f"pre-restore-{stamp}{suffix}"
            create_backup(project_root, rollback, passphrase=passphrase)

        data_dir = project_root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        for transient in ("app.db-wal", "app.db-shm"):
            (data_dir / transient).unlink(missing_ok=True)
        sqlite_backup = extracted / "data" / "app.db"
        if sqlite_backup.is_file():
            shutil.copy2(sqlite_backup, data_dir / "app.db")

        for relative in (Path("data/.session_key"), Path("data/profiles")):
            source = extracted / relative
            destination = project_root / relative
            if source.is_file():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            elif source.is_dir():
                shutil.copytree(source, destination, dirs_exist_ok=True)

        if restore_env and (extracted / ".env").is_file():
            shutil.copy2(extracted / ".env", project_root / ".env")
        if restore_secrets and (extracted / "secrets").is_dir():
            shutil.copytree(
                extracted / "secrets",
                project_root / "secrets",
                dirs_exist_ok=True,
            )
        if restore_captures:
            for relative in (Path("captures"), Path("data/screenshots")):
                source = extracted / relative
                if source.is_dir():
                    shutil.copytree(
                        source,
                        project_root / relative,
                        dirs_exist_ok=True,
                    )
        if postgres_dump.is_file():
            subprocess.run(
                ["docker", "compose", "stop", "db"],
                cwd=project_root,
                capture_output=True,
                timeout=60,
                check=False,
            )
    return rollback


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--restore-env", action="store_true")
    parser.add_argument("--restore-secrets", action="store_true")
    parser.add_argument("--restore-captures", action="store_true")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore la détection des conteneurs actifs (déconseillé).",
    )
    args = parser.parse_args()

    passphrase = os.environ.get("FAITHBOOK_BACKUP_PASSPHRASE")
    if is_encrypted_backup(args.archive) and not passphrase:
        passphrase = getpass.getpass("Mot de passe de la sauvegarde : ")
    rollback = restore_backup(
        args.project_root,
        args.archive,
        restore_env=args.restore_env,
        restore_secrets=args.restore_secrets,
        restore_captures=args.restore_captures,
        force=args.force,
        passphrase=passphrase,
    )
    print("Restauration terminée. Relancez : docker compose up -d --wait")
    if rollback:
        print(f"Sauvegarde de sécurité de l'ancien état : {rollback}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
