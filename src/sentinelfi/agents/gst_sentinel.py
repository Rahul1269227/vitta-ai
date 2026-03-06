from __future__ import annotations

import uuid

from sentinelfi.domain.models import ClassifiedTransaction, GstFinding, TxCategory
from sentinelfi.services.taxonomy_service import TaxonomyService


class GstSentinel:
    """
    Compliance specialist for India GST checks.
    """

    def __init__(
        self,
        taxonomy: TaxonomyService | None = None,
        business_propensity_threshold: float = 0.65,
    ) -> None:
        self.taxonomy = taxonomy
        self.business_propensity_threshold = business_propensity_threshold
        self.invoice_tokens = {
            "gstin",
            "tax invoice",
            "gst invoice",
            "invoice no",
            "invoice #",
        }

    def analyze(self, txs: list[ClassifiedTransaction]) -> list[GstFinding]:
        findings: list[GstFinding] = []
        for tx in txs:
            if tx.category != TxCategory.BUSINESS or not tx.is_debit:
                continue

            desc = tx.normalized_description.lower()
            matched = self.taxonomy.match_category(desc) if self.taxonomy else None
            likely_billable = False
            if matched and self.taxonomy:
                category_id, score, _ = matched
                propensity = self.taxonomy.business_score_for_category(category_id)
                likely_billable = propensity >= self.business_propensity_threshold and score >= 0.3
            else:
                likely_billable = any(
                    token in desc
                    for token in ["software", "license", "consulting", "invoice", "hosting", "agency", "ads"]
                )

            has_gst_invoice = any(token in desc for token in self.invoice_tokens)

            if likely_billable and not has_gst_invoice:
                potential_itc = round(tx.amount * 0.18, 2)
                findings.append(
                    GstFinding(
                        finding_id=f"gst-{uuid.uuid4().hex[:10]}",
                        tx_id=tx.tx_id,
                        has_gst_invoice=False,
                        likely_itc_eligible=True,
                        issue="Possible missing GST invoice for business expense",
                        potential_itc_amount=potential_itc,
                    )
                )
            elif likely_billable and has_gst_invoice:
                findings.append(
                    GstFinding(
                        finding_id=f"gst-{uuid.uuid4().hex[:10]}",
                        tx_id=tx.tx_id,
                        has_gst_invoice=True,
                        likely_itc_eligible=True,
                        issue="Invoice mentions GST; verify ITC claim mapping",
                        potential_itc_amount=round(tx.amount * 0.18, 2),
                    )
                )

        return findings
