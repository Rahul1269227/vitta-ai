from __future__ import annotations

from sentinelfi.core.config import Settings
from sentinelfi.domain.models import AuditInput, AuditOutput, ClassifiedTransaction
from sentinelfi.graph.audit_graph import AuditGraphFactory, build_audit_output
from sentinelfi.repositories.audit_repository import AuditRepository
from sentinelfi.repositories.db import session_scope


class AuditOrchestrator:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.graph = AuditGraphFactory(settings).build()

    def run(self, request: AuditInput) -> AuditOutput:
        output, _classified = self.run_with_details(request)
        return output

    def run_with_details(self, request: AuditInput) -> tuple[AuditOutput, list[ClassifiedTransaction]]:
        final_state = self.graph.invoke({"request": request})
        output = build_audit_output(final_state)
        classified = final_state.get("classified_transactions", [])

        with session_scope(self.settings) as session:
            repo = AuditRepository(session)
            repo.save_audit_output(request.source_type.value, output)
            repo.save_classified_transactions(output.summary.audit_id, classified)

        return output, classified
