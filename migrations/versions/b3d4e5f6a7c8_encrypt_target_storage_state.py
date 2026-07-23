"""encrypt target.storage_state_json at rest

Chiffre (Fernet) le storage_state legacy stocke en clair sur les cibles.
Idempotent : une valeur deja chiffree (dechiffrable) est laissee telle quelle.

Revision ID: b3d4e5f6a7c8
Revises: a7b8c9d0e1f2
Create Date: 2026-07-23 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b3d4e5f6a7c8'
down_revision: Union[str, None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_targets = sa.table(
    "targets",
    sa.column("id", sa.Integer),
    sa.column("storage_state_json", sa.Text),
)


def upgrade() -> None:
    from app.services import crypto

    bind = op.get_bind()
    rows = bind.execute(sa.select(_targets.c.id, _targets.c.storage_state_json)
                         .where(_targets.c.storage_state_json.is_not(None))).fetchall()
    for row in rows:
        raw = row.storage_state_json
        if not raw:
            continue
        # Deja chiffrable => deja migre (execution precedente, ou saisi apres
        # que le code applicatif chiffre desormais a l'ecriture) : ne pas y toucher.
        if crypto.decrypt_text(raw) is not None:
            continue
        chiffre = crypto.encrypt_text(raw)
        bind.execute(
            _targets.update().where(_targets.c.id == row.id).values(storage_state_json=chiffre)
        )


def downgrade() -> None:
    from app.services import crypto

    bind = op.get_bind()
    rows = bind.execute(sa.select(_targets.c.id, _targets.c.storage_state_json)
                         .where(_targets.c.storage_state_json.is_not(None))).fetchall()
    for row in rows:
        raw = row.storage_state_json
        if not raw:
            continue
        clair = crypto.decrypt_text(raw)
        if clair is None:
            continue  # deja en clair (ou illisible) : rien a defaire
        bind.execute(
            _targets.update().where(_targets.c.id == row.id).values(storage_state_json=clair)
        )
