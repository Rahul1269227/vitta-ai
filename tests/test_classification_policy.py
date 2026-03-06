from datetime import date

from sentinelfi.domain.models import ClassifiedTransaction, TxCategory
from sentinelfi.services.classification_policy import ClassificationPolicy


def _classified(desc: str, confidence: float, category: TxCategory) -> ClassifiedTransaction:
    return ClassifiedTransaction(
        tx_id="x1",
        tx_date=date(2025, 1, 1),
        description=desc,
        amount=15000,
        normalized_description=desc.lower(),
        pii_redacted_description=desc.lower(),
        category=category,
        confidence=confidence,
        classifier="slm",
    )


def test_policy_escalates_unknown_and_low_confidence() -> None:
    policy = ClassificationPolicy(slm_escalation_threshold=0.72)

    low = _classified("software invoice", 0.68, TxCategory.BUSINESS)
    unknown = _classified("ambiguous descriptor", 0.9, TxCategory.UNKNOWN)

    assert policy.should_escalate_from_slm(low)
    assert policy.should_escalate_from_slm(unknown)


def test_policy_sets_review_flag_for_high_risk() -> None:
    policy = ClassificationPolicy(review_threshold_default=0.7, review_threshold_high_risk=0.85)
    tx = _classified("gst invoice consulting", 0.82, TxCategory.BUSINESS)

    policy.apply_review_flag(tx)
    assert tx.requires_review is True
