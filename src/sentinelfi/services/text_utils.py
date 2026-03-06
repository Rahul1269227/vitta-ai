from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from typing import Any

from sentinelfi.services.signal_defaults import UPI_MERCHANT_HINTS

_PHONE_PATTERN = re.compile(r"\b(?:\+91[- ]?)?[6-9]\d{9}\b")
_EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_UPI_ID_PATTERN = re.compile(r"\b[a-zA-Z0-9._-]+@[a-zA-Z]{2,}\b")
_UPI_REF_PATTERN = re.compile(r"\b\d{12}\b")
_SPACES = re.compile(r"\s+")

_PERSON_NAME_HINTS = {
    "rahul",
    "vikas",
    "amit",
    "ajay",
    "anil",
    "arun",
    "aman",
    "neha",
    "priya",
    "pooja",
    "sunil",
    "rohit",
    "sachin",
    "manish",
    "sumit",
    "nitin",
    "vinay",
    "deepak",
    "ravi",
    "sandeep",
}


def hash_value(value: str, salt: str) -> str:
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        value.encode("utf-8"),
        salt.encode("utf-8"),
        200_000,
        dklen=16,
    )
    return derived.hex()[:12]


def _tokenize_upi_user(user_part: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", user_part.lower())


def _find_upi_merchant_hint(user_part: str, text: str) -> str | None:
    token = _tokenize_upi_user(user_part)
    for hint in UPI_MERCHANT_HINTS:
        if hint in token or hint in text:
            return hint
    return None


def scrub_pii(text: str, salt: str) -> str:
    def _phone_sub(match: re.Match[str]) -> str:
        return f"<PHONE:{hash_value(match.group(0), salt)}>"

    def _email_sub(match: re.Match[str]) -> str:
        return f"<EMAIL:{hash_value(match.group(0), salt)}>"

    def _upi_sub(match: re.Match[str]) -> str:
        raw = match.group(0)
        user_part = raw.split("@", 1)[0]
        merchant_hint = _find_upi_merchant_hint(user_part, text.lower())
        if merchant_hint:
            return f"<UPI_MERCHANT:{merchant_hint}>"

        token = _tokenize_upi_user(user_part)
        if token in _PERSON_NAME_HINTS:
            return f"<UPI_PERSON:{hash_value(raw, salt)}>"

        return f"<UPI:{hash_value(raw, salt)}>"

    text = _PHONE_PATTERN.sub(_phone_sub, text)
    text = _EMAIL_PATTERN.sub(_email_sub, text)
    text = _UPI_ID_PATTERN.sub(_upi_sub, text)
    return text


def extract_upi_signals(text: str) -> dict[str, Any]:
    lower = text.lower()
    handles = _UPI_ID_PATTERN.findall(lower)
    refs = _UPI_REF_PATTERN.findall(lower)

    merchant_token: str | None = None
    person_like = False
    domains: list[str] = []

    for handle in handles:
        user_part, domain = handle.split("@", 1)
        domains.append(domain)
        merchant_hint = _find_upi_merchant_hint(user_part, lower)
        if merchant_hint:
            merchant_token = merchant_hint
            break
        if _tokenize_upi_user(user_part) in _PERSON_NAME_HINTS:
            person_like = True

    is_upi = bool("upi" in lower or handles or refs)
    p2m_likely = bool(merchant_token is not None)
    p2p_likely = bool(is_upi and person_like and merchant_token is None)

    return {
        "is_upi": is_upi,
        "handle_count": len(handles),
        "handle_domains": sorted(set(domains)),
        "ref_count": len(refs),
        "merchant_token": merchant_token,
        "p2m_likely": p2m_likely,
        "p2p_likely": p2p_likely,
    }


def normalize_descriptor(text: str) -> str:
    cleaned = text.lower().replace("/", " ").replace("-", " ").replace("_", " ")
    cleaned = re.sub(r"[^a-z0-9.@ ]+", " ", cleaned)
    cleaned = _SPACES.sub(" ", cleaned).strip()
    return cleaned


def first_match(text: str, candidates: Iterable[str]) -> str | None:
    lower = text.lower()
    for c in candidates:
        if c in lower:
            return c
    return None
