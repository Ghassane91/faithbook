"""Cles de stockage distant en texte long

Un identifiant Google Drive fait 33 caracteres, d ou le String(120) initial.
Une cle S3 peut atteindre 1024 caracteres : avec un prefixe de bucket ou un
sous-dossier de cible, la valeur aurait ete tronquee en base et la capture
serait devenue introuvable. Les deux colonnes passent donc en texte.

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0

"""

import sqlalchemy as sa
from alembic import op

revision = "d6e7f8a9b0c1"
down_revision = "c5d6e7f8a9b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.alter_column(
            "drive_folder_id",
            existing_type=sa.String(length=120),
            type_=sa.Text(),
            existing_nullable=True,
        )
        batch.alter_column(
            "drive_file_id",
            existing_type=sa.String(length=120),
            type_=sa.Text(),
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.alter_column(
            "drive_file_id",
            existing_type=sa.Text(),
            type_=sa.String(length=120),
            existing_nullable=True,
        )
        batch.alter_column(
            "drive_folder_id",
            existing_type=sa.Text(),
            type_=sa.String(length=120),
            existing_nullable=True,
        )