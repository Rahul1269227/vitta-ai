from __future__ import annotations

from datetime import date

from sentinelfi.agents.slm_classifier import RuleBasedTransactionClassifier
from sentinelfi.domain.models import NormalizedTransaction, TxCategory


def _tx(tx_id: str, text: str) -> NormalizedTransaction:
    return NormalizedTransaction(
        tx_id=tx_id,
        tx_date=date(2025, 1, 1),
        description=text,
        amount=100.0,
        normalized_description=text.lower(),
        pii_redacted_description=text.lower(),
        is_debit=True,
    )


def test_rule_classifier_uses_local_vote_when_available(monkeypatch) -> None:
    classifier = RuleBasedTransactionClassifier(enable_local_model=True)

    def fake_vote(text: str):  # noqa: ANN001, ANN201
        return (TxCategory.BUSINESS, 0.88, "local_embedding_vote:b=0.90:p=0.12")

    monkeypatch.setattr(classifier, "_local_model_vote", fake_vote)
    out = classifier.classify([_tx("t1", "ambiguous descriptor")])
    assert len(out) == 1
    assert out[0].category == TxCategory.BUSINESS
    assert out[0].confidence >= 0.88
    assert any("local_embedding_vote" in item for item in out[0].explanations)


def test_rule_classifier_falls_back_to_keywords(monkeypatch) -> None:
    classifier = RuleBasedTransactionClassifier(enable_local_model=False)
    monkeypatch.setattr(classifier, "_local_model_vote", lambda _text: None)

    out = classifier.classify([_tx("t2", "swiggy lunch order")])
    assert len(out) == 1
    assert out[0].category == TxCategory.PERSONAL
