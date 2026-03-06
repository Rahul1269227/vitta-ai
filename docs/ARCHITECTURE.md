# Sentinel-Fi Architecture

## Runtime

- API layer: `FastAPI`
- Orchestration: `LangGraph` state graphs
- Storage: `PostgreSQL` via `SQLModel` + `Alembic` migrations
- Async execution: in-process background job workers + persisted audit job status
- Reports: `ReportLab` + markdown rendering
- Connectors: CSV, PDF, Stripe, Razorpay

## Audit graph nodes

1. `data_ingestor`
- Loads transactions from selected source
- Normalizes strings and scrubs PII

2. `mcc_classifier`
- Applies deterministic MCC mapping for early classification exit
- Keeps unresolved transactions for embedding/LLM routing

3. `ml_classifier`
- Primary classifier using taxonomy-aware multiclass ML model
- Maps model labels to business/personal decisions with calibrated confidence
- Escalates only low-confidence/high-risk rows

4. `routing_supervisor`
- Uses BGE-M3 embeddings when available
- Routes escalated descriptors to rule-fallback/LLM paths
- Uses conditional edges to skip fallback/LLM nodes when routes are empty

5. `slm_classifier`
- Fast rule-based classifier for cost control
- Fast-mode policy escalates uncertain/high-risk results to LLM

6. `llm_reasoner`
- Deep reasoning path for ambiguous transactions
- Enforces strict JSON schema and retry logic before fallback

7. `finalize_classification`
- Merges MCC + ML + fallback + LLM outputs
- Attaches explainable decision traces and review flags

8. `leak_detector`
- Detects duplicate subscriptions, zombie subscriptions, price hikes, SaaS sprawl, tax miscategorization

9. `gst_sentinel`
- Finds likely missing invoices and missed ITC opportunities

10. `cleanup_planner`
- Produces approval-gated write tasks

## Cleanup graph nodes

1. `approval_gate`
- Enforces explicit user approval by task ID

2. `execute_writes`
- Executes permitted actions (ledger reclass, email draft, invoice fetch, GST recon)

## Security and compliance controls

- PII scrubbing before model routing
- Explicit approval gate before write operations
- Structured JSON logs for auditability
- DB-backed persistence for run traceability
- Rolling runtime stats endpoint for operational monitoring
- API key auth middleware for `/v1/*` routes (config-gated)
- Sliding-window rate limiting for `/v1/*` routes (`memory` or `redis` backend)
- Upload guardrails: extension allowlist, UUID filename storage, size caps
- Prometheus metrics endpoint (`/metrics`) and request latency counters/histograms
- Optional OpenTelemetry FastAPI instrumentation with OTLP exporter

## ML reliability layer

- Active learning service stores user corrections and auto-triggers retraining on configurable thresholds.
- Training pipeline enforces dataset checksum/size manifest pinning for reproducibility.
- Training pipeline uses aggregate business-probability calibration before serving confidence scores.
- Drift monitor compares runtime confidence/token/business-rate distributions against training baseline.
- Runtime endpoint exposes `stable/warning/critical` drift state with numeric drift signals.

## Extension points for production scale

- Add queue workers for async ingestion and cleanup actions
- Add tenant-level RBAC and scoped API keys
- Add OpenTelemetry traces and metrics
- Add webhook connectors for WhatsApp/Slack alerts
