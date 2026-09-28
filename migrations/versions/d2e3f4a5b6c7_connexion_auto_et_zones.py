"""Connexion automatique des comptes et zones defilantes des cibles

- accounts.login_url, encrypted_credentials, login_selectors : reconnexion
  automatique pour les sites qui l'autorisent (HuntX). Identifiants chiffres.
- targets.expand_scroll_areas : deplie les listes a defilement interne avant
  la capture, pour les photographier en entier.

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6

"""

import sqlalchemy as sa
from alembic import op

revision = "d2e3f4a5b6c7"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("accounts") as batch:
        batch.add_column(sa.Column("login_url", sa.Text(), nullable=True))
        batch.add_column(sa.Column("encrypted_credentials", sa.Text(), nullable=True))
        batch.add_column(sa.Column("login_selectors", sa.Text(), nullable=True))
    with op.batch_alter_table("targets") as batch:
        batch.add_column(
            sa.Column("expand_scroll_areas", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("targets") as batch:
        batch.drop_column("expand_scroll_areas")
    with op.batch_alter_table("accounts") as batch:
        batch.drop_column("login_selectors")
        batch.drop_column("encrypted_credentials")
        batch.drop_column("login_url")
