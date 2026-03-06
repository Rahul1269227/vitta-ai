from __future__ import annotations

import json
from datetime import datetime

from sqlmodel import Session, select

from sentinelfi.domain.models import AuditOutput, ClassifiedTransaction, CleanupTask
from sentinelfi.repositories.models import (
    AuditRun,
    ClassifiedTxRecord,
    CleanupTaskRecord,
    FindingRecord,
    GstRecord,
)


class AuditRepository:
    def __init__(self, session: Session):
        self.session = session

    def save_audit_output(self, source_type: str, output: AuditOutput) -> None:
        summary = output.summary
        run = AuditRun(
            id=summary.audit_id,
            created_at=summary.created_at,
            source_type=source_type,
            total_transactions=summary.total_transactions,
            leak_count=summary.leak_count,
            total_leak_amount=summary.total_leak_amount,
            missed_itc=summary.missed_itc,
            risk_score=summary.risk_score,
        )
        self.session.add(run)

        for finding in output.findings:
            self.session.add(
                FindingRecord(
                    id=finding.finding_id,
                    audit_id=summary.audit_id,
                    finding_type=finding.leak_type.value,
                    severity=finding.severity,
                    amount_impact=finding.amount_impact,
                    confidence=finding.confidence,
                    description=finding.description,
                    tx_ids_csv=",".join(finding.tx_ids),
                    suggested_action=finding.suggested_action,
                )
            )

        for item in output.gst_findings:
            self.session.add(
                GstRecord(
                    id=item.finding_id,
                    audit_id=summary.audit_id,
                    tx_id=item.tx_id,
                    has_gst_invoice=item.has_gst_invoice,
                    likely_itc_eligible=item.likely_itc_eligible,
                    issue=item.issue,
                    potential_itc_amount=item.potential_itc_amount,
                )
            )

        for task in output.cleanup_tasks:
            self.session.add(
                CleanupTaskRecord(
                    id=task.task_id,
                    audit_id=summary.audit_id,
                    title=task.title,
                    task_type=task.task_type,
                    requires_approval=task.requires_approval,
                    payload_json=json.dumps(task.payload),
                )
            )

        self.session.commit()

    def save_classified_transactions(
        self,
        audit_id: str,
        transactions: list[ClassifiedTransaction],
    ) -> None:
        for idx, tx in enumerate(transactions):
            record_id = f"{audit_id}:{tx.tx_id}:{idx}"
            self.session.add(
                ClassifiedTxRecord(
                    id=record_id,
                    audit_id=audit_id,
                    tx_id=tx.tx_id,
                    pii_redacted_description=tx.pii_redacted_description,
                    normalized_description=tx.normalized_description,
                    merchant=tx.merchant,
                    amount=tx.amount,
                    currency=tx.currency,
                    is_debit=tx.is_debit,
                    classifier=tx.classifier,
                    predicted_category=tx.category.value,
                    confidence=tx.confidence,
                    metadata_json=json.dumps(tx.metadata),
                )
            )

        self.session.commit()

    def get_audit_runs(self, limit: int = 20) -> list[AuditRun]:
        statement = select(AuditRun).order_by(AuditRun.created_at.desc()).limit(limit)
        return list(self.session.exec(statement).all())

    def get_audit_run(self, audit_id: str) -> AuditRun | None:
        statement = select(AuditRun).where(AuditRun.id == audit_id)
        return self.session.exec(statement).first()

    def get_classified_transactions_as_dicts(self, audit_id: str) -> list[dict]:
        """Return classified transactions as plain dicts suitable for export."""
        statement = (
            select(ClassifiedTxRecord)
            .where(ClassifiedTxRecord.audit_id == audit_id)
            .order_by(ClassifiedTxRecord.id.asc())
        )
        rows = list(self.session.exec(statement).all())
        out: list[dict] = []
        for row in rows:
            metadata: dict = {}
            if row.metadata_json:
                try:
                    metadata = json.loads(row.metadata_json)
                except json.JSONDecodeError:
                    pass
            out.append(
                {
                    "id": row.tx_id,
                    "date": metadata.get("date", ""),
                    "amount": row.amount,
                    "currency": row.currency,
                    "category": row.predicted_category,
                    "subcategory": metadata.get("subcategory", ""),
                    "merchant": row.merchant or "",
                    "description": row.pii_redacted_description,
                    "text": row.pii_redacted_description,
                    "confidence": row.confidence,
                    "method": row.classifier,
                    "requires_review": metadata.get("requires_review", False),
                    "explanations": metadata.get("explanations", []),
                    "ensemble_votes": metadata.get("ensemble_votes", {}),
                }
            )
        return out

    def get_cleanup_tasks(self, audit_id: str) -> list[CleanupTask]:
        statement = (
            select(CleanupTaskRecord)
            .where(CleanupTaskRecord.audit_id == audit_id)
            .order_by(CleanupTaskRecord.id.asc())
        )
        rows = list(self.session.exec(statement).all())
        tasks: list[CleanupTask] = []
        for row in rows:
            try:
                payload = json.loads(row.payload_json) if row.payload_json else {}
            except json.JSONDecodeError:
                payload = {}
            tasks.append(
                CleanupTask(
                    task_id=row.id,
                    title=row.title,
                    task_type=row.task_type,
                    requires_approval=row.requires_approval,
                    payload=payload,
                )
            )
        return tasks

    def get_findings_as_dicts(self, audit_id: str) -> list[dict]:
        statement = (
            select(FindingRecord)
            .where(FindingRecord.audit_id == audit_id)
            .order_by(FindingRecord.id.asc())
        )
        rows = list(self.session.exec(statement).all())
        out: list[dict] = []
        for row in rows:
            out.append(
                {
                    "finding_id": row.id,
                    "leak_type": row.finding_type,
                    "severity": row.severity,
                    "amount_impact": row.amount_impact,
                    "confidence": row.confidence,
                    "description": row.description,
                    "tx_ids": [item for item in row.tx_ids_csv.split(",") if item],
                    "suggested_action": row.suggested_action,
                }
            )
        return out

    def get_gst_findings_as_dicts(self, audit_id: str) -> list[dict]:
        statement = (
            select(GstRecord)
            .where(GstRecord.audit_id == audit_id)
            .order_by(GstRecord.id.asc())
        )
        rows = list(self.session.exec(statement).all())
        return [
            {
                "finding_id": row.id,
                "tx_id": row.tx_id,
                "has_gst_invoice": row.has_gst_invoice,
                "likely_itc_eligible": row.likely_itc_eligible,
                "issue": row.issue,
                "potential_itc_amount": row.potential_itc_amount,
            }
            for row in rows
        ]

    def mark_cleanup_tasks_approved(
        self,
        audit_id: str,
        task_ids: list[str],
        *,
        approved_at: datetime,
    ) -> None:
        if not task_ids:
            return
        statement = select(CleanupTaskRecord).where(
            CleanupTaskRecord.audit_id == audit_id,
            CleanupTaskRecord.id.in_(task_ids),
        )
        rows = list(self.session.exec(statement).all())
        for row in rows:
            row.status = "approved"
            row.approved_at = approved_at
            self.session.add(row)
        self.session.commit()

    def mark_cleanup_tasks_status(
        self,
        audit_id: str,
        task_ids: list[str],
        *,
        status: str,
    ) -> None:
        if not task_ids:
            return
        statement = select(CleanupTaskRecord).where(
            CleanupTaskRecord.audit_id == audit_id,
            CleanupTaskRecord.id.in_(task_ids),
        )
        rows = list(self.session.exec(statement).all())
        for row in rows:
            row.status = status
            self.session.add(row)
        self.session.commit()
