from __future__ import annotations

import statistics
import uuid
from collections import defaultdict
from dataclasses import dataclass

from sentinelfi.domain.models import ClassifiedTransaction, LeakFinding, LeakType, TxCategory
from sentinelfi.services.signal_defaults import (
    LEAK_MERCHANT_TOKENS,
    LEAK_SAAS_CHAT,
    LEAK_SAAS_DOCS,
    LEAK_SAAS_VIDEO,
    LEAK_SUBSCRIPTION_MARKERS,
    TAX_MISCATEGORY_HINTS,
)
from sentinelfi.services.taxonomy_service import TaxonomyService

_CANONICAL_MERCHANT_ALIASES = [
    ("google workspace", "google_workspace"),
    ("workspace by google", "google_workspace"),
    ("google cloud", "google_cloud"),
    ("gcp", "google_cloud"),
    ("amazon web services", "aws"),
    ("microsoft teams", "microsoft_teams"),
    ("atlassian", "atlassian"),
    ("confluence", "confluence"),
    ("notion", "notion"),
    ("slack", "slack"),
    ("zoom", "zoom"),
]
@dataclass(frozen=True)
class LeakDetectionThresholds:
    duplicate_min_amount: float = 300.0
    duplicate_amount_tolerance: float = 0.05
    zombie_min_amount: float = 199.0
    price_hike_min_amount: float = 100.0
    price_hike_jump_threshold: float = 0.25
    free_trial_lookback_days: int = 60
    free_trial_low_amount_abs: float = 50.0
    free_trial_low_amount_ratio: float = 0.10


def _signal_set(taxonomy: TaxonomyService | None, name: str, default: set[str]) -> set[str]:
    if taxonomy is None:
        return set(default)
    return taxonomy.signal_keywords(name, default=default)


def _merchant_key(tx: ClassifiedTransaction, merchant_tokens: set[str]) -> str:
    text = tx.pii_redacted_description.lower()

    if tx.merchant:
        return tx.merchant.strip().lower().replace(" ", "_")

    upi = tx.metadata.get("upi") if tx.metadata else None
    if isinstance(upi, dict):
        token = str(upi.get("merchant_token") or "").strip().lower()
        if token:
            return token

    for phrase, canonical in _CANONICAL_MERCHANT_ALIASES:
        if phrase in text:
            return canonical

    for token in merchant_tokens:
        if token in text:
            return token

    alpha_tokens = [part for part in text.split(" ") if part.isalpha()]
    if alpha_tokens:
        return alpha_tokens[0]
    return "unknown"


def detect_leaks(
    txs: list[ClassifiedTransaction],
    taxonomy: TaxonomyService | None = None,
    thresholds: LeakDetectionThresholds | None = None,
) -> list[LeakFinding]:
    findings: list[LeakFinding] = []
    cfg = thresholds or LeakDetectionThresholds()
    merchant_tokens = _signal_set(taxonomy, "leak_merchant_tokens", LEAK_MERCHANT_TOKENS)
    subscription_markers = _signal_set(
        taxonomy,
        "leak_subscription_markers",
        LEAK_SUBSCRIPTION_MARKERS,
    )
    saas_video = _signal_set(taxonomy, "leak_saas_video_tools", LEAK_SAAS_VIDEO)
    saas_chat = _signal_set(taxonomy, "leak_saas_chat_tools", LEAK_SAAS_CHAT)
    saas_docs = _signal_set(taxonomy, "leak_saas_docs_tools", LEAK_SAAS_DOCS)
    tax_miscategory_hints = _signal_set(
        taxonomy,
        "tax_miscategory_business_hints",
        TAX_MISCATEGORY_HINTS,
    )

    by_merchant: dict[str, list[ClassifiedTransaction]] = defaultdict(list)
    for tx in txs:
        if tx.is_debit:
            by_merchant[_merchant_key(tx, merchant_tokens)].append(tx)

    findings.extend(_detect_duplicate_subscriptions(by_merchant, subscription_markers, cfg))
    findings.extend(_detect_forgotten_free_trials(by_merchant, subscription_markers, cfg))
    findings.extend(_detect_zombie_subscriptions(by_merchant, subscription_markers, cfg))
    findings.extend(_detect_price_hikes(by_merchant, cfg))
    findings.extend(_detect_saas_sprawl(by_merchant, saas_video, saas_chat, saas_docs, merchant_tokens))
    findings.extend(_detect_tax_miscategory(txs, tax_miscategory_hints))

    return findings


def _detect_duplicate_subscriptions(
    by_merchant: dict[str, list[ClassifiedTransaction]],
    subscription_markers: set[str],
    cfg: LeakDetectionThresholds,
) -> list[LeakFinding]:
    out: list[LeakFinding] = []
    for merchant, rows in by_merchant.items():
        monthly_like = [
            r
            for r in rows
            if r.amount > cfg.duplicate_min_amount
            and any(k in r.pii_redacted_description for k in (subscription_markers | {merchant}))
        ]
        if len(monthly_like) >= 2:
            for group in _cluster_by_amount(monthly_like, tolerance=cfg.duplicate_amount_tolerance):
                if len(group) < 2:
                    continue
                amount = round(sum(item.amount for item in group) / len(group), 2)
                out.append(
                    LeakFinding(
                        finding_id=f"leak-{uuid.uuid4().hex[:8]}",
                        leak_type=LeakType.DUPLICATE_SUBSCRIPTION,
                        severity="P1",
                        amount_impact=amount * (len(group) - 1) * 12,
                        confidence=0.82,
                        description=f"Possible duplicate {merchant} subscriptions at INR {amount}",
                        tx_ids=[g.tx_id for g in group],
                        suggested_action="Cancel overlapping licenses and request prorated refund.",
                    )
                )
    return out


def _detect_forgotten_free_trials(
    by_merchant: dict[str, list[ClassifiedTransaction]],
    subscription_markers: set[str],
    cfg: LeakDetectionThresholds,
) -> list[LeakFinding]:
    out: list[LeakFinding] = []
    for merchant, rows in by_merchant.items():
        ordered = sorted(rows, key=lambda item: item.tx_date)
        for idx, current in enumerate(ordered):
            if current.amount < 199:
                continue
            if not any(token in current.pii_redacted_description for token in (subscription_markers | {merchant})):
                continue
            for prev in ordered[max(0, idx - 4):idx]:
                days = (current.tx_date - prev.tx_date).days
                if days < 0 or days > cfg.free_trial_lookback_days:
                    continue
                low_cutoff = max(cfg.free_trial_low_amount_abs, current.amount * cfg.free_trial_low_amount_ratio)
                if prev.amount <= low_cutoff:
                    out.append(
                        LeakFinding(
                            finding_id=f"leak-{uuid.uuid4().hex[:8]}",
                            leak_type=LeakType.FREE_TRIAL,
                            severity="P2",
                            amount_impact=current.amount * 12,
                            confidence=0.73,
                            description=f"Possible forgotten free trial converted to paid plan for {merchant}",
                            tx_ids=[prev.tx_id, current.tx_id],
                            suggested_action="Review trial conversion and cancel/refund if unused.",
                        )
                    )
                    break
    return out


def _detect_zombie_subscriptions(
    by_merchant: dict[str, list[ClassifiedTransaction]],
    subscription_markers: set[str],
    cfg: LeakDetectionThresholds,
) -> list[LeakFinding]:
    out: list[LeakFinding] = []
    for merchant, rows in by_merchant.items():
        recurring = [
            r
            for r in rows
            if r.amount > cfg.zombie_min_amount
            and any(k in r.pii_redacted_description for k in subscription_markers)
        ]
        if len(recurring) < 3:
            continue

        # Proxy for non-usage: recurring descriptor with unknown category and low metadata signals.
        zombie_like = [r for r in recurring if r.category == TxCategory.UNKNOWN and not r.metadata]
        if len(zombie_like) >= 2:
            annual = sum(x.amount for x in zombie_like)
            out.append(
                LeakFinding(
                    finding_id=f"leak-{uuid.uuid4().hex[:8]}",
                    leak_type=LeakType.ZOMBIE_SUBSCRIPTION,
                    severity="P1",
                    amount_impact=annual,
                    confidence=0.71,
                    description=f"Potential zombie subscription pattern in {merchant}",
                    tx_ids=[x.tx_id for x in zombie_like],
                    suggested_action="Validate team usage and terminate inactive plans.",
                )
            )
    return out


def _detect_price_hikes(
    by_merchant: dict[str, list[ClassifiedTransaction]],
    cfg: LeakDetectionThresholds,
) -> list[LeakFinding]:
    out: list[LeakFinding] = []
    for merchant, rows in by_merchant.items():
        ordered = sorted((r for r in rows if r.amount > cfg.price_hike_min_amount), key=lambda item: item.tx_date)
        values = [r.amount for r in ordered]
        if len(values) < 3:
            continue

        base = statistics.median(values[:-1]) if len(values) > 3 else min(values)
        latest = values[-1]
        if base == 0:
            continue
        jump = (latest - base) / base
        if jump >= cfg.price_hike_jump_threshold:
            out.append(
                LeakFinding(
                    finding_id=f"leak-{uuid.uuid4().hex[:8]}",
                    leak_type=LeakType.PRICE_HIKE,
                    severity="P2",
                    amount_impact=max(0.0, latest - base) * 12,
                    confidence=0.68,
                    description=f"Price hike suspected for {merchant}: +{round(jump * 100, 1)}%",
                    tx_ids=[r.tx_id for r in ordered],
                    suggested_action="Renegotiate annual contract or reduce seat count.",
                )
            )
    return out


def _detect_saas_sprawl(
    by_merchant: dict[str, list[ClassifiedTransaction]],
    saas_video: set[str],
    saas_chat: set[str],
    saas_docs: set[str],
    merchant_tokens: set[str],
) -> list[LeakFinding]:
    out: list[LeakFinding] = []
    collab_tools: dict[str, str] = {}
    for token in saas_video:
        collab_tools[token] = "video"
    for token in saas_chat:
        collab_tools[token] = "chat"
    for token in saas_docs:
        collab_tools[token] = "docs"
    family: dict[str, list[ClassifiedTransaction]] = defaultdict(list)

    for merchant, rows in by_merchant.items():
        for key, fam in collab_tools.items():
            if key in merchant:
                family[fam].extend(rows)
                break

    for fam, rows in family.items():
        merchants = sorted({_merchant_key(r, merchant_tokens) for r in rows})
        if len(merchants) >= 2:
            annual = sum(r.amount for r in rows)
            out.append(
                LeakFinding(
                    finding_id=f"leak-{uuid.uuid4().hex[:8]}",
                    leak_type=LeakType.SAAS_SPRAWL,
                    severity="P2",
                    amount_impact=annual * 0.3,
                    confidence=0.74,
                    description=f"SaaS sprawl in {fam} stack: {', '.join(merchants)}",
                    tx_ids=[r.tx_id for r in rows],
                    suggested_action="Consolidate tools and keep one standard platform per function.",
                )
            )
    return out


def _detect_tax_miscategory(
    txs: list[ClassifiedTransaction],
    business_hints: set[str],
) -> list[LeakFinding]:
    out: list[LeakFinding] = []
    risky = [
        tx for tx in txs
        if tx.category == TxCategory.PERSONAL
        and any(k in tx.pii_redacted_description for k in business_hints)
    ]
    if risky:
        out.append(
            LeakFinding(
                finding_id=f"leak-{uuid.uuid4().hex[:8]}",
                leak_type=LeakType.TAX_MISCATEGORY,
                severity="P1",
                amount_impact=sum(x.amount for x in risky),
                confidence=0.84,
                description="Business-like expenses currently marked as personal",
                tx_ids=[x.tx_id for x in risky],
                suggested_action="Reclassify affected rows before GST and income tax filing.",
            )
        )
    return out


def _cluster_by_amount(
    rows: list[ClassifiedTransaction],
    *,
    tolerance: float,
) -> list[list[ClassifiedTransaction]]:
    if not rows:
        return []
    ordered = sorted(rows, key=lambda item: item.amount)
    groups: list[list[ClassifiedTransaction]] = []
    for row in ordered:
        placed = False
        for group in groups:
            baseline = sum(item.amount for item in group) / len(group)
            allowed_delta = max(1.0, baseline * tolerance)
            if abs(row.amount - baseline) <= allowed_delta:
                group.append(row)
                placed = True
                break
        if not placed:
            groups.append([row])
    return groups
