from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, select

from sentinelfi.repositories.models import AuditJobRecord


class AuditJobRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_job(self, job: AuditJobRecord) -> None:
        self.session.add(job)
        self.session.commit()

    def get_job(self, job_id: str) -> AuditJobRecord | None:
        return self.session.get(AuditJobRecord, job_id)

    def get_by_idempotency_key(self, key: str) -> AuditJobRecord | None:
        statement = select(AuditJobRecord).where(AuditJobRecord.idempotency_key == key).limit(1)
        return self.session.exec(statement).first()

    def list_jobs(self, limit: int = 50) -> list[AuditJobRecord]:
        statement = select(AuditJobRecord).order_by(AuditJobRecord.created_at.desc()).limit(limit)
        return list(self.session.exec(statement).all())

    def list_incomplete_jobs(self) -> list[AuditJobRecord]:
        statement = (
            select(AuditJobRecord)
            .where(AuditJobRecord.status.in_(["queued", "running"]))
            .order_by(AuditJobRecord.created_at.asc())
        )
        return list(self.session.exec(statement).all())

    def requeue_jobs(self, job_ids: list[str], error_message: str | None = None) -> list[AuditJobRecord]:
        if not job_ids:
            return []

        statement = select(AuditJobRecord).where(AuditJobRecord.id.in_(job_ids))
        rows = list(self.session.exec(statement).all())
        for row in rows:
            row.status = "queued"
            row.started_at = None
            row.finished_at = None
            if error_message:
                row.error = error_message
            self.session.add(row)
        self.session.commit()
        return rows

    def mark_running(self, job_id: str, started_at: datetime) -> AuditJobRecord | None:
        row = self.get_job(job_id)
        if row is None:
            return None
        row.status = "running"
        row.started_at = started_at
        self.session.add(row)
        self.session.commit()
        return row

    def mark_success(self, job_id: str, finished_at: datetime, result_json: str) -> AuditJobRecord | None:
        row = self.get_job(job_id)
        if row is None:
            return None
        row.status = "succeeded"
        row.finished_at = finished_at
        row.result_json = result_json
        self.session.add(row)
        self.session.commit()
        return row

    def mark_failed(self, job_id: str, finished_at: datetime, error: str) -> AuditJobRecord | None:
        row = self.get_job(job_id)
        if row is None:
            return None
        row.status = "failed"
        row.finished_at = finished_at
        row.error = error
        self.session.add(row)
        self.session.commit()
        return row

    def reset_for_retry(
        self,
        job_id: str,
        *,
        request_json: str,
        requeued_at: datetime,
    ) -> AuditJobRecord | None:
        row = self.get_job(job_id)
        if row is None:
            return None
        row.status = "queued"
        row.created_at = requeued_at
        row.started_at = None
        row.finished_at = None
        row.error = None
        row.result_json = "{}"
        row.request_json = request_json
        self.session.add(row)
        self.session.commit()
        return row
