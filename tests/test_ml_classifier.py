from __future__ import annotations

from datetime import date

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from sentinelfi.agents.ml_classifier import MLTransactionClassifier
from sentinelfi.domain.models import NormalizedTransaction, TxCategory


class DummyPipeline:
    def predict_proba(self, texts):  # noqa: ANN001, ANN201
        return np.array([[0.8, 0.2] for _ in texts], dtype=float)


class DummyMulticlassPipeline:
    def __init__(self, probs: np.ndarray) -> None:
        self._probs = probs

    def predict_proba(self, texts):  # noqa: ANN001, ANN201
        assert len(texts) == len(self._probs)
        return self._probs


def _tx(text: str) -> NormalizedTransaction:
    return NormalizedTransaction(
        tx_id="tx1",
        tx_date=date(2025, 1, 1),
        description=text,
        amount=1000,
        normalized_description=text.lower(),
        pii_redacted_description=text.lower(),
    )


def test_ml_classifier_predicts_binary_labels(tmp_path) -> None:
    model_path = tmp_path / "ml.joblib"

    X = ["aws cloud invoice", "gst filing fee", "swiggy dinner", "movie tickets"]
    y = ["business", "business", "personal", "personal"]
    pipeline = Pipeline(
        [
            ("tfidf", TfidfVectorizer()),
            ("clf", LogisticRegression(max_iter=500, solver="liblinear")),
        ]
    )
    pipeline.fit(X, y)

    joblib.dump({"pipeline": pipeline, "labels": ["business", "personal"], "metadata": {}}, model_path)

    classifier = MLTransactionClassifier(str(model_path), enabled=True)
    out = classifier.classify([_tx("aws hosting payment")])

    assert len(out) == 1
    assert out[0].category in {TxCategory.BUSINESS, TxCategory.PERSONAL}
    assert out[0].classifier == "ml"


def test_ml_classifier_applies_probability_calibration(tmp_path) -> None:
    model_path = tmp_path / "ml_calibrated.joblib"
    payload = {
        "pipeline": DummyPipeline(),
        "labels": ["business", "personal"],
        "metadata": {
            "probability_calibration": {
                "method": "platt",
                "positive_label": "business",
                "coef": 0.5,
                "intercept": 0.0,
            }
        },
    }
    joblib.dump(payload, model_path)

    classifier = MLTransactionClassifier(str(model_path), enabled=True)
    out = classifier.classify([_tx("aws hosting payment")])

    assert len(out) == 1
    assert out[0].category == TxCategory.BUSINESS
    assert 0.6 <= out[0].confidence <= 0.7


def test_ml_classifier_maps_taxonomy_labels_to_binary_category(tmp_path) -> None:
    model_path = tmp_path / "ml_multiclass.joblib"
    payload = {
        "pipeline": DummyMulticlassPipeline(np.array([[0.65, 0.25, 0.10]], dtype=float)),
        "labels": ["food_dining", "professional_services", "__fallback_business__"],
        "metadata": {
            "label_to_tx_category": {
                "food_dining": "personal",
                "professional_services": "business",
                "__fallback_business__": "business",
            },
            "probability_calibration": {
                "method": "platt_business_aggregate",
                "positive_label": "business",
                "business_labels": ["professional_services", "__fallback_business__"],
                "coef": 1.0,
                "intercept": 0.0,
            },
        },
    }
    joblib.dump(payload, model_path)

    classifier = MLTransactionClassifier(str(model_path), enabled=True)
    out = classifier.classify([_tx("swiggy order")])

    assert len(out) == 1
    assert out[0].category == TxCategory.PERSONAL
    assert out[0].taxonomy_category == "food_dining"
    assert 0.6 <= out[0].confidence <= 0.7
