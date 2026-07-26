"""quotas et retention par organisation

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c5d6e7f8a9b0"
down_revision: Union[str, None] = "b4c5d6e7f8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("organizations") as batch:
        batch.add_column(
            sa.Column(
                "quota_accounts",
                sa.Integer(),
                server_default="10",
                nullable=False,
            )
        )
        batch.add_column(
            sa.Column(
                "quota_targets",
                sa.Integer(),
                server_default="100",
                nullable=False,
            )
        )
        batch.add_column(
            sa.Column(
                "quota_daily_captures",
                sa.Integer(),
                server_default="500",
                nullable=False,
            )
        )
        batch.add_column(
            sa.Column(
                "quota_storage_bytes",
                sa.BigInteger(),
                server_default="10737418240",
                nullable=False,
            )
        )
        batch.add_column(
            sa.Column(
                "retention_days",
                sa.Integer(),
                server_default="90",
                nullable=False,
            )
        )
        batch.create_check_constraint(
            "ck_org_quota_accounts_nonnegative",
            "quota_accounts >= 0",
        )
        batch.create_check_constraint(
            "ck_org_quota_targets_nonnegative",
            "quota_targets >= 0",
        )
        batch.create_check_constraint(
            "ck_org_quota_daily_captures_nonnegative",
            "quota_daily_captures >= 0",
        )
        batch.create_check_constraint(
            "ck_org_quota_storage_bytes_nonnegative",
            "quota_storage_bytes >= 0",
        )
        batch.create_check_constraint(
            "ck_org_retention_days_nonnegative",
            "retention_days >= 0",
        )


def downgrade() -> None:
    with op.batch_alter_table("organizations") as batch:
        batch.drop_constraint(
            "ck_org_retention_days_nonnegative", type_="check"
        )
        batch.drop_constraint(
            "ck_org_quota_storage_bytes_nonnegative", type_="check"
        )
        batch.drop_constraint(
            "ck_org_quota_daily_captures_nonnegative", type_="check"
        )
        batch.drop_constraint(
            "ck_org_quota_targets_nonnegative", type_="check"
        )
        batch.drop_constraint(
            "ck_org_quota_accounts_nonnegative", type_="check"
        )
        batch.drop_column("retention_days")
        batch.drop_column("quota_storage_bytes")
        batch.drop_column("quota_daily_captures")
        batch.drop_column("quota_targets")
        batch.drop_column("quota_accounts")
