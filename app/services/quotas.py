from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Account, Organization, Run, Target
from app.services.capture import legacy_thumb_path, thumb_path


class QuotaExceeded(RuntimeError):
    """Refus métier stable : la demande dépasserait une limite d'organisation."""

    def __init__(self, resource: str, used: int, limit: int):
        self.resource = resource
        self.used = used
        self.limit = limit
        labels = {
            "accounts": "comptes connectés",
            "targets": "cibles",
            "daily_captures": "captures quotidiennes",
            "storage_bytes": "stockage",
        }
        super().__init__(
            f"Quota de {labels.get(resource, resource)} atteint "
            f"({used}/{limit})."
        )


@dataclass(frozen=True)
class UsageMetric:
    used: int
    limit: int

    @property
    def unlimited(self) -> bool:
        return self.limit == 0

    @property
    def remaining(self) -> int | None:
        return None if self.unlimited else max(0, self.limit - self.used)

    @property
    def percent(self) -> float | None:
        if self.unlimited:
            return None
        if self.limit == 0:
            return 0.0
        return round(min(100.0, self.used * 100 / self.limit), 2)


@dataclass(frozen=True)
class OrganizationUsage:
    organization_id: int
    billing_date: str
    accounts: UsageMetric
    targets: UsageMetric
    daily_captures: UsageMetric
    storage_bytes: UsageMetric
    retention_days: int


def _organization(
    session: Session, organization_id: int, *, lock: bool = False
) -> Organization:
    statement = select(Organization).where(Organization.id == organization_id)
    if lock:
        statement = statement.with_for_update()
    organization = session.scalars(statement).first()
    if organization is None:
        raise LookupError("Organisation introuvable")
    return organization


def _day_bounds(now: datetime | None = None) -> tuple[datetime, datetime, str]:
    tz = ZoneInfo(settings.timezone)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local = current.astimezone(tz)
    start_local = datetime.combine(local.date(), time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    return (
        start_local.astimezone(timezone.utc),
        end_local.astimezone(timezone.utc),
        local.date().isoformat(),
    )


def _account_count(session: Session, organization_id: int) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(Account)
            .where(Account.organization_id == organization_id)
        )
        or 0
    )


def _target_count(session: Session, organization_id: int) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(Target)
            .where(Target.organization_id == organization_id)
        )
        or 0
    )


def _daily_capture_count(
    session: Session,
    organization_id: int,
    *,
    now: datetime | None = None,
) -> tuple[int, str]:
    start, end, billing_date = _day_bounds(now)
    value = session.scalar(
        select(func.count())
        .select_from(Run)
        .join(Target)
        .where(
            Target.organization_id == organization_id,
            Run.started_at >= start,
            Run.started_at < end,
        )
    )
    return int(value or 0), billing_date


def _storage_bytes(
    session: Session,
    organization_id: int,
    *,
    exclude_run_id: int | None = None,
) -> int:
    filters = [
        Target.organization_id == organization_id,
        # Une capture déjà écrite doit compter même pendant les quelques
        # secondes où son run est encore "running". Cela ferme la course entre
        # deux workers de la même organisation.
        Run.screenshot_path.is_not(None),
        Run.screenshot_bytes.is_not(None),
    ]
    if exclude_run_id is not None:
        filters.append(Run.id != exclude_run_id)
    value = session.scalar(
        select(func.coalesce(func.sum(Run.screenshot_bytes), 0))
        .select_from(Run)
        .join(Target)
        .where(*filters)
    )
    return int(value or 0)


def organization_usage(
    session: Session,
    organization_id: int,
    *,
    now: datetime | None = None,
) -> OrganizationUsage:
    organization = _organization(session, organization_id)
    daily, billing_date = _daily_capture_count(
        session, organization_id, now=now
    )
    return OrganizationUsage(
        organization_id=organization_id,
        billing_date=billing_date,
        accounts=UsageMetric(
            _account_count(session, organization_id),
            organization.quota_accounts,
        ),
        targets=UsageMetric(
            _target_count(session, organization_id),
            organization.quota_targets,
        ),
        daily_captures=UsageMetric(daily, organization.quota_daily_captures),
        storage_bytes=UsageMetric(
            _storage_bytes(session, organization_id),
            organization.quota_storage_bytes,
        ),
        retention_days=organization.retention_days,
    )


def _raise_if_reached(resource: str, used: int, limit: int) -> None:
    if limit > 0 and used >= limit:
        raise QuotaExceeded(resource, used, limit)


def enforce_account_creation(session: Session, organization_id: int) -> None:
    organization = _organization(session, organization_id, lock=True)
    _raise_if_reached(
        "accounts",
        _account_count(session, organization_id),
        organization.quota_accounts,
    )


def enforce_target_creation(session: Session, organization_id: int) -> None:
    organization = _organization(session, organization_id, lock=True)
    _raise_if_reached(
        "targets",
        _target_count(session, organization_id),
        organization.quota_targets,
    )


def enforce_capture_creation(session: Session, organization_id: int) -> None:
    organization = _organization(session, organization_id, lock=True)
    daily, _ = _daily_capture_count(session, organization_id)
    _raise_if_reached(
        "daily_captures", daily, organization.quota_daily_captures
    )
    _raise_if_reached(
        "storage_bytes",
        _storage_bytes(session, organization_id),
        organization.quota_storage_bytes,
    )


def enforce_capture_size(
    session: Session,
    organization_id: int,
    size_bytes: int,
    *,
    run_id: int,
) -> None:
    organization = _organization(session, organization_id, lock=True)
    used = _storage_bytes(
        session, organization_id, exclude_run_id=run_id
    )
    if (
        organization.quota_storage_bytes > 0
        and used + size_bytes > organization.quota_storage_bytes
    ):
        raise QuotaExceeded(
            "storage_bytes",
            used + size_bytes,
            organization.quota_storage_bytes,
        )


def _safe_unlink(raw_path: str | None) -> bool:
    if not raw_path:
        return False
    root = Path(settings.screenshot_dir).resolve()
    try:
        path = Path(raw_path).resolve()
    except OSError:
        return False
    if path == root or root not in path.parents or not path.is_file():
        return False
    path.unlink(missing_ok=True)
    parent = path.parent
    while parent != root and root in parent.parents:
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent
    return True


def purge_expired_runs(
    session: Session, *, now: datetime | None = None
) -> tuple[int, int]:
    """Applique la rétention de chaque organisation et garde Drive intact."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    expired: list[Run] = []
    paths: list[str] = []
    for organization in session.scalars(select(Organization)).all():
        if organization.retention_days <= 0:
            continue
        cutoff = current - timedelta(days=organization.retention_days)
        runs = session.scalars(
            select(Run)
            .join(Target)
            .where(
                Target.organization_id == organization.id,
                Run.started_at < cutoff,
            )
        ).all()
        for run in runs:
            if run.screenshot_path:
                screenshot = Path(run.screenshot_path)
                paths.extend(
                    [
                        run.screenshot_path,
                        str(thumb_path(screenshot)),
                        str(legacy_thumb_path(screenshot)),
                    ]
                )
            if run.diagnostic_path:
                paths.append(run.diagnostic_path)
            expired.append(run)
            session.delete(run)

    if expired:
        session.commit()
    removed_files = sum(1 for path in dict.fromkeys(paths) if _safe_unlink(path))
    return len(expired), removed_files
