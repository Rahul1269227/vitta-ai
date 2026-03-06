#!/usr/bin/env python3
"""
Comprehensive accuracy evaluation for all Sentinel-Fi classifiers.

Tests:
  1. ML Classifier (primary path — trained joblib model)
  2. Rule-Based / SLM Classifier (keyword + optional embedding votes)
  3. TF-IDF Prototype Baseline (cosine similarity to prototypes)

Runs against data/upi_classifier_eval.csv (ground-truth labels).
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix

# ── Add project root to path ─────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from sentinelfi.agents.ml_classifier import MLTransactionClassifier  # noqa: E402
from sentinelfi.agents.slm_classifier import RuleBasedTransactionClassifier  # noqa: E402
from sentinelfi.domain.models import NormalizedTransaction, Transaction, TxCategory  # noqa: E402
from sentinelfi.services.ingestion_service import normalize_transactions  # noqa: E402
from sentinelfi.services.taxonomy_service import TaxonomyService  # noqa: E402

# ── Constants ─────────────────────────────────────────────────────────────
EVAL_CSV = ROOT / "data" / "upi_classifier_eval.csv"
MODEL_PATH = ROOT / "models" / "transaction_ml_classifier.joblib"
TAXONOMY_BASE = ROOT / "data" / "taxonomy_base.yaml"
TAXONOMY_OVERRIDES = ROOT / "data" / "taxonomy_overrides.yaml"
LABELS = ["business", "personal"]
OUTPUT_CSV = ROOT / "output" / "reports" / "accuracy_eval_all_classifiers.csv"

# TF-IDF prototype labels (same as evaluate_bge_m3.py)
PROTOTYPES = {
    "business": [
        "aws cloud hosting invoice",
        "google workspace business plan",
        "software license renewal",
        "digital marketing agency gst",
        "ca audit professional fees",
    ],
    "personal": [
        "swiggy food order",
        "zomato dinner",
        "movie tickets",
        "grocery shopping",
        "family travel booking",
    ],
}


def _build_normalized_txs(raw_texts: list[str]) -> list[NormalizedTransaction]:
    """Build NormalizedTransactions using the real ingestion pipeline (normalize + PII scrub)."""
    transactions = [
        Transaction(
            tx_id=f"EVAL_{idx:03d}",
            tx_date=date(2025, 11, 1),
            description=raw_text,
            amount=1000.0,
            currency="INR",
            is_debit=True,
            merchant=None,
            metadata={},
        )
        for idx, raw_text in enumerate(raw_texts)
    ]
    return normalize_transactions(transactions, pii_hash_salt="eval_salt_2025")


def _tfidf_predict(texts: list[str], prototypes: dict[str, list[str]] | None = None) -> list[str]:
    """TF-IDF cosine similarity baseline against prototype anchors."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    if prototypes is None:
        prototypes = PROTOTYPES

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
    return [prototype_labels[row.argmax()] for row in sim]


def _category_to_label(cat: TxCategory) -> str:
    if cat == TxCategory.BUSINESS:
        return "business"
    if cat == TxCategory.PERSONAL:
        return "personal"
    return "unknown"


def _print_section(title: str) -> None:
    width = 70
    print()
    print("=" * width)
    print(f"  {title}")
    print("=" * width)


def _print_metrics(
    expected: list[str],
    predicted: list[str],
    name: str,
    confidences: list[float] | None = None,
) -> dict[str, float]:
    acc = accuracy_score(expected, predicted)
    cm = confusion_matrix(expected, predicted, labels=LABELS)
    report = classification_report(expected, predicted, labels=LABELS, zero_division=0)

    print(f"\n  Accuracy:  {acc:.4f}  ({sum(a == b for a, b in zip(expected, predicted))}/{len(expected)})")
    if confidences:
        avg_conf = sum(confidences) / len(confidences)
        print(f"  Avg Confidence: {avg_conf:.4f}")
    print("\n  Confusion Matrix (rows=true, cols=pred):")
    print(f"  {pd.DataFrame(cm, index=LABELS, columns=LABELS).to_string()}")
    print("\n  Classification Report:")
    for line in report.strip().split("\n"):
        print(f"  {line}")

    # Show misclassifications
    misses = [(e, p, i) for i, (e, p) in enumerate(zip(expected, predicted)) if e != p]
    if misses:
        print(f"\n  Misclassifications ({len(misses)}):")
        for exp, pred, idx in misses:
            conf_str = f"  conf={confidences[idx]:.3f}" if confidences else ""
            print(f"    [{idx:2d}] expected={exp:10s}  predicted={pred:10s}{conf_str}")

    return {"accuracy": acc, "name": name}


def main() -> int:
    if not EVAL_CSV.exists():
        print(f"ERROR: Eval dataset not found: {EVAL_CSV}")
        return 1

    df = pd.read_csv(EVAL_CSV)
    if "raw_text" not in df.columns or "label" not in df.columns:
        print("ERROR: Eval CSV must have raw_text,label columns")
        return 1

    texts = df["raw_text"].astype(str).tolist()
    expected = [v.strip().lower() for v in df["label"].astype(str).tolist()]
    n = len(texts)

    print(f"Eval dataset: {EVAL_CSV}")
    print(f"Samples: {n}")
    print(f"Label distribution: {pd.Series(expected).value_counts().to_dict()}")

    # Build NormalizedTransaction objects using the real ingestion pipeline
    norm_txs = _build_normalized_txs(texts)

    # ── Results collector ─────────────────────────────────────────────────
    result_df = df.copy()
    summaries: list[dict[str, float]] = []

    # ══════════════════════════════════════════════════════════════════════
    # 1. ML Classifier (primary path)
    # ══════════════════════════════════════════════════════════════════════
    _print_section("1. ML Classifier (trained model)")
    if MODEL_PATH.exists():
        ml = MLTransactionClassifier(model_path=str(MODEL_PATH), enabled=True)
        if ml.available:
            ml_results = ml.classify(norm_txs)
            ml_preds = [_category_to_label(r.category) for r in ml_results]
            ml_confs = [r.confidence for r in ml_results]
            result_df["ml_predicted"] = ml_preds
            result_df["ml_confidence"] = ml_confs
            result_df["ml_correct"] = [e == p for e, p in zip(expected, ml_preds)]
            summaries.append(_print_metrics(expected, ml_preds, "ML Classifier", ml_confs))
        else:
            print("  ML model loaded but not available (corrupt artifact?)")
    else:
        print(f"  Model file not found: {MODEL_PATH}")
        print("  Run: uv run python scripts/train_ml_classifier.py")

    # ══════════════════════════════════════════════════════════════════════
    # 2. Rule-Based / SLM Classifier (no embeddings — pure keywords)
    # ══════════════════════════════════════════════════════════════════════
    _print_section("2. Rule-Based Classifier (keywords only, no embeddings)")
    taxonomy = None
    if TAXONOMY_BASE.exists():
        taxonomy = TaxonomyService(
            base_path=str(TAXONOMY_BASE),
            overrides_path=str(TAXONOMY_OVERRIDES) if TAXONOMY_OVERRIDES.exists() else None,
        )

    slm_no_embed = RuleBasedTransactionClassifier(
        taxonomy=taxonomy,
        enable_local_model=False,
    )
    slm_results = slm_no_embed.classify(norm_txs)
    slm_preds = [_category_to_label(r.category) for r in slm_results]
    slm_confs = [r.confidence for r in slm_results]
    result_df["rule_predicted"] = slm_preds
    result_df["rule_confidence"] = slm_confs
    result_df["rule_correct"] = [e == p for e, p in zip(expected, slm_preds)]
    summaries.append(_print_metrics(expected, slm_preds, "Rule-Based (keywords)", slm_confs))

    # ══════════════════════════════════════════════════════════════════════
    # 3. Rule-Based / SLM Classifier (with embeddings if available)
    # ══════════════════════════════════════════════════════════════════════
    _print_section("3. Rule-Based Classifier (keywords + embedding votes)")
    try:
        slm_embed = RuleBasedTransactionClassifier(
            taxonomy=taxonomy,
            enable_local_model=True,
        )
        slm_embed_results = slm_embed.classify(norm_txs)
        slm_embed_preds = [_category_to_label(r.category) for r in slm_embed_results]
        slm_embed_confs = [r.confidence for r in slm_embed_results]
        result_df["slm_embed_predicted"] = slm_embed_preds
        result_df["slm_embed_confidence"] = slm_embed_confs
        result_df["slm_embed_correct"] = [e == p for e, p in zip(expected, slm_embed_preds)]
        summaries.append(
            _print_metrics(expected, slm_embed_preds, "Rule-Based (+ embeddings)", slm_embed_confs)
        )
    except Exception as exc:
        print(f"  Skipped — embedding model unavailable: {exc}")

    # ══════════════════════════════════════════════════════════════════════
    # 4. BGE-M3 Prototype Prediction (nearest-prototype cosine similarity)
    # ══════════════════════════════════════════════════════════════════════
    _print_section("4. BGE-M3 Prototype Prediction (taxonomy-derived prototypes)")
    try:
        from sentence_transformers import SentenceTransformer

        bge_model = SentenceTransformer("BAAI/bge-m3")

        # Build prototypes from taxonomy categories + propensity
        bge_prototypes: dict[str, list[str]] = {"business": [], "personal": []}
        if taxonomy:
            for cat_id, cat in taxonomy.categories.items():
                propensity = taxonomy.business_score_for_category(cat_id)
                keywords = sorted(cat.keywords)[:8]
                if not keywords:
                    continue
                proto = " ".join(keywords)
                if propensity >= 0.65:
                    bge_prototypes["business"].append(proto)
                elif propensity <= 0.35:
                    bge_prototypes["personal"].append(proto)

        # Fallback if taxonomy didn't produce enough prototypes
        if len(bge_prototypes["business"]) < 3 or len(bge_prototypes["personal"]) < 3:
            bge_prototypes = PROTOTYPES

        print(f"  Prototypes: {len(bge_prototypes['business'])} business, {len(bge_prototypes['personal'])} personal")

        prototype_labels_bge: list[str] = []
        prototype_texts_bge: list[str] = []
        for label, samples in bge_prototypes.items():
            for sample in samples:
                prototype_labels_bge.append(label)
                prototype_texts_bge.append(sample)

        proto_vecs = bge_model.encode(prototype_texts_bge, normalize_embeddings=True)
        text_vecs = bge_model.encode(texts, normalize_embeddings=True)
        sim = text_vecs @ proto_vecs.T
        bge_preds = [prototype_labels_bge[row.argmax()] for row in sim]
        result_df["bge_predicted"] = bge_preds
        result_df["bge_correct"] = [e == p for e, p in zip(expected, bge_preds)]
        summaries.append(_print_metrics(expected, bge_preds, "BGE-M3 Taxonomy Proto"))
    except Exception as exc:
        print(f"  Skipped — BGE-M3 unavailable: {exc}")

    # ══════════════════════════════════════════════════════════════════════
    # 5. TF-IDF Prototype Baseline
    # ══════════════════════════════════════════════════════════════════════
    _print_section("5. TF-IDF Prototype Baseline (taxonomy-derived)")
    # Build taxonomy-derived prototypes for TF-IDF too
    tfidf_prototypes: dict[str, list[str]] = {"business": [], "personal": []}
    if taxonomy:
        for cat_id, cat in taxonomy.categories.items():
            propensity = taxonomy.business_score_for_category(cat_id)
            keywords = sorted(cat.keywords)[:8]
            if not keywords:
                continue
            proto = " ".join(keywords)
            if propensity >= 0.65:
                tfidf_prototypes["business"].append(proto)
            elif propensity <= 0.35:
                tfidf_prototypes["personal"].append(proto)
    if len(tfidf_prototypes["business"]) < 3 or len(tfidf_prototypes["personal"]) < 3:
        tfidf_prototypes = PROTOTYPES
    tfidf_preds = _tfidf_predict(texts, tfidf_prototypes)
    result_df["tfidf_predicted"] = tfidf_preds
    result_df["tfidf_correct"] = [e == p for e, p in zip(expected, tfidf_preds)]
    summaries.append(_print_metrics(expected, tfidf_preds, "TF-IDF Taxonomy Proto"))

    # ══════════════════════════════════════════════════════════════════════
    # Summary comparison
    # ══════════════════════════════════════════════════════════════════════
    _print_section("ACCURACY COMPARISON SUMMARY")
    summaries.sort(key=lambda s: s["accuracy"], reverse=True)
    for rank, s in enumerate(summaries, 1):
        bar = "#" * int(s["accuracy"] * 40)
        print(f"  {rank}. {s['name']:<35s}  {s['accuracy']:.4f}  {bar}")

    # ── Save detailed output ──────────────────────────────────────────────
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    result_df.to_csv(OUTPUT_CSV, index=False)
    print(f"\nDetailed per-row output saved: {OUTPUT_CSV}")

    # ── Per-row comparison table ──────────────────────────────────────────
    _print_section("PER-ROW PREDICTIONS")
    cols = ["raw_text", "label"]
    for col in ["ml_predicted", "rule_predicted", "slm_embed_predicted", "bge_predicted", "tfidf_predicted"]:
        if col in result_df.columns:
            cols.append(col)
    print(result_df[cols].to_string(index=True, max_colwidth=55))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
