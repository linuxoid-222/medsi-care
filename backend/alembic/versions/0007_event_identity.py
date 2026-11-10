"""Persist meaningful fact revisions and atomically unique event identities."""

from alembic import op
import sqlalchemy as sa

revision = "0007_event_identity"
down_revision = "0006_fact_lifecycle"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("check_ins", sa.Column("facts_revision", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("monitoring_events", sa.Column("identity_key", sa.String(64), nullable=True))
    op.create_index("uq_monitoring_events_identity_key", "monitoring_events", ["identity_key"], unique=True)
    # Legacy rows retain NULL keys and all historical notifications/read_at.


def downgrade():
    op.drop_index("uq_monitoring_events_identity_key", table_name="monitoring_events")
    op.drop_column("monitoring_events", "identity_key")
    op.drop_column("check_ins", "facts_revision")
