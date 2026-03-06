from __future__ import annotations

import json
from typing import Any, Literal

from openai import OpenAI
from pydantic import BaseModel, Field
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from sentinelfi.domain.models import ClassifiedTransaction, NormalizedTransaction, TxCategory
from sentinelfi.services.taxonomy_service import TaxonomyService


class LLMResponseItem(BaseModel):
    tx_id: str
    category: Literal["business", "personal", "unknown"]
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(min_length=1, max_length=512)


class LLMResponsePayload(BaseModel):
    items: list[LLMResponseItem]


class LLMResponseValidationError(ValueError):
    pass


class LLMReasoner:
    _SYSTEM_PROMPT = (
        "You are a financial transaction auditor for Indian SMB bookkeeping. "
        "Classify each transaction as business, personal, or unknown. "
        "Return only JSON that exactly matches this schema: "
        '{"items":[{"tx_id":"string","category":"business|personal|unknown","confidence":0.0,"reasoning":"string"}]}. '
        "Do not include markdown or extra keys."
    )

    def __init__(
        self,
        api_key: str | None,
        model: str = "gpt-4o-mini",
        batch_size: int = 20,
        client: OpenAI | None = None,
        taxonomy: TaxonomyService | None = None,
    ):
        self.model = model
        self.batch_size = max(1, batch_size)
        self.client = client if client is not None else (OpenAI(api_key=api_key) if api_key else None)
        self.taxonomy = taxonomy

    @property
    def available(self) -> bool:
        return self.client is not None

    def classify(self, txs: list[NormalizedTransaction]) -> list[ClassifiedTransaction]:
        if not txs:
            return []
        if self.client is None:
            return self._fallback(txs)

        out: list[ClassifiedTransaction] = []
        for batch in self._chunks(txs):
            payload = [
                {
                    "tx_id": tx.tx_id,
                    "description": tx.pii_redacted_description,
                    "amount": tx.amount,
                    "is_debit": tx.is_debit,
                }
                for tx in batch
            ]
            try:
                by_id = self._classify_with_retry(payload)
            except Exception:
                out.extend(self._fallback(batch))
                continue
            for tx in batch:
                item = by_id.get(tx.tx_id)
                if item is None:
                    out.extend(self._fallback([tx]))
                    continue
                out.append(
                    ClassifiedTransaction(
                        **tx.model_dump(),
                        category=TxCategory(item.category),
                        confidence=item.confidence,
                        classifier="llm",
                        explanations=[item.reasoning],
                    )
                )

        return out

    def _chunks(self, txs: list[NormalizedTransaction]):
        for i in range(0, len(txs), self.batch_size):
            yield txs[i:i + self.batch_size]

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.2, min=0.2, max=1.0),
        retry=retry_if_exception_type((RuntimeError, LLMResponseValidationError)),
        reraise=True,
    )
    def _classify_with_retry(self, payload: list[dict[str, Any]]) -> dict[str, LLMResponseItem]:
        if self.client is None:
            raise RuntimeError("llm_client_unavailable")
        try:
            response = self.client.responses.create(
                model=self.model,
                input=[
                    {"role": "system", "content": self._SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=True)},
                ],
                temperature=0,
            )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("llm_request_failed") from exc
        return self._parse_response(response.output_text)

    def _parse_response(self, raw: str) -> dict[str, LLMResponseItem]:
        if not raw or not raw.strip():
            raise LLMResponseValidationError("empty_llm_output")
        json_text = self._extract_json_text(raw)
        try:
            decoded = json.loads(json_text)
        except json.JSONDecodeError as exc:
            raise LLMResponseValidationError("invalid_json_output") from exc

        if isinstance(decoded, list):
            decoded = {"items": decoded}
        if not isinstance(decoded, dict):
            raise LLMResponseValidationError("json_payload_must_be_object_or_list")

        try:
            validated = LLMResponsePayload.model_validate(decoded)
        except Exception as exc:  # noqa: BLE001
            raise LLMResponseValidationError("schema_validation_failed") from exc

        return {item.tx_id: item for item in validated.items}

    @staticmethod
    def _extract_json_text(raw: str) -> str:
        text = raw.strip()
        if text.startswith("```"):
            lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
            return "\n".join(lines).strip()
        return text

    def _fallback(self, txs: list[NormalizedTransaction]) -> list[ClassifiedTransaction]:
        out: list[ClassifiedTransaction] = []
        for tx in txs:
            text = tx.pii_redacted_description.lower()
            cat = TxCategory.UNKNOWN
            confidence = 0.5
            reason = "fallback_ambiguous"

            # Taxonomy-first fallback
            if self.taxonomy:
                matched = self.taxonomy.match_category(text)
                if matched:
                    category_id, score, keywords = matched
                    propensity = self.taxonomy.business_score_for_category(category_id)
                    if propensity >= 0.6 and score >= 0.25:
                        cat = TxCategory.BUSINESS
                        confidence = min(0.78, 0.55 + score * 0.25)
                        reason = f"fallback_taxonomy_business:{category_id}"
                    elif propensity <= 0.4 and score >= 0.25:
                        cat = TxCategory.PERSONAL
                        confidence = min(0.75, 0.55 + score * 0.25)
                        reason = f"fallback_taxonomy_personal:{category_id}"

            # Keyword fallback if taxonomy didn't resolve
            if cat == TxCategory.UNKNOWN:
                if any(k in text for k in [
                    "invoice", "license", "subscription", "software", "gst",
                    "hosting", "cloud", "consulting", "professional", "saas",
                    "workspace", "agency", "domain", "renewal",
                ]):
                    cat = TxCategory.BUSINESS
                    confidence = 0.68
                    reason = "fallback_business_signal"
                elif any(k in text for k in [
                    "movie", "food", "restaurant", "personal", "myntra", "swiggy",
                    "grocery", "hotel", "vacation", "donation", "temple", "fuel",
                    "school", "medical", "pharmacy", "rent", "family", "dinner",
                    "cinema", "shopping", "lic", "insurance", "electricity",
                ]):
                    cat = TxCategory.PERSONAL
                    confidence = 0.65
                    reason = "fallback_personal_signal"

            out.append(
                ClassifiedTransaction(
                    **tx.model_dump(),
                    category=cat,
                    confidence=confidence,
                    classifier="rule",
                    explanations=[reason],
                )
            )
        return out
