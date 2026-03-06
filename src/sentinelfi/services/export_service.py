"""Transaction export service – CSV, QuickBooks IIF, Xero CSV, JSON.

Ported from transaction-ai and adapted for VittaAI's domain models.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any

from sentinelfi.core.logging import get_logger

log = get_logger(__name__)

# Mapping from VittaAI category → QuickBooks account name
_QB_ACCOUNT_MAP: dict[str, str] = {
    "food_dining": "Meals & Entertainment",
    "groceries": "Groceries",
    "transport": "Auto & Travel",
    "fuel": "Auto & Travel",
    "shopping": "Merchandise",
    "bills": "Utilities",
    "rent": "Rent",
    "health": "Medical",
    "education": "Education",
    "entertainment": "Meals & Entertainment",
    "travel": "Auto & Travel",
    "fees_charges": "Bank Charges",
    "insurance": "Insurance",
    "investments": "Investments",
    "subscriptions_memberships": "Subscriptions",
    "professional_services": "Professional Fees",
    "electronics_technology": "Office Equipment",
    "charity_donations": "Charitable Contributions",
    "taxes_government": "Taxes",
    "transfers_upi": "Transfers",
    "income_salary": "Income",
    "atm_cash": "Cash Withdrawals",
}

# Mapping from VittaAI category → Xero account code
_XERO_ACCOUNT_MAP: dict[str, str] = {
    "food_dining": "200",
    "groceries": "201",
    "transport": "202",
    "fuel": "202",
    "shopping": "203",
    "bills": "204",
    "rent": "205",
    "health": "206",
    "education": "207",
    "entertainment": "208",
    "travel": "202",
    "fees_charges": "209",
    "insurance": "210",
    "investments": "211",
    "subscriptions_memberships": "212",
    "professional_services": "213",
    "electronics_technology": "214",
    "charity_donations": "215",
    "taxes_government": "216",
    "transfers_upi": "217",
    "income_salary": "218",
    "atm_cash": "219",
}


class ExportService:
    """Stateless helpers to export classified transactions to various formats."""

    # ------------------------------------------------------------------
    # CSV
    # ------------------------------------------------------------------

    @staticmethod
    def to_csv(
        transactions: list[dict[str, Any]],
        include_explanations: bool = False,
    ) -> str:
        if not transactions:
            return ""

        cols = [
            "date",
            "amount",
            "currency",
            "category",
            "subcategory",
            "merchant",
            "description",
            "confidence",
            "method",
            "requires_review",
        ]
        if include_explanations:
            cols.extend(["explanations", "ensemble_votes"])

        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=cols)
        writer.writeheader()

        for txn in transactions:
            row: dict[str, Any] = {
                "date": txn.get("date", ""),
                "amount": txn.get("amount", ""),
                "currency": txn.get("currency", "INR"),
                "category": txn.get("category", ""),
                "subcategory": txn.get("subcategory", ""),
                "merchant": txn.get("merchant", ""),
                "description": txn.get("description", txn.get("text", "")),
                "confidence": txn.get("confidence", 0.0),
                "method": txn.get("method", ""),
                "requires_review": txn.get("requires_review", False),
            }
            if include_explanations:
                row["explanations"] = "; ".join(txn.get("explanations", []))
                votes = txn.get("ensemble_votes", {})
                parts: list[str] = []
                for method in ("rule", "ml", "llm", "mcc"):
                    v = votes.get(method)
                    if v:
                        parts.append(f"{method}:{v.get('category', 'N/A')}")
                row["ensemble_votes"] = ", ".join(parts)
            writer.writerow(row)

        return buf.getvalue()

    # ------------------------------------------------------------------
    # QuickBooks IIF
    # ------------------------------------------------------------------

    @staticmethod
    def to_quickbooks_iif(transactions: list[dict[str, Any]]) -> str:
        lines = [
            "!TRNS\tDATE\tACCNT\tAMOUNT\tMEMO",
            "!SPL\tDATE\tACCNT\tAMOUNT\tMEMO",
            "!ENDTRNS",
        ]
        for txn in transactions:
            date_val = txn.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
            amount = abs(float(txn.get("amount", 0)))
            category = txn.get("category", "other")
            account = _QB_ACCOUNT_MAP.get(category, "Other Expenses")
            memo = txn.get("description", txn.get("text", ""))

            lines.append(f"TRNS\t{date_val}\t{account}\t-{amount:.2f}\t{memo}")
            lines.append(f"SPL\t{date_val}\tBank Account\t{amount:.2f}\t{memo}")
            lines.append("ENDTRNS")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Xero CSV
    # ------------------------------------------------------------------

    @staticmethod
    def to_xero_csv(transactions: list[dict[str, Any]]) -> str:
        buf = io.StringIO()
        fields = [
            "*ContactName",
            "*InvoiceNumber",
            "*InvoiceDate",
            "*DueDate",
            "Description",
            "Quantity",
            "UnitAmount",
            "AccountCode",
            "*TaxType",
            "TaxAmount",
            "LineAmount",
        ]
        writer = csv.DictWriter(buf, fieldnames=fields)
        writer.writeheader()

        for txn in transactions:
            date_val = txn.get("date", datetime.now(timezone.utc).strftime("%d/%m/%Y"))
            amount = abs(float(txn.get("amount", 0)))
            category = txn.get("category", "other")
            account_code = _XERO_ACCOUNT_MAP.get(category, "299")

            writer.writerow(
                {
                    "*ContactName": txn.get("merchant", ""),
                    "*InvoiceNumber": f"TXN-{txn.get('id', '')}",
                    "*InvoiceDate": date_val,
                    "*DueDate": date_val,
                    "Description": txn.get("description", txn.get("text", "")),
                    "Quantity": "1",
                    "UnitAmount": f"{amount:.2f}",
                    "AccountCode": account_code,
                    "*TaxType": "GST",
                    "TaxAmount": f"{amount * 0.18:.2f}",
                    "LineAmount": f"{amount:.2f}",
                }
            )

        return buf.getvalue()

    # ------------------------------------------------------------------
    # JSON
    # ------------------------------------------------------------------

    @staticmethod
    def to_json(
        transactions: list[dict[str, Any]],
        variant: str = "standard",
    ) -> str:
        if variant == "quickbooks":
            qb = []
            for txn in transactions:
                amount = abs(float(txn.get("amount", 0)))
                qb.append(
                    {
                        "TxnDate": txn.get("date", ""),
                        "Amount": amount,
                        "AccountRef": {"name": _QB_ACCOUNT_MAP.get(txn.get("category", "other"), "Other Expenses")},
                        "Line": [
                            {
                                "Amount": amount,
                                "DetailType": "AccountBasedExpenseLineDetail",
                                "AccountBasedExpenseLineDetail": {
                                    "AccountRef": {
                                        "name": _QB_ACCOUNT_MAP.get(txn.get("category", "other"), "Other Expenses")
                                    }
                                },
                            }
                        ],
                    }
                )
            return json.dumps({"Transaction": qb}, indent=2)

        if variant == "xero":
            xero = []
            for txn in transactions:
                xero.append(
                    {
                        "Type": "ACCREC",
                        "Contact": {"Name": txn.get("merchant", "")},
                        "Date": txn.get("date", ""),
                        "LineItems": [
                            {
                                "Description": txn.get("description", txn.get("text", "")),
                                "Quantity": 1,
                                "UnitAmount": abs(float(txn.get("amount", 0))),
                                "AccountCode": _XERO_ACCOUNT_MAP.get(txn.get("category", "other"), "299"),
                            }
                        ],
                    }
                )
            return json.dumps({"Invoices": xero}, indent=2)

        return json.dumps(transactions, indent=2, default=str)
