from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, select

from sentinelfi.repositories.models import ScheduledAuditRecord


class ScheduledAuditRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, row: ScheduledAuditRecord) -> ScheduledAuditRecord:
        self.session.add(row)
        self.session.commit()
        return row

    def list(self, limit: int = 100) -> list[ScheduledAuditRecord]:
        statement = (
            select(ScheduledAuditRecord)
            .order_by(ScheduledAuditRecord.created_at.desc())
            .limit(limit)
        )
        return list(self.session.exec(statement).all())

    def get(self, schedule_id: str) -> ScheduledAuditRecord | None:
        return self.session.get(ScheduledAuditRecord, schedule_id)

    def update_status(self, schedule_id: str, *, status: str, updated_at: datetime) -> ScheduledAuditRecord | None:
        row = self.get(schedule_id)
        if row is None:
            return None
        row.status = status
        row.updated_at = updated_at
        self.session.add(row)
        self.session.commit()
        return row

    def list_due(self, now: datetime, limit: int = 20) -> list[ScheduledAuditRecord]:
        statement = (
            select(ScheduledAuditRecord)
            .where(
                ScheduledAuditRecord.status == "active",
                ScheduledAuditRecord.next_run_at <= now,
            )
            .order_by(ScheduledAuditRecord.next_run_at.asc())
            .limit(limit)
        )
        return list(self.session.exec(statement).all())

    def mark_dispatched(
        self,
        schedule_id: str,
        *,
        now: datetime,
        next_run_at: datetime,
        job_id: str | None,
        error: str | None = None,
    ) -> ScheduledAuditRecord | None:
        row = self.get(schedule_id)
        if row is None:
            return None
        row.last_run_at = now
        row.next_run_at = next_run_at
        row.last_job_id = job_id
        row.error = error
        row.updated_at = now
        self.session.add(row)
        self.session.commit()
        return row
