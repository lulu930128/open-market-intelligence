from __future__ import annotations

from datetime import date, datetime, time, timezone
import json
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.ai.market_context.taiwan_projection import _compact_index_quote
from app.db.models import TaiwanIndexContractSnapshot, utc_now
from app.market.calendar_status import build_taiwan_calendar_status
from app.market.index_resolution import (
    ResolvedTaiwanIndexTruth,
    resolve_taiwan_index_truth,
)
from app.market.indices import (
    get_market_index_intraday,
    get_market_index_summary,
)
from app.market.trading_calendar import TAIWAN_TZ


TAIWAN_INDEX_CONTRACT_IDS = ("TAIEX", "TPEX")
TAIWAN_INDEX_CONTRACT_SLOTS = (
    "13:24",
    "13:28",
    "13:30",
    "13:32",
    "13:34",
)


def _local_now(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(TAIWAN_TZ)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc).astimezone(TAIWAN_TZ)
    return now.astimezone(TAIWAN_TZ)


def _slot_datetime(trade_date: date, capture_slot: str) -> datetime:
    if capture_slot not in TAIWAN_INDEX_CONTRACT_SLOTS:
        raise ValueError(
            "Unsupported Taiwan index capture slot: "
            f"{capture_slot}. Expected one of "
            + ", ".join(TAIWAN_INDEX_CONTRACT_SLOTS)
        )
    hour_text, minute_text = capture_slot.split(":", maxsplit=1)
    return datetime.combine(
        trade_date,
        time(int(hour_text), int(minute_text)),
        tzinfo=TAIWAN_TZ,
    )


def _index_market(index_id: str) -> str:
    return "TPEX" if index_id == "TPEX" else "TWSE"


def _summary_row(payload: dict[str, Any], index_id: str) -> dict[str, Any]:
    for item in payload.get("indices") or []:
        if (
            isinstance(item, dict)
            and str(item.get("index_id") or "").upper() == index_id
        ):
            return dict(item)
    return {}


def _save_row(
    db: Session,
    *,
    index_id: str,
    trade_date: date,
    capture_slot: str,
    scheduled_at: datetime,
    captured_at: datetime,
    session_phase: str | None,
    capture_status: str,
    payload: dict[str, Any] | None,
    error: str | None,
) -> TaiwanIndexContractSnapshot:
    row = (
        db.query(TaiwanIndexContractSnapshot)
        .filter(TaiwanIndexContractSnapshot.index_id == index_id)
        .filter(TaiwanIndexContractSnapshot.trade_date == trade_date)
        .filter(TaiwanIndexContractSnapshot.capture_slot == capture_slot)
        .first()
    )
    if row is None:
        row = TaiwanIndexContractSnapshot(
            index_id=index_id,
            market=_index_market(index_id),
            trade_date=trade_date,
            capture_slot=capture_slot,
            scheduled_at=scheduled_at,
            captured_at=captured_at,
            session_phase=session_phase,
            capture_status=capture_status,
            source="taiwan_index_contract_capture",
        )
        db.add(row)
    row.market = _index_market(index_id)
    row.scheduled_at = scheduled_at
    row.captured_at = captured_at
    row.session_phase = session_phase
    row.capture_status = capture_status
    row.selected_candidate = (
        str(payload.get("selected_candidate") or "") or None
        if isinstance(payload, dict)
        else None
    )
    row.selected_value = (
        payload.get("selected_value")
        if isinstance(payload, dict)
        and isinstance(payload.get("selected_value"), (int, float))
        else None
    )
    row.selection_reason = (
        str(payload.get("selection_reason") or "") or None
        if isinstance(payload, dict)
        else None
    )
    row.official_close_status = (
        str(payload.get("official_close_status") or "") or None
        if isinstance(payload, dict)
        else None
    )
    row.payload_json = (
        json.dumps(payload, ensure_ascii=False, default=str)
        if payload is not None
        else None
    )
    row.error = error
    row.updated_at = utc_now()
    db.commit()
    db.refresh(row)
    return row


def capture_taiwan_index_contract_snapshot(
    db: Session,
    *,
    index_id: str,
    capture_slot: str,
    now: datetime | None = None,
    intraday_reader: Callable[[str], dict[str, Any]] = get_market_index_intraday,
    summary_reader: Callable[[Session, bool], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    normalized_index_id = str(index_id or "").strip().upper()
    if normalized_index_id not in TAIWAN_INDEX_CONTRACT_IDS:
        raise ValueError(
            "Unsupported Taiwan index contract id: "
            f"{normalized_index_id or index_id}."
        )
    local_now = _local_now(now)
    scheduled_at = _slot_datetime(local_now.date(), capture_slot)
    calendar_status = build_taiwan_calendar_status(now=local_now)
    summary_call = summary_reader or (
        lambda session, force_refresh: get_market_index_summary(
            session,
            force_refresh=force_refresh,
        )
    )
    try:
        intraday = intraday_reader(normalized_index_id)
        summary_payload = summary_call(db, False)
        summary = _summary_row(summary_payload, normalized_index_id)
        embedded_resolution = summary.get("resolution")
        truth: ResolvedTaiwanIndexTruth | None = None
        if isinstance(embedded_resolution, dict):
            try:
                truth = ResolvedTaiwanIndexTruth.model_validate(
                    embedded_resolution
                )
            except ValueError:
                truth = None
        if truth is None:
            truth = resolve_taiwan_index_truth(
                intraday=intraday,
                index_snapshot=summary,
                calendar_status=calendar_status,
                index_id=normalized_index_id,
                acquisition_policy=str(
                    intraday.get("acquisition_policy") or "prefer_live"
                ),
            )
        resolution = truth.model_dump(mode="json")
        summary = {**summary, "resolution": resolution}
        quote = _compact_index_quote(
            index_id=normalized_index_id,
            index_snapshot=summary,
            intraday=intraday,
            calendar_status=calendar_status,
        )
        payload = {
            "kind": "taiwan_index_contract_snapshot",
            "index_id": normalized_index_id,
            "trade_date": local_now.date().isoformat(),
            "capture_slot": capture_slot,
            "scheduled_at": scheduled_at.isoformat(),
            "captured_at": local_now.isoformat(),
            "session_phase": calendar_status.get("phase"),
            "intraday_candidate": (
                quote.get("quote_candidates") or [None]
            )[0],
            "summary_candidate": (
                quote.get("quote_candidates") or [None, None]
            )[1],
            "official_candidate": (
                quote.get("quote_candidates") or [None, None, None]
            )[2],
            "selected_candidate": quote.get("selected_candidate"),
            "selected_value": quote.get("latest_price"),
            "selected_source": quote.get("source"),
            "selection_reason": quote.get("selection_reason"),
            "official_close_status": quote.get("official_close_status"),
            "official_close_price": quote.get("official_close_price"),
            "resolution_version": resolution.get("resolution_version"),
            "resolution_id": resolution.get("resolution_id"),
            "resolution": resolution,
            "quote_semantics": quote.get("quote_semantics"),
            "delivery_status": quote.get("delivery_status"),
            "quote": quote,
        }
        row = _save_row(
            db,
            index_id=normalized_index_id,
            trade_date=local_now.date(),
            capture_slot=capture_slot,
            scheduled_at=scheduled_at,
            captured_at=local_now,
            session_phase=str(calendar_status.get("phase") or "") or None,
            capture_status="captured",
            payload=payload,
            error=None,
        )
        return {
            **payload,
            "id": row.id,
            "capture_status": row.capture_status,
        }
    except Exception as exc:
        db.rollback()
        row = _save_row(
            db,
            index_id=normalized_index_id,
            trade_date=local_now.date(),
            capture_slot=capture_slot,
            scheduled_at=scheduled_at,
            captured_at=local_now,
            session_phase=str(calendar_status.get("phase") or "") or None,
            capture_status="failed",
            payload=None,
            error=str(exc) or type(exc).__name__,
        )
        return {
            "kind": "taiwan_index_contract_snapshot",
            "id": row.id,
            "index_id": normalized_index_id,
            "trade_date": local_now.date().isoformat(),
            "capture_slot": capture_slot,
            "capture_status": "failed",
            "error": row.error,
        }


def _aware_taipei(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=TAIWAN_TZ)
    return value.astimezone(TAIWAN_TZ)


def get_taiwan_index_contract_replay(
    db: Session,
    *,
    index_id: str,
    trade_date: date | None = None,
) -> dict[str, Any]:
    normalized_index_id = str(index_id or "").strip().upper()
    if normalized_index_id not in TAIWAN_INDEX_CONTRACT_IDS:
        raise ValueError(
            "Unsupported Taiwan index contract id: "
            f"{normalized_index_id or index_id}."
        )
    target_trade_date = trade_date
    if target_trade_date is None:
        target_trade_date = (
            db.query(TaiwanIndexContractSnapshot.trade_date)
            .filter(
                TaiwanIndexContractSnapshot.index_id
                == normalized_index_id
            )
            .order_by(TaiwanIndexContractSnapshot.trade_date.desc())
            .limit(1)
            .scalar()
        )
    rows = (
        db.query(TaiwanIndexContractSnapshot)
        .filter(TaiwanIndexContractSnapshot.index_id == normalized_index_id)
        .filter(TaiwanIndexContractSnapshot.trade_date == target_trade_date)
        .all()
        if target_trade_date is not None
        else []
    )
    rows_by_slot = {row.capture_slot: row for row in rows}
    snapshots: list[dict[str, Any]] = []
    missing_slots: list[str] = []
    captured_count = 0
    for capture_slot in TAIWAN_INDEX_CONTRACT_SLOTS:
        row = rows_by_slot.get(capture_slot)
        if row is None:
            missing_slots.append(capture_slot)
            snapshots.append(
                {
                    "capture_slot": capture_slot,
                    "status": "missing",
                }
            )
            continue
        payload = (
            json.loads(row.payload_json)
            if row.payload_json
            else None
        )
        status = (
            "captured"
            if row.capture_status == "captured"
            else row.capture_status
        )
        if status == "captured":
            captured_count += 1
        else:
            missing_slots.append(capture_slot)
        snapshots.append(
            {
                "capture_slot": capture_slot,
                "status": status,
                "scheduled_at": _aware_taipei(row.scheduled_at),
                "captured_at": _aware_taipei(row.captured_at),
                "session_phase": row.session_phase,
                "selected_candidate": row.selected_candidate,
                "selected_value": row.selected_value,
                "selection_reason": row.selection_reason,
                "official_close_status": row.official_close_status,
                "resolution_version": (
                    payload.get("resolution_version")
                    if isinstance(payload, dict)
                    else None
                ),
                "resolution_id": (
                    payload.get("resolution_id")
                    if isinstance(payload, dict)
                    else None
                ),
                "error": row.error,
                "payload": payload,
            }
        )
    required_count = len(TAIWAN_INDEX_CONTRACT_SLOTS)
    return {
        "kind": "taiwan_index_contract_replay",
        "index_id": normalized_index_id,
        "trade_date": target_trade_date,
        "timezone": "Asia/Taipei",
        "required_slots": list(TAIWAN_INDEX_CONTRACT_SLOTS),
        "required_count": required_count,
        "captured_count": captured_count,
        "coverage_ratio": (
            captured_count / required_count if required_count else 1.0
        ),
        "complete": captured_count == required_count,
        "missing_slots": missing_slots,
        "snapshots": snapshots,
        "source": "taiwan_index_contract_snapshot",
        "replay_semantics": (
            "read_only_fixed_slot_candidates_and_selection_reasons"
        ),
        "read_path_side_effects": False,
    }


__all__ = [
    "TAIWAN_INDEX_CONTRACT_IDS",
    "TAIWAN_INDEX_CONTRACT_SLOTS",
    "capture_taiwan_index_contract_snapshot",
    "get_taiwan_index_contract_replay",
]
