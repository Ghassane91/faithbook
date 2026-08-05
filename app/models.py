from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class RunStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"
    skipped = "skipped"  # doublon evite
    suspended = "suspended"  # intervention humaine requise (2FA, captcha, session expiree)


class TriggerType(str, enum.Enum):
    scheduled = "scheduled"
    manual = "manual"


class AccountStatus(str, enum.Enum):
    never = "never"  # profil cree, jamais connecte
    connected = "connected"
    disconnected = "disconnected"  # coffre/cookies absents ou déconnexion détectée
    expired = "expired"
    verification_required = "verification_required"  # 2FA / captcha / checkpoint
    error = "error"


class CaptureMode(str, enum.Enum):
    desktop = "desktop"
    mobile = "mobile"


class MembershipRole(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    member = "member"
    viewer = "viewer"


class User(Base):
    """Compte d'acces a l'interface."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Force le changement du mot de passe genere automatiquement au 1er demarrage.
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    sessions: Mapped[list[AuthSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    memberships: Mapped[list[OrganizationMembership]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )


class Organization(Base):
    """Espace de travail qui possède les cibles et les comptes connectés."""

    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint("quota_accounts >= 0", name="ck_org_quota_accounts_nonnegative"),
        CheckConstraint("quota_targets >= 0", name="ck_org_quota_targets_nonnegative"),
        CheckConstraint(
            "quota_daily_captures >= 0",
            name="ck_org_quota_daily_captures_nonnegative",
        ),
        CheckConstraint(
            "quota_storage_bytes >= 0",
            name="ck_org_quota_storage_bytes_nonnegative",
        ),
        CheckConstraint("retention_days >= 0", name="ck_org_retention_days_nonnegative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    # 0 signifie illimité. Les valeurs sont stockées par organisation afin
    # qu'un futur plan commercial puisse les modifier sans changer le code.
    quota_accounts: Mapped[int] = mapped_column(
        Integer, default=10, server_default="10", nullable=False
    )
    quota_targets: Mapped[int] = mapped_column(
        Integer, default=100, server_default="100", nullable=False
    )
    quota_daily_captures: Mapped[int] = mapped_column(
        Integer, default=500, server_default="500", nullable=False
    )
    quota_storage_bytes: Mapped[int] = mapped_column(
        BigInteger, default=10_737_418_240, server_default="10737418240", nullable=False
    )
    retention_days: Mapped[int] = mapped_column(
        Integer, default=90, server_default="90", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    memberships: Mapped[list[OrganizationMembership]] = relationship(
        back_populates="organization", cascade="all, delete-orphan", passive_deletes=True
    )


class OrganizationMembership(Base):
    """Rôle d'un utilisateur dans une organisation."""

    __tablename__ = "organization_memberships"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_org_membership"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[MembershipRole] = mapped_column(
        Enum(MembershipRole), default=MembershipRole.member, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    organization: Mapped[Organization] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")


class OrganizationInvitation(Base):
    """Invitation à rejoindre une organisation, stockée sans jeton en clair."""

    __tablename__ = "organization_invitations"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    role: Mapped[MembershipRole] = mapped_column(
        Enum(MembershipRole), default=MembershipRole.member, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    invited_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthSession(Base):
    """Session ouverte. Jeton opaque stocke en base : revocable a tout moment,
    contrairement a un JWT qui reste valide jusqu'a son expiration."""

    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # On ne stocke que l'empreinte : une fuite de la base ne donne aucun jeton utilisable.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(300))
    ip: Mapped[str | None] = mapped_column(String(60))

    user: Mapped[User] = relationship(back_populates="sessions")


class PasswordResetToken(Base):
    """Jeton de réinitialisation de mot de passe, à usage unique et daté.

    Comme pour les sessions, seule l'empreinte du jeton est stockée : une fuite
    de la base ne permet pas de forger un lien de réinitialisation valide.
    """

    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Renseigné à la consommation : un jeton déjà utilisé est refusé.
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Account(Base):
    """Un compte connecté (ex. Facebook) avec son profil navigateur isolé.

    Aucun mot de passe de la plateforme n'est stocké : seule la session
    (cookies) obtenue par connexion manuelle est conservée, et chiffrée.
    """

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Propriétaire : une session ne doit jamais être partagée entre utilisateurs.
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    platform: Mapped[str] = mapped_column(String(40), default="facebook", nullable=False)
    # Slug du profil navigateur isolé (coffre chiffré profiles/<slug>.tar.enc).
    profile_slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)

    status: Mapped[AccountStatus] = mapped_column(
        Enum(AccountStatus), default=AccountStatus.never, nullable=False, index=True
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)

    # Sauvegarde chiffrée du storage_state (cookies). Le profil de travail vit
    # dans le coffre ; ceci est une copie exportée, elle aussi chiffrée.
    encrypted_state: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    targets: Mapped[list[Target]] = relationship(back_populates="account")


class AuditLog(Base):
    """Journal des actions sensibles (connexion de compte, suppression de
    session, gestion des cibles, changement de mot de passe...)."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # Dénormalisé : l'entrée doit survivre à la suppression de l'utilisateur.
    user_email: Mapped[str | None] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    detail: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(String(60))


class Target(Base):
    """Une URL a capturer avec son horaire."""

    __tablename__ = "targets"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Planification, par ordre de priorite decroissante : intervalle en minutes,
    # expression cron, puis heure quotidienne HH:MM. Une seule des trois sert.
    run_time: Mapped[str | None] = mapped_column(String(5))
    cron_expression: Mapped[str | None] = mapped_column(String(120))
    interval_minutes: Mapped[int | None] = mapped_column(Integer)
    timezone_name: Mapped[str | None] = mapped_column(String(64))

    # Options de capture (NULL => valeur par defaut globale)
    viewport_width: Mapped[int | None] = mapped_column(Integer)
    viewport_height: Mapped[int | None] = mapped_column(Integer)
    full_page: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    wait_until: Mapped[str] = mapped_column(String(20), default="networkidle", nullable=False)
    wait_after_load_ms: Mapped[int | None] = mapped_column(Integer)
    timeout_ms: Mapped[int | None] = mapped_column(Integer)
    user_agent: Mapped[str | None] = mapped_column(Text)
    locale: Mapped[str | None] = mapped_column(String(20))
    # Selecteurs CSS masques avant capture (bandeaux cookies, popups...), separes par ";"
    hide_selectors: Mapped[str | None] = mapped_column(Text)
    # Selecteurs CSS cliques avant capture (fermeture de bandeaux/modales), separes par ";".
    # Un selecteur absent est ignore sans erreur.
    dismiss_selectors: Mapped[str | None] = mapped_column(Text)
    # Cookies/session Playwright (storage_state JSON) pour les pages authentifiees
    storage_state_json: Mapped[str | None] = mapped_column(Text)
    # Profil Chromium persistant (/data/profiles/<nom>) : garde la session vivante
    # entre les executions, car Facebook fait tourner ses cookies.
    session_profile: Mapped[str | None] = mapped_column(String(64))

    # Compte connecté à utiliser (session partagée entre les cibles d'un compte).
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True
    )
    # Rendu ordinateur ou mobile.
    capture_mode: Mapped[CaptureMode] = mapped_column(
        Enum(CaptureMode), default=CaptureMode.desktop, nullable=False
    )
    # Délai entre deux tentatives (NULL => valeur globale RETRY_BACKOFF_SECONDS).
    retry_backoff_seconds: Mapped[int | None] = mapped_column(Integer)

    # Garde-fous : sans eux, une session expiree produit des captures du mur de
    # connexion pendant des semaines sans qu'aucune erreur ne soit remontee.
    expected_selector: Mapped[str | None] = mapped_column(Text)
    fail_if_url_contains: Mapped[str | None] = mapped_column(Text)

    # Sous-dossier optionnel a l'interieur du dossier du jour
    subfolder: Mapped[str | None] = mapped_column(String(200))

    # Etiquettes libres separees par des virgules : regrouper les cibles
    # par client ou par theme sans imposer une arborescence rigide.
    tags: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    runs: Mapped[list[Run]] = relationship(
        back_populates="target", cascade="all, delete-orphan", passive_deletes=True
    )
    account: Mapped[Account | None] = relationship(back_populates="targets")


class Run(Base):
    """Une execution (planifiee ou manuelle) et son resultat."""

    __tablename__ = "runs"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_runs_idempotency_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    target_id: Mapped[int] = mapped_column(
        ForeignKey("targets.id", ondelete="CASCADE"), index=True, nullable=False
    )

    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus), default=RunStatus.pending, nullable=False, index=True
    )
    trigger: Mapped[TriggerType] = mapped_column(Enum(TriggerType), nullable=False)

    # Date locale (fuseau configure) de la capture : sert au dossier Drive et a la deduplication
    capture_date: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(120))

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    screenshot_path: Mapped[str | None] = mapped_column(Text)
    screenshot_bytes: Mapped[int | None] = mapped_column(Integer)
    content_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    page_title: Mapped[str | None] = mapped_column(Text)
    # Texte visible de la page : sert a comparer les contenus entre deux
    # captures sans dependre de la position des elements a l ecran.
    body_text: Mapped[str | None] = mapped_column(Text)
    # Synthese lisible produite par l IA quand la page a change.
    ai_summary: Mapped[str | None] = mapped_column(Text)
    final_url: Mapped[str | None] = mapped_column(Text)

    # --- Intégration Google Drive -----------------------------------------
    # Cle ou prefixe distant : un identifiant Drive fait 33 caracteres, mais
    # une cle S3 peut aller jusqu a 1024. Type texte pour ne rien tronquer.
    drive_folder_id: Mapped[str | None] = mapped_column(Text)
    drive_file_id: Mapped[str | None] = mapped_column(Text)
    drive_file_link: Mapped[str | None] = mapped_column(Text)
    # local | pending | uploaded | failed. La capture locale reste toujours la
    # source de vérité jusqu'à confirmation de l'envoi Drive.
    drive_status: Mapped[str] = mapped_column(
        String(20), default="local", server_default="local", nullable=False, index=True
    )
    drive_attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    drive_last_error: Mapped[str | None] = mapped_column(Text)
    drive_uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    drive_next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )

    error_message: Mapped[str | None] = mapped_column(Text)
    skipped_reason: Mapped[str | None] = mapped_column(Text)

    # Capture de diagnostic prise en cas d'echec (etat de la page au moment de l'erreur).
    diagnostic_path: Mapped[str | None] = mapped_column(Text)
    # Statut de la session du compte au moment de l'execution.
    session_status: Mapped[str | None] = mapped_column(String(40))

    # Detection de changement : proportion (0..1) de pixels differents par rapport
    # a la capture reussie precedente, et le verdict booleen selon le seuil.
    change_ratio: Mapped[float | None] = mapped_column(Float)
    changed: Mapped[bool | None] = mapped_column(Boolean)

    # Metriques publiques extraites de la page (JSON), ex. {"followers": 12345}.
    metrics: Mapped[str | None] = mapped_column(Text)

    target: Mapped[Target] = relationship(back_populates="runs")
    logs: Mapped[list[RunLog]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="RunLog.id",
    )


class RunLog(Base):
    """Journal detaille, etape par etape, d'une execution."""

    __tablename__ = "run_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    level: Mapped[str] = mapped_column(String(10), default="INFO", nullable=False)
    step: Mapped[str] = mapped_column(String(50), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    attempt: Mapped[int | None] = mapped_column(Integer)

    run: Mapped[Run] = relationship(back_populates="logs")
