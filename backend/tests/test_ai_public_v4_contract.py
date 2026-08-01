from __future__ import annotations

import unittest

from pydantic import ValidationError

from app.ai.schemas import AiAskV4Request
from app.main import app


class AiPublicV4ContractTests(unittest.TestCase):
    def test_public_request_defaults_to_v4_and_rejects_legacy_versions(self) -> None:
        request = AiAskV4Request(question="2330 怎麼看")

        self.assertEqual(request.contract_version, "omi.decision.v4")
        for contract_version in ("omi.decision.v3", "omi.ai.ask.v2"):
            with self.subTest(contract_version=contract_version):
                with self.assertRaises(ValidationError):
                    AiAskV4Request(
                        question="2330 怎麼看",
                        contract_version=contract_version,
                    )

    def test_openapi_exposes_only_v4_request_and_response_models(self) -> None:
        schema = app.openapi()
        components = schema["components"]["schemas"]

        request_schema = components["AiAskV4Request"]["properties"][
            "contract_version"
        ]
        response_schema = components["AiDecisionEnvelopeV4"]["properties"][
            "contract_version"
        ]
        ask_operation = schema["paths"]["/api/ai/ask"]["post"]
        stream_operation = schema["paths"]["/api/ai/ask/stream"]["post"]

        self.assertEqual(request_schema["const"], "omi.decision.v4")
        self.assertEqual(response_schema["const"], "omi.decision.v4")
        self.assertEqual(
            ask_operation["requestBody"]["content"]["application/json"]["schema"][
                "$ref"
            ],
            "#/components/schemas/AiAskV4Request",
        )
        self.assertEqual(
            stream_operation["requestBody"]["content"]["application/json"][
                "schema"
            ]["$ref"],
            "#/components/schemas/AiAskV4Request",
        )
        self.assertEqual(
            ask_operation["responses"]["200"]["content"]["application/json"][
                "schema"
            ]["$ref"],
            "#/components/schemas/AiDecisionEnvelopeV4",
        )
        public_status_fields = {
            "transport_ok",
            "request_valid",
            "execution_completed",
            "data_available",
            "quality_status",
        }
        v4_response = components["AiDecisionEnvelopeV4"]
        self.assertTrue(
            public_status_fields <= set(v4_response["properties"])
        )
        self.assertTrue(
            public_status_fields <= set(v4_response["required"])
        )

    def test_openapi_exposes_us_exchange_trade_date_on_context_and_brief(self) -> None:
        schema = app.openapi()

        for path in (
            "/api/ai/us-stocks/{symbol}/context",
            "/api/ai/us-stocks/{symbol}/brief",
        ):
            with self.subTest(path=path):
                parameters = {
                    parameter["name"]: parameter
                    for parameter in schema["paths"][path]["get"]["parameters"]
                }
                trade_date = parameters["trade_date"]
                self.assertEqual(
                    trade_date["description"],
                    "US exchange trade date in America/New_York (YYYY-MM-DD).",
                )
                self.assertEqual(
                    trade_date["schema"]["anyOf"][0]["format"],
                    "date",
                )

    def test_openapi_exposes_taiwan_intraday_interval_and_metadata(self) -> None:
        schema = app.openapi()

        for path in (
            "/api/ai/stocks/{stock_id}/context",
            "/api/ai/stocks/{stock_id}/brief",
        ):
            with self.subTest(path=path):
                parameters = {
                    parameter["name"]: parameter
                    for parameter in schema["paths"][path]["get"]["parameters"]
                }
                interval = parameters["intraday_interval"]
                self.assertEqual(
                    interval["schema"]["anyOf"][0]["pattern"],
                    "^(1m|5m|15m|30m|1h|4h)$",
                )

        history = schema["components"]["schemas"]["MarketIntradayChartRead"]
        self.assertTrue(
            {
                "requested_interval",
                "source_interval",
                "effective_interval",
                "interval_status",
                "cache_status",
                "cache_hit",
                "cache_trade_date",
                "cache_latest_time",
                "fallback_used",
            }
            <= set(history["properties"])
        )

    def test_openapi_exposes_read_only_taiwan_index_contract_replay(
        self,
    ) -> None:
        schema = app.openapi()
        operation = schema["paths"][
            "/api/market/index/{index_id}/contract-replay"
        ]["get"]

        self.assertEqual(
            operation["responses"]["200"]["content"]["application/json"][
                "schema"
            ]["$ref"],
            "#/components/schemas/TaiwanIndexContractReplayRead",
        )
