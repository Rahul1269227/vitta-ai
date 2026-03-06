from __future__ import annotations

from datetime import UTC, datetime

import httpx

from sentinelfi.domain.models import Transaction


class StripeConnector:
    BASE_URL = "https://api.stripe.com/v1"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def fetch_transactions(self, limit: int = 100) -> list[Transaction]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        params = {"limit": limit}
        with httpx.Client(timeout=20) as client:
            resp = client.get(f"{self.BASE_URL}/balance_transactions", headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json().get("data", [])

        txs: list[Transaction] = []
        for row in data:
            created = datetime.fromtimestamp(row["created"], tz=UTC).date()
            txs.append(
                Transaction(
                    tx_id=row["id"],
                    tx_date=created,
                    description=row.get("description") or row.get("type", "stripe_tx"),
                    amount=abs(float(row.get("amount", 0))) / 100,
                    currency=str(row.get("currency", "inr")).upper(),
                    is_debit=float(row.get("amount", 0)) < 0,
                    merchant="Stripe",
                    metadata=row,
                )
            )
        return txs
