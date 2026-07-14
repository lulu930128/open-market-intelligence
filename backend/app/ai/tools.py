from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.ai import evidence_builder, technical_analysis, tool_catalog
from app.ai.evidence_passport import build_evidence_passport
from app.ai.market_payload_contract import (
    COMPACT_INTRADAY_BAR_LIMIT,
    PAYLOAD_LEVELS,
    bounded_int_param as _bounded_int_param,
    has_payload_value as _has_payload_value,
    intraday_point_limit as _intraday_point_limit,
    market_data_params as _market_data_params,
    payload_level as _payload_level,
    payload_slot_status as _payload_slot_status,
    slot_envelope as _slot_envelope,
)
from app.ai.market_context.common import append_source_ref_once as _append_source_ref_once
from app.ai.market_context import taiwan_freshness, taiwan_projection
from app.db.models import (
    BrokerBranchTradeDaily,
    FinancialMetricQuarterly,
    InstitutionalTradeDaily,
    MarginTradingDaily,
    MarketDailyPrice,
    MonthlyRevenue,
    ShareholdingDistributionWeekly,
    StockMaster,
)
from app.market import service as market_service
from app.market.broker_branch import get_broker_branch_trade_summary
from app.market.calendar_status import build_taiwan_calendar_status
from app.market.intraday import get_market_intraday_history
from app.market.quote_depth import get_taiwan_stock_quote_depth
from app.market.technical_report import build_stock_technical_report
from app.market.indices import (
    get_market_index_contributions,
    get_market_index_intraday,
    get_market_index_ohlc_chart_data,
    get_market_index_summary,
)
from app.market.market_chips import get_latest_market_chip_daily, market_chip_daily_to_dict
from app.market.overnight_impact import build_us_overnight_impact_report
from app.market.source_health import build_taiwan_source_health
from app.market.tw_futures import (
    get_latest_taiwan_futures_quotes,
    list_taiwan_futures_daily_bars,
    list_taiwan_futures_intraday_bars,
    normalize_taiwan_futures_symbols,
    taiwan_futures_daily_bar_to_dict,
    taiwan_futures_intraday_bar_to_dict,
    taiwan_futures_quote_to_dict,
)
from app.market.taiwan_industries import normalize_tw_industry_label
from app.stocks import service as stock_service
from app.watchlists import radar_service, ranking_service
from app.watchlists import service as watchlist_service


_now = taiwan_projection._now
_json_value = taiwan_projection._json_value
_row_dict = taiwan_projection._row_dict
_stock_dict = taiwan_projection._stock_dict
_latest_financial_period = taiwan_projection._latest_financial_period
_latest_date_string = taiwan_projection._latest_date_string
_broker_branch_row = taiwan_projection._broker_branch_row
_add_missing = taiwan_projection._add_missing
COMPACT_INTRADAY_INTERVALS = taiwan_projection.COMPACT_INTRADAY_INTERVALS
FRESHNESS_DOMAIN_RESOURCES = taiwan_projection.FRESHNESS_DOMAIN_RESOURCES
_quote_slot_status = taiwan_projection._quote_slot_status
_intraday_slot_status = taiwan_projection._intraday_slot_status
_build_tw_stock_slots = taiwan_projection._build_tw_stock_slots
_build_tw_index_slots = taiwan_projection._build_tw_index_slots
_build_tw_market_slots = taiwan_projection._build_tw_market_slots
_compact_row = taiwan_projection._compact_row
_compact_latest_daily_quote = taiwan_projection._compact_latest_daily_quote
_compact_quote_snapshot = taiwan_projection._compact_quote_snapshot
_compact_intraday_point = taiwan_projection._compact_intraday_point
_compact_intraday_history = taiwan_projection._compact_intraday_history
_compact_single_intraday_series = taiwan_projection._compact_single_intraday_series
_compact_technical_report = taiwan_projection._compact_technical_report
_compact_technical_evidence = taiwan_projection._compact_technical_evidence
_source_health_entries = taiwan_projection._source_health_entries
_compact_source_health_entry = taiwan_projection._compact_source_health_entry
_status_from_resources = taiwan_projection._status_from_resources
_freshness_domain_from_resources = taiwan_projection._freshness_domain_from_resources
_quote_freshness_domain = taiwan_projection._quote_freshness_domain
_intraday_bar_freshness_resource = taiwan_projection._intraday_bar_freshness_resource
_cross_market_freshness_domain = taiwan_projection._cross_market_freshness_domain
_build_freshness_by_domain = taiwan_projection._build_freshness_by_domain
_latest_intraday_point = taiwan_projection._latest_intraday_point
_intraday_source_is_live = taiwan_projection._intraday_source_is_live
_compact_index_quote = taiwan_projection._compact_index_quote
_index_freshness_by_domain = taiwan_projection._index_freshness_by_domain
_build_tw_index_compact_evidence = taiwan_projection._build_tw_index_compact_evidence
_build_stock_compact_evidence = taiwan_projection._build_stock_compact_evidence
_with_evidence_passport = taiwan_projection._with_evidence_passport


def _compact_intraday_bars(
    *,
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
            history = get_market_intraday_history(
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


def _json_dict(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: _json_value(value) for key, value in row.items()}


def list_ai_tools(*, include_internal: bool = False) -> dict[str, Any]:
    return tool_catalog.list_ai_tools(include_internal=include_internal)


def read_data_freshness(db: Session, stock_id: str | None = None) -> dict[str, Any]:
    return taiwan_freshness.read_data_freshness(
        db=db,
        stock_id=stock_id,
        now=_now,
    )


def _market_index_ids_from_params(params: dict[str, Any] | None) -> list[str]:
    data_params = _market_data_params(params)
    raw_value = data_params.get("index_ids") or data_params.get("indices") or ("TAIEX", "TPEX")
    if isinstance(raw_value, str):
        values = [item.strip().upper() for item in raw_value.split(",")]
    elif isinstance(raw_value, list):
        values = [str(item).strip().upper() for item in raw_value]
    else:
        values = ["TAIEX", "TPEX"]
    supported = {"TAIEX", "TPEX"}
    selected = [value for value in values if value in supported]
    return list(dict.fromkeys(selected or ["TAIEX", "TPEX"]))[:2]


def _market_index_intraday_pack(
    *,
    include_intraday: bool,
    market_data_params: dict[str, Any] | None,
    missing: list[str],
    warnings: list[str],
    source_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    payload_level = _payload_level(market_data_params)
    point_limit = _intraday_point_limit(market_data_params)
    index_ids = _market_index_ids_from_params(market_data_params)
    if not include_intraday:
        return {
            "kind": "market_index_intraday_pack",
            "enabled": False,
            "payload_level": payload_level,
            "bar_limit": point_limit,
            "index_ids": index_ids,
            "indices": [],
            "warnings": [],
        }

    rows: list[dict[str, Any]] = []
    local_warnings: list[str] = []
    _append_source_ref_once(source_refs, {"type": "external_or_cache", "name": "market_index_intraday"})
    for index_id in index_ids:
        try:
            intraday = get_market_index_intraday(index_id)
        except Exception as exc:
            message = f"{index_id} index intraday unavailable: {exc}"
            warnings.append(message)
            local_warnings.append(message)
            missing.append(f"market_index_intraday.{index_id}")
            continue

        intraday_bars = _compact_single_intraday_series(
            raw_payload=intraday,
            interval="1m",
            include_intraday=True,
            market_data_params=market_data_params,
        )
        quote = _compact_index_quote(
            index_id=index_id,
            index_snapshot=None,
            intraday=intraday,
        )
        rows.append(
            {
                "index_id": index_id,
                "quote": quote,
                "intraday_bars": intraday_bars,
            }
        )
        series = intraday_bars.get("series") if isinstance(intraday_bars.get("series"), dict) else {}
        if not any(isinstance(item, dict) and item.get("returned_point_count") for item in series.values()):
            missing.append(f"market_index_intraday.{index_id}")

    return {
        "kind": "market_index_intraday_pack",
        "enabled": True,
        "payload_level": payload_level,
        "bar_limit": point_limit,
        "index_ids": index_ids,
        "indices": rows,
        "warnings": local_warnings,
    }


def read_market_overview(
    db: Session,
    limit: int = 10,
    *,
    include_intraday: bool = False,
    market_data_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    latest_trade_date = market_service.get_latest_trade_date(db)
    missing: list[str] = []
    warnings: list[str] = []
    source_refs: list[dict[str, Any]] = [{"type": "table", "name": "market_daily_price"}]
    payload_level = _payload_level(market_data_params)
    index_intraday = _market_index_intraday_pack(
        include_intraday=include_intraday,
        market_data_params=market_data_params,
        missing=missing,
        warnings=warnings,
        source_refs=source_refs,
    )

    if latest_trade_date is None:
        envelope = {
            "kind": "market_overview",
            "generated_at": _now(),
            "as_of": None,
            "scope": {},
            "data": {
                "latest_trade_date": None,
                "breadth": {},
                "top_gainers": [],
                "top_losers": [],
                "index_intraday": index_intraday,
                "slots": _build_tw_market_slots(
                    as_of=None,
                    payload_level=payload_level,
                    breadth={},
                    distribution={},
                    industry_rows=[],
                    index_intraday=index_intraday,
                    missing=list(dict.fromkeys(["market_daily_price", *missing])),
                    warnings=[
                        "No market daily rows are available in the local database.",
                        *warnings,
                    ],
                ),
            },
            "missing": list(dict.fromkeys(["market_daily_price", *missing])),
            "warnings": [
                "No market daily rows are available in the local database.",
                *warnings,
            ],
            "source_refs": source_refs,
        }
        return _with_evidence_passport(
            envelope,
            freshness={
                "is_current": False,
                "missing": envelope["missing"],
                "warnings": envelope["warnings"],
            },
        )

    rows = market_service.list_market_daily_prices(
        db=db,
        trade_date=latest_trade_date,
        limit=10000,
    )
    stock_ids = sorted({row.stock_id for row in rows if row.stock_id})
    stock_industries: dict[str, str | None] = {}
    for index in range(0, len(stock_ids), 500):
        chunk = stock_ids[index : index + 500]
        for stock in db.query(StockMaster).filter(StockMaster.stock_id.in_(chunk)).all():
            stock_industries[stock.stock_id] = normalize_tw_industry_label(
                stock.industry or stock.category,
                fallback="未分類",
            )
    ranked = [
        {
            "stock_id": row.stock_id,
            "stock_name": row.stock_name,
            "close_price": row.close_price,
            "price_change": row.price_change,
            "change_pct": (
                (row.price_change / (row.close_price - row.price_change)) * 100
                if row.price_change is not None
                and row.close_price is not None
                and row.close_price != row.price_change
                else None
            ),
            "trade_volume": row.trade_volume,
            "trade_value": row.trade_value,
            "transaction_count": row.transaction_count,
            "industry": stock_industries.get(row.stock_id),
        }
        for row in rows
    ]
    ranked_with_change = [row for row in ranked if row["change_pct"] is not None]
    top_gainers = sorted(ranked_with_change, key=lambda row: row["change_pct"], reverse=True)[:limit]
    top_losers = sorted(ranked_with_change, key=lambda row: row["change_pct"])[:limit]
    value_leaders = sorted(
        [row for row in ranked if row["trade_value"] is not None],
        key=lambda row: row["trade_value"] or 0,
        reverse=True,
    )[:limit]

    advance_count = sum(1 for row in rows if (row.price_change or 0) > 0)
    decline_count = sum(1 for row in rows if (row.price_change or 0) < 0)
    unchanged_count = sum(1 for row in rows if (row.price_change or 0) == 0)
    total_trade_value = sum(row.trade_value or 0 for row in rows) or None
    total_count = len(rows)
    average_change_pct = (
        sum(row["change_pct"] for row in ranked_with_change) / len(ranked_with_change)
        if ranked_with_change
        else None
    )
    positive_ratio = advance_count / len(ranked_with_change) if ranked_with_change else None
    advance_decline_ratio = advance_count / decline_count if decline_count else None
    top_value_sum = sum(row["trade_value"] or 0 for row in value_leaders)
    top_value_share = (
        top_value_sum / total_trade_value
        if total_trade_value and value_leaders
        else None
    )
    breadth = {
        "advance_count": advance_count,
        "decline_count": decline_count,
        "unchanged_count": unchanged_count,
        "total_count": total_count,
        "trade_value": total_trade_value,
        "average_change_pct": average_change_pct,
        "positive_ratio": positive_ratio,
        "advance_decline_ratio": advance_decline_ratio,
        "top_value_share": top_value_share,
    }
    distribution = {
        "limit_up_count": sum(
            1 for row in ranked_with_change if (row["change_pct"] or 0) >= 9.5
        ),
        "strong_up_count": sum(
            1 for row in ranked_with_change if 5 <= (row["change_pct"] or 0) < 9.5
        ),
        "mild_up_count": sum(
            1 for row in ranked_with_change if 0 < (row["change_pct"] or 0) < 5
        ),
        "flat_count": unchanged_count,
        "mild_down_count": sum(
            1 for row in ranked_with_change if -5 < (row["change_pct"] or 0) < 0
        ),
        "strong_down_count": sum(
            1 for row in ranked_with_change if -9.5 < (row["change_pct"] or 0) <= -5
        ),
        "limit_down_count": sum(
            1 for row in ranked_with_change if (row["change_pct"] or 0) <= -9.5
        ),
    }
    industry_groups: dict[str, list[dict[str, Any]]] = {}
    for row in ranked_with_change:
        industry = normalize_tw_industry_label(row.get("industry"), fallback="未分類")
        industry_groups.setdefault(industry, []).append(row)

    industry_summary = []
    for industry, group_rows in industry_groups.items():
        changes = [
            row["change_pct"]
            for row in group_rows
            if isinstance(row.get("change_pct"), (int, float))
        ]
        if not changes:
            continue
        trade_value = sum(row.get("trade_value") or 0 for row in group_rows) or None
        top_row = max(
            group_rows,
            key=lambda row: (
                row.get("trade_value") or 0,
                row.get("change_pct") or 0,
            ),
        )
        industry_summary.append(
            {
                "industry": industry,
                "count": len(group_rows),
                "advance_count": sum(1 for value in changes if value > 0),
                "decline_count": sum(1 for value in changes if value < 0),
                "average_change_pct": sum(changes) / len(changes),
                "trade_value": trade_value,
                "top_stock_id": top_row.get("stock_id"),
                "top_stock_name": top_row.get("stock_name"),
            }
        )
    top_industries = sorted(
        [row for row in industry_summary if row["industry"] != "未分類" and row["count"] >= 2],
        key=lambda row: (
            row["average_change_pct"],
            row.get("trade_value") or 0,
        ),
        reverse=True,
    )[:6]
    weak_industries = sorted(
        [row for row in industry_summary if row["industry"] != "未分類" and row["count"] >= 2],
        key=lambda row: (
            row["average_change_pct"],
            -(row.get("trade_value") or 0),
        ),
    )[:6]

    if not ranked_with_change:
        missing.append("market_daily_price.change_pct")

    warnings.extend(
        [
            (
                "This overview includes bounded Taiwan index intraday data, but stock breadth still uses latest local daily rows."
                if include_intraday
                else "This overview uses the latest local daily market rows and does not fetch live quotes."
            )
        ]
    )

    envelope = {
        "kind": "market_overview",
        "generated_at": _now(),
        "as_of": latest_trade_date.isoformat(),
        "scope": {},
        "data": {
            "latest_trade_date": latest_trade_date.isoformat(),
            "breadth": breadth,
            "distribution": distribution,
            "top_gainers": top_gainers,
            "top_losers": top_losers,
            "value_leaders": value_leaders,
            "top_industries": top_industries,
            "weak_industries": weak_industries,
            "index_intraday": index_intraday,
            "slots": _build_tw_market_slots(
                as_of=latest_trade_date.isoformat(),
                payload_level=payload_level,
                breadth=breadth,
                distribution=distribution,
                industry_rows=[*top_industries, *weak_industries],
                index_intraday=index_intraday,
                missing=missing,
                warnings=warnings,
            ),
        },
        "missing": missing,
        "warnings": warnings,
        "source_refs": source_refs,
    }
    return _with_evidence_passport(
        envelope,
        freshness={
            "is_current": not missing,
            "missing": missing,
            "warnings": envelope["warnings"],
        },
    )


def read_tw_index_context(
    db: Session,
    index_id: str,
    *,
    bars: int = 120,
    include_intraday: bool = False,
    analysis_horizon: str = "swing",
    market_data_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_index_id = index_id.strip().upper()
    missing: list[str] = []
    warnings: list[str] = [
        "Taiwan index context uses market index evidence, not stock_master or individual stock daily tables.",
    ]
    charts: dict[str, Any] = {}
    technical_reports: dict[str, Any] = {}
    chart_bars = _bounded_int_param(
        market_data_params,
        ("daily_bars", "bars"),
        default=bars,
        minimum=20,
        maximum=500,
    )

    for timeframe in ("daily", "weekly", "monthly"):
        try:
            chart = get_market_index_ohlc_chart_data(
                index_id=normalized_index_id,
                timeframe=timeframe,
                bars=max(chart_bars, 1),
                db=db,
            )
        except ValueError:
            raise
        except Exception as exc:
            warnings.append(f"{timeframe.title()} index chart unavailable: {exc}")
            missing.append(f"market_index_ohlc.{timeframe}")
            continue

        serialized = _serialized_chart(chart)
        charts[timeframe] = serialized
        points = _normalize_technical_points(serialized.get("points", []))
        technical_reports[timeframe] = _technical_report_from_points(
            points=points,
            timeframe=timeframe,
            asset_label=normalized_index_id,
        )
        if not points:
            missing.append(f"market_index_ohlc.{timeframe}")
        backfill = chart.get("backfill") if isinstance(chart.get("backfill"), dict) else {}
        if backfill.get("status") == "error":
            warnings.append(str(backfill.get("message") or "Index daily stat refresh failed."))

    intraday: dict[str, Any] | None = None
    normalized_horizon = normalize_analysis_horizon(analysis_horizon)
    if include_intraday or normalized_horizon == "intraday":
        try:
            intraday = get_market_index_intraday(normalized_index_id)
            intraday_points = _normalize_technical_points(intraday.get("points", []))
            technical_reports["today"] = _technical_report_from_points(
                points=intraday_points,
                timeframe="today",
                asset_label=normalized_index_id,
            )
            if not intraday_points:
                missing.append("market_index_intraday")
        except Exception as exc:
            warnings.append(f"Index intraday unavailable: {exc}")
            missing.append("market_index_intraday")
    elif normalized_horizon == "intraday":
        warnings.append(
            "Intraday analysis horizon was requested without live intraday access; daily evidence is used as fallback context."
        )

    summary_payload: dict[str, Any] = {}
    index_snapshot: dict[str, Any] | None = None
    try:
        summary_payload = get_market_index_summary(db, force_refresh=False)
        for item in summary_payload.get("indices", []):
            if not isinstance(item, dict):
                continue
            if str(item.get("index_id") or item.get("stock_id") or "").upper() == normalized_index_id:
                index_snapshot = {key: _json_value(value) for key, value in item.items()}
                break
        if index_snapshot is None:
            missing.append("market_index_summary")
    except Exception as exc:
        warnings.append(f"Index summary unavailable: {exc}")
        missing.append("market_index_summary")

    market_chip: dict[str, Any] | None = None
    try:
        chip_row = get_latest_market_chip_daily(db, index_id=normalized_index_id)
        market_chip = _json_dict(market_chip_daily_to_dict(chip_row)) if chip_row is not None else None
        if market_chip is None:
            missing.append("market_chip_daily")
    except Exception as exc:
        warnings.append(f"Market chip context unavailable: {exc}")
        missing.append("market_chip_daily")

    contributions: dict[str, Any] | None = None
    try:
        contributions_payload = get_market_index_contributions(normalized_index_id, limit=10)
        contributions = {
            key: _json_value(value)
            for key, value in contributions_payload.items()
            if key not in {"positive", "negative"}
        }
        contributions["positive"] = [
            {key: _json_value(value) for key, value in item.items()}
            for item in contributions_payload.get("positive", [])
            if isinstance(item, dict)
        ]
        contributions["negative"] = [
            {key: _json_value(value) for key, value in item.items()}
            for item in contributions_payload.get("negative", [])
            if isinstance(item, dict)
        ]
    except Exception as exc:
        warnings.append(f"Index contribution context unavailable: {exc}")

    technical_analysis = _technical_analysis_summary(
        technical_reports=technical_reports,
        requested_horizon=analysis_horizon,
    )
    intraday_latest_time = (_latest_intraday_point(intraday) or {}).get("time")
    as_of = _latest_date_string(
        [
            (charts.get("daily") or {}).get("to_date"),
            (index_snapshot or {}).get("time"),
            (index_snapshot or {}).get("as_of"),
            (market_chip or {}).get("trade_date"),
            intraday_latest_time,
        ]
    )
    source_refs = [
        {"type": "table", "name": "market_index_daily_stat"},
        {"type": "table", "name": "market_chip_daily"},
        {"type": "derived", "name": "app.market.indices"},
        {"type": "external_or_cache", "name": "yahoo_finance_chart"},
    ]
    if include_intraday or intraday is not None:
        _append_source_ref_once(source_refs, {"type": "external_or_cache", "name": "market_index_intraday"})

    envelope = {
        "kind": "tw_index_context",
        "generated_at": _now(),
        "as_of": as_of,
        "scope": {"index_id": normalized_index_id},
        "data": {
            "index": index_snapshot,
            "charts": charts,
            "intraday": intraday,
            "market_chip": market_chip,
            "contributions": contributions,
            "technical_reports": technical_reports,
            "analysis": technical_analysis,
            "compact": _build_tw_index_compact_evidence(
                index_id=normalized_index_id,
                as_of=as_of,
                index_snapshot=index_snapshot,
                intraday=intraday,
                include_intraday=include_intraday or normalized_horizon == "intraday",
                market_data_params=market_data_params,
                market_chip=market_chip,
                contributions=contributions,
                technical_reports=technical_reports,
                technical_analysis=technical_analysis,
                missing=missing,
                warnings=warnings,
                source_refs=source_refs,
            ),
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


def read_tw_futures_context(
    db: Session,
    symbol: str,
    *,
    bars: int = 120,
    include_intraday: bool = False,
    analysis_horizon: str = "swing",
) -> dict[str, Any]:
    normalized_symbol = normalize_taiwan_futures_symbols([symbol])[0]
    missing: list[str] = []
    warnings: list[str] = [
        "Taiwan futures context uses TAIFEX futures quote and bar tables, not stock_master or stock daily tables.",
    ]

    quote_rows = get_latest_taiwan_futures_quotes(db, symbols=[normalized_symbol], refresh=False)
    quote_dicts = [_json_dict(taiwan_futures_quote_to_dict(row)) for row in quote_rows]
    latest_quote = quote_dicts[0] if quote_dicts else None
    if latest_quote is None:
        missing.append("taiwan_futures_quote_snapshot")

    daily_rows = list_taiwan_futures_daily_bars(
        db=db,
        symbol=normalized_symbol,
        limit=max(bars, 1),
        active_only=True,
    )
    daily_dicts = [
        _json_dict(taiwan_futures_daily_bar_to_dict(row))
        for row in daily_rows
    ]
    daily_points = _normalize_technical_points([row for row in daily_dicts if isinstance(row, dict)])
    if not daily_points:
        missing.append("taiwan_futures_daily_bar")

    normalized_horizon = normalize_analysis_horizon(analysis_horizon)
    intraday_dicts: list[dict[str, Any]] = []
    intraday_points: list[dict[str, Any]] = []
    if include_intraday or normalized_horizon == "intraday":
        intraday_rows = list_taiwan_futures_intraday_bars(
            db=db,
            symbol=normalized_symbol,
            limit=390,
        )
        intraday_dicts = [
            _json_dict(taiwan_futures_intraday_bar_to_dict(row))
            for row in intraday_rows
        ]
        intraday_points = _normalize_technical_points(
            [row for row in intraday_dicts if isinstance(row, dict)]
        )
        if not intraday_points:
            missing.append("taiwan_futures_intraday_bar")
    elif normalized_horizon == "intraday":
        warnings.append(
            "Intraday analysis horizon was requested without live intraday access; daily futures evidence is used as fallback context."
        )

    technical_reports: dict[str, Any] = {
        "daily": _technical_report_from_points(
            points=daily_points,
            timeframe="daily",
            asset_label=normalized_symbol,
        ),
    }
    if intraday_points:
        technical_reports["today"] = _technical_report_from_points(
            points=intraday_points,
            timeframe="today",
            asset_label=normalized_symbol,
        )

    technical_analysis = _technical_analysis_summary(
        technical_reports=technical_reports,
        requested_horizon=analysis_horizon,
    )
    daily_chart = _chart_from_points(timeframe="daily", points=daily_points)
    intraday_chart = _chart_from_points(timeframe="today", points=intraday_points)
    as_of = _latest_date_string(
        [
            (latest_quote or {}).get("quote_time"),
            daily_chart.get("to_date"),
            intraday_chart.get("to_date"),
        ]
    )

    envelope = {
        "kind": "tw_futures_context",
        "generated_at": _now(),
        "as_of": as_of,
        "scope": {"symbol": normalized_symbol},
        "data": {
            "latest_quote": latest_quote,
            "quotes": quote_dicts,
            "daily_chart": daily_chart,
            "intraday_chart": intraday_chart if intraday_points else None,
            "daily_bars": daily_dicts,
            "intraday_bars": intraday_dicts,
            "technical_reports": technical_reports,
            "analysis": technical_analysis,
        },
        "missing": list(dict.fromkeys(missing)),
        "warnings": list(dict.fromkeys(warnings)),
        "source_refs": [
            {"type": "table", "name": "taiwan_futures_quote_snapshot"},
            {"type": "table", "name": "taiwan_futures_daily_bar"},
            {"type": "table", "name": "taiwan_futures_intraday_bar"},
            {"type": "derived", "name": "app.market.tw_futures"},
        ],
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
) -> dict[str, Any]:
    normalized_stock_id = stock_id.strip()
    missing: list[str] = []
    warnings: list[str] = []

    try:
        stock = stock_service.get_stock(db=db, stock_id=normalized_stock_id)
    except stock_service.StockNotFoundError:
        stock = None
        missing.append("stock_master")

    latest_daily = market_service.get_latest_stock_daily_price(db, normalized_stock_id)
    latest_institutional = market_service.get_latest_stock_institutional_trade(db, normalized_stock_id)
    latest_margin = market_service.get_latest_stock_margin_trade(db, normalized_stock_id)
    latest_revenue = market_service.get_latest_stock_monthly_revenue(db, normalized_stock_id)
    latest_financial = market_service.get_latest_stock_financial_metric(db, normalized_stock_id)
    shareholding = market_service.list_latest_stock_shareholding_distribution(db, normalized_stock_id)
    revenue_history = market_service.list_stock_monthly_revenue_history(
        db=db,
        stock_id=normalized_stock_id,
        limit=max(revenue_months, 1),
    )
    financial_history = market_service.list_stock_financial_metric_history(
        db=db,
        stock_id=normalized_stock_id,
        limit=max(financial_quarters, 1),
    )
    chart = market_service.list_stock_ohlc_chart_data(
        db=db,
        stock_id=normalized_stock_id,
        timeframe="daily",
        bars=max(bars, 1),
        ensure_history=False,
    )
    branch_summary = get_broker_branch_trade_summary(
        db=db,
        stock_id=normalized_stock_id,
        days=max(branch_days, 1),
        ensure_daily=False,
    )
    normalized_horizon = normalize_analysis_horizon(analysis_horizon)
    technical_reports: dict[str, Any] = {}

    for timeframe in ("daily", "weekly", "monthly"):
        try:
            technical_reports[timeframe] = build_stock_technical_report(
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
            technical_reports["today"] = build_stock_technical_report(
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
            overnight_impact = build_us_overnight_impact_report(
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
    market_calendar_status = build_taiwan_calendar_status()
    source_health = build_taiwan_source_health(
        db=db,
        stock_id=normalized_stock_id,
    )
    source_refs.append({"type": "derived", "name": "app.market.source_health"})

    quote_depth: dict[str, Any] | None = None
    quote_error: str | None = None
    if include_intraday:
        try:
            quote_depth = get_taiwan_stock_quote_depth(
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
        "generated_at": _now(),
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


def read_watchlist_context(
    db: Session,
    group_id: int,
    *,
    include_children: bool = True,
    enabled_only: bool = True,
    rank_by: str = "score",
    sort_order: str = "desc",
    limit: int = 100,
    radar_mode: str = "action",
    radar_limit: int = 12,
) -> dict[str, Any]:
    group = watchlist_service.get_group(db=db, group_id=group_id)
    ranking = ranking_service.get_watchlist_group_latest_ranking(
        db=db,
        group_id=group_id,
        include_children=include_children,
        enabled_only=enabled_only,
        rank_by=rank_by,
        sort_order=sort_order,
        limit=limit,
        use_intraday=False,
    )
    radar = radar_service.build_watchlist_radar_from_ranking(
        ranking=ranking,
        include_children=include_children,
        mode=radar_mode,
        max_results=max(1, min(int(radar_limit or 12), 200)),
    )
    radar["group_id"] = group_id
    results = ranking.get("results", [])
    missing = []
    warnings = [
        "Watchlist context and radar use local daily indicator data and do not fetch live quotes.",
    ]

    if ranking.get("no_data_count"):
        missing.append("watchlist_items_with_market_data")
    if radar.get("error_count"):
        missing.append("watchlist_radar_error_items")

    ranked_as_of = _latest_date_string([row.get("time") for row in results])
    radar_as_of = _latest_date_string(
        [item.get("time") or item.get("trade_date") for item in radar.get("results", [])]
    )

    envelope = {
        "kind": "watchlist_context",
        "generated_at": _now(),
        "as_of": ranked_as_of or radar_as_of,
        "scope": {
            "group_id": group_id,
            "group_name": group.group_name,
            "include_children": include_children,
            "enabled_only": enabled_only,
            "radar_mode": radar.get("mode") or radar_mode,
        },
        "data": {
            "ranking": ranking,
            "radar": radar,
        },
        "missing": missing,
        "warnings": warnings,
        "source_refs": [
            {"type": "table", "name": "watchlist_group"},
            {"type": "table", "name": "watchlist_item"},
            {"type": "table", "name": "market_daily_price"},
            {"type": "service", "name": "watchlist_radar"},
        ],
    }
    return _with_evidence_passport(envelope)
