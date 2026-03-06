from __future__ import annotations

import json
from datetime import datetime, timezone

from sentinelfi.api.schemas import AuditRunRequest
from sentinelfi.core.config import Settings
from sentinelfi.domain.models import SourceType
from sentinelfi.repositories.db import init_db
from sentinelfi.repositories.job_repository import AuditJobRepository
from sentinelfi.repositories.models import AuditJobRecord
from sentinelfi.services.audit_job_service import AuditJobService


def test_audit_job_service_runs_inline_success(tmp_path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/test.db",
        enable_local_embeddings=False,
    )
    init_db(settings)

    service = AuditJobService(settings=settings, run_inline=True)
    payload = AuditRunRequest(
        source_type=SourceType.CSV,
        source_path="data/sample_transactions.csv",
        source_config={},
        generate_pdf=False,
        generate_markdown=False,
    )
    submitted = service.submit(payload)
    job = service.get(submitted["job_id"])

    assert job is not None
    assert job["status"] == "succeeded"
    assert isinstance(job.get("result"), dict)


def test_audit_job_service_runs_inline_failure(tmp_path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/test.db",
        enable_local_embeddings=False,
    )
    init_db(settings)

    service = AuditJobService(settings=settings, run_inline=True)
    payload = AuditRunRequest(
        source_type=SourceType.CSV,
        source_path="data/does-not-exist.csv",
        source_config={},
        generate_pdf=False,
        generate_markdown=False,
    )
    submitted = service.submit(payload)
    job = service.get(submitted["job_id"])

    assert job is not None
    assert job["status"] == "failed"
    assert job["error"] is not None


def test_audit_job_service_recovers_incomplete_jobs(tmp_path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/test.db",
        enable_local_embeddings=False,
    )
    init_db(settings)

    payload = AuditRunRequest(
        source_type=SourceType.CSV,
        source_path="data/sample_transactions.csv",
        source_config={},
        generate_pdf=False,
        generate_markdown=False,
    )
    now = datetime.now(timezone.utc)

    from sentinelfi.repositories.db import session_scope

    with session_scope(settings) as session:
        repo = AuditJobRepository(session)
        request_json = json.dumps(payload.model_dump(mode="json"))
        repo.create_job(
            AuditJobRecord(
                id="job-recover-queued",
                created_at=now,
                status="queued",
                request_json=request_json,
            )
        )
        repo.create_job(
            AuditJobRecord(
                id="job-recover-running",
                created_at=now,
                started_at=now,
                status="running",
                request_json=request_json,
            )
        )

    service = AuditJobService(settings=settings, run_inline=True)
    recovered = service.recover_incomplete_jobs()
    assert recovered == 2

    job_queued = service.get("job-recover-queued")
    job_running = service.get("job-recover-running")
    assert job_queued is not None and job_queued["status"] == "succeeded"
    assert job_running is not None and job_running["status"] == "succeeded"


def test_audit_job_service_idempotent_submit_reuses_existing_job(tmp_path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/test.db",
        enable_local_embeddings=False,
    )
    init_db(settings)

    service = AuditJobService(settings=settings, run_inline=False)
    payload = AuditRunRequest(
        source_type=SourceType.CSV,
        source_path="data/sample_transactions.csv",
        source_config={},
        idempotency_key="fixed-idempotency-key",
        generate_pdf=False,
        generate_markdown=False,
    )

    first = service.submit(payload)
    second = service.submit(payload)
    service.shutdown()

    assert first["job_id"] == second["job_id"]
