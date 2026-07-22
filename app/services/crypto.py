from __future__ import annotations

import logging
import os
import stat
import tarfile
import tempfile
from io import BytesIO
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

logger = logging.getLogger(__name__)

_fernet: Fernet | None = None


def _load_key() -> bytes:
    """Clé de chiffrement, par ordre de priorité :

    1. SESSION_ENCRYPTION_KEY (variable d'environnement) — recommandé en prod.
    2. Un fichier /data/.session_key généré au premier démarrage (permissions
       600), pour ne pas bloquer un usage local. Un avertissement invite à la
       déplacer en variable d'environnement.
    """
    env_key = settings.session_encryption_key.strip()
    if env_key:
        return env_key.encode("ascii")

    key_file = Path(settings.data_dir) / ".session_key"
    if key_file.is_file():
        return key_file.read_bytes().strip()

    key = Fernet.generate_key()
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_bytes(key)
    try:
        os.chmod(key_file, stat.S_IRUSR | stat.S_IWUSR)  # 600
    except OSError:  # pragma: no cover - systemes sans chmod POSIX
        pass
    logger.warning(
        "SESSION_ENCRYPTION_KEY absente : une cle a ete generee dans %s. "
        "Pour la production, copiez-la dans la variable d'environnement "
        "SESSION_ENCRYPTION_KEY et sauvegardez-la : sans elle, les sessions "
        "chiffrees deviennent illisibles.",
        key_file,
    )
    return key


def _get() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_load_key())
    return _fernet


# --- Chiffrement de courtes valeurs (cookies exportes, storage_state) -----
def encrypt_text(clair: str) -> str:
    return _get().encrypt(clair.encode("utf-8")).decode("ascii")


def decrypt_text(chiffre: str | None) -> str | None:
    if not chiffre:
        return None
    try:
        return _get().decrypt(chiffre.encode("ascii")).decode("utf-8")
    except InvalidToken:
        logger.error("Dechiffrement impossible : cle changee ou donnee corrompue.")
        return None


# --- Coffre de profil navigateur ------------------------------------------
# Un profil Chromium persistant contient des cookies en clair. Pour respecter
# le chiffrement au repos, on ne conserve sur disque QUE l'archive chiffree du
# profil. On la dechiffre dans un dossier de travail temporaire le temps d'une
# connexion ou d'une capture, puis on la rechiffre et on efface le clair.


def vault_path(profile_slug: str) -> Path:
    return Path(settings.data_dir) / "profiles" / f"{profile_slug}.tar.enc"


def profile_exists(profile_slug: str) -> bool:
    return vault_path(profile_slug).is_file()


def open_profile(profile_slug: str) -> Path:
    """Déchiffre le profil vers un dossier de travail et retourne son chemin.

    Si le coffre n'existe pas encore (premier login), retourne un dossier vide.
    L'appelant DOIT rappeler seal_profile() puis discard_profile() ensuite.
    """
    # /dev/shm (tmpfs) est vidé à chaque redémarrage du conteneur : on (re)crée
    # le dossier de travail à la volée, sinon mkdtemp échoue (FileNotFoundError).
    work_root = Path(settings.profile_work_dir)
    work_root.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f"prof-{profile_slug}-", dir=str(work_root)))
    vault = vault_path(profile_slug)
    if vault.is_file():
        blob = _get().decrypt(vault.read_bytes())
        with tarfile.open(fileobj=BytesIO(blob), mode="r:gz") as tar:
            tar.extractall(work)  # noqa: S202 - archive produite par nous, contenu maitrise
    return work


def seal_profile(profile_slug: str, work_dir: Path) -> None:
    """Rechiffre le dossier de travail dans le coffre (écriture atomique)."""
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for item in work_dir.iterdir():
            tar.add(item, arcname=item.name)
    token = _get().encrypt(buffer.getvalue())

    vault = vault_path(profile_slug)
    vault.parent.mkdir(parents=True, exist_ok=True)
    tmp = vault.with_suffix(".tmp")
    tmp.write_bytes(token)
    tmp.replace(vault)


def discard_profile(work_dir: Path) -> None:
    """Efface le dossier de travail en clair."""
    import shutil

    shutil.rmtree(work_dir, ignore_errors=True)


def delete_vault(profile_slug: str) -> None:
    vault_path(profile_slug).unlink(missing_ok=True)
