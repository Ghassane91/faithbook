"""Sauvegarde cohérente des données nécessaires à la reprise de FaithBook.

Usage :
    python scripts/backup.py
    python scripts/backup.py --output D:/Sauvegardes/faithbook.zip
    python scripts/backup.py --include-secrets --include-captures

L'archive contient un dump PostgreSQL lorsque le service `db` tourne, ou une
copie cohérente de SQLite pour les anciennes installations. Elle ajoute les
coffres de profils, la clé locale et le fichier .env.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

BACKUP_FORMAT = 1
ENCRYPTED_MAGIC = b"FAITHBOOK-BACKUP-V1\n"
_SALT_SIZE = 16
_NONCE_SIZE = 12
_TAG_SIZE = 16


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_sqlite(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_db = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    target_db = sqlite3.connect(destination)
    try:
        source_db.backup(target_db)
    finally:
        target_db.close()
        source_db.close()


def _compose_service_running(project_root: Path, service: str) -> bool:
    try:
        result = subprocess.run(
            ["docker", "compose", "ps", "--status", "running", "-q", service],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


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


def _dump_postgres(project_root: Path, destination: Path) -> None:
    user = _env_value(project_root, "POSTGRES_USER", "faithbook")
    database = _env_value(project_root, "POSTGRES_DB", "faithbook")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as stream:
        result = subprocess.run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "db",
                "pg_dump",
                "-U",
                user,
                "-d",
                database,
                "--format=custom",
                "--no-owner",
                "--no-privileges",
            ],
            cwd=project_root,
            stdout=stream,
            stderr=subprocess.PIPE,
            timeout=300,
            check=False,
        )
    if result.returncode != 0:
        destination.unlink(missing_ok=True)
        raise RuntimeError(
            "Sauvegarde PostgreSQL impossible : "
            + result.stderr.decode("utf-8", errors="replace")
        )


def _copy_optional(source: Path, destination: Path) -> None:
    if source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    elif source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=True)


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    if len(passphrase) < 12:
        raise ValueError("Le mot de passe de sauvegarde doit contenir au moins 12 caractères.")
    return Scrypt(salt=salt, length=32, n=2**14, r=8, p=1).derive(
        passphrase.encode("utf-8")
    )


def encrypt_archive(source_zip: Path, destination: Path, passphrase: str) -> None:
    salt = os.urandom(_SALT_SIZE)
    nonce = os.urandom(_NONCE_SIZE)
    key = _derive_key(passphrase, salt)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(ENCRYPTED_MAGIC + salt)

    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    with source_zip.open("rb") as source, temporary.open("wb") as target:
        target.write(ENCRYPTED_MAGIC)
        target.write(salt)
        target.write(nonce)
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            target.write(encryptor.update(chunk))
        target.write(encryptor.finalize())
        target.write(encryptor.tag)
    temporary.replace(destination)


def is_encrypted_backup(path: Path) -> bool:
    with path.open("rb") as stream:
        return stream.read(len(ENCRYPTED_MAGIC)) == ENCRYPTED_MAGIC


def decrypt_archive(source: Path, destination_zip: Path, passphrase: str) -> None:
    size = source.stat().st_size
    header_size = len(ENCRYPTED_MAGIC) + _SALT_SIZE + _NONCE_SIZE
    if size <= header_size + _TAG_SIZE:
        raise ValueError("Sauvegarde chiffrée tronquée.")
    with source.open("rb") as stream:
        if stream.read(len(ENCRYPTED_MAGIC)) != ENCRYPTED_MAGIC:
            raise ValueError("Format chiffré FaithBook invalide.")
        salt = stream.read(_SALT_SIZE)
        nonce = stream.read(_NONCE_SIZE)
        cipher_size = size - header_size - _TAG_SIZE
        stream.seek(size - _TAG_SIZE)
        tag = stream.read(_TAG_SIZE)
        stream.seek(header_size)

        key = _derive_key(passphrase, salt)
        decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
        decryptor.authenticate_additional_data(ENCRYPTED_MAGIC + salt)
        try:
            with destination_zip.open("wb") as target:
                remaining = cipher_size
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError("Sauvegarde chiffrée tronquée.")
                    remaining -= len(chunk)
                    target.write(decryptor.update(chunk))
                target.write(decryptor.finalize())
        except InvalidTag as exc:
            destination_zip.unlink(missing_ok=True)
            raise ValueError(
                "Mot de passe incorrect ou sauvegarde chiffrée corrompue."
            ) from exc


def create_backup(
    project_root: Path,
    output: Path,
    *,
    include_secrets: bool = False,
    include_captures: bool = False,
    passphrase: str | None = None,
) -> Path:
    project_root = project_root.resolve()
    database = project_root / "data" / "app.db"
    postgres_running = _compose_service_running(project_root, "db")
    if not postgres_running and not database.is_file():
        raise FileNotFoundError(
            f"Base introuvable : {database}. Lancez la commande depuis le projet FaithBook."
        )

    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="faithbook-backup-") as temp:
        payload = Path(temp) / "payload"
        payload.mkdir()

        if postgres_running:
            _dump_postgres(project_root, payload / "data" / "postgres.dump")
        else:
            _copy_sqlite(database, payload / "data" / "app.db")
        _copy_optional(project_root / "data" / ".session_key", payload / "data" / ".session_key")
        _copy_optional(project_root / "data" / "profiles", payload / "data" / "profiles")
        _copy_optional(project_root / ".env", payload / ".env")

        if include_secrets:
            _copy_optional(project_root / "secrets", payload / "secrets")
        if include_captures:
            _copy_optional(project_root / "captures", payload / "captures")
            _copy_optional(
                project_root / "data" / "screenshots",
                payload / "data" / "screenshots",
            )

        files = []
        for path in sorted(p for p in payload.rglob("*") if p.is_file()):
            relative = path.relative_to(payload).as_posix()
            files.append(
                {
                    "path": relative,
                    "size": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
        manifest = {
            "format": BACKUP_FORMAT,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "application": "FaithBook",
            "database": "postgresql" if postgres_running else "sqlite",
            "files": files,
        }
        (payload / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        inner_zip = Path(temp) / "faithbook.zip"
        with zipfile.ZipFile(
            inner_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
        ) as archive:
            for path in sorted(p for p in payload.rglob("*") if p.is_file()):
                archive.write(path, path.relative_to(payload).as_posix())
        if passphrase:
            encrypt_archive(inner_zip, output, passphrase)
        else:
            temporary_output = output.with_suffix(output.suffix + ".tmp")
            temporary_output.unlink(missing_ok=True)
            shutil.copy2(inner_zip, temporary_output)
            temporary_output.replace(output)

    try:
        os.chmod(output, 0o600)
    except OSError:
        pass
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--include-secrets", action="store_true")
    parser.add_argument("--include-captures", action="store_true")
    parser.add_argument(
        "--unencrypted",
        action="store_true",
        help="Crée un ZIP en clair (déconseillé).",
    )
    args = parser.parse_args()

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output = args.output or args.project_root / "backups" / f"faithbook-{stamp}.fbk"
    passphrase = None
    if not args.unencrypted:
        passphrase = os.environ.get("FAITHBOOK_BACKUP_PASSPHRASE")
        if not passphrase:
            first = getpass.getpass("Mot de passe de sauvegarde (12 caractères minimum) : ")
            second = getpass.getpass("Confirmez le mot de passe : ")
            if first != second:
                raise SystemExit("Les mots de passe ne correspondent pas.")
            passphrase = first
    result = create_backup(
        args.project_root,
        output,
        include_secrets=args.include_secrets,
        include_captures=args.include_captures,
        passphrase=passphrase,
    )
    print(f"Sauvegarde créée : {result}")
    print("IMPORTANT : cette archive contient des sessions et des clés. Gardez-la privée.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
