from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

from app.ai import capability_contract


REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_SERVER_PATH = REPO_ROOT / "agents" / "omi_mcp_server" / "server.py"


class McpSchemaContractTests(unittest.TestCase):
    def test_repo_mcp_capability_enum_matches_backend_registry(self) -> None:
        # The backend-generated snapshot is applied at module load; the static
        # emergency fallback is not the effective public capability inventory.
        spec = importlib.util.spec_from_file_location("mcp_schema_contract_test", MCP_SERVER_PATH)
        server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(server)
        capability_ids = server.CAPABILITY_IDS

        self.assertEqual(
            set(capability_ids),
            set(capability_contract.CAPABILITIES),
        )
        self.assertEqual(len(capability_ids), len(set(capability_ids)))


if __name__ == "__main__":
    unittest.main()
