from __future__ import annotations

from datetime import date

from sentinelfi.core.config import Settings
from sentinelfi.domain.models import ClassifiedTransaction, NormalizedTransaction, TxCategory
from sentinelfi.graph.audit_graph import AuditGraphFactory
from sentinelfi.services.routing_service import RouteDecision


def _tx(tx_id: str, text: str) -> NormalizedTransaction:
    return NormalizedTransaction(
        tx_id=tx_id,
        tx_date=date(2026, 1, 1),
        description=text,
        amount=499.0,
        is_debit=True,
        normalized_description=text.lower(),
        pii_redacted_description=text.lower(),
    )


def test_after_routing_supervisor_branches_correctly() -> None:
    factory = AuditGraphFactory(Settings(enable_local_embeddings=False))

    assert factory._after_routing_supervisor({"routed_to_slm": [{}], "routed_to_llm": []}) == "slm_classifier"
    assert factory._after_routing_supervisor({"routed_to_slm": [], "routed_to_llm": [{}]}) == "llm_reasoner"
    assert (
        factory._after_routing_supervisor({"routed_to_slm": [], "routed_to_llm": []})
        == "finalize_classification"
    )


def test_after_slm_classifier_branches_correctly() -> None:
    factory = AuditGraphFactory(Settings(enable_local_embeddings=False))

    assert factory._after_slm_classifier({"routed_to_llm": [{}], "slm_escalated_transactions": []}) == "llm_reasoner"
    assert (
        factory._after_slm_classifier({"routed_to_llm": [], "slm_escalated_transactions": [{}]})
        == "llm_reasoner"
    )
    assert (
        factory._after_slm_classifier({"routed_to_llm": [], "slm_escalated_transactions": []})
        == "finalize_classification"
    )


def test_routing_supervisor_reroutes_llm_items_to_slm_when_llm_unavailable() -> None:
    factory = AuditGraphFactory(Settings(enable_local_embeddings=False))
    tx = _tx("tx-1", "complex upi narration")
    factory.router.route = lambda _txs: ([], [tx], [RouteDecision(tx=tx, route="llm", score=0.2, reason="test")])  # type: ignore[method-assign]

    state = factory.routing_supervisor({"remaining_transactions": [tx]})

    assert state["routed_to_llm"] == []
    assert len(state["routed_to_slm"]) == 1
    assert state["routed_to_slm"][0].tx_id == "tx-1"
    assert state["route_reason_by_tx_id"]["tx-1"].endswith("llm_unavailable_fallback")


def test_slm_marks_human_review_when_escalation_needed_but_llm_unavailable() -> None:
    factory = AuditGraphFactory(Settings(enable_local_embeddings=False))
    tx = _tx("tx-2", "ambiguous merchant")
    ambiguous = ClassifiedTransaction(
        **tx.model_dump(),
        category=TxCategory.UNKNOWN,
        confidence=0.55,
        classifier="slm",
        explanations=["insufficient_signal"],
    )
    factory.slm.classify = lambda _txs: [ambiguous]  # type: ignore[method-assign]

    state = factory.slm_classifier({"routed_to_slm": [tx]})
    out = state["slm_classified_transactions"][0]

    assert state["slm_escalated_transactions"] == []
    assert out.requires_review is True
    assert "human_review_required:llm_unavailable" in out.explanations
