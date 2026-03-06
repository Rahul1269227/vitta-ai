"""initial schema

Revision ID: 20260213_01
Revises:
Create Date: 2026-02-13
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260213_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auditrun",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("total_transactions", sa.Integer(), nullable=False),
        sa.Column("leak_count", sa.Integer(), nullable=False),
        sa.Column("total_leak_amount", sa.Float(), nullable=False),
        sa.Column("missed_itc", sa.Float(), nullable=False),
        sa.Column("risk_score", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "findingrecord",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("audit_id", sa.String(), nullable=False),
        sa.Column("finding_type", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("amount_impact", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("tx_ids_csv", sa.String(), nullable=False),
        sa.Column("suggested_action", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_findingrecord_audit_id", "findingrecord", ["audit_id"], unique=False)

    op.create_table(
        "gstrecord",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("audit_id", sa.String(), nullable=False),
        sa.Column("tx_id", sa.String(), nullable=False),
        sa.Column("has_gst_invoice", sa.Boolean(), nullable=False),
        sa.Column("likely_itc_eligible", sa.Boolean(), nullable=False),
        sa.Column("issue", sa.String(), nullable=False),
        sa.Column("potential_itc_amount", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_gstrecord_audit_id", "gstrecord", ["audit_id"], unique=False)

    op.create_table(
        "cleanuptaskrecord",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("audit_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("task_type", sa.String(), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False),
        sa.Column("payload_json", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cleanuptaskrecord_audit_id", "cleanuptaskrecord", ["audit_id"], unique=False)

    op.create_table(
        "classifiedtxrecord",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("audit_id", sa.String(), nullable=False),
        sa.Column("tx_id", sa.String(), nullable=False),
        sa.Column("pii_redacted_description", sa.String(), nullable=False),
        sa.Column("normalized_description", sa.String(), nullable=False),
        sa.Column("merchant", sa.String(), nullable=True),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("is_debit", sa.Boolean(), nullable=False),
        sa.Column("classifier", sa.String(), nullable=False),
        sa.Column("predicted_category", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("metadata_json", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_classifiedtxrecord_audit_id", "classifiedtxrecord", ["audit_id"], unique=False)
    op.create_index("ix_classifiedtxrecord_tx_id", "classifiedtxrecord", ["tx_id"], unique=False)

    op.create_table(
        "feedbackrecord",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("audit_id", sa.String(), nullable=False),
        sa.Column("tx_id", sa.String(), nullable=False),
        sa.Column("corrected_category", sa.String(), nullable=False),
        sa.Column("predicted_category", sa.String(), nullable=False),
        sa.Column("training_text", sa.String(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("applied_model_version", sa.String(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_feedbackrecord_audit_id", "feedbackrecord", ["audit_id"], unique=False)
    op.create_index("ix_feedbackrecord_tx_id", "feedbackrecord", ["tx_id"], unique=False)

    op.create_table(
        "modeltrainingrun",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("trigger", sa.String(), nullable=False),
        sa.Column("feedback_rows_used", sa.Integer(), nullable=False),
        sa.Column("model_path", sa.String(), nullable=False),
        sa.Column("metrics_json", sa.String(), nullable=False),
        sa.Column("error", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "auditjobrecord",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("request_json", sa.String(), nullable=False),
        sa.Column("result_json", sa.String(), nullable=False),
        sa.Column("error", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("auditjobrecord")
    op.drop_table("modeltrainingrun")
    op.drop_index("ix_feedbackrecord_tx_id", table_name="feedbackrecord")
    op.drop_index("ix_feedbackrecord_audit_id", table_name="feedbackrecord")
    op.drop_table("feedbackrecord")
    op.drop_index("ix_classifiedtxrecord_tx_id", table_name="classifiedtxrecord")
    op.drop_index("ix_classifiedtxrecord_audit_id", table_name="classifiedtxrecord")
    op.drop_table("classifiedtxrecord")
    op.drop_index("ix_cleanuptaskrecord_audit_id", table_name="cleanuptaskrecord")
    op.drop_table("cleanuptaskrecord")
    op.drop_index("ix_gstrecord_audit_id", table_name="gstrecord")
    op.drop_table("gstrecord")
    op.drop_index("ix_findingrecord_audit_id", table_name="findingrecord")
    op.drop_table("findingrecord")
    op.drop_table("auditrun")
