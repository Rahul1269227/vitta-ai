from __future__ import annotations

import re

from sentinelfi.domain.models import ClassifiedTransaction, NormalizedTransaction, TxCategory
from sentinelfi.services.taxonomy_service import TaxonomyService

_MCC_TEXT_PATTERN = re.compile(r"\b(?:mcc[:\s]*)?(\d{4})\b", re.IGNORECASE)

_BUSINESS_MCC = {
    "4814",  # telecom/internet
    "4816",  # computer network services
    "5732",  # electronics stores
    "5734",  # computer software stores
    "7372",  # computer programming/integrated systems
    "7379",  # computer maintenance and repair
    "7392",  # management/consulting
    "7399",  # business services
    "8111",  # legal services
    "8742",  # management consulting
    "8999",  # professional services
}

_PERSONAL_MCC = {
    "5411",  # groceries
    "5541",  # fuel
    "5542",  # fuel dispenser
    "5812",  # restaurants
    "5814",  # fast food
    "5912",  # pharmacy
    "7832",  # movie theaters
    "7995",  # betting and leisure
}


class MCCClassifier:
    """
    Deterministic classifier for transactions carrying MCC code.
    Used as an early-exit path to reduce downstream model cost.
    """

    def __init__(self, taxonomy: TaxonomyService | None = None):
        self.taxonomy = taxonomy

    def classify(
        self,
        txs: list[NormalizedTransaction],
    ) -> tuple[list[ClassifiedTransaction], list[NormalizedTransaction]]:
        classified: list[ClassifiedTransaction] = []
        unresolved: list[NormalizedTransaction] = []

        for tx in txs:
            mcc = self._extract_mcc(tx)
            if mcc is None:
                unresolved.append(tx)
                continue

            if mcc in _BUSINESS_MCC:
                classified.append(
                    ClassifiedTransaction(
                        **tx.model_dump(),
                        category=TxCategory.BUSINESS,
                        confidence=0.92,
                        classifier="mcc",
                        explanations=[f"mcc:{mcc}", "deterministic_business_mcc"],
                    )
                )
                continue

            if mcc in _PERSONAL_MCC:
                classified.append(
                    ClassifiedTransaction(
                        **tx.model_dump(),
                        category=TxCategory.PERSONAL,
                        confidence=0.9,
                        classifier="mcc",
                        explanations=[f"mcc:{mcc}", "deterministic_personal_mcc"],
                    )
                )
                continue

            taxonomy_category = self.taxonomy.category_for_mcc(mcc) if self.taxonomy else None
            if taxonomy_category:
                propensity = self.taxonomy.business_score_for_category(taxonomy_category)
                if propensity >= 0.65:
                    classified.append(
                        ClassifiedTransaction(
                            **tx.model_dump(),
                            category=TxCategory.BUSINESS,
                            confidence=0.88,
                            classifier="mcc",
                            explanations=[f"mcc:{mcc}", f"taxonomy_category:{taxonomy_category}"],
                        )
                    )
                    continue

                if propensity <= 0.35:
                    classified.append(
                        ClassifiedTransaction(
                            **tx.model_dump(),
                            category=TxCategory.PERSONAL,
                            confidence=0.86,
                            classifier="mcc",
                            explanations=[f"mcc:{mcc}", f"taxonomy_category:{taxonomy_category}"],
                        )
                    )
                    continue

            unresolved.append(tx)

        return classified, unresolved

    def _extract_mcc(self, tx: NormalizedTransaction) -> str | None:
        metadata_value = tx.metadata.get("mcc") if tx.metadata else None
        if metadata_value:
            cleaned = str(metadata_value).strip()
            if cleaned.isdigit() and len(cleaned) == 4:
                return cleaned

        match = _MCC_TEXT_PATTERN.search(tx.pii_redacted_description)
        if match:
            return match.group(1)

        return None
