from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import AccountStatus, CaptureMode, RunStatus, TriggerType

TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
WAIT_UNTIL = {"load", "domcontentloaded", "networkidle", "commit"}


def _validate_url(v: str | None) -> str | None:
    if v is not None and not v.startswith(("http://", "https://")):
        raise ValueError("L'URL doit commencer par http:// ou https://")
    return v


def _validate_time(v: str | None) -> str | None:
    if v is not None and not TIME_RE.match(v):
        raise ValueError("run_time doit etre au format HH:MM (24h)")
    return v


def _validate_wait_until(v: str | None) -> str | None:
    if v is not None and v not in WAIT_UNTIL:
        raise ValueError(f"wait_until doit etre parmi {sorted(WAIT_UNTIL)}")
    return v


def _validate_cron(v: str | None) -> str | None:
    if v is not None and len(v.split()) != 5:
        raise ValueError("cron_expression doit avoir 5 champs : min heure jour mois jour_sem")
    return v


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=200)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


class ForgotPasswordIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)


class ResetPasswordIn(BaseModel):
    token: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    must_change_password: bool = False
    last_login_at: datetime | None = None


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    platform: str = Field(default="facebook", max_length=40)


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    platform: str
    status: AccountStatus
    last_verified_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime
    # Les cookies ne sont JAMAIS exposes : uniquement leur presence.
    has_session: bool = False
    target_count: int = 0


class LoginStatusOut(BaseModel):
    active: bool
    account_id: int | None = None
    logged_in: bool = False
    current_url: str | None = None
    platform: str | None = None
    novnc_path: str | None = None
    detail: str | None = None


class SessionTestOut(BaseModel):
    account_id: int
    status: AccountStatus
    logged_in: bool
    final_url: str | None = None
    detail: str


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ts: datetime
    user_email: str | None
    action: str
    detail: str | None
    ip: str | None


class TargetBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1)
    enabled: bool = True
    run_time: str | None = Field(default=None, description="Heure quotidienne HH:MM")
    cron_expression: str | None = Field(
        default=None, description="Cron 5 champs, prioritaire sur run_time"
    )
    timezone_name: str | None = Field(default=None, description="Defaut : TIMEZONE globale")

    viewport_width: int | None = Field(default=None, ge=320, le=3840)
    viewport_height: int | None = Field(default=None, ge=320, le=2160)
    full_page: bool = True
    wait_until: str = "networkidle"
    wait_after_load_ms: int | None = Field(default=None, ge=0, le=120000)
    timeout_ms: int | None = Field(default=None, ge=1000, le=300000)
    user_agent: str | None = None
    locale: str | None = None
    hide_selectors: str | None = Field(
        default=None, description='Selecteurs CSS masques avant capture, separes par ";"'
    )
    dismiss_selectors: str | None = Field(
        default=None,
        description='Selecteurs CSS cliques avant capture (fermeture de bandeaux), separes par ";"',
    )
    storage_state_json: str | None = Field(
        default=None, description="storage_state Playwright (JSON) pour pages authentifiees"
    )
    session_profile: str | None = Field(
        default=None,
        max_length=64,
        description="Nom d'un profil Chromium persistant (conserve la session entre executions)",
    )
    account_id: int | None = Field(
        default=None, description="Compte connecté dont réutiliser la session"
    )
    capture_mode: CaptureMode = CaptureMode.desktop
    retry_backoff_seconds: int | None = Field(default=None, ge=0, le=3600)
    expected_selector: str | None = Field(
        default=None,
        description="Selecteur CSS qui doit etre present ; sinon l'execution echoue",
    )
    fail_if_url_contains: str | None = Field(
        default=None,
        description='Fragments d\'URL interdits, separes par ";" (ex. "login;checkpoint")',
    )
    subfolder: str | None = Field(default=None, max_length=200)

    _v_url = field_validator("url")(_validate_url)
    _v_time = field_validator("run_time")(_validate_time)
    _v_wait = field_validator("wait_until")(_validate_wait_until)
    _v_cron = field_validator("cron_expression")(_validate_cron)


class TargetCreate(TargetBase):
    @model_validator(mode="after")
    def _needs_schedule(self):
        if self.enabled and not self.run_time and not self.cron_expression:
            raise ValueError("Une cible active doit avoir run_time ou cron_expression")
        return self


class TargetUpdate(BaseModel):
    """Mise a jour partielle : seuls les champs fournis sont modifies."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    url: str | None = None
    enabled: bool | None = None
    run_time: str | None = None
    cron_expression: str | None = None
    timezone_name: str | None = None
    viewport_width: int | None = Field(default=None, ge=320, le=3840)
    viewport_height: int | None = Field(default=None, ge=320, le=2160)
    full_page: bool | None = None
    wait_until: str | None = None
    wait_after_load_ms: int | None = Field(default=None, ge=0, le=120000)
    timeout_ms: int | None = Field(default=None, ge=1000, le=300000)
    user_agent: str | None = None
    locale: str | None = None
    hide_selectors: str | None = None
    dismiss_selectors: str | None = None
    storage_state_json: str | None = None
    session_profile: str | None = Field(default=None, max_length=64)
    account_id: int | None = None
    capture_mode: CaptureMode | None = None
    retry_backoff_seconds: int | None = Field(default=None, ge=0, le=3600)
    expected_selector: str | None = None
    fail_if_url_contains: str | None = None
    subfolder: str | None = Field(default=None, max_length=200)

    _v_url = field_validator("url")(_validate_url)
    _v_time = field_validator("run_time")(_validate_time)
    _v_wait = field_validator("wait_until")(_validate_wait_until)
    _v_cron = field_validator("cron_expression")(_validate_cron)


class TargetOut(TargetBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
    next_run_at: datetime | None = None
    last_run: RunSummary | None = None

    # Les cookies de session ne sont jamais renvoyes par l'API : on n'expose
    # que leur presence et leur date d'expiration.
    storage_state_json: str | None = Field(default=None, exclude=True)
    has_session: bool = False
    session_expires_at: datetime | None = None


class SessionIn(BaseModel):
    """storage_state Playwright produit par scripts/login_session.py."""

    storage_state: dict

    @field_validator("storage_state")
    @classmethod
    def _check_state(cls, v: dict) -> dict:
        if "cookies" not in v:
            raise ValueError("storage_state invalide : cle 'cookies' absente")
        if not v["cookies"]:
            raise ValueError("storage_state invalide : aucun cookie")
        return v


class SessionStatusOut(BaseModel):
    target_id: int
    has_session: bool
    session_profile: str | None
    cookie_count: int
    expires_at: datetime | None
    expired: bool
    detail: str


class RunLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ts: datetime
    level: str
    step: str
    message: str
    attempt: int | None


class RunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    target_id: int
    status: RunStatus
    trigger: TriggerType
    capture_date: str
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    attempts: int
    error_message: str | None
    skipped_reason: str | None
    changed: bool | None = None
    change_ratio: float | None = None


class RunOut(RunSummary):
    screenshot_path: str | None
    screenshot_bytes: int | None
    content_sha256: str | None
    page_title: str | None
    final_url: str | None
    # Capture réussie précédente de la même cible (pour la comparaison avant/après).
    previous_run_id: int | None = None
    logs: list[RunLogOut] = []


class RunListOut(BaseModel):
    total: int
    items: list[RunSummary]


class TriggerRunResponse(BaseModel):
    run_id: int
    status: RunStatus
    detail: str


class HealthOut(BaseModel):
    status: str
    version: str
    timezone: str
    output_dir: str
    scheduler_running: bool
    jobs: int
    targets_enabled: int


class JobOut(BaseModel):
    job_id: str
    target_id: int
    target_name: str
    next_run_at: datetime | None
    trigger: str


TargetOut.model_rebuild()
