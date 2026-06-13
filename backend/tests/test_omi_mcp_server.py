from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


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


if __name__ == "__main__":
    unittest.main()
