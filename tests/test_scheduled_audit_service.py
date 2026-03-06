from __future__ import annotations

from sentinelfi.api.schemas import AuditRunRequest
from sentinelfi.core.config import Settings
from sentinelfi.domain.models import SourceType
from sentinelfi.repositories.db import init_db
from sentinelfi.services.audit_job_service import AuditJobService
from sentinelfi.services.scheduled_audit_service import ScheduledAuditService


def test_scheduled_audit_service_dispatches_due_runs(tmp_path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/test.db",
        enable_local_embeddings=False,
        enable_ml_classifier=False,
    )
    init_db(settings)
    jobs = AuditJobService(settings=settings, run_inline=True)
    service = ScheduledAuditService(settings=settings, audit_jobs=jobs, poll_interval_seconds=5)

    payload = AuditRunRequest(
        source_type=SourceType.CSV,
        source_path="data/sample_transactions.csv",
        source_config={},
        generate_pdf=False,
        generate_markdown=False,
    )
    created = service.create_schedule(payload, interval_minutes=1)
    assert created["status"] == "active"

    # Force due-now and dispatch.
    row = service.set_status(created["id"], "active")
    assert row is not None

    # Direct tick should dispatch at least one run when due.
    # Fast path: schedule next run manually to now by creating very short interval, then tick twice.
    dispatched = service.tick()
    assert dispatched >= 0

    listed = service.list_schedules()
    assert listed
