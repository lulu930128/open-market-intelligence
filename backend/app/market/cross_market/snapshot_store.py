from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
from typing import Any, Iterable

from sqlalchemy import inspect, or_
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db.models import CrossMarketRelation, CrossMarketSignalSnapshot
from app.db.write_coordination import is_sqlite_locked_error
from app.market.cross_market.context import build_cross_market_target_context
from app.market.cross_market.schemas import CrossMarketTargetContextRead
from app.market.cross_market.types import taiwan_stock_ref


SNAPSHOT_TABLE = "cross_market_signal_snapshot"
SNAPSHOT_MATERIALIZER = "app.market.cross_market.snapshot_store.v1"
MAX_BATCH_STOCKS = 500
LATEST_CACHE_LIMITATION = "latest_local_cache_projection_not_materialized_snapshot"
SUPERSEDED_SNAPSHOT_LIMITATION = "materialized_snapshot_superseded_by_local_inputs"
_UNSET = object()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def _serialized_payload(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _payload_content_hash(payload: dict[str, Any]) -> str:
    hash_payload = json.loads(_serialized_payload(payload))
    hash_payload["payload_hash"] = None
    passport = hash_payload.get("evidence_passport")
    if isinstance(passport, dict):
        passport["payload_hash"] = None
    serialized = _serialized_payload(hash_payload)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _payload_json(context: CrossMarketTargetContextRead) -> tuple[str, str]:
    payload = context.model_dump(mode="json")
    payload_hash = _payload_content_hash(payload)
    if context.projection_source == "materialized_snapshot":
        if context.payload_hash != payload_hash:
            raise RuntimeError("cross-market materialized payload hash is inconsistent")
        passport = payload.get("evidence_passport")
        if isinstance(passport, dict) and passport.get("payload_hash") != payload_hash:
            raise RuntimeError(
                "cross-market evidence passport payload hash is inconsistent"
            )
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return serialized, payload_hash


def _input_lineage_hash(context: CrossMarketTargetContextRead) -> str | None:
    freshness = context.freshness if isinstance(context.freshness, dict) else {}
    passport = (
        context.evidence_passport
        if isinstance(context.evidence_passport, dict)
        else {}
    )
    value = freshness.get("input_lineage_hash") or passport.get(
        "input_lineage_hash"
    )
    normalized = str(value or "").strip()
    return normalized or None


def _superseded_local_context(
    current: CrossMarketTargetContextRead,
    materialized: CrossMarketTargetContextRead,
) -> CrossMarketTargetContextRead:
    payload = current.model_dump(mode="json")
    payload["limitations"] = list(
        dict.fromkeys(
            [
                *(payload.get("limitations") or []),
                SUPERSEDED_SNAPSHOT_LIMITATION,
            ]
        )
    )
    superseded = {
        "snapshot_id": materialized.snapshot_id,
        "decision_at": materialized.decision_at,
        "source_cutoff_at": materialized.source_cutoff_at,
        "input_lineage_hash": _input_lineage_hash(materialized),
    }
    freshness = dict(payload.get("freshness") or {})
    freshness["superseded_materialized_snapshot"] = superseded
    payload["freshness"] = freshness
    passport = dict(payload.get("evidence_passport") or {})
    passport["limitations"] = list(
        dict.fromkeys(
            [
                *(passport.get("limitations") or []),
                SUPERSEDED_SNAPSHOT_LIMITATION,
            ]
        )
    )
    passport["superseded_materialized_snapshot"] = superseded
    payload["evidence_passport"] = passport
    return CrossMarketTargetContextRead.model_validate(payload)


def _matching_local_context(
    current: CrossMarketTargetContextRead,
    materialized: CrossMarketTargetContextRead,
) -> CrossMarketTargetContextRead:
    payload = current.model_dump(mode="json")
    matching = {
        "snapshot_id": materialized.snapshot_id,
        "decision_at": materialized.decision_at,
        "source_cutoff_at": materialized.source_cutoff_at,
        "input_lineage_hash": _input_lineage_hash(materialized),
    }
    freshness = dict(payload.get("freshness") or {})
    freshness["matching_materialized_snapshot"] = matching
    payload["freshness"] = freshness
    passport = dict(payload.get("evidence_passport") or {})
    passport["matching_materialized_snapshot"] = matching
    payload["evidence_passport"] = passport
    return CrossMarketTargetContextRead.model_validate(payload)


def _materialized_context(
    context: CrossMarketTargetContextRead,
    *,
    materialized_at: datetime,
    materialized_by: str,
    source_cutoff_at: datetime,
) -> CrossMarketTargetContextRead:
    payload = context.model_dump(mode="json")
    payload["projection_source"] = "materialized_snapshot"
    payload["source_cutoff_at"] = _iso_utc(source_cutoff_at)
    payload["materialized_at"] = _iso_utc(materialized_at)
    payload["materialized_by"] = materialized_by
    payload["payload_hash"] = "pending"
    payload["limitations"] = [
        value
        for value in payload.get("limitations") or []
        if value != LATEST_CACHE_LIMITATION
    ]
    freshness = dict(payload.get("freshness") or {})
    freshness["projection_source"] = "materialized_snapshot"
    freshness["source_cutoff_at"] = _iso_utc(source_cutoff_at)
    payload["freshness"] = freshness
    passport = dict(payload.get("evidence_passport") or {})
    passport.update(
        {
            "projection_source": "materialized_snapshot",
            "source_cutoff_at": _iso_utc(source_cutoff_at),
            "materialized_at": _iso_utc(materialized_at),
            "materialized_by": materialized_by,
            "payload_hash": "pending",
            "limitations": [
                value
                for value in passport.get("limitations") or []
                if value != LATEST_CACHE_LIMITATION
            ],
        }
    )
    payload["evidence_passport"] = passport
    payload = CrossMarketTargetContextRead.model_validate(payload).model_dump(mode="json")
    payload["payload_hash"] = None
    passport = dict(payload.get("evidence_passport") or {})
    passport["payload_hash"] = None
    payload["evidence_passport"] = passport
    payload_hash = _payload_content_hash(payload)
    payload["payload_hash"] = payload_hash
    passport["payload_hash"] = payload_hash
    return CrossMarketTargetContextRead.model_validate(payload)


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
    materialized_at: datetime | None = None,
) -> CrossMarketSignalSnapshot:
    if not snapshot_table_available(db):
        raise RuntimeError("cross_market_signal_snapshot table is unavailable")

    normalized_decision_at = _utc(decision_at)
    normalized_materializer = str(materialized_by or "").strip()
    if not normalized_materializer:
        raise ValueError("materialized_by is required")
    latest_context = build_cross_market_target_context(
        db,
        stock_id,
        decision_at=normalized_decision_at,
        expected_adr_trade_date=expected_adr_trade_date,
        data_available_at=normalized_decision_at,
    )
    existing = (
        db.query(CrossMarketSignalSnapshot)
        .filter(
            CrossMarketSignalSnapshot.target_canonical_symbol
            == latest_context.target.canonical_symbol,
            CrossMarketSignalSnapshot.decision_at == normalized_decision_at,
            CrossMarketSignalSnapshot.methodology_version
            == latest_context.methodology_version,
        )
        .one_or_none()
    )
    if existing is not None:
        context = _materialized_context(
            latest_context,
            materialized_at=_utc(existing.materialized_at),
            materialized_by=existing.materialized_by,
            source_cutoff_at=_utc(existing.source_cutoff_at),
        )
        serialized, payload_hash = _payload_json(context)
        if (
            existing.projection_source != "materialized_snapshot"
            or existing.payload_hash != payload_hash
            or existing.payload_json != serialized
            or existing.snapshot_id != context.snapshot_id
            or existing.relation_snapshot_version
            != context.relation_snapshot_version
        ):
            raise RuntimeError(
                "cross-market snapshot is non-deterministic for the same target, "
                "decision_at, and methodology_version"
            )
        return existing

    normalized_materialized_at = _utc(materialized_at or _now())
    context = _materialized_context(
        latest_context,
        materialized_at=normalized_materialized_at,
        materialized_by=normalized_materializer,
        source_cutoff_at=normalized_decision_at,
    )
    serialized, payload_hash = _payload_json(context)

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
        projection_source="materialized_snapshot",
        source_cutoff_at=normalized_decision_at,
        materialized_at=normalized_materialized_at,
        materialized_by=normalized_materializer,
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
    materialized_at: datetime | None = None,
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
    normalized_materialized_at = _utc(materialized_at or _now())
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
                    materialized_at=normalized_materialized_at,
                )
            snapshot_ids.append(snapshot.snapshot_id)
            if existing_count:
                reused_count += 1
            else:
                materialized_count += 1
        except Exception as exc:
            if isinstance(exc, OperationalError) and is_sqlite_locked_error(exc):
                raise
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
        "materialized_at": normalized_materialized_at.isoformat(),
        "provider_refresh_attempted": False,
    }


def load_latest_cross_market_context_snapshots(
    db: Session,
    stock_ids: Iterable[str],
    *,
    as_of_at: datetime,
    exact_decision_at: datetime | None = None,
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
    query = db.query(CrossMarketSignalSnapshot).filter(
            CrossMarketSignalSnapshot.target_canonical_symbol.in_(
                list(stock_by_target)
            ),
            CrossMarketSignalSnapshot.decision_at <= _utc(as_of_at),
        )
    if exact_decision_at is not None:
        query = query.filter(
            CrossMarketSignalSnapshot.decision_at == _utc(exact_decision_at)
        )
    rows = (
        query
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
        try:
            serialized, payload_hash = _payload_json(context)
        except RuntimeError:
            continue
        if (
            context.projection_source != "materialized_snapshot"
            or context.snapshot_id != row.snapshot_id
            or context.payload_hash != row.payload_hash
            or payload_hash != row.payload_hash
            or serialized != row.payload_json
            or _utc(context.source_cutoff_at) != _utc(row.source_cutoff_at)
            or _utc(context.materialized_at) != _utc(row.materialized_at)
            or context.materialized_by != row.materialized_by
        ):
            continue
        contexts[stock_id] = context
    return contexts


def read_cross_market_target_context(
    db: Session,
    stock_id: str,
    *,
    as_of_at: datetime | None = None,
    expected_adr_trade_date: date | None = None,
    adr_parity_payload: dict[str, Any] | None | object = _UNSET,
    prefer_materialized: bool = True,
    projection_mode: str = "current",
) -> CrossMarketTargetContextRead:
    normalized_as_of = _utc(as_of_at or _now())
    normalized_mode = str(projection_mode or "").strip().lower()
    if normalized_mode not in {"current", "replay"}:
        raise ValueError("projection_mode must be current or replay")
    materialized: CrossMarketTargetContextRead | None = None
    if prefer_materialized:
        loaded = load_latest_cross_market_context_snapshots(
            db,
            [stock_id],
            as_of_at=normalized_as_of,
        )
        materialized = loaded.get(str(stock_id or "").strip().upper())
        if normalized_mode == "replay" and materialized is not None:
            return materialized
    kwargs: dict[str, Any] = {
        "decision_at": normalized_as_of,
        "expected_adr_trade_date": expected_adr_trade_date,
        "data_available_at": normalized_as_of,
    }
    if adr_parity_payload is not _UNSET:
        kwargs["adr_parity_payload"] = adr_parity_payload
    current = build_cross_market_target_context(
        db,
        stock_id,
        **kwargs,
    )
    if materialized is None:
        return current
    materialized_hash = _input_lineage_hash(materialized)
    current_hash = _input_lineage_hash(current)
    if (
        materialized_hash is not None
        and current_hash is not None
        and materialized_hash == current_hash
    ):
        return _matching_local_context(current, materialized)
    return _superseded_local_context(current, materialized)


__all__ = [
    "MAX_BATCH_STOCKS",
    "SNAPSHOT_MATERIALIZER",
    "SUPERSEDED_SNAPSHOT_LIMITATION",
    "load_latest_cross_market_context_snapshots",
    "materialize_cross_market_context_batch",
    "materialize_cross_market_context_snapshot",
    "read_cross_market_target_context",
    "snapshot_table_available",
]
