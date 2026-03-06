from __future__ import annotations

from sentinelfi.domain.models import ClassifiedTransaction, GstFinding, LeakFinding


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return max(0.0, numerator / denominator)


def compute_risk_score(
    leaks: list[LeakFinding],
    gst_findings: list[GstFinding],
    classified: list[ClassifiedTransaction],
) -> int:
    if not classified:
        return 0

    tx_count = len(classified)
    leak_count = len(leaks)
    review_count = sum(1 for tx in classified if tx.requires_review)
    avg_confidence = sum(tx.confidence for tx in classified) / tx_count

    p1_count = sum(1 for leak in leaks if leak.severity == "P1")
    p2_count = sum(1 for leak in leaks if leak.severity == "P2")
    p3_count = sum(1 for leak in leaks if leak.severity == "P3")
    severity_weighted = (p1_count * 1.0) + (p2_count * 0.6) + (p3_count * 0.25)
    severity_component = min(1.0, _safe_ratio(severity_weighted, max(1.0, tx_count * 0.08)))

    leak_density_component = min(1.0, _safe_ratio(float(leak_count), max(1.0, tx_count * 0.2)))

    total_leak_amount = sum(item.amount_impact for item in leaks)
    total_debit_spend = sum(tx.amount for tx in classified if tx.is_debit)
    leak_impact_component = min(1.0, _safe_ratio(total_leak_amount, max(1.0, total_debit_spend * 0.25)))

    missed_itc = sum(item.potential_itc_amount for item in gst_findings if not item.has_gst_invoice)
    itc_component = min(1.0, _safe_ratio(missed_itc, max(1.0, total_debit_spend * 0.1)))

    review_component = min(1.0, _safe_ratio(float(review_count), tx_count))
    uncertainty_component = min(1.0, max(0.0, 1.0 - avg_confidence))

    score = (
        0.35 * severity_component
        + 0.20 * leak_density_component
        + 0.20 * leak_impact_component
        + 0.10 * itc_component
        + 0.10 * review_component
        + 0.05 * uncertainty_component
    ) * 100.0
    return max(0, min(100, int(round(score))))
