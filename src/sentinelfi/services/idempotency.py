from __future__ import annotations

import hashlib
import json

from sentinelfi.api.schemas import AuditRunRequest


def build_audit_idempotency_key(payload: AuditRunRequest) -> str:
    if payload.idempotency_key and payload.idempotency_key.strip():
        return payload.idempotency_key.strip()
    canonical = {
        "source_type": payload.source_type.value,
        "source_path": payload.source_path or "",
        "source_config": payload.source_config,
        "client_name": payload.client_name,
        "report_period": payload.report_period,
        "generate_pdf": payload.generate_pdf,
        "generate_markdown": payload.generate_markdown,
    }
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    digest = hashlib.sha256(blob).hexdigest()
    return f"audit:{digest}"
