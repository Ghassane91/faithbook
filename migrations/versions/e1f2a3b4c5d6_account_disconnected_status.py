"""ajoute le statut de compte disconnected

Revision ID: e1f2a3b4c5d6
Revises: d9e1f2a3b4c5
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "d9e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "ALTER TYPE accountstatus ADD VALUE IF NOT EXISTS "
            "'disconnected' BEFORE 'expired'"
        )
        return
    old = sa.Enum(
        "never", "connected", "expired", "verification_required", "error",
        name="accountstatus",
    )
    new = sa.Enum(
        "never", "connected", "disconnected", "expired",
        "verification_required", "error", name="accountstatus",
    )
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.alter_column(
            "status", existing_type=old, type_=new, existing_nullable=False
        )


def downgrade() -> None:
    # Une valeur inconnue empêcherait la reconstruction de la table.
    op.execute(
        "UPDATE accounts SET status = 'expired' WHERE status = 'disconnected'"
    )
    if op.get_bind().dialect.name == "postgresql":
        # PostgreSQL ne sait pas retirer une valeur d'ENUM sans recréer le
        # type. La conserver est sans impact et rend le downgrade non destructif.
        return
    new = sa.Enum(
        "never", "connected", "disconnected", "expired",
        "verification_required", "error", name="accountstatus",
    )
    old = sa.Enum(
        "never", "connected", "expired", "verification_required", "error",
        name="accountstatus",
    )
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.alter_column(
            "status", existing_type=new, type_=old, existing_nullable=False
        )
