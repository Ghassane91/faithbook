from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Toute la configuration vient de l'environnement : rien en dur."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # API
    api_port: int = 8000
    # Cle machine-a-machine pour les scripts. N'a rien a voir avec les comptes
    # utilisateurs : elle ne donne acces qu'a l'API, jamais a l'interface.
    api_key: str = ""
    cors_origins: str = "*"

    # Authentification
    admin_email: str = "admin@local"
    admin_password: str = ""
    session_hours: int = 12
    # Doit passer a true derriere HTTPS : le cookie ne partira plus en clair.
    cookie_secure: bool = False

    # Reinitialisation de mot de passe par mail
    # Duree de validite du lien de reinitialisation.
    reset_token_minutes: int = 60
    # URL publique de l'interface, base du lien envoye par mail. En local :
    # http://localhost:3000 ; sur VPS : le domaine HTTPS du frontend.
    public_url: str = "http://localhost:3000"

    # SMTP : si smtp_host est vide, aucun mail n'est envoye et le lien de
    # reinitialisation est ecrit dans les journaux (pratique en local).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    # Adresse expeditrice ; a defaut, smtp_user est utilise.
    smtp_from: str = ""

    # Chiffrement au repos des sessions de comptes connectes (cle Fernet).
    session_encryption_key: str = ""
    # Dossier de travail ou les profils sont dechiffres le temps d'un usage.
    # /dev/shm (tmpfs, en RAM) evite d'ecrire le profil en clair sur le disque.
    profile_work_dir: str = "/dev/shm/faithbook"

    # Login manuel noVNC
    vnc_password: str = ""
    novnc_port: int = 6080
    login_timeout_minutes: int = 15

    # Anti-SSRF
    # Liste blanche de domaines autorises (vide = tout sauf les cibles internes).
    allowed_domains: str = ""
    # Autorise les cibles vers des adresses privees/internes. Danger : a laisser
    # a false sauf reseau de confiance.
    allow_private_targets: bool = False

    # Planification
    timezone: str = "UTC"

    # Stockage
    storage_backend: Literal["local", "google_drive"] = "local"
    data_dir: str = "/data"
    screenshot_dir: str = "/data/screenshots"
    database_url: str = "sqlite:////data/app.db"

    # Google Drive : EN SUSPEND (voir README §2). Non expose par l'API.
    google_service_account_file: str = "/secrets/service-account.json"
    google_drive_parent_folder_id: str = ""
    google_drive_shared_drive_id: str = ""
    # Format du nom des dossiers dates, en local comme sur Drive.
    folder_date_format: str = "%Y-%m-%d"

    # Capture
    default_viewport_width: int = 1440
    default_viewport_height: int = 900
    default_timeout_ms: int = 45000
    default_wait_after_load_ms: int = 2000
    default_user_agent: str = ""

    # Fiabilite
    max_attempts: int = 3
    retry_backoff_seconds: int = 15
    dedupe_mode: Literal["per_day", "content_hash", "both", "off"] = "per_day"
    run_retention_days: int = 90

    # Logs
    log_level: str = "INFO"
    log_file: str = "/data/app.log"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_domain_list(self) -> list[str]:
        return [d.strip().lower() for d in self.allowed_domains.split(",") if d.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
