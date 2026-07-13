from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


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

    def test_ask_schema_supports_cross_market_targets_and_market_data_params(self) -> None:
        properties = self.server.ASK_TOOL["inputSchema"]["properties"]
        target_enum = properties["target"]["properties"]["type"]["enum"]

        for target_type in (
            "tw_index",
            "tw_futures",
            "jp_stock",
            "jp_index",
            "kr_stock",
            "kr_index",
            "crypto_market",
            "crypto_asset",
        ):
            self.assertIn(target_type, target_enum)
        self.assertIn("market_data_params", properties)

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
            }
        )

        self.assertEqual(
            payload["market_data_params"],
            {
                "include_intraday": True,
                "payload_level": "summary",
                "intraday_limit": 1,
            },
        )

    def test_ask_schema_exposes_payload_controls_for_gpt_clients(self) -> None:
        properties = self.server.ASK_TOOL["inputSchema"]["properties"]

        self.assertEqual(properties["payload_level"]["enum"], ["summary", "compact", "standard", "full"])
        self.assertEqual(properties["intraday_limit"]["maximum"], 500)
        self.assertEqual(properties["session_scope"]["enum"], ["regular", "extended", "all"])
        self.assertIn("payload_level", properties["market_data_params"]["properties"])
        self.assertIn("session_scope", properties["market_data_params"]["properties"])

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
