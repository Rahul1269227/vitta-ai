from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import numpy as np

from sentinelfi.domain.models import ClassifiedTransaction, NormalizedTransaction, TxCategory
from sentinelfi.services.ml_features import build_ml_feature_text


class MLTransactionClassifier:
    """
    ML-first classifier for high-throughput categorization.

    Model artifact expects:
    - pipeline: sklearn pipeline exposing predict_proba
    - labels: list[str] class labels in training order
    """

    def __init__(self, model_path: str, enabled: bool = True):
        self.model_path = Path(model_path)
        self.enabled = enabled
        self.pipeline = None
        self.labels: list[str] = []
        self.metadata: dict[str, Any] = {}
        self.calibration: dict[str, Any] | None = None
        self.label_to_tx_category: dict[str, str] = {}

        if self.enabled:
            self._load_model()

    @property
    def available(self) -> bool:
        return self.pipeline is not None

    def classify(self, txs: list[NormalizedTransaction]) -> list[ClassifiedTransaction]:
        if not txs:
            return []
        if not self.available:
            return []

        assert self.pipeline is not None
        assert self.labels

        texts = [self._build_text(tx) for tx in txs]
        probs = np.array(self.pipeline.predict_proba(texts), dtype=float)
        business_probs = self._calibrated_business_probability(probs)

        out: list[ClassifiedTransaction] = []
        for idx, (tx, row) in enumerate(zip(txs, probs)):
            top_idx = int(row.argmax())
            top_label = self.labels[top_idx]

            mapped = self.label_to_tx_category.get(top_label)
            if mapped is None and top_label in {"business", "personal"}:
                mapped = top_label

            if mapped == "business":
                category = TxCategory.BUSINESS
                confidence = float(business_probs[idx])
            elif mapped == "personal":
                category = TxCategory.PERSONAL
                confidence = float(1.0 - business_probs[idx])
            else:
                category = TxCategory.UNKNOWN
                confidence = float(row[top_idx])

            taxonomy_category = top_label if not top_label.startswith("__fallback_") else None
            reason = f"ml_top_label:{top_label}"
            if mapped:
                reason = f"{reason}:{mapped}"
            out.append(
                ClassifiedTransaction(
                    **tx.model_dump(),
                    category=category,
                    taxonomy_category=taxonomy_category,
                    confidence=confidence,
                    classifier="ml",
                    explanations=[reason, "ml_classifier"],
                )
            )

        return out

    def _build_text(self, tx: NormalizedTransaction) -> str:
        return build_ml_feature_text(
            pii_redacted_description=tx.pii_redacted_description,
            merchant=tx.merchant,
            metadata=tx.metadata,
        )

    def _business_class_indices(self) -> list[int]:
        indices = [
            idx
            for idx, label in enumerate(self.labels)
            if self.label_to_tx_category.get(label) == "business"
        ]
        if not indices and "business" in self.labels:
            indices = [self.labels.index("business")]
        return indices

    def _aggregate_business_probability(self, probs: np.ndarray) -> np.ndarray:
        if probs.ndim != 2 or probs.shape[0] == 0:
            return np.array([], dtype=float)

        business_indices = self._business_class_indices()
        if not business_indices:
            return np.full((probs.shape[0],), 0.5, dtype=float)

        out = probs[:, business_indices].sum(axis=1)
        return np.clip(out, 1e-6, 1.0 - 1e-6)

    def _calibrated_business_probability(self, probs: np.ndarray) -> np.ndarray:
        business_probs = self._aggregate_business_probability(probs)
        if business_probs.size == 0:
            return business_probs

        calibrator = self.calibration or {}
        method = str(calibrator.get("method", "identity"))
        if method not in {"platt", "platt_business_aggregate"}:
            return business_probs

        coef = float(calibrator.get("coef", 1.0))
        intercept = float(calibrator.get("intercept", 0.0))
        logits = np.log(business_probs / (1.0 - business_probs))
        calibrated = 1.0 / (1.0 + np.exp(-(coef * logits + intercept)))
        return np.clip(calibrated, 1e-6, 1.0 - 1e-6)

    def _load_model(self) -> None:
        if not self.model_path.exists():
            return

        payload = joblib.load(self.model_path)
        pipeline = payload.get("pipeline") if isinstance(payload, dict) else None
        labels = payload.get("labels") if isinstance(payload, dict) else None
        if pipeline is None or not isinstance(labels, list) or not labels:
            return

        self.pipeline = pipeline
        self.labels = labels
        self.metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
        calibration = self.metadata.get("probability_calibration")
        self.calibration = calibration if isinstance(calibration, dict) else None
        raw_map = self.metadata.get("label_to_tx_category")
        if isinstance(raw_map, dict):
            self.label_to_tx_category = {
                str(key): str(value).lower() for key, value in raw_map.items() if str(value).strip()
            }
