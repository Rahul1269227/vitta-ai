from __future__ import annotations

from sentinelfi.domain.models import AuditOutput


def render_markdown(output: AuditOutput, client_name: str, report_period: str) -> str:
    summary = output.summary
    lines = [
        "# Sentinel-Fi Leakage Audit Report",
        "",
        f"Client: {client_name}",
        f"Report Period: {report_period}",
        f"Audit ID: {summary.audit_id}",
        "",
        "## Executive Summary",
        f"- Transactions scanned: {summary.total_transactions}",
        f"- Leak findings: {summary.leak_count}",
        f"- Estimated annual leakage: INR {summary.total_leak_amount:,.2f}",
        f"- Potential missed ITC: INR {summary.missed_itc:,.2f}",
        f"- Risk score: {summary.risk_score}/100",
        "",
        "## Findings",
    ]

    if not output.findings:
        lines.append("- No major leakage findings detected.")
    else:
        for finding in output.findings:
            lines.append(
                f"- [{finding.severity}] {finding.leak_type.value}: INR {finding.amount_impact:,.2f} - {finding.description}"
            )

    lines.append("")
    lines.append("## GST Findings")
    if not output.gst_findings:
        lines.append("- No GST anomalies detected.")
    else:
        for item in output.gst_findings:
            lines.append(
                f"- Tx {item.tx_id}: {item.issue} (Potential ITC INR {item.potential_itc_amount:,.2f})"
            )

    lines.append("")
    lines.append("## Cleanup Tasks")
    if not output.cleanup_tasks:
        lines.append("- No cleanup actions required.")
    else:
        for task in output.cleanup_tasks:
            lines.append(f"- {task.title} [{task.task_type}] (approval required)")

    return "\n".join(lines)
