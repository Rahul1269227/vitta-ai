from __future__ import annotations

from datetime import date, datetime, timezone

from sentinelfi.core.config import Settings
from sentinelfi.domain.models import ClassifiedTransaction, TxCategory
from sentinelfi.repositories.audit_repository import AuditRepository
from sentinelfi.repositories.db import init_db, session_scope
from sentinelfi.repositories.feedback_repository import FeedbackRepository
from sentinelfi.services.active_learning_service import ActiveLearningService, FeedbackCorrection


def _classified_tx() -> ClassifiedTransaction:
    return ClassifiedTransaction(
        tx_id="TX123",
        tx_date=date(2025, 1, 1),
        description="UPI/123/swIggy@okicici lunch",
        amount=420.0,
        currency="INR",
        is_debit=True,
        merchant="swiggy",
        metadata={"upi": {"is_upi": True, "merchant_token": "swiggy", "p2m_likely": True}},
        normalized_description="upi 123 swiggy@okicici lunch",
        pii_redacted_description="upi <UPI_MERCHANT:swiggy> lunch",
        category=TxCategory.PERSONAL,
        confidence=0.92,
        classifier="ml",
    )


def test_feedback_ingest_and_auto_retrain(monkeypatch, tmp_path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/test.db",
        ml_model_path=str(tmp_path / "model.joblib"),
        ml_metrics_path=str(tmp_path / "metrics.json"),
        ml_feedback_dataset_path=str(tmp_path / "corrections.jsonl"),
        ml_feedback_retrain_threshold=1,
        ml_feedback_min_rows=1,
        ml_retrain_cooldown_minutes=0,
        enable_local_embeddings=False,
    )
    init_db(settings)

    with session_scope(settings) as session:
        repo = AuditRepository(session)
        repo.save_classified_transactions("audit-1", [_classified_tx()])

    service = ActiveLearningService(settings)

    def _fake_train(*_args, **_kwargs):
        return {
            "accuracy": 0.99,
            "f1_macro": 0.99,
            "rows_total": 1000,
            "sources": {"bootstrap_local": 900, "feedback_api": 100},
            "class_balance": {"business": 500, "personal": 500},
            "selected_model": "tfidf_word_char_logreg",
        }

    monkeypatch.setattr("sentinelfi.services.active_learning_service.train_ml_classifier", _fake_train)
    monkeypatch.setattr(service, "_enqueue_training_job", service._run_training_job)

    result = service.submit_feedback(
        audit_id="audit-1",
        corrections=[FeedbackCorrection(tx_id="TX123", corrected_category="business")],
        auto_retrain=True,
    )

    assert result["accepted_count"] == 1
    assert result["retrain_triggered"] is True

    with session_scope(settings) as session:
        repo = FeedbackRepository(session)
        assert repo.count_feedback(statuses=["pending"]) == 0
        latest = repo.latest_training_run()
        assert latest is not None
        assert latest.status == "success"
    service.shutdown()


def test_feedback_rejects_unknown_tx(tmp_path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/test.db",
        ml_feedback_dataset_path=str(tmp_path / "corrections.jsonl"),
        enable_local_embeddings=False,
    )
    init_db(settings)

    service = ActiveLearningService(settings)
    result = service.submit_feedback(
        audit_id="audit-missing",
        corrections=[FeedbackCorrection(tx_id="TX404", corrected_category="business")],
        auto_retrain=False,
    )

    assert result["accepted_count"] == 0
    assert result["retrain_triggered"] is False
    assert result["rejected"][0]["reason"] == "tx_not_found"
    service.shutdown()


def test_recover_incomplete_training_runs_requeues_jobs(tmp_path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/test.db",
        enable_local_embeddings=False,
    )
    init_db(settings)

    with session_scope(settings) as session:
        repo = FeedbackRepository(session)
        repo.create_training_run(
            run_id="train-recover-1",
            started_at=datetime.now(timezone.utc),
            trigger="test",
            model_path=str(tmp_path / "model.joblib"),
            feedback_rows_used=0,
            status="running",
        )
        session.commit()

    service = ActiveLearningService(settings)
    enqueued: list[str] = []

    def _capture_enqueue(run_id: str) -> None:
        enqueued.append(run_id)

    service._enqueue_training_job = _capture_enqueue  # type: ignore[method-assign]
    recovered = service.recover_incomplete_training_runs()

    assert recovered == 1
    assert enqueued == ["train-recover-1"]

    with session_scope(settings) as session:
        latest = FeedbackRepository(session).latest_training_run()
        assert latest is not None
        assert latest.status == "queued"
        assert latest.error == "recovered_after_process_restart"

    service.shutdown()
