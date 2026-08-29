from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.ai import agentic_tools, query_plan
from app.ai.ask_execution import _us_market_data_params
from app.ai.market_context.us_context import USContextDependencies, read_us_stock_context
from app.ai.schemas import AiAskRequest


def _intraday_payload() -> dict:
    return {
        "stock_id": "AAPL",
        "symbol": "AAPL",
        "source": "yahoo_finance_chart",
        "interval": "5m",
        "source_interval": "1m",
        "effective_interval": "5m",
        "session_scope": "all",
        "session_phase": "after_hours",
        "point_count": 1,
        "points": [
            {
                "time": "2026-08-21T16:05:00-04:00",
                "session": "after_hours",
                "price": 225.0,
                "volume": None,
                "volume_status": "provider_unavailable",
            }
        ],
        "source_status": {"status": "ok", "is_live_window": False},
        "warnings": [],
    }


def test_intraday_only_context_skips_unselected_research_resources() -> None:
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    service = MagicMock()
    service.get_us_intraday_trend.return_value = _intraday_payload()
    service.build_us_source_health.return_value = {"entries": [], "summary": {}}
    latest_profile = MagicMock()
    gap_scan = MagicMock(
        return_value={"missing": ["us_intraday_trend"], "warnings": []}
    )
    dependencies = USContextDependencies(
        us_market_service=service,
        latest_profile=latest_profile,
        scan_us_stock_gaps=gap_scan,
        now=lambda: datetime(2026, 8, 23, 4, 0, tzinfo=timezone.utc),
    )

    with patch(
        "app.ai.market_context.us_context.build_us_calendar_status",
        return_value={
            "phase": "post_close",
            "previous_trading_day": "2026-08-21",
        },
    ):
        context = read_us_stock_context(
            db,
            symbol="AAPL",
            market_data_params={
                "include_intraday": True,
                "interval": "5m",
                "session_scope": "all",
                "requested_capabilities": [
                    "target.identity",
                    "intraday.bars",
                    "data.freshness",
                ],
            },
            dependencies=dependencies,
        )

    service.get_us_intraday_trend.assert_called_once_with(
        symbol="AAPL",
        session_scope="all",
        interval="5m",
        db=db,
        persist_history=False,
    )
    gap_scan.assert_called_once_with(
        db,
        "AAPL",
        requested_capabilities=(
            "target.identity",
            "intraday.bars",
            "data.freshness",
        ),
    )
    service.list_us_daily_prices.assert_not_called()
    service.list_us_ohlc_chart_data.assert_not_called()
    service.get_us_sec_fundamental_summary.assert_not_called()
    service.get_us_sec_financial_contract.assert_not_called()
    service.get_us_sec_insider_transactions.assert_not_called()
    service.get_us_sec_institutional_holdings.assert_not_called()
    service.list_us_corporate_actions.assert_not_called()
    service.list_us_short_volumes.assert_not_called()
    service.build_us_market_research.assert_not_called()
    latest_profile.assert_not_called()
    assert context["data"]["compact"]["intraday_bars"]["series"]["1m"][
        "effective_interval"
    ] == "5m"


def test_intraday_gap_scan_does_not_query_unselected_datasets() -> None:
    db = MagicMock()
    with (
        patch.object(agentic_tools, "USDailyOhlcvPlatform") as daily_platform,
        patch.object(agentic_tools, "_latest_profile") as latest_profile,
        patch.object(agentic_tools, "_sec_metric_count") as sec_count,
        patch.object(agentic_tools, "_corporate_action_summary") as actions,
    ):
        result = agentic_tools.scan_us_stock_gaps(
            db,
            "AAPL",
            requested_capabilities=("intraday.bars",),
        )

    daily_platform.assert_not_called()
    latest_profile.assert_not_called()
    sec_count.assert_not_called()
    actions.assert_not_called()
    assert result["required_capabilities"] == ["us_intraday_trend"]
    assert result["missing"] == ["us_intraday_trend"]


def test_us_selection_daily_limit_is_forwarded_as_reader_bound() -> None:
    payload = AiAskRequest(
        question="讀取 AAPL 最近 260 根日 K",
        target={"type": "us_stock", "id": "AAPL"},
        realtime_policy="cache_only",
        selection={
            "include": ["daily.ohlcv"],
            "limits": {"daily.ohlcv": 260},
        },
    )
    plan = query_plan.build_query_plan(
        payload=payload,
        scope_type="us_stock",
        question_intent="technical",
        effective_mode="data_only",
        target_market="US",
    )
    params = _us_market_data_params(
        payload,
        policy={"can_external_fetch": False, "query_plan": plan.as_dict()},
    )

    assert params["bars"] == 260
    assert params["external_fetch_allowed"] is False
    assert params["requested_capabilities"] == list(plan.selected_capabilities)


@pytest.mark.parametrize("symbol", ["AAPL", "TSM"])
def test_us_daily_context_uses_forwarded_selection_bound(symbol: str) -> None:
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    service = MagicMock()
    service.read_us_daily_ohlcv_chart.return_value = {"point_count": 0}
    service.build_us_source_health.return_value = {"entries": [], "summary": {}}
    gap_scan = MagicMock(return_value={"missing": [], "warnings": []})
    dependencies = USContextDependencies(
        us_market_service=service,
        latest_profile=MagicMock(),
        scan_us_stock_gaps=gap_scan,
        now=lambda: datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc),
    )
    platform_result = MagicMock(
        projection={
            "points": [],
            "selected_provider": None,
            "latest_trade_date": None,
            "limitations": [],
        },
        postcondition_satisfied=False,
    )

    with (
        patch(
            "app.ai.market_context.us_context.USDailyOhlcvPlatform"
        ) as platform,
        patch(
            "app.ai.market_context.us_context.build_us_calendar_status",
            return_value={
                "phase": "post_close",
                "previous_trading_day": "2026-08-28",
            },
        ),
    ):
        platform.return_value.read.return_value = platform_result
        read_us_stock_context(
            db,
            symbol=symbol,
            market_data_params={
                "bars": 260,
                "requested_capabilities": [
                    "target.identity",
                    "daily.ohlcv",
                    "data.freshness",
                ],
            },
            dependencies=dependencies,
        )

    platform.return_value.read.assert_called_once_with(
        symbol=symbol,
        bars=260,
        now=datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc),
        to_date=None,
    )
    service.read_us_daily_ohlcv_chart.assert_called_once_with(
        db=db,
        symbol=symbol,
        timeframe="daily",
        bars=260,
        to_date=None,
    )
