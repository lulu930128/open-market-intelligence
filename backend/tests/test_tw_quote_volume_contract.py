from app.market.quote_volume import build_taiwan_quote_volume_contract


def test_quote_volume_contract_keeps_provider_and_official_totals_distinct(
) -> None:
    result = build_taiwan_quote_volume_contract(
        snapshot_trade_date="2026-07-30",
        cumulative_volume_lots=44_328,
        last_trade_volume_lots=5_494,
        official_daily_trade_date="2026-07-30",
        official_daily_volume_shares=51_372_177,
        official_daily_volume_source="TWSE OpenAPI Daily Trading",
    )

    assert result["cumulative_volume_shares"] == 44_328_000
    assert result["last_trade_volume_shares"] == 5_494_000
    assert result["official_daily_volume_shares"] == 51_372_177
    assert result["volume_reconciliation"]["difference_shares"] == -7_044_177
    assert result["volume_reconciliation"]["difference_pct"] == -13.712
    assert result["volume_scope"] == "regular_session_board_lot_cumulative"
    assert result["official_daily_volume_scope"] == "official_daily_aggregate"
    assert result["volume_reconciliation"]["snapshot_volume_scope"] == (
        "regular_session_board_lot_cumulative"
    )
    assert result["volume_reconciliation"]["reference_volume_scope"] == (
        "official_daily_aggregate"
    )
    assert result["volume_reconciliation"]["tolerance_pct"] is None
    assert result["volume_reconciliation"]["status"] == "scope_different"
    assert result["volume_reconciliation"]["reason"] == (
        "provider_and_official_volume_scopes_differ"
    )
    assert result["volume_reconciliation"]["decision_usable"] is False


def test_quote_volume_contract_does_not_compare_different_trade_dates() -> None:
    result = build_taiwan_quote_volume_contract(
        snapshot_trade_date="2026-07-29",
        cumulative_volume_lots=10,
        official_daily_trade_date="2026-07-30",
        official_daily_volume_shares=10_000,
    )

    reconciliation = result["volume_reconciliation"]
    assert reconciliation["status"] == "not_comparable"
    assert reconciliation["reason"] == "trade_dates_do_not_match"
    assert reconciliation["difference_shares"] is None
