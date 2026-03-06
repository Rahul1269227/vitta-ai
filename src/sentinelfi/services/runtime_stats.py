from __future__ import annotations

from collections import deque
from threading import Lock

from sentinelfi.domain.models import AuditOutput


class RuntimeStatsTracker:
    def __init__(self, window: int = 500):
        self.window = window
        self.audit_latencies_ms: deque[float] = deque(maxlen=window)
        self.tx_counts: deque[int] = deque(maxlen=window)
        self.leak_counts: deque[int] = deque(maxlen=window)
        self.review_rates: deque[float] = deque(maxlen=window)
        self.total_audits = 0
        self.lock = Lock()

    def record(self, latency_ms: float, output: AuditOutput) -> None:
        review_count = sum(1 for decision in output.classification_decisions if decision.requires_review)
        tx_count = max(1, output.summary.total_transactions)
        review_rate = review_count / tx_count

        with self.lock:
            self.total_audits += 1
            self.audit_latencies_ms.append(max(0.0, latency_ms))
            self.tx_counts.append(output.summary.total_transactions)
            self.leak_counts.append(output.summary.leak_count)
            self.review_rates.append(review_rate)

    def snapshot(self) -> dict[str, float]:
        with self.lock:
            avg_latency = (
                sum(self.audit_latencies_ms) / len(self.audit_latencies_ms)
                if self.audit_latencies_ms
                else 0.0
            )
            avg_tx = sum(self.tx_counts) / len(self.tx_counts) if self.tx_counts else 0.0
            avg_leaks = sum(self.leak_counts) / len(self.leak_counts) if self.leak_counts else 0.0
            avg_review_rate = (
                sum(self.review_rates) / len(self.review_rates)
                if self.review_rates
                else 0.0
            )
            return {
                "total_audits": float(self.total_audits),
                "avg_latency_ms": avg_latency,
                "avg_transactions_per_audit": avg_tx,
                "avg_leaks_per_audit": avg_leaks,
                "avg_review_rate": avg_review_rate,
            }
