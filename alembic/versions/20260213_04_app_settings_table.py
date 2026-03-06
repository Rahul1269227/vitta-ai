"""add app settings table

Revision ID: 20260213_04
Revises: 20260213_03
Create Date: 2026-02-13
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260213_04"
down_revision = "20260213_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "appsettingrecord",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value_json", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("appsettingrecord")
