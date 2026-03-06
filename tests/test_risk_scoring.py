from __future__ import annotations

from datetime import date

from sentinelfi.domain.models import (
    ClassifiedTransaction,
    GstFinding,
    LeakFinding,
    LeakType,
    TxCategory,
)
from sentinelfi.services.risk_scoring import compute_risk_score


def _classified(tx_id: str, amount: float, confidence: float, requires_review: bool = False):
    return ClassifiedTransaction(
        tx_id=tx_id,
        tx_date=date(2025, 1, 1),
        description="test tx",
        amount=amount,
        normalized_description="test tx",
        pii_redacted_description="test tx",
        category=TxCategory.BUSINESS,
        confidence=confidence,
        classifier="ml",
        is_debit=True,
        requires_review=requires_review,
    )


def _leak(fid: str, severity: str, impact: float) -> LeakFinding:
    return LeakFinding(
        finding_id=fid,
        leak_type=LeakType.DUPLICATE_SUBSCRIPTION,
        severity=severity,
        amount_impact=impact,
        confidence=0.8,
        description="test leak",
        tx_ids=["t1"],
        suggested_action="test action",
    )


def test_compute_risk_score_increases_with_severity_and_impact() -> None:
    base_txs = [
        _classified("t1", 1000.0, 0.95),
        _classified("t2", 900.0, 0.93),
        _classified("t3", 1100.0, 0.91),
    ]

    low = compute_risk_score(leaks=[], gst_findings=[], classified=base_txs)
    high = compute_risk_score(
        leaks=[_leak("l1", "P1", 1500.0), _leak("l2", "P2", 900.0)],
        gst_findings=[
            GstFinding(
                finding_id="g1",
                tx_id="t1",
                has_gst_invoice=False,
                likely_itc_eligible=True,
                issue="missing invoice",
                potential_itc_amount=700.0,
            )
        ],
        classified=[_classified("t1", 1000.0, 0.55, True), _classified("t2", 900.0, 0.6, True)],
    )

    assert 0 <= low <= 100
    assert 0 <= high <= 100
    assert high > low
