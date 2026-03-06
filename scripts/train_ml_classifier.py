#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from sentinelfi.services.ml_training_service import load_feedback_jsonl, train_ml_classifier


def main() -> int:
    parser = argparse.ArgumentParser(description="Train ML-first transaction classifier")
    parser.add_argument("--output-model", default="models/transaction_ml_classifier.joblib")
    parser.add_argument("--metrics", default="output/reports/ml_training_metrics.json")
    parser.add_argument("--feedback-path", default="data/feedback/corrections.jsonl")
    args = parser.parse_args()

    feedback_rows = load_feedback_jsonl(Path(args.feedback_path))
    metrics = train_ml_classifier(
        output_model=Path(args.output_model),
        metrics_path=Path(args.metrics),
        feedback_records=feedback_rows,
    )

    print(f"Trained model: {args.output_model}")
    print(f"Rows total: {metrics['rows_total']}")
    print(f"Selected model: {metrics['selected_model']}")
    print(f"Accuracy: {metrics['accuracy']:.4f}")
    print(f"F1 Macro: {metrics['f1_macro']:.4f}")
    print(f"Sources: {metrics['sources']}")
    print(f"Class balance: {metrics['class_balance']}")
    print(f"Feedback rows used: {len(feedback_rows)}")
    print(f"Metrics: {args.metrics}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
