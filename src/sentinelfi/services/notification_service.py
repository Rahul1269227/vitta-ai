from __future__ import annotations

import hashlib
import hmac
import json
import random
import time
from datetime import datetime, timezone

import httpx

from sentinelfi.core.config import Settings
from sentinelfi.core.logging import get_logger
from sentinelfi.domain.models import AuditOutput

log = get_logger(__name__)
_RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


class NotificationService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def notify_audit(self, output: AuditOutput) -> None:
        if not self.settings.alert_webhook_url:
            return
        p1 = [item for item in output.findings if item.severity == "P1"]
        if not p1:
            return

        payload = {
            "event": "audit.p1_leaks_detected",
            "occurred_at_utc": datetime.now(timezone.utc).isoformat(),
            "audit_id": output.summary.audit_id,
            "risk_score": output.summary.risk_score,
            "leak_count": len(output.findings),
            "p1_count": len(p1),
            "p1_findings": [
                {
                    "finding_id": item.finding_id,
                    "leak_type": item.leak_type.value,
                    "amount_impact": item.amount_impact,
                    "description": item.description,
                }
                for item in p1
            ],
        }
        self._send_webhook(payload=payload, idempotency_key=f"audit-alert:{output.summary.audit_id}")

    def _send_webhook(self, *, payload: dict, idempotency_key: str) -> None:
        webhook_url = self.settings.alert_webhook_url
        if not webhook_url:
            return
        body = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
        timeout = float(self.settings.alert_webhook_timeout_seconds)
        max_attempts = max(1, int(self.settings.alert_webhook_max_attempts))
        base_wait = max(0.0, float(self.settings.alert_webhook_retry_base_seconds))
        max_wait = max(base_wait, float(self.settings.alert_webhook_retry_max_seconds))

        last_error = "unknown_error"
        for attempt in range(1, max_attempts + 1):
            headers = {
                "content-type": "application/json",
                "x-idempotency-key": idempotency_key,
            }
            headers.update(self._signed_headers(body))
            try:
                with httpx.Client(timeout=timeout) as client:
                    response = client.post(webhook_url, content=body, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = f"transport_error:{exc}"
                should_retry = True
            else:
                if response.status_code < 400:
                    return
                if response.status_code in _RETRYABLE_STATUS_CODES:
                    last_error = f"retryable_http_error:{response.status_code}"
                    should_retry = True
                else:
                    log.warning(
                        "alert_webhook_failed",
                        status_code=response.status_code,
                        response_text=response.text[:500],
                    )
                    return

            if not should_retry or attempt >= max_attempts:
                break

            sleep_for = min(max_wait, base_wait * (2 ** (attempt - 1)))
            if sleep_for > 0:
                sleep_for += random.uniform(0.0, min(0.25, sleep_for))
                time.sleep(sleep_for)

        log.warning("alert_webhook_retries_exhausted", error=last_error, attempts=max_attempts)

    def _signed_headers(self, body: str) -> dict[str, str]:
        secret = (self.settings.alert_webhook_hmac_secret or "").strip()
        if not secret:
            return {}
        timestamp = str(int(time.time()))
        signing_input = f"{timestamp}.{body}".encode()
        signature = hmac.new(secret.encode(), signing_input, hashlib.sha256).hexdigest()
        return {
            "x-sf-signature": f"sha256={signature}",
            "x-sf-signature-ts": timestamp,
        }
