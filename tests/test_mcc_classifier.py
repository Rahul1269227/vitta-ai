from __future__ import annotations

from datetime import date

from sentinelfi.agents.mcc_classifier import MCCClassifier
from sentinelfi.domain.models import NormalizedTransaction, TxCategory
from sentinelfi.services.taxonomy_service import TaxonomyService


def _tx(tx_id: str, desc: str, mcc: str | None) -> NormalizedTransaction:
    metadata = {"mcc": mcc} if mcc else {}
    return NormalizedTransaction(
        tx_id=tx_id,
        tx_date=date(2025, 1, 1),
        description=desc,
        amount=1200,
        normalized_description=desc.lower(),
        pii_redacted_description=desc.lower(),
        metadata=metadata,
    )


def test_mcc_classifier_early_exit() -> None:
    taxonomy = TaxonomyService(
        base_path="data/taxonomy_base.yaml",
        overrides_path="data/taxonomy_overrides.yaml",
    )
    classifier = MCCClassifier(taxonomy=taxonomy)
    txs = [
        _tx("b1", "software tools payment", "5734"),
        _tx("p1", "restaurant bill", "5812"),
        _tx("b2", "government tax payment", "9311"),
        _tx("u1", "unknown", None),
    ]

    classified, unresolved = classifier.classify(txs)
    by_id = {t.tx_id: t for t in classified}

    assert by_id["b1"].category == TxCategory.BUSINESS
    assert by_id["p1"].category == TxCategory.PERSONAL
    assert by_id["b2"].category == TxCategory.BUSINESS
    assert {t.tx_id for t in unresolved} == {"u1"}
