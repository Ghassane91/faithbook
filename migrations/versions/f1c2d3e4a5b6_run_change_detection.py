"""run change detection (change_ratio, changed)

Revision ID: f1c2d3e4a5b6
Revises: e5b2a1d7c3f9
Create Date: 2026-07-23 09:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f1c2d3e4a5b6'
down_revision: Union[str, None] = 'e5b2a1d7c3f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('runs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('change_ratio', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('changed', sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('runs', schema=None) as batch_op:
        batch_op.drop_column('changed')
        batch_op.drop_column('change_ratio')
