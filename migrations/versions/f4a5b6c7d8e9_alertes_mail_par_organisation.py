"""Organisations : interrupteur des alertes par e-mail

Revision ID: f4a5b6c7d8e9
Revises: c8d9e0f1a2b3

"""

import sqlalchemy as sa
from alembic import op

revision = "f4a5b6c7d8e9"
down_revision = "c8d9e0f1a2b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Activé par défaut : le comportement actuel (mails envoyés) est conservé
    # pour tous les espaces existants.
    with op.batch_alter_table("organizations") as batch:
        batch.add_column(
            sa.Column(
                "email_notifications",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("organizations") as batch:
        batch.drop_column("email_notifications")
