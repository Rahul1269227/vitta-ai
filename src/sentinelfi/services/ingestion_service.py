from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sentinelfi.connectors.csv_connector import load_transactions_from_csv
from sentinelfi.connectors.pdf_connector import load_transactions_from_pdf
from sentinelfi.connectors.razorpay_connector import RazorpayConnector
from sentinelfi.connectors.stripe_connector import StripeConnector
from sentinelfi.core.logging import get_logger
from sentinelfi.domain.models import NormalizedTransaction, SourceType, Transaction
from sentinelfi.services.text_utils import extract_upi_signals, normalize_descriptor, scrub_pii

log = get_logger(__name__)


def ingest_transactions(
    source_type: SourceType,
    source_path: str | None,
    source_config: dict[str, Any],
    allowed_local_roots: list[str] | None = None,
    pdf_ocr_enabled: bool = True,
    pdf_ocr_lang: str = "en",
) -> list[Transaction]:
    if source_type == SourceType.CSV:
        if not source_path:
            raise ValueError("source_path is required for CSV ingestion")
        safe_path = _resolve_local_source_path(source_path, allowed_local_roots)
        csv_encoding = _to_optional_str(source_config.get("csv_encoding"))
        csv_date_format = _to_optional_str(source_config.get("csv_date_format"))
        csv_dayfirst = _coerce_bool(source_config.get("csv_dayfirst"), default=True)
        csv_dedup_rows = _coerce_bool(source_config.get("csv_dedup_rows"), default=True)
        return load_transactions_from_csv(
            safe_path,
            encoding=csv_encoding,
            date_format=csv_date_format,
            dayfirst=csv_dayfirst,
            dedup_rows=csv_dedup_rows,
        )

    if source_type == SourceType.PDF:
        if not source_path:
            raise ValueError("source_path is required for PDF ingestion")
        safe_path = _resolve_local_source_path(source_path, allowed_local_roots)
        return load_transactions_from_pdf(
            safe_path,
            enable_ocr_fallback=pdf_ocr_enabled,
            ocr_lang=pdf_ocr_lang,
        )

    if source_type == SourceType.STRIPE:
        api_key = source_config.get("api_key")
        if not api_key:
            raise ValueError("Stripe api_key missing")
        return StripeConnector(api_key).fetch_transactions(limit=int(source_config.get("limit", 100)))

    if source_type == SourceType.RAZORPAY:
        key_id = source_config.get("key_id")
        key_secret = source_config.get("key_secret")
        if not key_id or not key_secret:
            raise ValueError("Razorpay key_id/key_secret missing")
        return RazorpayConnector(key_id, key_secret).fetch_transactions(count=int(source_config.get("count", 100)))

    raise ValueError(f"Unsupported source_type: {source_type}")


def normalize_transactions(transactions: list[Transaction], pii_hash_salt: str) -> list[NormalizedTransaction]:
    normalized: list[NormalizedTransaction] = []
    dropped_invalid = 0
    for tx in transactions:
        validation_errors = _validate_transaction(tx)
        if validation_errors:
            dropped_invalid += 1
            log.info("ingestion_row_dropped_invalid", tx_id=tx.tx_id, errors=validation_errors)
            continue
        clean_desc = normalize_descriptor(tx.description)
        upi_signals = extract_upi_signals(clean_desc)
        redacted = scrub_pii(clean_desc, pii_hash_salt)
        metadata = dict(tx.metadata)
        if upi_signals["is_upi"]:
            metadata["upi"] = upi_signals
        normalized.append(
            NormalizedTransaction(
                **tx.model_dump(exclude={"metadata"}),
                normalized_description=clean_desc,
                pii_redacted_description=redacted,
                metadata=metadata,
            )
        )
    if dropped_invalid > 0:
        log.warning("ingestion_invalid_rows_dropped", dropped=dropped_invalid, total=len(transactions))
    return normalized


def _resolve_local_source_path(source_path: str, allowed_local_roots: list[str] | None) -> str:
    source = Path(source_path).expanduser().resolve(strict=False)
    roots = allowed_local_roots if allowed_local_roots else ["data/uploads", "data"]
    resolved_roots = [Path(root).expanduser().resolve(strict=False) for root in roots]

    if not any(_is_within(source, root) for root in resolved_roots):
        roots_csv = ", ".join(str(root) for root in resolved_roots)
        raise ValueError(f"source_path must resolve under allowed roots: {roots_csv}")

    return str(source)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _coerce_bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _to_optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _validate_transaction(tx: Transaction) -> list[str]:
    issues: list[str] = []
    if not str(tx.description or "").strip():
        issues.append("empty_description")
    if float(tx.amount) <= 0:
        issues.append("non_positive_amount")
    today = datetime.now(timezone.utc).date()
    if tx.tx_date > today:
        issues.append("future_date")
    return issues
