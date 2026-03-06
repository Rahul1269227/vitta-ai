from __future__ import annotations

from datetime import datetime
from typing import TypedDict

from sentinelfi.domain.models import (
    AuditInput,
    ClassificationDecision,
    ClassifiedTransaction,
    CleanupTask,
    GstFinding,
    LeakFinding,
    NormalizedTransaction,
    Transaction,
)


class AuditState(TypedDict, total=False):
    audit_id: str
    created_at: datetime
    request: AuditInput
    raw_transactions: list[Transaction]
    normalized_transactions: list[NormalizedTransaction]
    mcc_classified_transactions: list[ClassifiedTransaction]
    ml_classified_transactions: list[ClassifiedTransaction]
    ml_escalated_transactions: list[NormalizedTransaction]
    remaining_transactions: list[NormalizedTransaction]
    routed_to_llm: list[NormalizedTransaction]
    routed_to_slm: list[NormalizedTransaction]
    route_reason_by_tx_id: dict[str, str]
    slm_classified_transactions: list[ClassifiedTransaction]
    llm_classified_transactions: list[ClassifiedTransaction]
    slm_escalated_transactions: list[NormalizedTransaction]
    classified_transactions: list[ClassifiedTransaction]
    classification_decisions: list[ClassificationDecision]
    leak_findings: list[LeakFinding]
    gst_findings: list[GstFinding]
    cleanup_tasks: list[CleanupTask]
    errors: list[str]
