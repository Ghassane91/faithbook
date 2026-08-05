"""Cadence par intervalle en minutes

Une cible ne pouvait etre planifiee qu a heure fixe (run_time) ou via une
expression cron. Surveiller un concurrent demande plutot un passage regulier
— toutes les 30 minutes — que l on ne veut pas obliger l utilisateur a
traduire en syntaxe cron.

Un champ dedie plutot qu un cron "*/N" genere : "*/N" n est correct que si N
divise 60. Avec "*/45" cron declenche a :00 et :45 puis saute a l heure
suivante, soit un ecart de 15 minutes et non 45 ; et au-dela de 59 il perd
tout sens. L intervalle reel est confie a l IntervalTrigger d APScheduler.

Revision ID: b0c1d2e3f4a5
Revises: a9b0c1d2e3f4

"""

import sqlalchemy as sa
from alembic import op

revision = "b0c1d2e3f4a5"
down_revision = "a9b0c1d2e3f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("targets", sa.Column("interval_minutes", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("targets", "interval_minutes")
