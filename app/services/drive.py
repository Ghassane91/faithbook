from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
    Un Drive partagé est donc recommandé ; l'autre option est la délégation
    d'autorité à l'échelle du domaine Google Workspace.
    """

    def __init__(self) -> None:
        self._service = None
        self._service_lock = threading.Lock()
        # googleapiclient/httplib2 n'est pas garanti thread-safe. Le backend
        # peut exécuter en même temps un contrôle manuel et une reprise
        # automatique : toutes les opérations d'un client sont donc sérialisées.
        self._api_lock = threading.RLock()

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
        with self._service_lock:
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
        """Vérifie que le dossier parent est accessible et accepte des enfants."""
        with self._api_lock:
            service = self._get_service()
            meta = (
                service.files()
                .get(
                    fileId=settings.google_drive_parent_folder_id,
                    fields="id,name,mimeType,capabilities(canAddChildren)",
                    **self._shared_drive_kwargs,
                )
                .execute(num_retries=settings.google_drive_api_retries)
            )
        if meta.get("mimeType") != FOLDER_MIME:
            raise DriveNotConfigured(
                "GOOGLE_DRIVE_PARENT_FOLDER_ID ne désigne pas un dossier."
            )
        if not meta.get("capabilities", {}).get("canAddChildren", False):
            raise DriveNotConfigured(
                "Le compte de service ne peut pas écrire dans le dossier parent."
            )
        return meta

    def ensure_folder(self, name: str, parent_id: str | None = None) -> str:
        """Retourne l'ID du dossier `name` sous `parent_id`, en le creant si besoin."""
        with self._api_lock:
            service = self._get_service()
            parent = parent_id or settings.google_drive_parent_folder_id
            safe_name = escape_query_value(name)
            query = (
                f"name = '{safe_name}' and mimeType = '{FOLDER_MIME}' "
                f"and '{parent}' in parents and trashed = false"
            )
            found = (
                service.files()
                .list(
                    q=query,
                    fields="files(id,name)",
                    pageSize=10,
                    orderBy="createdTime",
                    **self._list_kwargs(),
                )
                .execute(num_retries=settings.google_drive_api_retries)
            )
            files = found.get("files", [])
            if files:
                return files[0]["id"]

            created = (
                service.files()
                .create(
                    body={
                        "name": name,
                        "mimeType": FOLDER_MIME,
                        "parents": [parent],
                        "appProperties": {"faithbook": "folder"},
                    },
                    fields="id",
                    **self._shared_drive_kwargs,
                )
                .execute(num_retries=settings.google_drive_api_retries)
            )
        logger.info("Dossier Drive cree : %s (%s)", name, created["id"])
        return created["id"]

    def find_file(self, name: str, folder_id: str) -> dict | None:
        with self._api_lock:
            service = self._get_service()
            safe_name = escape_query_value(name)
            query = (
                f"name = '{safe_name}' and mimeType != '{FOLDER_MIME}' "
                f"and '{folder_id}' in parents and trashed = false"
            )
            found = (
                service.files()
                .list(
                    q=query,
                    fields="files(id,name,webViewLink,size)",
                    pageSize=10,
                    orderBy="createdTime",
                    **self._list_kwargs(),
                )
                .execute(num_retries=settings.google_drive_api_retries)
            )
        files = found.get("files", [])
        return files[0] if files else None

    def upload(self, path: Path, folder_id: str, filename: str | None = None) -> UploadResult:
        """Televerse le fichier ; si un fichier de meme nom existe deja, ne le duplique pas."""
        from googleapiclient.http import MediaFileUpload

        if not path.is_file():
            raise FileNotFoundError(f"Capture locale introuvable : {path}")

        with self._api_lock:
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

            media = MediaFileUpload(
                str(path),
                mimetype="image/png",
                resumable=True,
                chunksize=5 * 1024 * 1024,
            )
            request = service.files().create(
                body={"name": name, "parents": [folder_id]},
                media_body=media,
                fields="id,webViewLink",
                **self._shared_drive_kwargs,
            )
            created: dict[str, Any] | None = None
            while created is None:
                _, created = request.next_chunk(
                    num_retries=settings.google_drive_api_retries
                )
        return UploadResult(
            file_id=created["id"],
            folder_id=folder_id,
            web_link=created.get("webViewLink", ""),
        )


drive_client = DriveClient()
