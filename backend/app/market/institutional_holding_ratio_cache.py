"""Bounded compatibility cache for nStock institutional holding ratios.

The cache is intentionally classified as compatibility evidence: it preserves
provider/source/fetch time and prevents GET-side provider I/O, but it does not
claim Shared Core canonical raw-receipt lineage.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import date, datetime
import json
import os
from pathlib import Path
import tempfile
from threading import RLock
from typing import Any

from app.config import settings
from app.market.institutional_holding_ratios import (
    InstitutionalHoldingRatio,
    InstitutionalHoldingRatioPoint,
    fetch_institutional_holding_ratios,
)


CACHE_SCHEMA_VERSION = 1
_CACHE_LOCK = RLock()


def _resolved_path(path: Path | None = None) -> Path:
    configured = getattr(
        settings,
        "tw_institutional_holding_ratio_cache_path",
        Path("data") / "tw_institutional_holding_ratios.json",
    )
    return Path(path or configured).expanduser().resolve()


def _empty_cache() -> dict[str, Any]:
    return {
        "schema_version": CACHE_SCHEMA_VERSION,
        "classification": "compatibility_cache",
        "lineage_status": "raw_receipt_not_persisted",
        "updated_at": None,
        "stocks": {},
    }


def _read_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return _empty_cache()
    if not isinstance(payload, dict):
        return _empty_cache()
    if payload.get("schema_version") != CACHE_SCHEMA_VERSION:
        return _empty_cache()
    if not isinstance(payload.get("stocks"), dict):
        return _empty_cache()
    return payload


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _serialized(value: InstitutionalHoldingRatio) -> dict[str, Any]:
    payload = asdict(value)
    payload["trade_date"] = value.trade_date.isoformat() if value.trade_date else None
    payload["fetched_at"] = value.fetched_at.isoformat()
    payload["history"] = [
        {
            **asdict(point),
            "trade_date": point.trade_date.isoformat(),
        }
        for point in value.history
    ]
    payload["classification"] = "compatibility_cache"
    payload["lineage_status"] = "raw_receipt_not_persisted"
    payload["canonical_truth"] = False
    payload["decision_usable"] = False
    payload["raw_receipt_id"] = None
    payload["limitations"] = [
        "NSTOCK_HOLDING_RATIO_COMPATIBILITY_CACHE",
        "RAW_RECEIPT_NOT_PERSISTED",
    ]
    return payload


def _ratio(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _deserialized(payload: Any) -> InstitutionalHoldingRatio | None:
    if not isinstance(payload, dict):
        return None
    try:
        fetched_at = datetime.fromisoformat(str(payload["fetched_at"]))
        history = [
            InstitutionalHoldingRatioPoint(
                trade_date=date.fromisoformat(str(item["trade_date"])),
                foreign_investor_ratio=_ratio(item.get("foreign_investor_ratio")),
                investment_trust_ratio=_ratio(item.get("investment_trust_ratio")),
                dealer_ratio=_ratio(item.get("dealer_ratio")),
            )
            for item in payload.get("history", [])
            if isinstance(item, dict) and item.get("trade_date")
        ]
        trade_date = (
            date.fromisoformat(str(payload["trade_date"]))
            if payload.get("trade_date")
            else None
        )
        return InstitutionalHoldingRatio(
            stock_id=str(payload["stock_id"]),
            stock_name=(
                str(payload["stock_name"])
                if payload.get("stock_name") is not None
                else None
            ),
            trade_date=trade_date,
            foreign_investor_ratio=_ratio(payload.get("foreign_investor_ratio")),
            investment_trust_ratio=_ratio(payload.get("investment_trust_ratio")),
            dealer_ratio=_ratio(payload.get("dealer_ratio")),
            source_name=str(payload["source_name"]),
            source_url=str(payload["source_url"]),
            fetched_at=fetched_at,
            history=history,
            classification="compatibility_cache",
            lineage_status="raw_receipt_not_persisted",
            canonical_truth=False,
            decision_usable=False,
            raw_receipt_id=None,
            limitations=(
                "NSTOCK_HOLDING_RATIO_COMPATIBILITY_CACHE",
                "RAW_RECEIPT_NOT_PERSISTED",
            ),
        )
    except (KeyError, TypeError, ValueError):
        return None


def read_cached_institutional_holding_ratios(
    stock_id: str,
    *,
    path: Path | None = None,
) -> InstitutionalHoldingRatio | None:
    normalized = str(stock_id or "").strip()
    if not normalized:
        raise ValueError("stock_id is required")
    cache_path = _resolved_path(path)
    with _CACHE_LOCK:
        payload = _read_payload(cache_path)
        return _deserialized(payload["stocks"].get(normalized))


def refresh_cached_institutional_holding_ratios(
    stock_id: str,
    *,
    path: Path | None = None,
    fetcher: Callable[[str], InstitutionalHoldingRatio] = (
        fetch_institutional_holding_ratios
    ),
) -> InstitutionalHoldingRatio:
    normalized = str(stock_id or "").strip()
    if not normalized:
        raise ValueError("stock_id is required")
    observation = fetcher(normalized)
    cache_path = _resolved_path(path)
    with _CACHE_LOCK:
        payload = _read_payload(cache_path)
        payload["updated_at"] = observation.fetched_at.isoformat()
        payload["stocks"][normalized] = _serialized(observation)
        _atomic_write(cache_path, payload)
    return observation


__all__ = [
    "read_cached_institutional_holding_ratios",
    "refresh_cached_institutional_holding_ratios",
]
