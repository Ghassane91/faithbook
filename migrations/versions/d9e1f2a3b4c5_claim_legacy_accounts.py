"""Rattache les comptes connectes historiques au premier utilisateur.

Revision ID: d9e1f2a3b4c5
Revises: b3d4e5f6a7c8
"""

from typing import Sequence, Union

from alembic import op

revision: str = "d9e1f2a3b4c5"
down_revision: Union[str, None] = "b3d4e5f6a7c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Les anciennes versions autorisaient owner_id=NULL. Dans un contexte avec
    # plusieurs utilisateurs, ces sessions devenaient visibles par tous. Le
    # premier utilisateur (administrateur initial) en devient proprietaire.
    op.execute(
        """
        UPDATE accounts
        SET owner_id = (SELECT MIN(id) FROM users)
        WHERE owner_id IS NULL
          AND EXISTS (SELECT 1 FROM users)
        """
    )


def downgrade() -> None:
    # Impossible de distinguer sans ambiguite un compte historique d'un compte
    # cree apres migration. Ne jamais detacher des sessions en downgrade.
    pass
