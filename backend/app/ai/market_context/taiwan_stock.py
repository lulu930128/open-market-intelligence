from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.ai import evidence_builder, technical_analysis
from app.ai.market_context import taiwan_events
from app.ai.market_context.common import append_source_ref_once as _append_source_ref_once
from app.ai.market_context.taiwan_projection import (
    _add_missing,
    _broker_branch_metadata,
    _broker_branch_row,
    _build_stock_compact_evidence,
    _compact_intraday_history,
    _compact_quote_snapshot,
    _quote_component_freshness_rows,
    _quote_component_slots,
    _quote_components,
    _json_value,
    _latest_date_string,
    _row_dict,
    _stock_dict,
    _with_evidence_passport,
)
from app.ai.market_context.taiwan_bar_projection import project_taiwan_bar_series
from app.ai.market_payload_contract import (
    intraday_point_limit as _intraday_point_limit,
    payload_level as _payload_level,
    requested_intraday_interval as _requested_intraday_interval,
    slot_envelope as _slot_envelope,
)
from app.ai.taiwan_intraday_contract import (
    classify_taiwan_session_date_relation,
    resolve_effective_source_health,
    resolve_taiwan_current_price,
)
from app.market.live_snapshot import market_status_from_session
from app.market.financial_contract import (
    FINANCIAL_CONTRACT_VERSION,
    build_database_financial_contract,
)
from app.ai.market_date_request import parse_market_trade_date
from app.stocks.instruments import is_taiwan_etf
from app.market.tw_company_profile import (
    TaiwanCompanyProfileRead,
    project_taiwan_company_profile,
)
from app.market.tw_instrument_trading_policy import (
    TaiwanInstrumentTradingMode,
    resolve_taiwan_instrument_trading_policy,
)
from app.market.taiwan_quote_evidence import TW_QUOTE_EVIDENCE_CAPABILITIES


normalize_analysis_horizon = technical_analysis.normalize_analysis_horizon


def _requested_quote_evidence_capabilities(
    params: dict[str, Any],
) -> tuple[str, ...] | None:
    requested = {
        str(value or "").strip()
        for value in params.get("requested_capabilities") or []
    }
    if "quote.last_trade" in requested:
        requested.add("quote.snapshot")
    selected = tuple(
        capability
        for capability in TW_QUOTE_EVIDENCE_CAPABILITIES
        if capability in requested
    )
    return selected or None
_technical_analysis_summary = technical_analysis._technical_analysis_summary
_evaluate_technical_evidence_sufficiency = (
    technical_analysis.evaluate_technical_evidence_sufficiency
)
_apply_technical_sufficiency_gate = (
    technical_analysis.apply_technical_sufficiency_gate
)
_technical_price_levels = technical_analysis._technical_price_levels
TAIPEI_TZ = timezone(timedelta(hours=8))


def _read_stock_fundamental_inputs(
    *,
    db: Session,
    stock_id: str,
    revenue_months: int,
    financial_quarters: int,
    applicable: bool,
    market_service: Any,
) -> dict[str, Any]:
    if not applicable:
        return {
            "latest_revenue": None,
            "latest_financial": None,
            "revenue_history": [],
            "financial_history": [],
        }
    return {
        "latest_revenue": market_service.get_latest_stock_monthly_revenue(
            db,
            stock_id,
        ),
        "latest_financial": market_service.get_latest_stock_financial_metric(
            db,
            stock_id,
        ),
        "revenue_history": market_service.list_stock_monthly_revenue_history(
            db=db,
            stock_id=stock_id,
            limit=max(revenue_months, 1),
        ),
        "financial_history": market_service.list_stock_financial_metric_history(
            db=db,
            stock_id=stock_id,
            limit=max(financial_quarters, 1),
        ),
    }


@dataclass(frozen=True)
class TaiwanStockDependencies:
    market_service: Any
    stock_service: Any
    build_stock_technical_report: Callable[..., dict[str, Any]]
    build_taiwan_calendar_status: Callable[..., dict[str, Any]]
    build_taiwan_source_health: Callable[..., dict[str, Any]]
    build_us_overnight_impact_report: Callable[..., dict[str, Any]]
    get_broker_branch_trade_summary: Callable[..., dict[str, Any]]
    read_taiwan_bars: Callable[..., Any]
    read_taiwan_quote_evidence: Callable[..., dict[str, Any]]
    acquire_taiwan_quote_evidence: Callable[..., dict[str, Any]]
    read_taiwan_latest_daily_evidence: Callable[..., Any]
    now: Callable[[], datetime]
    read_taiwan_company_profile: Callable[..., TaiwanCompanyProfileRead | None] = (
        lambda _db, _stock_id: None
    )
    get_taiwan_disposition_status: Callable[..., dict[str, Any]] = (
        lambda stock_id, **_kwargs: {
            "stock_id": stock_id,
            "is_disposition": False,
            "is_active": False,
            "status": "none",
        }
    )
    get_taiwan_stock_event_summary: Callable[..., dict[str, Any]] = (
        lambda stock_id, **_kwargs: {
            "stock_id": stock_id,
            "cache_status": "missing",
            "result_count": 0,
            "results": [],
            "warning": "Taiwan corporate-event reader is unavailable.",
        }
    )
    get_taiwan_stock_event_history: Callable[..., dict[str, Any]] = (
        lambda stock_id, **_kwargs: {
            "stock_id": stock_id,
            "cache_status": "missing",
            "total_count": 0,
            "result_count": 0,
            "results": [],
            "warning": "Taiwan corporate-event history reader is unavailable.",
        }
    )
    build_tw_stock_technical_evidence: Callable[..., dict[str, Any]] | None = None


def _company_profile_payload(
    stock: Any,
    profile: TaiwanCompanyProfileRead | Any | None,
) -> dict[str, Any]:
    return project_taiwan_company_profile(stock, profile)


def _latest_daily_value(evidence: Any) -> Any:
    """Unwrap the market-owned evidence result; accept test compatibility rows."""

    return getattr(evidence, "daily", evidence)


def _apply_taiwan_official_daily_release_truth(
    *,
    latest_daily: Any,
    calendar_status: dict[str, Any],
    missing: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    """Project release-window truth without treating D-1 as today's official EOD."""

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
    expected_trade_date = _json_value(daily_window.get("expected_trade_date"))
    latest_trade_date = _json_value(getattr(latest_daily, "trade_date", None))
    release_status = str(daily_window.get("status") or "unknown")
    is_released = bool(
        daily_window.get("is_released") is True or release_status == "released"
    )
    latest_is_older = bool(
        latest_trade_date
        and expected_trade_date
        and str(latest_trade_date) < str(expected_trade_date)
    )
    unavailable_after_release = bool(
        is_released
        and expected_trade_date
        and (latest_trade_date is None or latest_is_older)
    )
    if unavailable_after_release:
        if "market_daily_price" not in missing:
            missing.append("market_daily_price")
        warning = (
            "TW_OFFICIAL_DAILY_RELEASED_BUT_UNAVAILABLE: Taiwan official daily "
            f"EOD is released for {expected_trade_date}, but canonical "
            f"market_daily_price latest trade date is {latest_trade_date or 'missing'}."
        )
        if warning not in warnings:
            warnings.append(warning)
    elif latest_is_older:
        warning = (
            "Latest local daily quote is older than the expected Taiwan trading date."
        )
        if warning not in warnings:
            warnings.append(warning)
    return {
        "status": (
            "released_but_unavailable"
            if unavailable_after_release
            else release_status
        ),
        "is_released": is_released,
        "expected_trade_date": expected_trade_date,
        "latest_trade_date": latest_trade_date,
        "unavailable_after_release": unavailable_after_release,
    }


def _apply_disposition_quote_contract(
    quote: dict[str, Any],
    disposition: dict[str, Any],
    *,
    now: datetime | None = None,
) -> None:
    policy = resolve_taiwan_instrument_trading_policy(disposition)
    is_active = (
        policy.trading_mode
        is TaiwanInstrumentTradingMode.DISPOSITION_BATCH_AUCTION
    )
    quote.update(policy.projection())
    quote["batch_interval_minutes"] = (
        disposition.get("matching_interval_minutes") if is_active else None
    )
    quote["disposition_start_date"] = (
        _json_value(disposition.get("start_date")) if is_active else None
    )
    quote["disposition_end_date"] = (
        _json_value(disposition.get("end_date")) if is_active else None
    )
    if quote.get("last_trade_available") is True:
        quote["last_trade_price"] = (
            quote.get("last_trade_price")
            if quote.get("last_trade_price") is not None
            else quote.get("last_price")
            if quote.get("last_price") is not None
            else quote.get("price")
        )
    else:
        quote["last_trade_price"] = None
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
    requested_interval = _requested_intraday_interval(market_data_params)
    params = (
        market_data_params
        if isinstance(market_data_params, dict)
        else {}
    )
    cached_fallback_allowed = params.get("fallback_to_cached") is not False
    requested_trade_date = parse_market_trade_date(params.get("trade_date"))
    current_session_scope = requested_trade_date is None
    # The Taiwan Bar owner reads resolved canonical cache only. AI never
    # triggers acquisition or chooses a provider.
    refresh_allowed = False
    intervals = (requested_interval or "1m",)
    if not include_intraday:
        return {
            "kind": "intraday_bars",
            "enabled": False,
            "intervals": list(intervals),
            "requested_interval": requested_interval,
            "payload_level": payload_level,
            "bar_limit": point_limit,
            "provider_refresh_allowed": refresh_allowed,
            "cached_fallback_allowed": cached_fallback_allowed,
            "read_mode": "disabled",
            "series": {},
            "warnings": [],
        }

    series: dict[str, Any] = {}
    warnings: list[str] = []
    for interval in intervals:
        try:
            bar_series = dependencies.read_taiwan_bars(
                db=db,
                instrument_id=stock_id,
                interval=interval,
                limit=point_limit,
                include_partial=True,
                **(
                    {
                        "session_scope": "current_session",
                        "requested_at": _contract_datetime(
                            calendar_status.get("checked_at")
                            if isinstance(calendar_status, dict)
                            else None
                        ),
                    }
                    if current_session_scope
                    else {}
                ),
            )
            history = project_taiwan_bar_series(
                bar_series,
                session_scope=("current_session" if current_session_scope else None),
            )
            compact_history = _compact_intraday_history(history, point_limit=point_limit)
            series[interval] = compact_history
            warnings.extend(str(item) for item in compact_history.get("warnings") or [])
        except Exception as exc:
            warnings.append(f"{interval} intraday bars unavailable: {exc}")
            series[interval] = {
                "interval": interval,
                "requested_interval": interval,
                "source_interval": None,
                "effective_interval": None,
                "range": "1d",
                "point_count": 0,
                "returned_point_count": 0,
                "latest": None,
                "points": [],
            }

    return {
        "kind": "intraday_bars",
        "enabled": True,
        "provider_refresh_allowed": refresh_allowed,
        "cached_fallback_allowed": cached_fallback_allowed,
        "read_mode": "taiwan_bar_service_cache_only",
        "intervals": list(intervals),
        "requested_interval": requested_interval,
        "range": "1d",
        "payload_level": payload_level,
        "bar_limit": point_limit,
        "session_scope": "current_session" if current_session_scope else "history",
        "expected_trade_date": (
            (series.get(intervals[0]) or {}).get("expected_trade_date")
            if current_session_scope
            else None
        ),
        "trade_date": (
            (series.get(intervals[0]) or {}).get("trade_date")
            if len(intervals) == 1
            else None
        ),
        "series": series,
        "warnings": warnings,
    }


def _contract_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=TAIPEI_TZ)
    return parsed.astimezone(TAIPEI_TZ)


def _contract_date_text(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.astimezone(TAIPEI_TZ).date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def _non_negative_contract_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(Decimal(str(value)))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _intraday_interval_tolerance_seconds(series: dict[str, Any]) -> int:
    interval = str(
        series.get("effective_interval")
        or series.get("interval")
        or "1m"
    ).strip().lower()
    unit = interval[-1:] if interval else ""
    try:
        amount = int(interval[:-1])
    except ValueError:
        amount = 1
    seconds = (
        amount
        if unit == "s"
        else amount * 60
        if unit == "m"
        else amount * 3600
        if unit == "h"
        else 60
    )
    return max(seconds, 60)


def _append_intraday_volume_warning(
    intraday_bars: dict[str, Any],
    series: dict[str, Any],
    message: str,
) -> None:
    for target in (series, intraday_bars):
        warnings = target.setdefault("warnings", [])
        if isinstance(warnings, list) and message not in warnings:
            warnings.append(message)


def _apply_bar_volume_fallback(
    series: dict[str, Any],
    *,
    status: str = "fallback_bar_sum",
) -> None:
    bar_shares = _non_negative_contract_int(series.get("bar_volume_sum_shares"))
    series.update(
        {
            "cumulative_volume_shares": bar_shares,
            "cumulative_volume_lots": (
                bar_shares / 1000 if bar_shares is not None else None
            ),
            "cumulative_volume_trade_date": series.get("bar_volume_trade_date"),
            "cumulative_volume_source": (
                "intraday_bar_sum" if bar_shares is not None else None
            ),
            "cumulative_volume_source_field": (
                "interval_bar.volume" if bar_shares is not None else None
            ),
            "cumulative_volume_event_time": series.get("bar_volume_latest_time"),
            "cumulative_volume_status": status,
        }
    )


def _apply_taiwan_intraday_volume_reconciliation(
    *,
    quote: dict[str, Any],
    intraday_bars: dict[str, Any],
    calendar_status: dict[str, Any],
) -> None:
    series_map = (
        intraday_bars.get("series")
        if isinstance(intraday_bars.get("series"), dict)
        else {}
    )
    if not series_map:
        return

    quote_trade_date = _contract_date_text(quote.get("trade_date"))
    exchange_event_time = _contract_datetime(
        quote.get("event_time")
        or quote.get("provider_event_time")
        or quote.get("quote_time")
    )
    exchange_shares = _non_negative_contract_int(
        quote.get("cumulative_volume_shares")
    )
    if exchange_shares is None:
        exchange_lots = _non_negative_contract_int(
            quote.get("cumulative_volume_lots")
        )
        exchange_shares = exchange_lots * 1000 if exchange_lots is not None else None
    volume_source = str(quote.get("volume_source") or "").strip() or None
    volume_source_field = (
        str(quote.get("volume_source_field") or "").strip() or None
    )
    volume_scope = str(quote.get("volume_scope") or "").strip()
    volume_status = str(quote.get("volume_status") or "").strip().lower()
    freshness = quote.get("freshness") if isinstance(quote.get("freshness"), dict) else {}
    freshness_status = str(freshness.get("status") or "unavailable")
    quote_is_stale = freshness.get("is_stale") is True
    phase_values = {
        str(calendar_status.get("phase") or "").strip().lower(),
        str(quote.get("session_phase") or "").strip().lower(),
        str(quote.get("instrument_phase") or "").strip().lower(),
    }
    is_preopen = bool(
        phase_values
        & {
            "preopen_pending",
            "preopen",
            "preopen_auction",
            "opening_auction_delayed",
        }
    )
    has_exchange_volume = bool(
        exchange_shares is not None
        and volume_source == "twse_mis"
        and volume_source_field == "v"
        and volume_scope == "regular_session_board_lot_cumulative"
        and volume_status == "available"
        and not is_preopen
    )

    for interval, series in series_map.items():
        if not isinstance(series, dict):
            continue
        _apply_bar_volume_fallback(series)
        bar_trade_date = _contract_date_text(series.get("bar_volume_trade_date"))
        bar_latest_time = _contract_datetime(
            series.get("bar_volume_latest_time") or series.get("to_time")
        )
        bar_shares = _non_negative_contract_int(series.get("bar_volume_sum_shares"))
        base_reconciliation = {
            "trade_date": bar_trade_date or quote_trade_date,
            "exchange_cumulative_shares": exchange_shares,
            "bar_volume_sum_shares": bar_shares,
            "difference_shares": None,
            "difference_lots": None,
            "difference_pct": None,
            "exchange_event_time": (
                exchange_event_time.isoformat()
                if exchange_event_time is not None
                else None
            ),
            "bar_latest_time": (
                bar_latest_time.isoformat() if bar_latest_time is not None else None
            ),
            "time_skew_seconds": None,
        }

        if is_preopen:
            series.update(
                {
                    "session_cumulative_volume_shares": None,
                    "session_cumulative_volume_lots": None,
                    "session_cumulative_volume_trade_date": quote_trade_date,
                    "session_cumulative_volume_source": None,
                    "session_cumulative_volume_source_field": None,
                    "session_cumulative_volume_event_time": None,
                    "session_cumulative_volume_status": "unavailable",
                    "cumulative_volume_shares": None,
                    "cumulative_volume_lots": None,
                    "cumulative_volume_trade_date": quote_trade_date,
                    "cumulative_volume_source": None,
                    "cumulative_volume_source_field": None,
                    "cumulative_volume_event_time": None,
                    "cumulative_volume_status": "unavailable",
                    "unallocated_volume_shares": None,
                    "unallocated_volume_lots": None,
                    "volume_reconciliation": {
                        **base_reconciliation,
                        "status": "unavailable",
                        "reason": "preopen_session_cumulative_unavailable",
                    },
                }
            )
            continue

        if not has_exchange_volume:
            series.update(
                {
                    "session_cumulative_volume_shares": None,
                    "session_cumulative_volume_lots": None,
                    "session_cumulative_volume_trade_date": quote_trade_date,
                    "session_cumulative_volume_source": None,
                    "session_cumulative_volume_source_field": None,
                    "session_cumulative_volume_event_time": None,
                    "session_cumulative_volume_status": "unavailable",
                    "unallocated_volume_shares": None,
                    "unallocated_volume_lots": None,
                    "volume_reconciliation": {
                        **base_reconciliation,
                        "status": "unavailable",
                        "reason": "exchange_cumulative_unavailable",
                    },
                }
            )
            continue

        session_status = (
            "stale"
            if quote_is_stale
            else "cached"
            if freshness.get("source_error")
            else freshness_status
        )
        series.update(
            {
                "session_cumulative_volume_shares": exchange_shares,
                "session_cumulative_volume_lots": exchange_shares // 1000,
                "session_cumulative_volume_trade_date": quote_trade_date,
                "session_cumulative_volume_source": volume_source,
                "session_cumulative_volume_source_field": volume_source_field,
                "session_cumulative_volume_event_time": (
                    exchange_event_time.isoformat()
                    if exchange_event_time is not None
                    else None
                ),
                "session_cumulative_volume_status": session_status,
            }
        )

        if quote_trade_date and bar_trade_date and quote_trade_date != bar_trade_date:
            series.update(
                {
                    "session_cumulative_volume_status": "date_mismatch",
                    "cumulative_volume_status": "date_mismatch",
                    "unallocated_volume_shares": None,
                    "unallocated_volume_lots": None,
                    "volume_reconciliation": {
                        **base_reconciliation,
                        "status": "date_mismatch",
                        "reason": "trade_dates_do_not_match",
                    },
                }
            )
            _append_intraday_volume_warning(
                intraday_bars,
                series,
                f"{interval} intraday volume date does not match the MIS quote date.",
            )
            continue

        difference_shares = (
            exchange_shares - bar_shares
            if bar_shares is not None
            else None
        )
        difference_pct = (
            round((difference_shares / exchange_shares) * 100, 4)
            if difference_shares is not None and exchange_shares > 0
            else None
        )
        comparison = {
            **base_reconciliation,
            "difference_shares": difference_shares,
            "difference_lots": (
                difference_shares / 1000
                if difference_shares is not None
                else None
            ),
            "difference_pct": difference_pct,
        }

        if quote_is_stale:
            series.update(
                {
                    "session_cumulative_volume_status": "stale",
                    "cumulative_volume_status": "fallback_bar_sum",
                    "unallocated_volume_shares": None,
                    "unallocated_volume_lots": None,
                    "volume_reconciliation": {
                        **comparison,
                        "status": "time_skew",
                        "reason": "exchange_snapshot_stale",
                    },
                }
            )
            _append_intraday_volume_warning(
                intraday_bars,
                series,
                f"{interval} MIS cumulative volume is stale; bar-sum fallback retained.",
            )
            continue

        if exchange_event_time is None or bar_latest_time is None:
            series.update(
                {
                    "session_cumulative_volume_status": "time_skew",
                    "cumulative_volume_status": "fallback_bar_sum",
                    "unallocated_volume_shares": None,
                    "unallocated_volume_lots": None,
                    "volume_reconciliation": {
                        **comparison,
                        "status": "unavailable",
                        "reason": "comparison_timestamp_unavailable",
                    },
                }
            )
            continue

        time_skew_seconds = int(
            (exchange_event_time - bar_latest_time).total_seconds()
        )
        tolerance_seconds = _intraday_interval_tolerance_seconds(series)
        comparison["time_skew_seconds"] = time_skew_seconds

        if time_skew_seconds < -tolerance_seconds:
            series.update(
                {
                    "session_cumulative_volume_status": "time_skew",
                    "cumulative_volume_status": "fallback_bar_sum",
                    "unallocated_volume_shares": None,
                    "unallocated_volume_lots": None,
                    "volume_reconciliation": {
                        **comparison,
                        "status": "time_skew",
                        "reason": "exchange_event_older_than_bar_latest",
                    },
                }
            )
            _append_intraday_volume_warning(
                intraday_bars,
                series,
                f"{interval} MIS cumulative volume is older than the latest bar; bar-sum fallback retained.",
            )
            continue

        series.update(
            {
                "cumulative_volume_shares": exchange_shares,
                "cumulative_volume_lots": exchange_shares // 1000,
                "cumulative_volume_trade_date": quote_trade_date,
                "cumulative_volume_source": volume_source,
                "cumulative_volume_source_field": volume_source_field,
                "cumulative_volume_event_time": exchange_event_time.isoformat(),
                "cumulative_volume_status": (
                    "time_skew"
                    if time_skew_seconds < 0
                    else session_status
                ),
            }
        )

        if abs(time_skew_seconds) > tolerance_seconds:
            reconciliation_status = "time_skew"
            reconciliation_reason = "exchange_event_newer_than_bar_latest"
            unallocated_shares = None
        elif time_skew_seconds < 0:
            reconciliation_status = "time_skew"
            reconciliation_reason = "bar_latest_slightly_after_exchange_event"
            unallocated_shares = max(difference_shares or 0, 0)
        elif difference_shares is None:
            reconciliation_status = "unavailable"
            reconciliation_reason = "bar_volume_sum_unavailable"
            unallocated_shares = None
        elif difference_shares == 0:
            reconciliation_status = "matched"
            reconciliation_reason = "exchange_and_bar_sum_match"
            unallocated_shares = 0
        elif difference_shares > 0:
            reconciliation_status = "provider_partial"
            reconciliation_reason = "opening_auction_or_provider_coverage_gap"
            unallocated_shares = difference_shares
        else:
            reconciliation_status = "bar_sum_exceeds_exchange"
            reconciliation_reason = "bar_sum_exceeds_exchange_snapshot"
            unallocated_shares = 0

        series.update(
            {
                "unallocated_volume_shares": unallocated_shares,
                "unallocated_volume_lots": (
                    unallocated_shares / 1000
                    if unallocated_shares is not None
                    else None
                ),
                "volume_reconciliation": {
                    **comparison,
                    "status": reconciliation_status,
                    "reason": reconciliation_reason,
                },
            }
        )
        if unallocated_shares and series.get("approx_vwap") is not None:
            series["vwap_confidence"] = "low"
        if reconciliation_status != "matched":
            _append_intraday_volume_warning(
                intraday_bars,
                series,
                f"{interval} MIS session volume and interval-bar sum are not fully comparable ({reconciliation_status}).",
            )


def _apply_taiwan_current_price_contract(
    *,
    quote: dict[str, Any],
    intraday_bars: dict[str, Any],
    latest_daily: Any,
    calendar_status: dict[str, Any],
    checked_at: datetime,
) -> dict[str, Any]:
    resolved = resolve_taiwan_current_price(
        quote=quote,
        intraday_bars=intraday_bars,
        current_session_date=calendar_status.get("date"),
        checked_at=checked_at,
    )
    provider_trade_date = quote.get("trade_date")
    resolved_trade_date = resolved.get("trade_date")
    completed_daily_date = _json_value(
        getattr(latest_daily, "trade_date", None)
    )
    relation = classify_taiwan_session_date_relation(
        quote_date=resolved_trade_date or provider_trade_date,
        completed_daily_date=completed_daily_date,
        current_session_date=calendar_status.get("date"),
        previous_trading_day=calendar_status.get(
            "previous_trading_day"
        ),
        is_trading_day=calendar_status.get("is_trading_day"),
        session_phase=calendar_status.get("phase"),
    )
    current_session_date = _json_value(calendar_status.get("date"))
    if (
        resolved.get("value") is None
        and resolved.get("source_kind") == "previous_close_reference"
        and completed_daily_date
        and current_session_date
        and str(completed_daily_date) < str(current_session_date)
    ):
        latest_completed_close = _json_value(
            getattr(latest_daily, "close_price", None)
        )
        if isinstance(latest_completed_close, (int, float, Decimal)):
            if latest_completed_close > 0:
                resolved["reference_price"] = latest_completed_close
    quote["provider_trade_date"] = provider_trade_date
    quote["current_price"] = resolved
    quote["current_price_available"] = resolved.get("value") is not None
    quote["current_price_source"] = resolved.get("source_kind")
    quote["price_source"] = resolved.get("source_kind")
    quote["price_semantics"] = resolved.get("semantics")
    quote["price_event_time"] = resolved.get("event_time")
    quote["price_confidence"] = resolved.get("confidence")
    quote["session_date_relation"] = relation
    if resolved.get("value") is not None:
        quote["latest_price"] = resolved["value"]
        quote["price"] = resolved["value"]
        quote["last_price"] = resolved["value"]
        quote["trade_date"] = (
            resolved_trade_date or provider_trade_date
        )
        quote["event_time"] = (
            resolved.get("event_time") or quote.get("event_time")
        )
        quote["facts_usable_for_current_session"] = bool(
            resolved.get("is_current_session")
            and resolved.get("is_estimate") is not True
        )
    quote["components"] = _quote_components(quote)
    return resolved


def _financial_valuation_input(
    resolved_current_price: dict[str, Any] | None,
) -> tuple[Decimal | None, datetime | None, str]:
    resolved = (
        resolved_current_price
        if isinstance(resolved_current_price, dict)
        else {}
    )
    if resolved.get("is_estimate") is True:
        return None, None, "unavailable"
    raw_value = resolved.get("value")
    observed_at = resolved.get("event_time") or resolved.get("trade_date")
    if raw_value is None or observed_at is None:
        return None, None, "unavailable"
    try:
        price = Decimal(str(raw_value))
    except (InvalidOperation, TypeError, ValueError):
        return None, None, "unavailable"
    if price <= 0:
        return None, None, "unavailable"
    if isinstance(observed_at, datetime):
        parsed_at = observed_at
    else:
        try:
            parsed_at = datetime.fromisoformat(
                str(observed_at).replace("Z", "+00:00")
            )
        except ValueError:
            return None, None, "unavailable"
    source_kind = str(resolved.get("source_kind") or "unknown")
    return price, parsed_at, f"resolved_current_price:{source_kind}"


def _with_effective_quote_source_health(
    source_health: dict[str, Any] | None,
    *,
    quote_depth: dict[str, Any] | None,
    quote_error: str | None,
    requested: bool,
    checked_at: datetime,
) -> dict[str, Any]:
    health = dict(source_health) if isinstance(source_health, dict) else {}
    entries = health.get("entries") if isinstance(health.get("entries"), list) else []
    persisted = next(
        (
            entry
            for entry in entries
            if isinstance(entry, dict)
            and entry.get("resource") == "taiwan_stock_quote_snapshot"
        ),
        None,
    )
    request_health: dict[str, Any] | None = None
    if requested:
        request_health = {
            "resource": "taiwan_stock_quote_snapshot",
            "status": "success" if quote_depth is not None and not quote_error else "error",
            "evidence_status": (
                (quote_depth.get("freshness") or {}).get("status")
                if isinstance((quote_depth or {}).get("freshness"), dict)
                else None
            ),
            "provider": (quote_depth or {}).get("provider") or "twse_mis",
            "source": (quote_depth or {}).get("source"),
            "observed_at": (
                (quote_depth or {}).get("provider_event_time")
                or (quote_depth or {}).get("quote_time")
            ),
            "checked_at": checked_at.isoformat(),
            "refresh_outcome": (quote_depth or {}).get("refresh_outcome"),
            "error": quote_error,
        }
    effective = resolve_effective_source_health(
        request_health=request_health,
        persisted_health=persisted,
    )
    effective_by_resource = (
        dict(health.get("effective_health_by_resource"))
        if isinstance(health.get("effective_health_by_resource"), dict)
        else {}
    )
    effective_by_resource["taiwan_stock_quote_snapshot"] = effective
    health["effective_health_by_resource"] = effective_by_resource
    health["effective_quote_health"] = effective
    return health





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
    overnight_impact: dict[str, Any] | None = None,
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
        overnight_impact=overnight_impact,
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
    stock_profile = (
        dependencies.read_taiwan_company_profile(db, normalized_stock_id)
        if stock is not None
        else None
    )
    company_profile = _company_profile_payload(stock, stock_profile)
    latest_daily_evidence = dependencies.read_taiwan_latest_daily_evidence(
        db,
        normalized_stock_id,
    )
    latest_daily = _latest_daily_value(latest_daily_evidence)
    if latest_daily is None:
        missing.append("market_daily_price")

    calendar_status = dependencies.build_taiwan_calendar_status()
    official_daily_release = _apply_taiwan_official_daily_release_truth(
        latest_daily=latest_daily,
        calendar_status=calendar_status,
        missing=missing,
        warnings=warnings,
    )
    expected_trade_date = official_daily_release["expected_trade_date"]
    latest_trade_date = official_daily_release["latest_trade_date"]
    quote_is_stale = bool(
        latest_trade_date
        and expected_trade_date
        and str(latest_trade_date) < str(expected_trade_date)
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
    external_fetch_allowed = params.get("external_fetch_allowed") is True
    cached_fallback_allowed = params.get("fallback_to_cached") is not False
    requested_provider_values = (
        params.get("providers") if isinstance(params.get("providers"), list) else []
    )
    legacy_requested_provider = str(
        params.get("provider")
        or (requested_provider_values[0] if requested_provider_values else "auto")
    ).strip().lower() or "auto"
    legacy_strict_provider = params.get("strict_provider") is True
    if legacy_requested_provider != "auto" or legacy_strict_provider:
        warnings.append(
            "Taiwan provider/strict_provider controls are deprecated and ignored; "
            "the backend Data Core owns acquisition and resolution."
        )
    quote_requested = "quote" in requested_domains
    live_quote_requested = external_fetch_allowed and quote_requested
    intraday_requested = "intraday" in requested_domains
    quote_depth: dict[str, Any] | None = None
    quote_error: str | None = None
    if quote_requested and (external_fetch_allowed or cached_fallback_allowed):
        try:
            quote_reader = (
                dependencies.acquire_taiwan_quote_evidence
                if external_fetch_allowed
                else dependencies.read_taiwan_quote_evidence
            )
            quote_kwargs: dict[str, Any] = {
                "db": db,
                "stock_id": normalized_stock_id,
            }
            if external_fetch_allowed:
                quote_kwargs["requested_capabilities"] = (
                    _requested_quote_evidence_capabilities(params)
                )
            quote_depth = quote_reader(
                **quote_kwargs,
            )
        except Exception as exc:
            quote_error = str(exc) or type(exc).__name__
            warnings.append(f"Taiwan public last-trade quote unavailable: {quote_error}")
            missing.append("quote")

    quote = _compact_quote_snapshot(
        latest_daily=latest_daily,
        quote_depth=quote_depth,
        quote_error=quote_error,
        session_phase=calendar_status.get("phase"),
        current_session_date=calendar_status.get("date"),
        is_trading_day=calendar_status.get("is_trading_day"),
        live_quote_requested=live_quote_requested,
    )
    quote_freshness = quote.get("freshness") if isinstance(quote.get("freshness"), dict) else {}
    if quote_depth is None:
        quote_freshness.update(
            {
                "status": "missing"
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
    quote["freshness"] = quote_freshness
    quote["official_daily_release"] = official_daily_release
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
    quote["components"] = _quote_components(quote)
    event_context = taiwan_events.build_tw_stock_event_context(
        stock_id=normalized_stock_id,
        market=getattr(stock, "market", None),
        market_data_params=market_data_params,
        now=dependencies.now(),
        get_event_summary=dependencies.get_taiwan_stock_event_summary,
        get_event_history=dependencies.get_taiwan_stock_event_history,
        get_disposition_status=dependencies.get_taiwan_disposition_status,
        disposition=disposition,
    )
    for item in event_context.get("missing") or []:
        missing.append(str(item))
    for item in event_context.get("warnings") or []:
        warnings.append(str(item))
    intraday_read_allowed = bool(
        str(params.get("realtime_policy") or "") == "cache_only"
        or cached_fallback_allowed
        or external_fetch_allowed
    )
    intraday_bars = _compact_intraday_bars(
        dependencies=dependencies,
        db=db,
        stock_id=normalized_stock_id,
        include_intraday=(
            intraday_requested
            and intraday_read_allowed
        ),
        market_data_params=market_data_params,
        calendar_status=calendar_status,
    )
    _apply_taiwan_intraday_volume_reconciliation(
        quote=quote,
        intraday_bars=intraday_bars,
        calendar_status=calendar_status,
    )
    resolved_current_price = _apply_taiwan_current_price_contract(
        quote=quote,
        intraday_bars=intraday_bars,
        latest_daily=latest_daily,
        calendar_status=calendar_status,
        checked_at=dependencies.now(),
    )
    try:
        source_health = dependencies.build_taiwan_source_health(
            db=db,
            stock_id=normalized_stock_id,
            dataset="taiwan_stock_quote_snapshot",
        )
    except Exception as exc:
        source_health = {
            "kind": "taiwan_source_health",
            "entries": [],
            "warnings": [
                "Taiwan quote source health unavailable: "
                f"{str(exc) or type(exc).__name__}"
            ],
        }
    source_health = _with_effective_quote_source_health(
        source_health,
        quote_depth=quote_depth,
        quote_error=quote_error,
        requested=live_quote_requested,
        checked_at=dependencies.now(),
    )
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
    if quote.get("provider"):
        effective_providers.insert(0, canonical_provider(quote["provider"]))
        effective_providers = list(dict.fromkeys(effective_providers))
    canonical_requested_provider = "auto"
    resolved_quote_health = (
        quote_depth.get("resolved_health")
        if isinstance(quote_depth, dict)
        and isinstance(quote_depth.get("resolved_health"), dict)
        else {}
    )
    provider_fallback_used = bool(resolved_quote_health.get("fallback_used"))
    platform_provider_attempts = (
        quote_depth.get("provider_attempts")
        if isinstance(quote_depth, dict)
        and isinstance(quote_depth.get("provider_attempts"), list)
        else []
    )
    provider_contract = {
        "requested_provider": canonical_requested_provider,
        "legacy_requested_provider": canonical_provider(legacy_requested_provider),
        "effective_provider": effective_providers[0] if effective_providers else None,
        "effective_providers": effective_providers,
        "strict_provider": False,
        "legacy_strict_provider": legacy_strict_provider,
        "provider_control_status": (
            "deprecated_ignored"
            if legacy_requested_provider != "auto" or legacy_strict_provider
            else "backend_owned"
        ),
        "provider_fallback_used": provider_fallback_used,
        "provider_fallback_reason": (
            resolved_quote_health.get("selection_reason")
            if provider_fallback_used
            else None
        ),
        # Data Core owns the attempt list. The AI consumer projects it without
        # inventing an "auto" provider attempt or reconstructing fallback.
        "provider_attempts": list(platform_provider_attempts),
    }
    attempted_domains = [
        domain
        for domain in ("quote",)
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
    provider_contract["cache_reads"] = (
        [
            {
                "domain": "intraday",
                "status": (
                    "persisted_hit"
                    if any(
                        isinstance(item, dict) and item.get("cache_hit")
                        for item in intraday_series.values()
                    )
                    else "persisted_miss"
                ),
                "provider_refresh_attempted": False,
            }
        ]
        if intraday_requested
        and intraday_bars.get("enabled")
        and "intraday" not in attempted_domains
        else []
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
    slots.update(
        _quote_component_slots(
            quote,
            payload_level=level,
        )
    )

    source_refs = (
        [{"type": "resolved_market_data", "name": "tw.daily.ohlcv"}]
        if latest_daily is not None
        else []
    )
    if quote_depth is not None:
        _append_source_ref_once(
            source_refs,
            {"type": "resolved_market_data", "name": "tw.quote.snapshot"},
        )
    if intraday_bars.get("enabled"):
        _append_source_ref_once(
            source_refs,
            {"type": "external_or_cache", "name": "market_intraday_bar"},
        )
    _append_source_ref_once(
        source_refs,
        {"type": "derived", "name": "app.market.source_health"},
    )
    for source_ref in event_context.get("source_refs") or []:
        if isinstance(source_ref, dict):
            _append_source_ref_once(source_refs, source_ref)
    intraday_domain_status = (
        str((intraday_series.get("1m") or {}).get("freshness_status") or "unavailable")
        if intraday_requested
        else "not_requested"
    )
    selected_intraday = intraday_series.get("1m") or {}
    intraday_freshness = (
        dict(selected_intraday.get("freshness"))
        if isinstance(selected_intraday.get("freshness"), dict)
        else {
            "status": intraday_domain_status,
            "is_current": intraday_domain_status == "current",
            "expected_trade_date": selected_intraday.get("expected_trade_date"),
            "latest_trade_date": selected_intraday.get("trade_date"),
        }
    )
    compact_status = (
        "missing"
        if latest_daily is None and quote_freshness.get("status") in {None, "missing", "unavailable"}
        else "partial"
        if quote_freshness.get("status") in {"cached", "stale", "unavailable", "source_unavailable"}
        or intraday_domain_status in {"partial", "delayed", "stale", "missing", "unavailable"}
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
        "source_health": source_health,
        "freshness_by_domain": {
            "quote": quote_freshness.get("status"),
            "intraday": intraday_domain_status,
        },
        "freshness_by_capability": {
            "target.identity": {
                "status": "current",
                "dataset": "stock_master",
                "is_current": stock is not None,
                "refresh_recommended": False,
            },
            "quote.snapshot": {
                **quote_freshness,
                "dataset": "quote",
            },
            **(
                {
                    "intraday.bars": {
                        **intraday_freshness,
                        "dataset": "tw.intraday.bars",
                    }
                }
                if intraday_requested
                else {}
            ),
            **_quote_component_freshness_rows(quote),
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
            "company_profile": company_profile,
            "quote": quote,
            "current_price": resolved_current_price,
            "intraday_bars": intraday_bars,
            "provider_contract": provider_contract,
            "refresh_summary": refresh_summary,
            "source_health": source_health,
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


def read_stock_event_context(
    db: Session,
    stock_id: str,
    *,
    market_data_params: dict[str, Any] | None = None,
    dependencies: TaiwanStockDependencies,
) -> dict[str, Any]:
    normalized_stock_id = stock_id.strip()
    missing: list[str] = []
    warnings: list[str] = []
    source_refs: list[dict[str, Any]] = []
    try:
        stock = dependencies.stock_service.get_stock(
            db=db,
            stock_id=normalized_stock_id,
        )
    except dependencies.stock_service.StockNotFoundError:
        stock = None
        missing.append("stock_master")
    if stock is not None:
        source_refs.append({"type": "table", "name": "stock_master"})

    generated_at = dependencies.now()
    event_context = taiwan_events.build_tw_stock_event_context(
        stock_id=normalized_stock_id,
        market=getattr(stock, "market", None),
        market_data_params=market_data_params,
        now=generated_at,
        get_event_summary=dependencies.get_taiwan_stock_event_summary,
        get_event_history=dependencies.get_taiwan_stock_event_history,
        get_disposition_status=dependencies.get_taiwan_disposition_status,
    )
    missing.extend(
        str(item) for item in event_context.get("missing") or []
    )
    warnings.extend(
        str(item) for item in event_context.get("warnings") or []
    )
    for source_ref in event_context.get("source_refs") or []:
        if isinstance(source_ref, dict):
            _append_source_ref_once(source_refs, source_ref)

    capability_data = (
        event_context.get("data")
        if isinstance(event_context.get("data"), dict)
        else {}
    )
    events = {
        key.split(".", 1)[1]: value
        for key, value in capability_data.items()
        if str(key).startswith("events.")
    }
    regulation = {
        key.split(".", 1)[1]: value
        for key, value in capability_data.items()
        if str(key).startswith("regulation.")
    }
    corporate_actions = capability_data.get("corporate.actions")
    freshness_by_capability = (
        event_context.get("freshness_by_capability")
        if isinstance(event_context.get("freshness_by_capability"), dict)
        else {}
    )
    statuses = {
        str(item.get("status") or "missing")
        for item in freshness_by_capability.values()
        if isinstance(item, dict)
    }
    is_current = bool(statuses) and statuses <= {"current"}
    freshness_status = (
        "current"
        if is_current
        else "missing"
        if statuses and statuses <= {"missing", "unavailable", "error"}
        else "partial"
        if statuses
        else "not_requested"
    )
    as_of = _latest_date_string(
        [
            value.get("as_of")
            for value in capability_data.values()
            if isinstance(value, dict) and value.get("as_of")
        ]
    )
    target = {
        "type": "tw_stock",
        "id": normalized_stock_id,
        "label": getattr(stock, "stock_name", None),
        "market": getattr(stock, "market", None) or "TW",
    }
    compact = {
        "kind": "tw_stock_event_compact_evidence",
        "version": "tw_stock_event_compact_evidence.v1",
        "payload_level": _payload_level(market_data_params),
        "status": event_context.get("status"),
        "target": target,
        "as_of": as_of,
        "events": events,
        "regulation": regulation,
        "freshness_by_capability": freshness_by_capability,
        "data_quality": {
            "missing": list(dict.fromkeys(missing)),
            "warnings": list(dict.fromkeys(warnings)),
        },
        "slots": event_context.get("slots") or {},
        "source_refs": source_refs,
    }
    envelope = {
        "kind": "stock_event_context",
        "generated_at": generated_at,
        "as_of": as_of,
        "scope": {"stock_id": normalized_stock_id},
        "data": {
            "stock": _stock_dict(stock),
            "events": events,
            "corporate_actions": corporate_actions,
            "regulation": regulation,
            "compact": compact,
        },
        "missing": list(dict.fromkeys(missing)),
        "warnings": list(dict.fromkeys(warnings)),
        "source_refs": source_refs,
    }
    return _with_evidence_passport(
        envelope,
        freshness={
            "scope_profile": "event_only",
            "status": freshness_status,
            "is_current": is_current,
            "as_of": as_of,
            "missing": envelope["missing"],
            "warnings": envelope["warnings"],
            "freshness_by_capability": freshness_by_capability,
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
        **_broker_branch_metadata(branch_summary),
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


def read_stock_technical_context(
    db: Session,
    stock_id: str,
    *,
    bars: int = 120,
    analysis_horizon: str = "swing",
    market_data_params: dict[str, Any] | None = None,
    dependencies: TaiwanStockDependencies,
) -> dict[str, Any]:
    """Read only the hard dependencies of explicit Taiwan technical evidence."""

    normalized_stock_id = stock_id.strip()
    stock = dependencies.stock_service.get_stock(
        db=db,
        stock_id=normalized_stock_id,
    )
    requested_trade_date = parse_market_trade_date(
        (market_data_params or {}).get("trade_date")
    )
    latest_daily_evidence = dependencies.read_taiwan_latest_daily_evidence(
        db,
        normalized_stock_id,
        to_date=requested_trade_date,
    )
    latest_daily = _latest_daily_value(latest_daily_evidence)
    chart = dependencies.market_service.list_stock_ohlc_chart_data(
        db=db,
        stock_id=normalized_stock_id,
        timeframe="daily",
        bars=max(int(bars), 1),
        ensure_history=False,
        to_date=requested_trade_date,
    )
    missing: list[str] = []
    warnings: list[str] = []
    technical_reports: dict[str, Any] = {}
    for timeframe in ("daily", "weekly", "monthly"):
        try:
            technical_reports[timeframe] = dependencies.build_stock_technical_report(
                db=db,
                stock_id=normalized_stock_id,
                timeframe=timeframe,
                include_intraday=False,
                to_date=requested_trade_date,
            )
        except Exception as exc:
            missing.append(f"technical_report.{timeframe}")
            warnings.append(
                f"{timeframe.title()} technical report unavailable: {exc}"
            )
    technical_analysis = _technical_analysis_summary(
        technical_reports=technical_reports,
        requested_horizon=analysis_horizon,
    )
    technical_sufficiency = _evaluate_technical_evidence_sufficiency(
        chart=chart,
        technical_reports=technical_reports,
        requested_horizon=analysis_horizon,
    )
    technical_analysis = _apply_technical_sufficiency_gate(
        technical_analysis,
        sufficiency=technical_sufficiency,
    )
    technical_levels = _technical_price_levels(
        technical_reports=technical_reports,
        latest_daily=latest_daily,
        resolved_current_price=None,
    )
    market_calendar_status = dependencies.build_taiwan_calendar_status()
    technical_evidence: dict[str, Any] = {}
    if dependencies.build_tw_stock_technical_evidence is not None:
        try:
            corporate_event_history = dependencies.get_taiwan_stock_event_history(
                normalized_stock_id,
                market=getattr(stock, "market", None),
                years=10,
                max_results=200,
                now=dependencies.now(),
            )
            technical_evidence = dependencies.build_tw_stock_technical_evidence(
                db=db,
                stock_id=normalized_stock_id,
                corporate_event_history=corporate_event_history,
                current_quote=None,
                intraday_points=[],
                market_calendar_status=market_calendar_status,
                to_date=requested_trade_date,
            )
            warnings.extend(str(item) for item in technical_evidence.get("warnings") or [])
        except Exception as exc:
            missing.append("technical_evidence")
            warnings.append(f"Canonical technical evidence unavailable: {exc}")
    source_refs = [
        {"type": "table", "name": "stock_master"},
        {"type": "resolved_market_data", "name": "tw.daily.ohlcv"},
        {"type": "derived", "name": "app.market.technical_report"},
        {"type": "derived", "name": "app.market.technical_evidence"},
    ]
    serialized_chart = {
        **chart,
        "from_date": _json_value(chart.get("from_date")),
        "to_date": _json_value(chart.get("to_date")),
        "returned_point_count": len(chart.get("points") or []),
        "volume_unit": chart.get("volume_unit") or "shares",
        "trade_value_unit": chart.get("trade_value_unit") or "TWD",
        "points": [
            {key: _json_value(value) for key, value in point.items()}
            for point in chart.get("points") or []
        ],
    }
    as_of = _json_value(
        chart.get("latest_data_date")
        or chart.get("to_date")
        or getattr(latest_daily, "trade_date", None)
    )
    compact = _build_stock_compact_evidence(
        stock=stock,
        company_profile={"status": "not_requested"},
        stock_id=normalized_stock_id,
        as_of=as_of,
        latest_daily=latest_daily,
        latest_institutional=None,
        latest_margin=None,
        shareholding=[],
        branch_summary={"buy_top": [], "sell_top": [], "trade_dates": []},
        latest_revenue=None,
        revenue_history=[],
        latest_financial=None,
        financial_history=[],
        technical_reports=technical_reports,
        technical_analysis=technical_analysis,
        technical_levels=technical_levels,
        technical_evidence=technical_evidence,
        quote={},
        intraday_bars={
            "enabled": False,
            "series": {},
            "payload_level": _payload_level(market_data_params),
        },
        source_health={"entries": []},
        overnight_impact=None,
        event_context={},
        missing=missing,
        warnings=warnings,
        source_refs=source_refs,
        latest_daily_evidence=latest_daily_evidence,
    )
    envelope = {
        "kind": "stock_technical_context",
        "generated_at": dependencies.now(),
        "as_of": as_of,
        "scope": {
            "type": "stock",
            "id": normalized_stock_id,
            "market": "TW",
        },
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
            "chart": serialized_chart,
            "technical_reports": technical_reports,
            "technical_evidence": technical_evidence,
            "technical_indicators": technical_evidence.get("indicators"),
            "analysis": technical_analysis,
            "technical_levels": technical_levels,
            "compact": compact,
            "market_calendar_status": market_calendar_status,
        },
        "missing": list(dict.fromkeys(missing)),
        "warnings": list(dict.fromkeys(warnings)),
        "source_refs": source_refs,
    }
    return _with_evidence_passport(
        envelope,
        analysis=technical_analysis,
        confidence=str(technical_analysis.get("selected_confidence") or ""),
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
    stock_profile = (
        dependencies.read_taiwan_company_profile(db, normalized_stock_id)
        if stock is not None
        else None
    )
    company_profile = _company_profile_payload(stock, stock_profile)
    fundamentals_applicable = not (
        stock is not None
        and is_taiwan_etf(
            getattr(stock, "instrument_type", None),
            stock_id=normalized_stock_id,
        )
    )

    requested_trade_date = parse_market_trade_date(
        (market_data_params or {}).get("trade_date")
    )
    latest_daily_evidence = dependencies.read_taiwan_latest_daily_evidence(
        db,
        normalized_stock_id,
        to_date=requested_trade_date,
    )
    latest_daily = _latest_daily_value(latest_daily_evidence)
    latest_institutional = dependencies.market_service.get_latest_stock_institutional_trade(db, normalized_stock_id)
    latest_margin = dependencies.market_service.get_latest_stock_margin_trade(db, normalized_stock_id)
    fundamental_inputs = _read_stock_fundamental_inputs(
        db=db,
        stock_id=normalized_stock_id,
        revenue_months=revenue_months,
        financial_quarters=financial_quarters,
        applicable=fundamentals_applicable,
        market_service=dependencies.market_service,
    )
    latest_revenue = fundamental_inputs["latest_revenue"]
    latest_financial = fundamental_inputs["latest_financial"]
    shareholding = dependencies.market_service.list_latest_stock_shareholding_distribution(db, normalized_stock_id)
    revenue_history = fundamental_inputs["revenue_history"]
    financial_history = fundamental_inputs["financial_history"]
    chart = dependencies.market_service.list_stock_ohlc_chart_data(
        db=db,
        stock_id=normalized_stock_id,
        timeframe="daily",
        bars=max(bars, 1),
        ensure_history=False,
        to_date=requested_trade_date,
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
                to_date=requested_trade_date,
            )
        except Exception as exc:
            warnings.append(f"{timeframe.title()} technical report unavailable: {exc}")
            missing.append(f"technical_report.{timeframe}")

    if requested_trade_date is None and (
        include_intraday or normalized_horizon == "intraday"
    ):
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
    technical_sufficiency = _evaluate_technical_evidence_sufficiency(
        chart=chart,
        technical_reports=technical_reports,
        requested_horizon=analysis_horizon,
    )
    technical_analysis = _apply_technical_sufficiency_gate(
        technical_analysis,
        sufficiency=technical_sufficiency,
    )
    technical_levels: dict[str, Any] = {}
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
    if fundamentals_applicable:
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
        {"type": "resolved_market_data", "name": "tw.daily.ohlcv"},
        {"type": "table", "name": "institutional_trade_daily"},
        {"type": "table", "name": "margin_trading_daily"},
        {"type": "table", "name": "shareholding_distribution_weekly"},
        {"type": "table", "name": "broker_branch_trade_daily"},
        {"type": "derived", "name": "app.market.technical_report"},
        {"type": "table", "name": "us_daily_price"},
        {"type": "table", "name": "us_watchlist_group"},
        {"type": "table", "name": "us_watchlist_item"},
        {"type": "derived", "name": "app.market.calendar_status"},
        {"type": "derived", "name": "app.market.overnight_impact"},
    ]
    if fundamentals_applicable:
        source_refs.extend(
            [
                {"type": "table", "name": "monthly_revenue"},
                {"type": "table", "name": "financial_metric_quarterly"},
            ]
        )
    market_calendar_status = dependencies.build_taiwan_calendar_status()
    official_daily_release = _apply_taiwan_official_daily_release_truth(
        latest_daily=latest_daily,
        calendar_status=market_calendar_status,
        missing=missing,
        warnings=warnings,
    )
    source_health = dependencies.build_taiwan_source_health(
        db=db,
        stock_id=normalized_stock_id,
    )
    source_refs.append({"type": "derived", "name": "app.market.source_health"})

    quote_depth: dict[str, Any] | None = None
    quote_error: str | None = None
    if include_intraday:
        try:
            context_params = (
                market_data_params
                if isinstance(market_data_params, dict)
                else {}
            )
            quote_reader = (
                dependencies.acquire_taiwan_quote_evidence
                if context_params.get("external_fetch_allowed") is True
                else dependencies.read_taiwan_quote_evidence
            )
            quote_kwargs: dict[str, Any] = {
                "db": db,
                "stock_id": normalized_stock_id,
            }
            if context_params.get("external_fetch_allowed") is True:
                quote_kwargs["requested_capabilities"] = (
                    _requested_quote_evidence_capabilities(context_params)
                )
            quote_depth = quote_reader(**quote_kwargs)
            _append_source_ref_once(
                source_refs,
                {"type": "resolved_market_data", "name": "tw.quote.snapshot"},
            )
        except Exception as exc:
            quote_error = str(exc) or exc.__class__.__name__
            warnings.append(f"Taiwan public last-trade quote unavailable: {quote_error}")
            missing.append("quote")
    source_health = _with_effective_quote_source_health(
        source_health,
        quote_depth=quote_depth,
        quote_error=quote_error,
        requested=include_intraday,
        checked_at=dependencies.now(),
    )

    quote = _compact_quote_snapshot(
        latest_daily=latest_daily,
        quote_depth=quote_depth,
        quote_error=quote_error,
        session_phase=market_calendar_status.get("phase"),
        current_session_date=market_calendar_status.get("date"),
        is_trading_day=market_calendar_status.get("is_trading_day"),
        live_quote_requested=include_intraday,
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
    quote["components"] = _quote_components(quote)
    event_context = taiwan_events.build_tw_stock_event_context(
        stock_id=normalized_stock_id,
        market=getattr(stock, "market", None),
        market_data_params=market_data_params,
        now=dependencies.now(),
        get_event_summary=dependencies.get_taiwan_stock_event_summary,
        get_event_history=dependencies.get_taiwan_stock_event_history,
        get_disposition_status=dependencies.get_taiwan_disposition_status,
        disposition=disposition,
    )
    for item in event_context.get("missing") or []:
        missing.append(str(item))
    for item in event_context.get("warnings") or []:
        warnings.append(str(item))
    for source_ref in event_context.get("source_refs") or []:
        if isinstance(source_ref, dict):
            _append_source_ref_once(source_refs, source_ref)

    intraday_bars = _compact_intraday_bars(
        dependencies=dependencies,
        db=db,
        stock_id=normalized_stock_id,
        include_intraday=include_intraday,
        market_data_params=market_data_params,
        calendar_status=market_calendar_status,
    )
    intraday_series = (
        intraday_bars.get("series")
        if isinstance(intraday_bars.get("series"), dict)
        else {}
    )
    if intraday_bars.get("enabled"):
        _append_source_ref_once(source_refs, {"type": "external_or_cache", "name": "market_intraday_bar"})
        for warning in intraday_bars.get("warnings") or []:
            warnings.append(str(warning))
        if not any(isinstance(item, dict) and item.get("returned_point_count") for item in intraday_series.values()):
            missing.append("intraday_bars")

    technical_evidence: dict[str, Any] = {}
    requested_capabilities = {
        str(value)
        for value in (market_data_params or {}).get("requested_capabilities") or []
    }
    technical_evidence_capabilities = {
        "technical.structure",
        "technical.indicators",
        "technical.swings",
        "technical.fibonacci",
        "technical.divergence",
        "technical.breakout",
        "technical.volume_profile",
        "technical.anchored_vwap",
        "technical.relative_strength",
    }
    if (
        dependencies.build_tw_stock_technical_evidence is not None
        and requested_capabilities & technical_evidence_capabilities
    ):
        try:
            corporate_event_history = dependencies.get_taiwan_stock_event_history(
                normalized_stock_id,
                market=getattr(stock, "market", None),
                years=10,
                max_results=200,
                now=dependencies.now(),
            )
            technical_evidence = dependencies.build_tw_stock_technical_evidence(
                db=db,
                stock_id=normalized_stock_id,
                corporate_event_history=corporate_event_history,
                current_quote=quote,
                intraday_points=list((intraday_series.get("1m") or {}).get("points") or []),
                market_calendar_status=market_calendar_status,
                to_date=requested_trade_date,
            )
            for item in technical_evidence.get("warnings") or []:
                warnings.append(str(item))
            for item in technical_evidence.get("source_refs") or []:
                if isinstance(item, dict):
                    _append_source_ref_once(source_refs, item)
        except Exception as exc:
            warnings.append(f"Canonical technical evidence unavailable: {exc}")
            missing.append("technical_evidence")

    resolved_current_price = _apply_taiwan_current_price_contract(
        quote=quote,
        intraday_bars=intraday_bars,
        latest_daily=latest_daily,
        calendar_status=market_calendar_status,
        checked_at=dependencies.now(),
    )
    technical_levels = _technical_price_levels(
        technical_reports=technical_reports,
        latest_daily=latest_daily,
        resolved_current_price=resolved_current_price,
    )
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
    financial_price, financial_price_as_of, financial_price_basis = (
        _financial_valuation_input(resolved_current_price)
    )
    financial_contract = (
        build_database_financial_contract(
            db,
            stock_id=normalized_stock_id,
            mode="current_comparable",
            as_of=dependencies.now(),
            financial_history=financial_history,
            revenue_history=revenue_history,
            price=financial_price,
            price_as_of=financial_price_as_of,
            price_basis=financial_price_basis,
            normalized_period_limit=max(
                5,
                min(financial_quarters + 1, 41),
            ),
        )
        if fundamentals_applicable
        else {
            "contract_version": FINANCIAL_CONTRACT_VERSION,
            "status": "not_applicable",
            "applicability_status": "not_applicable",
            "availability_status": "not_applicable",
            "reason_codes": ["ETF_FUNDAMENTALS_NOT_APPLICABLE"],
            "quality": {
                "status": "not_applicable",
                "decision_usable": False,
                "reason_codes": ["ETF_FUNDAMENTALS_NOT_APPLICABLE"],
            },
        }
    )

    decision_evidence = _stock_decision_evidence(
        latest_daily=latest_daily,
        chart=chart,
        latest_revenue=latest_revenue,
        latest_financial=latest_financial,
        technical_reports=technical_reports,
        calendar_status=market_calendar_status,
        overnight_impact=overnight_impact,
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
            "company_profile": company_profile,
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
                "returned_point_count": len(chart.get("points", [])),
                "volume_unit": "shares",
                "trade_value_unit": "TWD",
                "points": [
                    {key: _json_value(value) for key, value in point.items()}
                    for point in chart.get("points", [])
                ],
            },
            "technical_reports": technical_reports,
            "technical_evidence": technical_evidence,
            "technical_indicators": technical_evidence.get("indicators"),
            "technical_advanced": {
                key: technical_evidence.get(key)
                for key in (
                    "structure_v2",
                    "swings",
                    "fibonacci",
                    "divergence",
                    "breakout",
                    "volume_profile",
                    "anchored_vwap",
                    "relative_strength",
                )
                if technical_evidence.get(key) is not None
            },
            "analysis": technical_analysis,
            "technical_levels": technical_levels,
            "current_price": resolved_current_price,
            "compact": _build_stock_compact_evidence(
                stock=stock,
                company_profile=company_profile,
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
                technical_evidence=technical_evidence,
                quote=quote,
                intraday_bars=intraday_bars,
                source_health=source_health,
                overnight_impact=overnight_impact,
                event_context=event_context,
                missing=missing,
                warnings=warnings,
                source_refs=source_refs,
                financial_contract=financial_contract,
                fundamentals_applicable=fundamentals_applicable,
                latest_daily_evidence=latest_daily_evidence,
            ),
            "market_calendar_status": market_calendar_status,
            "official_daily_release": official_daily_release,
            "source_health": source_health,
            "events": {
                key.split(".", 1)[1]: value
                for key, value in (event_context.get("data") or {}).items()
                if str(key).startswith("events.")
            },
            "corporate_actions": (
                event_context.get("data", {}).get("corporate.actions")
                if isinstance(event_context.get("data"), dict)
                else None
            ),
            "regulation": {
                key.split(".", 1)[1]: value
                for key, value in (event_context.get("data") or {}).items()
                if str(key).startswith("regulation.")
            },
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
                **_broker_branch_metadata(branch_summary),
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
