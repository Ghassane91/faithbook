from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import Engine, MetaData, Table, create_engine, func, inspect, select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import engine
from app.models import Base, User

logger = logging.getLogger(__name__)


def copy_sqlite_database(source_path: Path, target_engine: Engine) -> int:
    source = create_engine(
        f"sqlite:///{source_path.as_posix()}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    source_inspector = inspect(source)
    if not source_inspector.has_table("users"):
        source.dispose()
        return 0

    copied = 0
    try:
        with target_engine.begin() as target_connection, source.connect() as source_connection:
            for table in Base.metadata.sorted_tables:
                if not source_inspector.has_table(table.name):
                    continue
                # La base SQLite peut venir d'une version plus ancienne de
                # FaithBook. On reflète sa vraie structure et on ne copie que
                # l'intersection des colonnes : les nouvelles colonnes de la
                # destination reçoivent alors leur valeur par défaut.
                source_table = Table(
                    table.name,
                    MetaData(),
                    autoload_with=source_connection,
                )
                common_names = [
                    column.name
                    for column in table.columns
                    if column.name in source_table.c
                ]
                rows = [
                    dict(row._mapping)
                    for row in source_connection.execute(
                        select(*(source_table.c[name] for name in common_names))
                    ).all()
                ]
                if rows:
                    target_connection.execute(table.insert(), rows)
                    copied += len(rows)

            if target_engine.dialect.name == "postgresql":
                for table in Base.metadata.sorted_tables:
                    if "id" not in table.c or not source_inspector.has_table(table.name):
                        continue
                    target_connection.execute(
                        text(
                            "SELECT setval("
                            "pg_get_serial_sequence(:table_name, 'id'), "
                            f"COALESCE((SELECT MAX(id) FROM {table.name}), 1), "
                            f"(SELECT COUNT(*) > 0 FROM {table.name})"
                            ")"
                        ),
                        {"table_name": table.name},
                    )
    finally:
        source.dispose()

    logger.warning(
        "Migration SQLite -> PostgreSQL terminée : %s lignes copiées. "
        "L'ancienne base %s est conservée.",
        copied,
        source_path,
    )
    return copied


def migrate_sqlite_if_needed() -> int:
    """Copie atomiquement l'ancienne base SQLite vers PostgreSQL vide.

    SQLite reste intacte comme retour arrière. La copie ne démarre jamais si
    PostgreSQL contient déjà un utilisateur.
    """
    if (
        not settings.auto_migrate_sqlite
        or settings.database_url.startswith("sqlite")
    ):
        return 0
    source_path = Path(settings.legacy_sqlite_path)
    if not source_path.is_file():
        return 0

    with Session(engine) as target_session:
        if target_session.scalar(select(func.count()).select_from(User)):
            return 0

    return copy_sqlite_database(source_path, engine)
