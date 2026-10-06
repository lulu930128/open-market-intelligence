from __future__ import annotations

import ast
from pathlib import Path


def test_presentation_modules_only_use_pure_projection_and_local_font_io():
    root = Path(__file__).resolve().parents[2] / "app" / "dispatch"
    allowed = {"__future__", "dataclasses", "datetime", "math", "typing", "re", "io", "pathlib",
               "PIL", "app.dispatch.market_report_presentation"}
    for name in ("market_report_presentation", "market_report_discord", "market_report_chart", "market_report_text"):
        tree = ast.parse((root / f"{name}.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module in allowed, (name, node.module)
            elif isinstance(node, ast.Import):
                assert all(alias.name in allowed for alias in node.names), name
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"open", "eval", "exec", "__import__", "sum", "sorted"}, name
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"connect", "execute", "request", "urlopen", "read_bytes", "read_text"}, name


def test_radar_chart_consumes_only_detached_projections():
    path = Path(__file__).resolve().parents[2] / "app" / "dispatch" / "market_report_chart.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    # No chart-owned selection/aggregation from raw stock rankings or radar.
    forbidden = {"value_leaders", "top_gainers", "top_losers", "radar", "cross_market", "cross_market_groups"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "model":
            assert node.attr not in forbidden
