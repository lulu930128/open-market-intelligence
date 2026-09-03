from __future__ import annotations

from conftest import REPO_ROOT


def _source(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_taiwan_ai_consumers_do_not_call_legacy_k_line_owners() -> None:
    sources = "\n".join(
        _source(path)
        for path in (
            "backend/app/ai/market_context/taiwan_stock.py",
            "backend/app/ai/market_context/taiwan_index.py",
            "backend/app/ai/market_context/taiwan_market.py",
            "backend/app/ai/tools.py",
        )
    )

    for forbidden in (
        "get_market_intraday_history",
        "get_market_index_intraday",
        "get_market_index_ohlc_chart_data",
        "read_taiwan_index_intraday_series",
    ):
        assert forbidden not in sources


def test_technical_report_does_not_reconstruct_bar_or_technical_truth() -> None:
    source = _source("backend/app/market/technical_report.py")

    for forbidden in (
        "get_intraday_trend",
        "read_taiwan_session_close",
        "project_taiwan_session_close",
        "calculate_active_indicator_points",
        "list_stock_ohlc_chart_data",
    ):
        assert forbidden not in source

    assert "TaiwanBarService" in source
    assert "TaiwanTechnicalService" in source


def test_taiwan_chart_quote_side_uses_canonical_public_quote_owner() -> None:
    source = _source("backend/app/market/tw_chart_service.py")

    assert "read_taiwan_public_quote_projection" in source
    assert "project_taiwan_index_quote_side" in source
    assert "get_market_index_summary" in source
    assert "get_intraday_trend" not in source


def test_taiwan_mcp_tools_remain_backend_http_relays() -> None:
    source = _source("agents/omi_mcp_server/server.py")

    assert '"omi.read_taiwan_bars"' in source
    assert '"omi.read_taiwan_technical_series"' in source
    assert '"omi.read_taiwan_chart"' in source
    assert "/api/market/bars/" in source
    assert "/api/market/technical/" in source
    assert "/api/market/chart/" in source
    for forbidden in (
        "app.db",
        "app.market.providers",
        "MarketIntradayBar",
        "MarketDailyPrice",
    ):
        assert forbidden not in source


def test_taiwan_unified_routers_do_not_own_aggregation_or_formulas() -> None:
    source = "\n".join(
        (
            _source("backend/app/routers/tw_market_bars.py"),
            _source("backend/app/routers/tw_market_technical.py"),
        )
    )

    for forbidden in (
        "aggregate_taiwan_bars",
        "calculate_canonical_indicator_points",
        "MarketIntradayBar",
        "MarketDailyPrice",
    ):
        assert forbidden not in source
