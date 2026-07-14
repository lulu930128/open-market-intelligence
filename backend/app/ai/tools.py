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
from app.ai.market_context import (
    taiwan_freshness,
    taiwan_futures,
    taiwan_index,
    taiwan_market,
    taiwan_projection,
    taiwan_stock,
)
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




def list_ai_tools(*, include_internal: bool = False) -> dict[str, Any]:
    return tool_catalog.list_ai_tools(include_internal=include_internal)


def read_data_freshness(db: Session, stock_id: str | None = None) -> dict[str, Any]:
    return taiwan_freshness.read_data_freshness(
        db=db,
        stock_id=stock_id,
        now=_now,
    )


def read_market_overview(
    db: Session,
    limit: int = 10,
    *,
    include_intraday: bool = False,
    market_data_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return taiwan_market.read_market_overview(
        db=db,
        limit=limit,
        include_intraday=include_intraday,
        market_data_params=market_data_params,
        dependencies=taiwan_market.TaiwanMarketDependencies(
            market_service=market_service,
            get_market_index_intraday=get_market_index_intraday,
            now=_now,
        ),
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
    return taiwan_index.read_tw_index_context(
        db=db,
        index_id=index_id,
        bars=bars,
        include_intraday=include_intraday,
        analysis_horizon=analysis_horizon,
        market_data_params=market_data_params,
        dependencies=taiwan_index.TaiwanIndexDependencies(
            get_latest_market_chip_daily=get_latest_market_chip_daily,
            get_market_index_contributions=get_market_index_contributions,
            get_market_index_intraday=get_market_index_intraday,
            get_market_index_ohlc_chart_data=get_market_index_ohlc_chart_data,
            get_market_index_summary=get_market_index_summary,
            now=_now,
        ),
    )


def read_tw_futures_context(
    db: Session,
    symbol: str,
    *,
    bars: int = 120,
    include_intraday: bool = False,
    analysis_horizon: str = "swing",
) -> dict[str, Any]:
    return taiwan_futures.read_tw_futures_context(
        db=db,
        symbol=symbol,
        bars=bars,
        include_intraday=include_intraday,
        analysis_horizon=analysis_horizon,
        dependencies=taiwan_futures.TaiwanFuturesDependencies(
            get_latest_taiwan_futures_quotes=get_latest_taiwan_futures_quotes,
            list_taiwan_futures_daily_bars=list_taiwan_futures_daily_bars,
            list_taiwan_futures_intraday_bars=list_taiwan_futures_intraday_bars,
            now=_now,
        ),
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
    return taiwan_stock.read_stock_context(
        db=db,
        stock_id=stock_id,
        branch_days=branch_days,
        bars=bars,
        revenue_months=revenue_months,
        financial_quarters=financial_quarters,
        include_intraday=include_intraday,
        analysis_horizon=analysis_horizon,
        market_data_params=market_data_params,
        dependencies=taiwan_stock.TaiwanStockDependencies(
            market_service=market_service,
            stock_service=stock_service,
            build_stock_technical_report=build_stock_technical_report,
            build_taiwan_calendar_status=build_taiwan_calendar_status,
            build_taiwan_source_health=build_taiwan_source_health,
            build_us_overnight_impact_report=build_us_overnight_impact_report,
            get_broker_branch_trade_summary=get_broker_branch_trade_summary,
            get_market_intraday_history=get_market_intraday_history,
            get_taiwan_stock_quote_depth=get_taiwan_stock_quote_depth,
            now=_now,
        ),
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
