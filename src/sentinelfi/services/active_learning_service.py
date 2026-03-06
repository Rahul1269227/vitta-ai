from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sentinelfi.core.config import Settings
from sentinelfi.core.logging import get_logger
from sentinelfi.repositories.db import session_scope
from sentinelfi.repositories.feedback_repository import FeedbackRepository
from sentinelfi.repositories.models import ModelTrainingRun
from sentinelfi.services.ml_features import build_ml_feature_text
from sentinelfi.services.ml_training_service import append_feedback_jsonl, train_ml_classifier

log = get_logger(__name__)


@dataclass
class FeedbackCorrection:
    tx_id: str
    corrected_category: str
    note: str | None = None


class ActiveLearningService:
    def __init__(self, settings: Settings, on_retrain_success: Callable[[], None] | None = None):
        self.settings = settings
        self.on_retrain_success = on_retrain_success
        self._training_executor = ThreadPoolExecutor(max_workers=1)
        self._state_lock = threading.Lock()
        self._training_in_progress = False

    def submit_feedback(
        self,
        audit_id: str,
        corrections: list[FeedbackCorrection],
        source: str = "api",
        auto_retrain: bool = True,
    ) -> dict[str, Any]:
        accepted_rows: list[dict[str, Any]] = []
        rejected: list[dict[str, str]] = []
        created_at = datetime.now(timezone.utc)

        with session_scope(self.settings) as session:
            repo = FeedbackRepository(session)

            for correction in corrections:
                label = correction.corrected_category.strip().lower()
                if label not in {"business", "personal"}:
                    rejected.append({"tx_id": correction.tx_id, "reason": "invalid_category"})
                    continue

                tx = repo.get_classified_tx(audit_id=audit_id, tx_id=correction.tx_id)
                if tx is None:
                    rejected.append({"tx_id": correction.tx_id, "reason": "tx_not_found"})
                    continue

                metadata: dict[str, Any]
                try:
                    metadata = json.loads(tx.metadata_json) if tx.metadata_json else {}
                except json.JSONDecodeError:
                    metadata = {}

                training_text = build_ml_feature_text(
                    pii_redacted_description=tx.pii_redacted_description,
                    merchant=tx.merchant,
                    metadata=metadata,
                )

                feedback_id = f"fb-{uuid.uuid4().hex[:12]}"
                repo.add_feedback(
                    feedback_id=feedback_id,
                    created_at=created_at,
                    audit_id=audit_id,
                    tx_id=tx.tx_id,
                    corrected_category=label,
                    predicted_category=tx.predicted_category,
                    training_text=training_text,
                    note=correction.note,
                    source=source,
                )

                accepted_rows.append(
                    {
                        "text": training_text,
                        "label": label,
                        "source": f"feedback_{source}",
                        "category": "feedback",
                    }
                )

            if accepted_rows:
                append_feedback_jsonl(Path(self.settings.ml_feedback_dataset_path), accepted_rows)

            pending_feedback = repo.count_feedback(statuses=["pending"])
            latest_run = repo.latest_training_run()
            has_incomplete_training = bool(repo.list_incomplete_training_runs())
            should_retrain = (
                auto_retrain
                and pending_feedback >= self.settings.ml_feedback_retrain_threshold
                and self._cooldown_elapsed(latest_run)
                and not has_incomplete_training
                and not self._is_training_in_progress()
            )

            training_run_id: str | None = None
            if should_retrain:
                training_run_id = f"train-{uuid.uuid4().hex[:12]}"
                repo.create_training_run(
                    run_id=training_run_id,
                    started_at=datetime.now(timezone.utc),
                    trigger="feedback_threshold",
                    model_path=self.settings.ml_model_path,
                    feedback_rows_used=pending_feedback,
                    status="queued",
                )

            session.commit()

        if training_run_id:
            self._enqueue_training_job(training_run_id)

        return {
            "accepted_count": len(accepted_rows),
            "rejected": rejected,
            "pending_feedback_count": pending_feedback,
            "retrain_triggered": bool(training_run_id),
            "training_run_id": training_run_id,
        }

    def trigger_retrain(self, trigger: str = "manual") -> dict[str, Any]:
        with session_scope(self.settings) as session:
            repo = FeedbackRepository(session)
            pending_feedback = repo.count_feedback(statuses=["pending"])
            incomplete_runs = repo.list_incomplete_training_runs()
            if incomplete_runs:
                existing_run_id = incomplete_runs[0].id
                return {
                    "training_run_id": existing_run_id,
                    "pending_feedback_count": pending_feedback,
                    "status": "already_running",
                }

            training_run_id = f"train-{uuid.uuid4().hex[:12]}"
            repo.create_training_run(
                run_id=training_run_id,
                started_at=datetime.now(timezone.utc),
                trigger=trigger,
                model_path=self.settings.ml_model_path,
                feedback_rows_used=pending_feedback,
                status="queued",
            )
            session.commit()

        self._enqueue_training_job(training_run_id)
        return {
            "training_run_id": training_run_id,
            "pending_feedback_count": pending_feedback,
            "status": "queued",
        }

    def status(self) -> dict[str, Any]:
        with session_scope(self.settings) as session:
            repo = FeedbackRepository(session)
            latest = repo.latest_training_run()
            pending = repo.count_feedback(statuses=["pending"])
            total = repo.count_feedback()

        return {
            "pending_feedback_count": pending,
            "total_feedback_count": total,
            "training_in_progress": self._is_training_in_progress(),
            "latest_training_run": self._training_run_payload(latest),
        }

    def export_feedback(self, statuses: list[str] | None = None) -> list[dict[str, Any]]:
        with session_scope(self.settings) as session:
            rows = FeedbackRepository(session).list_feedback(statuses=statuses)
        return [
            {
                "id": row.id,
                "created_at": row.created_at.isoformat(),
                "audit_id": row.audit_id,
                "tx_id": row.tx_id,
                "corrected_category": row.corrected_category,
                "predicted_category": row.predicted_category,
                "training_text": row.training_text,
                "note": row.note,
                "source": row.source,
                "status": row.status,
                "applied_model_version": row.applied_model_version,
                "applied_at": row.applied_at.isoformat() if row.applied_at else None,
            }
            for row in rows
        ]

    def recover_incomplete_training_runs(self) -> int:
        with session_scope(self.settings) as session:
            repo = FeedbackRepository(session)
            rows = repo.list_incomplete_training_runs()
            if not rows:
                return 0
            for row in rows:
                row.status = "queued"
                row.error = "recovered_after_process_restart"
                session.add(row)
            run_ids = [row.id for row in rows]
            session.commit()

        for run_id in run_ids:
            self._enqueue_training_job(run_id)

        log.info("retrain_jobs_recovered", count=len(run_ids))
        return len(run_ids)

    def shutdown(self) -> None:
        self._training_executor.shutdown(wait=False, cancel_futures=True)

    def _enqueue_training_job(self, training_run_id: str) -> None:
        self._training_executor.submit(self._run_training_job, training_run_id)

    def _is_training_in_progress(self) -> bool:
        with self._state_lock:
            return self._training_in_progress

    def _run_training_job(self, training_run_id: str) -> None:
        with self._state_lock:
            self._training_in_progress = True
        started_at = datetime.now(timezone.utc)
        try:
            with session_scope(self.settings) as session:
                repo = FeedbackRepository(session)
                run = repo.get_training_run(training_run_id)
                if run is None:
                    log.warning("retrain_run_missing", training_run_id=training_run_id)
                    return
                if run:
                    run.status = "running"
                    run.started_at = started_at
                    session.add(run)
                    session.commit()

                feedback_rows = repo.list_feedback()

            training_data = [
                {
                    "text": row.training_text,
                    "label": row.corrected_category,
                    "source": f"feedback_{row.source}",
                    "category": "feedback",
                }
                for row in feedback_rows
            ]

            if len(training_data) < self.settings.ml_feedback_min_rows:
                with session_scope(self.settings) as session:
                    repo = FeedbackRepository(session)
                    run = repo.get_training_run(training_run_id)
                    if run:
                        run.status = "skipped"
                        run.finished_at = datetime.now(timezone.utc)
                        run.error = (
                            f"insufficient_feedback_rows:{len(training_data)}"
                            f"<{self.settings.ml_feedback_min_rows}"
                        )
                        session.add(run)
                        session.commit()
                return

            metrics = train_ml_classifier(
                output_model=Path(self.settings.ml_model_path),
                metrics_path=Path(self.settings.ml_metrics_path),
                feedback_records=training_data,
            )

            model_version = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            feedback_ids = [row.id for row in feedback_rows if row.status == "pending"]

            with session_scope(self.settings) as session:
                repo = FeedbackRepository(session)
                repo.mark_feedback_applied(
                    feedback_ids=feedback_ids,
                    model_version=model_version,
                    applied_at=datetime.now(timezone.utc),
                )
                run = repo.get_training_run(training_run_id)
                if run:
                    run.status = "success"
                    run.finished_at = datetime.now(timezone.utc)
                    run.feedback_rows_used = len(training_data)
                    run.metrics_json = json.dumps(metrics)
                    session.add(run)
                session.commit()

            log.info(
                "retrain_complete",
                training_run_id=training_run_id,
                feedback_rows=len(training_data),
                model_path=self.settings.ml_model_path,
                accuracy=metrics.get("accuracy"),
                f1_macro=metrics.get("f1_macro"),
            )
            if self.on_retrain_success is not None:
                self.on_retrain_success()
        except Exception as exc:  # noqa: BLE001
            log.exception("retrain_failed", training_run_id=training_run_id, error=str(exc))
            with session_scope(self.settings) as session:
                repo = FeedbackRepository(session)
                run = repo.get_training_run(training_run_id)
                if run:
                    run.status = "failed"
                    run.finished_at = datetime.now(timezone.utc)
                    run.error = str(exc)
                    session.add(run)
                    session.commit()
        finally:
            with self._state_lock:
                self._training_in_progress = False

    def _cooldown_elapsed(self, latest_run: ModelTrainingRun | None) -> bool:
        if latest_run is None or latest_run.started_at is None:
            return True

        started_at = latest_run.started_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)

        cooldown = timedelta(minutes=self.settings.ml_retrain_cooldown_minutes)
        return datetime.now(timezone.utc) >= started_at + cooldown

    def _training_run_payload(self, run: ModelTrainingRun | None) -> dict[str, Any] | None:
        if run is None:
            return None
        return {
            "id": run.id,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "status": run.status,
            "trigger": run.trigger,
            "feedback_rows_used": run.feedback_rows_used,
            "model_path": run.model_path,
            "error": run.error,
        }
