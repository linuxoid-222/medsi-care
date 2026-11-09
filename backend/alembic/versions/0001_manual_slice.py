"""create profiles, observations and check-ins

Revision ID: 0001_manual_slice
Revises:
Create Date: 2026-11-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001_manual_slice"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "profiles",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("data_mode", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "observations",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("profile_id", sa.String(length=64), nullable=False),
        sa.Column("metric", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=16), nullable=False),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_observations_profile_id", "observations", ["profile_id"])
    op.create_index("ix_observations_metric", "observations", ["metric"])
    op.create_index("ix_observations_measured_at", "observations", ["measured_at"])
    op.create_table(
        "check_ins",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("profile_id", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_check_ins_profile_id", "check_ins", ["profile_id"])
    op.create_index("ix_check_ins_created_at", "check_ins", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_check_ins_created_at", table_name="check_ins")
    op.drop_index("ix_check_ins_profile_id", table_name="check_ins")
    op.drop_table("check_ins")
    op.drop_index("ix_observations_measured_at", table_name="observations")
    op.drop_index("ix_observations_metric", table_name="observations")
    op.drop_index("ix_observations_profile_id", table_name="observations")
    op.drop_table("observations")
    op.drop_table("profiles")
