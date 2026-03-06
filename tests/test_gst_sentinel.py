from __future__ import annotations

from datetime import date

from sentinelfi.agents.gst_sentinel import GstSentinel
from sentinelfi.domain.models import ClassifiedTransaction, TxCategory
from sentinelfi.services.taxonomy_service import TaxonomyService


def _tx(description: str) -> ClassifiedTransaction:
    return ClassifiedTransaction(
        tx_id="tx-1",
        tx_date=date(2026, 1, 1),
        description=description,
        normalized_description=description.lower(),
        pii_redacted_description=description.lower(),
        amount=1000.0,
        currency="INR",
        is_debit=True,
        category=TxCategory.BUSINESS,
        confidence=0.92,
        classifier="ml",
        metadata={},
    )


def test_gst_sentinel_uses_taxonomy_for_itc_likelihood() -> None:
    taxonomy = TaxonomyService(base_path="data/taxonomy_base.yaml", overrides_path="data/taxonomy_overrides.yaml")
    sentinel = GstSentinel(taxonomy=taxonomy, business_propensity_threshold=0.65)

    findings = sentinel.analyze([_tx("AWS cloud hosting monthly charge")])
    assert findings
    assert findings[0].likely_itc_eligible is True
    assert findings[0].has_gst_invoice is False


def test_gst_sentinel_detects_invoice_tokens() -> None:
    taxonomy = TaxonomyService(base_path="data/taxonomy_base.yaml", overrides_path="data/taxonomy_overrides.yaml")
    sentinel = GstSentinel(taxonomy=taxonomy)

    findings = sentinel.analyze([_tx("professional fee gst invoice no 12345")])
    assert findings
    assert findings[0].has_gst_invoice is True
