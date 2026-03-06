from __future__ import annotations

import csv
import hashlib
import hmac
import json
import random
import smtplib
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Callable

import httpx

from sentinelfi.core.config import Settings
from sentinelfi.domain.models import CleanupTask

_RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


class CleanupTaskExecutor:
    def __init__(
        self,
        output_dir: str | Path = "output/cleanup",
        settings: Settings | None = None,
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.settings = settings or Settings()
        self._handlers: dict[str, Callable[[CleanupTask], dict]] = {
            "ledger_reclass": self._handle_ledger_reclass,
            "email_draft": self._handle_email_draft,
            "invoice_fetch": self._handle_invoice_fetch,
            "gst_recon": self._handle_gst_recon,
        }

    def execute(self, task: CleanupTask) -> dict:
        handler = self._handlers.get(task.task_type)
        if handler is None:
            return {
                "task_id": task.task_id,
                "task_type": task.task_type,
                "status": "failed",
                "message": f"Unsupported cleanup task type: {task.task_type}",
            }
        try:
            return handler(task)
        except Exception as exc:  # noqa: BLE001
            return {
                "task_id": task.task_id,
                "task_type": task.task_type,
                "status": "failed",
                "message": f"cleanup_task_failed:{exc}",
            }

    def _handle_ledger_reclass(self, task: CleanupTask) -> dict:
        path = self.output_dir / f"{task.task_id}_ledger_reclass.csv"
        if path.exists() and not self.settings.cleanup_ledger_webhook_url:
            return self._result(task, "already_executed", path, "Ledger reclass file already exists")

        finding_ids = task.payload.get("finding_ids", [])
        target_category = str(task.payload.get("target_category", "IT Expenses"))
        webhook_payload = {
            "task_id": task.task_id,
            "task_type": task.task_type,
            "idempotency_key": task.task_id,
            "finding_ids": [str(item) for item in finding_ids],
            "target_category": target_category,
        }
        webhook_result = self._post_webhook(
            task=task,
            webhook_name="ledger",
            webhook_url=self.settings.cleanup_ledger_webhook_url,
            payload=webhook_payload,
            artifact_path=self.output_dir / f"{task.task_id}_ledger_webhook_response.json",
            missing_message="CLEANUP_LEDGER_WEBHOOK_URL is not configured",
            success_message="Ledger reclassification sent to external system",
        )
        if webhook_result is not None:
            return webhook_result

        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=["finding_id", "target_category", "action", "generated_at_utc"],
            )
            writer.writeheader()
            generated_at = datetime.now(timezone.utc).isoformat()
            for item in finding_ids:
                writer.writerow(
                    {
                        "finding_id": str(item),
                        "target_category": target_category,
                        "action": "reclassify",
                        "generated_at_utc": generated_at,
                    }
                )
        return self._result(task, "executed", path, "Generated ledger reclassification CSV")

    def _handle_email_draft(self, task: CleanupTask) -> dict:
        path = self.output_dir / f"{task.task_id}_cancellation_email.txt"
        if path.exists() and not self.settings.cleanup_email_smtp_host:
            return self._result(task, "already_executed", path, "Email draft already exists")

        finding_ids = task.payload.get("finding_ids", [])
        subject = "Cancellation and Refund Request"
        body = (
            "Hello Support Team,\n\n"
            "Please cancel the duplicate/overlapping subscription(s) listed below and process any eligible refund.\n\n"
            f"Finding IDs: {', '.join(str(item) for item in finding_ids) if finding_ids else 'N/A'}\n\n"
            "Regards,\n"
            "Finance Team\n"
        )
        full_text = f"Subject: {subject}\n\n{body}"
        path.write_text(full_text, encoding="utf-8")

        email_result = self._send_email_if_configured(
            task=task,
            subject=subject,
            body=body,
            draft_path=path,
        )
        if email_result is not None:
            return email_result
        return self._result(task, "executed", path, "Generated cancellation/refund email draft")

    def _handle_invoice_fetch(self, task: CleanupTask) -> dict:
        path = self.output_dir / f"{task.task_id}_invoice_fetch_plan.json"
        if path.exists() and not self.settings.cleanup_invoice_webhook_url:
            return self._result(task, "already_executed", path, "Invoice fetch plan already exists")

        tx_ids = [str(item) for item in task.payload.get("tx_ids", [])]
        payload = {
            "task_id": task.task_id,
            "task_type": task.task_type,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "tx_ids": tx_ids,
            "sources": ["email", "whatsapp"],
            "status": "pending_fetch",
        }
        webhook_result = self._post_webhook(
            task=task,
            webhook_name="invoice",
            webhook_url=self.settings.cleanup_invoice_webhook_url,
            payload=payload,
            artifact_path=self.output_dir / f"{task.task_id}_invoice_webhook_response.json",
            missing_message="CLEANUP_INVOICE_WEBHOOK_URL is not configured",
            success_message="Invoice retrieval task submitted to external system",
        )
        if webhook_result is not None:
            return webhook_result
        path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
        return self._result(task, "executed", path, "Generated invoice fetch execution plan")

    def _handle_gst_recon(self, task: CleanupTask) -> dict:
        path = self.output_dir / f"{task.task_id}_gst_recon.csv"
        if path.exists() and not self.settings.cleanup_gst_webhook_url:
            return self._result(task, "already_executed", path, "GST reconciliation sheet already exists")

        finding_ids = [str(item) for item in task.payload.get("gst_finding_ids", [])]
        webhook_result = self._post_webhook(
            task=task,
            webhook_name="gst",
            webhook_url=self.settings.cleanup_gst_webhook_url,
            payload={
                "task_id": task.task_id,
                "task_type": task.task_type,
                "idempotency_key": task.task_id,
                "gst_finding_ids": finding_ids,
            },
            artifact_path=self.output_dir / f"{task.task_id}_gst_webhook_response.json",
            missing_message="CLEANUP_GST_WEBHOOK_URL is not configured",
            success_message="GST reconciliation task submitted to external system",
        )
        if webhook_result is not None:
            return webhook_result

        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=["gst_finding_id", "status", "next_action"],
            )
            writer.writeheader()
            for item in finding_ids:
                writer.writerow(
                    {
                        "gst_finding_id": item,
                        "status": "pending_reconciliation",
                        "next_action": "validate_invoice_and_claim_itc",
                    }
                )
        return self._result(task, "executed", path, "Generated GST reconciliation CSV")

    @staticmethod
    def _result(task: CleanupTask, status: str, artifact: Path, message: str) -> dict:
        return {
            "task_id": task.task_id,
            "task_type": task.task_type,
            "status": status,
            "message": message,
            "artifact_path": str(artifact),
        }

    def _post_webhook(
        self,
        *,
        task: CleanupTask,
        webhook_name: str,
        webhook_url: str | None,
        payload: dict,
        artifact_path: Path,
        missing_message: str,
        success_message: str,
    ) -> dict | None:
        if not webhook_url:
            if self.settings.cleanup_live_mode:
                return {
                    "task_id": task.task_id,
                    "task_type": task.task_type,
                    "status": "failed",
                    "message": missing_message,
                }
            return None

        body = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
        timeout = float(self.settings.cleanup_webhook_timeout_seconds)
        max_attempts = max(1, int(self.settings.cleanup_webhook_max_attempts))
        base_wait = max(0.0, float(self.settings.cleanup_webhook_retry_base_seconds))
        max_wait = max(base_wait, float(self.settings.cleanup_webhook_retry_max_seconds))

        response: httpx.Response | None = None
        last_error: str | None = None
        for attempt in range(1, max_attempts + 1):
            headers = {
                "content-type": "application/json",
                "x-idempotency-key": task.task_id,
                "x-cleanup-task-id": task.task_id,
            }
            headers.update(self._signed_headers(webhook_name=webhook_name, body=body))
            try:
                with httpx.Client(timeout=timeout) as client:
                    response = client.post(webhook_url, content=body, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = f"transport_error:{exc}"
                response = None
            else:
                if response.status_code < 400:
                    break
                if response.status_code in _RETRYABLE_STATUS_CODES:
                    last_error = f"retryable_http_error:{response.status_code}"
                else:
                    return {
                        "task_id": task.task_id,
                        "task_type": task.task_type,
                        "status": "failed",
                        "message": f"cleanup_webhook_error:{response.status_code}",
                    }

            if attempt < max_attempts:
                sleep_for = min(max_wait, base_wait * (2 ** (attempt - 1)))
                if sleep_for > 0:
                    sleep_for += random.uniform(0.0, min(0.25, sleep_for))
                    time.sleep(sleep_for)

        if response is None or response.status_code >= 400:
            return {
                "task_id": task.task_id,
                "task_type": task.task_type,
                "status": "failed",
                "message": last_error or "cleanup_webhook_failed",
            }

        artifact_path.write_text(
            json.dumps(
                {
                    "task_id": task.task_id,
                    "webhook_name": webhook_name,
                    "status_code": response.status_code,
                    "response_text": response.text,
                    "attempts": max_attempts if response.status_code >= 400 else attempt,
                    "submitted_at_utc": datetime.now(timezone.utc).isoformat(),
                },
                ensure_ascii=True,
                indent=2,
            ),
            encoding="utf-8",
        )
        return self._result(task, "executed", artifact_path, success_message)

    def _send_email_if_configured(
        self,
        *,
        task: CleanupTask,
        subject: str,
        body: str,
        draft_path: Path,
    ) -> dict | None:
        host = self.settings.cleanup_email_smtp_host
        if not host:
            if self.settings.cleanup_live_mode:
                return {
                    "task_id": task.task_id,
                    "task_type": task.task_type,
                    "status": "failed",
                    "message": "CLEANUP_EMAIL_SMTP_HOST is not configured",
                }
            return None

        sender = (self.settings.cleanup_email_from or "").strip()
        recipients = [
            item.strip()
            for item in self.settings.cleanup_email_to_csv.split(",")
            if item.strip()
        ]
        if not sender or not recipients:
            return {
                "task_id": task.task_id,
                "task_type": task.task_type,
                "status": "failed",
                "message": "CLEANUP_EMAIL_FROM and CLEANUP_EMAIL_TO_CSV are required for SMTP send",
                "artifact_path": str(draft_path),
            }

        msg = EmailMessage()
        msg["From"] = sender
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = subject
        msg.set_content(body)

        try:
            if self.settings.cleanup_email_smtp_use_ssl:
                with smtplib.SMTP_SSL(host, self.settings.cleanup_email_smtp_port, timeout=20) as smtp:
                    self._smtp_login_if_needed(smtp)
                    smtp.send_message(msg)
            else:
                with smtplib.SMTP(host, self.settings.cleanup_email_smtp_port, timeout=20) as smtp:
                    if self.settings.cleanup_email_smtp_use_tls:
                        smtp.starttls()
                    self._smtp_login_if_needed(smtp)
                    smtp.send_message(msg)
        except Exception as exc:  # noqa: BLE001
            return {
                "task_id": task.task_id,
                "task_type": task.task_type,
                "status": "failed",
                "message": f"smtp_send_failed:{exc}",
                "artifact_path": str(draft_path),
            }

        return self._result(task, "executed", draft_path, "Email sent via SMTP")

    def _smtp_login_if_needed(self, smtp: smtplib.SMTP) -> None:
        username = self.settings.cleanup_email_smtp_username
        password = self.settings.cleanup_email_smtp_password
        if username and password:
            smtp.login(username, password)

    def _signed_headers(self, *, webhook_name: str, body: str) -> dict[str, str]:
        secret = self._webhook_secret(webhook_name)
        if not secret:
            return {}
        timestamp = str(int(time.time()))
        signing_input = f"{timestamp}.{body}".encode()
        signature = hmac.new(
            secret.encode("utf-8"),
            signing_input,
            hashlib.sha256,
        ).hexdigest()
        return {
            "x-sf-signature": f"sha256={signature}",
            "x-sf-signature-ts": timestamp,
        }

    def _webhook_secret(self, webhook_name: str) -> str | None:
        per_webhook = {
            "ledger": self.settings.cleanup_ledger_webhook_hmac_secret,
            "invoice": self.settings.cleanup_invoice_webhook_hmac_secret,
            "gst": self.settings.cleanup_gst_webhook_hmac_secret,
        }.get(webhook_name)
        secret = (per_webhook or self.settings.cleanup_webhook_hmac_secret or "").strip()
        return secret or None
