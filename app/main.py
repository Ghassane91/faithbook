from __future__ import annotations

import logging
import logging.handlers
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import accounts
from app.api import auth as auth_api
from app.api import organizations, runs, system, targets
from app.config import settings
from app.database import init_db, session_scope
from app.scheduler import mark_interrupted_runs, shutdown_scheduler, start_scheduler
from app.services.auth import (
    ensure_first_user,
    purge_expired_reset_tokens,
    purge_expired_sessions,
)
from app.services.crypto import ensure_encryption_ready
from app.services.legacy_migration import migrate_sqlite_if_needed
from app.services.tenancy import ensure_legacy_organizations


def setup_logging() -> None:
    Path(settings.log_file).parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    handlers.append(
        logging.handlers.RotatingFileHandler(
            settings.log_file, maxBytes=10_000_000, backupCount=5, encoding="utf-8"
        )
    )
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
        handlers=handlers,
        force=True,
    )
    logging.getLogger("apscheduler.executors.default").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_logging()
    Path(settings.screenshot_dir).mkdir(parents=True, exist_ok=True)
    ensure_encryption_ready()
    init_db()
    migrate_sqlite_if_needed()
    with session_scope() as db:
        ensure_first_user(db)
        ensure_legacy_organizations(db)
        purged = purge_expired_sessions(db)
        if purged:
            logging.getLogger(__name__).info("%s session(s) expiree(s) purgee(s)", purged)
        purge_expired_reset_tokens(db)
    mark_interrupted_runs()
    start_scheduler()
    logging.getLogger(__name__).info(
        "Backend pret | fuseau=%s stockage=%s", settings.timezone, settings.storage_backend
    )
    yield
    shutdown_scheduler()


DESCRIPTION = """
Backend de capture automatisee de pages web.

**Fonctionnement** : on enregistre une *cible* (URL + horaire). Au moment prevu,
la page est ouverte avec Chromium, une capture pleine page est prise, puis envoyee
dans un dossier Google Drive nomme avec la date du jour. Chaque execution est
journalisee, deduplicable et reessayee automatiquement en cas d'echec.

**Authentification** : si `API_KEY` est definie, envoyer l'en-tete `X-API-Key`.
"""

_docs_enabled = settings.environment != "production"

app = FastAPI(
    title="Capture Scheduler API",
    description=DESCRIPTION,
    version=system.VERSION,
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_api.router)
app.include_router(system.router)
app.include_router(accounts.router)
app.include_router(organizations.router)
app.include_router(targets.router)
app.include_router(runs.router)


@app.get("/", include_in_schema=False)
def root():
    return {
        "service": "Capture Scheduler API",
        "docs": "/docs" if _docs_enabled else None,
        "health": "/api/health",
    }
