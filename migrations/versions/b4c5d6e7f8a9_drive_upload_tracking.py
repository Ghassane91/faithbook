"""suivi fiable des envois Google Drive

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, None] = "a3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column(
            "drive_status",
            sa.String(length=20),
            server_default="local",
            nullable=False,
        ),
    )
    op.add_column(
        "runs",
        sa.Column(
            "drive_attempts",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column("runs", sa.Column("drive_last_error", sa.Text(), nullable=True))
    op.add_column(
        "runs",
        sa.Column("drive_uploaded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "runs",
        sa.Column("drive_next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_runs_drive_status", "runs", ["drive_status"])
    op.create_index("ix_runs_drive_next_retry_at", "runs", ["drive_next_retry_at"])
    op.execute(
        "UPDATE runs SET drive_status = 'uploaded' "
        "WHERE drive_file_id IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_runs_drive_next_retry_at", table_name="runs")
    op.drop_index("ix_runs_drive_status", table_name="runs")
    op.drop_column("runs", "drive_next_retry_at")
    op.drop_column("runs", "drive_uploaded_at")
    op.drop_column("runs", "drive_last_error")
    op.drop_column("runs", "drive_attempts")
    op.drop_column("runs", "drive_status")
