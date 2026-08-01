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
    taiwan_screening,
    taiwan_stock,
    taiwan_watchlist,
    tw_cross_market,
    tw_market_chips,
)
from app.ai.market_context.common import append_source_ref_once as _append_source_ref_once
from app.ai.market_payload_contract import has_payload_value as _has_payload_value
from app.market import service as market_service
from app.market.broker_branch import get_broker_branch_trade_summary
from app.market.calendar_status import build_market_calendar_status, build_taiwan_calendar_status
from app.market.live_snapshot import market_status_from_session
from app.market.intraday import get_market_intraday_history
from app.market.quote_depth import get_taiwan_stock_quote_depth
from app.market.tw_disposition import get_taiwan_disposition_status
from app.market.tw_corporate_events import (
    get_taiwan_stock_event_history,
    get_taiwan_stock_event_summary,
    list_taiwan_corporate_events,
)
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
from app.market.taiwan_market_state import read_taiwan_market_volume_state
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


def _health_dimensions(
    envelope: dict[str, Any],
    *,
    market: str,
) -> dict[str, Any]:
    calendar_market = market.lower()
    calendar_status: dict[str, Any] = {}
    if calendar_market in {"tw", "us", "jp", "kr"}:
        calendar_payload = build_market_calendar_status(
            market=calendar_market,
            now=_now(),
        )
        candidate = (calendar_payload.get("markets") or {}).get(calendar_market)
        calendar_status = candidate if isinstance(candidate, dict) else {}
    market_status = (
        market_status_from_session(calendar_status)
        if calendar_status
        else "not_applicable"
    )
    database_status = str(
        (envelope.get("evidence_passport") or {}).get("data_freshness")
        or envelope.get("status")
        or "unknown"
    )
    missing = list(envelope.get("missing") or [])
    return {
        "operational_health": {
            "status": "available",
            "as_of": envelope.get("generated_at") or envelope.get("as_of"),
            "meaning": "The freshness reader completed; individual provider health is reported separately.",
        },
        "live_feed_health": {
            "status": market_status
            if market_status in {"closed", "closed_holiday", "latest_session_close"}
            else "not_observed",
            "market_status": market_status,
            "as_of": calendar_status.get("checked_at"),
            "holiday_name": calendar_status.get("holiday_name"),
            "meaning": "Live feed health is independent from local database freshness.",
        },
        "database_freshness": {
            "status": database_status,
            "as_of": envelope.get("as_of"),
        },
        "coverage_completeness": {
            "status": "complete" if not missing else "partial",
            "missing_count": len(missing),
            "missing": missing,
            "as_of": envelope.get("as_of"),
        },
    }


def _attach_health_dimensions(
    envelope: dict[str, Any],
    *,
    market: str,
) -> dict[str, Any]:
    dimensions = _health_dimensions(envelope, market=market)
    as_of_by_domain = {
        domain: dimension.get("as_of")
        for domain, dimension in dimensions.items()
        if isinstance(dimension, dict)
    }
    envelope["health_dimensions"] = dimensions
    envelope["as_of_by_domain"] = as_of_by_domain
    data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
    compact = data.get("compact") if isinstance(data.get("compact"), dict) else {}
    if compact:
        compact["health_dimensions"] = dimensions
        compact["as_of_by_domain"] = as_of_by_domain
    return envelope


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
        envelope = taiwan_freshness.read_data_freshness(
            db=db,
            stock_id=stock_id,
            now=_now,
        )
        return _attach_health_dimensions(envelope, market="TW")
    if normalized_market != "ALL":
        envelope = regional_freshness.read_regional_data_freshness(
            db,
            market=normalized_market,
            symbol=stock_id,
            now=_now,
        )
        return _attach_health_dimensions(envelope, market=normalized_market)

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
                "health_dimensions": {
                    market_key: item.get("health_dimensions") or {}
                    for market_key, item in markets.items()
                },
                "as_of_by_domain": {
                    market_key: item.get("as_of_by_domain") or {}
                    for market_key, item in markets.items()
                },
            },
        },
        "missing": missing,
        "warnings": warnings,
        "source_refs": source_refs,
        "health_dimensions": {
            market_key: item.get("health_dimensions") or {}
            for market_key, item in markets.items()
        },
        "as_of_by_domain": {
            market_key: {
                domain: dimension.get("as_of")
                for domain, dimension in (item.get("health_dimensions") or {}).items()
                if isinstance(dimension, dict)
            }
            for market_key, item in markets.items()
        },
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
    params = (
        dict(market_data_params)
        if isinstance(market_data_params, dict)
        else {}
    )
    requested_capabilities = {
        str(value).strip()
        for value in params.get("requested_capabilities") or []
        if str(value).strip()
    }
    screening_requested = bool(
        requested_capabilities & taiwan_screening.SCREENING_CAPABILITIES
    )
    screening_context = (
        taiwan_screening.read_tw_screening_context(
            db,
            market_data_params=params,
            now=_now,
        )
        if screening_requested
        else None
    )
    screening_only_capabilities = (
        taiwan_screening.SCREENING_CAPABILITIES - {"market.sectors"}
    )
    non_screening_capabilities = requested_capabilities - {
        "target.identity",
        "data.freshness",
        *screening_only_capabilities,
    }
    if screening_context is not None and not non_screening_capabilities:
        return screening_context

    market_context = taiwan_market.read_market_overview(
        db=db,
        limit=limit,
        include_intraday=include_intraday,
        market_data_params=params,
        dependencies=taiwan_market.TaiwanMarketDependencies(
            market_service=market_service,
            get_market_index_intraday=get_market_index_intraday,
            get_market_index_summary=get_market_index_summary,
            read_cross_market_context=tw_cross_market.read_tw_cross_market_context,
            read_market_chips_context=tw_market_chips.read_tw_market_chips_context,
            read_market_volume_state=read_taiwan_market_volume_state,
            build_taiwan_source_health=build_taiwan_source_health,
            now=_now,
            get_market_index_contributions=get_market_index_contributions,
            list_taiwan_corporate_events=list_taiwan_corporate_events,
        ),
    )
    if screening_context is None:
        return market_context
    return taiwan_screening.merge_tw_screening_context(
        market_context,
        screening_context,
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
            get_taiwan_disposition_status=get_taiwan_disposition_status,
            get_taiwan_stock_event_summary=get_taiwan_stock_event_summary,
            get_taiwan_stock_event_history=get_taiwan_stock_event_history,
            now=_now,
        ),
    )


def read_stock_quote_context(
    db: Session,
    stock_id: str,
    *,
    market_data_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return taiwan_stock.read_stock_quote_context(
        db=db,
        stock_id=stock_id,
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
            get_taiwan_disposition_status=get_taiwan_disposition_status,
            get_taiwan_stock_event_summary=get_taiwan_stock_event_summary,
            get_taiwan_stock_event_history=get_taiwan_stock_event_history,
            now=_now,
        ),
    )


def read_stock_event_context(
    db: Session,
    stock_id: str,
    *,
    market_data_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return taiwan_stock.read_stock_event_context(
        db=db,
        stock_id=stock_id,
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
            get_taiwan_disposition_status=get_taiwan_disposition_status,
            get_taiwan_stock_event_summary=get_taiwan_stock_event_summary,
            get_taiwan_stock_event_history=get_taiwan_stock_event_history,
            now=_now,
        ),
    )


def read_stock_broker_branch_context(
    db: Session,
    stock_id: str,
    *,
    branch_days: int = 5,
    market_data_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return taiwan_stock.read_stock_broker_branch_context(
        db=db,
        stock_id=stock_id,
        branch_days=branch_days,
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
            get_taiwan_disposition_status=get_taiwan_disposition_status,
            get_taiwan_stock_event_summary=get_taiwan_stock_event_summary,
            get_taiwan_stock_event_history=get_taiwan_stock_event_history,
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
