from __future__ import annotations

from typing import Any


def build_ml_feature_text(
    pii_redacted_description: str,
    merchant: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    parts = [pii_redacted_description]

    upi = metadata.get("upi") if isinstance(metadata, dict) else None
    if isinstance(upi, dict):
        if upi.get("merchant_token"):
            parts.append(f"upi_merchant:{upi.get('merchant_token')}")
        if upi.get("p2p_likely"):
            parts.append("upi_p2p")
        if upi.get("p2m_likely"):
            parts.append("upi_p2m")

    if merchant:
        parts.append(f"merchant:{merchant.lower()}")

    return " | ".join(parts)
