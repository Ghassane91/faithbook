"""Cibles : capture des fiches produit liees depuis le tableau de la page

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7

"""

import sqlalchemy as sa
from alembic import op

revision = "e3f4a5b6c7d8"
down_revision = "d2e3f4a5b6c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("targets") as batch:
        batch.add_column(
            sa.Column("capture_row_links", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("targets") as batch:
        batch.drop_column("capture_row_links")
