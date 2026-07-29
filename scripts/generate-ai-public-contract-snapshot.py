from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "agents"
    / "omi_mcp_server"
    / "public_contract_snapshot.json"
)


def _load_snapshot() -> dict[str, Any]:
    sys.path.insert(0, str(BACKEND_ROOT))
    from app.ai import contract_manifest, tool_catalog

    catalog = tool_catalog.list_ai_tools()
    ask_tool = next(
        (
            item
            for item in catalog.get("tools") or []
            if isinstance(item, dict) and item.get("name") == "omi.ask"
        ),
        None,
    )
    if not isinstance(ask_tool, dict):
        raise RuntimeError("Backend catalog did not expose omi.ask.")
    input_schema = ask_tool.get("input_schema")
    if not isinstance(input_schema, dict):
        raise RuntimeError("Backend omi.ask did not expose input_schema.")
    manifest = contract_manifest.public_contract_manifest()
    return {
        "schema_version": "omi.mcp.public_contract_snapshot.v1",
        "contract_version": manifest["contract_version"],
        "capability_registry_version": manifest[
            "capability_registry_version"
        ],
        "selection_version": manifest["selection_version"],
        "digest": manifest["digest"],
        "target_types": [
            str(item["target_type"])
            for item in manifest["targets"]
            if isinstance(item, dict) and item.get("target_type")
        ],
        "capability_ids": [
            str(item["capability_id"])
            for item in manifest["capabilities"]
            if isinstance(item, dict) and item.get("capability_id")
        ],
        "ask_input_schema": input_schema,
    }


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate the backend-owned public omi.ask schema snapshot used "
            "only as an MCP offline fallback."
        )
    )
    parser.add_argument(
        "--output",
        action="append",
        type=Path,
        help=(
            "Output path. Repeat to update multiple adapters. Defaults to the "
            "repo MCP snapshot."
        ),
    )
    args = parser.parse_args()
    outputs = args.output or [DEFAULT_OUTPUT]
    payload = _load_snapshot()
    for output in outputs:
        resolved = output.expanduser().resolve()
        _atomic_write(resolved, payload)
        print(
            json.dumps(
                {
                    "output": str(resolved),
                    "digest": payload["digest"],
                    "target_count": len(payload["target_types"]),
                    "capability_count": len(payload["capability_ids"]),
                },
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
