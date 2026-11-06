"""File de fiches HuntX pour le navigateur personnel."""
from alembic import op
import sqlalchemy as sa

revision = "b7c8d9e0f1a2"
down_revision = "a6b7c8d9e0f1"
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table("browser_targets") as batch:
        batch.add_column(sa.Column("source_target_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_browser_source_target", "targets", ["source_target_id"], ["id"], ondelete="CASCADE")
        batch.create_index("ix_browser_targets_source_target_id", ["source_target_id"])
    op.create_table("browser_link_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("target_id", sa.Integer(), sa.ForeignKey("browser_targets.target_id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_run_id", sa.Integer(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("result_run_id", sa.Integer(), sa.ForeignKey("runs.id", ondelete="SET NULL")),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("target_id", "source_run_id", name="uq_browser_link_source"))
    op.create_index("ix_browser_link_jobs_target_id", "browser_link_jobs", ["target_id"])
    op.create_index("ix_browser_link_jobs_source_run_id", "browser_link_jobs", ["source_run_id"])

def downgrade():
    op.drop_table("browser_link_jobs")
    with op.batch_alter_table("browser_targets") as batch:
        batch.drop_index("ix_browser_targets_source_target_id")
        batch.drop_constraint("fk_browser_source_target", type_="foreignkey")
        batch.drop_column("source_target_id")
