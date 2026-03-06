from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timedelta, timezone

from sentinelfi.api.schemas import AuditRunRequest
from sentinelfi.core.config import Settings
from sentinelfi.core.logging import get_logger
from sentinelfi.repositories.db import session_scope
from sentinelfi.repositories.models import ScheduledAuditRecord
from sentinelfi.repositories.scheduled_audit_repository import ScheduledAuditRepository
from sentinelfi.services.audit_job_service import AuditJobService

log = get_logger(__name__)


class ScheduledAuditService:
    def __init__(
        self,
        settings: Settings,
        audit_jobs: AuditJobService,
        poll_interval_seconds: int = 30,
    ):
        self.settings = settings
        self.audit_jobs = audit_jobs
        self.poll_interval_seconds = max(5, poll_interval_seconds)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def create_schedule(self, payload: AuditRunRequest, interval_minutes: int) -> dict:
        now = datetime.now(timezone.utc)
        row = ScheduledAuditRecord(
            id=f"sch-{uuid.uuid4().hex[:12]}",
            created_at=now,
            updated_at=now,
            status="active",
            interval_minutes=max(1, int(interval_minutes)),
            next_run_at=now + timedelta(minutes=max(1, int(interval_minutes))),
            payload_json=json.dumps(payload.model_dump(mode="json")),
        )
        with session_scope(self.settings) as session:
            saved = ScheduledAuditRepository(session).create(row)
            return self._to_dict(saved)

    def list_schedules(self, limit: int = 100) -> list[dict]:
        with session_scope(self.settings) as session:
            rows = ScheduledAuditRepository(session).list(limit=limit)
            return [self._to_dict(row) for row in rows]

    def set_status(self, schedule_id: str, status: str) -> dict | None:
        now = datetime.now(timezone.utc)
        with session_scope(self.settings) as session:
            row = ScheduledAuditRepository(session).update_status(
                schedule_id,
                status=status,
                updated_at=now,
            )
            return self._to_dict(row) if row else None

    def tick(self) -> int:
        now = datetime.now(timezone.utc)
        dispatched = 0
        with session_scope(self.settings) as session:
            repo = ScheduledAuditRepository(session)
            due = repo.list_due(now, limit=25)

        for row in due:
            job_id: str | None = None
            error: str | None = None
            try:
                payload = AuditRunRequest.model_validate_json(row.payload_json)
                submit_result = self.audit_jobs.submit(payload)
                job_id = str(submit_result.get("job_id"))
                dispatched += 1
            except Exception as exc:  # noqa: BLE001
                error = str(exc)
                log.warning("scheduled_audit_dispatch_failed", schedule_id=row.id, error=error)

            next_run_at = now + timedelta(minutes=max(1, int(row.interval_minutes)))
            with session_scope(self.settings) as session:
                ScheduledAuditRepository(session).mark_dispatched(
                    row.id,
                    now=now,
                    next_run_at=next_run_at,
                    job_id=job_id,
                    error=error,
                )
        return dispatched

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001
                log.warning("scheduled_audit_tick_failed", error=str(exc))
            self._stop_event.wait(self.poll_interval_seconds)

    @staticmethod
    def _to_dict(row: ScheduledAuditRecord) -> dict:
        return {
            "id": row.id,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "status": row.status,
            "interval_minutes": row.interval_minutes,
            "next_run_at": row.next_run_at,
            "last_run_at": row.last_run_at,
            "last_job_id": row.last_job_id,
            "error": row.error,
        }
