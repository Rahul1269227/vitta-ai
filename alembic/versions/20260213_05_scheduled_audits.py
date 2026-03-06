"""add scheduled audits table

Revision ID: 20260213_05
Revises: 20260213_04
Create Date: 2026-02-13
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260213_05"
down_revision = "20260213_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scheduledauditrecord",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_job_id", sa.String(), nullable=True),
        sa.Column("payload_json", sa.String(), nullable=False),
        sa.Column("error", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scheduledauditrecord_status", "scheduledauditrecord", ["status"], unique=False)
    op.create_index(
        "ix_scheduledauditrecord_next_run_at",
        "scheduledauditrecord",
        ["next_run_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_scheduledauditrecord_next_run_at", table_name="scheduledauditrecord")
    op.drop_index("ix_scheduledauditrecord_status", table_name="scheduledauditrecord")
    op.drop_table("scheduledauditrecord")
