from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Sentinel-Fi"
    env: str = "dev"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/sentinelfi"

    # LLM providers
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    llm_model: str = "gpt-4o-mini"
    llm_batch_size: int = 20
    fast_mode_enabled: bool = True
    slm_escalation_threshold: float = 0.72
    review_threshold_default: float = 0.70
    review_threshold_high_risk: float = 0.85
    enable_ml_classifier: bool = True
    ml_model_path: str = "models/transaction_ml_classifier.joblib"
    ml_min_confidence: float = 0.72
    ml_metrics_path: str = "output/reports/ml_training_metrics.json"
    ml_feedback_dataset_path: str = "data/feedback/corrections.jsonl"
    ml_feedback_retrain_threshold: int = 25
    ml_feedback_min_rows: int = 10
    ml_retrain_cooldown_minutes: int = 60
    ml_drift_window: int = 1_000
    ml_drift_z_warning: float = 2.5
    ml_drift_z_critical: float = 4.0
    ml_drift_psi_warning: float = 0.2
    ml_drift_psi_critical: float = 0.35
    ml_business_rate_warning: float = 0.15
    ml_business_rate_critical: float = 0.25

    # Embeddings and routing
    embedding_model: str = "BAAI/bge-m3"
    enable_local_embeddings: bool = True
    taxonomy_base_path: str = "data/taxonomy_base.yaml"
    taxonomy_overrides_path: str = "data/taxonomy_overrides.yaml"

    # Integrations
    stripe_api_key: str | None = None
    razorpay_key_id: str | None = None
    razorpay_key_secret: str | None = None

    pii_hash_salt: str = "replace-me-in-prod"

    # API hardening
    enable_api_key_auth: bool = False
    api_keys_csv: str = ""
    admin_api_keys_csv: str = ""
    rate_limit_per_minute: int = 120
    rate_limit_backend: str = "auto"
    redis_url: str | None = None
    cors_allow_origins_csv: str = "*"
    upload_max_bytes: int = 10 * 1024 * 1024
    min_free_disk_mb: int = 256
    local_ingestion_roots_csv: str = "data/uploads,data"
    enable_pdf_ocr_fallback: bool = True
    pdf_ocr_lang: str = "en"
    audit_job_workers: int = 2
    prometheus_enabled: bool = True
    otel_enabled: bool = False
    otel_service_name: str = "sentinelfi-api"
    otel_exporter_otlp_endpoint: str | None = None

    # Cleanup live integrations
    cleanup_live_mode: bool = False
    cleanup_webhook_timeout_seconds: int = 15
    cleanup_webhook_max_attempts: int = 4
    cleanup_webhook_retry_base_seconds: float = 0.5
    cleanup_webhook_retry_max_seconds: float = 8.0
    cleanup_webhook_hmac_secret: str | None = None
    cleanup_ledger_webhook_url: str | None = None
    cleanup_ledger_webhook_hmac_secret: str | None = None
    cleanup_invoice_webhook_url: str | None = None
    cleanup_invoice_webhook_hmac_secret: str | None = None
    cleanup_gst_webhook_url: str | None = None
    cleanup_gst_webhook_hmac_secret: str | None = None
    cleanup_email_smtp_host: str | None = None
    cleanup_email_smtp_port: int = 587
    cleanup_email_smtp_username: str | None = None
    cleanup_email_smtp_password: str | None = None
    cleanup_email_smtp_use_tls: bool = True
    cleanup_email_smtp_use_ssl: bool = False
    cleanup_email_from: str | None = None
    cleanup_email_to_csv: str = ""

    # Leak detection thresholds
    leak_duplicate_min_amount: float = 300.0
    leak_duplicate_amount_tolerance: float = 0.05
    leak_zombie_min_amount: float = 199.0
    leak_price_hike_min_amount: float = 100.0
    leak_price_hike_jump_threshold: float = 0.25
    leak_free_trial_lookback_days: int = 60
    leak_free_trial_low_amount_abs: float = 50.0
    leak_free_trial_low_amount_ratio: float = 0.10

    # Alerts / notifications
    alert_webhook_url: str | None = None
    alert_webhook_timeout_seconds: int = 10
    alert_webhook_max_attempts: int = 3
    alert_webhook_retry_base_seconds: float = 0.5
    alert_webhook_retry_max_seconds: float = 6.0
    alert_webhook_hmac_secret: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
