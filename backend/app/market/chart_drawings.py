from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import ChartDrawingSnapshot


MAX_CHART_DRAWINGS = 200


class ChartDrawingSnapshotNotFoundError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_key(value: str, *, field_name: str, max_length: int, uppercase: bool = True) -> str:
    normalized = value.strip()
    if uppercase:
        normalized = normalized.upper()

    if not normalized:
        raise ValueError(f"{field_name} must not be empty.")
    if len(normalized) > max_length:
        raise ValueError(f"{field_name} must be <= {max_length} characters.")

    return normalized


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback

    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _normalize_drawings(value: list[dict[str, Any]]) -> list[dict[str, Any]]:
    drawings: list[dict[str, Any]] = []

    for item in value:
        if isinstance(item, dict):
            drawings.append(item)

    return drawings[-MAX_CHART_DRAWINGS:]


def serialize_chart_drawing_snapshot(row: ChartDrawingSnapshot) -> dict[str, Any]:
    return {
        "id": row.id,
        "market": row.market,
        "symbol": row.symbol,
        "timeframe": row.timeframe,
        "label": row.label,
        "time_mode": row.time_mode,
        "selected_drawing_id": row.selected_drawing_id,
        "drawing_count": row.drawing_count,
        "drawings": _json_loads(row.drawings_json, []),
        "summary": _json_loads(row.summary_json, None),
        "source": row.source,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def get_chart_drawing_snapshot(
    *,
    db: Session,
    market: str,
    symbol: str,
    timeframe: str,
) -> ChartDrawingSnapshot | None:
    normalized_market = _normalize_key(market, field_name="market", max_length=20)
    normalized_symbol = _normalize_key(symbol, field_name="symbol", max_length=40)
    normalized_timeframe = _normalize_key(
        timeframe,
        field_name="timeframe",
        max_length=20,
        uppercase=False,
    )

    return (
        db.query(ChartDrawingSnapshot)
        .filter(
            ChartDrawingSnapshot.market == normalized_market,
            ChartDrawingSnapshot.symbol == normalized_symbol,
            ChartDrawingSnapshot.timeframe == normalized_timeframe,
        )
        .first()
    )


def list_chart_drawing_snapshots(
    *,
    db: Session,
    market: str,
    symbol: str,
) -> list[ChartDrawingSnapshot]:
    normalized_market = _normalize_key(market, field_name="market", max_length=20)
    normalized_symbol = _normalize_key(symbol, field_name="symbol", max_length=40)

    return (
        db.query(ChartDrawingSnapshot)
        .filter(
            ChartDrawingSnapshot.market == normalized_market,
            ChartDrawingSnapshot.symbol == normalized_symbol,
        )
        .order_by(ChartDrawingSnapshot.updated_at.desc(), ChartDrawingSnapshot.id.desc())
        .all()
    )


def upsert_chart_drawing_snapshot(
    *,
    db: Session,
    market: str,
    symbol: str,
    timeframe: str,
    drawings: list[dict[str, Any]],
    label: str | None = None,
    time_mode: str | None = None,
    selected_drawing_id: str | None = None,
    summary: dict[str, Any] | None = None,
    source: str = "frontend",
) -> ChartDrawingSnapshot:
    normalized_market = _normalize_key(market, field_name="market", max_length=20)
    normalized_symbol = _normalize_key(symbol, field_name="symbol", max_length=40)
    normalized_timeframe = _normalize_key(
        timeframe,
        field_name="timeframe",
        max_length=20,
        uppercase=False,
    )
    normalized_source = _normalize_key(
        source or "frontend",
        field_name="source",
        max_length=80,
        uppercase=False,
    )
    normalized_drawings = _normalize_drawings(drawings)
    now = _now()

    row = get_chart_drawing_snapshot(
        db=db,
        market=normalized_market,
        symbol=normalized_symbol,
        timeframe=normalized_timeframe,
    )

    if row is None:
        row = ChartDrawingSnapshot(
            market=normalized_market,
            symbol=normalized_symbol,
            timeframe=normalized_timeframe,
            created_at=now,
        )
        db.add(row)

    row.label = label.strip()[:120] if label else None
    row.time_mode = time_mode.strip()[:20] if time_mode else None
    row.selected_drawing_id = selected_drawing_id.strip()[:120] if selected_drawing_id else None
    row.drawing_count = len(normalized_drawings)
    row.drawings_json = _json_dumps(normalized_drawings)
    row.summary_json = _json_dumps(summary) if isinstance(summary, dict) else None
    row.source = normalized_source
    row.updated_at = now

    db.commit()
    db.refresh(row)
    return row


def delete_chart_drawing_snapshot(
    *,
    db: Session,
    market: str,
    symbol: str,
    timeframe: str,
) -> None:
    row = get_chart_drawing_snapshot(
        db=db,
        market=market,
        symbol=symbol,
        timeframe=timeframe,
    )

    if row is None:
        raise ChartDrawingSnapshotNotFoundError(
            f"Chart drawing snapshot for {market}:{symbol}:{timeframe} was not found."
        )

    db.delete(row)
    db.commit()
