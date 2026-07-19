from typing import Any

from sqlalchemy.orm import Session

from app.ai import tool_catalog
from app.ai.evidence_passport import build_evidence_passport
from app.ai.market_context import (
    regional_freshness,
    taiwan_freshness,
    taiwan_futures,
    taiwan_index,
    taiwan_market,
    taiwan_projection,
    taiwan_stock,
    taiwan_watchlist,
    tw_cross_market,
    tw_market_chips,
)
from app.ai.market_context.common import append_source_ref_once as _append_source_ref_once
from app.ai.market_payload_contract import has_payload_value as _has_payload_value
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
from app.market.market_chips import get_latest_market_chip_daily, list_market_chip_daily
from app.market.overnight_impact import build_us_overnight_impact_report
from app.market.source_health import build_taiwan_source_health
from app.market.tw_futures import (
    get_latest_taiwan_futures_quotes,
    list_taiwan_futures_daily_bars,
    list_taiwan_futures_intraday_bars,
)
from app.market.tw_derivatives import build_taiwan_derivatives_summary
from app.stocks import service as stock_service
from app.watchlists import radar_service, ranking_service
from app.watchlists import service as watchlist_service


_now = taiwan_projection._now

def list_ai_tools(*, include_internal: bool = False) -> dict[str, Any]:
    return tool_catalog.list_ai_tools(include_internal=include_internal)


SUPPORTED_DATA_FRESHNESS_MARKETS = {
    "TW",
    *regional_freshness.SUPPORTED_REGIONAL_FRESHNESS_MARKETS,
    "ALL",
}


def read_data_freshness(
    db: Session,
    stock_id: str | None = None,
    *,
    market: str = "TW",
) -> dict[str, Any]:
    normalized_market = str(market or "TW").strip().upper()
    if normalized_market not in SUPPORTED_DATA_FRESHNESS_MARKETS:
        raise ValueError(f"Unsupported data freshness market: {market}")
    if normalized_market == "TW":
        return taiwan_freshness.read_data_freshness(
            db=db,
            stock_id=stock_id,
            now=_now,
        )
    if normalized_market != "ALL":
        return regional_freshness.read_regional_data_freshness(
            db,
            market=normalized_market,
            symbol=stock_id,
            now=_now,
        )

    markets = {
        market_key: read_data_freshness(db, market=market_key)
        for market_key in ("TW", "US", "JP", "KR", "CRYPTO")
    }
    missing = [
        f"{market_key}:{item}"
        for market_key, envelope in markets.items()
        for item in envelope.get("missing") or []
    ]
    warnings = [
        f"{market_key}: {warning}"
        for market_key, envelope in markets.items()
        for warning in envelope.get("warnings") or []
    ]
    current_by_market = {
        market_key: (envelope.get("evidence_passport") or {}).get("data_freshness")
        for market_key, envelope in markets.items()
    }
    overall_freshness = (
        "missing"
        if "missing" in current_by_market.values()
        else "stale"
        if "stale" in current_by_market.values()
        else "partial"
        if "partial" in current_by_market.values()
        else "unknown"
        if any(status in {None, "unknown"} for status in current_by_market.values())
        else "current"
    )
    generated_at = _now()
    source_refs = [{"type": "database", "name": "open_market_intelligence.db"}]
    envelope = {
        "kind": "data_freshness",
        "generated_at": generated_at,
        "as_of": max(
            (str(item.get("as_of")) for item in markets.values() if item.get("as_of")),
            default=None,
        ),
        "scope": {"market": "ALL", "stock_id": None},
        "data": {
            "status": overall_freshness,
            "markets": {
                market_key: item.get("data") or {}
                for market_key, item in markets.items()
            },
            "compact": {
                "kind": "data_freshness_compact_evidence",
                "version": "market_compact_evidence.v1",
                "payload_level": "compact",
                "status": overall_freshness,
                "target": {
                    "type": "data_freshness",
                    "id": None,
                    "label": "All market data freshness",
                    "market": "ALL",
                },
                "resources": {"market_count": len(markets)},
                "freshness_by_domain": current_by_market,
                "slots": {
                    market_key.lower(): {
                        "status": (
                            "ready"
                            if status == "current"
                            else "stale"
                            if status == "stale"
                            else "missing"
                            if status == "missing"
                            else "partial"
                        ),
                        "capability": f"{market_key.lower()}_data_freshness",
                        "payload_ref": f"data.markets.{market_key}",
                        "payload_level": "compact",
                    }
                    for market_key, status in current_by_market.items()
                },
            },
        },
        "missing": missing,
        "warnings": warnings,
        "source_refs": source_refs,
    }
    envelope["evidence_passport"] = build_evidence_passport(
        kind="data_freshness",
        as_of=envelope["as_of"],
        source_refs=source_refs,
        missing=missing,
        warnings=warnings,
        freshness={
            "status": overall_freshness,
            "is_current": all(status == "current" for status in current_by_market.values()),
            "missing": missing,
            "warnings": warnings,
        },
    )
    return envelope


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
            get_market_index_summary=get_market_index_summary,
            read_cross_market_context=tw_cross_market.read_tw_cross_market_context,
            read_market_chips_context=tw_market_chips.read_tw_market_chips_context,
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
    market_data_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return taiwan_futures.read_tw_futures_context(
        db=db,
        symbol=symbol,
        bars=bars,
        include_intraday=include_intraday,
        analysis_horizon=analysis_horizon,
        market_data_params=market_data_params,
        dependencies=taiwan_futures.TaiwanFuturesDependencies(
            get_latest_taiwan_futures_quotes=get_latest_taiwan_futures_quotes,
            list_taiwan_futures_daily_bars=list_taiwan_futures_daily_bars,
            list_taiwan_futures_intraday_bars=list_taiwan_futures_intraday_bars,
            get_latest_market_chip_daily=get_latest_market_chip_daily,
            list_market_chip_daily=list_market_chip_daily,
            now=_now,
            build_taiwan_derivatives_summary=build_taiwan_derivatives_summary,
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
    market_data_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return taiwan_watchlist.read_watchlist_context(
        db=db,
        group_id=group_id,
        include_children=include_children,
        enabled_only=enabled_only,
        rank_by=rank_by,
        sort_order=sort_order,
        limit=limit,
        radar_mode=radar_mode,
        radar_limit=radar_limit,
        market_data_params=market_data_params,
        dependencies=taiwan_watchlist.TaiwanWatchlistDependencies(
            watchlist_service=watchlist_service,
            ranking_service=ranking_service,
            radar_service=radar_service,
            now=_now,
        ),
    )
