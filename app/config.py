from functools import lru_cache
import ipaddress
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
    # La cle API agit au nom de ce compte reel. Cela conserve l'acces
    # machine-a-machine aux comptes connectes/noVNC sans utilisateur artificiel
    # id=0 ni contournement des controles de propriete.
    api_key_user_email: str = ""
    cors_origins: str = "*"
    environment: Literal["development", "test", "production"] = "development"
    # Seuls ces relais peuvent fournir X-Forwarded-For. Le reseau 172.16/12
    # couvre le bridge Docker habituel ; le backend n'est pas publie sur l'hote.
    trusted_proxy_cidrs: str = "127.0.0.1/32,::1/128,172.16.0.0/12"

    # Authentification
    admin_email: str = "admin@local"
    admin_password: str = ""
    session_hours: int = 12
    # Doit passer a true derriere HTTPS : le cookie ne partira plus en clair.
    cookie_secure: bool = False

    # Reinitialisation de mot de passe par mail
    # Duree de validite du lien de reinitialisation.
    reset_token_minutes: int = 60
    # Durée de validité d'une invitation à rejoindre une organisation.
    invitation_days: int = 7
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
    # Bornes anti-blocage du navigateur de connexion manuelle : sans elles,
    # une fermeture qui se fige laisse le verrou de profil pris pour toujours.
    login_lock_wait_seconds: int = 5
    login_close_timeout_seconds: int = 10

    # --- Rattrapage des captures manquees ---
    # La tolerance aux retards d APScheduler ne couvre que les taches deja
    # enregistrees. Apres un arret complet de la machine, la journee manquee
    # serait perdue : on la rattrape explicitement au demarrage.
    catchup_missed_runs: bool = True
    catchup_max_hours: int = 20
    catchup_delay_seconds: int = 30
    # Duree de vie du jeton qui autorise l'acces a /novnc et /websockify (courte
    # et independante de login_timeout_minutes : la fenetre d'exposition doit
    # rester minimale meme si la connexion manuelle elle-meme dure plus longtemps).
    novnc_token_ttl_minutes: int = 10

    # Anti-SSRF
    # Liste blanche de domaines autorises (vide = tout sauf les cibles internes).
    allowed_domains: str = ""
    # Autorise les cibles vers des adresses privees/internes. Danger : a laisser
    # a false sauf reseau de confiance.
    allow_private_targets: bool = False
    # Proxy sortant qui applique une seconde barriere reseau (ACL Squid) apres
    # les validations applicatives. Configure automatiquement par Compose.
    browser_proxy_url: str = ""

    # Planification
    timezone: str = "UTC"

    # Stockage
    storage_backend: Literal["local", "google_drive", "s3"] = "local"
    data_dir: str = "/data"
    screenshot_dir: str = "/data/screenshots"
    database_url: str = "sqlite:////data/app.db"

    # File d'exécution : inline pour les tests/développement sans Redis,
    # redis pour séparer l'API du worker de captures.
    queue_backend: Literal["inline", "redis"] = "inline"
    redis_url: str = "redis://redis:6379/0"
    queue_name: str = "faithbook:capture-runs"
    worker_lock_ttl_seconds: int = 21600
    auto_migrate_sqlite: bool = True
    legacy_sqlite_path: str = "/data/app.db"

    # Google Drive : compte de service + dossier parent partagé.
    google_service_account_file: str = "/secrets/service-account.json"
    google_drive_parent_folder_id: str = ""
    google_drive_shared_drive_id: str = ""
    # Nombre de nouvelles tentatives internes du client Google sur les erreurs
    # transitoires (429/5xx) pendant un envoi reprenable.
    google_drive_api_retries: int = 3
    # Les captures locales dont l'envoi a échoué sont reprises automatiquement.
    google_drive_retry_minutes: int = 5
    google_drive_retry_batch_size: int = 20

    # -- Stockage compatible S3 (AWS S3, Backblaze B2, Wasabi, MinIO) -----
    # Laisser s3_endpoint_url vide pour AWS ; le renseigner pour tout autre
    # fournisseur compatible S3.
    s3_bucket: str = ""
    s3_region: str = ""
    s3_endpoint_url: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    # Prefixe commun a toutes les cles, utile pour partager un bucket.
    s3_prefix: str = ""
    s3_api_retries: int = 3
    # Duree de validite des URLs signees servies a l'interface.
    s3_signed_url_ttl_seconds: int = 900

    # --- Synthese IA des changements (optionnelle, desactivee par defaut) ---
    anthropic_api_key: str = ""
    ai_summary_enabled: bool = False
    ai_summary_model: str = "claude-opus-5"
    ai_summary_retries: int = 2

    # --- Canaux d alerte complementaires (vides = inactifs) ---
    notify_telegram_bot_token: str = ""
    notify_telegram_chat_id: str = ""
    notify_webhook_url: str = ""
    notify_channel_timeout_seconds: int = 10
    # Format du nom des dossiers dates, en local comme sur Drive.
    folder_date_format: str = "%Y-%m-%d"

    # Notifications (les mails partent via le bloc SMTP_* ; sans SMTP ils sont
    # journalises). Destinataire : NOTIFY_EMAIL, a defaut le premier utilisateur.
    notify_email: str = ""
    # Mail immediat quand une capture echoue apres tous les reessais.
    notify_on_failure: bool = True
    # Detection de changement : une capture est marquee « modifiee » si la part
    # de la page qui change depasse ce seuil (0.03 = 3 %).
    change_threshold: float = 0.03
    # Mail quand une page suivie a change (opt-in, peut etre bavard).
    notify_on_change: bool = False
    # Rapport quotidien recapitulatif (HH:MM, vide = desactive).
    daily_report_time: str = "08:00"
    # Verification quotidienne des sessions des comptes connectes (HH:MM, vide = desactive).
    session_check_time: str = "07:30"
    # Alerte quand le cookie de session à échéance connue expire dans N jours.
    session_expiry_warning_days: int = 7

    # Capture
    default_viewport_width: int = 1440
    default_viewport_height: int = 900
    default_timeout_ms: int = 45000
    default_wait_after_load_ms: int = 2000
    default_user_agent: str = ""
    # Une capture pleine page descend progressivement pour déclencher le
    # lazy-loading (publications, images, listes infinies) avant le PNG final.
    auto_scroll_full_page: bool = True
    auto_scroll_delay_ms: int = 900
    auto_scroll_max_steps: int = 50
    auto_scroll_stable_rounds: int = 4

    # Fiabilite
    max_attempts: int = 3
    retry_backoff_seconds: int = 15
    dedupe_mode: Literal["per_day", "content_hash", "both", "off"] = "per_day"
    # Valeurs attribuées à toute nouvelle organisation. 0 = illimité.
    default_quota_accounts: int = 10
    default_quota_targets: int = 100
    default_quota_daily_captures: int = 500
    default_quota_storage_bytes: int = 10_737_418_240
    # Conservé comme défaut des nouvelles organisations et compatibilité
    # d'environnement. La purge utilise ensuite la valeur propre à chaque org.
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

    @property
    def trusted_proxy_networks(self) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
        networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
        for value in self.trusted_proxy_cidrs.split(","):
            value = value.strip()
            if value:
                networks.append(ipaddress.ip_network(value, strict=False))
        return networks


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
