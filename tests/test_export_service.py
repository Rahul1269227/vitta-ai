"""Tests for the export service."""

from __future__ import annotations

import csv
import io
import json

from sentinelfi.services.export_service import ExportService


def _sample_transactions() -> list[dict]:
    return [
        {
            "id": "tx-001",
            "date": "2025-01-15",
            "amount": 450.0,
            "currency": "INR",
            "category": "food_dining",
            "subcategory": "Restaurants",
            "merchant": "Zomato",
            "description": "UPI-ZOMATO-ORDER",
            "text": "UPI-ZOMATO-ORDER",
            "confidence": 0.92,
            "method": "ml",
            "requires_review": False,
            "explanations": ["keyword=zomato"],
            "ensemble_votes": {"ml": {"category": "food_dining"}},
        },
        {
            "id": "tx-002",
            "date": "2025-01-20",
            "amount": 15000.0,
            "currency": "INR",
            "category": "rent",
            "subcategory": "Rent",
            "merchant": "",
            "description": "NEFT RENT PAYMENT JAN",
            "text": "NEFT RENT PAYMENT JAN",
            "confidence": 0.95,
            "method": "rule",
            "requires_review": False,
            "explanations": ["rent_keyword"],
            "ensemble_votes": {"rule": {"category": "rent"}},
        },
    ]


def test_csv_export_has_header_and_rows() -> None:
    svc = ExportService()
    result = svc.to_csv(_sample_transactions())
    reader = csv.DictReader(io.StringIO(result))
    rows = list(reader)
    assert len(rows) == 2
    assert rows[0]["category"] == "food_dining"
    assert rows[1]["category"] == "rent"


def test_csv_export_with_explanations() -> None:
    svc = ExportService()
    result = svc.to_csv(_sample_transactions(), include_explanations=True)
    reader = csv.DictReader(io.StringIO(result))
    rows = list(reader)
    assert "explanations" in rows[0]
    assert "ensemble_votes" in rows[0]


def test_csv_export_empty() -> None:
    svc = ExportService()
    assert svc.to_csv([]) == ""


def test_quickbooks_iif_format() -> None:
    svc = ExportService()
    result = svc.to_quickbooks_iif(_sample_transactions())
    lines = result.strip().split("\n")
    # Header (3 lines) + 2 transactions * 3 lines each
    assert len(lines) == 3 + 2 * 3
    assert lines[0].startswith("!TRNS")
    assert "TRNS\t2025-01-15\tMeals & Entertainment\t-450.00" in lines[3]


def test_xero_csv_format() -> None:
    svc = ExportService()
    result = svc.to_xero_csv(_sample_transactions())
    reader = csv.DictReader(io.StringIO(result))
    rows = list(reader)
    assert len(rows) == 2
    assert rows[0]["*ContactName"] == "Zomato"
    assert rows[0]["AccountCode"] == "200"  # food_dining → 200


def test_json_standard() -> None:
    svc = ExportService()
    result = svc.to_json(_sample_transactions())
    parsed = json.loads(result)
    assert len(parsed) == 2


def test_json_quickbooks_variant() -> None:
    svc = ExportService()
    result = svc.to_json(_sample_transactions(), variant="quickbooks")
    parsed = json.loads(result)
    assert "Transaction" in parsed
    assert len(parsed["Transaction"]) == 2


def test_json_xero_variant() -> None:
    svc = ExportService()
    result = svc.to_json(_sample_transactions(), variant="xero")
    parsed = json.loads(result)
    assert "Invoices" in parsed
    assert len(parsed["Invoices"]) == 2
