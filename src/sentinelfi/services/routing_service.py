from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from sentinelfi.domain.models import NormalizedTransaction
from sentinelfi.services.signal_defaults import SIMPLE_MERCHANTS, UPI_FAST_PATH_MERCHANTS
from sentinelfi.services.taxonomy_service import TaxonomyService


@dataclass
class RouteDecision:
    tx: NormalizedTransaction
    route: str
    score: float
    reason: str


class EmbeddingRouter:
    def __init__(
        self,
        model_name: str = "BAAI/bge-m3",
        enable_local_embeddings: bool = True,
        taxonomy: TaxonomyService | None = None,
    ):
        self.model_name = model_name
        self.enable_local_embeddings = enable_local_embeddings
        self.taxonomy = taxonomy
        if taxonomy:
            self.simple_merchants = taxonomy.signal_keywords(
                "simple_merchants",
                default=SIMPLE_MERCHANTS,
            )
            self.upi_fast_path_merchants = taxonomy.signal_keywords(
                "upi_fast_path_merchants",
                default=UPI_FAST_PATH_MERCHANTS,
            )
        else:
            self.simple_merchants = set(SIMPLE_MERCHANTS)
            self.upi_fast_path_merchants = set(UPI_FAST_PATH_MERCHANTS)
        self._encoder = None

    def _load_encoder(self):
        if not self.enable_local_embeddings:
            return None
        if self._encoder is not None:
            return self._encoder
        try:
            from sentence_transformers import SentenceTransformer

            self._encoder = SentenceTransformer(self.model_name)
            return self._encoder
        except Exception:
            return None

    @lru_cache(maxsize=1)
    def _simple_centroid(self) -> np.ndarray | None:
        encoder = self._load_encoder()
        if encoder is None:
            return None
        vectors = encoder.encode(list(self.simple_merchants), normalize_embeddings=True)
        return np.mean(vectors, axis=0)

    def route(self, txs: list[NormalizedTransaction]) -> tuple[list[NormalizedTransaction], list[NormalizedTransaction], list[RouteDecision]]:
        slm: list[NormalizedTransaction] = []
        llm: list[NormalizedTransaction] = []
        decisions: list[RouteDecision] = []

        pending: list[NormalizedTransaction] = []
        for tx in txs:
            route = self._route_by_upi_signals(tx)
            if route is None:
                route = self._route_by_taxonomy_signals(tx)
            if route is None:
                pending.append(tx)
                continue
            if route.route == "slm":
                slm.append(tx)
            else:
                llm.append(tx)
            decisions.append(route)

        txs = pending

        if not txs:
            return slm, llm, decisions

        encoder = self._load_encoder()
        centroid = self._simple_centroid()

        if encoder is not None and centroid is not None:
            descs = [t.pii_redacted_description for t in txs]
            vectors = encoder.encode(descs, normalize_embeddings=True)
            scores = vectors @ centroid
            for tx, score in zip(txs, scores.tolist()):
                token_count = len(tx.pii_redacted_description.split())
                if score > 0.44 and token_count <= 8:
                    slm.append(tx)
                    decisions.append(RouteDecision(tx=tx, route="slm", score=float(score), reason="embedding-simple-merchant"))
                else:
                    llm.append(tx)
                    decisions.append(RouteDecision(tx=tx, route="llm", score=float(score), reason="embedding-complex"))
            return slm, llm, decisions

        for tx in txs:
            text = tx.pii_redacted_description
            token_count = len(text.split())
            has_simple = any(m in text for m in self.simple_merchants)
            has_noise = any(char.isdigit() for char in text) and "upi" in text
            if has_simple and token_count <= 7 and not has_noise:
                slm.append(tx)
                decisions.append(RouteDecision(tx=tx, route="slm", score=0.7, reason="heuristic-simple"))
            else:
                llm.append(tx)
                decisions.append(RouteDecision(tx=tx, route="llm", score=0.3, reason="heuristic-complex"))

        return slm, llm, decisions

    def _route_by_upi_signals(self, tx: NormalizedTransaction) -> RouteDecision | None:
        upi = tx.metadata.get("upi") if tx.metadata else None
        if not isinstance(upi, dict) or not upi.get("is_upi"):
            return None

        merchant_token = str(upi.get("merchant_token") or "")
        if upi.get("p2p_likely"):
            return RouteDecision(tx=tx, route="slm", score=0.88, reason="upi-p2p-fast-path")

        if merchant_token and merchant_token in self.upi_fast_path_merchants:
            return RouteDecision(tx=tx, route="slm", score=0.9, reason="upi-known-merchant-fast-path")

        if merchant_token:
            return RouteDecision(tx=tx, route="llm", score=0.4, reason="upi-merchant-complex")

        return RouteDecision(tx=tx, route="llm", score=0.35, reason="upi-unknown-handle")

    def _route_by_taxonomy_signals(self, tx: NormalizedTransaction) -> RouteDecision | None:
        if self.taxonomy is None:
            return None

        matched = self.taxonomy.match_category(tx.pii_redacted_description)
        if matched is None:
            return None

        category_id, score, _keywords = matched
        propensity = self.taxonomy.business_score_for_category(category_id)
        token_count = len(tx.pii_redacted_description.split())
        if score >= 0.45 and token_count <= 10:
            return RouteDecision(tx=tx, route="slm", score=score, reason=f"taxonomy-fast-path:{category_id}")

        if propensity >= 0.85 and score >= 0.35:
            return RouteDecision(tx=tx, route="slm", score=score, reason=f"taxonomy-high-business-signal:{category_id}")

        return None
