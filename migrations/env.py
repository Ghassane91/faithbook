from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings
from app.models import Base

config = context.config

# L'URL de base vient toujours de la configuration (DATABASE_URL), jamais
# d'alembic.ini : le passage SQLite -> PostgreSQL reste purement configurable.
config.set_main_option("sqlalchemy.url", settings.database_url)

# Les migrations sont jouees DANS le processus de l'application au demarrage.
# fileConfig() y remplacerait les gestionnaires du logger racine et
# l'application perdrait sa journalisation en silence, pour le reste de sa vie.
# On ne configure donc les logs que lorsque Alembic est lance en ligne de
# commande ; app/database.py positionne cet attribut a False.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata

# SQLite ne sait pas faire ALTER TABLE : le mode "batch" recree la table.
# Indispensable pour renommer ou supprimer une colonne sans perdre les donnees.
IS_SQLITE = settings.database_url.startswith("sqlite")


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=IS_SQLITE,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=IS_SQLITE,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
