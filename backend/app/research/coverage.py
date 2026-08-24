"""Versioned coverage gates for market-wide research capabilities."""

from __future__ import annotations

from typing import Any


def build_market_coverage_gate(
    *,
    market: str,
    universe_id: str,
    universe_version: str,
    as_of: str | None,
    expected_count: int | None,
    observed_count: int,
    fresh_count: int,
    universe_complete: bool,
) -> dict[str, Any]:
    coverage_ratio = (
        fresh_count / expected_count
        if expected_count is not None and expected_count > 0
        else None
    )
    full_market_ready = bool(
        universe_complete
        and expected_count is not None
        and observed_count >= expected_count
        and fresh_count >= expected_count
    )
    reason_codes: list[str] = []
    if expected_count is None:
        reason_codes.append("EXPECTED_UNIVERSE_UNKNOWN")
    if not universe_complete:
        reason_codes.append("UNIVERSE_NOT_PROVEN_COMPLETE")
    if expected_count is not None and observed_count < expected_count:
        reason_codes.append("OBSERVED_COVERAGE_INCOMPLETE")
    if expected_count is not None and fresh_count < expected_count:
        reason_codes.append("FRESH_COVERAGE_INCOMPLETE")
    return {
        "kind": "market_coverage_gate",
        "schema_version": "omi.research.market_coverage.v1",
        "market": market,
        "universe_id": universe_id,
        "universe_version": universe_version,
        "as_of": as_of,
        "expected_count": expected_count,
        "observed_count": observed_count,
        "fresh_count": fresh_count,
        "coverage_ratio": coverage_ratio,
        "universe_complete": universe_complete,
        "full_market_ready": full_market_ready,
        "reason_codes": reason_codes,
    }


__all__ = ["build_market_coverage_gate"]
