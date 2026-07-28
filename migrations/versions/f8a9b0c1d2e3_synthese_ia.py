"""Synthese IA des changements detectes

Le ratio de changement dit combien la page a bouge, pas ce qui a bouge.
On conserve ici une phrase lisible produite a partir des lignes apparues
et disparues, pour que la fiche d execution reponde a la vraie question :
qu est-ce qui est nouveau ?

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2

"""

import sqlalchemy as sa
from alembic import op

revision = "f8a9b0c1d2e3"
down_revision = "e7f8a9b0c1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("ai_summary", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "ai_summary")