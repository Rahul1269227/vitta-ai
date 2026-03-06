from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from sentinelfi.api import app as app_module
from sentinelfi.services.api_security import SlidingWindowRateLimiter, parse_api_keys
from sentinelfi.services.audit_execution import AuditExecutionService
from sentinelfi.services.audit_job_service import AuditJobService


def _configure_app_for_test(tmp_path: Path, *, enable_auth: bool) -> None:
    app_module.settings.database_url = f"sqlite:///{tmp_path}/api_test.db"
    app_module.settings.enable_local_embeddings = False
    app_module.settings.enable_ml_classifier = False
    app_module.settings.enable_api_key_auth = enable_auth
    app_module.settings.api_keys_csv = "test-key" if enable_auth else ""
    app_module.settings.admin_api_keys_csv = "admin-key"
    app_module.settings.cleanup_live_mode = False
    app_module.settings.cleanup_ledger_webhook_url = None
    app_module.settings.cleanup_invoice_webhook_url = None
    app_module.settings.cleanup_gst_webhook_url = None
    app_module.settings.cleanup_email_smtp_host = None
    app_module.settings.cleanup_email_from = None
    app_module.settings.cleanup_email_to_csv = ""
    app_module.settings.rate_limit_per_minute = 10_000
    app_module.allowed_api_keys = parse_api_keys(app_module.settings.api_keys_csv)
    app_module.admin_api_keys = parse_api_keys(app_module.settings.admin_api_keys_csv)
    app_module.rate_limiter = SlidingWindowRateLimiter(limit=10_000, window_seconds=60)
    app_module.audit_execution = AuditExecutionService(app_module.settings)

    app_module.audit_jobs.shutdown()
    app_module.audit_jobs = AuditJobService(
        settings=app_module.settings,
        max_workers=1,
        run_inline=True,
        execute_audit=app_module.audit_execution.execute,
    )


def test_upload_statement_sanitizes_filename(tmp_path) -> None:
    _configure_app_for_test(tmp_path, enable_auth=False)
    with TestClient(app_module.app) as client:
        response = client.post(
            "/v1/audit/upload",
            files={
                "file": (
                    "../../escape.csv",
                    b"tx_date,description,amount\n2025-01-01,upi payment,-100\n",
                    "text/csv",
                )
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["original_filename"] == "escape.csv"
    assert ".." not in payload["path"]
    assert payload["path"].startswith("data/uploads/")
    assert Path(payload["path"]).exists()


def test_dashboard_ui_routes_are_public(tmp_path) -> None:
    _configure_app_for_test(tmp_path, enable_auth=True)
    with TestClient(app_module.app) as client:
        dashboard = client.get("/")
        assert dashboard.status_code == 200
        assert "Leakage Command Center" in dashboard.text

        css_asset = client.get("/assets/styles.css")
        assert css_asset.status_code == 200
        assert "Inter" in css_asset.text
        assert "Content-Security-Policy" in dashboard.headers


def test_api_key_auth_enforced_for_v1_routes(tmp_path) -> None:
    _configure_app_for_test(tmp_path, enable_auth=True)
    with TestClient(app_module.app) as client:
        unauthorized = client.get("/v1/runtime/stats")
        assert unauthorized.status_code == 401

        authorized = client.get("/v1/runtime/stats", headers={"x-api-key": "test-key"})
        assert authorized.status_code == 200


def test_metrics_endpoint_available(tmp_path) -> None:
    _configure_app_for_test(tmp_path, enable_auth=False)
    app_module.settings.prometheus_enabled = True
    with TestClient(app_module.app) as client:
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "sentinelfi_http_requests_total" in response.text


def test_admin_settings_endpoint_requires_admin_key(tmp_path) -> None:
    _configure_app_for_test(tmp_path, enable_auth=False)
    with TestClient(app_module.app) as client:
        forbidden = client.get("/v1/admin/settings")
        assert forbidden.status_code == 403

        authorized = client.get("/v1/admin/settings", headers={"x-api-key": "admin-key"})
        assert authorized.status_code == 200
        payload = authorized.json()
        assert "settings" in payload
        assert "mutable_keys" in payload


def test_admin_settings_endpoint_updates_runtime(tmp_path) -> None:
    _configure_app_for_test(tmp_path, enable_auth=False)
    with TestClient(app_module.app) as client:
        update = client.put(
            "/v1/admin/settings",
            headers={"x-api-key": "admin-key"},
            json={"settings": {"cleanup_live_mode": True, "rate_limit_per_minute": 777}},
        )
        assert update.status_code == 200
        payload = update.json()
        assert payload["settings"]["cleanup_live_mode"] is True
        assert payload["settings"]["rate_limit_per_minute"] == 777


def test_submit_and_poll_audit_job_inline(tmp_path) -> None:
    _configure_app_for_test(tmp_path, enable_auth=False)
    with TestClient(app_module.app) as client:
        submit = client.post(
            "/v1/audit/submit",
            json={
                "source_type": "csv",
                "source_path": "data/sample_transactions.csv",
                "source_config": {},
                "client_name": "Integration Test SMB",
                "report_period": "Jan 2026",
                "generate_pdf": False,
                "generate_markdown": False,
            },
        )
        assert submit.status_code == 200
        job_id = submit.json()["job_id"]

        status = client.get(f"/v1/audit/jobs/{job_id}")
        assert status.status_code == 200
        payload = status.json()
        assert payload["status"] in {"succeeded", "failed"}


def test_submit_audit_job_is_idempotent(tmp_path) -> None:
    _configure_app_for_test(tmp_path, enable_auth=False)
    with TestClient(app_module.app) as client:
        body = {
            "source_type": "csv",
            "source_path": "data/sample_transactions.csv",
            "source_config": {},
            "idempotency_key": "submit-key-1",
            "client_name": "Integration Test SMB",
            "report_period": "Jan 2026",
            "generate_pdf": False,
            "generate_markdown": False,
        }
        first = client.post("/v1/audit/submit", json=body)
        second = client.post("/v1/audit/submit", json=body)

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["job_id"] == second.json()["job_id"]


def test_run_audit_sync_is_idempotent(tmp_path) -> None:
    _configure_app_for_test(tmp_path, enable_auth=False)
    with TestClient(app_module.app) as client:
        body = {
            "source_type": "csv",
            "source_path": "data/sample_transactions.csv",
            "source_config": {},
            "idempotency_key": "run-key-1",
            "client_name": "Integration Test SMB",
            "report_period": "Jan 2026",
            "generate_pdf": False,
            "generate_markdown": False,
        }
        first = client.post("/v1/audit/run", json=body)
        second = client.post("/v1/audit/run", json=body)

        assert first.status_code == 200
        assert second.status_code == 200
        assert (
            first.json()["output"]["summary"]["audit_id"]
            == second.json()["output"]["summary"]["audit_id"]
        )


def test_cleanup_run_uses_server_side_tasks(tmp_path) -> None:
    _configure_app_for_test(tmp_path, enable_auth=False)
    with TestClient(app_module.app) as client:
        audit = client.post(
            "/v1/audit/run",
            json={
                "source_type": "csv",
                "source_path": "data/sample_transactions.csv",
                "source_config": {},
                "client_name": "Cleanup API Test",
                "report_period": "Jan 2026",
                "generate_pdf": False,
                "generate_markdown": False,
            },
        )
        assert audit.status_code == 200
        audit_payload = audit.json()
        audit_id = audit_payload["output"]["summary"]["audit_id"]
        cleanup_tasks = audit_payload["output"]["cleanup_tasks"]

        forged = client.post(
            "/v1/cleanup/run",
            json={"audit_id": audit_id, "approved_task_ids": ["task-forged"]},
        )
        assert forged.status_code == 400
        assert "Unknown approved_task_ids" in forged.json()["detail"]

        approved = [task["task_id"] for task in cleanup_tasks if task["requires_approval"]][:1]
        run = client.post(
            "/v1/cleanup/run",
            json={"audit_id": audit_id, "approved_task_ids": approved},
        )
        assert run.status_code == 200
        run_payload = run.json()
        executed_ids = {row["task_id"] for row in run_payload["executed"]}
        known_ids = {task["task_id"] for task in cleanup_tasks}
        assert executed_ids.issubset(known_ids)
        for row in run_payload["executed"]:
            assert "artifact_path" in row
            assert Path(row["artifact_path"]).exists()


def test_get_unknown_job_returns_404(tmp_path) -> None:
    _configure_app_for_test(tmp_path, enable_auth=False)
    with TestClient(app_module.app) as client:
        response = client.get("/v1/audit/jobs/job-missing")
        assert response.status_code == 404


def test_audit_schedule_endpoints(tmp_path) -> None:
    _configure_app_for_test(tmp_path, enable_auth=False)
    with TestClient(app_module.app) as client:
        create = client.post(
            "/v1/audit/schedules",
            json={
                "interval_minutes": 15,
                "payload": {
                    "source_type": "csv",
                    "source_path": "data/sample_transactions.csv",
                    "source_config": {},
                    "client_name": "Schedule Test",
                    "report_period": "Feb 2026",
                    "generate_pdf": False,
                    "generate_markdown": False,
                },
            },
        )
        assert create.status_code == 200
        created = create.json()
        assert created["status"] == "active"
        schedule_id = created["id"]

        listed = client.get("/v1/audit/schedules")
        assert listed.status_code == 200
        ids = {row["id"] for row in listed.json()}
        assert schedule_id in ids

        paused = client.post(f"/v1/audit/schedules/{schedule_id}/pause")
        assert paused.status_code == 200
        assert paused.json()["status"] == "paused"

        resumed = client.post(f"/v1/audit/schedules/{schedule_id}/resume")
        assert resumed.status_code == 200
        assert resumed.json()["status"] == "active"


def test_feedback_export_returns_jsonl(tmp_path) -> None:
    _configure_app_for_test(tmp_path, enable_auth=False)
    with TestClient(app_module.app) as client:
        audit = client.post(
            "/v1/audit/run",
            json={
                "source_type": "csv",
                "source_path": "data/sample_transactions.csv",
                "source_config": {},
                "client_name": "Feedback Export Test",
                "report_period": "Jan 2026",
                "generate_pdf": False,
                "generate_markdown": False,
            },
        )
        assert audit.status_code == 200
        payload = audit.json()
        audit_id = payload["output"]["summary"]["audit_id"]
        first_decision = payload["output"]["classification_decisions"][0]
        corrected = "personal" if first_decision["category"] == "business" else "business"

        feedback = client.post(
            "/v1/ml/feedback",
            json={
                "audit_id": audit_id,
                "corrections": [{"tx_id": first_decision["tx_id"], "corrected_category": corrected}],
                "auto_retrain": False,
                "source": "api_test",
            },
        )
        assert feedback.status_code == 200
        assert feedback.json()["accepted_count"] == 1

        export = client.get("/v1/ml/feedback/export")
        assert export.status_code == 200
        assert export.headers["content-type"].startswith("application/x-ndjson")
        lines = [line for line in export.text.splitlines() if line.strip()]
        assert len(lines) >= 1
        assert '"audit_id"' in lines[0]


def test_merchant_resolve_endpoint(tmp_path) -> None:
    _configure_app_for_test(tmp_path, enable_auth=False)
    with TestClient(app_module.app) as client:
        resp = client.post(
            "/v1/merchant/resolve",
            json={"text": "ZOMATO order food", "threshold": 0.50, "top_k": 3},
        )
        assert resp.status_code == 200
        matches = resp.json()
        # If gazetteer is loaded, expect results
        if matches:
            assert matches[0]["category"] == "food_dining"


def test_export_endpoint_404_on_missing_audit(tmp_path) -> None:
    _configure_app_for_test(tmp_path, enable_auth=False)
    with TestClient(app_module.app) as client:
        resp = client.post(
            "/v1/export",
            json={"audit_id": "nonexistent-audit", "format": "csv"},
        )
        assert resp.status_code == 404
