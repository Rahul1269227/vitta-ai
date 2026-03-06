from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from sentinelfi.domain.models import AuditOutput


class LeakageReportPDFBuilder:
    def __init__(self, brand_name: str = "Sentinel-Fi"):
        self.brand_name = brand_name

    def _draw_header(self, canv: canvas.Canvas, doc):
        width, height = A4
        canv.saveState()
        canv.setFillColor(colors.HexColor("#0B132B"))
        canv.rect(0, height - 28 * mm, width, 28 * mm, stroke=0, fill=1)
        canv.setFillColor(colors.white)
        canv.setFont("Helvetica-Bold", 16)
        canv.drawString(15 * mm, height - 16 * mm, f"{self.brand_name} Leakage Audit Report")
        canv.setFont("Helvetica", 9)
        canv.drawString(15 * mm, height - 22 * mm, "Confidential: For client internal finance use")
        canv.restoreState()

    def build(self, output: AuditOutput, client_name: str, report_period: str, out_path: str) -> str:
        target = Path(out_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        doc = SimpleDocTemplate(
            str(target),
            pagesize=A4,
            leftMargin=15 * mm,
            rightMargin=15 * mm,
            topMargin=35 * mm,
            bottomMargin=15 * mm,
        )

        styles = getSampleStyleSheet()
        h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=13, textColor=colors.HexColor("#0B132B"))
        p = ParagraphStyle("p", parent=styles["Normal"], fontSize=9.5, leading=12.5)
        red = ParagraphStyle("red", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=11, textColor=colors.HexColor("#B00020"))

        summary = output.summary
        story = [
            Paragraph("Executive Summary", h1),
            Paragraph(f"Client: <b>{client_name}</b>", p),
            Paragraph(f"Report period: <b>{report_period}</b>", p),
            Paragraph(f"Transactions scanned: <b>{summary.total_transactions}</b>", p),
            Paragraph(f"Estimated annual leakage: <b>INR {summary.total_leak_amount:,.2f}</b>", red),
            Paragraph(f"Potential missed ITC: <b>INR {summary.missed_itc:,.2f}</b>", red),
            Paragraph(f"Risk score: <b>{summary.risk_score}/100</b>", p),
            Spacer(1, 3 * mm),
            Paragraph("Leak Findings", h1),
        ]

        leak_rows = [["Type", "Severity", "Impact (INR)", "Confidence", "Action"]]
        for finding in output.findings:
            leak_rows.append(
                [
                    finding.leak_type.value.replace("_", " "),
                    finding.severity,
                    f"{finding.amount_impact:,.2f}",
                    f"{finding.confidence:.2f}",
                    finding.suggested_action,
                ]
            )
        if len(leak_rows) == 1:
            leak_rows.append(["none", "-", "0.00", "-", "No major leaks detected"])

        leak_table = Table(leak_rows, colWidths=[34 * mm, 18 * mm, 24 * mm, 20 * mm, 74 * mm])
        leak_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B132B")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.4),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#A9B4C2")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TEXTCOLOR", (2, 1), (2, -1), colors.HexColor("#B00020")),
            ("FONTNAME", (2, 1), (2, -1), "Helvetica-Bold"),
        ]))
        story.append(leak_table)
        story.append(Spacer(1, 4 * mm))

        story.append(Paragraph("Cleanup Tasks (Approval Required)", h1))
        for task in output.cleanup_tasks:
            story.append(Paragraph(f"- {task.title} ({task.task_type})", p))

        doc.build(story, onFirstPage=self._draw_header, onLaterPages=self._draw_header)
        return str(target)
