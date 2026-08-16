from __future__ import annotations

from datetime import datetime, timedelta, timezone
import time
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.db.models import (
    ProviderEvent,
    ResourceOhlcvBar,
    ResourceQuoteSnapshot,
    USDailyPrice,
)
from app.market.adr_parity import resolve_adr_mapping
from app.market.calendar_status import expected_us_trade_date
from app.market.cross_market.proxy_signal_engine import PROXY_BENCHMARK_RULES
from app.market.cross_market.relation_store import build_relation_registry_read
from app.market.cross_market.types import taiwan_stock_ref
from app.observability.provider_health import ERROR_STATUSES, record_provider_event
from app.resource_market import service as resource_market_service
from app.resource_market.fx_freshness import evaluate_fx_freshness, fx_daily_data_date
from app.us_market import service as us_market_service


MAX_REFRESH_SYMBOLS = 8
MAX_REFRESH_STOCK_IDS = 32
REFRESH_FAILURE_COOLDOWN_SECONDS = 300
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


def _latest_fx_evidence(
    db: Session,
    *,
    expected_data_date,
) -> dict[str, Any] | None:
    daily_rows = (
        db.query(ResourceOhlcvBar)
        .filter(ResourceOhlcvBar.symbol.in_(("USD-TWD", "TWD-USD")))
        .filter(ResourceOhlcvBar.interval == "1d")
        .order_by(
            ResourceOhlcvBar.bar_time.desc(),
            ResourceOhlcvBar.fetched_at.desc(),
            ResourceOhlcvBar.id.desc(),
        )
        .limit(160)
        .all()
    )
    aligned = next(
        (
            row
            for row in daily_rows
            if fx_daily_data_date(row.bar_time, row.raw_payload_json)
            == expected_data_date
            and isinstance(row.close_price, (int, float))
            and row.close_price > 0
        ),
        None,
    )
    if aligned is not None:
        data_date = fx_daily_data_date(aligned.bar_time, aligned.raw_payload_json)
        return {
            "as_of": aligned.bar_time,
            "fetched_at": aligned.fetched_at,
            "data_date": data_date,
            "source_resource": "resource_ohlcv_bar.1d",
        }

    snapshot = (
        db.query(ResourceQuoteSnapshot)
        .filter(ResourceQuoteSnapshot.symbol.in_(("USD-TWD", "TWD-USD")))
        .order_by(
            ResourceQuoteSnapshot.fetched_at.desc(),
            ResourceQuoteSnapshot.id.desc(),
        )
        .first()
    )
    if snapshot is None:
        return None
    return {
        "as_of": snapshot.event_time or snapshot.fetched_at,
        "fetched_at": snapshot.fetched_at,
        "data_date": None,
        "source_resource": "resource_quote_snapshot",
    }


def _fx_status(
    db: Session,
    *,
    now: datetime,
) -> tuple[str, datetime | None, dict[str, Any]]:
    expected_data_date = expected_us_trade_date(
        "us_daily_price",
        now=now,
    )
    evidence = _latest_fx_evidence(
        db,
        expected_data_date=expected_data_date or now.date(),
    )
    evaluation = evaluate_fx_freshness(
        purpose="adr_alignment",
        now=now,
        event_time=evidence.get("as_of") if evidence is not None else None,
        fetched_at=evidence.get("fetched_at") if evidence is not None else None,
        data_date=evidence.get("data_date") if evidence is not None else None,
        expected_data_date=expected_data_date or now.date(),
    )
    payload = evaluation.as_payload()
    if evidence is not None:
        payload["source_resource"] = evidence["source_resource"]
    return evaluation.status, evidence.get("as_of") if evidence else None, payload


def _refresh_event_target(source_kind: str, symbol: str) -> str:
    return f"{source_kind}:{symbol}"


def _active_failure_cooldown(
    db: Session,
    *,
    source_kind: str,
    symbol: str,
    now: datetime,
) -> tuple[ProviderEvent | None, datetime | None]:
    threshold = now.astimezone(timezone.utc) - timedelta(
        seconds=REFRESH_FAILURE_COOLDOWN_SECONDS
    )
    event = (
        db.query(ProviderEvent)
        .filter(ProviderEvent.market == "cross_market")
        .filter(ProviderEvent.provider == "cross_market_orchestrator")
        .filter(ProviderEvent.resource == "context_source")
        .filter(
            ProviderEvent.target == _refresh_event_target(source_kind, symbol)
        )
        .filter(ProviderEvent.status.in_(ERROR_STATUSES))
        .filter(ProviderEvent.event_time >= threshold)
        .order_by(ProviderEvent.event_time.desc(), ProviderEvent.id.desc())
        .first()
    )
    if event is None:
        return None, None
    event_time = event.event_time
    normalized_event_time = (
        event_time
        if event_time.tzinfo is not None
        else event_time.replace(tzinfo=timezone.utc)
    )
    cooldown_until = normalized_event_time.astimezone(timezone.utc) + timedelta(
        seconds=REFRESH_FAILURE_COOLDOWN_SECONDS
    )
    if cooldown_until <= now.astimezone(timezone.utc):
        return None, None
    return event, cooldown_until


def _record_refresh_failure(
    db: Session,
    *,
    source_kind: str,
    symbol: str,
    provider: str,
    error_message: str,
    event_time: datetime,
    detail: dict[str, Any] | None = None,
) -> None:
    try:
        record_provider_event(
            db,
            market="cross_market",
            provider="cross_market_orchestrator",
            resource="context_source",
            target=_refresh_event_target(source_kind, symbol),
            status="failed",
            event_type="cross_market_refresh",
            event_time=event_time,
            observed_at=event_time,
            message="Bounded cross-market source refresh failed; cooldown applied.",
            error_message=error_message[:1_000],
            detail={
                "source_kind": source_kind,
                "symbol": symbol,
                "requested_provider": provider,
                "cooldown_seconds": REFRESH_FAILURE_COOLDOWN_SECONDS,
                **(detail or {}),
            },
        )
    except Exception:
        db.rollback()


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
    fx_status, fx_as_of, fx_freshness = _fx_status(db, now=planned_at)
    if not bool(fx_freshness.get("usable")) and adr_targets:
        candidates.append(
            {
                "source_kind": "resource_quote",
                "symbol": "USD-TWD",
                "targets": sorted({item for values in adr_targets.values() for item in values}),
                "status": fx_status,
                "latest": fx_as_of,
                "expected": expected_date,
                "freshness": fx_freshness,
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

    eligible_sources: list[dict[str, Any]] = []
    cooldown_sources: list[dict[str, Any]] = []
    session_deferred_sources: list[dict[str, Any]] = []
    for source in candidates:
        freshness = source.get("freshness")
        if (
            isinstance(freshness, dict)
            and not bool(freshness.get("refresh_eligible"))
        ):
            session_deferred_sources.append(
                {
                    **source,
                    "deferred_reason": "fx_session_not_refreshable",
                    "next_eligible_at": freshness.get("next_expected_update_at"),
                }
            )
            continue
        event, cooldown_until = _active_failure_cooldown(
            db,
            source_kind=str(source["source_kind"]),
            symbol=str(source["symbol"]),
            now=planned_at,
        )
        if event is None or cooldown_until is None:
            eligible_sources.append(source)
            continue
        cooldown_sources.append(
            {
                **source,
                "deferred_reason": "refresh_failure_cooldown",
                "cooldown_until": cooldown_until,
                "last_failure_event_id": event.id,
                "last_failure_at": event.event_time,
                "last_failure_status": event.status,
            }
        )

    planned_sources = eligible_sources[:max_symbols]
    deferred_sources = [
        *session_deferred_sources,
        *cooldown_sources,
        *eligible_sources[max_symbols:],
    ]
    return {
        "kind": "cross_market_context_refresh_plan",
        "planned_at": planned_at,
        "expected_dates": {
            "us_daily_price": expected_date,
            "resource_fx.USD-TWD": expected_date,
        },
        "requested_stock_ids": normalized_stock_ids,
        "mapping_entries": mapping_entries,
        "requested_source_count": len(candidates),
        "planned_source_count": len(planned_sources),
        "deferred_source_count": len(deferred_sources),
        "cooldown_source_count": len(cooldown_sources),
        "session_deferred_source_count": len(session_deferred_sources),
        "cooldown_seconds": REFRESH_FAILURE_COOLDOWN_SECONDS,
        "max_symbols": max_symbols,
        "planned_sources": planned_sources,
        "deferred_sources": deferred_sources,
        "cooldown_sources": cooldown_sources,
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
    refresh_started_at = _normalized_now(now)

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
                result = resource_market_service.refresh_resource_market_snapshot(
                    db,
                    symbols=symbol,
                    intervals="1d",
                    limit=10,
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
                _record_refresh_failure(
                    db,
                    source_kind=source_kind,
                    symbol=symbol,
                    provider=provider,
                    error_message=(
                        str(result.get("error_message") or result.get("message") or "")
                        or "Provider refresh returned an unsuccessful result."
                    ),
                    event_time=refresh_started_at,
                    detail={
                        "result_status": result.get("status"),
                        "error_count": result.get("error_count"),
                    },
                )
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
            _record_refresh_failure(
                db,
                source_kind=source_kind,
                symbol=symbol,
                provider=provider,
                error_message=str(exc),
                event_time=refresh_started_at,
            )
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
        "cooldown"
        if total == 0 and int(plan["cooldown_source_count"]) > 0
        else "no_refresh_needed"
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
