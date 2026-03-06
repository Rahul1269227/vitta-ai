from sentinelfi.core.config import Settings
from sentinelfi.domain.models import AuditInput, SourceType
from sentinelfi.repositories.db import init_db
from sentinelfi.services.audit_orchestrator import AuditOrchestrator


def test_audit_orchestrator_runs_on_sample_csv(tmp_path) -> None:
    settings = Settings(database_url=f"sqlite:///{tmp_path}/test.db", enable_local_embeddings=False)
    init_db(settings)
    orchestrator = AuditOrchestrator(settings)
    output = orchestrator.run(
        AuditInput(
            source_type=SourceType.CSV,
            source_path="data/sample_transactions.csv",
            source_config={},
        )
    )

    assert output.summary.total_transactions > 0
    assert output.summary.leak_count >= 1
    assert len(output.classification_decisions) == output.summary.total_transactions
    assert output.summary.avg_classification_confidence >= 0
