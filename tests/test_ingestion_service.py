from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sentinelfi.domain.models import SourceType, Transaction
from sentinelfi.services.ingestion_service import ingest_transactions, normalize_transactions


def test_ingest_transactions_allows_paths_under_configured_root(tmp_path) -> None:
    csv_path = tmp_path / "input.csv"
    csv_path.write_text(
        "tx_id,tx_date,description,amount\n"
        "tx-1,2026-01-01,upi payment to merchant,-100.0\n",
        encoding="utf-8",
    )

    txs = ingest_transactions(
        SourceType.CSV,
        str(csv_path),
        {},
        allowed_local_roots=[str(tmp_path)],
    )

    assert len(txs) == 1
    assert txs[0].tx_id == "tx-1"


def test_ingest_transactions_blocks_paths_outside_allowed_roots(tmp_path) -> None:
    csv_path = tmp_path / "outside.csv"
    csv_path.write_text(
        "tx_id,tx_date,description,amount\n"
        "tx-1,2026-01-01,upi payment to merchant,-100.0\n",
        encoding="utf-8",
    )
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()

    with pytest.raises(ValueError, match="allowed roots"):
        ingest_transactions(
            SourceType.CSV,
            str(csv_path),
            {},
            allowed_local_roots=[str(allowed_root)],
        )


def test_normalize_transactions_drops_invalid_rows() -> None:
    today = datetime.now(timezone.utc).date()
    txs = [
        Transaction(
            tx_id="valid-1",
            tx_date=today - timedelta(days=1),
            description="UPI PAYMENT TO ACME SOFTWARE",
            amount=1500.0,
            is_debit=True,
            metadata={},
        ),
        Transaction(
            tx_id="invalid-amount",
            tx_date=today - timedelta(days=1),
            description="subscription",
            amount=0.0,
            is_debit=True,
            metadata={},
        ),
        Transaction(
            tx_id="invalid-desc",
            tx_date=today - timedelta(days=1),
            description="   ",
            amount=300.0,
            is_debit=True,
            metadata={},
        ),
        Transaction(
            tx_id="invalid-future",
            tx_date=today + timedelta(days=2),
            description="future debit",
            amount=100.0,
            is_debit=True,
            metadata={},
        ),
    ]

    normalized = normalize_transactions(txs, pii_hash_salt="unit-test-salt")
    assert len(normalized) == 1
    assert normalized[0].tx_id == "valid-1"
