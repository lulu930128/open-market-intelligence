from app.research.coverage import build_market_coverage_gate


def test_unknown_universe_never_advertises_full_market_readiness() -> None:
    result = build_market_coverage_gate(
        market="US",
        universe_id="us_stock_master.active",
        universe_version="2026-08-23.local",
        as_of="2026-08-22",
        expected_count=None,
        observed_count=7427,
        fresh_count=1,
        universe_complete=False,
    )

    assert result["full_market_ready"] is False
    assert result["coverage_ratio"] is None
    assert "EXPECTED_UNIVERSE_UNKNOWN" in result["reason_codes"]
    assert "UNIVERSE_NOT_PROVEN_COMPLETE" in result["reason_codes"]


def test_full_market_requires_complete_fresh_versioned_universe() -> None:
    result = build_market_coverage_gate(
        market="US",
        universe_id="fixture",
        universe_version="fixture.v1",
        as_of="2026-08-22",
        expected_count=3,
        observed_count=3,
        fresh_count=3,
        universe_complete=True,
    )

    assert result["full_market_ready"] is True
    assert result["coverage_ratio"] == 1.0
    assert result["reason_codes"] == []
