from __future__ import annotations

from datetime import date

from sentinelfi.domain.models import ClassifiedTransaction, ClassifierVote, TxCategory
from sentinelfi.services.explainability_service import build_classification_decisions


def _classified(
    tx_id: str,
    *,
    classifier: str,
    category: TxCategory,
    confidence: float,
    requires_review: bool = False,
) -> ClassifiedTransaction:
    return ClassifiedTransaction(
        tx_id=tx_id,
        tx_date=date(2026, 1, 1),
        description="sample",
        amount=100.0,
        is_debit=True,
        normalized_description="sample",
        pii_redacted_description="sample",
        classifier=classifier,  # type: ignore[arg-type]
        category=category,
        confidence=confidence,
        requires_review=requires_review,
        explanations=["reason"],
    )


def test_build_classification_decisions_uses_all_votes_for_mixed_path() -> None:
    final = _classified(
        "tx-1",
        classifier="llm",
        category=TxCategory.BUSINESS,
        confidence=0.91,
    )
    votes = {
        "tx-1": [
            ClassifierVote(classifier="ml", category=TxCategory.PERSONAL, confidence=0.67, rationale="ml"),
            ClassifierVote(classifier="slm", category=TxCategory.UNKNOWN, confidence=0.58, rationale="slm"),
            ClassifierVote(classifier="llm", category=TxCategory.BUSINESS, confidence=0.91, rationale="llm"),
        ]
    }
    out = build_classification_decisions(
        [final],
        {"tx-1": "embedding-complex"},
        {"tx-1"},
        votes_by_tx_id=votes,
    )

    assert len(out) == 1
    decision = out[0]
    assert decision.route == "mixed"
    assert [vote.classifier for vote in decision.votes] == ["ml", "slm", "llm"]
    assert "vote:ml:TxCategory.PERSONAL:0.67" in decision.decision_path
    assert decision.final_classifier == "llm"


def test_build_classification_decisions_falls_back_to_final_vote() -> None:
    final = _classified(
        "tx-2",
        classifier="ml",
        category=TxCategory.PERSONAL,
        confidence=0.82,
    )
    out = build_classification_decisions([final], {}, set(), votes_by_tx_id={})

    assert len(out) == 1
    decision = out[0]
    assert decision.route == "ml"
    assert len(decision.votes) == 1
    assert decision.votes[0].classifier == "ml"
    assert decision.votes[0].category == TxCategory.PERSONAL
