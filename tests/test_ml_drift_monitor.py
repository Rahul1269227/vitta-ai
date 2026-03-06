from __future__ import annotations

from datetime import date

import joblib

from sentinelfi.domain.models import ClassifiedTransaction, TxCategory
from sentinelfi.services.ml_drift_monitor import MLDriftMonitor


def _tx(confidence: float, category: TxCategory, text: str = "upi merchant payment") -> ClassifiedTransaction:
    return ClassifiedTransaction(
        tx_id=f"tx-{confidence}",
        tx_date=date(2025, 1, 1),
        description=text,
        amount=100.0,
        normalized_description=text,
        pii_redacted_description=text,
        category=category,
        confidence=confidence,
        classifier="ml",
    )


def test_drift_monitor_reports_stable_for_baseline_like_batch(tmp_path) -> None:
    model_path = tmp_path / "model.joblib"
    joblib.dump(
        {
            "metadata": {
                "drift_baseline": {
                    "confidence_histogram": [0, 0, 0, 1, 1, 2, 4, 6, 9, 17],
                    "confidence_mean": 0.9,
                    "confidence_std": 0.08,
                    "business_rate": 0.6,
                    "text_token_mean": 3.0,
                    "text_token_std": 1.0,
                }
            }
        },
        model_path,
    )

    monitor = MLDriftMonitor(str(model_path), window=100)
    monitor.record(
        [
            _tx(0.88, TxCategory.BUSINESS, "upi merchant payment"),
            _tx(0.93, TxCategory.BUSINESS, "upi vendor invoice"),
            _tx(0.85, TxCategory.PERSONAL, "upi dinner payment"),
        ]
    )
    snapshot = monitor.snapshot()
    assert snapshot["ml_samples"] == 3.0
    assert snapshot["ml_drift_status"] == "stable"


def test_drift_monitor_reports_critical_for_large_shift(tmp_path) -> None:
    model_path = tmp_path / "model.joblib"
    joblib.dump(
        {
            "metadata": {
                "drift_baseline": {
                    "confidence_histogram": [1, 1, 1, 1, 2, 3, 4, 7, 10, 20],
                    "confidence_mean": 0.92,
                    "confidence_std": 0.05,
                    "business_rate": 0.5,
                    "text_token_mean": 3.0,
                    "text_token_std": 0.5,
                }
            }
        },
        model_path,
    )

    monitor = MLDriftMonitor(str(model_path), window=100)
    monitor.record(
        [
            _tx(0.2, TxCategory.BUSINESS, "very long new transaction descriptor unseen"),
            _tx(0.18, TxCategory.BUSINESS, "very long new transaction descriptor unseen"),
            _tx(0.15, TxCategory.BUSINESS, "very long new transaction descriptor unseen"),
        ]
    )
    snapshot = monitor.snapshot()
    assert snapshot["ml_samples"] == 3.0
    assert snapshot["ml_drift_status"] == "critical"
