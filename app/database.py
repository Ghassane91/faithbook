from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import Base

def _connect_args(url: str) -> dict:
    """Options de connexion selon le moteur.

    Sans limite, une capture attendait un verrou indefiniment et figeait
    la boucle du backend. Voir DEFAUTS.md, blocage du 01/08.
    """
    if url.startswith("sqlite"):
        return {"check_same_thread": False}
    reglages = "-c lock_timeout=%d -c idle_in_transaction_session_timeout=%d"
    return {
        "options": reglages
        % (settings.db_lock_timeout_ms, settings.db_idle_tx_timeout_ms)
    }


connect_args = _connect_args(settings.database_url)

engine = create_engine(settings.database_url, connect_args=connect_args, future=True)

if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - infra
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def init_db() -> None:
    """Applique les migrations Alembic jusqu'a la derniere revision.

    On n'utilise volontairement PAS `create_all` : il cree les tables absentes
    mais ne modifie jamais une table existante. Un renommage de colonne
    laisserait alors une base incoherente au demarrage.
    """
    from alembic import command
    from alembic.config import Config

    root = Path(__file__).resolve().parent.parent
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    # Empeche env.py de reconfigurer la journalisation : sinon les migrations
    # jouees au demarrage effaceraient les handlers deja poses par l'application.
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")


def create_all_for_tests() -> None:
    """Raccourci pour les tests : cree le schema sans passer par Alembic."""
    Base.metadata.create_all(engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Session transactionnelle pour le code hors requete HTTP (scheduler, workers)."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """Dependance FastAPI."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
