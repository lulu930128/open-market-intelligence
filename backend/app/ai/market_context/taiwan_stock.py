from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.ai import evidence_builder, technical_analysis
from app.ai.market_context.common import append_source_ref_once as _append_source_ref_once
from app.ai.market_context.taiwan_projection import (
    COMPACT_INTRADAY_INTERVALS,
    _add_missing,
    _broker_branch_row,
    _build_stock_compact_evidence,
    _compact_intraday_history,
    _compact_quote_snapshot,
    _json_value,
    _latest_date_string,
    _row_dict,
    _stock_dict,
    _with_evidence_passport,
)
from app.ai.market_payload_contract import (
    intraday_point_limit as _intraday_point_limit,
    payload_level as _payload_level,
    slot_envelope as _slot_envelope,
)
from app.market.live_snapshot import classify_market_snapshot, market_status_from_session


normalize_analysis_horizon = technical_analysis.normalize_analysis_horizon
_technical_analysis_summary = technical_analysis._technical_analysis_summary
_technical_price_levels = technical_analysis._technical_price_levels


@dataclass(frozen=True)
class TaiwanStockDependencies:
    market_service: Any
    stock_service: Any
    build_stock_technical_report: Callable[..., dict[str, Any]]
    build_taiwan_calendar_status: Callable[..., dict[str, Any]]
    build_taiwan_source_health: Callable[..., dict[str, Any]]
    build_us_overnight_impact_report: Callable[..., dict[str, Any]]
    get_broker_branch_trade_summary: Callable[..., dict[str, Any]]
    get_market_intraday_history: Callable[..., dict[str, Any]]
    get_taiwan_stock_quote_depth: Callable[..., dict[str, Any]]
    now: Callable[[], datetime]
    get_taiwan_disposition_status: Callable[..., dict[str, Any]] = (
        lambda stock_id, **_kwargs: {
            "stock_id": stock_id,
            "is_disposition": False,
            "is_active": False,
            "status": "none",
        }
    )


def _apply_disposition_quote_contract(
    quote: dict[str, Any],
    disposition: dict[str, Any],
    *,
    now: datetime | None = None,
) -> None:
    is_active = disposition.get("is_active") is True
    quote["trading_mode"] = (
        "disposition_batch_auction" if is_active else "continuous"
    )
    quote["analysis_basis"] = "effective_matches" if is_active else "time_bars"
    quote["batch_interval_minutes"] = (
        disposition.get("matching_interval_minutes") if is_active else None
    )
    quote["disposition_start_date"] = (
        _json_value(disposition.get("start_date")) if is_active else None
    )
    quote["disposition_end_date"] = (
        _json_value(disposition.get("end_date")) if is_active else None
    )
    quote["last_trade_price"] = (
        quote.get("last_price")
        if quote.get("last_price") is not None
        else quote.get("price")
    )
    quote["indicative_bid"] = quote.get("best_bid_price") if is_active else None
    quote["indicative_ask"] = quote.get("best_ask_price") if is_active else None
    quote["next_batch_time"] = None
    interval = disposition.get("matching_interval_minutes")
    quote_time = quote.get("quote_time")
    if is_active:
        quote["market_status"] = "disposition_batch_auction"
    if is_active and isinstance(interval, int) and interval > 0 and quote_time:
        try:
            parsed = datetime.fromisoformat(str(quote_time))
        except ValueError:
            parsed = None
        if parsed is not None:
            next_batch = parsed + timedelta(minutes=interval)
            if isinstance(now, datetime):
                current = now
                if current.tzinfo is None and parsed.tzinfo is not None:
                    current = current.replace(tzinfo=parsed.tzinfo)
                if current.tzinfo is not None and parsed.tzinfo is None:
                    current = current.replace(tzinfo=None)
                while next_batch <= current:
                    next_batch += timedelta(minutes=interval)
            quote["next_batch_time"] = next_batch.isoformat()


def _compact_intraday_bars(
    *,
    dependencies: TaiwanStockDependencies,
    db: Session,
    stock_id: str,
    include_intraday: bool,
    market_data_params: dict[str, Any] | None = None,
    calendar_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload_level = _payload_level(market_data_params)
    point_limit = _intraday_point_limit(market_data_params)
    if not include_intraday:
        return {
            "kind": "intraday_bars",
            "enabled": False,
            "intervals": list(COMPACT_INTRADAY_INTERVALS),
            "payload_level": payload_level,
            "bar_limit": point_limit,
            "series": {},
            "warnings": [],
        }

    series: dict[str, Any] = {}
    warnings: list[str] = []
    for interval in COMPACT_INTRADAY_INTERVALS:
        try:
            history = dependencies.get_market_intraday_history(
                db=db,
                stock_id=stock_id,
                interval=interval,
                range_value="1d",
                refresh=True,
            )
            compact_history = _compact_intraday_history(history, point_limit=point_limit)
            series[interval] = compact_history
            warnings.extend(str(item) for item in compact_history.get("warnings") or [])
        except Exception as exc:
            warnings.append(f"{interval} intraday bars unavailable: {exc}")
            series[interval] = {
                "interval": interval,
                "range": "1d",
                "point_count": 0,
                "returned_point_count": 0,
                "latest": None,
                "points": [],
            }

    one_minute_time = (series.get("1m") or {}).get("to_time")
    try:
        one_minute_at = datetime.fromisoformat(str(one_minute_time)) if one_minute_time else None
    except ValueError:
        one_minute_at = None
    for interval, item in series.items():
        if not isinstance(item, dict):
            continue
        try:
            interval_at = (
                datetime.fromisoformat(str(item.get("to_time")))
                if item.get("to_time")
                else None
            )
        except ValueError:
            interval_at = None
        delta_seconds = (
            max(int((one_minute_at - interval_at).total_seconds()), 0)
            if one_minute_at is not None and interval_at is not None
            else None
        )
        item["freshness_delta_seconds"] = delta_seconds
        snapshot_freshness = classify_market_snapshot(
            calendar_status=calendar_status or dependencies.build_taiwan_calendar_status(),
            quote_time=item.get("to_time"),
        )
        item["freshness_status"] = snapshot_freshness["status"]
        item["age_seconds"] = snapshot_freshness["age_seconds"]
        item["quote_semantics"] = snapshot_freshness["quote_semantics"]
        item["market_status"] = snapshot_freshness["market_status"]

    return {
        "kind": "intraday_bars",
        "enabled": True,
        "intervals": list(COMPACT_INTRADAY_INTERVALS),
        "range": "1d",
        "payload_level": payload_level,
        "bar_limit": point_limit,
        "series": series,
        "warnings": warnings,
    }





normalize_analysis_horizon = technical_analysis.normalize_analysis_horizon
_report_score = technical_analysis._report_score
TECHNICAL_FACTOR_ROW_KEYS = technical_analysis.TECHNICAL_FACTOR_ROW_KEYS
TECHNICAL_FACTOR_WEIGHTS_BY_HORIZON = technical_analysis.TECHNICAL_FACTOR_WEIGHTS_BY_HORIZON
_score_direction = technical_analysis._score_direction
_factor_score_from_row = technical_analysis._factor_score_from_row
_timeframe_factor_scores = technical_analysis._timeframe_factor_scores
_weighted_factor_score = technical_analysis._weighted_factor_score
_technical_factor_score_model = technical_analysis._technical_factor_score_model
_weighted_score = technical_analysis._weighted_score
_technical_analysis_summary = technical_analysis._technical_analysis_summary
_finite_number = technical_analysis._finite_number
_first_value = technical_analysis._first_value
_moving_average = technical_analysis._moving_average
_pct_change = technical_analysis._pct_change
_format_number = technical_analysis._format_number
_format_pct = technical_analysis._format_pct
_source_value = technical_analysis._source_value
_round_price = technical_analysis._round_price
_price_zone = technical_analysis._price_zone
_price_level = technical_analysis._price_level
_indicator_from_report = technical_analysis._indicator_from_report
_indicator_level_values = technical_analysis._indicator_level_values
_donchian_position = technical_analysis._donchian_position
_technical_price_levels = technical_analysis._technical_price_levels
_normalize_technical_points = technical_analysis._normalize_technical_points
_technical_report_from_points = technical_analysis._technical_report_from_points
_serialized_chart = technical_analysis._serialized_chart
_chart_from_points = technical_analysis._chart_from_points


def _stock_decision_evidence(
    *,
    latest_daily: Any,
    chart: dict[str, Any],
    latest_revenue: Any,
    latest_financial: Any,
    technical_reports: dict[str, Any],
    calendar_status: dict[str, Any] | None = None,
    missing: list[str],
    source_refs: list[dict[str, str]],
) -> dict[str, Any]:
    return evidence_builder.build_stock_decision_evidence(
        latest_daily=latest_daily,
        chart=chart,
        latest_revenue=latest_revenue,
        latest_financial=latest_financial,
        technical_reports=technical_reports,
        calendar_status=calendar_status,
        missing=missing,
        source_refs=source_refs,
    )


def read_stock_quote_context(
    db: Session,
    stock_id: str,
    *,
    market_data_params: dict[str, Any] | None = None,
    dependencies: TaiwanStockDependencies,
) -> dict[str, Any]:
    """Read only identity and the latest local quote evidence for a Taiwan stock."""

    normalized_stock_id = stock_id.strip()
    missing: list[str] = []
    warnings: list[str] = []
    try:
        stock = dependencies.stock_service.get_stock(db=db, stock_id=normalized_stock_id)
    except dependencies.stock_service.StockNotFoundError:
        stock = None
        missing.append("stock_master")

    latest_daily = dependencies.market_service.get_latest_stock_daily_price(
        db,
        normalized_stock_id,
    )
    if latest_daily is None:
        missing.append("market_daily_price")

    calendar_status = dependencies.build_taiwan_calendar_status()
    release_windows = (
        calendar_status.get("release_windows")
        if isinstance(calendar_status.get("release_windows"), dict)
        else {}
    )
    daily_window = (
        release_windows.get("market_daily_price")
        if isinstance(release_windows.get("market_daily_price"), dict)
        else {}
    )
    expected_trade_date = daily_window.get("expected_trade_date")
    latest_trade_date = _json_value(getattr(latest_daily, "trade_date", None))
    quote_is_stale = bool(
        latest_trade_date
        and expected_trade_date
        and str(latest_trade_date) < str(expected_trade_date)
    )
    if quote_is_stale:
        warnings.append(
            "Latest local daily quote is older than the expected Taiwan trading date."
        )

    params = market_data_params if isinstance(market_data_params, dict) else {}
    requested_domain_values = tuple(
        dict.fromkeys(
            str(value).strip().lower()
            for value in params.get("requested_domains") or []
            if str(value).strip()
        )
    )
    excluded_domain_values = tuple(
        dict.fromkeys(
            str(value).strip().lower()
            for value in params.get("excluded_domains") or []
            if str(value).strip()
        )
    )
    requested_domains = set(requested_domain_values)
    excluded_domains = set(excluded_domain_values)
    external_fetch_allowed = params.get("external_fetch_allowed") is True
    requested_provider_values = (
        params.get("providers") if isinstance(params.get("providers"), list) else []
    )
    requested_provider = str(
        params.get("provider")
        or (requested_provider_values[0] if requested_provider_values else "auto")
    ).strip().lower() or "auto"
    strict_provider = params.get("strict_provider") is True
    live_quote_requested = external_fetch_allowed and "quote" in requested_domains
    intraday_requested = external_fetch_allowed and "intraday" in requested_domains
    quote_depth: dict[str, Any] | None = None
    quote_error: str | None = None
    if live_quote_requested:
        try:
            quote_depth = dependencies.get_taiwan_stock_quote_depth(
                db=db,
                stock_id=normalized_stock_id,
                refresh=True,
            )
        except Exception as exc:
            quote_error = str(exc) or type(exc).__name__
            warnings.append(f"Taiwan quote depth unavailable: {quote_error}")
            missing.append("quote_depth")

    quote = _compact_quote_snapshot(
        latest_daily=latest_daily,
        quote_depth=quote_depth,
        quote_error=quote_error,
        session_phase=calendar_status.get("phase"),
    )
    quote_freshness = quote.get("freshness") if isinstance(quote.get("freshness"), dict) else {}
    if strict_provider and quote_freshness.get("source_error"):
        quote_freshness.update(
            {
                "status": "unavailable",
                "is_live": False,
                "is_stale": True,
            }
        )
        for key in ("latest_price", "price", "last_price"):
            quote[key] = None
        quote["depth_available"] = False
        quote["status"] = "unavailable"
    if quote_depth is None:
        quote_freshness.update(
            {
                "status": "unavailable"
                if live_quote_requested and strict_provider
                else "missing"
                if latest_daily is None
                else "stale"
                if quote_is_stale
                else "current",
                "is_stale": quote_is_stale,
                "expected_trade_date": expected_trade_date,
                "latest_trade_date": latest_trade_date,
                "source_error": quote_error,
            }
        )
        if live_quote_requested and strict_provider:
            for key in ("latest_price", "price", "last_price"):
                quote[key] = None
            quote["status"] = "unavailable"
            quote["depth_available"] = False
    quote["freshness"] = quote_freshness
    quote["market_status"] = market_status_from_session(calendar_status)
    quote["timezone"] = calendar_status.get("timezone") or "Asia/Taipei"
    session = calendar_status.get("session") if isinstance(calendar_status.get("session"), dict) else {}
    quote["session_start"] = session.get("open_time")
    quote["session_end"] = session.get("close_time")
    quote["holiday_name"] = calendar_status.get("holiday_name")
    disposition = dependencies.get_taiwan_disposition_status(
        normalized_stock_id,
        market=getattr(stock, "market", None),
        now=dependencies.now(),
    )
    _apply_disposition_quote_contract(quote, disposition, now=dependencies.now())

    allow_intraday_fallback = not strict_provider or requested_provider in {
        "auto",
        "yahoo",
        "yahoo_chart",
        "yahoo_finance_chart",
    }
    intraday_bars = _compact_intraday_bars(
        dependencies=dependencies,
        db=db,
        stock_id=normalized_stock_id,
        include_intraday=intraday_requested and allow_intraday_fallback,
        market_data_params=market_data_params,
        calendar_status=calendar_status,
    )
    if intraday_requested and not allow_intraday_fallback:
        intraday_bars["warnings"] = [
            f"strict_provider={requested_provider} does not permit Yahoo intraday fallback."
        ]
    intraday_series = (
        intraday_bars.get("series")
        if isinstance(intraday_bars.get("series"), dict)
        else {}
    )
    def canonical_provider(value: Any) -> str:
        provider = str(value or "").strip().lower()
        if provider.startswith("twse_mis"):
            return "twse_mis"
        if provider in {"yahoo", "yahoo_chart", "yahoo_finance_chart"}:
            return "yahoo_finance_chart"
        return provider

    effective_providers = list(
        dict.fromkeys(
            canonical_provider(value.get("provider") or value.get("source"))
            for value in intraday_series.values()
            if isinstance(value, dict)
            and str(value.get("provider") or value.get("source") or "").strip()
        )
    )
    if quote.get("provider") and not (
        strict_provider and quote.get("status") == "unavailable"
    ):
        effective_providers.insert(0, canonical_provider(quote["provider"]))
        effective_providers = list(dict.fromkeys(effective_providers))
    canonical_requested_provider = canonical_provider(requested_provider)
    provider_fallback_used = bool(
        canonical_requested_provider not in {"", "auto"}
        and any(provider != canonical_requested_provider for provider in effective_providers)
    )
    provider_contract = {
        "requested_provider": canonical_requested_provider,
        "effective_provider": effective_providers[0] if effective_providers else None,
        "effective_providers": effective_providers,
        "strict_provider": strict_provider,
        "provider_fallback_used": provider_fallback_used,
        "provider_fallback_reason": (
            "requested_provider_unavailable"
            if provider_fallback_used
            else "strict_provider_unavailable"
            if strict_provider and live_quote_requested and quote_depth is None
            else None
        ),
        "provider_attempts": [
            {
                "provider": canonical_requested_provider,
                "domain": "quote",
                "status": quote_freshness.get("status"),
                "error": quote_freshness.get("source_error") or quote_error,
            }
        ]
        if live_quote_requested
        else [],
    }
    attempted_domains = [
        domain
        for domain in ("quote", "intraday")
        if domain in requested_domains and external_fetch_allowed
    ]
    updated_domains: list[str] = []
    unchanged_domains: list[str] = []
    failed_domains: list[str] = []
    if "quote" in attempted_domains:
        quote_refresh_outcome = str(
            (quote_depth or {}).get("refresh_outcome") or ""
        )
        if quote_depth is None or quote_freshness.get("source_error"):
            failed_domains.append("quote")
        elif quote_refresh_outcome == "updated":
            updated_domains.append("quote")
        elif quote_refresh_outcome in {"unchanged", "cache_hit", "not_attempted"}:
            unchanged_domains.append("quote")
        elif quote_freshness.get("status") in {
            "live",
            "final_snapshot",
            "latest_completed_session",
        }:
            updated_domains.append("quote")
        else:
            unchanged_domains.append("quote")
    if "intraday" in attempted_domains:
        intraday_refresh_count = sum(
            int(item.get("refreshed_count") or 0)
            for item in intraday_series.values()
            if isinstance(item, dict)
        )
        intraday_has_points = any(
            int(item.get("returned_point_count") or 0) > 0
            for item in intraday_series.values()
            if isinstance(item, dict)
        )
        if intraday_refresh_count > 0:
            updated_domains.append("intraday")
        elif intraday_has_points:
            unchanged_domains.append("intraday")
        else:
            failed_domains.append("intraday")
    refresh_summary = {
        "requested_domains": list(requested_domain_values),
        "excluded_domains": list(excluded_domain_values),
        "attempted_domains": attempted_domains,
        "updated_domains": updated_domains,
        "unchanged_domains": unchanged_domains,
        "failed_domains": failed_domains,
        "attempted_dataset_count": len(attempted_domains),
        "updated_dataset_count": len(updated_domains),
        "unchanged_dataset_count": len(unchanged_domains),
        "failed_dataset_count": len(failed_domains),
    }
    if intraday_requested:
        provider_contract["provider_attempts"].append(
            {
                "provider": (
                    "yahoo_finance_chart"
                    if allow_intraday_fallback
                    else canonical_requested_provider
                ),
                "domain": "intraday",
                "status": (
                    "updated"
                    if "intraday" in updated_domains
                    else "unchanged"
                    if "intraday" in unchanged_domains
                    else "unavailable"
                ),
                "error": (
                    None
                    if "intraday" not in failed_domains
                    else "; ".join(str(item) for item in intraday_bars.get("warnings") or [])
                    or "intraday provider unavailable"
                ),
            }
        )

    level = _payload_level(market_data_params)
    target = {
        "type": "tw_stock",
        "id": normalized_stock_id,
        "label": getattr(stock, "stock_name", None),
        "market": getattr(stock, "market", None) or "TW",
    }
    quote_slot_status = (
        "missing"
        if quote.get("last_price") is None and quote.get("price") is None
        else "partial"
        if quote_freshness.get("status")
        in {"cached", "stale", "delayed", "unavailable", "source_unavailable"}
        else "ready"
    )
    slots = {
        "identity": _slot_envelope(
            status="ready" if stock is not None else "missing",
            capability="target_identity",
            payload_ref="target",
            priority="core",
            as_of=latest_trade_date,
            missing=["stock_master"] if stock is None else [],
        ),
        "quote": _slot_envelope(
            status=quote_slot_status,
            capability="quote_snapshot",
            payload_ref="quote",
            payload_level=level,
            priority="core",
            as_of=quote.get("quote_time") or latest_trade_date,
            missing=["quote"] if quote_slot_status == "missing" else [],
            warnings=warnings,
            freshness_status=str(quote_freshness.get("status") or "missing"),
        ),
    }
    for key, capability in (
        ("intraday", "live_intraday_bars"),
        ("daily_chart", "daily_ohlc_chart"),
        ("technical", "technical_decision_evidence"),
        ("chips_flows", "tw_chips_and_flows"),
        ("fundamentals", "tw_fundamentals"),
        ("broker_branch", "broker_branch"),
        ("cross_market", "cross_market_context"),
    ):
        slots[key] = _slot_envelope(
            status="not_requested",
            capability=capability,
            payload_level=level,
        )
    if intraday_bars.get("enabled"):
        slots["intraday"] = _slot_envelope(
            status="ready"
            if any(
                isinstance(value, dict) and value.get("returned_point_count")
                for value in intraday_series.values()
            )
            else "missing",
            capability="live_intraday_bars",
            payload_ref="intraday_bars",
            payload_level=level,
            priority="core",
            warnings=intraday_bars.get("warnings") or [],
        )

    source_refs = (
        [{"type": "table", "name": "market_daily_price"}]
        if latest_daily is not None
        else []
    )
    if quote_depth is not None:
        _append_source_ref_once(
            source_refs,
            {"type": "external_or_cache", "name": "taiwan_quote_depth"},
        )
    if intraday_bars.get("enabled"):
        _append_source_ref_once(
            source_refs,
            {"type": "external_or_cache", "name": "market_intraday_bar"},
        )
    intraday_domain_status = (
        str((intraday_series.get("1m") or {}).get("freshness_status") or "unavailable")
        if intraday_requested
        else "not_requested"
    )
    compact_status = (
        "missing"
        if latest_daily is None and quote_freshness.get("status") in {None, "missing", "unavailable"}
        else "partial"
        if quote_freshness.get("status") in {"cached", "stale", "unavailable", "source_unavailable"}
        or intraday_domain_status in {"delayed", "stale", "missing", "unavailable"}
        else "ready"
    )
    compact = {
        "kind": "tw_stock_quote_compact_evidence",
        "version": "market_compact_evidence.v1",
        "payload_level": level,
        "status": compact_status,
        "target": target,
        "quote": quote,
        "intraday_bars": intraday_bars,
        "provider_contract": provider_contract,
        "refresh_summary": refresh_summary,
        "freshness_by_domain": {
            "quote": quote_freshness.get("status"),
            "intraday": intraday_domain_status,
        },
        "slots": slots,
        "missing": missing,
        "warnings": warnings,
        "source_refs": source_refs,
    }
    quote_context_as_of = _latest_date_string(
        [
            latest_trade_date,
            quote.get("quote_time"),
            (intraday_series.get("1m") or {}).get("to_time"),
        ]
    )
    envelope = {
        "kind": "stock_quote_context",
        "generated_at": dependencies.now(),
        "as_of": quote_context_as_of,
        "scope": {"stock_id": normalized_stock_id},
        "data": {
            "stock": _stock_dict(stock),
            "quote": quote,
            "intraday_bars": intraday_bars,
            "provider_contract": provider_contract,
            "refresh_summary": refresh_summary,
            "compact": compact,
        },
        "missing": missing,
        "warnings": warnings,
        "source_refs": source_refs,
    }
    return _with_evidence_passport(
        envelope,
        freshness={
            "status": quote_freshness.get("status"),
            "is_current": compact_status == "ready",
            "expected_trade_date": expected_trade_date,
            "latest_trade_date": latest_trade_date,
            "missing": missing,
            "warnings": warnings,
        },
    )


def read_stock_broker_branch_context(
    db: Session,
    stock_id: str,
    *,
    branch_days: int = 5,
    market_data_params: dict[str, Any] | None = None,
    dependencies: TaiwanStockDependencies,
) -> dict[str, Any]:
    """Read only identity and broker-branch evidence for a Taiwan stock."""

    normalized_stock_id = stock_id.strip()
    missing: list[str] = []
    warnings: list[str] = []
    try:
        stock = dependencies.stock_service.get_stock(db=db, stock_id=normalized_stock_id)
    except dependencies.stock_service.StockNotFoundError:
        stock = None
        missing.append("stock_master")

    branch_summary = dependencies.get_broker_branch_trade_summary(
        db=db,
        stock_id=normalized_stock_id,
        days=max(branch_days, 1),
        ensure_daily=False,
    )
    has_rows = bool(branch_summary.get("buy_top") or branch_summary.get("sell_top"))
    is_partial = bool(branch_summary.get("is_partial"))
    if not has_rows:
        missing.append("broker_branch_trade_daily")
    if is_partial:
        warnings.append(
            "Broker branch data is partial for the requested window: "
            f"{branch_summary.get('available_days')} / "
            f"{branch_summary.get('requested_days')} days."
        )

    calendar_status = dependencies.build_taiwan_calendar_status()
    release_windows = (
        calendar_status.get("release_windows")
        if isinstance(calendar_status.get("release_windows"), dict)
        else {}
    )
    branch_window = (
        release_windows.get("broker_branch_trade_daily")
        if isinstance(release_windows.get("broker_branch_trade_daily"), dict)
        else {}
    )
    latest_trade_date = _json_value(branch_summary.get("trade_date"))
    expected_trade_date = branch_window.get("expected_trade_date")
    is_stale = bool(
        latest_trade_date
        and expected_trade_date
        and str(latest_trade_date) < str(expected_trade_date)
    )
    if is_stale:
        warnings.append(
            "Latest broker branch evidence is older than the expected Taiwan trading date."
        )

    level = _payload_level(market_data_params)
    target = {
        "type": "tw_stock",
        "id": normalized_stock_id,
        "label": getattr(stock, "stock_name", None),
        "market": getattr(stock, "market", None) or "TW",
    }
    branch_payload = {
        **branch_summary,
        "trade_date": latest_trade_date,
        "trade_dates": [
            _json_value(value) for value in branch_summary.get("trade_dates", [])
        ],
        "buy_top": [
            _broker_branch_row(row) for row in branch_summary.get("buy_top", [])
        ],
        "sell_top": [
            _broker_branch_row(row) for row in branch_summary.get("sell_top", [])
        ],
    }
    branch_freshness = (
        "missing" if not has_rows else "stale" if is_stale else "current"
    )
    branch_slot_status = (
        "missing" if not has_rows else "partial" if is_partial else "ready"
    )
    slots = {
        "identity": _slot_envelope(
            status="ready" if stock is not None else "missing",
            capability="target_identity",
            payload_ref="target",
            priority="core",
            as_of=latest_trade_date,
            missing=["stock_master"] if stock is None else [],
        ),
        "broker_branch": _slot_envelope(
            status=branch_slot_status,
            capability="broker_branch",
            payload_ref="chips.broker_branch",
            payload_level=level,
            priority="core",
            as_of=latest_trade_date,
            missing=["broker_branch_trade_daily"] if not has_rows else [],
            warnings=warnings,
            freshness_status=branch_freshness,
        ),
    }
    for key, capability in (
        ("quote", "quote_snapshot"),
        ("intraday", "live_intraday_bars"),
        ("daily_chart", "daily_ohlc_chart"),
        ("technical", "technical_decision_evidence"),
        ("chips_flows", "tw_chips_and_flows"),
        ("fundamentals", "tw_fundamentals"),
        ("cross_market", "cross_market_context"),
    ):
        slots[key] = _slot_envelope(
            status="not_requested",
            capability=capability,
            payload_level=level,
        )

    source_refs = []
    if stock is not None:
        source_refs.append({"type": "table", "name": "stock_master"})
    if has_rows:
        source_refs.append({"type": "table", "name": "broker_branch_trade_daily"})
    compact = {
        "kind": "tw_stock_broker_branch_compact_evidence",
        "version": "market_compact_evidence.v1",
        "payload_level": level,
        "status": (
            "missing"
            if not has_rows
            else "partial"
            if is_partial or is_stale
            else "ready"
        ),
        "target": target,
        "chips": {"broker_branch": branch_payload},
        "freshness_by_domain": {"broker_branch": branch_freshness},
        "slots": slots,
        "missing": missing,
        "warnings": warnings,
        "source_refs": source_refs,
    }
    envelope = {
        "kind": "stock_broker_branch_context",
        "generated_at": dependencies.now(),
        "as_of": latest_trade_date,
        "scope": {"stock_id": normalized_stock_id},
        "data": {
            "stock": _stock_dict(stock),
            "broker_branch": branch_payload,
            "compact": compact,
        },
        "missing": missing,
        "warnings": warnings,
        "source_refs": source_refs,
    }
    return _with_evidence_passport(
        envelope,
        freshness={
            "status": branch_freshness,
            "is_current": has_rows and not is_stale,
            "expected_trade_date": expected_trade_date,
            "latest_trade_date": latest_trade_date,
            "missing": missing,
            "warnings": warnings,
        },
    )


def read_stock_context(
    db: Session,
    stock_id: str,
    *,
    branch_days: int = 5,
    bars: int = 120,
    revenue_months: int = 12,
    financial_quarters: int = 8,
    include_intraday: bool = False,
    analysis_horizon: str = "swing",
    market_data_params: dict[str, Any] | None = None,
    dependencies: TaiwanStockDependencies,
) -> dict[str, Any]:
    normalized_stock_id = stock_id.strip()
    missing: list[str] = []
    warnings: list[str] = []

    try:
        stock = dependencies.stock_service.get_stock(db=db, stock_id=normalized_stock_id)
    except dependencies.stock_service.StockNotFoundError:
        stock = None
        missing.append("stock_master")

    latest_daily = dependencies.market_service.get_latest_stock_daily_price(db, normalized_stock_id)
    latest_institutional = dependencies.market_service.get_latest_stock_institutional_trade(db, normalized_stock_id)
    latest_margin = dependencies.market_service.get_latest_stock_margin_trade(db, normalized_stock_id)
    latest_revenue = dependencies.market_service.get_latest_stock_monthly_revenue(db, normalized_stock_id)
    latest_financial = dependencies.market_service.get_latest_stock_financial_metric(db, normalized_stock_id)
    shareholding = dependencies.market_service.list_latest_stock_shareholding_distribution(db, normalized_stock_id)
    revenue_history = dependencies.market_service.list_stock_monthly_revenue_history(
        db=db,
        stock_id=normalized_stock_id,
        limit=max(revenue_months, 1),
    )
    financial_history = dependencies.market_service.list_stock_financial_metric_history(
        db=db,
        stock_id=normalized_stock_id,
        limit=max(financial_quarters, 1),
    )
    chart = dependencies.market_service.list_stock_ohlc_chart_data(
        db=db,
        stock_id=normalized_stock_id,
        timeframe="daily",
        bars=max(bars, 1),
        ensure_history=False,
    )
    branch_summary = dependencies.get_broker_branch_trade_summary(
        db=db,
        stock_id=normalized_stock_id,
        days=max(branch_days, 1),
        ensure_daily=False,
    )
    normalized_horizon = normalize_analysis_horizon(analysis_horizon)
    technical_reports: dict[str, Any] = {}

    for timeframe in ("daily", "weekly", "monthly"):
        try:
            technical_reports[timeframe] = dependencies.build_stock_technical_report(
                db=db,
                stock_id=normalized_stock_id,
                timeframe=timeframe,
                include_intraday=False,
            )
        except Exception as exc:
            warnings.append(f"{timeframe.title()} technical report unavailable: {exc}")
            missing.append(f"technical_report.{timeframe}")

    if include_intraday or normalized_horizon == "intraday":
        try:
            technical_reports["today"] = dependencies.build_stock_technical_report(
                db=db,
                stock_id=normalized_stock_id,
                timeframe="today",
                include_intraday=include_intraday,
            )
        except Exception as exc:
            warnings.append(f"Today technical report unavailable: {exc}")
            missing.append("technical_report.today")

    if normalized_horizon == "intraday" and not include_intraday:
        warnings.append(
            "Intraday analysis horizon was requested without live intraday access; daily evidence is used as fallback context."
        )

    technical_analysis = _technical_analysis_summary(
        technical_reports=technical_reports,
        requested_horizon=analysis_horizon,
    )
    technical_levels = _technical_price_levels(
        technical_reports=technical_reports,
        latest_daily=latest_daily,
    )
    overnight_impact: dict[str, Any] | None = None

    if stock is not None:
        try:
            overnight_impact = dependencies.build_us_overnight_impact_report(
                db=db,
                stock_id=normalized_stock_id,
            )
            for warning in overnight_impact.get("warnings") or []:
                warnings.append(f"US overnight impact warning: {warning}")
            if overnight_impact.get("missing"):
                warnings.append(
                    "US overnight impact is partial: "
                    + ", ".join(str(value) for value in overnight_impact.get("missing", [])[:5])
                )
        except Exception as exc:
            warnings.append(f"US overnight impact unavailable: {exc}")
            missing.append("us_overnight_tw_impact")

    if branch_summary.get("is_partial"):
        warnings.append(
            "Broker branch data is partial for the requested window: "
            f"{branch_summary.get('available_days')} / {branch_summary.get('requested_days')} days."
        )

    _add_missing(missing, "market_daily_price", latest_daily)
    _add_missing(missing, "institutional_trade_daily", latest_institutional)
    _add_missing(missing, "margin_trading_daily", latest_margin)
    _add_missing(missing, "shareholding_distribution_weekly", shareholding)
    _add_missing(missing, "monthly_revenue", latest_revenue)
    _add_missing(missing, "financial_metric_quarterly", latest_financial)
    _add_missing(missing, "broker_branch_trade_daily", branch_summary.get("buy_top") or branch_summary.get("sell_top"))
    _add_missing(missing, "us_overnight_tw_impact", overnight_impact)

    as_of = _latest_date_string(
        [
            getattr(latest_daily, "trade_date", None),
            getattr(latest_institutional, "trade_date", None),
            getattr(latest_margin, "trade_date", None),
            branch_summary.get("trade_date"),
            getattr(latest_revenue, "period", None),
            getattr(latest_financial, "released_at", None)
            or getattr(latest_financial, "report_date", None),
            overnight_impact.get("as_of") if isinstance(overnight_impact, dict) else None,
        ]
    )

    source_refs = [
        {"type": "table", "name": "stock_master"},
        {"type": "table", "name": "market_daily_price"},
        {"type": "table", "name": "institutional_trade_daily"},
        {"type": "table", "name": "margin_trading_daily"},
        {"type": "table", "name": "shareholding_distribution_weekly"},
        {"type": "table", "name": "broker_branch_trade_daily"},
        {"type": "table", "name": "monthly_revenue"},
        {"type": "table", "name": "financial_metric_quarterly"},
        {"type": "derived", "name": "app.market.technical_report"},
        {"type": "table", "name": "us_daily_price"},
        {"type": "table", "name": "us_watchlist_group"},
        {"type": "table", "name": "us_watchlist_item"},
        {"type": "derived", "name": "app.market.calendar_status"},
        {"type": "derived", "name": "app.market.overnight_impact"},
    ]
    market_calendar_status = dependencies.build_taiwan_calendar_status()
    source_health = dependencies.build_taiwan_source_health(
        db=db,
        stock_id=normalized_stock_id,
    )
    source_refs.append({"type": "derived", "name": "app.market.source_health"})

    quote_depth: dict[str, Any] | None = None
    quote_error: str | None = None
    if include_intraday:
        try:
            quote_depth = dependencies.get_taiwan_stock_quote_depth(
                db=db,
                stock_id=normalized_stock_id,
                refresh=True,
            )
            _append_source_ref_once(source_refs, {"type": "external_or_cache", "name": "taiwan_quote_depth"})
        except Exception as exc:
            quote_error = str(exc) or exc.__class__.__name__
            warnings.append(f"Taiwan quote depth unavailable: {quote_error}")
            missing.append("quote_depth")

    quote = _compact_quote_snapshot(
        latest_daily=latest_daily,
        quote_depth=quote_depth,
        quote_error=quote_error,
        session_phase=market_calendar_status.get("phase"),
    )
    quote["market_status"] = market_status_from_session(market_calendar_status)
    quote["timezone"] = market_calendar_status.get("timezone") or "Asia/Taipei"
    market_session = (
        market_calendar_status.get("session")
        if isinstance(market_calendar_status.get("session"), dict)
        else {}
    )
    quote["session_start"] = market_session.get("open_time")
    quote["session_end"] = market_session.get("close_time")
    quote["holiday_name"] = market_calendar_status.get("holiday_name")
    disposition = dependencies.get_taiwan_disposition_status(
        normalized_stock_id,
        market=getattr(stock, "market", None),
        now=dependencies.now(),
    )
    _apply_disposition_quote_contract(quote, disposition, now=dependencies.now())
    intraday_bars = _compact_intraday_bars(
        dependencies=dependencies,
        db=db,
        stock_id=normalized_stock_id,
        include_intraday=include_intraday,
        market_data_params=market_data_params,
        calendar_status=market_calendar_status,
    )
    if intraday_bars.get("enabled"):
        _append_source_ref_once(source_refs, {"type": "external_or_cache", "name": "market_intraday_bar"})
        for warning in intraday_bars.get("warnings") or []:
            warnings.append(str(warning))
        series = intraday_bars.get("series") if isinstance(intraday_bars.get("series"), dict) else {}
        if not any(isinstance(item, dict) and item.get("returned_point_count") for item in series.values()):
            missing.append("intraday_bars")
    intraday_latest_times = [
        item.get("to_time")
        for item in (intraday_bars.get("series") or {}).values()
        if isinstance(item, dict) and item.get("to_time")
    ]
    compact_as_of = _latest_date_string(
        [
            as_of,
            quote.get("quote_time"),
            quote.get("trade_date"),
            *intraday_latest_times,
        ]
    )

    decision_evidence = _stock_decision_evidence(
        latest_daily=latest_daily,
        chart=chart,
        latest_revenue=latest_revenue,
        latest_financial=latest_financial,
        technical_reports=technical_reports,
        calendar_status=market_calendar_status,
        missing=missing,
        source_refs=source_refs,
    )

    envelope = {
        "kind": "stock_context",
        "generated_at": dependencies.now(),
        "as_of": as_of,
        "scope": {"stock_id": normalized_stock_id},
        "data": {
            "stock": _stock_dict(stock),
            "latest_daily": _row_dict(
                latest_daily,
                (
                    "trade_date",
                    "stock_id",
                    "stock_name",
                    "trade_volume",
                    "trade_value",
                    "open_price",
                    "high_price",
                    "low_price",
                    "close_price",
                    "price_change",
                    "transaction_count",
                ),
            ),
            "chart": {
                **chart,
                "from_date": _json_value(chart.get("from_date")),
                "to_date": _json_value(chart.get("to_date")),
                "points": [
                    {key: _json_value(value) for key, value in point.items()}
                    for point in chart.get("points", [])
                ],
            },
            "technical_reports": technical_reports,
            "analysis": technical_analysis,
            "technical_levels": technical_levels,
            "compact": _build_stock_compact_evidence(
                stock=stock,
                stock_id=normalized_stock_id,
                as_of=compact_as_of or as_of,
                latest_daily=latest_daily,
                latest_institutional=latest_institutional,
                latest_margin=latest_margin,
                shareholding=shareholding,
                branch_summary=branch_summary,
                latest_revenue=latest_revenue,
                revenue_history=revenue_history,
                latest_financial=latest_financial,
                financial_history=financial_history,
                technical_reports=technical_reports,
                technical_analysis=technical_analysis,
                technical_levels=technical_levels,
                quote=quote,
                intraday_bars=intraday_bars,
                source_health=source_health,
                overnight_impact=overnight_impact,
                missing=missing,
                warnings=warnings,
                source_refs=source_refs,
            ),
            "market_calendar_status": market_calendar_status,
            "source_health": source_health,
            "decision_evidence": decision_evidence,
            "overnight_impact": overnight_impact,
            "latest_institutional": _row_dict(
                latest_institutional,
                (
                    "trade_date",
                    "foreign_investor_net",
                    "investment_trust_net",
                    "dealer_net",
                    "total_institutional_net",
                ),
            ),
            "latest_margin": _row_dict(
                latest_margin,
                (
                    "trade_date",
                    "margin_buy",
                    "margin_sell",
                    "margin_today_balance",
                    "short_sale",
                    "short_covering",
                    "short_today_balance",
                ),
            ),
            "latest_shareholding": [
                _row_dict(
                    row,
                    (
                        "data_date",
                        "holding_level",
                        "holder_count",
                        "share_count",
                        "share_ratio",
                    ),
                )
                for row in shareholding
            ],
            "broker_branch": {
                **branch_summary,
                "trade_date": _json_value(branch_summary.get("trade_date")),
                "trade_dates": [_json_value(value) for value in branch_summary.get("trade_dates", [])],
                "buy_top": [_broker_branch_row(row) for row in branch_summary.get("buy_top", [])],
                "sell_top": [_broker_branch_row(row) for row in branch_summary.get("sell_top", [])],
            },
            "latest_revenue": _row_dict(
                latest_revenue,
                (
                    "period",
                    "monthly_revenue",
                    "month_over_month_pct",
                    "year_over_year_pct",
                    "cumulative_revenue",
                    "cumulative_year_over_year_pct",
                ),
            ),
            "revenue_history": [
                _row_dict(
                    row,
                    (
                        "period",
                        "monthly_revenue",
                        "month_over_month_pct",
                        "year_over_year_pct",
                        "cumulative_revenue",
                        "cumulative_year_over_year_pct",
                    ),
                )
                for row in revenue_history
            ],
            "latest_financial": _row_dict(
                latest_financial,
                (
                    "period",
                    "report_date",
                    "released_at",
                    "filed_at",
                    "revenue",
                    "gross_profit",
                    "operating_income",
                    "net_income",
                    "eps",
                    "book_value_per_share",
                    "roe",
                    "roa",
                ),
            ),
            "financial_history": [
                _row_dict(
                    row,
                    (
                        "period",
                        "report_date",
                        "released_at",
                        "filed_at",
                        "revenue",
                        "gross_profit",
                        "operating_income",
                        "net_income",
                        "eps",
                        "book_value_per_share",
                        "roe",
                        "roa",
                    ),
                )
                for row in financial_history
            ],
        },
        "missing": missing,
        "warnings": warnings,
        "source_refs": source_refs,
    }
    return _with_evidence_passport(
        envelope,
        analysis=technical_analysis,
        confidence=str(technical_analysis.get("selected_confidence") or ""),
    )
