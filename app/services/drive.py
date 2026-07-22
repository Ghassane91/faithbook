from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive"]
FOLDER_MIME = "application/vnd.google-apps.folder"


class DriveNotConfigured(RuntimeError):
    pass


def escape_query_value(value: str) -> str:
    """Echappe une valeur pour une requete Drive `q`.

    L'antislash doit etre echappe AVANT l'apostrophe, sinon l'antislash ajoute
    par l'echappement de l'apostrophe serait lui-meme redouble.
    """
    return value.replace("\\", "\\\\").replace("'", "\\'")


@dataclass
class UploadResult:
    file_id: str
    folder_id: str
    web_link: str
    deduplicated: bool = False


class DriveClient:
    """Client Google Drive (compte de service).

    Rappel important : un compte de service n'a pas de quota de stockage propre.
    Le dossier parent doit donc etre soit un dossier de votre Drive partage avec
    l'adresse du compte de service, soit un dossier d'un Drive partage (Shared Drive).
    """

    def __init__(self) -> None:
        self._service = None
        self._lock = threading.Lock()

    # -- infra -------------------------------------------------------------
    def is_configured(self) -> bool:
        return (
            settings.storage_backend == "google_drive"
            and bool(settings.google_drive_parent_folder_id)
            and Path(settings.google_service_account_file).is_file()
        )

    def _get_service(self):
        if self._service is not None:
            return self._service
        with self._lock:
            if self._service is not None:
                return self._service
            if not self.is_configured():
                raise DriveNotConfigured(
                    "Google Drive non configure : verifiez STORAGE_BACKEND, "
                    "GOOGLE_SERVICE_ACCOUNT_FILE et GOOGLE_DRIVE_PARENT_FOLDER_ID."
                )
            from google.oauth2 import service_account
            from googleapiclient.discovery import build

            creds = service_account.Credentials.from_service_account_file(
                settings.google_service_account_file, scopes=SCOPES
            )
            self._service = build("drive", "v3", credentials=creds, cache_discovery=False)
            return self._service

    @property
    def _shared_drive_kwargs(self) -> dict:
        kwargs = {"supportsAllDrives": True}
        return kwargs

    def _list_kwargs(self) -> dict:
        kwargs = {"supportsAllDrives": True, "includeItemsFromAllDrives": True}
        if settings.google_drive_shared_drive_id:
            kwargs.update(corpora="drive", driveId=settings.google_drive_shared_drive_id)
        return kwargs

    # -- operations --------------------------------------------------------
    def check_access(self) -> dict:
        """Verifie que le dossier parent est accessible. Leve une exception sinon."""
        service = self._get_service()
        meta = (
            service.files()
            .get(
                fileId=settings.google_drive_parent_folder_id,
                fields="id,name,mimeType",
                **self._shared_drive_kwargs,
            )
            .execute()
        )
        return meta

    def ensure_folder(self, name: str, parent_id: str | None = None) -> str:
        """Retourne l'ID du dossier `name` sous `parent_id`, en le creant si besoin."""
        service = self._get_service()
        parent = parent_id or settings.google_drive_parent_folder_id
        safe_name = escape_query_value(name)
        query = (
            f"name = '{safe_name}' and mimeType = '{FOLDER_MIME}' "
            f"and '{parent}' in parents and trashed = false"
        )
        found = (
            service.files()
            .list(q=query, fields="files(id,name)", pageSize=1, **self._list_kwargs())
            .execute()
        )
        files = found.get("files", [])
        if files:
            return files[0]["id"]

        created = (
            service.files()
            .create(
                body={"name": name, "mimeType": FOLDER_MIME, "parents": [parent]},
                fields="id",
                **self._shared_drive_kwargs,
            )
            .execute()
        )
        logger.info("Dossier Drive cree : %s (%s)", name, created["id"])
        return created["id"]

    def find_file(self, name: str, folder_id: str) -> dict | None:
        service = self._get_service()
        safe_name = escape_query_value(name)
        query = f"name = '{safe_name}' and '{folder_id}' in parents and trashed = false"
        found = (
            service.files()
            .list(
                q=query,
                fields="files(id,name,webViewLink,size)",
                pageSize=1,
                **self._list_kwargs(),
            )
            .execute()
        )
        files = found.get("files", [])
        return files[0] if files else None

    def upload(self, path: Path, folder_id: str, filename: str | None = None) -> UploadResult:
        """Televerse le fichier ; si un fichier de meme nom existe deja, ne le duplique pas."""
        from googleapiclient.http import MediaFileUpload

        service = self._get_service()
        name = filename or path.name

        existing = self.find_file(name, folder_id)
        if existing:
            logger.info("Fichier deja present sur Drive, upload ignore : %s", name)
            return UploadResult(
                file_id=existing["id"],
                folder_id=folder_id,
                web_link=existing.get("webViewLink", ""),
                deduplicated=True,
            )

        media = MediaFileUpload(str(path), mimetype="image/png", resumable=True)
        created = (
            service.files()
            .create(
                body={"name": name, "parents": [folder_id]},
                media_body=media,
                fields="id,webViewLink",
                **self._shared_drive_kwargs,
            )
            .execute()
        )
        return UploadResult(
            file_id=created["id"],
            folder_id=folder_id,
            web_link=created.get("webViewLink", ""),
        )


drive_client = DriveClient()
