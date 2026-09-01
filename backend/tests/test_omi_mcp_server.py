from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from app.ai import contract_manifest


def load_server_module():
    repo_root = Path(__file__).resolve().parents[2]
    server_path = repo_root / "agents" / "omi_mcp_server" / "server.py"
    spec = importlib.util.spec_from_file_location("omi_mcp_server_test_module", server_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load MCP server module from {server_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OmiMcpServerPayloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = load_server_module()

    def setUp(self) -> None:
        self._old_token = self.server.AI_TRUST_TOKEN
        self._old_default_fetch = self.server.TRUSTED_DEFAULT_EXTERNAL_FETCH

    def tearDown(self) -> None:
        self.server.AI_TRUST_TOKEN = self._old_token
        self.server.TRUSTED_DEFAULT_EXTERNAL_FETCH = self._old_default_fetch

    def test_trusted_us_question_defaults_external_fetch_and_budget(self) -> None:
        self.server.AI_TRUST_TOKEN = "trusted-token"
        self.server.TRUSTED_DEFAULT_EXTERNAL_FETCH = True

        payload = self.server._ask_payload({"question": "MU 怎麼看？"})

        self.assertTrue(payload["allow_external_fetch"])
        self.assertEqual(payload["tool_budget"], self.server.TRUSTED_DEFAULT_TOOL_BUDGET)

    def test_untrusted_us_question_stays_read_only_by_default(self) -> None:
        self.server.AI_TRUST_TOKEN = ""
        self.server.TRUSTED_DEFAULT_EXTERNAL_FETCH = True

        payload = self.server._ask_payload({"question": "MU 怎麼看？"})

        self.assertFalse(payload["allow_external_fetch"])
        self.assertEqual(payload["tool_budget"], {})

    def test_explicit_external_fetch_false_overrides_trusted_default(self) -> None:
        self.server.AI_TRUST_TOKEN = "trusted-token"
        self.server.TRUSTED_DEFAULT_EXTERNAL_FETCH = True

        payload = self.server._ask_payload(
            {"question": "MU 怎麼看？", "allow_external_fetch": False}
        )

        self.assertFalse(payload["allow_external_fetch"])
        self.assertEqual(payload["tool_budget"], {})

    def test_trusted_taiwan_question_does_not_default_external_fetch(self) -> None:
        self.server.AI_TRUST_TOKEN = "trusted-token"
        self.server.TRUSTED_DEFAULT_EXTERNAL_FETCH = True

        payload = self.server._ask_payload({"question": "2330 近況"})

        self.assertFalse(payload["allow_external_fetch"])
        self.assertEqual(payload["tool_budget"], {})

    def test_trusted_taiwan_intraday_question_defaults_external_fetch_and_budget(self) -> None:
        self.server.AI_TRUST_TOKEN = "trusted-token"
        self.server.TRUSTED_DEFAULT_EXTERNAL_FETCH = True

        payload = self.server._ask_payload(
            {
                "question": "2330 intraday now",
                "target": {"type": "tw_stock", "id": "2330"},
                "analysis_horizon": "intraday",
                "mode": "brief",
            }
        )

        self.assertTrue(payload["allow_external_fetch"])
        self.assertEqual(payload["tool_budget"], self.server.TRUSTED_DEFAULT_TOOL_BUDGET)

    def test_trusted_japan_intraday_request_defaults_external_fetch_and_budget(self) -> None:
        self.server.AI_TRUST_TOKEN = "trusted-token"
        self.server.TRUSTED_DEFAULT_EXTERNAL_FETCH = True

        payload = self.server._targeted_ask_payload(
            {"symbol": "7203.T", "include_intraday": True},
            target_type="jp_stock",
            target_id="7203.T",
            question="Read Japan stock context 7203.T",
            mode="data_only",
        )

        self.assertTrue(payload["allow_external_fetch"])
        self.assertTrue(payload["market_data_params"]["include_intraday"])
        self.assertEqual(payload["tool_budget"], self.server.TRUSTED_DEFAULT_TOOL_BUDGET)

    def test_auto_target_symbol_defaults_external_fetch_when_trusted(self) -> None:
        self.server.AI_TRUST_TOKEN = "trusted-token"
        self.server.TRUSTED_DEFAULT_EXTERNAL_FETCH = True

        payload = self.server._ask_payload(
            {
                "question": "幫我分析這檔",
                "target": {"type": "auto", "id": "SPCX"},
            }
        )

        self.assertTrue(payload["allow_external_fetch"])
        self.assertEqual(payload["tool_budget"], self.server.TRUSTED_DEFAULT_TOOL_BUDGET)

    def test_ask_schema_and_payload_support_full_mode(self) -> None:
        mode_schema = self.server.ASK_TOOL["inputSchema"]["properties"]["mode"]
        self.assertIn("full", mode_schema["enum"])

        payload = self.server._ask_payload({"question": "2330 full evidence", "mode": "full"})

        self.assertEqual(payload["mode"], "full")

    def test_ask_defaults_to_v4_and_forwards_selective_contract_fields(self) -> None:
        arguments = {
            "question": "只要 2330 即時價",
            "intents": ["quote", "data_freshness"],
            "output": "evidence_only",
            "realtime_policy": "require_live",
            "selection": {
                "include": ["quote.snapshot"],
                "fields": {"quote.snapshot": ["price", "quote_time"]},
                "max_response_bytes": 12_000,
            },
            "continuation": {
                "plan_id": "plan_123",
                "selected_action_ids": ["fill_123"],
            },
        }

        payload = self.server._ask_payload(arguments)
        properties = self.server.ASK_TOOL["inputSchema"]["properties"]

        self.assertEqual(payload["contract_version"], "omi.decision.v4")
        self.assertEqual(payload["intents"], ["quote", "data_freshness"])
        self.assertEqual(payload["output"], "evidence_only")
        self.assertEqual(payload["realtime_policy"], "require_live")
        self.assertEqual(payload["selection"], arguments["selection"])
        self.assertEqual(payload["continuation"], arguments["continuation"])
        self.assertEqual(
            properties["contract_version"]["enum"],
            ["omi.decision.v4"],
        )
        self.assertIn("selection", properties)
        self.assertIn("continuation", properties)

    def test_ask_rejects_legacy_contract_before_backend_call(self) -> None:
        for contract_version in ("omi.decision.v3", "omi.ai.ask.v2"):
            with self.subTest(contract_version=contract_version):
                with self.assertRaisesRegex(
                    ValueError,
                    "contract_version must be omi.decision.v4",
                ):
                    self.server._ask_payload(
                        {
                            "question": "2330",
                            "contract_version": contract_version,
                        }
                    )

    def test_tools_list_uses_backend_owned_ask_schema_with_local_transport_only_fields(
        self,
    ) -> None:
        backend_schema = {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "selection": {
                    "type": "object",
                    "properties": {
                        "include": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["backend.only"],
                            },
                        }
                    },
                },
            },
            "required": ["question"],
        }
        with patch.object(
            self.server,
            "_api_request",
            return_value={
                "tools": [
                    {
                        "name": "omi.ask",
                        "title": "Backend Ask OMI",
                        "description": "Backend-owned contract.",
                        "input_schema": backend_schema,
                    }
                ]
            },
        ) as request:
            response = self.server._handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 5,
                    "method": "tools/list",
                }
            )

        tools = response["result"]["tools"]
        ask_tool = next(tool for tool in tools if tool["name"] == "omi.ask")
        stream_tool = next(
            tool for tool in tools if tool["name"] == "omi.ask_stream"
        )
        refresh_tool = next(
            tool
            for tool in tools
            if tool["name"] == "omi.read_refresh_status"
        )
        taiwan_data_tools = {
            tool["name"]: tool
            for tool in tools
            if tool["name"].startswith("omi.read_taiwan_")
        }
        self.assertEqual(ask_tool["title"], "Backend Ask OMI")
        self.assertEqual(
            ask_tool["inputSchema"]["properties"]["selection"]["properties"][
                "include"
            ]["items"]["enum"],
            ["backend.only"],
        )
        self.assertIn("include_raw", ask_tool["inputSchema"]["properties"])
        self.assertEqual(
            stream_tool["inputSchema"]["properties"]["selection"],
            ask_tool["inputSchema"]["properties"]["selection"],
        )
        self.assertEqual(
            refresh_tool["inputSchema"]["properties"]["job_id"][
                "minimum"
            ],
            1,
        )
        self.assertEqual(
            set(taiwan_data_tools),
            {
                "omi.read_taiwan_bars",
                "omi.read_taiwan_technical_series",
                "omi.read_taiwan_chart",
            },
        )
        request.assert_called_once_with(
            "GET",
            "/api/ai/tools",
            timeout_seconds=self.server.SCHEMA_TIMEOUT_SECONDS,
        )

    def test_taiwan_data_tools_are_thin_backend_route_relays(self) -> None:
        with patch.object(self.server, "_api_get", return_value={"ok": True}) as read:
            result = self.server._call_tool(
                "omi.read_taiwan_technical_series",
                {
                    "instrument_id": "TAIEX",
                    "interval": "15m",
                    "limit": 120,
                    "include_partial": False,
                    "expected_series_revision": "a" * 64,
                },
            )

        self.assertEqual(result, {"ok": True})
        read.assert_called_once_with(
            "/api/market/technical/TAIEX/series",
            {
                "interval": "15m",
                "from": None,
                "to": None,
                "limit": 120,
                "include_partial": False,
                "ma_windows": None,
                "volume_ma_windows": None,
                "expected_series_revision": "a" * 64,
            },
        )

    def test_taiwan_chart_tool_relays_atomic_bundle_route(self) -> None:
        with patch.object(self.server, "_api_get", return_value={"ok": True}) as read:
            self.server._call_tool(
                "omi.read_taiwan_chart",
                {"instrument_id": "2330", "interval": "1d"},
            )

        read.assert_called_once_with(
            "/api/market/chart/2330",
            {
                "interval": "1d",
                "from": None,
                "to": None,
                "limit": 500,
                "include_partial": True,
                "ma_windows": None,
                "volume_ma_windows": None,
            },
        )

    def test_tools_list_falls_back_to_static_schema_when_backend_is_unavailable(
        self,
    ) -> None:
        with patch.object(
            self.server,
            "_api_request",
            side_effect=RuntimeError("offline"),
        ):
            tools = self.server._tools_for_client()

        self.assertEqual(tools, self.server.TOOLS)
        ask_schema = next(
            tool["inputSchema"]
            for tool in tools
            if tool["name"] == "omi.ask"
        )
        selection = ask_schema["properties"]["selection"]["properties"]
        self.assertIn("parameters", selection)
        self.assertIn(
            "screening.ranking",
            selection["parameters"]["properties"],
        )
        self.assertIn(
            "events.calendar",
            selection["parameters"]["properties"],
        )
        self.assertEqual(
            ask_schema["x-omi-public-contract-digest"],
            contract_manifest.public_contract_manifest()["digest"],
        )

    def test_offline_snapshot_matches_backend_public_contract(self) -> None:
        snapshot = self.server._load_public_contract_snapshot()
        manifest = contract_manifest.public_contract_manifest()

        self.assertEqual(snapshot["digest"], manifest["digest"])
        self.assertEqual(
            snapshot["capability_registry_version"],
            manifest["capability_registry_version"],
        )
        self.assertEqual(
            set(snapshot["capability_ids"]),
            {
                item["capability_id"]
                for item in manifest["capabilities"]
            },
        )
        self.assertEqual(
            set(snapshot["target_types"]),
            {item["target_type"] for item in manifest["targets"]},
        )

    def test_ask_include_raw_false_keeps_canonical_v4_envelope(self) -> None:
        status_dimensions = {
            "version": "omi.status-dimensions.v1",
            "status_authority": "backend_status_taxonomy",
            "service_status": "available",
            "data_quality": "current",
            "decision_readiness": "ready",
            "provider_status": "available",
        }
        raw_response = {
            "kind": "omi_decision",
            "contract_version": "omi.decision.v4",
            "ok": True,
            "answer": {
                "headline": "NVDA trend",
                "text": "Canonical backend answer.",
            },
            "evidence": {
                "status_dimensions": status_dimensions,
                "data": {
                    "quote.snapshot": {
                        "price": 170,
                        "provider": "test",
                    }
                }
            },
            "projection": {
                "max_response_bytes": 12_000,
                "budget_met": True,
            },
        }

        with patch.object(self.server, "_api_post", return_value=raw_response):
            response = self.server._call_tool(
                "omi.ask",
                {"question": "NVDA", "include_raw": False},
            )

        self.assertIs(response, raw_response)
        self.assertEqual(response["evidence"]["status_dimensions"], status_dimensions)

    def test_legacy_ask_summary_preserves_status_dimensions(self) -> None:
        status_dimensions = {
            "version": "omi.status-dimensions.v1",
            "status_authority": "backend_status_taxonomy",
            "service_status": "available",
            "data_quality": "stale",
            "decision_readiness": "limited",
            "provider_status": "degraded",
        }
        response = {
            "ok": True,
            "result": {
                "kind": "market_context",
                "data": {
                    "compact": {
                        "kind": "market_context_compact",
                        "status_dimensions": status_dimensions,
                    }
                },
            },
            "evidence_passport": {
                "kind": "omi.evidence.passport.v1",
                "status_dimensions": status_dimensions,
            },
        }

        summary = self.server._summarize_ask_response(response)

        self.assertEqual(
            summary["compact_evidence"]["status_dimensions"],
            status_dimensions,
        )
        self.assertEqual(
            summary["evidence_passport"]["status_dimensions"],
            status_dimensions,
        )

    def test_ask_rejects_non_v4_backend_response(self) -> None:
        raw_response = {
            "contract_version": "omi.decision.v3",
            "ok": True,
        }
        with patch.object(self.server, "_api_post", return_value=raw_response):
            with self.assertRaisesRegex(
                RuntimeError,
                "non-v4 public ask response",
            ):
                self.server._call_tool(
                    "omi.ask",
                    {"question": "2330", "include_raw": True},
                )

    def test_ask_stream_include_raw_false_keeps_v4_stream_result(self) -> None:
        raw_response = {
            "kind": "omi_stream_result",
            "ok": True,
            "events": [{"event": "delta", "data": {"text": "ready"}}],
            "evidence": {"rows": list(range(100))},
            "delta_text": "ready",
            "final": {
                "kind": "omi_decision",
                "contract_version": "omi.decision.v4",
                "ok": True,
                "answer": {"text": "ready"},
            },
            "error": None,
        }
        with patch.object(self.server, "_api_stream_post", return_value=raw_response):
            response = self.server._call_tool(
                "omi.ask_stream",
                {"question": "2330", "include_raw": False},
            )

        self.assertIs(response, raw_response)

    def test_read_refresh_status_calls_redacted_ai_endpoint(self) -> None:
        payload = {
            "kind": "ai_refresh_status",
            "version": "omi.ai.refresh.status.v1",
            "job_id": 17,
            "status": "running",
            "evidence_status": "unobserved",
        }
        with patch.object(
            self.server,
            "_api_get",
            return_value=payload,
        ) as api_get:
            response = self.server._call_tool(
                "omi.read_refresh_status",
                {"job_id": 17},
            )

        self.assertIs(response, payload)
        api_get.assert_called_once_with("/api/ai/refresh-status/17")

    def test_offline_public_schema_limits_selected_actions_to_eight(self) -> None:
        selected_actions = self.server.ASK_TOOL["inputSchema"]["properties"][
            "continuation"
        ]["properties"]["selected_action_ids"]
        self.assertEqual(selected_actions["maxItems"], 8)
        self.assertIn(
            "omi.read_refresh_status",
            [tool["name"] for tool in self.server.PUBLIC_TOOLS],
        )

    def test_ask_schema_supports_cross_market_targets_and_market_data_params(self) -> None:
        properties = self.server.ASK_TOOL["inputSchema"]["properties"]
        target_enum = properties["target"]["properties"]["type"]["enum"]

        self.assertEqual(target_enum, self.server.ASK_TARGET_TYPES)
        self.assertEqual(
            set(target_enum),
            {
                "auto",
                "market",
                "data_freshness",
                "tw_stock",
                "tw_watchlist",
                "tw_index",
                "tw_futures",
                "us_stock",
                "jp_stock",
                "jp_index",
                "kr_stock",
                "kr_index",
                "crypto_market",
                "crypto_asset",
                "resource_asset",
                "portfolio",
                "us_macro",
                "us_watchlist",
                "jp_watchlist",
                "kr_watchlist",
                "source_health",
                "capability_status",
            },
        )
        self.assertIn("market_data_params", properties)

    def test_tool_result_exposes_matching_structured_content(self) -> None:
        payload = {"kind": "omi_answer", "result": {"data": {"status": "ready"}}}

        result = self.server._tool_result(payload)

        self.assertEqual(result["structuredContent"], payload)
        self.assertEqual(json.loads(result["content"][0]["text"]), payload)

    def test_structured_business_failure_keeps_mcp_is_error_false(self) -> None:
        payload = {
            "kind": "ai_ask",
            "ok": False,
            "answer_ready": False,
            "error": {"code": "TARGET_NOT_FOUND"},
        }
        with patch.object(self.server, "_call_tool", return_value=payload):
            response = self.server._handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 7,
                    "method": "tools/call",
                    "params": {"name": "omi.ask", "arguments": {"question": "9999"}},
                }
            )

        self.assertFalse(response["result"]["isError"])
        self.assertFalse(response["result"]["structuredContent"]["ok"])

    def test_normal_empty_result_keeps_mcp_is_error_false(self) -> None:
        payload = {
            "kind": "search_results",
            "ok": True,
            "answer_ready": True,
            "results": [],
        }
        with patch.object(self.server, "_call_tool", return_value=payload):
            response = self.server._handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 8,
                    "method": "tools/call",
                    "params": {"name": "omi.ask", "arguments": {"question": "empty"}},
                }
            )

        self.assertFalse(response["result"]["isError"])
        self.assertEqual(response["result"]["structuredContent"]["results"], [])

    def test_payload_forwards_market_data_params(self) -> None:
        payload = self.server._ask_payload(
            {
                "question": "BTC context",
                "target": {"type": "crypto_asset", "id": "BTC"},
                "market_data_params": {
                    "provider": "binance",
                    "symbol": "BTCUSDT",
                    "instrument_type": "perpetual",
                    "interval": "1m",
                    "limit": 80,
                },
            }
        )

        self.assertEqual(payload["target"]["type"], "crypto_asset")
        self.assertEqual(payload["market_data_params"]["symbol"], "BTCUSDT")
        self.assertEqual(payload["market_data_params"]["interval"], "1m")

    def test_payload_merges_top_level_payload_controls(self) -> None:
        payload = self.server._ask_payload(
            {
                "question": "台股大盤盤中摘要",
                "target": {"type": "market"},
                "include_intraday": True,
                "payload_level": "summary",
                "intraday_limit": 1,
                "intraday_interval": "5m",
            }
        )

        self.assertEqual(
            payload["market_data_params"],
            {
                "include_intraday": True,
                "payload_level": "summary",
                "intraday_limit": 1,
                "intraday_interval": "5m",
            },
        )
        self.assertEqual(
            self.server._market_query_controls(
                {"market_data_params": {"intraday_interval": "5m"}}
            )["intraday_interval"],
            "5m",
        )

    def test_ask_schema_exposes_payload_controls_for_gpt_clients(self) -> None:
        properties = self.server.ASK_TOOL["inputSchema"]["properties"]

        self.assertEqual(properties["payload_level"]["enum"], ["summary", "compact", "standard", "full"])
        self.assertEqual(properties["intraday_limit"]["maximum"], 500)
        self.assertEqual(
            properties["intraday_interval"]["enum"],
            ["1m", "5m", "15m", "30m", "1h", "4h"],
        )
        self.assertEqual(properties["session_scope"]["enum"], ["regular", "extended", "all"])
        self.assertEqual(properties["trade_date"]["pattern"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertTrue(properties["include_raw"]["default"])
        self.assertIn("payload_level", properties["market_data_params"]["properties"])
        self.assertIn("intraday_interval", properties["market_data_params"]["properties"])
        self.assertIn("interval", properties["market_data_params"]["properties"])
        self.assertIn("session_scope", properties["market_data_params"]["properties"])
        self.assertIn("trade_date", properties["market_data_params"]["properties"])

        kr_tool = next(tool for tool in self.server.TOOLS if tool["name"] == "omi.ask")
        self.assertIn("payload_level", kr_tool["inputSchema"]["properties"])

    def test_internal_cross_market_schema_gets_top_level_payload_controls(self) -> None:
        tool = next(
            tool
            for tool in self.server.INTERNAL_TOOLS
            if tool["name"] == "omi.read_kr_stock_context"
        )

        properties = tool["inputSchema"]["properties"]
        self.assertIn("payload_level", properties)
        self.assertIn("intraday_limit", properties)
        self.assertIn("market_data_params", properties)

    def test_cross_market_direct_tool_posts_to_ask(self) -> None:
        with patch.object(self.server, "_api_post", return_value={"ok": True}) as api_post:
            result = self.server._call_tool(
                "omi.read_kr_stock_context",
                {
                    "symbol": "005930",
                    "market_data_params": {"timeframe": "weekly", "bars": 26},
                },
            )

        self.assertEqual(result, {"ok": True})
        path = api_post.call_args.args[0]
        payload = api_post.call_args.kwargs["payload"]
        self.assertEqual(path, "/api/ai/ask")
        self.assertEqual(payload["target"], {"type": "kr_stock", "id": "005930"})
        self.assertEqual(payload["mode"], "data_only")
        self.assertEqual(payload["market_data_params"]["timeframe"], "weekly")

    def test_direct_tools_forward_payload_controls(self) -> None:
        with patch.object(self.server, "_api_get", return_value={"ok": True}) as api_get:
            result = self.server._call_tool(
                "omi.read_market_overview",
                {
                    "include_intraday": True,
                    "payload_level": "summary",
                    "intraday_limit": 1,
                },
            )

        self.assertEqual(result, {"ok": True})
        query = api_get.call_args.args[1]
        self.assertTrue(query["include_intraday"])
        self.assertEqual(query["payload_level"], "summary")
        self.assertEqual(query["intraday_limit"], 1)

    def test_us_direct_tool_uses_ask_when_top_level_payload_controls_exist(self) -> None:
        with patch.object(self.server, "_api_post", return_value={"ok": True}) as api_post:
            result = self.server._call_tool(
                "omi.read_us_stock_context",
                {
                    "symbol": "TSM",
                    "payload_level": "summary",
                    "intraday_limit": 1,
                },
            )

        self.assertEqual(result, {"ok": True})
        payload = api_post.call_args.kwargs["payload"]
        self.assertEqual(payload["target"], {"type": "us_stock", "id": "TSM"})
        self.assertEqual(payload["market_data_params"]["payload_level"], "summary")
        self.assertEqual(payload["market_data_params"]["intraday_limit"], 1)

    def test_us_direct_tool_forwards_exact_trade_date(self) -> None:
        with patch.object(self.server, "_api_post", return_value={"ok": True}) as api_post:
            result = self.server._call_tool(
                "omi.read_us_stock_context",
                {
                    "symbol": "AAPL",
                    "trade_date": "2026-07-20",
                },
            )

        self.assertEqual(result, {"ok": True})
        payload = api_post.call_args.kwargs["payload"]
        self.assertEqual(payload["target"], {"type": "us_stock", "id": "AAPL"})
        self.assertEqual(
            payload["market_data_params"]["trade_date"],
            "2026-07-20",
        )

    def test_us_direct_tool_uses_ask_when_intraday_horizon_requested(self) -> None:
        with patch.object(self.server, "_api_post", return_value={"ok": True}) as api_post:
            result = self.server._call_tool(
                "omi.read_us_stock_context",
                {
                    "symbol": "MU",
                    "analysis_horizon": "intraday",
                    "session_scope": "all",
                },
            )

        self.assertEqual(result, {"ok": True})
        payload = api_post.call_args.kwargs["payload"]
        self.assertEqual(payload["target"], {"type": "us_stock", "id": "MU"})
        self.assertEqual(payload["analysis_horizon"], "intraday")
        self.assertTrue(payload["market_data_params"]["include_intraday"])
        self.assertEqual(payload["market_data_params"]["session_scope"], "all")


if __name__ == "__main__":
    unittest.main()
