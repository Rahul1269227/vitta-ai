from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from sentinelfi.domain.models import AuditOutput, SourceType


class AuditRunRequest(BaseModel):
    source_type: SourceType
    source_path: str | None = None
    source_config: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None
    client_name: str = "Client"
    report_period: str = "Last 90 days"
    generate_pdf: bool = True
    generate_markdown: bool = True


class AuditRunResponse(BaseModel):
    output: AuditOutput
    markdown_report_path: str | None = None
    pdf_report_path: str | None = None


class AuditJobSubmitResponse(BaseModel):
    job_id: str
    status: str
    created_at: datetime


class AuditJobStatusResponse(BaseModel):
    job_id: str
    status: str
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    result: AuditRunResponse | None = None


class AuditJobListItem(BaseModel):
    job_id: str
    status: str
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None


class CleanupRunRequest(BaseModel):
    audit_id: str
    approved_task_ids: list[str] = Field(default_factory=list)


class CleanupRunResponse(BaseModel):
    executed: list[dict[str, Any]]
    skipped: list[str]


class AuditRunSummary(BaseModel):
    id: str
    created_at: datetime
    source_type: str
    total_transactions: int
    leak_count: int
    total_leak_amount: float
    missed_itc: float
    risk_score: int


class RuntimeStatsResponse(BaseModel):
    total_audits: float
    avg_latency_ms: float
    avg_transactions_per_audit: float
    avg_leaks_per_audit: float
    avg_review_rate: float
    ml_samples: float = 0.0
    ml_drift_status: str = "unknown"
    ml_confidence_shift_z: float = 0.0
    ml_business_rate_delta: float = 0.0
    ml_text_token_shift_z: float = 0.0
    ml_confidence_psi: float = 0.0


class FeedbackCorrectionRequest(BaseModel):
    tx_id: str
    corrected_category: str
    note: str | None = None


class FeedbackIngestRequest(BaseModel):
    audit_id: str
    corrections: list[FeedbackCorrectionRequest]
    auto_retrain: bool = True
    source: str = "api"


class FeedbackIngestResponse(BaseModel):
    accepted_count: int
    rejected: list[dict[str, str]]
    pending_feedback_count: int
    retrain_triggered: bool
    training_run_id: str | None = None


class RetrainResponse(BaseModel):
    training_run_id: str
    pending_feedback_count: int
    status: str


class ActiveLearningStatusResponse(BaseModel):
    pending_feedback_count: int
    total_feedback_count: int
    training_in_progress: bool
    latest_training_run: dict[str, Any] | None = None


# -------------------------------------------------------------------
# Merchant resolver
# -------------------------------------------------------------------


class MerchantResolveRequest(BaseModel):
    text: str
    threshold: float = 0.70
    top_k: int = 3


class MerchantMatchResponse(BaseModel):
    merchant_id: str
    canonical_name: str
    category: str
    subcategory: str | None = None
    similarity_score: float
    match_type: str


# -------------------------------------------------------------------
# Export
# -------------------------------------------------------------------


class ExportRequest(BaseModel):
    audit_id: str
    format: str = "csv"  # csv | quickbooks_iif | xero_csv | json | quickbooks_json | xero_json
    include_explanations: bool = False


class AdminSettingsUpdateRequest(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)


class AdminSettingsResponse(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)
    mutable_keys: list[str] = Field(default_factory=list)


class AuditScheduleCreateRequest(BaseModel):
    interval_minutes: int = Field(ge=1)
    payload: AuditRunRequest


class AuditScheduleResponse(BaseModel):
    id: str
    created_at: datetime
    updated_at: datetime
    status: str
    interval_minutes: int
    next_run_at: datetime
    last_run_at: datetime | None = None
    last_job_id: str | None = None
    error: str | None = None
