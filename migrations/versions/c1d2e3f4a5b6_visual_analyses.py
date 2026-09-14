"""Persist scoped visual analyses and resumable archive receipts."""
from alembic import op
import sqlalchemy as sa
revision = "c1d2e3f4a5b6"
down_revision = "b0c1d2e3f4a5"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("visual_analyses",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("source", sa.String(300), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("storage_bytes", sa.BigInteger(), nullable=False),
        sa.Column("archive_status", sa.String(20), nullable=False),
        sa.Column("archive_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archive_manifest", sa.Text(), nullable=False))
    op.create_index("ix_visual_analyses_organization_id", "visual_analyses", ["organization_id"])

def downgrade():
    op.drop_index("ix_visual_analyses_organization_id", table_name="visual_analyses")
    op.drop_table("visual_analyses")
