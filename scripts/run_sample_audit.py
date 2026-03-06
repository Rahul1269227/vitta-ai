#!/usr/bin/env python3
from __future__ import annotations

from sentinelfi.core.config import get_settings
from sentinelfi.domain.models import AuditInput, SourceType
from sentinelfi.reports.leakage_markdown import render_markdown
from sentinelfi.reports.leakage_pdf import LeakageReportPDFBuilder
from sentinelfi.repositories.db import init_db
from sentinelfi.services.audit_orchestrator import AuditOrchestrator


def main() -> int:
    settings = get_settings()
    init_db(settings)

    orchestrator = AuditOrchestrator(settings)
    output = orchestrator.run(
        AuditInput(
            source_type=SourceType.CSV,
            source_path="data/sample_transactions.csv",
            source_config={},
        )
    )

    markdown = render_markdown(output, client_name="Demo SMB", report_period="Nov 2025")
    md_path = f"output/reports/{output.summary.audit_id}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown)

    pdf_path = LeakageReportPDFBuilder().build(output, "Demo SMB", "Nov 2025", f"output/pdf/{output.summary.audit_id}.pdf")

    print(f"Audit ID: {output.summary.audit_id}")
    print(f"Leak findings: {output.summary.leak_count}")
    print(f"Estimated annual leakage: INR {output.summary.total_leak_amount:,.2f}")
    print(f"Markdown: {md_path}")
    print(f"PDF: {pdf_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
