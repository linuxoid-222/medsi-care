"""Store profile timezone and numeric analysis snapshots.

Revision ID: 0005_daily_monitoring
Revises: 0004_observation_quality
"""

from alembic import op
import sqlalchemy as sa

revision = "0005_daily_monitoring"
down_revision = "0004_observation_quality"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("profiles", sa.Column("timezone", sa.String(64), nullable=False, server_default="Europe/Moscow"))
    op.add_column("monitoring_events", sa.Column("analysis_details", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("monitoring_events", "analysis_details")
    op.drop_column("profiles", "timezone")
