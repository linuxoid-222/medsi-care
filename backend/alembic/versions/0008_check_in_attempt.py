"""Persist an optional idempotency key for check-in creation."""

from alembic import op
import sqlalchemy as sa

revision = "0008_check_in_attempt"
down_revision = "0007_event_identity"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("check_ins", sa.Column("creation_key", sa.String(36), nullable=True))
    op.create_index("uq_check_ins_creation_key", "check_ins", ["profile_id", "creation_key"], unique=True)


def downgrade():
    op.drop_index("uq_check_ins_creation_key", table_name="check_ins")
    op.drop_column("check_ins", "creation_key")
