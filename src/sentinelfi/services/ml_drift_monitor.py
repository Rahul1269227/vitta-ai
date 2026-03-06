from __future__ import annotations

from collections import deque
from pathlib import Path
from threading import Lock
from typing import Any

import joblib
import numpy as np

from sentinelfi.domain.models import ClassifiedTransaction, TxCategory


class MLDriftMonitor:
    def __init__(
        self,
        model_path: str,
        window: int = 1_000,
        z_warning: float = 2.5,
        z_critical: float = 4.0,
        psi_warning: float = 0.2,
        psi_critical: float = 0.35,
        business_rate_warning: float = 0.15,
        business_rate_critical: float = 0.25,
    ):
        self.model_path = Path(model_path)
        self.window = window
        self.z_warning = z_warning
        self.z_critical = z_critical
        self.psi_warning = psi_warning
        self.psi_critical = psi_critical
        self.business_rate_warning = business_rate_warning
        self.business_rate_critical = business_rate_critical

        self.confidences: deque[float] = deque(maxlen=window)
        self.business_flags: deque[int] = deque(maxlen=window)
        self.text_token_lengths: deque[int] = deque(maxlen=window)
        self.lock = Lock()

        self.baseline: dict[str, Any] | None = None
        self.refresh_baseline()

    def refresh_baseline(self) -> None:
        if not self.model_path.exists():
            self.baseline = None
            return

        payload = joblib.load(self.model_path)
        metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
        baseline = metadata.get("drift_baseline") if isinstance(metadata, dict) else None
        self.baseline = baseline if isinstance(baseline, dict) else None

    def record(self, transactions: list[ClassifiedTransaction]) -> None:
        rows = [tx for tx in transactions if tx.classifier == "ml"]
        if not rows:
            return

        with self.lock:
            for tx in rows:
                self.confidences.append(float(tx.confidence))
                self.business_flags.append(1 if tx.category == TxCategory.BUSINESS else 0)
                self.text_token_lengths.append(len(tx.pii_redacted_description.split()))

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            sample_count = len(self.confidences)
            if sample_count == 0:
                return {
                    "ml_samples": 0.0,
                    "ml_drift_status": "unknown",
                    "ml_confidence_shift_z": 0.0,
                    "ml_business_rate_delta": 0.0,
                    "ml_text_token_shift_z": 0.0,
                    "ml_confidence_psi": 0.0,
                }

            conf = np.array(self.confidences, dtype=float)
            business = np.array(self.business_flags, dtype=float)
            token_len = np.array(self.text_token_lengths, dtype=float)

            confidence_mean = float(conf.mean())
            business_rate = float(business.mean())
            token_mean = float(token_len.mean())

            baseline = self.baseline or {}
            conf_z = self._z_shift(
                current=confidence_mean,
                baseline_mean=float(baseline.get("confidence_mean", confidence_mean)),
                baseline_std=float(baseline.get("confidence_std", 0.0)),
            )
            token_z = self._z_shift(
                current=token_mean,
                baseline_mean=float(baseline.get("text_token_mean", token_mean)),
                baseline_std=float(baseline.get("text_token_std", 0.0)),
            )
            business_delta = abs(
                business_rate - float(baseline.get("business_rate", business_rate))
            )
            psi = self._confidence_psi(
                current_confidences=conf,
                baseline_hist=baseline.get("confidence_histogram"),
            )
            status = self._status(conf_z=conf_z, token_z=token_z, business_delta=business_delta, psi=psi)

            return {
                "ml_samples": float(sample_count),
                "ml_drift_status": status,
                "ml_confidence_shift_z": conf_z,
                "ml_business_rate_delta": business_delta,
                "ml_text_token_shift_z": token_z,
                "ml_confidence_psi": psi,
            }

    def _z_shift(self, current: float, baseline_mean: float, baseline_std: float) -> float:
        if baseline_std <= 1e-6:
            return 0.0
        return abs((current - baseline_mean) / baseline_std)

    def _confidence_psi(self, current_confidences: np.ndarray, baseline_hist: Any) -> float:
        if len(current_confidences) < 30:
            return 0.0
        if not isinstance(baseline_hist, list) or not baseline_hist:
            return 0.0

        baseline = np.array([float(item) for item in baseline_hist], dtype=float)
        if baseline.sum() <= 0:
            return 0.0
        baseline = baseline / baseline.sum()

        current_hist, _ = np.histogram(current_confidences, bins=np.linspace(0.0, 1.0, len(baseline) + 1))
        current = current_hist.astype(float)
        if current.sum() <= 0:
            return 0.0
        current = current / current.sum()

        eps = 1e-6
        current = np.clip(current, eps, 1.0)
        baseline = np.clip(baseline, eps, 1.0)
        return float(np.sum((current - baseline) * np.log(current / baseline)))

    def _status(self, conf_z: float, token_z: float, business_delta: float, psi: float) -> str:
        if (
            conf_z >= self.z_critical
            or token_z >= self.z_critical
            or psi >= self.psi_critical
            or business_delta >= self.business_rate_critical
        ):
            return "critical"

        if (
            conf_z >= self.z_warning
            or token_z >= self.z_warning
            or psi >= self.psi_warning
            or business_delta >= self.business_rate_warning
        ):
            return "warning"

        return "stable"
