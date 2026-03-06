from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class AuditRun(SQLModel, table=True):
    id: str = Field(primary_key=True)
    created_at: datetime
    source_type: str
    total_transactions: int
    leak_count: int
    total_leak_amount: float
    missed_itc: float
    risk_score: int


class FindingRecord(SQLModel, table=True):
    id: str = Field(primary_key=True)
    audit_id: str = Field(index=True)
    finding_type: str
    severity: str
    amount_impact: float
    confidence: float
    description: str
    tx_ids_csv: str
    suggested_action: str


class GstRecord(SQLModel, table=True):
    id: str = Field(primary_key=True)
    audit_id: str = Field(index=True)
    tx_id: str
    has_gst_invoice: bool
    likely_itc_eligible: bool
    issue: str
    potential_itc_amount: float


class CleanupTaskRecord(SQLModel, table=True):
    id: str = Field(primary_key=True)
    audit_id: str = Field(index=True)
    title: str
    task_type: str
    requires_approval: bool
    payload_json: str
    status: str = "proposed"
    approved_at: Optional[datetime] = None


class ClassifiedTxRecord(SQLModel, table=True):
    id: str = Field(primary_key=True)
    audit_id: str = Field(index=True)
    tx_id: str = Field(index=True)
    pii_redacted_description: str
    normalized_description: str
    merchant: Optional[str] = None
    amount: float
    currency: str
    is_debit: bool
    classifier: str
    predicted_category: str
    confidence: float
    metadata_json: str = "{}"


class FeedbackRecord(SQLModel, table=True):
    id: str = Field(primary_key=True)
    created_at: datetime
    audit_id: str = Field(index=True)
    tx_id: str = Field(index=True)
    corrected_category: str
    predicted_category: str
    training_text: str
    note: Optional[str] = None
    source: str = "api"
    status: str = Field(default="pending", index=True)
    applied_model_version: Optional[str] = None
    applied_at: Optional[datetime] = None


class ModelTrainingRun(SQLModel, table=True):
    id: str = Field(primary_key=True)
    started_at: datetime
    finished_at: Optional[datetime] = None
    status: str
    trigger: str
    feedback_rows_used: int = 0
    model_path: str
    metrics_json: str = "{}"
    error: Optional[str] = None


class AuditJobRecord(SQLModel, table=True):
    id: str = Field(primary_key=True)
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    status: str
    idempotency_key: Optional[str] = Field(default=None, index=True, unique=True)
    request_json: str
    result_json: str = "{}"
    error: Optional[str] = None


class AppSettingRecord(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value_json: str
    updated_at: datetime


class ScheduledAuditRecord(SQLModel, table=True):
    id: str = Field(primary_key=True)
    created_at: datetime
    updated_at: datetime
    status: str = Field(default="active", index=True)
    interval_minutes: int
    next_run_at: datetime = Field(index=True)
    last_run_at: Optional[datetime] = None
    last_job_id: Optional[str] = None
    payload_json: str
    error: Optional[str] = None
