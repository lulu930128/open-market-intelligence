from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.db.models import ResourceQuoteSnapshot, USDailyPrice
from app.market.adr_parity import FX_STALE_AFTER_SECONDS, resolve_adr_mapping
from app.market.calendar_status import expected_us_trade_date
from app.market.cross_market.proxy_signal_engine import PROXY_BENCHMARK_RULES
from app.market.cross_market.relation_store import build_relation_registry_read
from app.market.cross_market.types import taiwan_stock_ref
from app.resource_market import service as resource_market_service
from app.us_market import service as us_market_service


MAX_REFRESH_SYMBOLS = 8
MAX_REFRESH_STOCK_IDS = 32
ProgressCallback = Callable[[int | None, int | None, str | None], None]


def normalize_refresh_stock_ids(value: str | list[str]) -> list[str]:
    raw_values = value if isinstance(value, list) else value.split(",")
    normalized: list[str] = []
    for raw_value in raw_values:
        stock_id = str(raw_value).strip().upper()
        if not stock_id:
            continue
        taiwan_stock_ref(stock_id)
        if stock_id not in normalized:
            normalized.append(stock_id)
    if not normalized:
        raise ValueError("at least one Taiwan stock_id is required")
    if len(normalized) > MAX_REFRESH_STOCK_IDS:
        raise ValueError(
            f"cross-market refresh accepts at most {MAX_REFRESH_STOCK_IDS} stock ids"
        )
    return normalized


def _normalized_now(value: datetime | None) -> datetime:
    now = value or datetime.now(timezone.utc)
    return now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)


def _latest_us_trade_date(db: Session, symbol: str):
    row = (
        db.query(USDailyPrice)
        .filter(USDailyPrice.symbol == symbol)
        .order_by(
            USDailyPrice.trade_date.desc(),
            USDailyPrice.updated_at.desc(),
            USDailyPrice.id.desc(),
        )
        .first()
    )
    return row.trade_date if row is not None else None


def _latest_fx_snapshot(db: Session) -> ResourceQuoteSnapshot | None:
    return (
        db.query(ResourceQuoteSnapshot)
        .filter(ResourceQuoteSnapshot.symbol.in_(("USD-TWD", "TWD-USD")))
        .order_by(
            ResourceQuoteSnapshot.fetched_at.desc(),
            ResourceQuoteSnapshot.id.desc(),
        )
        .first()
    )


def _fx_status(
    db: Session,
    *,
    now: datetime,
) -> tuple[str, datetime | None]:
    row = _latest_fx_snapshot(db)
    if row is None:
        return "missing", None
    as_of = row.event_time or row.fetched_at
    normalized = as_of if as_of.tzinfo is not None else as_of.replace(tzinfo=timezone.utc)
    age_seconds = max(
        0,
        int(
            (
                now.astimezone(timezone.utc)
                - normalized.astimezone(timezone.utc)
            ).total_seconds()
        ),
    )
    return (
        "current" if age_seconds <= FX_STALE_AFTER_SECONDS else "stale",
        as_of,
    )


def build_cross_market_refresh_plan(
    db: Session,
    stock_ids: str | list[str],
    *,
    max_symbols: int = MAX_REFRESH_SYMBOLS,
    now: datetime | None = None,
) -> dict[str, Any]:
    if max_symbols < 1 or max_symbols > MAX_REFRESH_SYMBOLS:
        raise ValueError(f"max_symbols must be between 1 and {MAX_REFRESH_SYMBOLS}")
    normalized_stock_ids = normalize_refresh_stock_ids(stock_ids)
    planned_at = _normalized_now(now)
    expected_date = expected_us_trade_date(
        "us_daily_price",
        now=planned_at,
    ) or planned_at.date()

    mapping_entries: list[dict[str, Any]] = []
    adr_targets: dict[str, list[str]] = {}
    us_targets: dict[str, set[str]] = {}
    source_roles: dict[str, set[str]] = {}
    missing_relations: list[str] = []
    for stock_id in normalized_stock_ids:
        resolution = resolve_adr_mapping(
            db,
            stock_id,
            as_of=planned_at.date(),
            data_available_at=planned_at,
        )
        mapping = resolution.mapping
        mapping_entries.append(
            {
                "stock_id": stock_id,
                "mapping_resolution": resolution.as_payload(),
                "adr_symbol": mapping.adr_symbol if mapping is not None else None,
            }
        )
        registry = build_relation_registry_read(
            db,
            stock_id,
            as_of=planned_at.date(),
            generated_at=planned_at,
            data_available_at=planned_at,
        )
        if mapping is not None:
            adr_targets.setdefault(mapping.adr_symbol, []).append(stock_id)
            us_targets.setdefault(mapping.adr_symbol, set()).add(stock_id)
            source_roles.setdefault(mapping.adr_symbol, set()).add("direct_source")

        usable_relations = [item for item in registry.relations if item.decision_usable]
        for relation in usable_relations:
            source_symbol = str(relation.source.provider_symbol or "").strip().upper()
            if relation.source.market == "US" and source_symbol:
                us_targets.setdefault(source_symbol, set()).add(stock_id)
                source_roles.setdefault(source_symbol, set()).add(
                    "direct_source"
                    if relation.bucket == "direct_equivalent"
                    else "proxy_source"
                )
            rule = PROXY_BENCHMARK_RULES.get(str(relation.relation_subtype or ""))
            if rule is not None:
                benchmark_symbol = rule.benchmark_symbol.strip().upper()
                us_targets.setdefault(benchmark_symbol, set()).add(stock_id)
                source_roles.setdefault(benchmark_symbol, set()).add(
                    "proxy_benchmark"
                )

        if mapping is None and not usable_relations:
            missing_relations.append(stock_id)

    candidates: list[dict[str, Any]] = []
    fx_status, fx_as_of = _fx_status(db, now=planned_at)
    if fx_status != "current" and adr_targets:
        candidates.append(
            {
                "source_kind": "resource_quote",
                "symbol": "USD-TWD",
                "targets": sorted({item for values in adr_targets.values() for item in values}),
                "status": fx_status,
                "latest": fx_as_of,
                "expected": "age<=72h",
            }
        )

    for symbol, targets in sorted(us_targets.items()):
        latest_date = _latest_us_trade_date(db, symbol)
        status = (
            "missing"
            if latest_date is None
            else "stale"
            if latest_date < expected_date
            else "current"
        )
        if status == "current":
            continue
        candidates.append(
            {
                "source_kind": "us_daily_price",
                "symbol": symbol,
                "targets": sorted(targets),
                "roles": sorted(source_roles.get(symbol, set())),
                "status": status,
                "latest": latest_date,
                "expected": expected_date,
            }
        )

    planned_sources = candidates[:max_symbols]
    deferred_sources = candidates[max_symbols:]
    return {
        "kind": "cross_market_context_refresh_plan",
        "planned_at": planned_at,
        "expected_dates": {"us_daily_price": expected_date},
        "requested_stock_ids": normalized_stock_ids,
        "mapping_entries": mapping_entries,
        "requested_source_count": len(candidates),
        "planned_source_count": len(planned_sources),
        "deferred_source_count": len(deferred_sources),
        "max_symbols": max_symbols,
        "planned_sources": planned_sources,
        "deferred_sources": deferred_sources,
        "missing_relations": missing_relations,
        "read_path_provider_refresh": False,
    }


def refresh_cross_market_context_sources(
    db: Session,
    stock_ids: str | list[str],
    *,
    max_symbols: int = MAX_REFRESH_SYMBOLS,
    provider: str = "auto",
    outputsize: str = "compact",
    max_runtime_seconds: int = 120,
    progress_callback: ProgressCallback | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if provider not in {"auto", "alphavantage", "yahoo_chart"}:
        raise ValueError("provider must be one of: auto, alphavantage, yahoo_chart")
    if outputsize not in {"compact", "full"}:
        raise ValueError("outputsize must be compact or full")
    if max_runtime_seconds < 10 or max_runtime_seconds > 300:
        raise ValueError("max_runtime_seconds must be between 10 and 300")

    plan = build_cross_market_refresh_plan(
        db,
        stock_ids,
        max_symbols=max_symbols,
        now=now,
    )
    sources = list(plan["planned_sources"])
    total = len(sources)
    attempted = 0
    succeeded = 0
    failed = 0
    deferred = int(plan["deferred_source_count"])
    results: list[dict[str, Any]] = []
    started = time.monotonic()

    if progress_callback is not None:
        progress_callback(0, max(total, 1), "Refreshing cross-market context sources.")

    for source in sources:
        if time.monotonic() - started >= max_runtime_seconds:
            deferred += total - attempted
            break
        attempted += 1
        source_kind = source["source_kind"]
        symbol = source["symbol"]
        try:
            if source_kind == "us_daily_price":
                result = us_market_service.refresh_us_daily_prices(
                    db=db,
                    symbol=symbol,
                    outputsize=outputsize,
                    adjusted=False,
                    provider=provider,
                )
                success = result.get("status") in {"success", "partial_success"}
            elif source_kind == "resource_quote":
                result = resource_market_service.refresh_resource_quotes(
                    db,
                    symbols=symbol,
                )
                success = int(result.get("error_count") or 0) == 0 and int(
                    result.get("refreshed_count") or 0
                ) > 0
            else:
                raise ValueError(f"unsupported source_kind: {source_kind}")
            if success:
                succeeded += 1
            else:
                failed += 1
            results.append(
                {
                    "source_kind": source_kind,
                    "symbol": symbol,
                    "status": "success" if success else "failed",
                    "result": result,
                }
            )
        except Exception as exc:  # provider failures stay isolated per source.
            db.rollback()
            failed += 1
            results.append(
                {
                    "source_kind": source_kind,
                    "symbol": symbol,
                    "status": "failed",
                    "error": str(exc),
                }
            )
        if progress_callback is not None:
            progress_callback(
                attempted,
                max(total, 1),
                f"Processed {attempted}/{total} cross-market sources.",
            )

    status = (
        "no_refresh_needed"
        if total == 0
        else "success"
        if failed == 0 and deferred == 0
        else "partial"
        if succeeded > 0
        else "failed"
    )
    return {
        "kind": "cross_market_context_refresh_result",
        "status": status,
        "requested_count": int(plan["requested_source_count"]),
        "attempted_count": attempted,
        "success_count": succeeded,
        "failed_count": failed,
        "deferred_count": deferred,
        "max_symbols": max_symbols,
        "max_runtime_seconds": max_runtime_seconds,
        "provider": provider,
        "outputsize": outputsize,
        "plan": plan,
        "results": results,
    }
