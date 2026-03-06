from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.metrics import accuracy_score, classification_report, f1_score
from sklearn.model_selection import train_test_split
from sklearn.naive_bayes import ComplementNB
from sklearn.pipeline import FeatureUnion, Pipeline

from sentinelfi.services.dataset_manifest import (
    DEFAULT_MANIFEST_PATH,
    DatasetManifestError,
    ensure_dataset_artifact,
    load_manifest,
)
from sentinelfi.services.taxonomy_service import TaxonomyService

INTERNET_DATASETS = {
    "andyrasika_procurement_csv": {
        "url": (
            "https://huggingface.co/datasets/Andyrasika/bank_transactions/"
            "resolve/main/labelled_transactions.csv?download=true"
        ),
        "cache": Path("data/external/andyrasika_labelled_transactions.csv"),
    },
    "alok_financial_transactions_csv": {
        "url": (
            "https://huggingface.co/datasets/alokkulkarni/financial_Transactions/"
            "resolve/main/transactions.csv?download=true"
        ),
        "cache": Path("data/external/alok_financial_transactions.csv"),
    },
    "rajesh_transaction_category_train_parquet": {
        "url": (
            "https://huggingface.co/datasets/rajeshradhakrishnan/"
            "fin-transaction-category/resolve/main/data/train-00000-of-00001.parquet?download=true"
        ),
        "cache": Path("data/external/rajesh_fin_transaction_train.parquet"),
    },
    "rajesh_transaction_category_test_parquet": {
        "url": (
            "https://huggingface.co/datasets/rajeshradhakrishnan/"
            "fin-transaction-category/resolve/main/data/test-00000-of-00001.parquet?download=true"
        ),
        "cache": Path("data/external/rajesh_fin_transaction_test.parquet"),
    },
}

PERSONAL_CATEGORIES = {
    "food_dining",
    "groceries",
    "shopping",
    "entertainment",
    "health",
    "personal_care",
    "kids_family",
    "gifts_occasions",
    "pets",
    "other",
}

_PERSONAL_CATEGORY_HINTS = {
    "dining out",
    "dining",
    "entertainment",
    "shopping",
    "groceries",
    "healthcare",
    "transportation",
    "housing",
    "fuel",
    "automotive",
    "online shopping",
    "cash withdrawal",
}

_BUSINESS_CATEGORY_HINTS = {
    "utilities",
    "service subscriptions",
    "subscriptions",
    "payments/credits",
    "credit card payment",
    "loan payment",
    "income",
}

_RAJESH_CATEGORY_MAP = {
    0: "shopping",
    1: "dining out",
    2: "entertainment",
    3: "transportation",
    4: "housing",
    5: "payments/credits",
    6: "utilities",
    7: "service subscriptions",
}

_FALLBACK_BUSINESS_LABEL = "__fallback_business__"
_FALLBACK_PERSONAL_LABEL = "__fallback_personal__"


def _binary_label_from_category(category_id: str) -> str:
    return "personal" if category_id in PERSONAL_CATEGORIES else "business"


def _normalize_space(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _infer_label_from_category_text(category_text: str, descriptor_text: str, taxonomy: TaxonomyService) -> str:
    cat = _normalize_space(category_text)
    if cat in _BUSINESS_CATEGORY_HINTS:
        return "business"
    if cat in _PERSONAL_CATEGORY_HINTS:
        return "personal"

    matched = taxonomy.match_category(f"{cat} {descriptor_text}".strip())
    if matched:
        category_id, score, _ = matched
        propensity = taxonomy.business_score_for_category(category_id)
        if propensity >= 0.65 and score >= 0.3:
            return "business"
        if propensity <= 0.35 and score >= 0.3:
            return "personal"

    return "personal"


def load_feedback_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue

            text = str(row.get("text", "")).strip()
            label = str(row.get("label", "")).strip().lower()
            if not text or label not in {"business", "personal"}:
                continue
            out.append(
                {
                    "text": text,
                    "label": label,
                    "source": str(row.get("source", "feedback")),
                    "category": str(row.get("category", "feedback")),
                }
            )
    return out


def append_feedback_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            text = str(row.get("text", "")).strip()
            label = str(row.get("label", "")).strip().lower()
            if not text or label not in {"business", "personal"}:
                continue
            payload = {
                "text": text,
                "label": label,
                "source": str(row.get("source", "feedback")),
                "category": str(row.get("category", "feedback")),
            }
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")


def _load_local_bootstrap_data() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    path = Path("data/training/bootstrap_transactions.jsonl")
    if not path.exists():
        return records

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue

            text = str(row.get("text", "")).strip()
            label = str(row.get("label", "")).strip().lower()
            category = str(row.get("category", label or "other")).strip().lower()
            if not text or label not in {"business", "personal"}:
                continue

            records.append(
                {
                    "text": text,
                    "label": label,
                    "source": str(row.get("source", "bootstrap_local")),
                    "category": category,
                }
            )
    return records


def _load_transaction_ai_data() -> list[dict[str, Any]]:
    """Load the rich JSONL training data ported from transaction-ai.

    Each line has ``{"text": ..., "category": ..., "label": ...}``.
    The *label* field equals the category id.  We derive the binary label
    (business / personal) from the category via ``PERSONAL_CATEGORIES``.
    """
    records: list[dict[str, Any]] = []
    for name in ("train.jsonl", "test.jsonl"):
        path = Path("data/training") / name
        if not path.exists():
            continue

        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue

                text = str(row.get("text", "")).strip()
                category = str(row.get("category", "")).strip().lower()
                if not text or not category:
                    continue

                binary_label = _binary_label_from_category(category)
                records.append(
                    {
                        "text": text,
                        "label": binary_label,
                        "source": f"transaction_ai_{name.replace('.jsonl', '')}",
                        "category": category,
                    }
                )
    return records


def _load_upi_seed_data() -> list[dict[str, Any]]:
    path = Path("data/upi_classifier_eval.csv")
    if not path.exists():
        return []

    df = pd.read_csv(path)
    out: list[dict[str, Any]] = []
    for row in df.to_dict(orient="records"):
        text = str(row.get("raw_text", "")).strip()
        label = str(row.get("label", "")).strip().lower()
        if label not in {"business", "personal"} or not text:
            continue
        out.append({"text": text, "label": label, "source": "upi_seed", "category": "upi_seed"})
    return out


def _download_with_cache(dataset_id: str, url: str, cache_path: Path) -> None:
    ensure_dataset_artifact(
        dataset_id=dataset_id,
        url=url,
        cache_path=cache_path,
        manifest_path=DEFAULT_MANIFEST_PATH,
    )


def _safe_read_cached_csv(dataset_id: str, url: str, cache_path: Path) -> pd.DataFrame | None:
    try:
        _download_with_cache(dataset_id, url, cache_path)
        return pd.read_csv(cache_path)
    except DatasetManifestError:
        raise
    except Exception:
        return None


def _safe_read_cached_parquet(dataset_id: str, url: str, cache_path: Path) -> pd.DataFrame | None:
    try:
        _download_with_cache(dataset_id, url, cache_path)
        return pd.read_parquet(cache_path)
    except DatasetManifestError:
        raise
    except Exception:
        return None


def _load_internet_andyrasika_data() -> list[dict[str, Any]]:
    dataset_id = "andyrasika_procurement_csv"
    conf = INTERNET_DATASETS[dataset_id]
    df = _safe_read_cached_csv(dataset_id, conf["url"], conf["cache"])
    if df is None:
        return []

    out: list[dict[str, Any]] = []
    for row in df.to_dict(orient="records"):
        supplier = str(row.get("Supplier", "")).strip()
        description = str(row.get("Description", "")).strip()
        classification = str(row.get("Classification", "")).strip()
        if not supplier and not description:
            continue

        text = " | ".join([part for part in [supplier, description] if part])
        out.append(
            {
                "text": text,
                "label": "business",
                "source": "internet_andyrasika",
                "category": classification or "other",
            }
        )
    return out


def _load_internet_alok_data(taxonomy: TaxonomyService) -> list[dict[str, Any]]:
    dataset_id = "alok_financial_transactions_csv"
    conf = INTERNET_DATASETS[dataset_id]
    df = _safe_read_cached_csv(dataset_id, conf["url"], conf["cache"])
    if df is None:
        return []

    out: list[dict[str, Any]] = []
    for row in df.to_dict(orient="records"):
        desc = str(row.get("Description", "")).strip()
        category = str(row.get("Category", "")).strip()
        if not desc or not category:
            continue

        label = _infer_label_from_category_text(category, desc, taxonomy)
        out.append(
            {
                "text": desc,
                "label": label,
                "source": "internet_alok",
                "category": _normalize_space(category),
            }
        )
    return out


def _load_internet_rajesh_data(taxonomy: TaxonomyService) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    keys = [
        "rajesh_transaction_category_train_parquet",
        "rajesh_transaction_category_test_parquet",
    ]

    for key in keys:
        conf = INTERNET_DATASETS[key]
        df = _safe_read_cached_parquet(key, conf["url"], conf["cache"])
        if df is None:
            continue

        for row in df.to_dict(orient="records"):
            merchant = str(row.get("merchant", "")).strip()
            category_raw = row.get("category")
            if not merchant:
                continue

            try:
                category_int = int(category_raw)
            except (TypeError, ValueError):
                continue

            category_name = _RAJESH_CATEGORY_MAP.get(category_int, "other")
            label = _infer_label_from_category_text(category_name, merchant, taxonomy)
            out.append(
                {
                    "text": merchant,
                    "label": label,
                    "source": "internet_rajesh",
                    "category": category_name,
                }
            )
    return out


def _load_internet_data(taxonomy: TaxonomyService) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    out.extend(_load_internet_andyrasika_data())
    out.extend(_load_internet_alok_data(taxonomy))
    out.extend(_load_internet_rajesh_data(taxonomy))
    return out


def _manifest_dataset_snapshot() -> dict[str, dict[str, Any]]:
    payload = load_manifest(DEFAULT_MANIFEST_PATH)
    datasets = payload.get("datasets", {})
    out: dict[str, dict[str, Any]] = {}
    for dataset_id in INTERNET_DATASETS:
        entry = datasets.get(dataset_id)
        if not isinstance(entry, dict):
            continue
        out[dataset_id] = {
            "url": str(entry.get("url", "")),
            "sha256": str(entry.get("sha256", "")),
            "size_bytes": int(entry.get("size_bytes", 0)),
        }
    return out


def _resolve_model_label(
    taxonomy: TaxonomyService,
    category: str,
    text: str,
    binary_label: str,
) -> str:
    cleaned_category = _normalize_space(category)
    if cleaned_category and taxonomy.has_category(cleaned_category):
        return cleaned_category

    matched = taxonomy.match_category(f"{cleaned_category} {text}".strip())
    if matched:
        category_id, score, _ = matched
        if score >= 0.3:
            return category_id

    return _FALLBACK_BUSINESS_LABEL if binary_label == "business" else _FALLBACK_PERSONAL_LABEL


def _build_label_to_tx_category(records: list[dict[str, Any]]) -> dict[str, str]:
    counts: dict[str, dict[str, int]] = {}
    for row in records:
        model_label = str(row["model_label"]).strip()
        binary_label = str(row["label"]).strip().lower()
        if model_label not in counts:
            counts[model_label] = {"business": 0, "personal": 0}
        if binary_label in {"business", "personal"}:
            counts[model_label][binary_label] += 1

    out: dict[str, str] = {}
    for model_label, label_counts in counts.items():
        business_count = label_counts.get("business", 0)
        personal_count = label_counts.get("personal", 0)
        if business_count > personal_count:
            out[model_label] = "business"
        elif personal_count > business_count:
            out[model_label] = "personal"
        else:
            out[model_label] = "unknown"
    return out


def _aggregate_business_probability(
    labels: list[str],
    probs: np.ndarray,
    label_to_tx_category: dict[str, str],
) -> np.ndarray:
    if probs.ndim != 2 or probs.shape[0] == 0:
        return np.array([], dtype=float)

    business_indices = [
        idx for idx, label in enumerate(labels) if label_to_tx_category.get(label) == "business"
    ]
    if not business_indices and "business" in labels:
        business_indices = [labels.index("business")]
    if not business_indices:
        return np.full((probs.shape[0],), 0.5, dtype=float)

    return _clip_probs(probs[:, business_indices].sum(axis=1))


def _dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for row in records:
        key = (row["text"].strip().lower(), row["label"])
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _build_features() -> FeatureUnion:
    return FeatureUnion(
        [
            (
                "word_tfidf",
                TfidfVectorizer(
                    ngram_range=(1, 2),
                    lowercase=True,
                    min_df=2,
                    max_features=120_000,
                    sublinear_tf=True,
                ),
            ),
            (
                "char_tfidf",
                TfidfVectorizer(
                    analyzer="char_wb",
                    ngram_range=(3, 5),
                    lowercase=True,
                    min_df=2,
                    max_features=80_000,
                    sublinear_tf=True,
                ),
            ),
        ]
    )


def _build_candidate_pipelines() -> dict[str, Pipeline]:
    return {
        "tfidf_word_char_logreg": Pipeline(
            [
                ("features", _build_features()),
                (
                    "classifier",
                    LogisticRegression(
                        solver="lbfgs",
                        class_weight="balanced",
                        C=4.0,
                        max_iter=2_500,
                    ),
                ),
            ]
        ),
        "tfidf_word_char_sgd_logloss": Pipeline(
            [
                ("features", _build_features()),
                (
                    "classifier",
                    SGDClassifier(
                        loss="log_loss",
                        class_weight="balanced",
                        alpha=1e-5,
                        max_iter=3_000,
                        random_state=42,
                    ),
                ),
            ]
        ),
        "tfidf_word_char_complement_nb": Pipeline(
            [
                ("features", _build_features()),
                ("classifier", ComplementNB(alpha=0.2)),
            ]
        ),
    }


def _pipeline_labels(pipeline: Pipeline, fallback_labels: list[str]) -> list[str]:
    classes = getattr(pipeline, "classes_", None)
    if classes is not None:
        values = [str(v) for v in classes]
        if values:
            return values

    classifier = pipeline.named_steps.get("classifier")
    if classifier is not None:
        classes = getattr(classifier, "classes_", None)
        if classes is not None:
            values = [str(v) for v in classes]
            if values:
                return values

    return fallback_labels


def _select_best_model(
    X_train: list[str],
    y_train: list[str],
    X_val: list[str],
    y_val: list[str],
) -> tuple[str, Pipeline, list[dict[str, Any]]]:
    candidates = _build_candidate_pipelines()
    leaderboard: list[dict[str, Any]] = []
    best_name = ""
    best_pipeline: Pipeline | None = None
    best_f1 = -1.0
    best_acc = -1.0

    for name, pipeline in candidates.items():
        pipeline.fit(X_train, y_train)
        preds = pipeline.predict(X_val)
        f1 = float(f1_score(y_val, preds, average="macro"))
        acc = float(accuracy_score(y_val, preds))
        leaderboard.append({"name": name, "f1_macro_val": f1, "accuracy_val": acc})

        if (f1 > best_f1) or (f1 == best_f1 and acc > best_acc):
            best_name = name
            best_pipeline = pipeline
            best_f1 = f1
            best_acc = acc

    if best_pipeline is None:
        raise RuntimeError("Model selection failed to produce a trained candidate.")

    leaderboard.sort(key=lambda item: (item["f1_macro_val"], item["accuracy_val"]), reverse=True)
    return best_name, best_pipeline, leaderboard


def _clip_probs(values: np.ndarray) -> np.ndarray:
    return np.clip(values, 1e-6, 1.0 - 1e-6)


def _fit_probability_calibrator(
    labels: list[str],
    raw_probs: np.ndarray,
    y_true: list[str],
    label_to_tx_category: dict[str, str],
) -> dict[str, Any]:
    if raw_probs.ndim != 2 or raw_probs.shape[0] == 0:
        return {"method": "identity", "positive_label": "business"}

    business_probs = _aggregate_business_probability(labels, raw_probs, label_to_tx_category)
    if business_probs.size == 0:
        return {"method": "identity", "positive_label": "business"}

    logits = np.log(business_probs / (1.0 - business_probs)).reshape(-1, 1)
    y = np.array([1 if item == "business" else 0 for item in y_true], dtype=int)

    if len(np.unique(y)) < 2:
        return {"method": "identity", "positive_label": "business"}

    model = LogisticRegression(solver="lbfgs", max_iter=500)
    model.fit(logits, y)

    return {
        "method": "platt_business_aggregate",
        "positive_label": "business",
        "business_labels": [
            label for label in labels if label_to_tx_category.get(label) == "business"
        ],
        "coef": float(model.coef_[0][0]),
        "intercept": float(model.intercept_[0]),
    }


def _apply_business_probability_calibrator(
    labels: list[str],
    raw_probs: np.ndarray,
    calibrator: dict[str, Any] | None,
    label_to_tx_category: dict[str, str] | None = None,
) -> np.ndarray:
    if raw_probs.ndim != 2 or raw_probs.shape[0] == 0:
        return np.array([], dtype=float)

    if "business" in labels and raw_probs.shape[1] == 2:
        base_business_probs = _clip_probs(raw_probs[:, labels.index("business")])
    else:
        business_labels = set(calibrator.get("business_labels", [])) if calibrator else set()
        if not business_labels and label_to_tx_category:
            label_map = {
                label: str(label_to_tx_category.get(label, "personal")).lower() for label in labels
            }
        else:
            if not business_labels:
                business_labels = {"business"}
            label_map = {label: ("business" if label in business_labels else "personal") for label in labels}
        base_business_probs = _aggregate_business_probability(labels, raw_probs, label_map)

    if not calibrator or calibrator.get("method") not in {"platt", "platt_business_aggregate"}:
        return base_business_probs

    coef = float(calibrator.get("coef", 1.0))
    intercept = float(calibrator.get("intercept", 0.0))
    logits = np.log(base_business_probs / (1.0 - base_business_probs))
    calibrated_business = 1.0 / (1.0 + np.exp(-(coef * logits + intercept)))
    return _clip_probs(calibrated_business)


def _drift_baseline(
    texts: list[str],
    binary_predictions: list[str],
    confidences: np.ndarray,
) -> dict[str, Any]:
    text_lengths = np.array([len(text.split()) for text in texts], dtype=float)
    confidence_hist, edges = np.histogram(confidences, bins=np.linspace(0.0, 1.0, 11))
    business_rate = (
        sum(1 for label in binary_predictions if label == "business") / len(binary_predictions)
        if binary_predictions
        else 0.0
    )

    return {
        "window_bins": [round(float(edge), 2) for edge in edges.tolist()],
        "confidence_histogram": confidence_hist.astype(int).tolist(),
        "confidence_mean": float(confidences.mean()) if len(confidences) else 0.0,
        "confidence_std": float(confidences.std()) if len(confidences) else 0.0,
        "business_rate": float(business_rate),
        "text_token_mean": float(text_lengths.mean()) if len(text_lengths) else 0.0,
        "text_token_std": float(text_lengths.std()) if len(text_lengths) else 0.0,
    }


def train_ml_classifier(
    output_model: Path,
    metrics_path: Path,
    feedback_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    taxonomy = TaxonomyService(
        base_path="data/taxonomy_base.yaml",
        overrides_path="data/taxonomy_overrides.yaml",
    )

    records: list[dict[str, Any]] = []
    records.extend(_load_transaction_ai_data())
    records.extend(_load_local_bootstrap_data())
    records.extend(_load_upi_seed_data())
    records.extend(_load_internet_data(taxonomy))
    if feedback_records:
        records.extend(feedback_records)
    records = _dedupe_records(records)

    if len(records) < 500:
        raise RuntimeError("Insufficient training rows after merge. Need at least 500 samples.")

    for row in records:
        row["model_label"] = _resolve_model_label(
            taxonomy=taxonomy,
            category=str(row.get("category", "")),
            text=str(row.get("text", "")),
            binary_label=str(row.get("label", "personal")).lower(),
        )
    label_to_tx_category = _build_label_to_tx_category(records)

    df = pd.DataFrame(records)
    X = df["text"].astype(str).tolist()
    y_binary = df["label"].astype(str).tolist()
    y_model = df["model_label"].astype(str).tolist()

    (
        X_train_pool,
        X_test,
        y_model_train_pool,
        y_model_test,
        y_binary_train_pool,
        y_binary_test,
    ) = train_test_split(
        X,
        y_model,
        y_binary,
        test_size=0.15,
        random_state=42,
        stratify=y_binary,
    )
    (
        X_train,
        X_val,
        y_model_train,
        y_model_val,
        y_binary_train,
        y_binary_val,
    ) = train_test_split(
        X_train_pool,
        y_model_train_pool,
        y_binary_train_pool,
        test_size=0.15,
        random_state=42,
        stratify=y_binary_train_pool,
    )

    selected_name, _, leaderboard = _select_best_model(X_train, y_model_train, X_val, y_model_val)
    (
        X_fit,
        X_calib,
        y_model_fit,
        y_model_calib,
        y_binary_fit,
        y_binary_calib,
    ) = train_test_split(
        X_train_pool,
        y_model_train_pool,
        y_binary_train_pool,
        test_size=0.18,
        random_state=42,
        stratify=y_binary_train_pool,
    )

    selected_pipeline = _build_candidate_pipelines()[selected_name]
    selected_pipeline.fit(X_fit, y_model_fit)
    labels = _pipeline_labels(selected_pipeline, sorted(set(y_model_train_pool)))

    raw_calib_probs = selected_pipeline.predict_proba(X_calib)
    calibrator = _fit_probability_calibrator(
        labels=labels,
        raw_probs=raw_calib_probs,
        y_true=y_binary_calib,
        label_to_tx_category=label_to_tx_category,
    )

    raw_test_probs = selected_pipeline.predict_proba(X_test)
    calibrated_business_probs = _apply_business_probability_calibrator(
        labels,
        raw_test_probs,
        calibrator,
        label_to_tx_category=label_to_tx_category,
    )
    test_pred_idx = raw_test_probs.argmax(axis=1)
    test_pred_model_labels = [labels[int(idx)] for idx in test_pred_idx]
    test_pred_binary = [label_to_tx_category.get(label, "unknown") for label in test_pred_model_labels]
    test_confidence = np.array(
        [
            float(prob) if pred == "business" else float(1.0 - prob)
            for pred, prob in zip(test_pred_binary, calibrated_business_probs)
        ],
        dtype=float,
    )
    test_confidence = _clip_probs(test_confidence)

    accuracy = float(accuracy_score(y_binary_test, test_pred_binary))
    f1_macro = float(
        f1_score(
            y_binary_test,
            test_pred_binary,
            average="macro",
            labels=["business", "personal"],
            zero_division=0,
        )
    )
    report = classification_report(
        y_binary_test,
        test_pred_binary,
        labels=["business", "personal"],
        output_dict=True,
        zero_division=0,
    )
    model_label_accuracy = float(accuracy_score(y_model_test, test_pred_model_labels))
    model_label_f1_macro = float(
        f1_score(y_model_test, test_pred_model_labels, average="macro", zero_division=0)
    )
    drift_profile = _drift_baseline(X_test, test_pred_binary, test_confidence)

    output_model.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pipeline": selected_pipeline,
        "labels": labels,
        "metadata": {
            "model_type": selected_name,
            "model_target": "taxonomy_multiclass",
            "train_rows": len(X_fit),
            "calibration_rows": len(X_calib),
            "test_rows": len(X_test),
            "sources": df["source"].value_counts().to_dict(),
            "class_balance": df["label"].value_counts().to_dict(),
            "model_label_distribution": df["model_label"].value_counts().to_dict(),
            "label_to_tx_category": label_to_tx_category,
            "model_selection": leaderboard,
            "probability_calibration": calibrator,
            "drift_baseline": drift_profile,
        },
    }
    joblib.dump(payload, output_model)

    metrics = {
        "accuracy": accuracy,
        "f1_macro": f1_macro,
        "report": report,
        "rows_total": len(df),
        "rows_train": len(X_fit),
        "rows_calibration": len(X_calib),
        "rows_test": len(X_test),
        "rows_validation": len(X_val),
        "rows_validation_binary": len(y_binary_val),
        "rows_fit_binary": len(y_binary_fit),
        "sources": df["source"].value_counts().to_dict(),
        "class_balance": df["label"].value_counts().to_dict(),
        "model_label_distribution": df["model_label"].value_counts().to_dict(),
        "model_label_accuracy": model_label_accuracy,
        "model_label_f1_macro": model_label_f1_macro,
        "label_to_tx_category": label_to_tx_category,
        "selected_model": selected_name,
        "model_selection": leaderboard,
        "calibration": calibrator,
        "drift_baseline": drift_profile,
        "dataset_manifest": _manifest_dataset_snapshot(),
        "model_path": str(output_model),
    }
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return metrics
