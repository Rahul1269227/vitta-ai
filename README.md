# Sentinel-Fi

Production-ready starter for an agentic financial leakage platform that moves from:
1. `Audit` (find ghost money)
2. `Cleanup` (approval-gated write actions)
3. `Strategy` (ready extension path)

Built with `FastAPI + LangGraph + SQLModel` and optimized for Indian SMB finance/GST workflows.

## What is implemented

- Ingestion connectors for `CSV`, `PDF`, `Stripe`, `Razorpay`
- OCR fallback for scanned PDF statements (PaddleOCR + pypdfium2, optional dependency)
- PII scrubbing and transaction normalization
- UPI-aware signal extraction (VPA/UTR heuristics, P2P vs P2M hints)
- Taxonomy-driven intelligence using project-owned taxonomy (`data/taxonomy_base.yaml`) + Sentinel overrides
- Taxonomy-aware multiclass ML classifier path (primary), mapped to business/personal audit decisions
- Conditional LangGraph routing (skips fallback/LLM nodes when no work is routed)
- LangGraph `Audit Graph` with specialized nodes:
  - Data Ingestor
  - MCC Classifier (deterministic early exit)
  - ML Classifier (primary classification engine)
  - Routing Supervisor (BGE-M3 + heuristic fallback)
  - Rule-Based Classifier (fast deterministic fallback path)
  - LLM Reasoner (OpenAI with strict JSON contract + fallback)
  - Fast-mode escalation policy (ML/rule-fallback uncertain cases only)
  - Leak Detector
  - GST Sentinel
  - Cleanup Planner
- LangGraph `Cleanup Graph` with approval gate and write execution stage
- Leak detection for:
  - duplicate subscriptions
  - zombie subscriptions
  - price hikes
  - SaaS sprawl
  - tax miscategorization
- GST anomaly detection and missed ITC estimation
- Auto-generated client reports:
  - Markdown report
  - professional PDF report
- PostgreSQL-first persistence with Alembic migrations
- Explainability traces per transaction (`classification_decisions`)
- Active learning loop: correction ingestion + continuous retraining
- Probability calibration for ML confidence reliability (Platt scaling)
- Drift monitoring on confidence/data distribution (`/v1/runtime/stats`)
- Runtime service metrics (`/v1/runtime/stats`, includes drift signals)
- API key authentication middleware (`ENABLE_API_KEY_AUTH`, `API_KEYS_CSV`)
- Per-client sliding-window rate limiting for `/v1/*` APIs (in-memory or Redis-backed)
- Secure upload handling (UUID filenames, path traversal-safe, max-size enforcement)
- Local statement ingestion allowlist for CSV/PDF paths (`LOCAL_INGESTION_ROOTS_CSV`)
- Async API handlers with threadpool boundaries for blocking DB/LLM/file operations
- Restart recovery for queued/running audit and ML retraining jobs persisted in DB
- Prometheus metrics endpoint at `/metrics`
- Optional OpenTelemetry tracing (`OTEL_ENABLED=true`)
- Lifespan-based startup + readiness checks (DB + ML model availability)
- Integration and unit tests
- Dockerized API deployment

## Architecture

```text
Input (CSV/PDF/APIs)
  -> Data Ingestor (clean + scrub PII)
  -> MCC Classifier (early deterministic path)
  -> ML Classifier (primary path)
  -> Routing Supervisor (BGE-M3)
      -> Rule-Based Classifier (fallback path)
      -> LLM Reasoner (deep path + escalations)
  -> Leak Detector
  -> GST Sentinel
  -> Cleanup Planner
  -> Persist + Generate Reports

Cleanup Graph (separate, paid tier)
  -> Approval Gate
  -> Execute write actions (ledger/email/invoice/GST recon)
```

Reference integration details: `docs/REFERENCE_INTEGRATION.md`

## Quick start

### Zero-manual scripts (recommended)

First time setup with `uv` (creates `.venv`, installs deps, allocates free non-standard ports, builds + runs docker):

```bash
bash scripts/setup_first_time.sh
```

Regular run (re-checks running ports, allocates free non-standard ports, starts stack):

```bash
bash scripts/run_regular.sh
```

Both scripts generate `.env.runtime` with host ports:
- `HOST_API_PORT` (default preference `18000`)
- `HOST_POSTGRES_PORT` (default preference `15432`)

### 1. Install

```bash
uv sync
```

For scanned-statement OCR support:

```bash
uv sync --extra ocr
```

For tests/lint:

```bash
uv sync --dev --extra ocr

# Optional local hooks
uv run pre-commit install
```

### 2. Configure env (Postgres)

```bash
cp .env.example .env
```

Set `OPENAI_API_KEY` if you want live LLM reasoning.
Set `DATABASE_URL` to your Postgres instance (see `.env.example`).

### 3. Apply DB migrations

```bash
make migrate
```

### Useful make commands

```bash
make migrate   # alembic upgrade head
make sync      # fast-forward local branch from origin/main
```

### 4. Run API (local hot reload)

```bash
make runserver
```

Open control room UI: `http://localhost:8000/`  
Open API docs: `http://localhost:8000/docs`

### 5. Run frontend dev server (separate hot reload)

```bash
make dev
```

Frontend dev URL: `http://127.0.0.1:5173` (served separately, API calls go to `http://127.0.0.1:8000/v1`).

### Optional: Docker services

Run infra-only (default):

```bash
docker compose up
```

Run full Docker stack (includes API container):

```bash
docker compose --profile app up --build
```

Docker host ports are configurable and non-standard by default:
- API profile: `${HOST_API_PORT:-18000}`
- Postgres: `${HOST_POSTGRES_PORT:-15432}`

## Run end-to-end sample

```bash
uv run python scripts/run_sample_audit.py
```

Output artifacts:
- `output/reports/<audit_id>.md`
- `output/pdf/<audit_id>.pdf`

## Evaluate BGE-M3 classifier

```bash
uv run python scripts/evaluate_bge_m3.py --input data/upi_classifier_eval.csv --model BAAI/bge-m3
```

If sentence-transformers/BGE model is unavailable, the script falls back to a TF-IDF baseline and still produces:
- accuracy
- confusion matrix
- misclassification table
- `output/reports/classifier_eval_results.csv`

## Train ML-first classifier

This training pipeline merges:
- external internet datasets from HuggingFace:
  - `Andyrasika/bank_transactions`
  - `alokkulkarni/financial_Transactions`
  - `rajeshradhakrishnan/fin-transaction-category`
- bundled local bootstrap training data (`data/training/bootstrap_transactions.jsonl`)
- local UPI seed labels
- automatic candidate model selection (`LogisticRegression`, `SGDClassifier`, `ComplementNB`)
- dataset integrity enforcement via `data/external/dataset_manifest.json` (URL + SHA-256 + size pinning)

```bash
uv run python scripts/train_ml_classifier.py --feedback-path data/feedback/corrections.jsonl
```

Outputs:
- `models/transaction_ml_classifier.joblib`
- `output/reports/ml_training_metrics.json`

## Core API endpoints

- `POST /v1/audit/upload` - upload CSV/PDF statement
- `POST /v1/audit/run` - direct audit execution for small workloads
- `POST /v1/audit/submit` - async audit job submission
- `GET /v1/audit/jobs/{job_id}` - async audit job status/result polling
- `GET /v1/audit/jobs` - list recent audit jobs
- `GET /v1/audits` - list recent audit runs
- `POST /v1/cleanup/run` - execute approved cleanup tasks for an existing audit (`audit_id`, `approved_task_ids`)
- `POST /v1/ml/feedback` - ingest corrected labels (active learning)
- `POST /v1/ml/retrain` - force retraining now
- `GET /v1/ml/status` - feedback/retraining status
- `GET /v1/admin/settings` - admin-only runtime settings view
- `PUT /v1/admin/settings` - admin-only runtime settings update
- `GET /v1/runtime/stats` - rolling runtime/quality + ML drift metrics
- `GET /healthz`
- `GET /readyz`
- `GET /` - Sentinel-Fi Control Room UI

When `ENABLE_API_KEY_AUTH=true`, all `/v1/*` endpoints require header `x-api-key`.
`/v1/admin/*` endpoints always require admin key from `ADMIN_API_KEYS_CSV`.
Rate limiting backend can be set with `RATE_LIMIT_BACKEND=memory|redis|auto` and `REDIS_URL=...`.
Local CSV/PDF ingestion is restricted to `LOCAL_INGESTION_ROOTS_CSV` (default: `data/uploads,data`).
Scanned PDF OCR fallback can be toggled via `ENABLE_PDF_OCR_FALLBACK` and language set with `PDF_OCR_LANG`.

Cleanup execution supports real integrations when enabled:
- `CLEANUP_LIVE_MODE=true`
- SMTP send for `email_draft` via `CLEANUP_EMAIL_SMTP_*`
- Webhook execution for `ledger_reclass`, `invoice_fetch`, `gst_recon` via:
  - `CLEANUP_LEDGER_WEBHOOK_URL`
  - `CLEANUP_INVOICE_WEBHOOK_URL`
  - `CLEANUP_GST_WEBHOOK_URL`

## March 2026 Refresh

- Public-safe copy reviewed before publication
- Full automated test suite re-run successfully
- Repository metadata polished for public presentation

## Sample audit request

```json
{
  "source_type": "csv",
  "source_path": "data/sample_transactions.csv",
  "source_config": {},
  "client_name": "Demo SMB",
  "report_period": "Nov 2025",
  "generate_pdf": true,
  "generate_markdown": true
}
```

Async flow:
1. `POST /v1/audit/submit` with the same payload.
2. Poll `GET /v1/audit/jobs/{job_id}` until `status` is `succeeded` or `failed`.

## Project structure

```text
src/sentinelfi/
  api/                FastAPI app + schemas
  agents/             rule-based, LLM, GST, cleanup planning
  connectors/         CSV/PDF/Stripe/Razorpay ingestion
  core/               settings + logging
  domain/             typed models + graph state
  graph/              langgraph workflows
  reports/            markdown/pdf report builders
  repositories/       SQLModel persistence
  services/           orchestration, routing, detection
scripts/
  run_sample_audit.py
  evaluate_bge_m3.py
  train_ml_classifier.py
data/
  sample_transactions.csv
  taxonomy_base.yaml
  taxonomy_overrides.yaml
  upi_classifier_eval.csv
alembic/
  env.py
  versions/
tests/
```

## Production hardening checklist

- Replace rule-based SLM with local Phi-4/Mistral inference service
- Add idempotency keys and audit trails for cleanup write actions
- Add RBAC, tenant isolation, encryption-at-rest, and secret manager integration
- Add job queue (Celery/Arq) for heavy PDF/API sync workloads
- Add Prometheus/OpenTelemetry instrumentation and alerts
- Add contract tests for bank/PDF parsers per institution
