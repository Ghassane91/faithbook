"""Texte de page conserve pour la comparaison de contenu

La comparaison pixel mesure des positions absolues : sur un fil social
reordonne, elle signale 45% de changement sans qu aucun contenu ne soit
nouveau. Conserver le texte visible permet de comparer les contenus eux-memes,
independamment de leur place a l ecran.

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1

"""

import sqlalchemy as sa
from alembic import op

revision = "e7f8a9b0c1d2"
down_revision = "d6e7f8a9b0c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("body_text", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "body_text")