from __future__ import annotations

import numpy as np

from sentinelfi.domain.models import ClassifiedTransaction, NormalizedTransaction, TxCategory
from sentinelfi.services.signal_defaults import (
    SLM_BUSINESS_KEYWORDS,
    SLM_PERSONAL_KEYWORDS,
    SLM_UPI_BUSINESS_HINTS,
    SLM_UPI_PERSONAL_HINTS,
)
from sentinelfi.services.taxonomy_service import TaxonomyService


class RuleBasedTransactionClassifier:
    """
    Fast local classifier for high-volume easy transactions.

    Classification priority:
      1. Taxonomy match (primary) — uses category propensity to decide
      2. Keyword vote tallies (supplementary)
      3. Embedding centroid vote (tie-breaker when available)

    All text matching is case-insensitive.
    """

    def __init__(
        self,
        taxonomy: TaxonomyService | None = None,
        model_name: str = "BAAI/bge-m3",
        enable_local_model: bool = True,
    ):
        self.taxonomy = taxonomy
        self.model_name = model_name
        self.enable_local_model = enable_local_model
        self._encoder = None
        self._business_centroid: np.ndarray | None = None
        self._personal_centroid: np.ndarray | None = None

        if taxonomy:
            self.business_keywords = taxonomy.signal_keywords(
                "slm_business_keywords",
                default=SLM_BUSINESS_KEYWORDS,
            )
            self.personal_keywords = taxonomy.signal_keywords(
                "slm_personal_keywords",
                default=SLM_PERSONAL_KEYWORDS,
            )
            self.upi_business_hints = taxonomy.signal_keywords(
                "slm_upi_business_hints",
                default=SLM_UPI_BUSINESS_HINTS,
            )
            self.upi_personal_hints = taxonomy.signal_keywords(
                "slm_upi_personal_hints",
                default=SLM_UPI_PERSONAL_HINTS,
            )
        else:
            self.business_keywords = set(SLM_BUSINESS_KEYWORDS)
            self.personal_keywords = set(SLM_PERSONAL_KEYWORDS)
            self.upi_business_hints = set(SLM_UPI_BUSINESS_HINTS)
            self.upi_personal_hints = set(SLM_UPI_PERSONAL_HINTS)

    def _load_encoder(self):
        if not self.enable_local_model:
            return None
        if self._encoder is not None:
            return self._encoder
        try:
            from sentence_transformers import SentenceTransformer

            self._encoder = SentenceTransformer(self.model_name)
            return self._encoder
        except Exception:
            return None

    def _build_centroids(self) -> tuple[np.ndarray, np.ndarray] | None:
        if self._business_centroid is not None and self._personal_centroid is not None:
            return self._business_centroid, self._personal_centroid

        encoder = self._load_encoder()
        if encoder is None:
            return None

        business_anchors = sorted(self.business_keywords | self.upi_business_hints)
        personal_anchors = sorted(self.personal_keywords | self.upi_personal_hints)
        if not business_anchors or not personal_anchors:
            return None

        business_vecs = np.array(encoder.encode(business_anchors, normalize_embeddings=True), dtype=float)
        personal_vecs = np.array(encoder.encode(personal_anchors, normalize_embeddings=True), dtype=float)
        self._business_centroid = business_vecs.mean(axis=0)
        self._personal_centroid = personal_vecs.mean(axis=0)
        return self._business_centroid, self._personal_centroid

    def _local_model_vote(self, text: str) -> tuple[TxCategory, float, str] | None:
        centroids = self._build_centroids()
        if centroids is None:
            return None

        encoder = self._load_encoder()
        if encoder is None:
            return None

        business_centroid, personal_centroid = centroids
        vector = np.array(encoder.encode([text], normalize_embeddings=True), dtype=float)[0]
        b_score = float(vector @ business_centroid)
        p_score = float(vector @ personal_centroid)
        margin = abs(b_score - p_score)
        if margin < 0.03:
            return None

        category = TxCategory.BUSINESS if b_score > p_score else TxCategory.PERSONAL
        confidence = min(0.95, 0.6 + min(0.3, margin * 2.0))
        reason = f"local_embedding_vote:b={b_score:.3f}:p={p_score:.3f}"
        return category, float(confidence), reason

    def classify(self, txs: list[NormalizedTransaction]) -> list[ClassifiedTransaction]:
        result: list[ClassifiedTransaction] = []
        for tx in txs:
            text_lower = tx.pii_redacted_description.lower()
            explanations: list[str] = []

            # ── 1. Taxonomy match (primary signal) ────────────────────────
            taxonomy_category: TxCategory | None = None
            taxonomy_confidence = 0.0
            taxonomy_propensity: float | None = None

            if self.taxonomy:
                matched = self.taxonomy.match_category(text_lower)
                if matched:
                    category_id, score, matched_keywords = matched
                    taxonomy_propensity = self.taxonomy.business_score_for_category(category_id)
                    explanations.append(
                        f"taxonomy_match:{category_id}:{','.join(matched_keywords[:3])}:prop={taxonomy_propensity:.2f}"
                    )

                    if taxonomy_propensity >= 0.65:
                        taxonomy_category = TxCategory.BUSINESS
                        taxonomy_confidence = min(0.95, 0.55 + score * 0.35 + (taxonomy_propensity - 0.5) * 0.3)
                    elif taxonomy_propensity <= 0.35:
                        taxonomy_category = TxCategory.PERSONAL
                        taxonomy_confidence = min(0.95, 0.55 + score * 0.35 + (0.5 - taxonomy_propensity) * 0.3)
                    else:
                        # Ambiguous zone — taxonomy matched but propensity is neutral
                        # Still record it; keyword/embedding votes will decide
                        explanations.append(f"taxonomy_ambiguous_propensity:{taxonomy_propensity:.2f}")

            # ── 2. Keyword vote tallies (case-insensitive) ────────────────
            business_hits = sum(1 for word in self.business_keywords if word in text_lower)
            personal_hits = sum(1 for word in self.personal_keywords if word in text_lower)

            # ── 3. UPI signal boosts ──────────────────────────────────────
            upi = tx.metadata.get("upi") if tx.metadata else None
            if isinstance(upi, dict) and upi.get("is_upi"):
                token = str(upi.get("merchant_token") or "")
                if token in self.upi_business_hints:
                    business_hits += 2
                    explanations.append(f"upi_business_hint:{token}")
                elif token in self.upi_personal_hints:
                    personal_hits += 2
                    explanations.append(f"upi_personal_hint:{token}")
                elif upi.get("p2p_likely"):
                    personal_hits += 1
                    explanations.append("upi_p2p_transfer_hint")

            # ── 4. Taxonomy boosts keyword tallies ────────────────────────
            if taxonomy_propensity is not None:
                if taxonomy_propensity >= 0.55:
                    boost = max(2, int(round((taxonomy_propensity - 0.5) * 10)))
                    business_hits += boost
                    explanations.append(f"taxonomy_business_boost:+{boost}")
                elif taxonomy_propensity <= 0.45:
                    boost = max(2, int(round((0.5 - taxonomy_propensity) * 10)))
                    personal_hits += boost
                    explanations.append(f"taxonomy_personal_boost:+{boost}")

            # ── 5. Embedding vote (supplementary) ─────────────────────────
            local_vote = self._local_model_vote(text_lower)
            local_category: TxCategory | None = None
            local_confidence = 0.0
            if local_vote is not None:
                local_category, local_confidence, local_reason = local_vote
                explanations.append(local_reason)
                if local_category == TxCategory.BUSINESS:
                    business_hits += 2
                elif local_category == TxCategory.PERSONAL:
                    personal_hits += 2

            # ── 6. Final decision ─────────────────────────────────────────
            # Strong taxonomy match takes priority
            if taxonomy_category is not None and taxonomy_confidence >= 0.70:
                category = taxonomy_category
                confidence = taxonomy_confidence
                explanations.append(f"decided_by_taxonomy:conf={confidence:.3f}")
            elif business_hits > personal_hits:
                category = TxCategory.BUSINESS
                confidence = min(0.95, 0.6 + 0.06 * business_hits)
                explanations.append(f"business_keyword_hits:{business_hits}")
                if local_category == TxCategory.BUSINESS:
                    confidence = max(confidence, local_confidence)
                if taxonomy_category == TxCategory.BUSINESS:
                    confidence = max(confidence, taxonomy_confidence)
            elif personal_hits > business_hits:
                category = TxCategory.PERSONAL
                confidence = min(0.95, 0.6 + 0.06 * personal_hits)
                explanations.append(f"personal_keyword_hits:{personal_hits}")
                if local_category == TxCategory.PERSONAL:
                    confidence = max(confidence, local_confidence)
                if taxonomy_category == TxCategory.PERSONAL:
                    confidence = max(confidence, taxonomy_confidence)
            else:
                # Tie — use taxonomy or embedding as tie-breakers
                if taxonomy_category is not None:
                    category = taxonomy_category
                    confidence = max(taxonomy_confidence, 0.55)
                    explanations.append("resolved_by_taxonomy_propensity")
                elif local_vote is not None and local_category is not None:
                    category = local_category
                    confidence = local_confidence
                    explanations.append("resolved_by_local_embedding_vote")
                else:
                    category = TxCategory.UNKNOWN
                    confidence = 0.45
                    explanations.append("insufficient_signal")

            result.append(
                ClassifiedTransaction(
                    **tx.model_dump(),
                    category=category,
                    confidence=float(confidence),
                    classifier="slm",
                    explanations=explanations,
                )
            )
        return result
