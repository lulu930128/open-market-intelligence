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
    ),
    ("get", "/api/market/indices/list"): (
        "get_indices_list_api_market_indices_list_get",
        "MarketIndexListRead",
    ),
    ("get", "/api/market/indices/{index_id}/intraday"): (
        "get_index_intraday_trend_api_market_indices__index_id__intraday_get",
        "IntradayTrendRead",
    ),
    ("get", "/api/market/indices/{index_id}/contributions"): (
        "get_index_contributions_api_market_indices__index_id__contributions_get",
        "MarketIndexContributionRead",
    ),
    ("get", "/api/market/indices/{index_id}/ohlc"): (
        "get_index_ohlc_chart_data_api_market_indices__index_id__ohlc_get",
        "MarketOhlcChartRead",
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
    ("get", "/api/market/tw-futures/{symbol}/intraday"): (
        "list_taiwan_futures_intraday_bars_api_api_market_tw_futures__symbol__intraday_get",
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
        {"interval": "1m", "limit": 390, "refresh": True, "session": "auto"},
    ),
}


class APIContractInventoryTests(unittest.TestCase):
    def test_openapi_operation_inventory_remains_stable(self) -> None:
        schema = app.openapi()
        methods = {"get", "post", "put", "patch", "delete"}
        operations = [
            (method, path)
            for path, path_item in schema["paths"].items()
            for method in path_item
            if method in methods
        ]

        self.assertEqual(len(operations), 329)
        self.assertEqual(sum(1 for _, path in operations if path.startswith("/api/")), 328)

    def test_taiwan_index_openapi_contracts_survive_router_split(self) -> None:
        schema = app.openapi()
        for (method, path), (operation_id, response_model) in EXPECTED_INDEX_CONTRACTS.items():
            with self.subTest(method=method, path=path):
                operation = schema["paths"][path][method]
                response = operation["responses"]["200"]
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
                self.assertEqual(
                    response_schema["items"]["$ref"],
                    f"#/components/schemas/{response_model}",
                )
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
            "list_taiwan_futures_daily_bars_api",
            "list_taiwan_futures_intraday_bars_api",
            "list_taiwan_futures_products_api",
            "refresh_taiwan_futures_quotes_api",
        )
        for name in handler_names:
            with self.subTest(name=name):
                self.assertIs(getattr(market, name), getattr(tw_market_futures, name))

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
