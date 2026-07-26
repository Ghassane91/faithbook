"""invitations d'organisation

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organization_invitations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM(
                "owner",
                "admin",
                "member",
                "viewer",
                name="membershiprole",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("invited_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["invited_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_organization_invitations_organization_id",
        "organization_invitations",
        ["organization_id"],
    )
    op.create_index(
        "ix_organization_invitations_email",
        "organization_invitations",
        ["email"],
    )
    op.create_index(
        "ix_organization_invitations_token_hash",
        "organization_invitations",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_organization_invitations_invited_by_user_id",
        "organization_invitations",
        ["invited_by_user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_organization_invitations_invited_by_user_id",
        table_name="organization_invitations",
    )
    op.drop_index(
        "ix_organization_invitations_token_hash",
        table_name="organization_invitations",
    )
    op.drop_index(
        "ix_organization_invitations_email",
        table_name="organization_invitations",
    )
    op.drop_index(
        "ix_organization_invitations_organization_id",
        table_name="organization_invitations",
    )
    op.drop_table("organization_invitations")
