from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
from typing import Any, Iterable

from sqlalchemy import inspect, or_
from sqlalchemy.orm import Session

from app.db.models import CrossMarketRelation, CrossMarketSignalSnapshot
from app.market.cross_market.context import build_cross_market_target_context
from app.market.cross_market.schemas import CrossMarketTargetContextRead
from app.market.cross_market.types import taiwan_stock_ref


SNAPSHOT_TABLE = "cross_market_signal_snapshot"
SNAPSHOT_MATERIALIZER = "app.market.cross_market.snapshot_store.v1"
MAX_BATCH_STOCKS = 500


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _payload_json(context: CrossMarketTargetContextRead) -> tuple[str, str]:
    payload = context.model_dump(mode="json")
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return serialized, hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def snapshot_table_available(db: Session) -> bool:
    # Use the session-owned connection. Inspecting the Engine can borrow the same
    # DBAPI connection used by an in-memory SQLite session and roll back its
    # pending transaction when the inspector closes it.
    return inspect(db.connection()).has_table(SNAPSHOT_TABLE)


def materialize_cross_market_context_snapshot(
    db: Session,
    stock_id: str,
    *,
    decision_at: datetime,
    expected_adr_trade_date: date | None = None,
    materialized_by: str = SNAPSHOT_MATERIALIZER,
) -> CrossMarketSignalSnapshot:
    if not snapshot_table_available(db):
        raise RuntimeError("cross_market_signal_snapshot table is unavailable")

    normalized_decision_at = _utc(decision_at)
    context = build_cross_market_target_context(
        db,
        stock_id,
        decision_at=normalized_decision_at,
        expected_adr_trade_date=expected_adr_trade_date,
        data_available_at=normalized_decision_at,
    )
    serialized, payload_hash = _payload_json(context)
    existing = (
        db.query(CrossMarketSignalSnapshot)
        .filter(
            CrossMarketSignalSnapshot.target_canonical_symbol
            == context.target.canonical_symbol,
            CrossMarketSignalSnapshot.decision_at == normalized_decision_at,
            CrossMarketSignalSnapshot.methodology_version
            == context.methodology_version,
        )
        .one_or_none()
    )
    if existing is not None:
        if existing.payload_hash != payload_hash or existing.snapshot_id != context.snapshot_id:
            raise RuntimeError(
                "cross-market snapshot is non-deterministic for the same target, "
                "decision_at, and methodology_version"
            )
        return existing

    snapshot = CrossMarketSignalSnapshot(
        snapshot_id=context.snapshot_id,
        schema_version=context.schema_version,
        methodology_version=context.methodology_version,
        relation_snapshot_version=context.relation_snapshot_version,
        target_market=context.target.market,
        target_canonical_symbol=context.target.canonical_symbol,
        target_provider_symbol=context.target.provider_symbol,
        decision_at=normalized_decision_at,
        as_of=context.as_of,
        status=context.status,
        decision_usable=context.decision_usable,
        coverage_ratio=Decimal(str(context.coverage.coverage_ratio)),
        payload_hash=payload_hash,
        payload_json=serialized,
        materialized_by=materialized_by,
    )
    db.add(snapshot)
    db.flush()
    return snapshot


def _eligible_stock_ids(
    db: Session,
    *,
    stock_ids: list[str],
    decision_date: date,
) -> list[str]:
    if not stock_ids:
        return []
    target_symbols = [taiwan_stock_ref(stock_id).canonical_symbol for stock_id in stock_ids]
    rows = (
        db.query(CrossMarketRelation.target_provider_symbol)
        .filter(
            CrossMarketRelation.target_canonical_symbol.in_(target_symbols),
            CrossMarketRelation.review_status == "approved",
            CrossMarketRelation.is_active.is_(True),
            CrossMarketRelation.valid_from <= decision_date,
            or_(
                CrossMarketRelation.valid_to.is_(None),
                CrossMarketRelation.valid_to >= decision_date,
            ),
        )
        .distinct()
        .all()
    )
    eligible = {str(value).strip() for (value,) in rows if value}
    return [stock_id for stock_id in stock_ids if stock_id in eligible]


def materialize_cross_market_context_batch(
    db: Session,
    stock_ids: Iterable[str],
    *,
    decision_at: datetime,
    expected_adr_trade_date: date | None = None,
    materialized_by: str = SNAPSHOT_MATERIALIZER,
) -> dict[str, Any]:
    normalized = list(
        dict.fromkeys(str(stock_id or "").strip().upper() for stock_id in stock_ids)
    )
    if len(normalized) > MAX_BATCH_STOCKS:
        raise ValueError(f"cross-market snapshot batch exceeds {MAX_BATCH_STOCKS} stocks")
    if not snapshot_table_available(db):
        return {
            "status": "unavailable",
            "requested_count": len(normalized),
            "eligible_count": 0,
            "materialized_count": 0,
            "reused_count": 0,
            "errors": ["cross_market_signal_snapshot_table_unavailable"],
        }

    normalized_decision_at = _utc(decision_at)
    eligible = _eligible_stock_ids(
        db,
        stock_ids=normalized,
        decision_date=normalized_decision_at.date(),
    )
    materialized_count = 0
    reused_count = 0
    snapshot_ids: list[str] = []
    errors: list[dict[str, str]] = []
    for stock_id in eligible:
        try:
            existing_count = (
                db.query(CrossMarketSignalSnapshot.id)
                .filter(
                    CrossMarketSignalSnapshot.target_canonical_symbol
                    == taiwan_stock_ref(stock_id).canonical_symbol,
                    CrossMarketSignalSnapshot.decision_at == normalized_decision_at,
                )
                .count()
            )
            with db.begin_nested():
                snapshot = materialize_cross_market_context_snapshot(
                    db,
                    stock_id,
                    decision_at=normalized_decision_at,
                    expected_adr_trade_date=expected_adr_trade_date,
                    materialized_by=materialized_by,
                )
            snapshot_ids.append(snapshot.snapshot_id)
            if existing_count:
                reused_count += 1
            else:
                materialized_count += 1
        except Exception as exc:
            errors.append({"stock_id": stock_id, "error": str(exc)})

    return {
        "status": "partial" if errors else "ready",
        "requested_count": len(normalized),
        "eligible_count": len(eligible),
        "materialized_count": materialized_count,
        "reused_count": reused_count,
        "snapshot_ids": snapshot_ids,
        "errors": errors,
        "decision_at": normalized_decision_at.isoformat(),
        "provider_refresh_attempted": False,
    }


def load_latest_cross_market_context_snapshots(
    db: Session,
    stock_ids: Iterable[str],
    *,
    as_of_at: datetime,
) -> dict[str, CrossMarketTargetContextRead]:
    normalized = list(
        dict.fromkeys(str(stock_id or "").strip().upper() for stock_id in stock_ids)
    )
    if not normalized or not snapshot_table_available(db):
        return {}
    target_by_stock = {
        stock_id: taiwan_stock_ref(stock_id).canonical_symbol for stock_id in normalized
    }
    stock_by_target = {value: key for key, value in target_by_stock.items()}
    rows = (
        db.query(CrossMarketSignalSnapshot)
        .filter(
            CrossMarketSignalSnapshot.target_canonical_symbol.in_(
                list(stock_by_target)
            ),
            CrossMarketSignalSnapshot.decision_at <= _utc(as_of_at),
        )
        .order_by(
            CrossMarketSignalSnapshot.target_canonical_symbol.asc(),
            CrossMarketSignalSnapshot.decision_at.desc(),
            CrossMarketSignalSnapshot.id.desc(),
        )
        .all()
    )
    contexts: dict[str, CrossMarketTargetContextRead] = {}
    for row in rows:
        stock_id = stock_by_target.get(row.target_canonical_symbol)
        if stock_id is None or stock_id in contexts:
            continue
        try:
            context = CrossMarketTargetContextRead.model_validate_json(row.payload_json)
        except ValueError:
            continue
        if context.snapshot_id != row.snapshot_id:
            continue
        contexts[stock_id] = context
    return contexts


__all__ = [
    "MAX_BATCH_STOCKS",
    "SNAPSHOT_MATERIALIZER",
    "load_latest_cross_market_context_snapshots",
    "materialize_cross_market_context_batch",
    "materialize_cross_market_context_snapshot",
    "snapshot_table_available",
]
