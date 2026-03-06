from __future__ import annotations

from datetime import date

from sentinelfi.agents.llm_reasoner import LLMReasoner
from sentinelfi.domain.models import NormalizedTransaction, TxCategory


class _FakeResponse:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text


class _FakeResponsesClient:
    def __init__(self, events: list[object]) -> None:
        self._events = events
        self.create_calls = 0

    def create(self, **_: object) -> _FakeResponse:
        self.create_calls += 1
        if not self._events:
            raise RuntimeError("no_more_events")
        event = self._events.pop(0)
        if isinstance(event, Exception):
            raise event
        return _FakeResponse(str(event))


class _FakeOpenAIClient:
    def __init__(self, events: list[object]) -> None:
        self.responses = _FakeResponsesClient(events)


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


def test_llm_reasoner_parses_structured_json_object() -> None:
    tx = _tx("t-1", "google workspace monthly license")
    client = _FakeOpenAIClient(
        [
            (
                '{"items":[{"tx_id":"t-1","category":"business","confidence":0.91,'
                '"reasoning":"SaaS workspace charge"}]}'
            )
        ]
    )
    reasoner = LLMReasoner(api_key=None, client=client)

    out = reasoner.classify([tx])
    assert len(out) == 1
    assert out[0].category == TxCategory.BUSINESS
    assert out[0].confidence == 0.91
    assert out[0].classifier == "llm"
    assert "workspace" in out[0].explanations[0].lower()


def test_llm_reasoner_retries_on_invalid_json_then_succeeds() -> None:
    tx = _tx("t-2", "client dinner")
    client = _FakeOpenAIClient(
        [
            "not-json",
            '```json\n{"items":[{"tx_id":"t-2","category":"personal","confidence":0.83,"reasoning":"meal"}]}\n```',
        ]
    )
    reasoner = LLMReasoner(api_key=None, client=client)

    out = reasoner.classify([tx])
    assert len(out) == 1
    assert out[0].category == TxCategory.PERSONAL
    assert out[0].confidence == 0.83
    assert client.responses.create_calls == 2


def test_llm_reasoner_falls_back_after_retry_exhaustion() -> None:
    tx = _tx("t-3", "aws cloud invoice")
    client = _FakeOpenAIClient(["invalid", "still-invalid", "again-invalid"])
    reasoner = LLMReasoner(api_key=None, client=client)

    out = reasoner.classify([tx])
    assert len(out) == 1
    assert out[0].classifier == "rule"
    assert out[0].category == TxCategory.BUSINESS
    assert client.responses.create_calls == 3


def test_llm_reasoner_chunks_large_payloads() -> None:
    txs = [
        _tx("t-10", "google workspace license"),
        _tx("t-11", "netflix subscription"),
        _tx("t-12", "aws cloud invoice"),
    ]
    client = _FakeOpenAIClient(
        [
            (
                '{"items":[{"tx_id":"t-10","category":"business","confidence":0.88,"reasoning":"saas"},'
                '{"tx_id":"t-11","category":"personal","confidence":0.80,"reasoning":"personal entertainment"}]}'
            ),
            '{"items":[{"tx_id":"t-12","category":"business","confidence":0.90,"reasoning":"cloud infra"}]}',
        ]
    )
    reasoner = LLMReasoner(api_key=None, client=client, batch_size=2)

    out = reasoner.classify(txs)
    by_id = {item.tx_id: item for item in out}

    assert client.responses.create_calls == 2
    assert len(out) == 3
    assert by_id["t-10"].classifier == "llm"
    assert by_id["t-11"].category == TxCategory.PERSONAL
    assert by_id["t-12"].confidence == 0.90
