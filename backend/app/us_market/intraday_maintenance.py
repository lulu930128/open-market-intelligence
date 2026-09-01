"""Bounded maintenance transactions for persisted US intraday datasets."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import case, extract, func, or_
from sqlalchemy.orm import Session

from app.db.models import (
    MarketIntradayBar,
    MarketIntradayBarLineage,
    USQuoteSnapshot,
)


US_QUOTE_RETENTION_DAYS = 30
US_YAHOO_INTRADAY_PROVIDERS = ("yahoo_chart", "yahoo_finance_chart")
US_YAHOO_INTRADAY_MARKETS = (
    "US",
    "NASDAQ",
    "NYSE",
    "SP_INDEX",
    "NASDAQ_INDEX",
    "DJI_INDEX",
    "CBOE_INDEX",
)
US_YAHOO_INTRADAY_REPAIR_CONTRACT = "omi.us.intraday_minute_repair.v1"

_BAR_MANIFEST_FIELDS = (
    "id", "source_id", "provider", "stock_id", "market", "canonical_market",
    "venue", "instrument_type", "symbol", "interval", "bar_time",
    "open_price", "high_price", "low_price", "close_price", "trade_volume",
    "trade_value", "source", "source_url", "created_at", "updated_at",
)
_LINEAGE_MANIFEST_FIELDS = (
    "id", "bar_id", "source_id", "raw_result_id", "provider", "source",
    "authority", "raw_contract_version", "event_at", "received_at",
    "fetched_at", "finalization", "source_interval", "calculation_version",
    "component_raw_result_ids_json", "created_at", "updated_at",
)
_BAR_DATETIME_FIELDS = {"bar_time", "created_at", "updated_at"}
_LINEAGE_DATETIME_FIELDS = {
    "event_at", "received_at", "fetched_at", "created_at", "updated_at",
}
_BAR_VALUE_FIELDS = (
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "trade_volume",
    "trade_value",
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _json_value(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def _snapshot(model: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: _json_value(getattr(model, field)) for field in fields}


def _restore_values(
    snapshot: dict[str, Any],
    *,
    datetime_fields: set[str],
) -> dict[str, Any]:
    values = dict(snapshot)
    for field in datetime_fields:
        value = values.get(field)
        if value is not None:
            values[field] = datetime.fromisoformat(str(value))
    return values


def _write_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _minute_group_expressions(db: Session):
    dialect = db.get_bind().dialect.name
    if dialect == "sqlite":
        return (
            func.strftime("%Y-%m-%d %H:%M:00", MarketIntradayBar.bar_time),
            func.strftime("%S", MarketIntradayBar.bar_time) != "00",
        )
    if dialect == "postgresql":
        return (
            func.date_trunc("minute", MarketIntradayBar.bar_time),
            extract("second", MarketIntradayBar.bar_time) != 0,
        )
    raise ValueError(
        "US Yahoo intraday minute repair supports SQLite and PostgreSQL only."
    )


def _canonical_minute(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    return _utc(parsed).replace(second=0, microsecond=0)


def _repair_group_rows(
    db: Session,
    *,
    provider: str,
    symbol: str,
    canonical_minute: datetime,
) -> list[tuple[MarketIntradayBar, MarketIntradayBarLineage | None]]:
    minute_start = canonical_minute.replace(tzinfo=None)
    minute_end = (canonical_minute + timedelta(minutes=1)).replace(tzinfo=None)
    return (
        db.query(MarketIntradayBar, MarketIntradayBarLineage)
        .outerjoin(
            MarketIntradayBarLineage,
            MarketIntradayBarLineage.bar_id == MarketIntradayBar.id,
        )
        .filter(MarketIntradayBar.provider == provider)
        .filter(MarketIntradayBar.stock_id == symbol)
        .filter(MarketIntradayBar.interval == "1m")
        .filter(MarketIntradayBar.market.in_(US_YAHOO_INTRADAY_MARKETS))
        .filter(MarketIntradayBar.bar_time >= minute_start)
        .filter(MarketIntradayBar.bar_time < minute_end)
        .order_by(MarketIntradayBar.id.asc())
        .all()
    )


def _recommended_survivor(
    candidates: list[tuple[MarketIntradayBar, MarketIntradayBarLineage | None]],
    *,
    canonical_minute: datetime,
) -> tuple[MarketIntradayBar, MarketIntradayBarLineage | None]:
    minimum = datetime.min.replace(tzinfo=timezone.utc)
    return max(
        candidates,
        key=lambda item: (
            item[1] is not None
            and _utc(item[0].bar_time) == canonical_minute,
            _utc(item[0].bar_time) == canonical_minute,
            item[1] is not None,
            _utc(item[1].fetched_at) if item[1] is not None else minimum,
            _utc(item[1].event_at)
            if item[1] is not None
            else _utc(item[0].bar_time),
            item[0].id,
        ),
    )


def _survivor_after_values(
    candidates: list[tuple[MarketIntradayBar, MarketIntradayBarLineage | None]],
    *,
    canonical_minute: datetime,
) -> tuple[str, dict[str, Any]]:
    canonical_candidates = [
        bar for bar, _ in candidates if _utc(bar.bar_time) == canonical_minute
    ]
    if canonical_candidates:
        canonical_bar = max(canonical_candidates, key=lambda bar: bar.id)
        return (
            "canonical_bar",
            {
                "bar_time": canonical_minute.isoformat(),
                **{
                    field: getattr(canonical_bar, field)
                    for field in _BAR_VALUE_FIELDS
                },
            },
        )

    ordered = sorted(
        candidates,
        key=lambda item: (
            _utc(item[1].event_at)
            if item[1] is not None
            else _utc(item[0].bar_time),
            item[0].id,
        ),
    )
    first_bar = ordered[0][0]
    last_bar = ordered[-1][0]
    high_values = [
        bar.high_price for bar, _ in ordered if bar.high_price is not None
    ]
    low_values = [
        bar.low_price for bar, _ in ordered if bar.low_price is not None
    ]
    volume_values = [
        bar.trade_volume for bar, _ in ordered if bar.trade_volume is not None
    ]
    trade_value_values = [
        bar.trade_value for bar, _ in ordered if bar.trade_value is not None
    ]
    return (
        "aggregate_provisional",
        {
            "bar_time": canonical_minute.isoformat(),
            "open_price": first_bar.open_price,
            "high_price": max(high_values) if high_values else None,
            "low_price": min(low_values) if low_values else None,
            "close_price": last_bar.close_price,
            "trade_volume": max(volume_values) if volume_values else None,
            "trade_value": max(trade_value_values) if trade_value_values else None,
        },
    )


def repair_us_yahoo_intraday_minute_integrity(
    db: Session,
    *,
    apply: bool = False,
    max_groups: int = 200,
    max_candidate_rows: int = 10_000,
    after_group_id: int | None = None,
    audit_manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Plan or apply one bounded, audited US Yahoo 1m identity repair batch."""

    if max_groups < 1 or max_groups > 5_000:
        raise ValueError("max_groups must be between 1 and 5000")
    if max_candidate_rows < 1 or max_candidate_rows > 50_000:
        raise ValueError("max_candidate_rows must be between 1 and 50000")
    if after_group_id is not None and after_group_id < 0:
        raise ValueError("after_group_id must be non-negative")
    if apply and audit_manifest_path is None:
        raise ValueError("audit_manifest_path is required when apply is true")

    minute_bucket, invalid_identity = _minute_group_expressions(db)
    group_count = func.count(MarketIntradayBar.id)
    invalid_count = func.sum(case((invalid_identity, 1), else_=0))
    minimum_id = func.min(MarketIntradayBar.id)
    groups_query = (
        db.query(
            MarketIntradayBar.provider,
            MarketIntradayBar.stock_id,
            minute_bucket.label("canonical_minute"),
            minimum_id.label("minimum_id"),
            group_count.label("row_count"),
            invalid_count.label("invalid_identity_count"),
        )
        .filter(MarketIntradayBar.provider.in_(US_YAHOO_INTRADAY_PROVIDERS))
        .filter(MarketIntradayBar.interval == "1m")
        .filter(MarketIntradayBar.market.in_(US_YAHOO_INTRADAY_MARKETS))
        .group_by(
            MarketIntradayBar.provider,
            MarketIntradayBar.stock_id,
            minute_bucket,
        )
        .having(or_(group_count > 1, invalid_count > 0))
    )
    if after_group_id is not None:
        groups_query = groups_query.having(minimum_id > after_group_id)
    group_rows = groups_query.order_by(minimum_id.asc()).limit(max_groups + 1).all()
    has_more = len(group_rows) > max_groups
    selected_groups = group_rows[:max_groups]
    planned_groups: list[dict[str, Any]] = []
    affected_symbols: set[str] = set()
    affected_dates: set[str] = set()
    missing_lineage_count = 0
    planned_candidate_row_count = 0
    row_budget_exhausted = False

    for group in selected_groups:
        canonical_minute = _canonical_minute(group.canonical_minute)
        candidates = _repair_group_rows(
            db,
            provider=group.provider,
            symbol=group.stock_id,
            canonical_minute=canonical_minute,
        )
        if not candidates:
            continue
        if planned_candidate_row_count + len(candidates) > max_candidate_rows:
            row_budget_exhausted = True
            has_more = True
            break
        planned_candidate_row_count += len(candidates)
        survivor, survivor_lineage = _recommended_survivor(
            candidates,
            canonical_minute=canonical_minute,
        )
        survivor_policy, survivor_after = _survivor_after_values(
            candidates,
            canonical_minute=canonical_minute,
        )
        missing_lineage_count += sum(1 for _, lineage in candidates if lineage is None)
        affected_symbols.add(group.stock_id)
        affected_dates.add(canonical_minute.date().isoformat())
        planned_groups.append(
            {
                "provider": group.provider,
                "symbol": group.stock_id,
                "canonical_minute": canonical_minute.isoformat(),
                "minimum_row_id": int(group.minimum_id),
                "row_count": len(candidates),
                "invalid_identity_count": sum(
                    1 for bar, _ in candidates if _utc(bar.bar_time) != canonical_minute
                ),
                "survivor_id": survivor.id,
                "survivor_policy": survivor_policy,
                "survivor_before": {
                    "bar": _snapshot(survivor, _BAR_MANIFEST_FIELDS),
                    "lineage": (
                        _snapshot(survivor_lineage, _LINEAGE_MANIFEST_FIELDS)
                        if survivor_lineage is not None
                        else None
                    ),
                },
                "survivor_after": survivor_after,
                "deleted": [
                    {
                        "bar": _snapshot(bar, _BAR_MANIFEST_FIELDS),
                        "lineage": (
                            _snapshot(lineage, _LINEAGE_MANIFEST_FIELDS)
                            if lineage is not None
                            else None
                        ),
                    }
                    for bar, lineage in candidates
                    if bar.id != survivor.id
                ],
            }
        )

    next_after_group_id = (
        int(planned_groups[-1]["minimum_row_id"])
        if planned_groups
        else after_group_id
    )
    manifest = {
        "contract_version": US_YAHOO_INTRADAY_REPAIR_CONTRACT,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "prepared" if apply else "dry_run",
        "apply_requested": apply,
        "after_group_id": after_group_id,
        "next_after_group_id": next_after_group_id,
        "max_groups": max_groups,
        "max_candidate_rows": max_candidate_rows,
        "has_more_groups": has_more,
        "row_budget_exhausted": row_budget_exhausted,
        "groups": planned_groups,
    }
    if not apply:
        return {
            "contract_version": US_YAHOO_INTRADAY_REPAIR_CONTRACT,
            "dry_run": True,
            "status": "partial" if has_more else "complete",
            "after_group_id": after_group_id,
            "next_after_group_id": next_after_group_id,
            "planned_group_count": len(planned_groups),
            "planned_candidate_row_count": planned_candidate_row_count,
            "planned_delete_count": sum(len(group["deleted"]) for group in planned_groups),
            "planned_update_count": len(planned_groups),
            "affected_symbol_count": len(affected_symbols),
            "affected_symbols": sorted(affected_symbols),
            "affected_trade_dates": sorted(affected_dates),
            "missing_lineage_count": missing_lineage_count,
            "has_more_groups": has_more,
            "row_budget_exhausted": row_budget_exhausted,
            "writes_performed": 0,
            "groups": [
                {
                    "provider": group["provider"],
                    "symbol": group["symbol"],
                    "canonical_minute": group["canonical_minute"],
                    "minimum_row_id": group["minimum_row_id"],
                    "row_count": group["row_count"],
                    "invalid_identity_count": group["invalid_identity_count"],
                    "survivor_id": group["survivor_id"],
                    "survivor_policy": group["survivor_policy"],
                    "deleted_row_ids": [item["bar"]["id"] for item in group["deleted"]],
                }
                for group in planned_groups[:50]
            ],
            "groups_truncated": len(planned_groups) > 50,
        }

    assert audit_manifest_path is not None
    _write_manifest(audit_manifest_path, manifest)
    bar_rows_deleted = 0
    lineage_rows_deleted = 0
    bar_rows_updated = 0
    try:
        for group in planned_groups:
            survivor_id = int(group["survivor_id"])
            candidate_ids = [
                int(group["survivor_before"]["bar"]["id"]),
                *(int(item["bar"]["id"]) for item in group["deleted"]),
            ]
            candidates = (
                db.query(MarketIntradayBar, MarketIntradayBarLineage)
                .outerjoin(
                    MarketIntradayBarLineage,
                    MarketIntradayBarLineage.bar_id == MarketIntradayBar.id,
                )
                .filter(MarketIntradayBar.id.in_(candidate_ids))
                .all()
            )
            if {bar.id for bar, _ in candidates} != set(candidate_ids):
                raise RuntimeError(
                    "US Yahoo intraday repair candidates changed after manifest preparation."
                )
            for bar, lineage in candidates:
                if bar.id == survivor_id:
                    continue
                if lineage is not None:
                    db.delete(lineage)
                    lineage_rows_deleted += 1
                db.delete(bar)
                bar_rows_deleted += 1
            db.flush()
            survivor = db.get(MarketIntradayBar, survivor_id)
            if survivor is None:
                raise RuntimeError("US Yahoo intraday repair survivor disappeared.")
            for field, value in group["survivor_after"].items():
                if field == "bar_time":
                    value = datetime.fromisoformat(str(value)).replace(tzinfo=None)
                setattr(survivor, field, value)
            survivor.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            bar_rows_updated += 1
        db.commit()
    except Exception:
        db.rollback()
        manifest["status"] = "rolled_back"
        manifest["failed_at"] = datetime.now(timezone.utc).isoformat()
        _write_manifest(audit_manifest_path, manifest)
        raise

    manifest.update(
        status="applied",
        applied_at=datetime.now(timezone.utc).isoformat(),
        bar_rows_deleted=bar_rows_deleted,
        lineage_rows_deleted=lineage_rows_deleted,
        bar_rows_updated=bar_rows_updated,
    )
    manifest_warning = None
    try:
        _write_manifest(audit_manifest_path, manifest)
    except OSError as exc:
        manifest_warning = f"Applied DB batch but could not finalize audit manifest: {exc}"

    return {
        "contract_version": US_YAHOO_INTRADAY_REPAIR_CONTRACT,
        "dry_run": False,
        "status": "partial" if has_more else "complete",
        "after_group_id": after_group_id,
        "next_after_group_id": next_after_group_id,
        "repaired_group_count": len(planned_groups),
        "candidate_row_count": planned_candidate_row_count,
        "bar_rows_deleted": bar_rows_deleted,
        "lineage_rows_deleted": lineage_rows_deleted,
        "bar_rows_updated": bar_rows_updated,
        "affected_symbol_count": len(affected_symbols),
        "affected_symbols": sorted(affected_symbols),
        "affected_trade_dates": sorted(affected_dates),
        "missing_lineage_count": missing_lineage_count,
        "has_more_groups": has_more,
        "row_budget_exhausted": row_budget_exhausted,
        "audit_manifest_path": str(audit_manifest_path),
        "audit_manifest_warning": manifest_warning,
        "writes_performed": bar_rows_deleted + lineage_rows_deleted + bar_rows_updated,
    }


def rollback_us_yahoo_intraday_minute_repair(
    db: Session,
    *,
    audit_manifest_path: Path,
    apply: bool = False,
) -> dict[str, Any]:
    """Validate or apply rollback for one completed minute-repair manifest."""

    manifest = json.loads(audit_manifest_path.read_text(encoding="utf-8"))
    if manifest.get("contract_version") != US_YAHOO_INTRADAY_REPAIR_CONTRACT:
        raise ValueError("unsupported US Yahoo intraday repair manifest")
    if manifest.get("status") != "applied":
        raise ValueError("only an applied US Yahoo intraday repair can be rolled back")

    conflicts: list[dict[str, Any]] = []
    for group in manifest.get("groups") or []:
        survivor_id = int(group["survivor_id"])
        survivor = db.get(MarketIntradayBar, survivor_id)
        expected_time = datetime.fromisoformat(str(group["survivor_after"]["bar_time"]))
        if survivor is None or _utc(survivor.bar_time) != _utc(expected_time):
            conflicts.append({"survivor_id": survivor_id, "reason": "SURVIVOR_CHANGED"})
        for item in group.get("deleted") or []:
            deleted_id = int(item["bar"]["id"])
            if db.get(MarketIntradayBar, deleted_id) is not None:
                conflicts.append({"bar_id": deleted_id, "reason": "DELETED_ROW_ID_REUSED"})
    if conflicts:
        return {
            "contract_version": US_YAHOO_INTRADAY_REPAIR_CONTRACT,
            "dry_run": not apply,
            "status": "blocked",
            "conflicts": conflicts[:100],
            "writes_performed": 0,
        }
    if not apply:
        return {
            "contract_version": US_YAHOO_INTRADAY_REPAIR_CONTRACT,
            "dry_run": True,
            "status": "ready",
            "group_count": len(manifest.get("groups") or []),
            "writes_performed": 0,
        }

    restored_bars = 0
    restored_lineages = 0
    try:
        for group in manifest.get("groups") or []:
            survivor = db.get(MarketIntradayBar, int(group["survivor_id"]))
            if survivor is None:
                raise RuntimeError("US Yahoo intraday rollback survivor disappeared.")
            survivor_values = _restore_values(
                group["survivor_before"]["bar"],
                datetime_fields=_BAR_DATETIME_FIELDS,
            )
            for field, value in survivor_values.items():
                setattr(survivor, field, value)
            for item in group.get("deleted") or []:
                bar_values = _restore_values(
                    item["bar"],
                    datetime_fields=_BAR_DATETIME_FIELDS,
                )
                db.add(MarketIntradayBar(**bar_values))
                restored_bars += 1
            db.flush()
            for item in group.get("deleted") or []:
                lineage_snapshot = item.get("lineage")
                if lineage_snapshot is None:
                    continue
                lineage_values = _restore_values(
                    lineage_snapshot,
                    datetime_fields=_LINEAGE_DATETIME_FIELDS,
                )
                db.add(MarketIntradayBarLineage(**lineage_values))
                restored_lineages += 1
        db.commit()
    except Exception:
        db.rollback()
        raise

    manifest["status"] = "rolled_back"
    manifest["rolled_back_at"] = datetime.now(timezone.utc).isoformat()
    _write_manifest(audit_manifest_path, manifest)
    return {
        "contract_version": US_YAHOO_INTRADAY_REPAIR_CONTRACT,
        "dry_run": False,
        "status": "completed",
        "restored_bar_count": restored_bars,
        "restored_lineage_count": restored_lineages,
        "writes_performed": restored_bars + restored_lineages + len(manifest.get("groups") or []),
    }


def inspect_us_yahoo_intraday_minute_integrity(
    db: Session,
    *,
    max_rows: int = 50_000,
    max_conflicts: int = 200,
) -> dict[str, Any]:
    """Inspect persisted Yahoo 1m identity conflicts without mutating the DB."""

    if max_rows < 1 or max_rows > 250_000:
        raise ValueError("max_rows must be between 1 and 250000")
    if max_conflicts < 0 or max_conflicts > 5_000:
        raise ValueError("max_conflicts must be between 0 and 5000")

    rows = (
        db.query(MarketIntradayBar, MarketIntradayBarLineage)
        .outerjoin(
            MarketIntradayBarLineage,
            MarketIntradayBarLineage.bar_id == MarketIntradayBar.id,
        )
        .filter(MarketIntradayBar.provider.in_(US_YAHOO_INTRADAY_PROVIDERS))
        .filter(MarketIntradayBar.interval == "1m")
        .filter(MarketIntradayBar.market.in_(US_YAHOO_INTRADAY_MARKETS))
        .order_by(MarketIntradayBar.id.asc())
        .limit(max_rows + 1)
        .all()
    )
    has_more = len(rows) > max_rows
    inspected = rows[:max_rows]
    grouped: dict[
        tuple[str, str, datetime],
        list[tuple[MarketIntradayBar, MarketIntradayBarLineage | None]],
    ] = {}
    non_minute_count = 0
    missing_lineage_count = 0
    for bar, lineage in inspected:
        observed_at = _utc(bar.bar_time)
        canonical_minute = observed_at.replace(second=0, microsecond=0)
        if observed_at != canonical_minute:
            non_minute_count += 1
        if lineage is None:
            missing_lineage_count += 1
        grouped.setdefault(
            (bar.provider, bar.stock_id, canonical_minute),
            [],
        ).append((bar, lineage))

    conflict_groups = [
        (key, candidates)
        for key, candidates in grouped.items()
        if len(candidates) > 1
    ]
    conflict_groups.sort(key=lambda item: item[0])
    conflicts: list[dict[str, Any]] = []
    for (provider, symbol, canonical_minute), candidates in conflict_groups[
        :max_conflicts
    ]:
        ranked = sorted(
            candidates,
            key=lambda item: (
                _utc(item[1].fetched_at)
                if item[1] is not None
                else datetime.min.replace(tzinfo=timezone.utc),
                item[0].id,
            ),
        )
        conflicts.append(
            {
                "provider": provider,
                "symbol": symbol,
                "canonical_minute": canonical_minute.isoformat(),
                "row_ids": [bar.id for bar, _ in candidates],
                "bar_times": [_utc(bar.bar_time).isoformat() for bar, _ in candidates],
                "raw_result_ids": [
                    lineage.raw_result_id if lineage is not None else None
                    for _, lineage in candidates
                ],
                "recommended_survivor_id": ranked[-1][0].id,
                "requires_lineage_review": any(
                    lineage is None for _, lineage in candidates
                ),
            }
        )

    return {
        "contract_version": "omi.us.intraday_minute_integrity.v1",
        "dry_run": True,
        "status": "partial" if has_more else "complete",
        "providers": list(US_YAHOO_INTRADAY_PROVIDERS),
        "interval": "1m",
        "max_rows": max_rows,
        "inspected_row_count": len(inspected),
        "non_minute_row_count": non_minute_count,
        "duplicate_minute_bucket_count": len(conflict_groups),
        "rows_in_duplicate_minute_buckets": sum(
            len(candidates) for _, candidates in conflict_groups
        ),
        "missing_lineage_count": missing_lineage_count,
        "reported_conflict_count": len(conflicts),
        "conflicts_truncated": len(conflict_groups) > len(conflicts),
        "has_more_rows": has_more,
        "writes_performed": 0,
        "conflicts": conflicts,
    }


def prune_expired_us_quote_snapshots(
    db: Session,
    *,
    now: datetime | None = None,
    retention_days: int = US_QUOTE_RETENTION_DAYS,
    max_rows: int = 10_000,
) -> dict[str, object]:
    """Delete one bounded batch of Quote snapshots outside the retention horizon."""

    requested_at = now or datetime.now(timezone.utc)
    if requested_at.tzinfo is None or requested_at.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if retention_days < 1 or retention_days > 365:
        raise ValueError("retention_days must be between 1 and 365")
    if max_rows < 1 or max_rows > 50_000:
        raise ValueError("max_rows must be between 1 and 50000")

    cutoff = requested_at.astimezone(timezone.utc) - timedelta(days=retention_days)
    expired_ids = [
        row_id
        for (row_id,) in (
            db.query(USQuoteSnapshot.id)
            .filter(USQuoteSnapshot.event_at < cutoff)
            .order_by(USQuoteSnapshot.event_at.asc(), USQuoteSnapshot.id.asc())
            .limit(max_rows)
            .all()
        )
    ]
    try:
        deleted_count = 0
        if expired_ids:
            deleted_count = (
                db.query(USQuoteSnapshot)
                .filter(USQuoteSnapshot.id.in_(expired_ids))
                .delete(synchronize_session=False)
            )
        remaining_expired = (
            db.query(USQuoteSnapshot.id)
            .filter(USQuoteSnapshot.event_at < cutoff)
            .first()
            is not None
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "contract_version": "omi.us.quote_retention.v1",
        "status": "partial" if remaining_expired else "complete",
        "cutoff": cutoff.isoformat(),
        "retention_days": retention_days,
        "max_rows": max_rows,
        "deleted_count": deleted_count,
        "remaining_expired": remaining_expired,
    }


__all__ = [
    "US_QUOTE_RETENTION_DAYS",
    "US_YAHOO_INTRADAY_MARKETS",
    "US_YAHOO_INTRADAY_PROVIDERS",
    "US_YAHOO_INTRADAY_REPAIR_CONTRACT",
    "inspect_us_yahoo_intraday_minute_integrity",
    "prune_expired_us_quote_snapshots",
    "repair_us_yahoo_intraday_minute_integrity",
    "rollback_us_yahoo_intraday_minute_repair",
]
