from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable

from sentinelfi.api.schemas import AuditRunRequest
from sentinelfi.core.config import Settings
from sentinelfi.core.logging import get_logger
from sentinelfi.repositories.db import session_scope
from sentinelfi.repositories.job_repository import AuditJobRepository
from sentinelfi.repositories.models import AuditJobRecord
from sentinelfi.services.audit_execution import AuditExecutionService
from sentinelfi.services.idempotency import build_audit_idempotency_key
from sentinelfi.services.notification_service import NotificationService

log = get_logger(__name__)


class AuditJobService:
    def __init__(
        self,
        settings: Settings,
        max_workers: int = 2,
        run_inline: bool = False,
        execute_audit: Callable[[AuditRunRequest], tuple[Any, list[Any]]] | None = None,
    ):
        self.settings = settings
        self.run_inline = run_inline
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        if execute_audit is None:
            execution_service = AuditExecutionService(settings)
            self.execute_audit = execution_service.execute
        else:
            self.execute_audit = execute_audit
        self.notifier = NotificationService(settings)

    def submit(self, payload: AuditRunRequest) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        request_json = json.dumps(payload.model_dump(mode="json"))
        idempotency_key = build_audit_idempotency_key(payload)
        should_schedule = False

        with session_scope(self.settings) as session:
            repo = AuditJobRepository(session)
            existing = repo.get_by_idempotency_key(idempotency_key)
            if existing is None:
                job_id = f"job-{uuid.uuid4().hex[:12]}"
                repo.create_job(
                    AuditJobRecord(
                        id=job_id,
                        created_at=now,
                        status="queued",
                        idempotency_key=idempotency_key,
                        request_json=request_json,
                    )
                )
                status = "queued"
                created_at = now
                should_schedule = True
            elif existing.status == "failed":
                repo.reset_for_retry(existing.id, request_json=request_json, requeued_at=now)
                job_id = existing.id
                status = "queued"
                created_at = now
                should_schedule = True
            else:
                job_id = existing.id
                status = existing.status
                created_at = existing.created_at

        if should_schedule:
            if self.run_inline:
                self._run_job(job_id)
            else:
                self.executor.submit(self._run_job, job_id)

        return {"job_id": job_id, "status": status, "created_at": created_at}

    def get(self, job_id: str) -> dict[str, Any] | None:
        with session_scope(self.settings) as session:
            repo = AuditJobRepository(session)
            row = repo.get_job(job_id)
            if row is None:
                return None

            result: dict[str, Any] | None = None
            if row.result_json:
                try:
                    parsed = json.loads(row.result_json)
                    if isinstance(parsed, dict) and parsed:
                        result = parsed
                except json.JSONDecodeError:
                    result = None

            return {
                "job_id": row.id,
                "status": row.status,
                "created_at": row.created_at,
                "started_at": row.started_at,
                "finished_at": row.finished_at,
                "error": row.error,
                "result": result,
            }

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        with session_scope(self.settings) as session:
            rows = AuditJobRepository(session).list_jobs(limit=limit)

        return [
            {
                "job_id": row.id,
                "status": row.status,
                "created_at": row.created_at,
                "started_at": row.started_at,
                "finished_at": row.finished_at,
                "error": row.error,
            }
            for row in rows
        ]

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)

    def recover_incomplete_jobs(self) -> int:
        with session_scope(self.settings) as session:
            repo = AuditJobRepository(session)
            rows = repo.list_incomplete_jobs()
            if not rows:
                return 0
            requeued = repo.requeue_jobs(
                [row.id for row in rows],
                error_message="recovered_after_process_restart",
            )
            requeued_ids = [row.id for row in requeued]

        for job_id in requeued_ids:
            if self.run_inline:
                self._run_job(job_id)
            else:
                self.executor.submit(self._run_job, job_id)

        log.info("audit_jobs_recovered", count=len(requeued_ids))
        return len(requeued_ids)

    def _run_job(self, job_id: str) -> None:
        started = datetime.now(timezone.utc)
        payload: AuditRunRequest | None = None

        with session_scope(self.settings) as session:
            repo = AuditJobRepository(session)
            row = repo.mark_running(job_id, started_at=started)
            if row is None:
                return
            payload = AuditRunRequest.model_validate_json(row.request_json)

        if payload is None:
            return

        try:
            response, _classified = self.execute_audit(payload)
            result_json = json.dumps(response.model_dump(mode="json"))

            with session_scope(self.settings) as session:
                AuditJobRepository(session).mark_success(
                    job_id=job_id,
                    finished_at=datetime.now(timezone.utc),
                    result_json=result_json,
                )
            self.notifier.notify_audit(response.output)
            log.info("audit_job_succeeded", job_id=job_id)
        except Exception as exc:  # noqa: BLE001
            with session_scope(self.settings) as session:
                AuditJobRepository(session).mark_failed(
                    job_id=job_id,
                    finished_at=datetime.now(timezone.utc),
                    error=str(exc),
                )
            log.exception("audit_job_failed", job_id=job_id, error=str(exc))
