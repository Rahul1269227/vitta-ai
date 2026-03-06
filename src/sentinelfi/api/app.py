from __future__ import annotations

import json
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import TypeAdapter
from sqlmodel import select
from starlette.concurrency import run_in_threadpool

from sentinelfi.agents.ml_classifier import MLTransactionClassifier
from sentinelfi.api.schemas import (
    ActiveLearningStatusResponse,
    AdminSettingsResponse,
    AdminSettingsUpdateRequest,
    AuditJobListItem,
    AuditJobStatusResponse,
    AuditJobSubmitResponse,
    AuditRunRequest,
    AuditRunResponse,
    AuditRunSummary,
    AuditScheduleCreateRequest,
    AuditScheduleResponse,
    CleanupRunRequest,
    CleanupRunResponse,
    ExportRequest,
    FeedbackIngestRequest,
    FeedbackIngestResponse,
    MerchantMatchResponse,
    MerchantResolveRequest,
    RetrainResponse,
    RuntimeStatsResponse,
)
from sentinelfi.core.config import get_settings
from sentinelfi.core.logging import configure_logging, get_logger
from sentinelfi.repositories.audit_repository import AuditRepository
from sentinelfi.repositories.db import init_db, session_scope
from sentinelfi.repositories.job_repository import AuditJobRepository
from sentinelfi.repositories.models import AuditJobRecord
from sentinelfi.repositories.settings_repository import SettingsRepository
from sentinelfi.services.active_learning_service import ActiveLearningService, FeedbackCorrection
from sentinelfi.services.api_security import (
    build_rate_limiter,
    build_upload_path,
    is_api_key_allowed,
    parse_api_keys,
    persist_upload_with_size_limit,
)
from sentinelfi.services.audit_execution import AuditExecutionService
from sentinelfi.services.audit_job_service import AuditJobService
from sentinelfi.services.cleanup_orchestrator import CleanupOrchestrator
from sentinelfi.services.export_service import ExportService
from sentinelfi.services.idempotency import build_audit_idempotency_key
from sentinelfi.services.merchant_resolver import MerchantResolver
from sentinelfi.services.ml_drift_monitor import MLDriftMonitor
from sentinelfi.services.notification_service import NotificationService
from sentinelfi.services.runtime_stats import RuntimeStatsTracker
from sentinelfi.services.scheduled_audit_service import ScheduledAuditService
from sentinelfi.services.telemetry import setup_opentelemetry

try:
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

    _PROMETHEUS_AVAILABLE = True
except Exception:  # noqa: BLE001
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4"
    Counter = None
    Histogram = None
    generate_latest = None
    _PROMETHEUS_AVAILABLE = False

settings = get_settings()
configure_logging(settings.log_level)
log = get_logger(__name__)
runtime_stats = RuntimeStatsTracker(window=500)
allowed_api_keys = parse_api_keys(settings.api_keys_csv)
admin_api_keys = parse_api_keys(settings.admin_api_keys_csv)
rate_limiter = build_rate_limiter(
    limit=settings.rate_limit_per_minute,
    window_seconds=60,
    backend=settings.rate_limit_backend,
    redis_url=settings.redis_url,
)
drift_monitor = MLDriftMonitor(
    model_path=settings.ml_model_path,
    window=settings.ml_drift_window,
    z_warning=settings.ml_drift_z_warning,
    z_critical=settings.ml_drift_z_critical,
    psi_warning=settings.ml_drift_psi_warning,
    psi_critical=settings.ml_drift_psi_critical,
    business_rate_warning=settings.ml_business_rate_warning,
    business_rate_critical=settings.ml_business_rate_critical,
)
active_learning = ActiveLearningService(settings, on_retrain_success=drift_monitor.refresh_baseline)
audit_execution = AuditExecutionService(settings)
notifier = NotificationService(settings)
merchant_resolver = MerchantResolver(Path("data/gazetteer/merchant_aliases.csv"))
export_service = ExportService()
audit_jobs = AuditJobService(
    settings=settings,
    max_workers=settings.audit_job_workers,
    execute_audit=audit_execution.execute,
)
scheduled_audits = ScheduledAuditService(
    settings=settings,
    audit_jobs=audit_jobs,
    poll_interval_seconds=30,
)
_METRICS_ENABLED = settings.prometheus_enabled and _PROMETHEUS_AVAILABLE
if _METRICS_ENABLED:
    HTTP_REQUESTS_TOTAL = Counter(
        "sentinelfi_http_requests_total",
        "HTTP requests served",
        ["method", "path", "status"],
    )
    HTTP_REQUEST_DURATION_SECONDS = Histogram(
        "sentinelfi_http_request_duration_seconds",
        "HTTP request duration in seconds",
        ["method", "path"],
    )
else:
    HTTP_REQUESTS_TOTAL = None
    HTTP_REQUEST_DURATION_SECONDS = None
otel_enabled_runtime = False
MUTABLE_RUNTIME_SETTINGS = {
    "llm_model",
    "llm_batch_size",
    "fast_mode_enabled",
    "slm_escalation_threshold",
    "review_threshold_default",
    "review_threshold_high_risk",
    "ml_min_confidence",
    "enable_api_key_auth",
    "api_keys_csv",
    "admin_api_keys_csv",
    "rate_limit_per_minute",
    "rate_limit_backend",
    "redis_url",
    "cors_allow_origins_csv",
    "upload_max_bytes",
    "local_ingestion_roots_csv",
    "enable_pdf_ocr_fallback",
    "pdf_ocr_lang",
    "prometheus_enabled",
    "otel_enabled",
    "otel_service_name",
    "otel_exporter_otlp_endpoint",
    "cleanup_live_mode",
    "cleanup_webhook_timeout_seconds",
    "cleanup_webhook_max_attempts",
    "cleanup_webhook_retry_base_seconds",
    "cleanup_webhook_retry_max_seconds",
    "cleanup_webhook_hmac_secret",
    "cleanup_ledger_webhook_url",
    "cleanup_ledger_webhook_hmac_secret",
    "cleanup_invoice_webhook_url",
    "cleanup_invoice_webhook_hmac_secret",
    "cleanup_gst_webhook_url",
    "cleanup_gst_webhook_hmac_secret",
    "cleanup_email_smtp_host",
    "cleanup_email_smtp_port",
    "cleanup_email_smtp_username",
    "cleanup_email_smtp_password",
    "cleanup_email_smtp_use_tls",
    "cleanup_email_smtp_use_ssl",
    "cleanup_email_from",
    "cleanup_email_to_csv",
    "leak_duplicate_min_amount",
    "leak_duplicate_amount_tolerance",
    "leak_zombie_min_amount",
    "leak_price_hike_min_amount",
    "leak_price_hike_jump_threshold",
    "leak_free_trial_lookback_days",
    "leak_free_trial_low_amount_abs",
    "leak_free_trial_low_amount_ratio",
    "alert_webhook_url",
    "alert_webhook_timeout_seconds",
    "alert_webhook_max_attempts",
    "alert_webhook_retry_base_seconds",
    "alert_webhook_retry_max_seconds",
    "alert_webhook_hmac_secret",
}


def _refresh_security_runtime() -> None:
    global allowed_api_keys, admin_api_keys, rate_limiter
    allowed_api_keys = parse_api_keys(settings.api_keys_csv)
    admin_api_keys = parse_api_keys(settings.admin_api_keys_csv)
    rate_limiter = build_rate_limiter(
        limit=settings.rate_limit_per_minute,
        window_seconds=60,
        backend=settings.rate_limit_backend,
        redis_url=settings.redis_url,
    )


def _refresh_runtime_services() -> None:
    global audit_execution, notifier, audit_jobs
    audit_execution = AuditExecutionService(settings)
    notifier = NotificationService(settings)
    audit_jobs.execute_audit = audit_execution.execute
    audit_jobs.notifier = notifier


def _apply_runtime_setting(key: str, value: object) -> object:
    if key not in MUTABLE_RUNTIME_SETTINGS:
        raise ValueError(f"unsupported_setting:{key}")
    field = settings.__class__.model_fields.get(key)
    if field is None:
        raise ValueError(f"unknown_setting:{key}")
    annotation = field.annotation
    adapter = TypeAdapter(annotation)
    coerced = adapter.validate_python(value)
    setattr(settings, key, coerced)
    return coerced


def _load_runtime_settings_overrides() -> int:
    loaded = 0
    with session_scope(settings) as session:
        repo = SettingsRepository(session)
        rows = repo.list_settings()
    for row in rows:
        try:
            decoded = json.loads(row.value_json)
            _apply_runtime_setting(row.key, decoded)
            loaded += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("runtime_setting_override_invalid", key=row.key, error=str(exc))
    _refresh_security_runtime()
    _refresh_runtime_services()
    return loaded


def _runtime_settings_payload() -> dict[str, object]:
    payload: dict[str, object] = {}
    for key in sorted(MUTABLE_RUNTIME_SETTINGS):
        payload[key] = getattr(settings, key)
    return payload


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.env.lower() != "dev" and settings.pii_hash_salt in {
        "replace-me-in-prod",
        "replace-this-in-prod",
    }:
        raise RuntimeError("PII_HASH_SALT must be overridden outside dev environment")

    init_db(settings)
    loaded_overrides = _load_runtime_settings_overrides()
    drift_monitor.refresh_baseline()
    scheduled_audits.start()
    recovered_jobs = audit_jobs.recover_incomplete_jobs()
    recovered_training_runs = active_learning.recover_incomplete_training_runs()
    log.info(
        "startup_complete",
        api_key_auth_enabled=settings.enable_api_key_auth,
        configured_api_keys=len(allowed_api_keys),
        recovered_jobs=recovered_jobs,
        recovered_training_runs=recovered_training_runs,
        loaded_runtime_overrides=loaded_overrides,
        rate_limit_backend=settings.rate_limit_backend,
        prometheus_enabled=_METRICS_ENABLED,
        otel_enabled=otel_enabled_runtime,
    )
    yield
    active_learning.shutdown()
    scheduled_audits.stop()
    audit_jobs.shutdown()
    log.info("shutdown_complete")


app = FastAPI(title="Sentinel-Fi API", version="0.1.0", lifespan=lifespan)
otel_enabled_runtime = setup_opentelemetry(app, settings)
web_root = Path(__file__).resolve().parents[1] / "web"
templates = Jinja2Templates(directory=str(web_root / "templates"))
app.mount("/assets", StaticFiles(directory=str(web_root / "static")), name="assets")

cors_origins = [item.strip() for item in settings.cors_allow_origins_csv.split(",") if item.strip()]
if cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def _normalize_metrics_path(path: str) -> str:
    if path.startswith("/v1/audit/jobs/"):
        return "/v1/audit/jobs/{job_id}"
    return path


@app.middleware("http")
async def collect_http_metrics(request: Request, call_next):
    if not _METRICS_ENABLED:
        return await call_next(request)

    started = time.perf_counter()
    status = 500
    path_label = _normalize_metrics_path(request.url.path)
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        elapsed = max(0.0, time.perf_counter() - started)
        assert HTTP_REQUESTS_TOTAL is not None
        assert HTTP_REQUEST_DURATION_SECONDS is not None
        HTTP_REQUESTS_TOTAL.labels(
            method=request.method,
            path=path_label,
            status=str(status),
        ).inc()
        HTTP_REQUEST_DURATION_SECONDS.labels(
            method=request.method,
            path=path_label,
        ).observe(elapsed)


@app.middleware("http")
async def enforce_api_key(request: Request, call_next):
    request_key = ""
    if request.url.path.startswith("/v1/"):
        request_key = request.headers.get("x-api-key", "")
        client_ip = request.client.host if request.client else "unknown"
        rate_key = request_key if request_key else client_ip
        allowed, retry_after = rate_limiter.allow(rate_key)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={"Retry-After": str(retry_after)},
            )

    if settings.enable_api_key_auth and request.url.path.startswith("/v1/"):
        if not allowed_api_keys:
            return JSONResponse(
                status_code=500,
                content={"detail": "API key auth enabled but API_KEYS_CSV is empty"},
            )

        if not is_api_key_allowed(request_key, allowed_api_keys):
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

    if request.url.path.startswith("/v1/admin/"):
        if not admin_api_keys:
            return JSONResponse(
                status_code=500,
                content={"detail": "Admin API access not configured (ADMIN_API_KEYS_CSV)"},
            )
        if not is_api_key_allowed(request_key, admin_api_keys):
            return JSONResponse(status_code=403, content={"detail": "Forbidden"})

    return await call_next(request)


@app.middleware("http")
async def apply_ui_security_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/assets/"):
        response.headers.setdefault(
            "Content-Security-Policy",
            (
                "default-src 'self'; "
                "script-src 'self'; "
                "style-src 'self' https://fonts.googleapis.com; "
                "img-src 'self' data:; "
                "font-src 'self' https://fonts.gstatic.com; "
                "connect-src 'self'; "
                "base-uri 'self'; "
                "form-action 'self'"
            ),
        )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response


@app.get("/healthz")
async def healthz() -> dict[str, object]:
    return {"status": "ok", "service": settings.app_name}


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> Response:
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "app_name": settings.app_name,
            "api_base": "/v1",
        },
    )


@app.get("/metrics")
async def metrics() -> Response:
    if not settings.prometheus_enabled:
        raise HTTPException(status_code=404, detail="Prometheus metrics disabled")
    if not _PROMETHEUS_AVAILABLE or generate_latest is None:
        raise HTTPException(status_code=503, detail="prometheus_client not available")
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/readyz")
async def readyz() -> JSONResponse:
    checks = {
        "database": False,
        "ml_model": False,
        "taxonomy_files": False,
        "disk_space": False,
    }

    def _db_ready() -> bool:
        try:
            with session_scope(settings) as session:
                session.exec(select(1)).first()
            return True
        except Exception:  # noqa: BLE001
            return False

    def _ml_ready() -> bool:
        if not settings.enable_ml_classifier:
            return True
        try:
            return MLTransactionClassifier(
                model_path=settings.ml_model_path,
                enabled=True,
            ).available
        except Exception:  # noqa: BLE001
            return False

    def _taxonomy_ready() -> bool:
        base = Path(settings.taxonomy_base_path)
        overrides = Path(settings.taxonomy_overrides_path)
        return base.exists() and overrides.exists()

    def _disk_ready() -> bool:
        usage = shutil.disk_usage(Path(".").resolve())
        free_mb = usage.free / (1024 * 1024)
        return free_mb >= settings.min_free_disk_mb

    checks["database"] = await run_in_threadpool(_db_ready)
    checks["ml_model"] = await run_in_threadpool(_ml_ready)
    checks["taxonomy_files"] = await run_in_threadpool(_taxonomy_ready)
    checks["disk_space"] = await run_in_threadpool(_disk_ready)

    ready = all(checks.values())
    status_code = 200 if ready else 503
    return JSONResponse(
        status_code=status_code,
        content={"status": "ready" if ready else "not_ready", "checks": checks},
    )


@app.post("/v1/audit/run", response_model=AuditRunResponse)
async def run_audit_sync(payload: AuditRunRequest) -> AuditRunResponse:
    idempotency_key = build_audit_idempotency_key(payload)

    def _lookup_existing_run() -> AuditJobRecord | None:
        with session_scope(settings) as session:
            repo = AuditJobRepository(session)
            return repo.get_by_idempotency_key(idempotency_key)

    existing = await run_in_threadpool(_lookup_existing_run)
    if existing is not None:
        if existing.status == "succeeded":
            try:
                parsed = json.loads(existing.result_json)
                return AuditRunResponse.model_validate(parsed)
            except Exception as exc:  # noqa: BLE001
                log.warning("idempotent_cached_result_invalid", job_id=existing.id, error=str(exc))
        if existing.status in {"queued", "running"}:
            raise HTTPException(
                status_code=409,
                detail=f"Audit already in progress for idempotency key; job_id={existing.id}",
            )

    job_id = existing.id if existing is not None else f"job-sync-{uuid.uuid4().hex[:12]}"
    request_json = json.dumps(payload.model_dump(mode="json"))

    def _mark_running() -> None:
        now = datetime.now(timezone.utc)
        with session_scope(settings) as session:
            repo = AuditJobRepository(session)
            row = repo.get_job(job_id)
            if row is None:
                repo.create_job(
                    AuditJobRecord(
                        id=job_id,
                        created_at=now,
                        started_at=now,
                        status="running",
                        idempotency_key=idempotency_key,
                        request_json=request_json,
                    )
                )
                return
            row.request_json = request_json
            row.idempotency_key = idempotency_key
            row.status = "running"
            row.started_at = now
            row.finished_at = None
            row.error = None
            row.result_json = "{}"
            session.add(row)
            session.commit()

    await run_in_threadpool(_mark_running)
    started_at = time.perf_counter()

    try:
        response, classified = await run_in_threadpool(audit_execution.execute, payload)
    except Exception as exc:  # noqa: BLE001
        error_message = str(exc)

        def _mark_failed() -> None:
            with session_scope(settings) as session:
                AuditJobRepository(session).mark_failed(
                    job_id=job_id,
                    finished_at=datetime.now(timezone.utc),
                    error=error_message,
                )

        await run_in_threadpool(_mark_failed)
        log.exception("audit_run_failed", error=error_message)
        raise HTTPException(status_code=400, detail=error_message) from exc

    def _mark_success() -> None:
        with session_scope(settings) as session:
            AuditJobRepository(session).mark_success(
                job_id=job_id,
                finished_at=datetime.now(timezone.utc),
                result_json=json.dumps(response.model_dump(mode="json")),
            )

    await run_in_threadpool(_mark_success)

    runtime_stats.record(
        latency_ms=(time.perf_counter() - started_at) * 1000.0,
        output=response.output,
    )
    drift_monitor.record(classified)
    await run_in_threadpool(notifier.notify_audit, response.output)

    return response


@app.post("/v1/audit/submit", response_model=AuditJobSubmitResponse)
async def submit_audit_job(payload: AuditRunRequest) -> AuditJobSubmitResponse:
    result = await run_in_threadpool(audit_jobs.submit, payload)
    return AuditJobSubmitResponse(**result)


@app.get("/v1/audit/jobs/{job_id}", response_model=AuditJobStatusResponse)
async def get_audit_job(job_id: str) -> AuditJobStatusResponse:
    result = await run_in_threadpool(audit_jobs.get, job_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    if isinstance(result.get("result"), dict):
        result["result"] = AuditRunResponse.model_validate(result["result"])
    return AuditJobStatusResponse(**result)


@app.get("/v1/audit/jobs", response_model=list[AuditJobListItem])
async def list_audit_jobs(limit: int = 50) -> list[AuditJobListItem]:
    rows = await run_in_threadpool(audit_jobs.list, limit)
    return [AuditJobListItem(**row) for row in rows]


@app.post("/v1/audit/schedules", response_model=AuditScheduleResponse)
async def create_audit_schedule(payload: AuditScheduleCreateRequest) -> AuditScheduleResponse:
    row = await run_in_threadpool(
        scheduled_audits.create_schedule,
        payload.payload,
        payload.interval_minutes,
    )
    return AuditScheduleResponse(**row)


@app.get("/v1/audit/schedules", response_model=list[AuditScheduleResponse])
async def list_audit_schedules(limit: int = 100) -> list[AuditScheduleResponse]:
    rows = await run_in_threadpool(scheduled_audits.list_schedules, limit)
    return [AuditScheduleResponse(**row) for row in rows]


@app.post("/v1/audit/schedules/{schedule_id}/{action}", response_model=AuditScheduleResponse)
async def set_audit_schedule_status(schedule_id: str, action: str) -> AuditScheduleResponse:
    status_map = {"pause": "paused", "resume": "active"}
    status = status_map.get(action)
    if status is None:
        raise HTTPException(status_code=400, detail="action must be pause or resume")
    row = await run_in_threadpool(scheduled_audits.set_status, schedule_id, status)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Schedule not found: {schedule_id}")
    return AuditScheduleResponse(**row)


@app.post("/v1/cleanup/run", response_model=CleanupRunResponse)
async def run_cleanup(payload: CleanupRunRequest) -> CleanupRunResponse:
    def _load_cleanup_tasks():
        with session_scope(settings) as session:
            return AuditRepository(session).get_cleanup_tasks(payload.audit_id)

    tasks = await run_in_threadpool(_load_cleanup_tasks)
    if not tasks:
        raise HTTPException(status_code=404, detail=f"No cleanup tasks found for audit_id={payload.audit_id}")

    task_ids = {task.task_id for task in tasks}
    unknown_ids = sorted(set(payload.approved_task_ids) - task_ids)
    if unknown_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown approved_task_ids for audit {payload.audit_id}: {', '.join(unknown_ids)}",
        )

    result = await run_in_threadpool(
        CleanupOrchestrator(settings=settings).run,
        tasks,
        payload.approved_task_ids,
    )

    def _persist_cleanup_result() -> None:
        with session_scope(settings) as session:
            repo = AuditRepository(session)
            now = datetime.now(timezone.utc)
            repo.mark_cleanup_tasks_approved(
                payload.audit_id,
                payload.approved_task_ids,
                approved_at=now,
            )

            executed_items = result.get("executed", [])
            executed_ids = [
                item["task_id"]
                for item in executed_items
                if item.get("status") in {"executed", "already_executed"}
            ]
            failed_ids = [
                item["task_id"]
                for item in executed_items
                if item.get("status") == "failed"
            ]
            skipped_ids = result.get("skipped", [])

            repo.mark_cleanup_tasks_status(payload.audit_id, executed_ids, status="executed")
            repo.mark_cleanup_tasks_status(payload.audit_id, skipped_ids, status="skipped_unapproved")
            repo.mark_cleanup_tasks_status(payload.audit_id, failed_ids, status="failed")

    await run_in_threadpool(_persist_cleanup_result)
    return CleanupRunResponse(executed=result.get("executed", []), skipped=result.get("skipped", []))


@app.get("/v1/audits", response_model=list[AuditRunSummary])
async def list_audits(limit: int = 20) -> list[AuditRunSummary]:
    def _fetch_rows():
        with session_scope(settings) as session:
            return AuditRepository(session).get_audit_runs(limit=limit)

    rows = await run_in_threadpool(_fetch_rows)

    return [
        AuditRunSummary(
            id=r.id,
            created_at=r.created_at,
            source_type=r.source_type,
            total_transactions=r.total_transactions,
            leak_count=r.leak_count,
            total_leak_amount=r.total_leak_amount,
            missed_itc=r.missed_itc,
            risk_score=r.risk_score,
        )
        for r in rows
    ]


@app.get("/v1/audits/{audit_id}/snapshot")
async def get_audit_snapshot(audit_id: str) -> JSONResponse:
    def _fetch_snapshot() -> dict | None:
        with session_scope(settings) as session:
            repo = AuditRepository(session)
            run = repo.get_audit_run(audit_id)
            if run is None:
                return None
            findings = repo.get_findings_as_dicts(audit_id)
            gst_findings = repo.get_gst_findings_as_dicts(audit_id)
            cleanup_tasks = [task.model_dump(mode="json") for task in repo.get_cleanup_tasks(audit_id)]
            classified = repo.get_classified_transactions_as_dicts(audit_id)
            decisions = [
                {
                    "tx_id": row["id"],
                    "route": row["method"],
                    "final_classifier": row["method"],
                    "category": row["category"],
                    "confidence": row["confidence"],
                    "requires_review": bool(row.get("requires_review")),
                    "decision_path": [],
                    "votes": [],
                }
                for row in classified
            ]
            return {
                "output": {
                    "summary": {
                        "audit_id": run.id,
                        "created_at": run.created_at,
                        "total_transactions": run.total_transactions,
                        "leak_count": run.leak_count,
                        "total_leak_amount": run.total_leak_amount,
                        "missed_itc": run.missed_itc,
                        "risk_score": run.risk_score,
                        "review_count": sum(1 for row in classified if row.get("requires_review")),
                        "avg_classification_confidence": (
                            sum(float(row.get("confidence", 0.0)) for row in classified) / len(classified)
                            if classified
                            else 0.0
                        ),
                    },
                    "findings": findings,
                    "gst_findings": gst_findings,
                    "cleanup_tasks": cleanup_tasks,
                    "classification_decisions": decisions,
                },
                "markdown_report_path": None,
                "pdf_report_path": None,
            }

    snapshot = await run_in_threadpool(_fetch_snapshot)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Audit not found: {audit_id}")
    return JSONResponse(snapshot)


@app.get("/v1/runtime/stats", response_model=RuntimeStatsResponse)
async def runtime_metrics() -> RuntimeStatsResponse:
    stats = runtime_stats.snapshot()
    stats.update(drift_monitor.snapshot())
    return RuntimeStatsResponse(**stats)


@app.post("/v1/ml/feedback", response_model=FeedbackIngestResponse)
async def ingest_feedback(payload: FeedbackIngestRequest) -> FeedbackIngestResponse:
    corrections = [
        FeedbackCorrection(
            tx_id=item.tx_id,
            corrected_category=item.corrected_category,
            note=item.note,
        )
        for item in payload.corrections
    ]
    result = await run_in_threadpool(
        active_learning.submit_feedback,
        payload.audit_id,
        corrections,
        payload.source,
        payload.auto_retrain,
    )
    return FeedbackIngestResponse(**result)


@app.post("/v1/ml/retrain", response_model=RetrainResponse)
async def retrain_now() -> RetrainResponse:
    result = await run_in_threadpool(active_learning.trigger_retrain, "manual_api")
    return RetrainResponse(**result)


@app.get("/v1/ml/status", response_model=ActiveLearningStatusResponse)
async def ml_status() -> ActiveLearningStatusResponse:
    result = await run_in_threadpool(active_learning.status)
    return ActiveLearningStatusResponse(**result)


@app.get("/v1/ml/feedback/export")
async def export_feedback(status: str | None = None) -> Response:
    statuses = [status] if status else None
    rows = await run_in_threadpool(active_learning.export_feedback, statuses)
    body = "\n".join(json.dumps(item, ensure_ascii=True) for item in rows)
    headers = {"Content-Disposition": "attachment; filename=feedback_export.jsonl"}
    return Response(content=body, media_type="application/x-ndjson", headers=headers)


@app.get("/v1/admin/settings", response_model=AdminSettingsResponse)
async def admin_get_settings() -> AdminSettingsResponse:
    return AdminSettingsResponse(
        settings=_runtime_settings_payload(),
        mutable_keys=sorted(MUTABLE_RUNTIME_SETTINGS),
    )


@app.put("/v1/admin/settings", response_model=AdminSettingsResponse)
async def admin_update_settings(payload: AdminSettingsUpdateRequest) -> AdminSettingsResponse:
    if payload.settings:
        try:
            updated_at = datetime.now(timezone.utc)
            with session_scope(settings) as session:
                repo = SettingsRepository(session)
                for key, value in payload.settings.items():
                    coerced = _apply_runtime_setting(key, value)
                    repo.upsert_setting(
                        key=key,
                        value_json=json.dumps(coerced, ensure_ascii=True),
                        updated_at=updated_at,
                    )
            _refresh_security_runtime()
            _refresh_runtime_services()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AdminSettingsResponse(
        settings=_runtime_settings_payload(),
        mutable_keys=sorted(MUTABLE_RUNTIME_SETTINGS),
    )


@app.post("/v1/merchant/resolve", response_model=list[MerchantMatchResponse])
async def resolve_merchant(payload: MerchantResolveRequest) -> list[MerchantMatchResponse]:
    matches = await run_in_threadpool(
        merchant_resolver.resolve,
        payload.text,
        payload.threshold,
        payload.top_k,
    )
    return [
        MerchantMatchResponse(
            merchant_id=m.merchant_id,
            canonical_name=m.canonical_name,
            category=m.category,
            subcategory=m.subcategory,
            similarity_score=m.similarity_score,
            match_type=m.match_type,
        )
        for m in matches
    ]


@app.post("/v1/export")
async def export_audit(payload: ExportRequest) -> Response:
    def _load_classified_transactions() -> list[dict]:
        with session_scope(settings) as session:
            repo = AuditRepository(session)
            run = repo.get_audit_run(payload.audit_id)
            if run is None:
                return []
            return repo.get_classified_transactions_as_dicts(payload.audit_id)

    rows = await run_in_threadpool(_load_classified_transactions)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No transactions found for audit_id={payload.audit_id}")

    fmt = payload.format.lower()
    if fmt == "csv":
        body = export_service.to_csv(rows, payload.include_explanations)
        media = "text/csv"
        filename = f"export_{payload.audit_id}.csv"
    elif fmt == "quickbooks_iif":
        body = export_service.to_quickbooks_iif(rows)
        media = "text/plain"
        filename = f"export_{payload.audit_id}.iif"
    elif fmt == "xero_csv":
        body = export_service.to_xero_csv(rows)
        media = "text/csv"
        filename = f"export_{payload.audit_id}_xero.csv"
    elif fmt in {"json", "quickbooks_json", "xero_json"}:
        variant = fmt.replace("_json", "") if "_json" in fmt else "standard"
        body = export_service.to_json(rows, variant)
        media = "application/json"
        filename = f"export_{payload.audit_id}.json"
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {payload.format}")

    return Response(
        content=body,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/v1/audit/upload")
async def upload_statement(file: UploadFile = File(...)) -> JSONResponse:
    name = Path(file.filename or "statement.csv").name
    suffix = Path(name).suffix.lower()
    if suffix not in {".csv", ".pdf"}:
        raise HTTPException(status_code=400, detail="Only .csv and .pdf files are allowed")

    out_path = build_upload_path(Path("data/uploads"), suffix=suffix)

    try:
        size_bytes = await run_in_threadpool(
            persist_upload_with_size_limit,
            file.file,
            out_path,
            settings.upload_max_bytes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    finally:
        file.file.close()

    return JSONResponse(
        {
            "path": str(out_path),
            "type": suffix.replace(".", ""),
            "original_filename": name,
            "size_bytes": size_bytes,
        }
    )
