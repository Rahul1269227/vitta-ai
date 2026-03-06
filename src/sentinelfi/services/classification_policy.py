from __future__ import annotations

from dataclasses import dataclass

from sentinelfi.domain.models import ClassifiedTransaction, TxCategory

_HIGH_RISK_KEYWORDS = {
    "gst",
    "invoice",
    "consulting",
    "license",
    "software",
    "hosting",
    "agency",
    "audit",
    "tax",
    "professional",
}


@dataclass
class ClassificationPolicy:
    slm_escalation_threshold: float = 0.72
    review_threshold_default: float = 0.70
    review_threshold_high_risk: float = 0.85

    def is_high_risk(self, tx: ClassifiedTransaction) -> bool:
        text = tx.pii_redacted_description
        has_sensitive_keyword = any(token in text for token in _HIGH_RISK_KEYWORDS)
        high_amount = tx.amount >= 10000
        return bool(has_sensitive_keyword or high_amount)

    def review_threshold(self, tx: ClassifiedTransaction) -> float:
        return self.review_threshold_high_risk if self.is_high_risk(tx) else self.review_threshold_default

    def should_escalate_from_slm(self, tx: ClassifiedTransaction) -> bool:
        if tx.category == TxCategory.UNKNOWN:
            return True
        if tx.confidence < self.slm_escalation_threshold:
            return True

        threshold = self.review_threshold(tx)
        return tx.confidence < threshold

    def apply_review_flag(self, tx: ClassifiedTransaction) -> ClassifiedTransaction:
        tx.requires_review = tx.confidence < self.review_threshold(tx)
        return tx
