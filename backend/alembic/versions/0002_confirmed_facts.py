"""store confirmed check-in facts

Revision ID: 0002_confirmed_facts
Revises: 0001_manual_slice
Create Date: 2026-11-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_confirmed_facts"
down_revision: Union[str, None] = "0001_manual_slice"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("check_ins", sa.Column("corrected_text", sa.Text(), nullable=True))
    op.create_table(
        "symptom_facts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("check_in_id", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("polarity", sa.String(length=16), nullable=False),
        sa.Column("temporal_context", sa.String(length=256), nullable=True),
        sa.Column("evidence", sa.String(length=500), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("confirmed", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["check_in_id"], ["check_ins.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_symptom_facts_check_in_id", "symptom_facts", ["check_in_id"])


def downgrade() -> None:
    op.drop_index("ix_symptom_facts_check_in_id", table_name="symptom_facts")
    op.drop_table("symptom_facts")
    op.drop_column("check_ins", "corrected_text")
