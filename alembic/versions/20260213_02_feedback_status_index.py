"""add feedback status index

Revision ID: 20260213_02
Revises: 20260213_01
Create Date: 2026-02-13
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260213_02"
down_revision = "20260213_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_feedbackrecord_status", "feedbackrecord", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_feedbackrecord_status", table_name="feedbackrecord")
