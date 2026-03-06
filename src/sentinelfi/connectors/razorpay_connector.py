from __future__ import annotations

from datetime import UTC, datetime

import httpx

from sentinelfi.domain.models import Transaction


class RazorpayConnector:
    BASE_URL = "https://api.razorpay.com/v1"

    def __init__(self, key_id: str, key_secret: str):
        self.auth = (key_id, key_secret)

    def fetch_transactions(self, count: int = 100) -> list[Transaction]:
        params = {"count": count}
        with httpx.Client(timeout=20, auth=self.auth) as client:
            resp = client.get(f"{self.BASE_URL}/payments", params=params)
            resp.raise_for_status()
            items = resp.json().get("items", [])

        txs: list[Transaction] = []
        for item in items:
            created = datetime.fromtimestamp(item["created_at"], tz=UTC).date()
            amount = float(item.get("amount", 0)) / 100
            txs.append(
                Transaction(
                    tx_id=item["id"],
                    tx_date=created,
                    description=item.get("description") or item.get("notes", {}).get("purpose", "razorpay_payment"),
                    amount=abs(amount),
                    currency=str(item.get("currency", "INR")).upper(),
                    is_debit=False,
                    merchant=item.get("method", "Razorpay"),
                    metadata=item,
                )
            )
        return txs
