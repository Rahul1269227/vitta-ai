# Reference Integration Notes

This project previously used `transaction-ai` as architectural reference only.
No code was copied verbatim into Sentinel-Fi.

## Key takeaways implemented

1. Deterministic early-exit path
- Reference idea: MCC-first deterministic classification for cheap/high-confidence cases.
- Implemented in Sentinel-Fi: `src/sentinelfi/agents/mcc_classifier.py`.
- Effect: transactions with known MCC bypass expensive reasoning paths.

2. Fast path with controlled escalation
- Reference idea: FAST_MODE (skip heavy LLM on confident agreement).
- Implemented in Sentinel-Fi: `src/sentinelfi/services/classification_policy.py` and updated graph flow.
- Effect: SLM handles easy traffic; uncertain/high-risk transactions escalate to LLM.
- Enhancement: conditional graph edges now skip SLM/LLM nodes entirely when route sets are empty.

3. Category/risk-aware confidence policy
- Reference idea: category-specific thresholds and review gating.
- Implemented in Sentinel-Fi: risk-sensitive review thresholds (`default` + `high_risk`) and escalation policy.
- Effect: tax-sensitive/high-value transactions are review-stricter.

4. Explainability traces
- Reference idea: explicit decision path and vote visibility.
- Implemented in Sentinel-Fi: classification decision objects in API outputs.
- Files:
  - `src/sentinelfi/domain/models.py` (`ClassificationDecision`, `ClassifierVote`)
  - `src/sentinelfi/services/explainability_service.py`

5. Runtime operational metrics
- Reference idea: rolling runtime stats for health/performance monitoring.
- Implemented in Sentinel-Fi:
  - `src/sentinelfi/services/runtime_stats.py`
- API endpoint: `GET /v1/runtime/stats`

5b. DB lifecycle hardening
- Implemented Alembic migration baseline and PostgreSQL-first runtime defaults.
- Files:
  - `alembic.ini`
  - `alembic/env.py`
  - `alembic/versions/20260213_01_initial_schema.py`

6. Taxonomy reuse and enhancement
- Imported category taxonomy baseline from:
  - Prior taxonomy ideas were adapted into `data/taxonomy_base.yaml` and `data/taxonomy_overrides.yaml`
- Materialized as:
  - `data/taxonomy_base.yaml`
- Added Sentinel-Fi B2B/UPI/GST-specific overrides:
  - `data/taxonomy_overrides.yaml`
- Runtime integration:
  - `src/sentinelfi/services/taxonomy_service.py`
  - wired into MCC classifier, router, and SLM classifier

7. ML-first production path
- Reference idea: keep deterministic/rule systems as assistive, not primary.
- Implemented in Sentinel-Fi:
  - `src/sentinelfi/agents/ml_classifier.py`
  - graph node `ml_classifier` in `src/sentinelfi/graph/audit_graph.py`
- Behavior:
  - MCC first (deterministic)
  - ML as default classifier for remaining rows
  - SLM/LLM only for low-confidence escalations

8. External internet data for training
- Downloaded training sources:
  - `Andyrasika/bank_transactions` from HuggingFace
  - `alokkulkarni/financial_Transactions` from HuggingFace
  - `rajeshradhakrishnan/fin-transaction-category` from HuggingFace
- Training script:
  - `scripts/train_ml_classifier.py`
- Artifact:
  - `models/transaction_ml_classifier.joblib`

9. Active learning feedback loop
- Reference idea: feed human-corrected low-confidence rows back into training.
- Implemented in Sentinel-Fi:
  - `src/sentinelfi/services/active_learning_service.py`
  - `src/sentinelfi/repositories/feedback_repository.py`
  - API: `POST /v1/ml/feedback`, `POST /v1/ml/retrain`, `GET /v1/ml/status`
- Effect:
  - corrections are persisted and merged into subsequent ML retraining runs.

10. Probability calibration + drift monitoring
- Reference idea: confidence should be calibrated and monitored in production.
- Implemented in Sentinel-Fi:
  - `src/sentinelfi/services/ml_training_service.py` (Platt scaling + drift baseline)
  - `src/sentinelfi/services/ml_drift_monitor.py`
  - runtime surfacing in `GET /v1/runtime/stats`
- Effect:
  - confidence scores are calibrated and runtime distribution shifts are flagged as `stable/warning/critical`.

## Graph-level implementation details

`src/sentinelfi/graph/audit_graph.py` now includes:
1. `data_ingestor`
2. `mcc_classifier`
3. `ml_classifier`
4. `routing_supervisor`
5. `slm_classifier` (with escalation)
6. `llm_reasoner`
7. `finalize_classification` (decision traces)
8. `leak_detector`
9. `gst_sentinel`
10. `cleanup_planner`

## Quality checks

- Lint: `python3 -m ruff check src tests scripts`
- Tests: `python3 -m pytest -q`
- End-to-end sample run: `PYTHONPATH=src python3 scripts/run_sample_audit.py`
