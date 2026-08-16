from __future__ import annotations

from datetime import date, datetime, time
import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import (
    ProviderEvent,
    StockMaster,
    TaiwanQuoteContractSnapshot,
    WatchlistGroup,
    WatchlistItem,
)
from app.market.quote_depth import TAIWAN_QUOTE_CONTRACT_SLOTS


QUOTE_CONTRACT_HEALTH_VERSION = "tw.quote.health.v1"
QUOTE_PROVIDER_RESOURCES = ("quote_depth", "stock_quote_batch")
PROVIDER_FAILURE_STATUSES = {
    "blocked",
    "error",
    "failed",
    "rate_limited",
    "timeout",
}
PROVIDER_SUCCESS_STATUSES = {"completed", "ok", "success"}


def _universe_digest(*, source: str, symbols: list[str], max_symbols: int) -> str:
    payload = json.dumps(
        {
            "source": source,
            "symbols": symbols,
            "max_symbols": max_symbols,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:24]


def resolve_taiwan_quote_contract_universe(db: Session) -> dict[str, Any]:
    configured = list(
        dict.fromkeys(
            value.strip()
            for value in settings.scheduler_taiwan_quote_contract_symbols.split(",")
            if value.strip()
        )
    )
    max_symbols = max(
        min(int(settings.scheduler_taiwan_quote_contract_max_symbols), 20),
        1,
    )
    unknown_symbols: list[str] = []
    if configured:
        known = {
            str(row[0])
            for row in (
                db.query(StockMaster.stock_id)
                .filter(StockMaster.stock_id.in_(configured))
                .all()
            )
        }
        unknown_symbols = [symbol for symbol in configured if symbol not in known]
        symbols = [symbol for symbol in configured if symbol in known][:max_symbols]
        source = "configured_symbols"
    else:
        rows = (
            db.query(WatchlistItem.stock_id)
            .join(WatchlistGroup, WatchlistGroup.id == WatchlistItem.group_id)
            .filter(WatchlistItem.enabled.is_(True))
            .filter(WatchlistGroup.is_active.is_(True))
            .order_by(
                WatchlistItem.priority.asc(),
                WatchlistItem.stock_id.asc(),
            )
            .limit(max_symbols * 4)
            .all()
        )
        symbols = []
        seen: set[str] = set()
        for (stock_id,) in rows:
            normalized = str(stock_id or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            symbols.append(normalized)
            if len(symbols) >= max_symbols:
                break
        source = "active_watchlist"
    digest = _universe_digest(
        source=source,
        symbols=symbols,
        max_symbols=max_symbols,
    )
    return {
        "version": QUOTE_CONTRACT_HEALTH_VERSION,
        "source": source,
        "symbols": symbols,
        "symbol_count": len(symbols),
        "max_symbols": max_symbols,
        "configured_symbol_count": len(configured),
        "unknown_symbols": unknown_symbols,
        "symbol_set_digest": digest,
        "target": f"universe:{digest}",
        "scope_semantics": "bounded_symbol_universe_not_all_market",
    }


def required_quote_contract_slots(
    *,
    trade_date: date | None,
    current_time: datetime,
) -> list[str]:
    if trade_date is None:
        return []
    if trade_date < current_time.date():
        return list(TAIWAN_QUOTE_CONTRACT_SLOTS)
    if trade_date > current_time.date():
        return []
    current_clock = current_time.timetz().replace(tzinfo=None)
    return [
        slot
        for slot in TAIWAN_QUOTE_CONTRACT_SLOTS
        if time.fromisoformat(slot) <= current_clock
    ]


def build_taiwan_quote_scheduler_contract(
    db: Session,
    *,
    trade_date: date | None,
    current_time: datetime,
    stock_id: str | None = None,
) -> dict[str, Any]:
    universe = resolve_taiwan_quote_contract_universe(db)
    symbols = list(universe["symbols"])
    required_slots = required_quote_contract_slots(
        trade_date=trade_date,
        current_time=current_time,
    )
    scoped_symbols = (
        [stock_id]
        if stock_id and stock_id in symbols
        else []
        if stock_id
        else symbols
    )
    rows: list[TaiwanQuoteContractSnapshot] = []
    if trade_date is not None and scoped_symbols and required_slots:
        rows = (
            db.query(TaiwanQuoteContractSnapshot)
            .filter(TaiwanQuoteContractSnapshot.trade_date == trade_date)
            .filter(TaiwanQuoteContractSnapshot.stock_id.in_(scoped_symbols))
            .filter(
                TaiwanQuoteContractSnapshot.capture_slot.in_(required_slots)
            )
            .all()
        )
    rows_by_key = {
        (str(row.stock_id), str(row.capture_slot)): row for row in rows
    }
    required_pairs = [
        (symbol, slot)
        for symbol in scoped_symbols
        for slot in required_slots
    ]
    captured_pairs = {
        key
        for key, row in rows_by_key.items()
        if str(row.capture_status or "").startswith("captured")
    }
    failed_pairs = {
        key
        for key, row in rows_by_key.items()
        if not str(row.capture_status or "").startswith("captured")
    }
    missing_pairs = [pair for pair in required_pairs if pair not in rows_by_key]
    missing_symbols = [
        symbol
        for symbol in scoped_symbols
        if required_slots
        and not any(pair[0] == symbol for pair in captured_pairs)
    ]
    partial_symbols = [
        symbol
        for symbol in scoped_symbols
        if any(pair[0] == symbol for pair in captured_pairs)
        and any(pair[0] == symbol for pair in missing_pairs)
    ]
    complete_symbols = [
        symbol
        for symbol in scoped_symbols
        if required_slots
        and all((symbol, slot) in captured_pairs for slot in required_slots)
    ]
    requested_count = len(required_pairs)
    captured_count = len(captured_pairs)
    status = (
        "disabled"
        if not settings.enable_taiwan_quote_contract_scheduler
        else "not_in_universe"
        if stock_id and stock_id not in symbols
        else "not_configured"
        if not scoped_symbols
        else "pending"
        if not required_slots
        else "ready"
        if captured_count == requested_count
        else "partial"
        if captured_count or failed_pairs
        else "missing"
    )
    observed_slots = {
        slot for _, slot in captured_pairs if slot in required_slots
    }
    return {
        "version": QUOTE_CONTRACT_HEALTH_VERSION,
        "axis": "scheduler_contract",
        "status": status,
        "decision_usable": status == "ready",
        "trade_date": trade_date.isoformat() if trade_date else None,
        "target": stock_id or universe["target"],
        "target_scope": (
            "single_symbol" if stock_id else "bounded_universe"
        ),
        "universe": universe,
        "required_slots": required_slots,
        "latest_required_slot": required_slots[-1] if required_slots else None,
        "latest_observed_slot": max(observed_slots) if observed_slots else None,
        "requested_symbol_count": len(scoped_symbols),
        "observed_symbol_count": len(
            {symbol for symbol, _ in captured_pairs}
        ),
        "complete_symbol_count": len(complete_symbols),
        "requested_count": requested_count,
        "captured_count": captured_count,
        "failed_count": len(failed_pairs),
        "missing_count": len(missing_pairs),
        "unsatisfied_count": max(requested_count - captured_count, 0),
        "coverage_ratio": (
            captured_count / requested_count if requested_count else None
        ),
        "complete_symbols": complete_symbols,
        "partial_symbols": partial_symbols,
        "missing_symbols": missing_symbols,
        "missing_symbol_slots": [
            {"stock_id": symbol, "capture_slot": slot}
            for symbol, slot in missing_pairs[:100]
        ],
        "missing_symbol_slots_truncated": len(missing_pairs) > 100,
        "read_path_side_effects": False,
    }


def build_taiwan_quote_provider_availability(
    db: Session,
    *,
    stock_id: str | None = None,
) -> dict[str, Any]:
    query = (
        db.query(ProviderEvent)
        .filter(ProviderEvent.market == "tw")
        .filter(ProviderEvent.provider == "twse_mis")
        .filter(ProviderEvent.resource.in_(QUOTE_PROVIDER_RESOURCES))
    )
    if stock_id:
        query = query.filter(
            ProviderEvent.target.in_((stock_id, "all"))
        )
    event = query.order_by(
        ProviderEvent.event_time.desc(),
        ProviderEvent.id.desc(),
    ).first()
    event_status = str(event.status or "").lower() if event else None
    status = (
        "unavailable"
        if event_status in PROVIDER_FAILURE_STATUSES
        else "available"
        if event_status in PROVIDER_SUCCESS_STATUSES
        else "unknown"
    )
    return {
        "version": QUOTE_CONTRACT_HEALTH_VERSION,
        "axis": "provider_availability",
        "status": status,
        "provider": "twse_mis",
        "target": stock_id or "bounded_quote_operations",
        "event_status": event_status,
        "event_type": event.event_type if event else None,
        "event_at": event.event_time.isoformat() if event else None,
        "http_status_code": event.http_status_code if event else None,
        "rate_limited": bool(event.rate_limited) if event else False,
        "retry_after_seconds": event.retry_after_seconds if event else None,
        "message": (
            event.error_message or event.message if event else None
        ),
        "evidence_source": "provider_event" if event else "not_observed",
        "inferred_from_quote_row": False,
    }


__all__ = [
    "QUOTE_CONTRACT_HEALTH_VERSION",
    "build_taiwan_quote_provider_availability",
    "build_taiwan_quote_scheduler_contract",
    "required_quote_contract_slots",
    "resolve_taiwan_quote_contract_universe",
]
