"""Extraction IA : resultats par capture

Une ligne par execution capturee et extraite : regle appliquee, lignes
validees (JSON), anomalies, et empreinte du texte pour eviter de rappeler
le modele quand la page n a pas change.

Revision ID: c1d2e3f4a5b6
Revises: b0c1d2e3f4a5

"""

import sqlalchemy as sa
from alembic import op

revision = "c1d2e3f4a5b6"
down_revision = "b0c1d2e3f4a5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "page_extractions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("regle", sa.String(length=40), nullable=False),
        sa.Column("fournisseur", sa.String(length=40), nullable=True),
        sa.Column("modele", sa.String(length=120), nullable=True),
        sa.Column("texte_sha256", sa.String(length=64), nullable=False),
        sa.Column("lignes_json", sa.Text(), nullable=False),
        sa.Column("anomalies_json", sa.Text(), nullable=False),
        sa.Column("nb_lignes", sa.Integer(), nullable=False),
        sa.Column("tronque", sa.Boolean(), nullable=False),
        sa.Column("reprise", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_id"], ["targets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uq_page_extractions_run_id"),
    )
    op.create_index("ix_page_extractions_target_id", "page_extractions", ["target_id"])
    op.create_index("ix_page_extractions_created_at", "page_extractions", ["created_at"])
    op.create_index("ix_page_extractions_texte_sha256", "page_extractions", ["texte_sha256"])


def downgrade() -> None:
    op.drop_index("ix_page_extractions_texte_sha256", table_name="page_extractions")
    op.drop_index("ix_page_extractions_created_at", table_name="page_extractions")
    op.drop_index("ix_page_extractions_target_id", table_name="page_extractions")
    op.drop_table("page_extractions")
