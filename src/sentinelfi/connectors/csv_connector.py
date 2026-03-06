from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd

from sentinelfi.domain.models import Transaction


def load_transactions_from_csv(
    path: str,
    *,
    encoding: str | None = None,
    date_format: str | None = None,
    dayfirst: bool = True,
    dedup_rows: bool = True,
) -> list[Transaction]:
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {path}")

    detected_encoding = encoding or _detect_encoding(csv_path)
    df = pd.read_csv(csv_path, encoding=detected_encoding)
    required_cols = {"tx_id", "tx_date", "description", "amount"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    if dedup_rows:
        parsed_dates = df["tx_date"].apply(
            lambda value: _parse_date(value, date_format=date_format, dayfirst=dayfirst, errors="coerce")
        )
        dedup_frame = pd.DataFrame(
            {
                "tx_date": parsed_dates.apply(lambda value: value.strftime("%Y-%m-%d") if not pd.isna(value) else None),
                "amount": pd.to_numeric(df["amount"], errors="coerce"),
                "description": df["description"].astype(str).str.strip().str.lower(),
            }
        )
        before = len(df)
        keep_mask = ~dedup_frame.duplicated(subset=["tx_date", "amount", "description"], keep="first")
        df = df.loc[keep_mask].copy()
        removed = before - len(df)
        if removed > 0:
            df.attrs["dedup_removed"] = removed

    txs: list[Transaction] = []
    for row in df.to_dict(orient="records"):
        tx_date = _parse_date(row["tx_date"], date_format=date_format, dayfirst=dayfirst, errors="raise").date()
        txs.append(
            Transaction(
                tx_id=str(row["tx_id"]),
                tx_date=tx_date,
                description=str(row["description"]),
                amount=float(row["amount"]),
                currency=str(row.get("currency", "INR")),
                is_debit=_parse_is_debit(row.get("is_debit", True)),
                merchant=str(row.get("merchant")) if row.get("merchant") else None,
                account_id=str(row.get("account_id")) if row.get("account_id") else None,
                metadata=_metadata_from_row(row),
            )
        )
    return txs


def _detect_encoding(path: Path) -> str:
    sample = path.read_bytes()[:100_000]
    if not sample:
        return "utf-8"
    try:
        import chardet

        detected = chardet.detect(sample)
        encoding = str(detected.get("encoding") or "").strip()
        if encoding:
            return encoding
    except Exception:  # noqa: BLE001
        pass
    return "utf-8-sig"


def _parse_is_debit(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "debit", "dr"}:
        return True
    if text in {"0", "false", "no", "credit", "cr"}:
        return False
    return True


def _metadata_from_row(row: dict[str, Any]) -> dict[str, Any]:
    exclude = {"tx_id", "tx_date", "description", "amount", "currency", "is_debit", "merchant", "account_id"}
    out: dict[str, Any] = {}
    for key, value in row.items():
        if key in exclude:
            continue
        if value is None:
            continue
        if isinstance(value, float) and pd.isna(value):
            continue
        out[key] = value
    return out


def _parse_date(
    value: Any,
    *,
    date_format: str | None,
    dayfirst: bool,
    errors: str,
):
    if date_format:
        return pd.to_datetime(value, format=date_format, errors=errors)
    text = str(value).strip()
    iso_like = bool(re.match(r"^\d{4}-\d{2}-\d{2}", text))
    return pd.to_datetime(value, dayfirst=False if iso_like else dayfirst, errors=errors)
