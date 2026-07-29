from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.ai.agentic_common import _json_ready, _list_rows
from app.ai.evidence_passport import build_evidence_passport
from app.ai.market_context.common import (
    append_source_ref_once as _append_source_ref_once,
    compact_market_context as _compact_market_context,
    freshness_effective_status,
    latest_timestamp_from_rows as _latest_timestamp_from_rows,
)
from app.ai.market_context.regional_params import (
    _market_data_int,
    _market_data_param,
    _market_data_str,
)
from app.ai.market_payload_contract import payload_level as _market_payload_level
from app.crypto_market.contract import (
    PERPETUAL,
    SPOT,
    list_provider_instruments,
    normalize_symbol as normalize_crypto_symbol,
)


@dataclass(frozen=True)
class CryptoContextDependencies:
    crypto_market_service: Any
    get_crypto_asset: Callable[..., Any]
    build_crypto_source_health: Callable[..., dict[str, Any]]
    now: Callable[[], datetime]


def _crypto_supported_symbols_for_asset(asset: str, *, instrument_type: str | None = None, resource: str = "ticker") -> list[str]:
    symbols: list[str] = []
    for instrument in list_provider_instruments(instrument_type=instrument_type, resource=resource):
        if instrument.base_asset != asset:
            continue
        if instrument.symbol in symbols:
            continue
        symbols.append(instrument.symbol)
    return symbols


def _crypto_asset_from_symbol(
    symbol: str | None,
    *,
    dependencies: CryptoContextDependencies,
) -> str | None:
    normalized = normalize_crypto_symbol(symbol)
    if "-" not in normalized:
        return normalized if dependencies.get_crypto_asset(normalized) is not None else None
    base = normalized.split("-", maxsplit=1)[0]
    return base if dependencies.get_crypto_asset(base) is not None else None


def _crypto_requested_symbols(
    *,
    asset: str | None,
    market_data_params: dict[str, Any] | None,
    instrument_type: str | None,
) -> list[str] | None:
    symbols_value = _market_data_param(market_data_params, "symbols")
    if symbols_value is None:
        symbols_value = _market_data_param(market_data_params, "symbol")
    if symbols_value:
        if isinstance(symbols_value, str):
            return [normalize_crypto_symbol(part) for part in symbols_value.split(",") if part.strip()]
        if isinstance(symbols_value, (list, tuple)):
            return [normalize_crypto_symbol(part) for part in symbols_value if str(part).strip()]

    if asset:
        supported = _crypto_supported_symbols_for_asset(
            asset,
            instrument_type=instrument_type,
            resource="ticker",
        )
        return supported or [f"{asset}-USDT"]
    return None


def _requested_crypto_capabilities(
    market_data_params: dict[str, Any] | None,
) -> set[str]:
    value = _market_data_param(market_data_params, "requested_capabilities")
    if isinstance(value, str):
        return {part.strip() for part in value.split(",") if part.strip()}
    if isinstance(value, (list, tuple, set)):
        return {str(part).strip() for part in value if str(part).strip()}
    return set()


def _crypto_capability_limit(
    market_data_params: dict[str, Any] | None,
    capability_id: str,
    *,
    default: int,
) -> int:
    raw_limits = _market_data_param(market_data_params, "capability_limits")
    raw_value = raw_limits.get(capability_id) if isinstance(raw_limits, dict) else None
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        return default
    return max(1, min(raw_value, 500))


def _crypto_ohlcv_projection(rows: list[Any]) -> list[dict[str, Any]]:
    def bar_time(row: Any) -> str:
        value = (
            row.get("bar_time")
            if isinstance(row, dict)
            else getattr(row, "bar_time", None)
        )
        return str(_json_ready(value) or "")

    chronological_rows = sorted(rows, key=bar_time)
    projected = _list_rows(
        chronological_rows,
        (
            "provider",
            "exchange",
            "symbol",
            "instrument_type",
            "interval",
            "bar_time",
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "base_volume",
            "quote_volume",
            "base_asset",
            "quote_asset",
            "fetched_at",
        ),
    )
    for item in projected:
        base_unit = str(item.pop("base_asset", "") or "").strip().upper() or None
        quote_unit = str(item.pop("quote_asset", "") or "").strip().upper() or None
        item["base_volume_unit"] = base_unit
        item["quote_volume_unit"] = quote_unit
        item["volume_unit"] = base_unit
        item["volume_semantics"] = "interval_base_and_quote_volume"
        item["volume_status"] = (
            "available"
            if item.get("base_volume") is not None
            or item.get("quote_volume") is not None
            else "missing"
        )
    return projected


def _crypto_market_cap_matches_asset(row: Any, asset_definition: Any) -> bool:
    if asset_definition is None:
        return True
    coin_id = str(getattr(asset_definition, "coin_id", "") or "").strip()
    if coin_id and str(getattr(row, "coin_id", "") or "").strip() == coin_id:
        return True
    return str(getattr(row, "symbol", "") or "").strip().upper() == asset_definition.asset


_EVENT_DRIVEN_CRYPTO_RESOURCES = {
    "crypto_cvd_perpetual",
    "crypto_cvd_spot",
    "crypto_liquidation_event",
    "crypto_liquidation_heatmap",
    "crypto_realtime_liquidation_event",
}


def _crypto_health_status(
    source_health: dict[str, Any],
    *,
    resources: set[str],
    available: bool,
) -> str:
    entries = [
        entry
        for entry in (source_health.get("entries") or [])
        if isinstance(entry, dict) and entry.get("resource") in resources
    ]
    if any(entry.get("ok") is True for entry in entries):
        return "current"
    problem_statuses = [
        status
        for entry in entries
        if (status := freshness_effective_status(entry.get("status") or entry.get("data_quality")))
        in {"partial", "missing", "stale", "blocked", "failed"}
    ]
    for status in ("failed", "blocked", "stale", "missing", "partial"):
        if status in problem_statuses:
            return status
    return "partial" if available else "missing"


def _crypto_core_source_health_status(source_health: dict[str, Any]) -> str:
    problem_statuses: list[str] = []
    current_count = 0
    for entry in source_health.get("entries") or []:
        if not isinstance(entry, dict) or not entry.get("required"):
            continue
        resource = str(entry.get("resource") or "")
        status = freshness_effective_status(entry.get("status") or entry.get("data_quality"))
        if resource in _EVENT_DRIVEN_CRYPTO_RESOURCES and status == "missing":
            continue
        if entry.get("ok") is True:
            current_count += 1
        elif status in {"partial", "missing", "stale", "blocked", "failed"}:
            problem_statuses.append(status)
    for status in ("failed", "blocked", "stale", "missing", "partial"):
        if status in problem_statuses:
            return status
    return "current" if current_count else "partial"


def read_crypto_context(
    db: Session,
    *,
    asset: str | None = None,
    tool_runs: list[dict[str, Any]] | None = None,
    market_data_params: dict[str, Any] | None = None,
    context_limit: int = 100,
    dependencies: CryptoContextDependencies,
) -> dict[str, Any]:
    tool_runs = tool_runs or []
    requested_asset = str(asset or "").strip().upper() or None
    params_symbol = _market_data_str(market_data_params, "symbol")
    if requested_asset is None and params_symbol:
        requested_asset = _crypto_asset_from_symbol(
            params_symbol,
            dependencies=dependencies,
        )
    asset_definition = dependencies.get_crypto_asset(requested_asset) if requested_asset else None
    if requested_asset and asset_definition is None:
        warnings = [f"Unsupported crypto asset: {requested_asset}."]
        target = {"type": "crypto_asset", "id": requested_asset, "label": requested_asset, "market": "crypto"}
        payload_level = _market_payload_level(market_data_params)
        envelope = {
            "kind": "crypto_asset_context",
            "generated_at": dependencies.now().isoformat(),
            "as_of": None,
            "scope": {"target": target},
            "summary": {},
            "data": {"compact": _compact_market_context(kind="crypto_asset_compact_evidence", target=target, quote={}, resources={}, freshness={}, payload_level=payload_level)},
            "missing": ["crypto_asset"],
            "warnings": warnings,
            "source_refs": [],
        }
        envelope["evidence_passport"] = build_evidence_passport(
            kind="crypto_asset_context",
            missing=envelope["missing"],
            warnings=warnings,
            confidence="low",
            tool_runs=tool_runs,
        )
        return envelope

    normalized_asset = asset_definition.asset if asset_definition else None
    instrument_type = _market_data_str(market_data_params, "instrument_type")
    provider = _market_data_str(market_data_params, "provider")
    interval = _market_data_str(market_data_params, "interval", "1m") or "1m"
    limit = _market_data_int(market_data_params, "limit", min(context_limit, 100), minimum=1, maximum=500)
    payload_level = _market_payload_level(market_data_params)
    requested_capabilities = _requested_crypto_capabilities(market_data_params)
    history_limit = min(limit, 100)
    requested_symbols = _crypto_requested_symbols(
        asset=normalized_asset,
        market_data_params=market_data_params,
        instrument_type=instrument_type,
    )
    derivative_symbols = (
        _crypto_supported_symbols_for_asset(normalized_asset, instrument_type=PERPETUAL, resource="derivatives")
        if normalized_asset
        else None
    )
    if normalized_asset and not derivative_symbols and normalized_asset != "USDT":
        derivative_symbols = [f"{normalized_asset}-USDT"]

    warnings: list[str] = [
        "Crypto AI context is read-only local-cache evidence; refresh endpoints are separate bounded POST operations.",
    ]
    missing: list[str] = []
    source_refs: list[dict[str, Any]] = []

    tickers = dependencies.crypto_market_service.list_latest_crypto_tickers(
        db,
        provider=provider,
        symbols=requested_symbols,
        instrument_type=instrument_type,
        limit=limit,
    )
    order_books = dependencies.crypto_market_service.list_latest_crypto_order_books(
        db,
        provider=provider,
        symbols=requested_symbols,
        instrument_type=instrument_type,
        limit=limit,
    )
    ohlcv_rows = dependencies.crypto_market_service.list_latest_crypto_ohlcv_bars(
        db,
        provider=provider,
        symbols=requested_symbols,
        instrument_type=instrument_type or SPOT,
        interval=interval,
        limit=limit,
    )
    intraday_ohlcv_rows = ohlcv_rows if interval != "1d" else []
    daily_ohlcv_rows = ohlcv_rows if interval == "1d" else []
    if "intraday.bars" in requested_capabilities and not intraday_ohlcv_rows:
        intraday_ohlcv_rows = (
            dependencies.crypto_market_service.list_latest_crypto_ohlcv_bars(
                db,
                provider=provider,
                symbols=requested_symbols,
                instrument_type=instrument_type or SPOT,
                interval="1m",
                limit=_crypto_capability_limit(
                    market_data_params,
                    "intraday.bars",
                    default=min(limit, 100),
                ),
            )
        )
    if "daily.ohlcv" in requested_capabilities and not daily_ohlcv_rows:
        daily_ohlcv_rows = (
            dependencies.crypto_market_service.list_latest_crypto_ohlcv_bars(
                db,
                provider=provider,
                symbols=requested_symbols,
                instrument_type=instrument_type or SPOT,
                interval="1d",
                limit=_crypto_capability_limit(
                    market_data_params,
                    "daily.ohlcv",
                    default=min(limit, 100),
                ),
            )
        )
    coverage = dependencies.crypto_market_service.list_crypto_ohlcv_coverage(
        db,
        provider=provider,
        symbols=requested_symbols,
        instrument_type=instrument_type,
    )
    derivatives = dependencies.crypto_market_service.list_latest_crypto_derivatives(
        db,
        provider=provider,
        symbols=derivative_symbols or requested_symbols,
        limit=limit,
    )
    market_caps = dependencies.crypto_market_service.list_latest_crypto_market_caps(db, vs_currency="usd", limit=100)
    if normalized_asset:
        market_caps = [
            row for row in market_caps if _crypto_market_cap_matches_asset(row, asset_definition)
        ]
    spreads = dependencies.crypto_market_service.list_latest_crypto_spreads(
        db,
        base=normalized_asset,
        global_provider=provider,
        limit=limit,
    )
    ticker_history = dependencies.crypto_market_service.list_crypto_ticker_history(
        db,
        provider=provider,
        symbols=requested_symbols,
        instrument_type=instrument_type,
        limit=history_limit,
        ascending=False,
    )
    liquidity_history = dependencies.crypto_market_service.list_crypto_liquidity_history(
        db,
        provider=provider,
        symbols=requested_symbols,
        instrument_type=instrument_type,
        limit=history_limit,
        ascending=False,
    )
    derivatives_history = dependencies.crypto_market_service.list_crypto_derivatives_history(
        db,
        provider=provider,
        symbols=derivative_symbols or requested_symbols,
        instrument_type=PERPETUAL if derivative_symbols else instrument_type,
        limit=history_limit,
        ascending=False,
    )
    long_short_history = dependencies.crypto_market_service.list_crypto_long_short_ratio_history(
        db,
        provider=provider,
        symbols=derivative_symbols or requested_symbols,
        instrument_type=PERPETUAL if derivative_symbols else instrument_type,
        limit=history_limit,
        ascending=False,
    )
    liquidation_heatmap = dependencies.crypto_market_service.list_crypto_liquidation_heatmap_cells(
        db,
        symbols=derivative_symbols or requested_symbols,
        instrument_type=PERPETUAL if derivative_symbols else instrument_type,
        limit=min(history_limit, 200),
        ascending=False,
    )
    provider_contract = dependencies.crypto_market_service.get_crypto_provider_contract()
    source_health = dependencies.build_crypto_source_health(
        db,
        provider=provider,
        base=normalized_asset,
        required_only=False,
        include_events=False,
        max_entries=min(max(limit, 20), 100),
    )

    if not tickers:
        missing.append("crypto_ticker")
    if not order_books:
        missing.append("crypto_order_book")
    if not ohlcv_rows:
        missing.append("crypto_ohlcv")
    if normalized_asset and not market_caps and asset_definition and asset_definition.market_cap:
        missing.append("crypto_market_cap")

    for entry in source_health.get("entries") or []:
        if (
            isinstance(entry, dict)
            and not entry.get("ok", True)
            and not (
                entry.get("resource") in _EVENT_DRIVEN_CRYPTO_RESOURCES
                and freshness_effective_status(entry.get("status")) == "missing"
            )
        ):
            warnings.append(
                f"Crypto source health {entry.get('status')}: {entry.get('resource')} {entry.get('provider')} {entry.get('target')} - {entry.get('reason')}"
            )

    primary_ticker = tickers[0] if tickers else None
    as_of = _latest_timestamp_from_rows(
        [
            *tickers,
            *order_books,
            *ohlcv_rows,
            *intraday_ohlcv_rows,
            *daily_ohlcv_rows,
            *derivatives,
            *market_caps,
            *spreads,
        ],
        ("fetched_at", "event_time", "bar_time", "last_updated", "observed_at"),
    )
    target_id = normalized_asset if normalized_asset else "market"
    target_label = asset_definition.name if asset_definition else "Crypto Market"
    target_type = "crypto_asset" if normalized_asset else "crypto_market"
    target = {"type": target_type, "id": target_id, "label": target_label, "market": "crypto"}
    quote_freshness_status = _crypto_health_status(
        source_health,
        resources={"crypto_ticker", "crypto_realtime_ticker"},
        available=bool(tickers),
    )
    order_book_freshness_status = _crypto_health_status(
        source_health,
        resources={"crypto_order_book", "crypto_realtime_order_book"},
        available=bool(order_books),
    )
    ohlcv_freshness_status = _crypto_health_status(
        source_health,
        resources={"crypto_ohlcv", "crypto_realtime_ohlcv"},
        available=bool(ohlcv_rows),
    )
    market_cap_freshness_status = _crypto_health_status(
        source_health,
        resources={"crypto_market_cap"},
        available=bool(market_caps),
    )
    core_source_health_status = _crypto_core_source_health_status(source_health)

    _append_source_ref_once(source_refs, {"type": "table", "name": "crypto_ticker_snapshot"})
    _append_source_ref_once(source_refs, {"type": "table", "name": "crypto_order_book_snapshot"})
    _append_source_ref_once(source_refs, {"type": "table", "name": "crypto_ohlcv_bar"})
    _append_source_ref_once(source_refs, {"type": "table", "name": "crypto_derivatives_metric"})
    _append_source_ref_once(source_refs, {"type": "table", "name": "crypto_market_cap_snapshot"})
    _append_source_ref_once(source_refs, {"type": "table", "name": "crypto_spread_snapshot"})
    _append_source_ref_once(source_refs, {"type": "derived", "name": "app.crypto_market.source_health"})
    data = {
        "provider_contract": {
            "kind": provider_contract.get("kind"),
            "execution_enabled": provider_contract.get("execution_enabled"),
            "ai_execution_enabled": provider_contract.get("ai_execution_enabled"),
            "notes": provider_contract.get("notes") or [],
            "ohlcv_intervals": provider_contract.get("ohlcv_intervals") or {},
            "selected_asset": asset_definition.to_dict() if asset_definition else None,
        },
        "latest_tickers": _list_rows(
            tickers,
            (
                "provider",
                "exchange",
                "symbol",
                "provider_symbol",
                "base_asset",
                "quote_asset",
                "instrument_type",
                "last_price",
                "bid_price",
                "ask_price",
                "high_24h",
                "low_24h",
                "price_change_24h",
                "price_change_pct_24h",
                "base_volume_24h",
                "quote_volume_24h",
                "event_time",
                "fetched_at",
            ),
        ),
        "order_books": _list_rows(
            order_books,
            (
                "provider",
                "exchange",
                "symbol",
                "instrument_type",
                "depth_limit",
                "best_bid_price",
                "best_bid_size",
                "best_ask_price",
                "best_ask_size",
                "spread",
                "spread_pct",
                "event_time",
                "fetched_at",
            ),
        ),
        "ohlcv": _list_rows(
            ohlcv_rows,
            (
                "provider",
                "exchange",
                "symbol",
                "instrument_type",
                "interval",
                "bar_time",
                "open_price",
                "high_price",
                "low_price",
                "close_price",
                "base_volume",
                "quote_volume",
                "fetched_at",
            ),
        ),
        "ohlcv_coverage": _json_ready(coverage),
        "derivatives": _list_rows(
            derivatives,
            (
                "provider",
                "exchange",
                "symbol",
                "instrument_type",
                "mark_price",
                "index_price",
                "funding_rate",
                "next_funding_time",
                "open_interest",
                "open_interest_value",
                "event_time",
                "fetched_at",
            ),
        ),
        "market_caps": _list_rows(
            market_caps,
            (
                "provider",
                "coin_id",
                "symbol",
                "name",
                "vs_currency",
                "current_price",
                "market_cap",
                "market_cap_rank",
                "total_volume",
                "price_change_pct_24h",
                "last_updated",
                "fetched_at",
            ),
        ),
        "spreads": _list_rows(
            spreads,
            (
                "base_asset",
                "local_provider",
                "global_provider",
                "local_symbol",
                "global_symbol",
                "fx_symbol",
                "local_price",
                "global_price",
                "fx_rate",
                "implied_twd_price",
                "spread",
                "spread_pct",
                "observed_at",
            ),
        ),
        "history": {
            "tickers": _list_rows(
                ticker_history,
                (
                    "provider",
                    "symbol",
                    "instrument_type",
                    "last_price",
                    "bid_price",
                    "ask_price",
                    "price_change_pct_24h",
                    "base_volume_24h",
                    "quote_volume_24h",
                    "sampled_at",
                    "fetched_at",
                ),
            ),
            "liquidity": _list_rows(
                liquidity_history,
                (
                    "provider",
                    "symbol",
                    "instrument_type",
                    "depth_limit",
                    "best_bid_price",
                    "best_ask_price",
                    "spread",
                    "spread_pct",
                    "sampled_at",
                    "fetched_at",
                ),
            ),
            "derivatives": _list_rows(
                derivatives_history,
                (
                    "provider",
                    "symbol",
                    "instrument_type",
                    "mark_price",
                    "funding_rate",
                    "open_interest",
                    "sampled_at",
                    "fetched_at",
                ),
            ),
            "long_short_ratio": _list_rows(
                long_short_history,
                (
                    "provider",
                    "symbol",
                    "instrument_type",
                    "ratio_scope",
                    "long_ratio",
                    "short_ratio",
                    "long_short_ratio",
                    "sampled_at",
                    "fetched_at",
                ),
            ),
            "liquidation_heatmap": _list_rows(
                liquidation_heatmap,
                (
                    "provider",
                    "source_kind",
                    "method",
                    "symbol",
                    "instrument_type",
                    "time_bucket",
                    "bucket_seconds",
                    "price_bucket",
                    "liquidation_side",
                    "liquidation_notional",
                    "event_count",
                    "intensity",
                    "fetched_at",
                ),
            ),
        },
        "source_health": _json_ready(source_health),
        "tool_runs": tool_runs,
    }
    data["compact"] = _compact_market_context(
        kind="crypto_asset_compact_evidence" if normalized_asset else "crypto_market_compact_evidence",
        target=target,
        quote={
            "source": "crypto_ticker_snapshot",
            "provider": primary_ticker.provider if primary_ticker else None,
            "symbol": primary_ticker.symbol if primary_ticker else None,
            "instrument_type": primary_ticker.instrument_type if primary_ticker else None,
            "price": primary_ticker.last_price if primary_ticker else None,
            "bid": primary_ticker.bid_price if primary_ticker else None,
            "ask": primary_ticker.ask_price if primary_ticker else None,
            "change_pct_24h": primary_ticker.price_change_pct_24h if primary_ticker else None,
            "quote_time": primary_ticker.event_time.isoformat() if primary_ticker and primary_ticker.event_time else None,
            "event_time": primary_ticker.event_time.isoformat() if primary_ticker and primary_ticker.event_time else None,
            "fetched_at": primary_ticker.fetched_at.isoformat() if primary_ticker else None,
            "received_at": primary_ticker.fetched_at.isoformat() if primary_ticker else None,
            "market_status": "continuous",
            "session_phase": "continuous",
            "timezone": "UTC",
            "is_realtime": False,
        },
        resources={
            "ticker_rows": len(tickers),
            "order_book_rows": len(order_books),
            "ohlcv_rows": len(ohlcv_rows),
            "ohlcv_coverage_rows": len(coverage),
            "derivatives_rows": len(derivatives),
            "market_cap_rows": len(market_caps),
            "spread_rows": len(spreads),
            "history_rows": {
                "ticker": len(ticker_history),
                "liquidity": len(liquidity_history),
                "derivatives": len(derivatives_history),
                "long_short_ratio": len(long_short_history),
                "liquidation_heatmap": len(liquidation_heatmap),
            },
            "provider": provider,
            "symbols": requested_symbols,
            "interval": interval,
            "limit": limit,
            "payload_level": payload_level,
        },
        freshness={
            "quote": quote_freshness_status,
            "order_book": order_book_freshness_status,
            "ohlcv": ohlcv_freshness_status,
            "market_cap": market_cap_freshness_status,
            "source_health": core_source_health_status,
        },
        payload_level=payload_level,
    )
    if "crypto.order_book" in requested_capabilities:
        data["compact"]["order_book"] = _list_rows(
            order_books[
                : _crypto_capability_limit(
                    market_data_params,
                    "crypto.order_book",
                    default=10,
                )
            ],
            (
                "provider",
                "exchange",
                "symbol",
                "instrument_type",
                "depth_limit",
                "best_bid_price",
                "best_bid_size",
                "best_ask_price",
                "best_ask_size",
                "spread",
                "spread_pct",
                "event_time",
                "fetched_at",
            ),
        )
    if "intraday.bars" in requested_capabilities:
        intraday_limit = _crypto_capability_limit(
            market_data_params,
            "intraday.bars",
            default=20,
        )
        intraday_bars = _crypto_ohlcv_projection(
            intraday_ohlcv_rows[:intraday_limit]
        )
        data["compact"]["intraday_bars"] = {
            "interval": "1m",
            "sort_order": "asc",
            "point_count": len(intraday_ohlcv_rows),
            "returned_point_count": len(intraday_bars),
            "bars": intraday_bars,
            "provider": provider,
            "freshness": {"status": ohlcv_freshness_status},
        }
    if "daily.ohlcv" in requested_capabilities:
        daily_limit = _crypto_capability_limit(
            market_data_params,
            "daily.ohlcv",
            default=30,
        )
        daily_bars = _crypto_ohlcv_projection(daily_ohlcv_rows[:daily_limit])
        data["compact"]["daily_chart"] = {
            "interval": "1d",
            "sort_order": "asc",
            "point_count": len(daily_ohlcv_rows),
            "returned_point_count": len(daily_bars),
            "bars": daily_bars,
            "provider": provider,
            "freshness": {"status": ohlcv_freshness_status},
        }
    if "crypto.derivatives" in requested_capabilities:
        data["compact"]["derivatives"] = _list_rows(
            derivatives[
                : _crypto_capability_limit(
                    market_data_params,
                    "crypto.derivatives",
                    default=10,
                )
            ],
            (
                "provider",
                "exchange",
                "symbol",
                "instrument_type",
                "mark_price",
                "index_price",
                "funding_rate",
                "next_funding_time",
                "open_interest",
                "open_interest_value",
                "event_time",
                "fetched_at",
            ),
        )
    envelope = {
        "kind": "crypto_asset_context" if normalized_asset else "crypto_market_context",
        "generated_at": dependencies.now().isoformat(),
        "as_of": as_of,
        "scope": {"target": target},
        "summary": {
            "latest_price": primary_ticker.last_price if primary_ticker else None,
            "latest_symbol": primary_ticker.symbol if primary_ticker else None,
            "latest_provider": primary_ticker.provider if primary_ticker else None,
            "latest_fetched_at": primary_ticker.fetched_at.isoformat() if primary_ticker else None,
            "source_health": source_health.get("summary"),
        },
        "data": data,
        "data_limitations": [
            "GET/read paths use local cache only; POST refresh endpoints are required for external data fetch.",
            "Crypto contract is watch/research only and exposes no order placement endpoint.",
            "Event-driven resources such as liquidations can be empty without implying provider failure.",
        ],
        "missing": list(dict.fromkeys(missing)),
        "warnings": list(dict.fromkeys(warnings)),
        "source_refs": source_refs,
    }
    core_statuses = [
        quote_freshness_status,
        ohlcv_freshness_status,
        core_source_health_status,
    ]
    if normalized_asset and asset_definition and asset_definition.market_cap:
        core_statuses.append(market_cap_freshness_status)
    context_is_current = all(status == "current" for status in core_statuses)
    freshness_result = {
        "kind": "crypto_asset_freshness" if normalized_asset else "crypto_market_freshness",
        "scope": {"target": target},
        "is_current": context_is_current,
        "refresh_recommended": bool(missing) or not context_is_current,
        "missing": envelope["missing"],
        "warnings": envelope["warnings"],
        "as_of": as_of,
        "source_health": source_health.get("summary"),
        "domains": {
            "quote": quote_freshness_status,
            "order_book": order_book_freshness_status,
            "ohlcv": ohlcv_freshness_status,
            "market_cap": market_cap_freshness_status,
            "source_health": core_source_health_status,
        },
    }
    envelope["evidence_passport"] = build_evidence_passport(
        kind=envelope["kind"],
        as_of=envelope["as_of"],
        source_refs=source_refs,
        missing=envelope["missing"],
        warnings=envelope["warnings"],
        freshness=freshness_result,
        tool_runs=tool_runs,
    )
    return envelope
