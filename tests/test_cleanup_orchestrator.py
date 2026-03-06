from __future__ import annotations

from pathlib import Path

import httpx

from sentinelfi.core.config import Settings
from sentinelfi.domain.models import CleanupTask
from sentinelfi.services.cleanup_orchestrator import CleanupOrchestrator


def test_cleanup_orchestrator_respects_approval_gate(tmp_path: Path) -> None:
    tasks = [
        CleanupTask(
            task_id="t-approved",
            title="Approved task",
            task_type="ledger_reclass",
            requires_approval=True,
            payload={"finding_ids": ["f-1"], "target_category": "IT Expenses"},
        ),
        CleanupTask(
            task_id="t-auto",
            title="No approval task",
            task_type="email_draft",
            requires_approval=False,
            payload={"finding_ids": ["f-2"]},
        ),
    ]
    out = CleanupOrchestrator(output_dir=tmp_path).run(tasks, approved_task_ids=["t-approved"])

    executed_ids = {item["task_id"] for item in out.get("executed", [])}
    skipped_ids = set(out.get("skipped", []))

    assert executed_ids == {"t-approved", "t-auto"}
    assert skipped_ids == set()


def test_cleanup_orchestrator_skips_unapproved_tasks(tmp_path: Path) -> None:
    tasks = [
        CleanupTask(
            task_id="t1",
            title="Needs approval",
            task_type="gst_recon",
            requires_approval=True,
        ),
    ]
    out = CleanupOrchestrator(output_dir=tmp_path).run(tasks, approved_task_ids=[])

    assert out.get("executed", []) == []
    assert out.get("skipped", []) == ["t1"]


def test_cleanup_orchestrator_generates_artifacts(tmp_path: Path) -> None:
    tasks = [
        CleanupTask(
            task_id="t-ledger",
            title="Ledger reclass",
            task_type="ledger_reclass",
            requires_approval=False,
            payload={"finding_ids": ["f-1"], "target_category": "IT Expenses"},
        ),
        CleanupTask(
            task_id="t-gst",
            title="GST recon",
            task_type="gst_recon",
            requires_approval=False,
            payload={"gst_finding_ids": ["g-1"]},
        ),
    ]
    out = CleanupOrchestrator(output_dir=tmp_path).run(tasks, approved_task_ids=[])
    executed = out.get("executed", [])
    assert len(executed) == 2
    for item in executed:
        assert item["status"] == "executed"
        artifact = Path(item["artifact_path"])
        assert artifact.exists()


def test_cleanup_live_mode_fails_without_real_connectors(tmp_path: Path) -> None:
    tasks = [
        CleanupTask(
            task_id="t-live",
            title="Email task",
            task_type="email_draft",
            requires_approval=False,
            payload={"finding_ids": ["f-1"]},
        ),
    ]
    settings = Settings(
        cleanup_live_mode=True,
        cleanup_email_smtp_host=None,
    )
    out = CleanupOrchestrator(output_dir=tmp_path, settings=settings).run(tasks, approved_task_ids=[])
    assert len(out["executed"]) == 1
    assert out["executed"][0]["status"] == "failed"


def test_cleanup_webhook_retries_and_sends_hmac(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    statuses = [503, 503, 200]

    def _fake_post(self, url, *, content=None, headers=None, **kwargs):  # noqa: ANN001, ANN201, ARG001
        request = httpx.Request("POST", url, content=content, headers=headers)
        status = statuses[len(calls)]
        calls.append({"headers": headers or {}, "content": content})
        return httpx.Response(status, request=request, text="ok" if status == 200 else "retry")

    monkeypatch.setattr(httpx.Client, "post", _fake_post)

    settings = Settings(
        cleanup_live_mode=True,
        cleanup_ledger_webhook_url="https://example.test/ledger",
        cleanup_ledger_webhook_hmac_secret="super-secret",
        cleanup_webhook_max_attempts=3,
        cleanup_webhook_retry_base_seconds=0.0,
        cleanup_webhook_retry_max_seconds=0.0,
    )
    tasks = [
        CleanupTask(
            task_id="t-webhook",
            title="Ledger reclass",
            task_type="ledger_reclass",
            requires_approval=False,
            payload={"finding_ids": ["f-1"], "target_category": "IT Expenses"},
        )
    ]

    out = CleanupOrchestrator(output_dir=tmp_path, settings=settings).run(tasks, approved_task_ids=[])
    assert len(calls) == 3
    executed = out["executed"][0]
    assert executed["status"] == "executed"
    assert "artifact_path" in executed
    first_headers = calls[0]["headers"]
    assert "x-sf-signature" in first_headers
    assert str(first_headers["x-sf-signature"]).startswith("sha256=")
    assert "x-sf-signature-ts" in first_headers
