from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class TaxonomyCategory:
    category_id: str
    name: str
    keywords: set[str] = field(default_factory=set)
    mcc_codes: set[str] = field(default_factory=set)


_DEFAULT_BUSINESS_PROPENSITY: dict[str, float] = {
    "food_dining": 0.15,
    "groceries": 0.1,
    "transport": 0.3,
    "travel": 0.45,
    "fuel": 0.45,
    "rent": 0.55,
    "shopping": 0.25,
    "entertainment": 0.1,
    "health": 0.25,
    "education": 0.3,
    "fees_charges": 0.8,
    "income_salary": 0.65,
    "transfers_upi": 0.4,
    "atm_cash": 0.35,
    "investments": 0.6,
    "bills": 0.7,
    "fraud_security": 0.5,
    "insurance": 0.55,
    "charity_donations": 0.45,
    "personal_care": 0.1,
    "pets": 0.1,
    "home_improvement": 0.45,
    "automotive": 0.45,
    "taxes_government": 0.85,
    "electronics_technology": 0.75,
    "professional_services": 0.9,
    "kids_family": 0.1,
    "subscriptions_memberships": 0.75,
    "gifts_occasions": 0.25,
    "other": 0.5,
}


class TaxonomyService:
    def __init__(self, base_path: str | None = None, overrides_path: str | None = None):
        self.base_path = Path(base_path) if base_path else Path("data/taxonomy_base.yaml")
        self.overrides_path = Path(overrides_path) if overrides_path else Path("data/taxonomy_overrides.yaml")

        self.categories: dict[str, TaxonomyCategory] = {}
        self.mcc_to_category: dict[str, str] = {}
        self.business_propensity: dict[str, float] = dict(_DEFAULT_BUSINESS_PROPENSITY)
        self.signal_groups: dict[str, set[str]] = {}

        self._load_base()
        self._load_overrides()

    def _load_base(self) -> None:
        if not self.base_path.exists():
            return

        data = self._read_yaml(self.base_path)
        for raw in data.get("categories", []):
            category_id = str(raw.get("id", "")).strip().lower()
            if not category_id:
                continue

            category = TaxonomyCategory(
                category_id=category_id,
                name=str(raw.get("name", category_id)).strip(),
                keywords={str(k).strip().lower() for k in raw.get("keywords", []) if str(k).strip()},
                mcc_codes={str(m).strip() for m in raw.get("mcc_codes", []) if str(m).strip()},
            )
            self.categories[category_id] = category
            for mcc in category.mcc_codes:
                self.mcc_to_category[mcc] = category_id

    def _load_overrides(self) -> None:
        if not self.overrides_path.exists():
            return

        data = self._read_yaml(self.overrides_path)

        keyword_overrides: dict[str, list[str]] = data.get("keyword_overrides", {})
        for category_id, terms in keyword_overrides.items():
            key = str(category_id).strip().lower()
            category = self.categories.get(key)
            if category is None:
                category = TaxonomyCategory(category_id=key, name=key)
                self.categories[key] = category
            for term in terms:
                cleaned = str(term).strip().lower()
                if cleaned:
                    category.keywords.add(cleaned)

        mcc_overrides: dict[str, str] = data.get("mcc_overrides", {})
        for mcc, category_id in mcc_overrides.items():
            self.mcc_to_category[str(mcc).strip()] = str(category_id).strip().lower()

        propensity_overrides: dict[str, float] = data.get("business_propensity_overrides", {})
        for category_id, score in propensity_overrides.items():
            key = str(category_id).strip().lower()
            try:
                self.business_propensity[key] = max(0.0, min(1.0, float(score)))
            except (TypeError, ValueError):
                continue

        signal_groups: dict[str, list[str]] = data.get("signal_groups", {})
        for group_name, terms in signal_groups.items():
            key = str(group_name).strip().lower()
            if not key:
                continue
            values = {str(term).strip().lower() for term in terms if str(term).strip()}
            if values:
                self.signal_groups[key] = values

    def category_for_mcc(self, mcc: str | None) -> str | None:
        if not mcc:
            return None
        return self.mcc_to_category.get(str(mcc).strip())

    def business_score_for_category(self, category_id: str | None) -> float:
        if not category_id:
            return 0.5
        return self.business_propensity.get(category_id, 0.5)

    def match_category(self, text: str) -> tuple[str, float, list[str]] | None:
        lower = text.lower()
        best_category: str | None = None
        best_matches: list[str] = []
        best_score = 0.0

        for category_id, category in self.categories.items():
            matches = [kw for kw in category.keywords if kw and kw in lower]
            if not matches:
                continue

            unique_count = len(set(matches))
            density = unique_count / max(1, min(8, len(lower.split())))
            score = min(1.0, 0.25 + density)

            if score > best_score:
                best_score = score
                best_category = category_id
                best_matches = sorted(set(matches))[:6]

        if best_category is None:
            return None
        return best_category, best_score, best_matches

    def has_category(self, category_id: str) -> bool:
        return category_id.lower() in self.categories

    def signal_keywords(self, group_name: str, default: set[str] | None = None) -> set[str]:
        key = group_name.strip().lower()
        values = self.signal_groups.get(key)
        if values:
            return set(values)
        return set(default or set())

    def _read_yaml(self, path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if not isinstance(data, dict):
            return {}
        return data
