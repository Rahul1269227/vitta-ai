from datetime import date

from sentinelfi.domain.models import ClassifiedTransaction, TxCategory
from sentinelfi.services.leak_detection_service import detect_leaks


def _tx(tx_id: str, desc: str, amount: float, category: TxCategory = TxCategory.BUSINESS):
    return ClassifiedTransaction(
        tx_id=tx_id,
        tx_date=date(2025, 1, 1),
        description=desc,
        amount=amount,
        normalized_description=desc.lower(),
        pii_redacted_description=desc.lower(),
        category=category,
        confidence=0.8,
        classifier="slm",
        is_debit=True,
    )


def test_detect_duplicate_and_sprawl() -> None:
    txs = [
        _tx("1", "zoom subscription monthly", 4100),
        _tx("2", "zoom subscription monthly team2", 4100),
        _tx("3", "google meet business license", 5400),
    ]
    findings = detect_leaks(txs)
    types = {f.leak_type.value for f in findings}
    assert "duplicate_subscription" in types
    assert "saas_sprawl" in types


def test_duplicate_subscription_uses_fuzzy_amount_matching() -> None:
    txs = [
        _tx("1", "zoom subscription monthly", 649.00),
        _tx("2", "zoom subscription monthly team2", 649.18),
    ]
    findings = detect_leaks(txs)
    types = {f.leak_type.value for f in findings}
    assert "duplicate_subscription" in types


def test_detect_forgotten_free_trial_conversion() -> None:
    txs = [
        ClassifiedTransaction(
            tx_id="trial",
            tx_date=date(2025, 1, 1),
            description="notion subscription trial",
            amount=0.0,
            normalized_description="notion subscription trial",
            pii_redacted_description="notion subscription trial",
            category=TxCategory.BUSINESS,
            confidence=0.8,
            classifier="slm",
            is_debit=True,
        ),
        ClassifiedTransaction(
            tx_id="paid",
            tx_date=date(2025, 1, 20),
            description="notion subscription monthly",
            amount=499.0,
            normalized_description="notion subscription monthly",
            pii_redacted_description="notion subscription monthly",
            category=TxCategory.BUSINESS,
            confidence=0.8,
            classifier="slm",
            is_debit=True,
        ),
    ]
    findings = detect_leaks(txs)
    free_trial_findings = [f for f in findings if f.leak_type.value == "forgotten_free_trial"]
    assert len(free_trial_findings) == 1
    assert free_trial_findings[0].tx_ids == ["trial", "paid"]


def test_price_hike_uses_transaction_date_order() -> None:
    txs = [
        ClassifiedTransaction(
            tx_id="apr",
            tx_date=date(2025, 4, 1),
            description="zoom subscription monthly",
            amount=1400,
            normalized_description="zoom subscription monthly",
            pii_redacted_description="zoom subscription monthly",
            category=TxCategory.BUSINESS,
            confidence=0.8,
            classifier="slm",
            is_debit=True,
        ),
        _tx("jan", "zoom subscription monthly", 1000),
        ClassifiedTransaction(
            tx_id="feb",
            tx_date=date(2025, 2, 1),
            description="zoom subscription monthly",
            amount=1000,
            normalized_description="zoom subscription monthly",
            pii_redacted_description="zoom subscription monthly",
            category=TxCategory.BUSINESS,
            confidence=0.8,
            classifier="slm",
            is_debit=True,
        ),
        ClassifiedTransaction(
            tx_id="mar",
            tx_date=date(2025, 3, 1),
            description="zoom subscription monthly",
            amount=1000,
            normalized_description="zoom subscription monthly",
            pii_redacted_description="zoom subscription monthly",
            category=TxCategory.BUSINESS,
            confidence=0.8,
            classifier="slm",
            is_debit=True,
        ),
    ]

    findings = detect_leaks(txs)
    types = {f.leak_type.value for f in findings}
    assert "price_hike" in types


def test_google_workspace_and_cloud_are_not_merged_as_same_merchant() -> None:
    txs = [
        _tx("gw", "google workspace monthly license", 4100),
        _tx("gc", "google cloud monthly license", 4100),
    ]

    findings = detect_leaks(txs)
    types = {f.leak_type.value for f in findings}
    assert "duplicate_subscription" not in types
