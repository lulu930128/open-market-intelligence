"""Provider-neutral Taiwan issued-shares receipt contract and parser."""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from pydantic import Field

from app.market_data.contracts import CanonicalModel


_EMPTY_VALUES = {"", "-", "--", "nan", "null", "none"}


class OfficialIssuedSharesRecord(CanonicalModel):
    venue: str = Field(pattern=r"^TPEX$")
    trade_date: date
    symbol: str = Field(pattern=r"^\d{4}$")
    issued_shares: int = Field(gt=0)


def _repair_text(value: str | None) -> str:
    if value is None:
        return ""
    if re.search(r"[\u4e00-\u9fff]", value):
        return value
    try:
        return value.encode("latin1").decode("utf-8-sig")
    except UnicodeError:
        return value


def _text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = _repair_text(str(value)).replace("\ufeff", "").strip()
    return None if normalized.lower() in _EMPTY_VALUES else normalized


def _integer(value: Any) -> int | None:
    normalized = _text(value)
    if normalized is None:
        return None
    match = re.search(r"-?\d+", normalized.replace(",", "").replace(" ", ""))
    return int(match.group()) if match else None


def _date(value: Any) -> date | None:
    normalized = _text(value)
    if normalized is None:
        return None
    digits = re.sub(r"\D", "", normalized)
    try:
        if len(digits) == 8:
            return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
        if len(digits) == 7:
            return date(int(digits[:3]) + 1911, int(digits[3:5]), int(digits[5:7]))
    except ValueError:
        return None
    return None


def _first_tpex_table(payload: dict[str, Any]) -> list[Any]:
    tables = payload.get("tables") or payload.get("Tables") or []
    if isinstance(tables, list):
        for table in tables:
            if isinstance(table, dict) and isinstance(table.get("data"), list):
                return table["data"]
    data = payload.get("data")
    if isinstance(data, list):
        return data
    raise ValueError("TPEx official daily payload has no data table")


def parse_tpex_issued_shares_payload(
    raw_text: str,
) -> tuple[OfficialIssuedSharesRecord, ...]:
    """Parse exchange-reported issued shares from a persisted TPEx receipt."""

    payload = json.loads(_repair_text(raw_text).lstrip("\ufeff").strip())
    if not isinstance(payload, (dict, list)):
        raise ValueError("TPEx issued-shares payload must be a JSON object or list")
    rows = payload if isinstance(payload, list) else _first_tpex_table(payload)
    payload_date = None if isinstance(payload, list) else _date(payload.get("date"))
    records: list[OfficialIssuedSharesRecord] = []
    seen: set[tuple[str, date]] = set()
    for row in rows:
        if isinstance(row, dict):
            symbol = _text(row.get("SecuritiesCompanyCode"))
            trade_date = _date(row.get("Date")) or payload_date
            issued_shares = _integer(row.get("Capitals"))
        elif isinstance(row, list):
            symbol = _text(row[0] if len(row) > 0 else None)
            trade_date = payload_date
            issued_shares = _integer(row[15] if len(row) > 15 else None)
        else:
            continue
        if (
            symbol is None
            or not re.fullmatch(r"\d{4}", symbol)
            or trade_date is None
            or issued_shares is None
            or issued_shares <= 0
        ):
            continue
        key = (symbol, trade_date)
        if key in seen:
            continue
        seen.add(key)
        records.append(
            OfficialIssuedSharesRecord(
                venue="TPEX",
                trade_date=trade_date,
                symbol=symbol,
                issued_shares=issued_shares,
            )
        )
    return tuple(records)


__all__ = ["OfficialIssuedSharesRecord", "parse_tpex_issued_shares_payload"]
