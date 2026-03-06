from __future__ import annotations

from datetime import datetime

from sqlalchemy import func
from sqlmodel import Session, select

from sentinelfi.repositories.models import ClassifiedTxRecord, FeedbackRecord, ModelTrainingRun


class FeedbackRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_classified_tx(self, audit_id: str, tx_id: str) -> ClassifiedTxRecord | None:
        statement = select(ClassifiedTxRecord).where(
            ClassifiedTxRecord.audit_id == audit_id,
            ClassifiedTxRecord.tx_id == tx_id,
        )
        return self.session.exec(statement).first()

    def add_feedback(
        self,
        feedback_id: str,
        created_at: datetime,
        audit_id: str,
        tx_id: str,
        corrected_category: str,
        predicted_category: str,
        training_text: str,
        note: str | None = None,
        source: str = "api",
    ) -> FeedbackRecord:
        row = FeedbackRecord(
            id=feedback_id,
            created_at=created_at,
            audit_id=audit_id,
            tx_id=tx_id,
            corrected_category=corrected_category,
            predicted_category=predicted_category,
            training_text=training_text,
            note=note,
            source=source,
        )
        self.session.add(row)
        return row

    def list_feedback(self, statuses: list[str] | None = None) -> list[FeedbackRecord]:
        statement = select(FeedbackRecord).order_by(FeedbackRecord.created_at.asc())
        if statuses:
            statement = statement.where(FeedbackRecord.status.in_(statuses))
        return list(self.session.exec(statement).all())

    def count_feedback(self, statuses: list[str] | None = None) -> int:
        statement = select(func.count(FeedbackRecord.id))
        if statuses:
            statement = statement.where(FeedbackRecord.status.in_(statuses))
        result = self.session.exec(statement).one()
        return int(result or 0)

    def mark_feedback_applied(
        self,
        feedback_ids: list[str],
        model_version: str,
        applied_at: datetime,
    ) -> None:
        if not feedback_ids:
            return

        statement = select(FeedbackRecord).where(FeedbackRecord.id.in_(feedback_ids))
        rows = list(self.session.exec(statement).all())
        for row in rows:
            row.status = "applied"
            row.applied_model_version = model_version
            row.applied_at = applied_at
            self.session.add(row)

    def create_training_run(
        self,
        run_id: str,
        started_at: datetime,
        trigger: str,
        model_path: str,
        feedback_rows_used: int,
        status: str = "running",
    ) -> ModelTrainingRun:
        row = ModelTrainingRun(
            id=run_id,
            started_at=started_at,
            status=status,
            trigger=trigger,
            model_path=model_path,
            feedback_rows_used=feedback_rows_used,
        )
        self.session.add(row)
        return row

    def get_training_run(self, run_id: str) -> ModelTrainingRun | None:
        return self.session.get(ModelTrainingRun, run_id)

    def latest_training_run(self) -> ModelTrainingRun | None:
        statement = select(ModelTrainingRun).order_by(ModelTrainingRun.started_at.desc()).limit(1)
        return self.session.exec(statement).first()

    def list_incomplete_training_runs(self) -> list[ModelTrainingRun]:
        statement = select(ModelTrainingRun).where(
            ModelTrainingRun.status.in_(["queued", "running"])
        )
        return list(self.session.exec(statement).all())
