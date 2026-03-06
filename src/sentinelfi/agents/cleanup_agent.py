from __future__ import annotations

import uuid

from sentinelfi.domain.models import CleanupTask, GstFinding, LeakFinding, LeakType


class CleanupPlanner:
    """
    Produces actionable write tasks. Execution stays approval-gated.
    """

    def plan(self, leak_findings: list[LeakFinding], gst_findings: list[GstFinding]) -> list[CleanupTask]:
        tasks: list[CleanupTask] = []

        tax_related = [f for f in leak_findings if f.leak_type == LeakType.TAX_MISCATEGORY]
        if tax_related:
            tasks.append(
                CleanupTask(
                    task_id=f"task-{uuid.uuid4().hex[:8]}",
                    title="Reclassify miscategorized tax-sensitive entries",
                    task_type="ledger_reclass",
                    payload={"finding_ids": [f.finding_id for f in tax_related], "target_category": "IT Expenses"},
                )
            )

        duplicate = [f for f in leak_findings if f.leak_type in {LeakType.DUPLICATE_SUBSCRIPTION, LeakType.SAAS_SPRAWL}]
        if duplicate:
            tasks.append(
                CleanupTask(
                    task_id=f"task-{uuid.uuid4().hex[:8]}",
                    title="Draft cancellation and refund emails",
                    task_type="email_draft",
                    payload={"finding_ids": [f.finding_id for f in duplicate]},
                )
            )

        missing_docs = [g for g in gst_findings if not g.has_gst_invoice]
        if missing_docs:
            tasks.append(
                CleanupTask(
                    task_id=f"task-{uuid.uuid4().hex[:8]}",
                    title="Collect missing invoices from inbox and chats",
                    task_type="invoice_fetch",
                    payload={"tx_ids": [g.tx_id for g in missing_docs]},
                )
            )

            tasks.append(
                CleanupTask(
                    task_id=f"task-{uuid.uuid4().hex[:8]}",
                    title="Prepare GST reconciliation workbook for CA",
                    task_type="gst_recon",
                    payload={"gst_finding_ids": [g.finding_id for g in missing_docs]},
                )
            )

        return tasks
