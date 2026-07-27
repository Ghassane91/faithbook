from __future__ import annotations

import logging
import threading
from pathlib import Path

from app.config import settings
from app.services.drive import UploadResult

logger = logging.getLogger(__name__)

# Codes renvoyes par S3 lorsque l'objet n'existe pas.
_ABSENT = {"404", "NoSuchKey", "NotFound"}


class S3NotConfigured(RuntimeError):
    pass


class S3Client:
    """Client de stockage compatible S3 (AWS S3, Backblaze B2, Wasabi, MinIO).

    Expose la meme interface que DriveClient afin que drive_sync bascule d'un
    backend a l'autre sans changer sa logique. S3 n'a pas de dossiers :
    ensure_folder se contente de composer un prefixe de cle, sans appel reseau.
    """

    def __init__(self) -> None:
        self._client = None
        self._lock = threading.Lock()

    # -- infra ------------------------------------------------------------
    def is_configured(self) -> bool:
        return (
            settings.storage_backend == "s3"
            and bool(settings.s3_bucket)
            and bool(settings.s3_access_key_id)
            and bool(settings.s3_secret_access_key)
        )
    def _get_client(self):
        if self._client is not None:
            return self._client
        with self._lock:
            if self._client is None:
                if not self.is_configured():
                    raise S3NotConfigured(
                        "Stockage S3 non configure : verifiez STORAGE_BACKEND, "
                        "S3_BUCKET, S3_ACCESS_KEY_ID et S3_SECRET_ACCESS_KEY."
                    )
                import boto3
                from botocore.config import Config

                self._client = boto3.client(
                    "s3",
                    region_name=settings.s3_region or None,
                    endpoint_url=settings.s3_endpoint_url or None,
                    aws_access_key_id=settings.s3_access_key_id,
                    aws_secret_access_key=settings.s3_secret_access_key,
                    config=Config(
                        signature_version="s3v4",
                        retries={
                            "max_attempts": settings.s3_api_retries,
                            "mode": "standard",
                        },
                    ),
                )
        return self._client

    def check_access(self) -> dict:
        self._get_client().head_bucket(Bucket=settings.s3_bucket)
        return {
            "bucket": settings.s3_bucket,
            "endpoint": settings.s3_endpoint_url or "aws",
            "prefix": settings.s3_prefix,
        }

    # -- arborescence -----------------------------------------------------
    def ensure_folder(self, name: str, parent_id: str | None = None) -> str:
        """Compose un prefixe de cle : S3 n'a pas de dossiers, aucun appel reseau."""
        base = settings.s3_prefix if parent_id is None else parent_id
        parts = [p.strip("/") for p in (base, name) if p and p.strip("/")]
        return "/".join(parts)

    @staticmethod
    def _key(folder_id: str, filename: str) -> str:
        return f"{folder_id.strip('/')}/{filename}" if folder_id else filename
    def find_file(self, name: str, folder_id: str) -> dict | None:
        key = self._key(folder_id, name)
        try:
            head = self._get_client().head_object(Bucket=settings.s3_bucket, Key=key)
        except Exception as exc:  # noqa: BLE001
            code = str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
            if code in _ABSENT:
                return None
            raise
        return {"id": key, "size": head.get("ContentLength", 0)}

    def upload(self, path: Path, folder_id: str, filename: str | None = None) -> UploadResult:
        """Envoie le fichier ; si la cle existe deja, ne la reecrit pas."""
        if not path.is_file():
            raise FileNotFoundError(f"Capture locale introuvable : {path}")

        name = filename or path.name
        key = self._key(folder_id, name)

        if self.find_file(name, folder_id) is not None:
            logger.info("Objet deja present sur S3, envoi ignore : %s", key)
            return UploadResult(
                file_id=key,
                folder_id=folder_id,
                web_link=self.signed_url(key),
                deduplicated=True,
            )

        self._get_client().upload_file(
            str(path),
            settings.s3_bucket,
            key,
            ExtraArgs={"ContentType": "image/png"},
        )
        return UploadResult(
            file_id=key, folder_id=folder_id, web_link=self.signed_url(key)
        )

    # -- lecture ----------------------------------------------------------
    def signed_url(self, key: str, ttl_seconds: int | None = None) -> str:
        """URL de lecture temporaire : elle expire, la regenerer a l'affichage."""
        return self._get_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.s3_bucket, "Key": key},
            ExpiresIn=ttl_seconds or settings.s3_signed_url_ttl_seconds,
        )


s3_client = S3Client()