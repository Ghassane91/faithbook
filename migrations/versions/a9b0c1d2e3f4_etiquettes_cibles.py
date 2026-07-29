"""Etiquettes de regroupement des cibles

Une cible n avait aucun moyen d etre rangee : au-dela d une dizaine de
pages suivies, la liste devient illisible. Des etiquettes libres separees
par des virgules permettent de filtrer par client ou par theme sans
imposer une arborescence figee.

Revision ID: a9b0c1d2e3f4
Revises: f8a9b0c1d2e3

"""

import sqlalchemy as sa
from alembic import op

revision = "a9b0c1d2e3f4"
down_revision = "f8a9b0c1d2e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("targets", sa.Column("tags", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("targets", "tags")