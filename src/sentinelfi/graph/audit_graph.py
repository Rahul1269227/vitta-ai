from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from langgraph.graph import END, START, StateGraph

from sentinelfi.agents.cleanup_agent import CleanupPlanner
from sentinelfi.agents.gst_sentinel import GstSentinel
from sentinelfi.agents.llm_reasoner import LLMReasoner
from sentinelfi.agents.mcc_classifier import MCCClassifier
from sentinelfi.agents.ml_classifier import MLTransactionClassifier
from sentinelfi.agents.slm_classifier import RuleBasedTransactionClassifier
from sentinelfi.core.config import Settings
from sentinelfi.core.logging import get_logger
from sentinelfi.domain.models import (
    AuditOutput,
    AuditSummary,
    ClassifiedTransaction,
    ClassifierVote,
)
from sentinelfi.domain.state import AuditState
from sentinelfi.services.classification_policy import ClassificationPolicy
from sentinelfi.services.explainability_service import build_classification_decisions
from sentinelfi.services.ingestion_service import ingest_transactions, normalize_transactions
from sentinelfi.services.leak_detection_service import LeakDetectionThresholds, detect_leaks
from sentinelfi.services.risk_scoring import compute_risk_score
from sentinelfi.services.routing_service import EmbeddingRouter
from sentinelfi.services.taxonomy_service import TaxonomyService

log = get_logger(__name__)
try:
    from opentelemetry import trace

    _TRACER = trace.get_tracer("sentinelfi.audit_graph")
except Exception:  # pragma: no cover
    _TRACER = None


@contextmanager
def _trace_span(name: str, **attributes):
    if _TRACER is None:
        yield None
        return
    with _TRACER.start_as_current_span(name) as span:
        for key, value in attributes.items():
            if isinstance(value, (str, bool, int, float)):
                span.set_attribute(f"sentinelfi.{key}", value)
        yield span


class AuditGraphFactory:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.taxonomy = TaxonomyService(
            base_path=settings.taxonomy_base_path,
            overrides_path=settings.taxonomy_overrides_path,
        )
        self.router = EmbeddingRouter(
            settings.embedding_model,
            settings.enable_local_embeddings,
            taxonomy=self.taxonomy,
        )
        self.mcc = MCCClassifier(taxonomy=self.taxonomy)
        self.ml = MLTransactionClassifier(
            model_path=settings.ml_model_path,
            enabled=settings.enable_ml_classifier,
        )
        self.slm = RuleBasedTransactionClassifier(
            taxonomy=self.taxonomy,
            model_name=settings.embedding_model,
            enable_local_model=settings.enable_local_embeddings,
        )
        self.llm = LLMReasoner(
            api_key=settings.openai_api_key,
            model=settings.llm_model,
            batch_size=settings.llm_batch_size,
            taxonomy=self.taxonomy,
        )
        self.gst = GstSentinel(taxonomy=self.taxonomy)
        self.cleanup = CleanupPlanner()
        self.leak_thresholds = LeakDetectionThresholds(
            duplicate_min_amount=settings.leak_duplicate_min_amount,
            duplicate_amount_tolerance=settings.leak_duplicate_amount_tolerance,
            zombie_min_amount=settings.leak_zombie_min_amount,
            price_hike_min_amount=settings.leak_price_hike_min_amount,
            price_hike_jump_threshold=settings.leak_price_hike_jump_threshold,
            free_trial_lookback_days=settings.leak_free_trial_lookback_days,
            free_trial_low_amount_abs=settings.leak_free_trial_low_amount_abs,
            free_trial_low_amount_ratio=settings.leak_free_trial_low_amount_ratio,
        )
        self.policy = ClassificationPolicy(
            slm_escalation_threshold=settings.slm_escalation_threshold,
            review_threshold_default=settings.review_threshold_default,
            review_threshold_high_risk=settings.review_threshold_high_risk,
        )

    def build(self):
        graph = StateGraph(AuditState)
        graph.add_node("data_ingestor", self.data_ingestor)
        graph.add_node("mcc_classifier", self.mcc_classifier)
        graph.add_node("ml_classifier", self.ml_classifier)
        graph.add_node("routing_supervisor", self.routing_supervisor)
        graph.add_node("slm_classifier", self.slm_classifier)
        graph.add_node("llm_reasoner", self.llm_reasoner)
        graph.add_node("finalize_classification", self.finalize_classification)
        graph.add_node("leak_detector", self.leak_detector)
        graph.add_node("gst_sentinel", self.gst_sentinel)
        graph.add_node("cleanup_planner", self.cleanup_planner)

        graph.add_edge(START, "data_ingestor")
        graph.add_edge("data_ingestor", "mcc_classifier")
        graph.add_edge("mcc_classifier", "ml_classifier")
        graph.add_edge("ml_classifier", "routing_supervisor")
        graph.add_conditional_edges(
            "routing_supervisor",
            self._after_routing_supervisor,
            {
                "slm_classifier": "slm_classifier",
                "llm_reasoner": "llm_reasoner",
                "finalize_classification": "finalize_classification",
            },
        )
        graph.add_conditional_edges(
            "slm_classifier",
            self._after_slm_classifier,
            {
                "llm_reasoner": "llm_reasoner",
                "finalize_classification": "finalize_classification",
            },
        )
        graph.add_edge("llm_reasoner", "finalize_classification")
        graph.add_edge("finalize_classification", "leak_detector")
        graph.add_edge("leak_detector", "gst_sentinel")
        graph.add_edge("gst_sentinel", "cleanup_planner")
        graph.add_edge("cleanup_planner", END)

        return graph.compile()

    def data_ingestor(self, state: AuditState) -> AuditState:
        request = state["request"]
        with _trace_span("audit_graph.data_ingestor", source_type=str(request.source_type)):
            allowed_roots = [
                item.strip()
                for item in self.settings.local_ingestion_roots_csv.split(",")
                if item.strip()
            ]
            pdf_ocr_enabled = _coerce_bool(
                request.source_config.get("pdf_ocr_enabled"),
                default=self.settings.enable_pdf_ocr_fallback,
            )
            pdf_ocr_lang = str(
                request.source_config.get("pdf_ocr_lang", self.settings.pdf_ocr_lang)
            ).strip() or self.settings.pdf_ocr_lang
            raw = ingest_transactions(
                request.source_type,
                request.source_path,
                request.source_config,
                allowed_local_roots=allowed_roots,
                pdf_ocr_enabled=pdf_ocr_enabled,
                pdf_ocr_lang=pdf_ocr_lang,
            )
            normalized = normalize_transactions(raw, self.settings.pii_hash_salt)
            state["audit_id"] = f"audit-{uuid.uuid4().hex[:10]}"
            state["created_at"] = datetime.now(timezone.utc)
            state["raw_transactions"] = raw
            state["normalized_transactions"] = normalized
            state["remaining_transactions"] = normalized
            state["errors"] = []
            log.info("data_ingested", count=len(normalized), source=str(request.source_type))
            return state

    def mcc_classifier(self, state: AuditState) -> AuditState:
        txs = state.get("remaining_transactions", [])
        with _trace_span("audit_graph.mcc_classifier", tx_count=len(txs)):
            mcc_classified, unresolved = self.mcc.classify(txs)

            for tx in mcc_classified:
                self.policy.apply_review_flag(tx)

            state["mcc_classified_transactions"] = mcc_classified
            state["remaining_transactions"] = unresolved

            log.info(
                "mcc_classification_complete",
                mcc_classified=len(mcc_classified),
                unresolved=len(unresolved),
            )
            return state

    def ml_classifier(self, state: AuditState) -> AuditState:
        txs = state.get("remaining_transactions", [])
        with _trace_span("audit_graph.ml_classifier", tx_count=len(txs)):
            if not txs:
                state["ml_classified_transactions"] = []
                state["ml_escalated_transactions"] = []
                return state

            if not self.ml.available:
                state["ml_classified_transactions"] = []
                state["ml_escalated_transactions"] = txs
                state["remaining_transactions"] = txs
                log.info("ml_classification_skipped", reason="model_unavailable", escalated=len(txs))
                return state

            ml_classified = self.ml.classify(txs)
            tx_by_id = {tx.tx_id: tx for tx in txs}
            escalated: list = []
            escalated_ids: set[str] = set()

            for tx in ml_classified:
                self.policy.apply_review_flag(tx)
                threshold = max(self.policy.review_threshold(tx), self.settings.ml_min_confidence)
                if tx.confidence < threshold:
                    escalated_ids.add(tx.tx_id)
                    original = tx_by_id.get(tx.tx_id)
                    if original is not None:
                        escalated.append(original)
                    tx.explanations.append(f"ml_escalated_threshold:{threshold:.2f}")

            state["ml_classified_transactions"] = ml_classified
            state["ml_escalated_transactions"] = escalated
            state["remaining_transactions"] = escalated

            log.info(
                "ml_classification_complete",
                ml_total=len(ml_classified),
                ml_escalated=len(escalated_ids),
            )
            return state

    def routing_supervisor(self, state: AuditState) -> AuditState:
        remaining = state.get("remaining_transactions", [])
        with _trace_span("audit_graph.routing_supervisor", tx_count=len(remaining)):
            slm, llm, decisions = self.router.route(remaining)
            if llm and not self.llm.available:
                # Keep the cascade alive even without remote LLM: run uncertain rows through
                # local SLM first, then hard-flag unresolved ones for human review.
                slm_by_id = {tx.tx_id: tx for tx in slm}
                for tx in llm:
                    slm_by_id.setdefault(tx.tx_id, tx)
                slm = list(slm_by_id.values())
                llm = []
                for decision in decisions:
                    if decision.route == "llm":
                        decision.route = "slm"
                        decision.reason = f"{decision.reason}|llm_unavailable_fallback"
            state["routed_to_slm"] = slm
            state["routed_to_llm"] = llm
            state["route_reason_by_tx_id"] = {d.tx.tx_id: d.reason for d in decisions}

            log.info("routing_complete", slm=len(slm), llm=len(llm), fast_mode=self.settings.fast_mode_enabled)
            return state

    def _after_routing_supervisor(self, state: AuditState) -> str:
        routed_to_slm = state.get("routed_to_slm", [])
        routed_to_llm = state.get("routed_to_llm", [])
        if routed_to_slm:
            return "slm_classifier"
        if routed_to_llm:
            return "llm_reasoner"
        return "finalize_classification"

    def slm_classifier(self, state: AuditState) -> AuditState:
        routed = state.get("routed_to_slm", [])
        with _trace_span("audit_graph.slm_classifier", tx_count=len(routed)):
            slm_classified = self.slm.classify(routed)

            escalated_ids: set[str] = set()
            escalated_txs = []
            routed_by_id = {tx.tx_id: tx for tx in routed}

            for tx in slm_classified:
                self.policy.apply_review_flag(tx)
                if self.settings.fast_mode_enabled and self.policy.should_escalate_from_slm(tx):
                    if self.llm.available:
                        escalated_ids.add(tx.tx_id)
                        escalated_txs.append(routed_by_id[tx.tx_id])
                        tx.explanations.append("escalated_to_llm")
                    else:
                        tx.requires_review = True
                        tx.explanations.append("human_review_required:llm_unavailable")

            state["slm_classified_transactions"] = slm_classified
            state["slm_escalated_transactions"] = escalated_txs

            log.info(
                "slm_classification_complete",
                slm_total=len(slm_classified),
                escalated=len(escalated_txs),
            )
            return state

    def _after_slm_classifier(self, state: AuditState) -> str:
        routed_to_llm = state.get("routed_to_llm", [])
        slm_escalated = state.get("slm_escalated_transactions", [])
        if routed_to_llm or slm_escalated:
            return "llm_reasoner"
        return "finalize_classification"

    def llm_reasoner(self, state: AuditState) -> AuditState:
        direct_llm = state.get("routed_to_llm", [])
        escalated = state.get("slm_escalated_transactions", [])
        with _trace_span("audit_graph.llm_reasoner", direct_count=len(direct_llm), escalated_count=len(escalated)):
            llm_input_by_id = {tx.tx_id: tx for tx in direct_llm}
            for tx in escalated:
                llm_input_by_id[tx.tx_id] = tx

            llm_input = list(llm_input_by_id.values())
            llm_classified = self.llm.classify(llm_input)

            for tx in llm_classified:
                self.policy.apply_review_flag(tx)

            state["llm_classified_transactions"] = llm_classified
            return state

    def finalize_classification(self, state: AuditState) -> AuditState:
        with _trace_span("audit_graph.finalize_classification"):
            final_by_id: dict[str, ClassifiedTransaction] = {}

            for tx in state.get("mcc_classified_transactions", []):
                final_by_id[tx.tx_id] = tx

            ml_escalated_ids = {tx.tx_id for tx in state.get("ml_escalated_transactions", [])}
            slm_escalated_ids = {tx.tx_id for tx in state.get("slm_escalated_transactions", [])}
            escalated_ids = ml_escalated_ids | slm_escalated_ids

            for tx in state.get("ml_classified_transactions", []):
                if tx.tx_id in ml_escalated_ids:
                    continue
                final_by_id[tx.tx_id] = tx

            for tx in state.get("slm_classified_transactions", []):
                # Only SLM-escalated transactions should be replaced by LLM output.
                if tx.tx_id in slm_escalated_ids:
                    continue
                final_by_id[tx.tx_id] = tx

            for tx in state.get("llm_classified_transactions", []):
                final_by_id[tx.tx_id] = tx

            classified = list(final_by_id.values())
            route_reasons = state.get("route_reason_by_tx_id", {})
            votes_by_tx_id = _collect_votes_by_tx_id(state)
            decisions = build_classification_decisions(
                classified,
                route_reasons,
                escalated_ids,
                votes_by_tx_id=votes_by_tx_id,
            )

            state["classified_transactions"] = classified
            state["classification_decisions"] = decisions
            return state

    def leak_detector(self, state: AuditState) -> AuditState:
        classified = state.get("classified_transactions", [])
        with _trace_span("audit_graph.leak_detector", tx_count=len(classified)):
            state["leak_findings"] = detect_leaks(
                classified,
                taxonomy=self.taxonomy,
                thresholds=self.leak_thresholds,
            )
            return state

    def gst_sentinel(self, state: AuditState) -> AuditState:
        classified = state.get("classified_transactions", [])
        with _trace_span("audit_graph.gst_sentinel", tx_count=len(classified)):
            state["gst_findings"] = self.gst.analyze(classified)
            return state

    def cleanup_planner(self, state: AuditState) -> AuditState:
        leak_findings = state.get("leak_findings", [])
        gst_findings = state.get("gst_findings", [])
        with _trace_span(
            "audit_graph.cleanup_planner",
            leak_count=len(leak_findings),
            gst_count=len(gst_findings),
        ):
            state["cleanup_tasks"] = self.cleanup.plan(leak_findings, gst_findings)
            return state


def build_audit_output(final_state: AuditState) -> AuditOutput:
    leaks = final_state.get("leak_findings", [])
    gst = final_state.get("gst_findings", [])
    classifications = final_state.get("classified_transactions", [])

    total_leak = round(sum(item.amount_impact for item in leaks), 2)
    missed_itc = round(
        sum(item.potential_itc_amount for item in gst if not item.has_gst_invoice),
        2,
    )
    tx_count = len(final_state.get("normalized_transactions", []))

    risk_score = compute_risk_score(leaks, gst, classifications)

    review_count = sum(1 for item in classifications if item.requires_review)
    avg_conf = (
        round(sum(item.confidence for item in classifications) / len(classifications), 4)
        if classifications
        else 0.0
    )

    summary = AuditSummary(
        audit_id=final_state["audit_id"],
        created_at=final_state["created_at"],
        total_transactions=tx_count,
        leak_count=len(leaks),
        total_leak_amount=total_leak,
        missed_itc=missed_itc,
        risk_score=risk_score,
        review_count=review_count,
        avg_classification_confidence=avg_conf,
    )

    return AuditOutput(
        summary=summary,
        findings=leaks,
        gst_findings=gst,
        cleanup_tasks=final_state.get("cleanup_tasks", []),
        classification_decisions=final_state.get("classification_decisions", []),
    )


def _coerce_bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _collect_votes_by_tx_id(state: AuditState) -> dict[str, list[ClassifierVote]]:
    votes_by_tx_id: dict[str, list[ClassifierVote]] = {}
    seen: set[tuple[str, str]] = set()
    for key in [
        "mcc_classified_transactions",
        "ml_classified_transactions",
        "slm_classified_transactions",
        "llm_classified_transactions",
    ]:
        for tx in state.get(key, []):
            dedupe_key = (tx.tx_id, tx.classifier)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            votes_by_tx_id.setdefault(tx.tx_id, []).append(
                ClassifierVote(
                    classifier=tx.classifier,
                    category=tx.category,
                    confidence=tx.confidence,
                    rationale=(tx.explanations[0] if tx.explanations else "classifier_output"),
                )
            )
    return votes_by_tx_id
