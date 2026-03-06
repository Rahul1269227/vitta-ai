"""add idempotency key to audit job record

Revision ID: 20260213_03
Revises: 20260213_02
Create Date: 2026-02-13
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260213_03"
down_revision = "20260213_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("auditjobrecord", sa.Column("idempotency_key", sa.String(), nullable=True))
    op.create_index(
        "ix_auditjobrecord_idempotency_key",
        "auditjobrecord",
        ["idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_auditjobrecord_idempotency_key", table_name="auditjobrecord")
    op.drop_column("auditjobrecord", "idempotency_key")
