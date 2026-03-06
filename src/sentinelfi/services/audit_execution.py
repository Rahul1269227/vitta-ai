from __future__ import annotations

from pathlib import Path

from sentinelfi.api.schemas import AuditRunRequest, AuditRunResponse
from sentinelfi.core.config import Settings
from sentinelfi.domain.models import AuditInput, ClassifiedTransaction
from sentinelfi.reports.leakage_markdown import render_markdown
from sentinelfi.reports.leakage_pdf import LeakageReportPDFBuilder
from sentinelfi.services.audit_orchestrator import AuditOrchestrator


class AuditExecutionService:
    def __init__(self, settings: Settings, orchestrator: AuditOrchestrator | None = None):
        self.settings = settings
        self.orchestrator = orchestrator or AuditOrchestrator(settings)

    def execute(self, payload: AuditRunRequest) -> tuple[AuditRunResponse, list[ClassifiedTransaction]]:
        output, classified = self.orchestrator.run_with_details(
            AuditInput(
                source_type=payload.source_type,
                source_path=payload.source_path,
                source_config=payload.source_config,
            )
        )

        markdown_path = None
        if payload.generate_markdown:
            markdown = render_markdown(output, payload.client_name, payload.report_period)
            p = Path("output/reports") / f"{output.summary.audit_id}.md"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(markdown, encoding="utf-8")
            markdown_path = str(p)

        pdf_path = None
        if payload.generate_pdf:
            builder = LeakageReportPDFBuilder()
            p = Path("output/pdf") / f"{output.summary.audit_id}.pdf"
            pdf_path = builder.build(output, payload.client_name, payload.report_period, str(p))

        return AuditRunResponse(
            output=output,
            markdown_report_path=markdown_path,
            pdf_report_path=pdf_path,
        ), classified
