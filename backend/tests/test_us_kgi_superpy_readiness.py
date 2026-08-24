from __future__ import annotations

from app.us_market.market_data_policy import US_PROVIDER_DESCRIPTORS
from app.us_market.providers.kgi_superpy_readiness import (
    KGI_US_PROVIDER_KEY,
    KGI_US_REQUIRED_QUOTE_FIXTURE_FIELDS,
    assess_kgi_us_quote_fixture,
    build_kgi_us_quote_readiness,
)


def _sanitized_us_quote_fixture() -> dict[str, object]:
    return {
        "symbol": "AAPL",
        "datetime": "20260821155959",
        "open": 226.4,
        "high": 227.2,
        "low": 226.3,
        "close": 227.0,
        "volume": 100,
        "total_volume": 52_000_000,
        "best_bid_price": 226.99,
        "best_bid_volume": 2,
        "best_ask_price": 227.01,
        "best_ask_volume": 3,
        "suspend": 0,
        "trading_session": 0,
        "received_at": "2026-08-21T20:00:00+00:00",
    }


def test_kgi_us_readiness_is_fail_closed_and_not_advertised() -> None:
    readiness = build_kgi_us_quote_readiness()

    assert readiness.status == "blocked_live_validation"
    assert readiness.advertised is False
    assert readiness.provider_policy_enabled is False
    assert readiness.production_wired is False
    assert readiness.live_validation == "not_attempted"
    assert readiness.entitlement == "unknown"
    assert readiness.account_plane_access_allowed is False
    assert KGI_US_PROVIDER_KEY not in {
        descriptor.provider_key for descriptor in US_PROVIDER_DESCRIPTORS
    }


def test_kgi_us_readiness_separates_quote_from_account_and_order() -> None:
    readiness = build_kgi_us_quote_readiness()
    reason_codes = {gate.reason_code for gate in readiness.blocking_gates}

    assert readiness.candidate_capabilities == ("quote.snapshot", "intraday.bars")
    assert set(readiness.forbidden_surfaces) == {
        "Account",
        "SubAccount",
        "Order",
        "portfolio_get",
    }
    assert reason_codes == {
        "US_BRIDGE_FACADE_NOT_IMPLEMENTED",
        "US_QUOTE_FIELD_MAPPING_UNVERIFIED",
        "US_SYMBOL_VENUE_MAPPING_UNVERIFIED",
        "US_SESSION_MAPPING_UNVERIFIED",
        "US_ENTITLEMENT_UNVERIFIED",
        "US_SUBSCRIPTION_CLEANUP_UNVERIFIED",
    }


def test_sanitized_kgi_us_quote_fixture_passes_source_only_gate() -> None:
    assessment = assess_kgi_us_quote_fixture(_sanitized_us_quote_fixture())

    assert assessment.accepted_for_adapter_fixture is True
    assert assessment.missing_fields == ()
    assert assessment.forbidden_fields == ()
    assert "LIVE_ENTITLEMENT_NOT_PROVEN" in assessment.limitations


def test_fixture_gate_rejects_missing_source_fields_and_account_data() -> None:
    fixture = _sanitized_us_quote_fixture()
    fixture.pop("trading_session")
    fixture["account_id"] = "must-not-cross-market-data-boundary"

    assessment = assess_kgi_us_quote_fixture(fixture)

    assert assessment.accepted_for_adapter_fixture is False
    assert assessment.missing_fields == ("trading_session",)
    assert assessment.forbidden_fields == ("account_id",)


def test_fixture_contract_contains_us_specific_best_quote_and_session_fields() -> None:
    assert {
        "best_bid_price",
        "best_bid_volume",
        "best_ask_price",
        "best_ask_volume",
        "suspend",
        "trading_session",
    }.issubset(KGI_US_REQUIRED_QUOTE_FIXTURE_FIELDS)
