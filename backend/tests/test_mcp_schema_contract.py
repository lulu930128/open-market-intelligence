from __future__ import annotations

import ast
from pathlib import Path
import unittest

from app.ai import capability_contract


REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_SERVER_PATH = REPO_ROOT / "agents" / "omi_mcp_server" / "server.py"


def _literal_assignment(path: Path, name: str) -> object:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} is not defined in {path}")


class McpSchemaContractTests(unittest.TestCase):
    def test_repo_mcp_capability_enum_matches_backend_registry(self) -> None:
        capability_ids = _literal_assignment(
            MCP_SERVER_PATH,
            "CAPABILITY_IDS",
        )

        self.assertEqual(
            set(capability_ids),
            set(capability_contract.CAPABILITIES),
        )
        self.assertEqual(len(capability_ids), len(set(capability_ids)))


if __name__ == "__main__":
    unittest.main()
