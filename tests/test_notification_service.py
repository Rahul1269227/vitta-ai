from __future__ import annotations

from datetime import datetime, timezone

import httpx

from sentinelfi.core.config import Settings
from sentinelfi.domain.models import AuditOutput, AuditSummary, LeakFinding, LeakType
from sentinelfi.services.notification_service import NotificationService


def _build_output() -> AuditOutput:
    return AuditOutput(
        summary=AuditSummary(
            audit_id="audit-1",
            created_at=datetime.now(timezone.utc),
            total_transactions=10,
            leak_count=1,
            total_leak_amount=1200.0,
            missed_itc=100.0,
            risk_score=80,
        ),
        findings=[
            LeakFinding(
                finding_id="f-1",
                leak_type=LeakType.DUPLICATE_SUBSCRIPTION,
                severity="P1",
                amount_impact=1200.0,
                confidence=0.8,
                description="duplicate",
                tx_ids=["tx-1"],
                suggested_action="cancel",
            )
        ],
        gst_findings=[],
        cleanup_tasks=[],
        classification_decisions=[],
    )


def test_notification_service_retries_and_signs(monkeypatch) -> None:
    calls: list[dict] = []
    statuses = [503, 200]

    def _fake_post(self, url, *, content=None, headers=None, **kwargs):  # noqa: ANN001, ANN201, ARG001
        request = httpx.Request("POST", url, content=content, headers=headers)
        status = statuses[len(calls)]
        calls.append({"headers": headers or {}, "content": content})
        return httpx.Response(status, request=request, text="ok")

    monkeypatch.setattr(httpx.Client, "post", _fake_post)

    settings = Settings(
        alert_webhook_url="https://example.test/alert",
        alert_webhook_hmac_secret="alert-secret",
        alert_webhook_max_attempts=2,
        alert_webhook_retry_base_seconds=0.0,
        alert_webhook_retry_max_seconds=0.0,
    )
    NotificationService(settings).notify_audit(_build_output())

    assert len(calls) == 2
    headers = calls[0]["headers"]
    assert "x-sf-signature" in headers
    assert "x-sf-signature-ts" in headers
