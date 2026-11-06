"""Appareils Chrome et calendrier de capture local."""
from alembic import op
import sqlalchemy as sa

revision = "a6b7c8d9e0f1"
down_revision = "e3f4a5b6c7d8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("browser_devices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_browser_devices_organization_id", "browser_devices", ["organization_id"])
    op.create_table("browser_targets",
        sa.Column("target_id", sa.Integer(), sa.ForeignKey("targets.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("browser_devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("completed_slot", sa.String(40)),
        sa.Column("manual_key", sa.String(40)),
        sa.Column("lease_key", sa.String(40)),
        sa.Column("lease_hash", sa.String(64)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("last_result_key", sa.String(40)),
        sa.Column("last_run_id", sa.Integer(), sa.ForeignKey("runs.id", ondelete="SET NULL")),
    )
    op.create_index("ix_browser_targets_device_id", "browser_targets", ["device_id"])


def downgrade():
    op.drop_table("browser_targets")
    op.drop_table("browser_devices")
