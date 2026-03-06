from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class TxCategory(str, Enum):
    BUSINESS = "business"
    PERSONAL = "personal"
    UNKNOWN = "unknown"


class LeakType(str, Enum):
    DUPLICATE_SUBSCRIPTION = "duplicate_subscription"
    ZOMBIE_SUBSCRIPTION = "zombie_subscription"
    FREE_TRIAL = "forgotten_free_trial"
    PRICE_HIKE = "price_hike"
    SAAS_SPRAWL = "saas_sprawl"
    TAX_MISCATEGORY = "tax_miscategory"


class SourceType(str, Enum):
    CSV = "csv"
    PDF = "pdf"
    STRIPE = "stripe"
    RAZORPAY = "razorpay"


class Transaction(BaseModel):
    tx_id: str
    tx_date: date
    description: str
    amount: float
    currency: str = "INR"
    is_debit: bool = True
    merchant: str | None = None
    account_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class NormalizedTransaction(Transaction):
    normalized_description: str
    pii_redacted_description: str


class ClassifiedTransaction(NormalizedTransaction):
    category: TxCategory = TxCategory.UNKNOWN
    taxonomy_category: str | None = None
    confidence: float = 0.0
    classifier: Literal["mcc", "ml", "slm", "llm", "rule"] = "rule"
    requires_review: bool = False
    explanations: list[str] = Field(default_factory=list)


class ClassifierVote(BaseModel):
    classifier: Literal["mcc", "ml", "slm", "llm", "rule"]
    category: TxCategory
    confidence: float
    rationale: str


class ClassificationDecision(BaseModel):
    tx_id: str
    route: Literal["mcc", "ml", "slm", "llm", "mixed"]
    final_classifier: Literal["mcc", "ml", "slm", "llm", "rule"]
    category: TxCategory
    confidence: float
    requires_review: bool
    decision_path: list[str] = Field(default_factory=list)
    votes: list[ClassifierVote] = Field(default_factory=list)


class LeakFinding(BaseModel):
    finding_id: str
    leak_type: LeakType
    severity: Literal["P1", "P2", "P3"]
    amount_impact: float
    confidence: float
    description: str
    tx_ids: list[str] = Field(default_factory=list)
    suggested_action: str


class GstFinding(BaseModel):
    finding_id: str
    tx_id: str
    has_gst_invoice: bool
    likely_itc_eligible: bool
    issue: str
    potential_itc_amount: float = 0.0


class CleanupTask(BaseModel):
    task_id: str
    title: str
    task_type: Literal["ledger_reclass", "email_draft", "invoice_fetch", "gst_recon"]
    requires_approval: bool = True
    payload: dict[str, Any] = Field(default_factory=dict)


class AuditSummary(BaseModel):
    audit_id: str
    created_at: datetime
    total_transactions: int
    leak_count: int
    total_leak_amount: float
    missed_itc: float
    risk_score: int
    review_count: int = 0
    avg_classification_confidence: float = 0.0


class AuditInput(BaseModel):
    source_type: SourceType
    source_path: str | None = None
    source_config: dict[str, Any] = Field(default_factory=dict)


class AuditOutput(BaseModel):
    summary: AuditSummary
    findings: list[LeakFinding]
    gst_findings: list[GstFinding]
    cleanup_tasks: list[CleanupTask]
    classification_decisions: list[ClassificationDecision] = Field(default_factory=list)


class ClassifierEvaluationRow(BaseModel):
    raw_text: str
    expected: TxCategory
    predicted: TxCategory
    confidence: float
