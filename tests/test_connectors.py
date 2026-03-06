from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from sentinelfi.connectors.csv_connector import load_transactions_from_csv
from sentinelfi.connectors.pdf_connector import load_transactions_from_pdf
from sentinelfi.connectors.razorpay_connector import RazorpayConnector
from sentinelfi.connectors.stripe_connector import StripeConnector
from sentinelfi.domain.models import Transaction


def test_csv_connector_loads_transactions(tmp_path) -> None:
    df = pd.DataFrame(
        [
            {
                "tx_id": "t1",
                "tx_date": "2025-01-01",
                "description": "AWS subscription",
                "amount": 1200.0,
                "is_debit": True,
            }
        ]
    )
    csv_path = tmp_path / "sample.csv"
    df.to_csv(csv_path, index=False)

    txs = load_transactions_from_csv(str(csv_path))
    assert len(txs) == 1
    assert txs[0].tx_id == "t1"
    assert txs[0].amount == 1200.0


def test_csv_connector_rejects_missing_required_columns(tmp_path) -> None:
    df = pd.DataFrame([{"tx_id": "t1", "description": "x"}])
    csv_path = tmp_path / "bad.csv"
    df.to_csv(csv_path, index=False)

    with pytest.raises(ValueError):
        load_transactions_from_csv(str(csv_path))


def test_csv_connector_deduplicates_by_date_amount_description(tmp_path) -> None:
    df = pd.DataFrame(
        [
            {
                "tx_id": "t1",
                "tx_date": "2025-01-01",
                "description": "AWS Subscription",
                "amount": 1200.0,
                "is_debit": True,
            },
            {
                "tx_id": "t2",
                "tx_date": "2025-01-01",
                "description": " aws subscription ",
                "amount": 1200.0,
                "is_debit": True,
            },
        ]
    )
    csv_path = tmp_path / "dupe.csv"
    df.to_csv(csv_path, index=False)

    txs = load_transactions_from_csv(str(csv_path), dedup_rows=True)
    assert len(txs) == 1
    assert txs[0].tx_id == "t1"


def test_csv_connector_respects_configured_date_format(tmp_path) -> None:
    df = pd.DataFrame(
        [
            {
                "tx_id": "t3",
                "tx_date": "31/01/2026",
                "description": "Invoice payment",
                "amount": 2500.0,
                "is_debit": "dr",
            }
        ]
    )
    csv_path = tmp_path / "date-format.csv"
    df.to_csv(csv_path, index=False)

    txs = load_transactions_from_csv(str(csv_path), date_format="%d/%m/%Y")
    assert len(txs) == 1
    assert txs[0].tx_date == date(2026, 1, 31)
    assert txs[0].is_debit is True


def test_pdf_connector_missing_file_raises() -> None:
    with pytest.raises(FileNotFoundError):
        load_transactions_from_pdf("does-not-exist.pdf")


def test_pdf_connector_uses_ocr_fallback_when_table_is_missing(monkeypatch, tmp_path) -> None:
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%stub\n")

    class _Page:
        def extract_table(self):  # noqa: ANN201
            return None

    class _Pdf:
        pages = [_Page()]

        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN204
            return False

    monkeypatch.setattr("sentinelfi.connectors.pdf_connector.pdfplumber.open", lambda *_args, **_kwargs: _Pdf())
    monkeypatch.setattr(
        "sentinelfi.connectors.pdf_connector._parse_ocr_transactions",
        lambda *_args, **_kwargs: [
            Transaction(
                tx_id="ocr-1",
                tx_date=date(2026, 1, 1),
                description="scan txn",
                amount=512.0,
                is_debit=True,
            )
        ],
    )

    txs = load_transactions_from_pdf(str(pdf_path), enable_ocr_fallback=True)
    assert len(txs) == 1
    assert txs[0].tx_id == "ocr-1"


def test_pdf_connector_skips_ocr_when_disabled(monkeypatch, tmp_path) -> None:
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%stub\n")

    class _Page:
        def extract_table(self):  # noqa: ANN201
            return None

    class _Pdf:
        pages = [_Page()]

        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN204
            return False

    monkeypatch.setattr("sentinelfi.connectors.pdf_connector.pdfplumber.open", lambda *_args, **_kwargs: _Pdf())

    def _ocr_should_not_run(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("OCR fallback should be disabled in this test")

    monkeypatch.setattr("sentinelfi.connectors.pdf_connector._parse_ocr_transactions", _ocr_should_not_run)

    txs = load_transactions_from_pdf(str(pdf_path), enable_ocr_fallback=False)
    assert txs == []


def test_stripe_connector_parses_response(monkeypatch) -> None:
    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self):  # noqa: ANN201
            return {
                "data": [
                    {
                        "id": "txn_1",
                        "created": 1735689600,
                        "description": "Stripe payout",
                        "amount": -12345,
                        "currency": "inr",
                        "type": "payout",
                    }
                ]
            }

    class _Client:
        def __init__(self, **kwargs):  # noqa: ANN003
            self.kwargs = kwargs

        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN204
            return False

        def get(self, url: str, headers: dict[str, str], params: dict[str, int]):  # noqa: ANN201
            assert url.endswith("/balance_transactions")
            assert headers["Authorization"].startswith("Bearer ")
            assert params["limit"] == 5
            return _Resp()

    monkeypatch.setattr("sentinelfi.connectors.stripe_connector.httpx.Client", _Client)

    connector = StripeConnector(api_key="sk_test")
    txs = connector.fetch_transactions(limit=5)
    assert len(txs) == 1
    assert txs[0].tx_id == "txn_1"
    assert txs[0].amount == 123.45
    assert txs[0].is_debit is True


def test_razorpay_connector_parses_response(monkeypatch) -> None:
    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self):  # noqa: ANN201
            return {
                "items": [
                    {
                        "id": "pay_1",
                        "created_at": 1735689600,
                        "description": "Invoice payment",
                        "amount": 250000,
                        "currency": "INR",
                        "method": "upi",
                    }
                ]
            }

    class _Client:
        def __init__(self, **kwargs):  # noqa: ANN003
            self.kwargs = kwargs

        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN204
            return False

        def get(self, url: str, params: dict[str, int]):  # noqa: ANN201
            assert url.endswith("/payments")
            assert params["count"] == 7
            return _Resp()

    monkeypatch.setattr("sentinelfi.connectors.razorpay_connector.httpx.Client", _Client)

    connector = RazorpayConnector(key_id="rzp_test", key_secret="secret")
    txs = connector.fetch_transactions(count=7)
    assert len(txs) == 1
    assert txs[0].tx_id == "pay_1"
    assert txs[0].amount == 2500.0
    assert txs[0].merchant == "upi"
