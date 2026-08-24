from __future__ import annotations

import argparse
from hashlib import sha256
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
    / "tw_market_dashboard_contract_snapshot.json"
)
SNAPSHOT_SCHEMA_VERSION = "omi.mcp.tw_market_dashboard_snapshot.v1"


def _canonical_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _load_snapshot() -> dict[str, Any]:
    sys.path.insert(0, str(BACKEND_ROOT))
    from app.market.tw_market_dashboard_schemas import (
        TaiwanDashboardStockDetailRead,
        TaiwanDashboardSymbolSearchRead,
        TaiwanMarketDashboardRead,
    )

    payload = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "dashboard_contract_version": "omi.tw_market_dashboard.v1",
        "symbol_search_contract_version": "omi.tw_symbol_search.v1",
        "stock_detail_contract_version": (
            "omi.tw_stock_dashboard_detail.v2"
        ),
        "dashboard_output_schema": (
            TaiwanMarketDashboardRead.model_json_schema()
        ),
        "symbol_search_output_schema": (
            TaiwanDashboardSymbolSearchRead.model_json_schema()
        ),
        "stock_detail_output_schema": (
            TaiwanDashboardStockDetailRead.model_json_schema()
        ),
    }
    return {**payload, "digest": _canonical_digest(payload)}


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
            "Generate backend-owned Taiwan market dashboard output schemas "
            "for thin MCP adapter consumption."
        )
    )
    parser.add_argument(
        "--output",
        action="append",
        type=Path,
        help=(
            "Output path. Repeat to update multiple adapters. Defaults to the "
            "OMI MCP snapshot."
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
                    "schema_version": payload["schema_version"],
                },
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
