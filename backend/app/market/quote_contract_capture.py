"""Explicit Taiwan quote-contract capture transaction and cache-only replay."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time
import json
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import TaiwanQuoteContractSnapshot
from app.market.quote_depth import (
    TWSE_MIS_SOURCE,
    _get_stock,
    _local_now,
    _normalize_stock_id,
    _taiwan_exchange_datetime,
    get_taiwan_stock_quote_depth,
)
from app.market.taiwan_realtime_platform import refresh_taiwan_realtime_snapshot
from app.market.trading_calendar import TAIWAN_TZ, is_taiwan_trading_day
from app.market_data.policies import RealtimePolicy


TAIWAN_QUOTE_CONTRACT_SLOTS = (
    "08:30",
    "08:50",
    "08:55",
    "08:58",
    "08:59",
    "09:00",
    "09:01",
    "09:02",
    "09:05",
    "11:00",
    "13:24",
    "13:28",
    "13:30",
    "13:31",
    "13:32",
    "13:33",
    "13:34",
)


def _json_default(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Unsupported quote contract snapshot value: {type(value)!r}")


def _slot_time(capture_slot: str) -> time:
    normalized = str(capture_slot or "").strip()
    if normalized not in TAIWAN_QUOTE_CONTRACT_SLOTS:
        raise ValueError(
            "capture_slot must be one of: " + ", ".join(TAIWAN_QUOTE_CONTRACT_SLOTS)
        )
    hour_text, minute_text = normalized.split(":", maxsplit=1)
    return time(int(hour_text), int(minute_text))


def _upsert_snapshot(
    db: Session,
    *,
    stock_id: str,
    trade_date: date,
    capture_slot: str,
    scheduled_at: datetime,
    captured_at: datetime,
    payload: dict[str, Any] | None,
    error: str | None,
) -> TaiwanQuoteContractSnapshot:
    freshness = (
        payload.get("freshness")
        if isinstance(payload, dict) and isinstance(payload.get("freshness"), dict)
        else {}
    )
    capture_status = (
        "failed"
        if payload is None
        else "captured_degraded"
        if error or freshness.get("source_error")
        else "captured"
    )
    values = {
        "provider": payload.get("provider") if payload else None,
        "market": payload.get("market") if payload else None,
        "scheduled_at": scheduled_at,
        "captured_at": captured_at,
        "quote_time": payload.get("quote_time") if payload else None,
        "session_phase": payload.get("session_phase") if payload else None,
        "capture_status": capture_status,
        "refresh_outcome": payload.get("refresh_outcome") if payload else "failed",
        "freshness_status": freshness.get("status"),
        "source": str(payload.get("source") or TWSE_MIS_SOURCE) if payload else TWSE_MIS_SOURCE,
        "payload_json": (
            json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                default=_json_default,
            )
            if payload is not None
            else None
        ),
        "error": error or freshness.get("source_error"),
        "updated_at": captured_at,
    }
    row = (
        db.query(TaiwanQuoteContractSnapshot)
        .filter(TaiwanQuoteContractSnapshot.stock_id == stock_id)
        .filter(TaiwanQuoteContractSnapshot.trade_date == trade_date)
        .filter(TaiwanQuoteContractSnapshot.capture_slot == capture_slot)
        .first()
    )
    if row is None:
        row = TaiwanQuoteContractSnapshot(
            stock_id=stock_id,
            trade_date=trade_date,
            capture_slot=capture_slot,
            created_at=captured_at,
            **values,
        )
        db.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return row


def capture_taiwan_quote_contract_snapshot(
    *,
    db: Session,
    stock_id: str,
    capture_slot: str,
    now: datetime | None = None,
    contract_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Acquire through Shared Core, then persist the outward compatibility view."""

    normalized_stock_id = _normalize_stock_id(stock_id)
    local_now = _local_now(now)
    if not is_taiwan_trading_day(local_now.date()):
        raise ValueError(
            f"Taiwan quote contract capture requires a trading day: {local_now.date()}."
        )
    scheduled_at = datetime.combine(
        local_now.date(),
        _slot_time(capture_slot),
        tzinfo=TAIWAN_TZ,
    )
    payload: dict[str, Any] | None = None
    error: str | None = None
    try:
        refresh_taiwan_realtime_snapshot(
            db,
            stock_id=normalized_stock_id,
            policy=RealtimePolicy.PREFER_LIVE,
            requested_at=local_now,
        )
        payload = get_taiwan_stock_quote_depth(
            db=db,
            stock_id=normalized_stock_id,
            now=local_now,
        )
        if contract_context:
            payload = {**payload, "scheduler_contract": deepcopy(contract_context)}
    except Exception as exc:
        db.rollback()
        error = str(exc) or exc.__class__.__name__

    row = _upsert_snapshot(
        db,
        stock_id=normalized_stock_id,
        trade_date=local_now.date(),
        capture_slot=capture_slot,
        scheduled_at=scheduled_at,
        captured_at=local_now,
        payload=payload,
        error=error,
    )
    captured_at = _taiwan_exchange_datetime(row.captured_at)
    scheduled_at = _taiwan_exchange_datetime(row.scheduled_at)
    assert captured_at is not None and scheduled_at is not None
    return {
        "stock_id": row.stock_id,
        "trade_date": row.trade_date,
        "capture_slot": row.capture_slot,
        "scheduled_at": scheduled_at,
        "captured_at": captured_at,
        "capture_delay_seconds": int((captured_at - scheduled_at).total_seconds()),
        "capture_status": row.capture_status,
        "refresh_outcome": row.refresh_outcome,
        "freshness_status": row.freshness_status,
        "error": row.error,
    }


def _project_replay(
    payload: dict[str, Any] | None,
    *,
    captured_at: datetime,
) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    output = dict(payload)
    phase = str(output.get("session_phase") or "")
    source = str(output.get("source") or "")
    snapshot_time = output.get("snapshot_time") or captured_at.isoformat()
    provider_event_time = (
        output.get("provider_event_time")
        or output.get("last_trade_time")
        or output.get("quote_time")
    )
    output["quote_time"] = provider_event_time
    output.setdefault("quote_time_basis", "provider_exchange_event_time")
    output["snapshot_time"] = snapshot_time
    output.setdefault("snapshot_time_basis", "persisted_capture_time")
    output["provider_event_time"] = provider_event_time
    output["event_time"] = provider_event_time
    if source == TWSE_MIS_SOURCE:
        auction_phase = phase in {"preopen_auction", "closing_auction"}
        book_available = bool(auction_phase and output.get("depth_available"))
        indicative_available = bool(
            output.get("auction_indicative_available")
            or output.get("indicative_match_available")
        )
        output["auction_book_available"] = book_available
        output.setdefault(
            "auction_book_status",
            "depth_and_indicative_match"
            if book_available and indicative_available
            else "depth_only"
            if book_available
            else "unavailable",
        )
        output.setdefault("auction_book_time", snapshot_time if book_available else None)
        output.setdefault("auction_event_time", snapshot_time if book_available else None)
        output.setdefault(
            "auction_best_bid",
            output.get("best_bid_price") if book_available else None,
        )
        output.setdefault(
            "auction_best_ask",
            output.get("best_ask_price") if book_available else None,
        )
        output.setdefault("auction_indicative_available", False)
        output.setdefault("auction_indicative_status", "not_provided")
        output.setdefault("indicative_match_available", False)
        output.setdefault("indicative_match_price", None)
        output.setdefault("indicative_match_volume_lots", None)
        output.setdefault("indicative_unmatched_buy_volume_lots", None)
        output.setdefault("indicative_unmatched_sell_volume_lots", None)
        output.setdefault("indicative_match_status", "not_provided")
        output.setdefault("indicative_price_available", False)
        output.setdefault("indicative_price", None)
        output.setdefault("indicative_bid", None)
        output.setdefault("indicative_ask", None)
        output["last_trade_before_auction"] = bool(
            phase == "closing_auction" and output.get("last_trade_available")
        )
    output["replay_projection"] = "captured_public_contract_preserved"
    output["captured_contract_semantics"] = "persisted_public_payload"
    return output


def get_taiwan_quote_contract_replay(
    *,
    db: Session,
    stock_id: str,
    trade_date: date | None = None,
) -> dict[str, Any]:
    normalized_stock_id = _normalize_stock_id(stock_id)
    _get_stock(db, normalized_stock_id)
    target_trade_date = trade_date
    if target_trade_date is None:
        target_trade_date = (
            db.query(TaiwanQuoteContractSnapshot.trade_date)
            .filter(TaiwanQuoteContractSnapshot.stock_id == normalized_stock_id)
            .order_by(TaiwanQuoteContractSnapshot.trade_date.desc())
            .limit(1)
            .scalar()
        )
    rows: list[TaiwanQuoteContractSnapshot] = []
    if target_trade_date is not None:
        rows = (
            db.query(TaiwanQuoteContractSnapshot)
            .filter(TaiwanQuoteContractSnapshot.stock_id == normalized_stock_id)
            .filter(TaiwanQuoteContractSnapshot.trade_date == target_trade_date)
            .order_by(TaiwanQuoteContractSnapshot.capture_slot.asc())
            .all()
        )
    rows_by_slot = {row.capture_slot: row for row in rows}
    snapshots: list[dict[str, Any]] = []
    captured_count = 0
    for capture_slot in TAIWAN_QUOTE_CONTRACT_SLOTS:
        row = rows_by_slot.get(capture_slot)
        if row is None:
            snapshots.append(
                {"capture_slot": capture_slot, "status": "missing", "quote": None}
            )
            continue
        captured_at = _taiwan_exchange_datetime(row.captured_at)
        assert captured_at is not None
        payload = json.loads(row.payload_json) if row.payload_json else None
        payload = _project_replay(payload, captured_at=captured_at)
        if row.capture_status.startswith("captured"):
            captured_count += 1
        snapshots.append(
            {
                "capture_slot": capture_slot,
                "status": row.capture_status,
                "scheduled_at": _taiwan_exchange_datetime(row.scheduled_at),
                "captured_at": captured_at,
                "quote_time": _taiwan_exchange_datetime(row.quote_time),
                "freshness_status": row.freshness_status,
                "refresh_outcome": row.refresh_outcome,
                "error": row.error,
                "quote": payload,
            }
        )
    required_count = len(TAIWAN_QUOTE_CONTRACT_SLOTS)
    missing_slots = [
        item["capture_slot"]
        for item in snapshots
        if not str(item["status"]).startswith("captured")
    ]
    return {
        "kind": "taiwan_quote_contract_replay",
        "stock_id": normalized_stock_id,
        "trade_date": target_trade_date,
        "timezone": str(TAIWAN_TZ),
        "required_slots": list(TAIWAN_QUOTE_CONTRACT_SLOTS),
        "required_count": required_count,
        "captured_count": captured_count,
        "coverage_ratio": captured_count / required_count,
        "complete": captured_count == required_count,
        "missing_slots": missing_slots,
        "snapshots": snapshots,
        "source": "taiwan_quote_contract_snapshot",
        "replay_semantics": "persisted_fixed_slot_evidence_projected_to_current_public_contract",
        "read_path_side_effects": False,
    }


__all__ = [
    "TAIWAN_QUOTE_CONTRACT_SLOTS",
    "capture_taiwan_quote_contract_snapshot",
    "get_taiwan_quote_contract_replay",
]
