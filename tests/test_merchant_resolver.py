"""Tests for the merchant gazetteer resolver."""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path

from sentinelfi.services.merchant_resolver import MerchantResolver


def _write_sample_gazetteer(path: Path) -> None:
    rows = [
        {
            "merchant_id": "1",
            "canonical_name": "ZOMATO",
            "aliases": "zomato,zmt,zomato pay",
            "category": "food_dining",
            "subcategory": "Food Delivery",
        },
        {
            "merchant_id": "2",
            "canonical_name": "SWIGGY",
            "aliases": "swiggy,swgy,swigy",
            "category": "food_dining",
            "subcategory": "Food Delivery",
        },
        {
            "merchant_id": "3",
            "canonical_name": "UBER",
            "aliases": "uber,uber cab,uber ride",
            "category": "transport",
            "subcategory": "Cab Services",
        },
        {
            "merchant_id": "4",
            "canonical_name": "FLIPKART",
            "aliases": "flipkart,flipkrt,fk",
            "category": "shopping",
            "subcategory": "Online Shopping",
        },
    ]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def test_exact_match() -> None:
    with tempfile.TemporaryDirectory() as td:
        csv_path = Path(td) / "merchants.csv"
        _write_sample_gazetteer(csv_path)
        resolver = MerchantResolver(csv_path)

        matches = resolver.resolve("ZOMATO")
        assert len(matches) == 1
        assert matches[0].canonical_name == "ZOMATO"
        assert matches[0].similarity_score == 1.0
        assert matches[0].match_type == "exact"


def test_alias_match_case_insensitive() -> None:
    with tempfile.TemporaryDirectory() as td:
        csv_path = Path(td) / "merchants.csv"
        _write_sample_gazetteer(csv_path)
        resolver = MerchantResolver(csv_path)

        matches = resolver.resolve("zomato pay")
        assert len(matches) >= 1
        assert matches[0].category == "food_dining"


def test_substring_match() -> None:
    with tempfile.TemporaryDirectory() as td:
        csv_path = Path(td) / "merchants.csv"
        _write_sample_gazetteer(csv_path)
        resolver = MerchantResolver(csv_path)

        matches = resolver.resolve("UPI UBER cab ride")
        assert len(matches) >= 1
        assert matches[0].canonical_name == "UBER"


def test_no_match_below_threshold() -> None:
    with tempfile.TemporaryDirectory() as td:
        csv_path = Path(td) / "merchants.csv"
        _write_sample_gazetteer(csv_path)
        resolver = MerchantResolver(csv_path)

        matches = resolver.resolve("some random text", threshold=0.90)
        assert matches == []


def test_search_returns_results() -> None:
    with tempfile.TemporaryDirectory() as td:
        csv_path = Path(td) / "merchants.csv"
        _write_sample_gazetteer(csv_path)
        resolver = MerchantResolver(csv_path)

        results = resolver.search("flipkart order")
        assert len(results) >= 1
        assert results[0].category == "shopping"


def test_empty_text() -> None:
    with tempfile.TemporaryDirectory() as td:
        csv_path = Path(td) / "merchants.csv"
        _write_sample_gazetteer(csv_path)
        resolver = MerchantResolver(csv_path)

        assert resolver.resolve("") == []
        assert resolver.resolve("", threshold=0.5) == []


def test_loading_real_gazetteer() -> None:
    path = Path("data/gazetteer/merchant_aliases.csv")
    if not path.exists():
        return  # skip if data not available

    resolver = MerchantResolver(path)
    assert len(resolver.merchants) > 100

    matches = resolver.resolve("Starbucks Coffee")
    assert len(matches) >= 1
    assert matches[0].category == "food_dining"
