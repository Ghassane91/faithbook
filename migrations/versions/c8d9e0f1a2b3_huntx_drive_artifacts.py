"""Reprise des fiches Chrome et archivage HuntX durable par date et ligne."""
from alembic import op
import sqlalchemy as sa

revision = "c8d9e0f1a2b3"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("browser_link_jobs") as batch:
        batch.add_column(sa.Column("row_references", sa.Text(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_index("ix_browser_link_jobs_next_attempt_at", ["next_attempt_at"])
    op.create_table("huntx_drive_artifacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_run_id", sa.Integer(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("result_run_id", sa.Integer(), sa.ForeignKey("runs.id", ondelete="SET NULL")),
        sa.Column("dedupe_key", sa.String(200), nullable=False, unique=True),
        sa.Column("capture_date", sa.String(10), nullable=False),
        sa.Column("row_key", sa.String(200)),
        sa.Column("row_label", sa.String(240)),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("marketplace", sa.String(160)),
        sa.Column("local_path", sa.Text(), nullable=False),
        sa.Column("filename", sa.String(240), nullable=False),
        sa.Column("drive_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("drive_folder_id", sa.Text()),
        sa.Column("drive_file_id", sa.Text()),
        sa.Column("drive_file_link", sa.Text()),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text()),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
        sa.Column("uploaded_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    for column in ("source_run_id", "result_run_id", "capture_date", "drive_status", "next_retry_at"):
        op.create_index(f"ix_huntx_drive_artifacts_{column}", "huntx_drive_artifacts", [column])


def downgrade():
    op.drop_table("huntx_drive_artifacts")
    with op.batch_alter_table("browser_link_jobs") as batch:
        batch.drop_index("ix_browser_link_jobs_next_attempt_at")
        batch.drop_column("next_attempt_at")
        batch.drop_column("attempt_count")
        batch.drop_column("row_references")
