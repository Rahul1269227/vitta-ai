from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pdfplumber

from sentinelfi.domain.models import Transaction

try:
    import pypdfium2 as pdfium  # type: ignore[import-not-found]
except Exception:  # noqa: BLE001
    pdfium = None  # type: ignore[assignment]

try:
    from paddleocr import PaddleOCR  # type: ignore[import-not-found]
except Exception:  # noqa: BLE001
    PaddleOCR = None  # type: ignore[assignment]


_DATE_PATTERNS = [
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b\d{2}[/-]\d{2}[/-]\d{4}\b"),
    re.compile(r"\b\d{2}\s+[A-Za-z]{3}\s+\d{4}\b"),
    re.compile(r"\b\d{2}\s+[A-Za-z]{4,9}\s+\d{4}\b"),
]
_AMOUNT_PATTERN = re.compile(r"(?<!\d)([-+]?)\s*(?:INR|Rs\.?|₹)?\s*(\d[\d,]*(?:\.\d{1,2})?)")
_DATE_FORMATS = [
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%d %b %Y",
    "%d %B %Y",
]


def load_transactions_from_pdf(
    path: str,
    enable_ocr_fallback: bool = True,
    ocr_lang: str = "en",
) -> list[Transaction]:
    """
    Heuristic PDF parser with OCR fallback for scanned statements.
    """
    pdf_path = Path(path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {path}")

    table_transactions = _parse_table_transactions(pdf_path)
    if table_transactions or not enable_ocr_fallback:
        return table_transactions

    ocr_transactions = _parse_ocr_transactions(pdf_path, lang=ocr_lang)
    if ocr_transactions:
        return ocr_transactions
    return table_transactions


def _parse_table_transactions(pdf_path: Path) -> list[Transaction]:
    txs: list[Transaction] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            table = page.extract_table()
            if not table:
                continue
            rows = table[1:] if len(table) > 1 else []
            for row in rows:
                if len(row) < 3:
                    continue
                date_text, description, amount_text = row[0], row[1], row[2]
                if not date_text or not description or not amount_text:
                    continue
                tx_date = _parse_date(str(date_text))
                amount = _parse_amount(str(amount_text))
                if tx_date is None or amount is None:
                    continue
                tx_id = hashlib.sha256(f"{date_text}|{description}|{amount}".encode()).hexdigest()[:16]
                txs.append(
                    Transaction(
                        tx_id=tx_id,
                        tx_date=tx_date,
                        description=description.strip(),
                        amount=abs(amount),
                        is_debit=amount < 0,
                    )
                )
    return txs


def _parse_ocr_transactions(pdf_path: Path, lang: str) -> list[Transaction]:
    if PaddleOCR is None or pdfium is None:
        return []

    ocr = _get_ocr_engine(lang)
    txs: list[Transaction] = []
    seen_keys: set[tuple[str, str, float, bool]] = set()

    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        for page_index in range(len(doc)):
            page = doc[page_index]
            try:
                bitmap = page.render(scale=2.0)
                pil_image = bitmap.to_pil()
                raw = ocr.ocr(np.array(pil_image), cls=True)  # type: ignore[no-untyped-call]
            finally:
                page.close()

            lines = _extract_ocr_lines(raw)
            for tx in _transactions_from_ocr_lines(lines):
                key = (tx.tx_date.isoformat(), tx.description, tx.amount, tx.is_debit)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                txs.append(tx)
    finally:
        doc.close()

    return txs


@lru_cache(maxsize=4)
def _get_ocr_engine(lang: str):  # noqa: ANN201
    if PaddleOCR is None:
        raise RuntimeError("PaddleOCR is not installed. Install optional dependency group: .[ocr]")
    return PaddleOCR(use_angle_cls=True, lang=lang, show_log=False)


def _extract_ocr_lines(raw: Any) -> list[tuple[str, float, float, float]]:
    lines: list[tuple[str, float, float, float]] = []
    page_lines = raw[0] if isinstance(raw, list) and raw else []
    if not isinstance(page_lines, list):
        return lines

    for item in page_lines:
        if not isinstance(item, list) or len(item) < 2:
            continue
        box = item[0]
        content = item[1]
        if not isinstance(content, (list, tuple)) or len(content) < 2:
            continue
        text = str(content[0]).strip()
        if not text:
            continue
        try:
            confidence = float(content[1])
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < 0.35:
            continue

        x_min, y_center = _box_position(box)
        lines.append((text, confidence, x_min, y_center))

    return lines


def _box_position(box: Any) -> tuple[float, float]:
    if not isinstance(box, list) or not box:
        return (0.0, 0.0)
    points = [point for point in box if isinstance(point, (list, tuple)) and len(point) >= 2]
    if not points:
        return (0.0, 0.0)
    x_min = min(float(point[0]) for point in points)
    y_avg = sum(float(point[1]) for point in points) / len(points)
    return (x_min, y_avg)


def _transactions_from_ocr_lines(lines: list[tuple[str, float, float, float]]) -> list[Transaction]:
    if not lines:
        return []
    grouped_rows = _group_lines_by_row(lines)
    txs: list[Transaction] = []
    for idx, row in enumerate(grouped_rows):
        row_text = " ".join(text for text, _x in row).strip()
        parsed = _parse_row_text(row_text)
        if parsed is None:
            continue
        tx_date, description, amount, is_debit = parsed
        tx_id = hashlib.sha256(f"{tx_date}|{description}|{amount}|{idx}".encode()).hexdigest()[:16]
        txs.append(
            Transaction(
                tx_id=tx_id,
                tx_date=tx_date,
                description=description,
                amount=abs(amount),
                is_debit=is_debit,
            )
        )
    return txs


def _group_lines_by_row(lines: list[tuple[str, float, float, float]]) -> list[list[tuple[str, float]]]:
    sorted_lines = sorted(lines, key=lambda item: item[3])
    rows: list[list[tuple[str, float, float]]] = []
    threshold = 14.0
    for text, _confidence, x_min, y_center in sorted_lines:
        if not rows:
            rows.append([(text, x_min, y_center)])
            continue
        previous_row = rows[-1]
        previous_y = previous_row[-1][2]
        if abs(y_center - previous_y) <= threshold:
            previous_row.append((text, x_min, y_center))
        else:
            rows.append([(text, x_min, y_center)])

    grouped: list[list[tuple[str, float]]] = []
    for row in rows:
        sorted_row = sorted(row, key=lambda item: item[1])
        grouped.append([(text, x_min) for text, x_min, _y in sorted_row])
    return grouped


def _parse_row_text(row_text: str) -> tuple[date, str, float, bool] | None:
    date_match = _find_date_match(row_text)
    if date_match is None:
        return None
    date_value = _parse_date(date_match)
    if date_value is None:
        return None

    amount_match = _find_amount_match(row_text)
    if amount_match is None:
        return None

    amount_sign, amount_raw = amount_match
    amount_value = _parse_amount(f"{amount_sign}{amount_raw}")
    if amount_value is None:
        return None

    amount_fragment = f"{amount_sign}{amount_raw}".strip()
    description = row_text.replace(date_match, " ", 1)
    description = description.replace(amount_fragment, " ", 1)
    description = re.sub(r"\s+", " ", description).strip()
    if not description:
        description = "statement transaction"

    lowered = row_text.lower()
    is_debit = amount_value < 0 or " dr " in f" {lowered} " or "debit" in lowered
    if amount_value >= 0 and (" cr " in f" {lowered} " or "credit" in lowered):
        is_debit = False

    return date_value, description, amount_value, is_debit


def _find_date_match(text: str) -> str | None:
    for pattern in _DATE_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(0)
    return None


def _find_amount_match(text: str) -> tuple[str, str] | None:
    matches = _AMOUNT_PATTERN.findall(text)
    if not matches:
        return None
    return matches[-1]


def _parse_date(value: str) -> date | None:
    cleaned = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount(value: str) -> float | None:
    cleaned = value.strip().replace("INR", "").replace("Rs.", "").replace("₹", "")
    cleaned = cleaned.replace(",", "").replace(" ", "")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None
