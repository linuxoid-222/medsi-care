"""Bind confirmation to text revisions and preserve event text evidence."""

from alembic import op
import sqlalchemy as sa

revision = "0006_fact_lifecycle"
down_revision = "0005_daily_monitoring"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("check_ins", sa.Column("text_revision", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("check_ins", sa.Column("confirmed_revision", sa.Integer(), nullable=True))
    op.add_column("check_ins", sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("symptom_facts", sa.Column("text_revision", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("monitoring_events", sa.Column("text_provenance", sa.JSON(), nullable=True))
    # Legacy records require explicit reconfirmation: their exact reviewed
    # revision/time (including an empty review) cannot safely be inferred.


def downgrade():
    op.drop_column("monitoring_events", "text_provenance")
    op.drop_column("symptom_facts", "text_revision")
    op.drop_column("check_ins", "confirmed_at")
    op.drop_column("check_ins", "confirmed_revision")
    op.drop_column("check_ins", "text_revision")
