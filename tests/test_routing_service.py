from __future__ import annotations

from datetime import date

from sentinelfi.domain.models import NormalizedTransaction
from sentinelfi.services.routing_service import EmbeddingRouter


def _tx(tx_id: str, desc: str, upi_payload: dict | None = None) -> NormalizedTransaction:
    metadata = {"upi": upi_payload} if upi_payload else {}
    return NormalizedTransaction(
        tx_id=tx_id,
        tx_date=date(2025, 1, 1),
        description=desc,
        amount=250,
        normalized_description=desc,
        pii_redacted_description=desc,
        metadata=metadata,
    )


def test_router_uses_upi_fast_path_for_known_merchant() -> None:
    router = EmbeddingRouter(enable_local_embeddings=False)
    tx = _tx(
        "u1",
        "upi payment",
        {
            "is_upi": True,
            "merchant_token": "swiggy",
            "p2m_likely": True,
            "p2p_likely": False,
        },
    )

    slm, llm, decisions = router.route([tx])
    assert len(slm) == 1
    assert len(llm) == 0
    assert decisions[0].reason == "upi-known-merchant-fast-path"
