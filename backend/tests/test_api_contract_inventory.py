from __future__ import annotations

import ast
import unittest
from pathlib import Path

from app.main import app
from app.routers import market, tw_market_futures, tw_market_indices


EXPECTED_INDEX_CONTRACTS = {
    ("get", "/api/market/indices/summary"): (
        "get_indices_summary_api_market_indices_summary_get",
        "MarketIndexSummaryRead",
        "200",
    ),
    ("post", "/api/market/indices/summary/refresh-job"): (
        "queue_indices_summary_refresh_api_market_indices_summary_refresh_job_post",
        "JobRunRead",
        "202",
    ),
    ("post", "/api/market/indices/summary/refresh"): (
        "refresh_indices_summary_api_market_indices_summary_refresh_post",
        "MarketIndexSummaryRead",
        "200",
    ),
    ("post", "/api/market/indices/{index_id}/daily-stats/refresh"): (
        "refresh_index_daily_stats_api_market_indices__index_id__daily_stats_refresh_post",
        "MarketIndexDailyStatRefreshRead",
        "200",
    ),
    ("get", "/api/market/indices/list"): (
        "get_indices_list_api_market_indices_list_get",
        "MarketIndexListRead",
        "200",
    ),
    ("get", "/api/market/indices/{index_id}/intraday"): (
        "get_index_intraday_trend_api_market_indices__index_id__intraday_get",
        "IntradayTrendRead",
        "200",
    ),
    ("get", "/api/market/indices/{index_id}/contributions"): (
        "get_index_contributions_api_market_indices__index_id__contributions_get",
        "MarketIndexContributionRead",
        "200",
    ),
    ("get", "/api/market/indices/{index_id}/ohlc"): (
        "get_index_ohlc_chart_data_api_market_indices__index_id__ohlc_get",
        "MarketOhlcChartRead",
        "200",
    ),
    ("post", "/api/market/indices/list/refresh"): (
        "refresh_indices_list_api_market_indices_list_refresh_post",
        "MarketIndexListRead",
        "200",
    ),
    ("post", "/api/market/indices/{index_id}/contributions/refresh"): (
        "refresh_index_contributions_api_market_indices__index_id__contributions_refresh_post",
        "MarketIndexContributionRead",
        "200",
    ),
    ("post", "/api/market/indices/{index_id}/ohlc/refresh"): (
        "refresh_index_ohlc_chart_data_api_market_indices__index_id__ohlc_refresh_post",
        "MarketOhlcChartRead",
        "200",
    ),
}

EXPECTED_FUTURES_CONTRACTS = {
    ("get", "/api/market/tw-futures/products"): (
        "list_taiwan_futures_products_api_api_market_tw_futures_products_get",
        "TaiwanFuturesProductRead",
    ),
    ("post", "/api/market/tw-futures/refresh"): (
        "refresh_taiwan_futures_quotes_api_api_market_tw_futures_refresh_post",
        "TaiwanFuturesQuoteRead",
    ),
    ("get", "/api/market/tw-futures/latest"): (
        "get_latest_taiwan_futures_quotes_api_api_market_tw_futures_latest_get",
        "TaiwanFuturesQuoteRead",
    ),
    ("get", "/api/market/tw-futures/{symbol}/daily"): (
        "list_taiwan_futures_daily_bars_api_api_market_tw_futures__symbol__daily_get",
        "TaiwanFuturesDailyBarRead",
    ),
    ("post", "/api/market/tw-futures/{symbol}/daily/refresh"): (
        "refresh_taiwan_futures_daily_bars_api_api_market_tw_futures__symbol__daily_refresh_post",
        "TaiwanFuturesDailyRefreshRead",
    ),
    ("get", "/api/market/tw-futures/{symbol}/intraday"): (
        "list_taiwan_futures_intraday_bars_api_api_market_tw_futures__symbol__intraday_get",
        "TaiwanFuturesIntradayBarRead",
    ),
    ("post", "/api/market/tw-futures/{symbol}/intraday/refresh"): (
        "refresh_taiwan_futures_intraday_bars_api_api_market_tw_futures__symbol__intraday_refresh_post",
        "TaiwanFuturesIntradayBarRead",
    ),
}

EXPECTED_FUTURES_PARAMETERS = {
    ("get", "/api/market/tw-futures/products"): ((), {}),
    ("post", "/api/market/tw-futures/refresh"): (
        ("symbols", "session", "provider", "active_only"),
        {"symbols": "TXF,MXF,TMF", "session": "auto", "active_only": True},
    ),
    ("get", "/api/market/tw-futures/latest"): (
        ("symbols", "refresh", "session", "provider"),
        {"symbols": "TXF,MXF,TMF", "refresh": False, "session": "auto"},
    ),
    ("get", "/api/market/tw-futures/{symbol}/daily"): (
        (
            "symbol",
            "limit",
            "refresh",
            "lookback_days",
            "start_date",
            "end_date",
            "active_only",
        ),
        {"limit": 120, "refresh": False, "lookback_days": 45, "active_only": True},
    ),
    ("get", "/api/market/tw-futures/{symbol}/intraday"): (
        (
            "symbol",
            "interval",
            "limit",
            "refresh",
            "session",
            "provider",
            "trade_date",
        ),
        {"interval": "1m", "limit": 390, "refresh": False, "session": "auto"},
    ),
    ("post", "/api/market/tw-futures/{symbol}/intraday/refresh"): (
        ("symbol", "interval", "limit", "session", "trade_date"),
        {"interval": "1m", "limit": 390, "session": "auto"},
    ),
    ("post", "/api/market/tw-futures/{symbol}/daily/refresh"): (
        (
            "symbol",
            "limit",
            "lookback_days",
            "start_date",
            "end_date",
            "active_only",
            "force",
        ),
        {"limit": 180, "lookback_days": 45, "active_only": True, "force": False},
    ),
}

EXPECTED_DERIVATIVES_CONTRACTS = {
    ("post", "/api/market/tw-futures/derivatives/refresh"): (
        "refresh_taiwan_derivatives_api_api_market_tw_futures_derivatives_refresh_post",
        "TaiwanDerivativesRefreshRead",
        False,
    ),
    ("get", "/api/market/tw-futures/options-chain"): (
        "list_taiwan_option_chain_api_api_market_tw_futures_options_chain_get",
        "TaiwanOptionChainDailyRead",
        True,
    ),
    ("get", "/api/market/tw-futures/large-traders"): (
        "list_taiwan_large_traders_api_api_market_tw_futures_large_traders_get",
        "TaiwanDerivativesLargeTraderDailyRead",
        True,
    ),
    ("get", "/api/market/tw-futures/term-structure"): (
        "list_taiwan_term_structure_api_api_market_tw_futures_term_structure_get",
        "TaiwanFuturesTermStructureDailyRead",
        True,
    ),
}

EXPECTED_DERIVATIVES_PARAMETERS = {
    ("post", "/api/market/tw-futures/derivatives/refresh"): ((), {}),
    ("get", "/api/market/tw-futures/options-chain"): (
        (
            "trade_date",
            "product_code",
            "contract_month",
            "session",
            "option_type",
            "center_strike",
            "limit",
            "offset",
        ),
        {"product_code": "TXO", "session": "regular", "limit": 100, "offset": 0},
    ),
    ("get", "/api/market/tw-futures/large-traders"): (
        (
            "trade_date",
            "instrument_type",
            "settlement_bucket",
            "trader_type",
            "limit",
        ),
        {"limit": 100},
    ),
    ("get", "/api/market/tw-futures/term-structure"): (
        ("trade_date", "symbol", "limit"),
        {"symbol": "TXF", "limit": 12},
    ),
}

EXPECTED_SYSTEM_HEALTH_CONTRACTS = {
    ("get", "/api/system/livez"): "liveness_check_api_system_livez_get",
    ("get", "/api/system/readyz"): "readiness_check_api_system_readyz_get",
}


class APIContractInventoryTests(unittest.TestCase):
    def test_market_intraday_volume_contract_is_additive_and_explicit(self) -> None:
        schema = app.openapi()
        chart_properties = schema["components"]["schemas"][
            "MarketIntradayChartRead"
        ]["properties"]
        for field in (
            "bar_volume_sum_shares",
            "bar_volume_sum_lots",
            "bar_volume_trade_date",
            "bar_volume_latest_time",
            "bar_volume_scope",
            "session_cumulative_volume_shares",
            "session_cumulative_volume_lots",
            "session_cumulative_volume_trade_date",
            "session_cumulative_volume_source",
            "session_cumulative_volume_source_field",
            "session_cumulative_volume_event_time",
            "session_cumulative_volume_status",
            "cumulative_volume_shares",
            "cumulative_volume_lots",
            "cumulative_volume_source",
            "cumulative_volume_status",
            "unallocated_volume_shares",
            "unallocated_volume_lots",
            "volume_reconciliation",
        ):
            with self.subTest(field=field):
                self.assertIn(field, chart_properties)

        reconciliation = schema["components"]["schemas"][
            "MarketIntradayVolumeReconciliationRead"
        ]["properties"]
        for field in (
            "status",
            "trade_date",
            "exchange_cumulative_shares",
            "bar_volume_sum_shares",
            "difference_shares",
            "difference_lots",
            "difference_pct",
            "exchange_event_time",
            "bar_latest_time",
            "time_skew_seconds",
            "reason",
        ):
            with self.subTest(field=field):
                self.assertIn(field, reconciliation)

    def test_openapi_operation_inventory_remains_stable(self) -> None:
        schema = app.openapi()
        methods = {"get", "post", "put", "patch", "delete"}
        operations = [
            (method, path)
            for path, path_item in schema["paths"].items()
            for method in path_item
            if method in methods
        ]

        self.assertEqual(len(operations), 417)
        self.assertEqual(sum(1 for _, path in operations if path.startswith("/api/")), 416)
        self.assertIn(("get", "/api/market-data/eod-coverage"), operations)
        self.assertIn(("post", "/api/market-data/eod-coverage/reconcile"), operations)
        self.assertIn(
            ("post", "/api/market/daily/{stock_id}/refresh-official"),
            operations,
        )
        self.assertIn(
            ("get", "/api/market/quotes/{stock_id}/public-last-trade"),
            operations,
        )
        self.assertIn(
            (
                "post",
                "/api/market/quotes/{stock_id}/public-last-trade/refresh",
            ),
            operations,
        )
        self.assertIn(
            ("post", "/api/market/quote-depth/{stock_id}/refresh"),
            operations,
        )
        self.assertIn(
            ("post", "/api/market/intraday/{stock_id}/history/refresh"),
            operations,
        )
        self.assertIn(
            ("post", "/api/market/overnight-impact/{stock_id}/refresh"),
            operations,
        )
        self.assertIn(
            ("post", "/api/market/broker-branches/{stock_id}/daily/refresh"),
            operations,
        )
        self.assertIn(
            (
                "post",
                "/api/market/institutional/{stock_id}/holding-ratios/refresh",
            ),
            operations,
        )
        self.assertIn(("get", "/api/market/breadth/official"), operations)
        self.assertIn(("get", "/api/market/data-core/datasets"), operations)
        self.assertIn(("get", "/api/market/data-core/operations"), operations)
        self.assertIn(
            (
                "get",
                "/api/market/data-core/datasets/{dataset_id}/platform-evidence",
            ),
            operations,
        )
        self.assertIn(
            ("get", "/api/market/data-core/datasets/{dataset_id}/health"),
            operations,
        )
        self.assertIn(("get", "/api/market/indicators/contract/active"), operations)
        self.assertIn(
            ("get", "/api/market/indices/{index_id}/official-daily"),
            operations,
        )
        self.assertIn(
            ("post", "/api/market/indices/{index_id}/official-daily/refresh"),
            operations,
        )
        self.assertIn(
            ("post", "/api/portfolio/holdings/kgi-sync"),
            operations,
        )
        self.assertIn(
            ("get", "/api/us-market/sec/{symbol}/financials"),
            operations,
        )
        self.assertTrue(
            {
                ("post", "/api/market/realtime-quote-leases"),
                ("get", "/api/market/realtime-quote-leases/summary"),
                ("patch", "/api/market/realtime-quote-leases/{lease_id}"),
                ("delete", "/api/market/realtime-quote-leases/{lease_id}"),
                ("get", "/api/market/realtime-quotes/{stock_id}"),
                ("get", "/api/market/realtime-quotes/{stock_id}/stream"),
                ("post", "/api/market/kgi-data/{stock_id}/backfill"),
            }.issubset(set(operations))
        )
        self.assertIn(
            ("get", "/api/us-market/sec/{symbol}/insider-transactions"),
            operations,
        )
        self.assertIn(
            ("post", "/api/us-market/sec/ownership/jobs/form4-sync"),
            operations,
        )
        self.assertIn(
            (
                "post",
                "/api/us-market/diagnostics/providers/{provider}/ohlc/{symbol}/repair",
            ),
            operations,
        )
        self.assertIn(
            ("get", "/api/ai/refresh-status/{job_id}"),
            operations,
        )

        tw_dashboard_operations = {
            ("get", "/api/market/tw-dashboard/snapshot"),
            ("get", "/api/market/tw-dashboard/symbols/search"),
            ("get", "/api/market/tw-dashboard/stocks/{stock_id}"),
        }
        self.assertTrue(tw_dashboard_operations.issubset(set(operations)))

        self.assertIn(
            (
                "get",
                "/api/market/technical/{stock_id}/next-session-plan",
            ),
            operations,
        )

        cross_market_operations = {
            ("get", "/api/market/cross-market/relations/{stock_id}"),
            ("get", "/api/market/cross-market/context/{stock_id}"),
            ("post", "/api/market/cross-market/refresh"),
        }
        self.assertTrue(cross_market_operations.issubset(set(operations)))

        radar_v2_operations = {
            (
                "post",
                "/api/watchlists/groups/{group_id}/radar/v2/evaluate",
            ),
            (
                "get",
                "/api/watchlists/groups/{group_id}/radar/v2/snapshots/history",
            ),
            (
                "get",
                "/api/watchlists/groups/{group_id}/radar/v2/outcomes/latest",
            ),
            (
                "get",
                "/api/watchlists/groups/{group_id}/radar/v2/outcomes/history",
            ),
            (
                "post",
                "/api/watchlists/groups/{group_id}/radar/v2/outcomes/reconcile",
            ),
            (
                "post",
                "/api/watchlists/groups/{group_id}/radar/v2/backtests",
            ),
            (
                "get",
                "/api/watchlists/groups/{group_id}/radar/v2/backtests/latest",
            ),
        }
        self.assertTrue(radar_v2_operations.issubset(set(operations)))
        dispatch_v2_operations = {
            ("get", "/api/dispatch/schedules/{schedule_id}/runs"),
            ("post", "/api/dispatch/schedules/{schedule_id}/runs"),
            ("get", "/api/dispatch/schedule-runs/{run_id}"),
            ("post", "/api/dispatch/schedule-runs/{run_id}/retry"),
        }
        self.assertTrue(dispatch_v2_operations.issubset(set(operations)))

    def test_system_health_contracts_are_exposed(self) -> None:
        schema = app.openapi()
        for (method, path), operation_id in EXPECTED_SYSTEM_HEALTH_CONTRACTS.items():
            with self.subTest(method=method, path=path):
                operation = schema["paths"][path][method]
                self.assertEqual(operation["operationId"], operation_id)
                self.assertIn("200", operation["responses"])

    def test_taiwan_index_openapi_contracts_survive_router_split(self) -> None:
        schema = app.openapi()
        for (method, path), (operation_id, response_model, success_status) in EXPECTED_INDEX_CONTRACTS.items():
            with self.subTest(method=method, path=path):
                operation = schema["paths"][path][method]
                response = operation["responses"][success_status]
                response_schema = response["content"]["application/json"]["schema"]
                self.assertEqual(operation["operationId"], operation_id)
                self.assertEqual(
                    response_schema["$ref"],
                    f"#/components/schemas/{response_model}",
                )

    def test_market_router_reexports_index_handlers(self) -> None:
        self.assertIs(market.get_indices_summary, tw_market_indices.get_indices_summary)
        self.assertIs(market.get_indices_list, tw_market_indices.get_indices_list)
        self.assertIs(
            market.get_index_intraday_trend,
            tw_market_indices.get_index_intraday_trend,
        )
        self.assertIs(
            market.get_index_contributions,
            tw_market_indices.get_index_contributions,
        )
        self.assertIs(
            market.get_index_ohlc_chart_data,
            tw_market_indices.get_index_ohlc_chart_data,
        )

    def test_taiwan_futures_openapi_contracts_survive_router_split(self) -> None:
        schema = app.openapi()
        for (method, path), (
            operation_id,
            response_model,
        ) in EXPECTED_FUTURES_CONTRACTS.items():
            with self.subTest(method=method, path=path):
                operation = schema["paths"][path][method]
                response_schema = operation["responses"]["200"]["content"]["application/json"][
                    "schema"
                ]
                self.assertEqual(operation["operationId"], operation_id)
                if response_schema.get("type") == "array":
                    response_ref = response_schema["items"]["$ref"]
                else:
                    response_ref = response_schema["$ref"]
                self.assertEqual(response_ref, f"#/components/schemas/{response_model}")
                parameter_names, parameter_defaults = EXPECTED_FUTURES_PARAMETERS[
                    (method, path)
                ]
                parameters = operation.get("parameters", [])
                self.assertEqual(
                    tuple(parameter["name"] for parameter in parameters),
                    parameter_names,
                )
                parameters_by_name = {parameter["name"]: parameter for parameter in parameters}
                for name, default in parameter_defaults.items():
                    self.assertEqual(parameters_by_name[name]["schema"]["default"], default)

    def test_market_router_reexports_taiwan_futures_handlers(self) -> None:
        handler_names = (
            "get_latest_taiwan_futures_quotes_api",
            "list_taiwan_large_traders_api",
            "list_taiwan_option_chain_api",
            "list_taiwan_term_structure_api",
            "list_taiwan_futures_daily_bars_api",
            "list_taiwan_futures_intraday_bars_api",
            "list_taiwan_futures_products_api",
            "refresh_taiwan_derivatives_api",
            "refresh_taiwan_futures_daily_bars_api",
            "refresh_taiwan_futures_quotes_api",
        )
        for name in handler_names:
            with self.subTest(name=name):
                self.assertIs(getattr(market, name), getattr(tw_market_futures, name))

    def test_taiwan_derivatives_openapi_contracts_are_bounded(self) -> None:
        schema = app.openapi()
        for (method, path), (
            operation_id,
            response_model,
            is_array,
        ) in EXPECTED_DERIVATIVES_CONTRACTS.items():
            with self.subTest(method=method, path=path):
                operation = schema["paths"][path][method]
                response_schema = operation["responses"]["200"]["content"]["application/json"][
                    "schema"
                ]
                self.assertEqual(operation["operationId"], operation_id)
                expected_ref = f"#/components/schemas/{response_model}"
                self.assertEqual(
                    response_schema["items"]["$ref"] if is_array else response_schema["$ref"],
                    expected_ref,
                )
                parameter_names, parameter_defaults = EXPECTED_DERIVATIVES_PARAMETERS[
                    (method, path)
                ]
                parameters = operation.get("parameters", [])
                self.assertEqual(
                    tuple(parameter["name"] for parameter in parameters),
                    parameter_names,
                )
                parameters_by_name = {parameter["name"]: parameter for parameter in parameters}
                for name, default in parameter_defaults.items():
                    self.assertEqual(parameters_by_name[name]["schema"]["default"], default)

    def test_router_modules_do_not_own_database_transactions(self) -> None:
        routers_dir = Path(__file__).resolve().parents[1] / "app" / "routers"
        transaction_calls: list[str] = []
        for path in routers_dir.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr not in {"commit", "rollback", "flush"}:
                    continue
                transaction_calls.append(f"{path.name}:{node.lineno}:{node.func.attr}")

        self.assertEqual(transaction_calls, [])

    def test_router_modules_do_not_depend_on_requests_transport(self) -> None:
        routers_dir = Path(__file__).resolve().parents[1] / "app" / "routers"
        transport_imports: list[str] = []
        for path in routers_dir.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "requests" or alias.name.startswith("requests."):
                            transport_imports.append(f"{path.name}:{node.lineno}:{alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if module == "requests" or module.startswith("requests."):
                        transport_imports.append(f"{path.name}:{node.lineno}:{module}")

        self.assertEqual(transport_imports, [])


if __name__ == "__main__":
    unittest.main()
