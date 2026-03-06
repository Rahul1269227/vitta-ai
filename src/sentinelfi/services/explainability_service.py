from __future__ import annotations

from sentinelfi.domain.models import ClassificationDecision, ClassifiedTransaction, ClassifierVote


def build_classification_decisions(
    classified: list[ClassifiedTransaction],
    route_reason_by_tx_id: dict[str, str],
    escalated_tx_ids: set[str],
    votes_by_tx_id: dict[str, list[ClassifierVote]] | None = None,
) -> list[ClassificationDecision]:
    decisions: list[ClassificationDecision] = []

    for tx in classified:
        votes = (votes_by_tx_id or {}).get(tx.tx_id, [])
        if not votes:
            votes = [
                ClassifierVote(
                    classifier=tx.classifier,
                    category=tx.category,
                    confidence=tx.confidence,
                    rationale=(tx.explanations[0] if tx.explanations else "classifier_output"),
                )
            ]

        classifiers_used = {vote.classifier for vote in votes}
        if tx.classifier == "mcc":
            route = "mcc"
            base_path = ["mcc_early_exit"]
        elif tx.tx_id in escalated_tx_ids or len(classifiers_used) > 1:
            route = "mixed"
            base_path = ["multi_stage_cascade"]
        elif tx.classifier == "ml":
            route = "ml"
            base_path = ["ml_primary_path"]
        elif tx.classifier in {"llm", "rule"}:
            route = "llm"
            base_path = ["routed_to_llm"]
        else:
            route = "slm"
            base_path = ["routed_to_slm"]

        route_reason = route_reason_by_tx_id.get(tx.tx_id)
        if route_reason:
            base_path.append(route_reason)

        base_path.extend(f"vote:{vote.classifier}:{vote.category}:{vote.confidence:.2f}" for vote in votes)
        base_path.append(f"final_classifier:{tx.classifier}")
        if tx.requires_review:
            base_path.append("requires_human_review")
        else:
            base_path.append("auto_accepted")

        decisions.append(
            ClassificationDecision(
                tx_id=tx.tx_id,
                route=route,
                final_classifier=tx.classifier,
                category=tx.category,
                confidence=tx.confidence,
                requires_review=tx.requires_review,
                decision_path=base_path,
                votes=votes,
            )
        )

    return decisions
