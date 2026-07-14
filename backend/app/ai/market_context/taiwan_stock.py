from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
)


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


def _compact_intraday_bars(
    *,
    dependencies: TaiwanStockDependencies,
    db: Session,
    stock_id: str,
    include_intraday: bool,
    market_data_params: dict[str, Any] | None = None,
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
            series[interval] = _compact_intraday_history(history, point_limit=point_limit)
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
            getattr(latest_financial, "report_date", None),
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
    intraday_bars = _compact_intraday_bars(
        dependencies=dependencies,
        db=db,
        stock_id=normalized_stock_id,
        include_intraday=include_intraday,
        market_data_params=market_data_params,
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
