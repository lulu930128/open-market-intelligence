from __future__ import annotations

import unittest

from app.main import app
from app.routers import market, tw_market_indices


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

        self.assertEqual(len(operations), 326)
        self.assertEqual(sum(1 for _, path in operations if path.startswith("/api/")), 325)

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


if __name__ == "__main__":
    unittest.main()
