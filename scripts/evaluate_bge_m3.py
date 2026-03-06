#!/usr/bin/env python3
"""Evaluate BGE-M3 / TF-IDF classifier using taxonomy-derived prototypes."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.metrics.pairwise import cosine_similarity

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from sentinelfi.services.taxonomy_service import TaxonomyService  # noqa: E402

LABELS = ["business", "personal", "unknown"]

# ── Fallback prototypes (used only if taxonomy is unavailable) ────────
_FALLBACK_PROTOTYPES = {
    "business": [
        "aws cloud hosting invoice",
        "google workspace business plan",
        "software license renewal",
        "digital marketing agency gst",
        "ca audit professional fees",
        "salesforce crm subscription",
        "consulting retainer payment",
        "domain hosting godaddy",
        "slack technologies monthly",
        "zoom pro license",
    ],
    "personal": [
        "swiggy food order",
        "zomato dinner",
        "movie tickets pvr cinema",
        "grocery shopping dmart",
        "family travel booking hotel",
        "uber ola cab ride fare",
        "medical store pharmacy",
        "school fees education",
        "lic insurance premium",
        "donation temple charity",
        "electricity bill home",
        "fuel petrol personal commute",
        "netflix spotify streaming",
        "myntra shopping clothes",
    ],
}


def _build_taxonomy_prototypes(taxonomy: TaxonomyService) -> dict[str, list[str]]:
    """Build prototype sentences from taxonomy categories using propensity scores."""
    business_protos: list[str] = []
    personal_protos: list[str] = []

    for category_id, category in taxonomy.categories.items():
        propensity = taxonomy.business_score_for_category(category_id)
        keywords = sorted(category.keywords)[:8]
        if not keywords:
            continue

        proto_sentence = " ".join(keywords)
        if propensity >= 0.65:
            business_protos.append(proto_sentence)
        elif propensity <= 0.35:
            personal_protos.append(proto_sentence)

    if not business_protos or not personal_protos:
        return _FALLBACK_PROTOTYPES

    return {"business": business_protos, "personal": personal_protos}


def normalize_label(value: str) -> str:
    lowered = value.strip().lower()
    if lowered in {"business", "personal", "unknown"}:
        return lowered
    return "unknown"


def bge_predict(texts: list[str], model_name: str, prototypes: dict[str, list[str]]) -> list[str]:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name)
    prototype_labels: list[str] = []
    prototype_texts: list[str] = []

    for label, samples in prototypes.items():
        for sample in samples:
            prototype_labels.append(label)
            prototype_texts.append(sample)

    proto_vecs = model.encode(prototype_texts, normalize_embeddings=True)
    text_vecs = model.encode(texts, normalize_embeddings=True)

    sim = text_vecs @ proto_vecs.T
    pred = [prototype_labels[row.argmax()] for row in sim]
    return pred


def tfidf_predict(texts: list[str], prototypes: dict[str, list[str]]) -> list[str]:
    prototype_labels: list[str] = []
    prototype_texts: list[str] = []
    for label, samples in prototypes.items():
        for sample in samples:
            prototype_labels.append(label)
            prototype_texts.append(sample)

    vectorizer = TfidfVectorizer(ngram_range=(1, 2), lowercase=True)
    corpus = prototype_texts + texts
    matrix = vectorizer.fit_transform(corpus)
    proto_mat = matrix[: len(prototype_texts)]
    text_mat = matrix[len(prototype_texts) :]

    sim = cosine_similarity(text_mat, proto_mat)
    pred = [prototype_labels[row.argmax()] for row in sim]
    return pred


def run(path: Path, model_name: str) -> int:
    df = pd.read_csv(path)
    if "raw_text" not in df.columns or "label" not in df.columns:
        raise ValueError("Input CSV must include raw_text,label columns")

    texts = df["raw_text"].astype(str).tolist()
    expected = [normalize_label(v) for v in df["label"].astype(str).tolist()]

    # Build taxonomy-aware prototypes
    taxonomy = TaxonomyService(
        base_path=str(ROOT / "data" / "taxonomy_base.yaml"),
        overrides_path=str(ROOT / "data" / "taxonomy_overrides.yaml"),
    )
    prototypes = _build_taxonomy_prototypes(taxonomy)
    print(f"Prototypes: {sum(len(v) for v in prototypes.values())} total "
          f"({len(prototypes.get('business', []))} business, {len(prototypes.get('personal', []))} personal)")

    try:
        predicted = bge_predict(texts, model_name, prototypes)
        backend = f"BGE model: {model_name}"
    except Exception as exc:
        print(f"BGE-M3 unavailable ({exc}); falling back to TF-IDF baseline.")
        predicted = tfidf_predict(texts, prototypes)
        backend = "TF-IDF fallback"

    acc = accuracy_score(expected, predicted)
    cm = confusion_matrix(expected, predicted, labels=LABELS)

    print(f"Backend: {backend}")
    print(f"Rows: {len(df)}")
    print(f"Accuracy: {acc:.4f}")
    print("Confusion Matrix (rows=true, cols=pred):")
    print(pd.DataFrame(cm, index=LABELS, columns=LABELS).to_string())
    print("\nClassification Report:")
    print(classification_report(expected, predicted, labels=LABELS, zero_division=0))

    result = df.copy()
    result["predicted"] = predicted
    result["correct"] = result["label"].str.lower() == result["predicted"]
    bad = result[~result["correct"]]
    if not bad.empty:
        print("\nMisclassifications:")
        print(bad[["raw_text", "label", "predicted"]].to_string(index=False))

    output_path = Path("output/reports/classifier_eval_results.csv")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_path, index=False)
    print(f"\nSaved detailed output: {output_path}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate BGE-M3 on Indian transaction labels")
    parser.add_argument("--input", default="data/upi_classifier_eval.csv")
    parser.add_argument("--model", default="BAAI/bge-m3")
    args = parser.parse_args()

    return run(Path(args.input), args.model)


if __name__ == "__main__":
    raise SystemExit(main())
