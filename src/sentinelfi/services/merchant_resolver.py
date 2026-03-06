"""Merchant gazetteer resolver – fuzzy-matches transaction text against a
known-merchant CSV (ported from transaction-ai, adapted for VittaAI).

The resolver supports four match strategies executed in order:
  1. Exact alias match (1.0 confidence)
  2. Substring / word-level match (0.85)
  3. SequenceMatcher fuzzy match (threshold-based)
  4. Trigram Jaccard similarity (threshold-based)
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from sentinelfi.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class MerchantInfo:
    merchant_id: str
    canonical_name: str
    aliases: list[str]
    category: str
    subcategory: str | None = None


@dataclass
class MerchantMatch:
    merchant_id: str
    canonical_name: str
    category: str
    subcategory: str | None
    similarity_score: float
    match_type: str  # exact | substring | alias | trigram


class MerchantResolver:
    """Load a merchant gazetteer CSV and resolve transaction text to a known merchant."""

    def __init__(self, gazetteer_path: str | Path | None = None) -> None:
        self.merchants: dict[str, MerchantInfo] = {}
        self.alias_to_merchant: dict[str, str] = {}  # UPPERCASE alias → merchant_id
        self._trigram_index: dict[str, list[str]] = {}

        if gazetteer_path:
            self.load(gazetteer_path)

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load(self, path: str | Path) -> None:
        gazetteer_file = Path(path)
        if not gazetteer_file.exists():
            log.warning("merchant_gazetteer_not_found", path=str(path))
            return

        with open(gazetteer_file, encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                mid = row["merchant_id"]
                canonical = row["canonical_name"].upper()
                aliases = [a.strip().upper() for a in row["aliases"].split(",") if a.strip()]
                category = row["category"]
                subcategory = row.get("subcategory") or None

                info = MerchantInfo(
                    merchant_id=mid,
                    canonical_name=canonical,
                    aliases=aliases,
                    category=category,
                    subcategory=subcategory,
                )
                self.merchants[mid] = info

                self.alias_to_merchant[canonical] = mid
                for alias in aliases:
                    self.alias_to_merchant[alias] = mid

                self._index_trigrams(canonical, mid)
                for alias in aliases:
                    self._index_trigrams(alias, mid)

        log.info("merchant_gazetteer_loaded", count=len(self.merchants))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(
        self,
        text: str,
        threshold: float = 0.70,
        top_k: int = 3,
    ) -> list[MerchantMatch]:
        """Resolve *text* against the gazetteer returning up to *top_k* matches."""
        if not text:
            return []

        cleaned = self._clean(text)

        # Strategy 1: exact alias match
        exact = self._exact_match(cleaned)
        if exact:
            return [exact]

        matches: list[MerchantMatch] = []

        # Strategy 2: fuzzy alias (SequenceMatcher)
        matches.extend(self._fuzzy_alias_match(cleaned, threshold))

        # Strategy 3: trigram Jaccard
        matches.extend(self._trigram_match(cleaned, threshold))

        # Dedup + sort
        best: dict[str, MerchantMatch] = {}
        for m in matches:
            if m.merchant_id not in best or m.similarity_score > best[m.merchant_id].similarity_score:
                best[m.merchant_id] = m

        return sorted(best.values(), key=lambda m: m.similarity_score, reverse=True)[:top_k]

    def search(self, query: str, limit: int = 5) -> list[MerchantMatch]:
        """Convenience wrapper with a lower threshold for search-style usage."""
        return self.resolve(query, threshold=0.50, top_k=limit)

    # ------------------------------------------------------------------
    # Match strategies
    # ------------------------------------------------------------------

    def _exact_match(self, text: str) -> MerchantMatch | None:
        upper = text.upper()
        if upper in self.alias_to_merchant:
            return self._build_match(self.alias_to_merchant[upper], 1.0, "exact")

        # Substring / word-level match
        for alias, mid in self.alias_to_merchant.items():
            if "*" in alias or len(alias) < 4:
                continue
            if alias in upper or upper in alias:
                words = upper.split()
                if alias in words or any(alias in w for w in words):
                    return self._build_match(mid, 0.85, "substring")
        return None

    def _fuzzy_alias_match(self, text: str, threshold: float) -> list[MerchantMatch]:
        upper = text.upper()
        results: list[MerchantMatch] = []
        for alias, mid in self.alias_to_merchant.items():
            sim = SequenceMatcher(None, upper, alias).ratio()
            if sim >= threshold:
                results.append(self._build_match(mid, sim, "alias"))
        return results

    def _trigram_match(self, text: str, threshold: float) -> list[MerchantMatch]:
        query_trigrams = self._get_trigrams(text.upper())
        candidates: set[str] = set()
        for tri in query_trigrams:
            candidates.update(self._trigram_index.get(tri, []))

        results: list[MerchantMatch] = []
        for mid in candidates:
            info = self.merchants[mid]
            best_sim = 0.0
            for name in [info.canonical_name, *info.aliases]:
                sim = self._jaccard(text.upper(), name)
                best_sim = max(best_sim, sim)
            if best_sim >= threshold:
                results.append(self._build_match(mid, best_sim, "trigram"))
        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_match(self, mid: str, score: float, match_type: str) -> MerchantMatch:
        info = self.merchants[mid]
        return MerchantMatch(
            merchant_id=mid,
            canonical_name=info.canonical_name,
            category=info.category,
            subcategory=info.subcategory,
            similarity_score=score,
            match_type=match_type,
        )

    @staticmethod
    def _clean(text: str) -> str:
        text = text.upper()
        text = re.sub(r"\*PAY|\*PAYMENT|-PAY|-PAYMENT", "", text)
        text = re.sub(r"INTL TRX ", "", text)
        text = re.sub(r"[*\-/.]+", " ", text)
        return " ".join(text.split()).strip()

    # Trigram helpers -------------------------------------------------------

    def _index_trigrams(self, text: str, mid: str) -> None:
        for tri in self._get_trigrams(text):
            self._trigram_index.setdefault(tri, [])
            if mid not in self._trigram_index[tri]:
                self._trigram_index[tri].append(mid)

    @staticmethod
    def _get_trigrams(text: str) -> list[str]:
        text = re.sub(r"\s+", "", text)
        if len(text) < 3:
            return [text]
        return [text[i : i + 3] for i in range(len(text) - 2)]

    def _jaccard(self, a: str, b: str) -> float:
        sa = set(self._get_trigrams(a))
        sb = set(self._get_trigrams(b))
        if not sa or not sb:
            return 0.0
        return len(sa & sb) / len(sa | sb)
