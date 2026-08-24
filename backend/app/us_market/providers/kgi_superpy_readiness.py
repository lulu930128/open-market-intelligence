"""Pure, fail-closed readiness contract for a future KGI US quote adapter.

The installed KGI SuperPy SDK exposes a distinct ``USQuote`` facade, but OMI's
current bridge and canonical adapter are Taiwan-only.  This module records the
source evidence and the remaining gates without importing the SDK, logging in,
subscribing, touching Account/Order surfaces, or advertising a provider route.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any


KGI_US_READINESS_SCHEMA = "omi.us.kgi-superpy-source-readiness.v1"
KGI_US_PROVIDER_KEY = "kgi_superpy_us"
KGI_US_REVIEWED_SDK_VERSION = "2.1.0"

KGI_US_REQUIRED_QUOTE_FIXTURE_FIELDS = frozenset(
    {
        "symbol",
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "total_volume",
        "best_bid_price",
        "best_bid_volume",
        "best_ask_price",
        "best_ask_volume",
        "suspend",
        "trading_session",
        "received_at",
    }
)

KGI_US_FORBIDDEN_FIXTURE_FIELDS = frozenset(
    {
        "account",
        "account_id",
        "cash",
        "cost",
        "cost_basis",
        "holdings",
        "order",
        "orders",
        "password",
        "person_id",
        "positions",
    }
)


@dataclass(frozen=True)
class KgiUsReadinessGate:
    reason_code: str
    detail: str


@dataclass(frozen=True)
class KgiUsQuoteReadiness:
    schema_version: str
    provider_key: str
    reviewed_sdk_version: str
    status: str
    advertised: bool
    provider_policy_enabled: bool
    production_wired: bool
    live_validation: str
    entitlement: str
    account_plane_access_allowed: bool
    candidate_capabilities: tuple[str, ...]
    verified_sdk_surfaces: tuple[str, ...]
    forbidden_surfaces: tuple[str, ...]
    blocking_gates: tuple[KgiUsReadinessGate, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class KgiUsQuoteFixtureGate:
    accepted_for_adapter_fixture: bool
    missing_fields: tuple[str, ...]
    forbidden_fields: tuple[str, ...]
    limitations: tuple[str, ...]


def build_kgi_us_quote_readiness() -> KgiUsQuoteReadiness:
    """Return source-reviewed KGI US readiness without runtime side effects."""

    return KgiUsQuoteReadiness(
        schema_version=KGI_US_READINESS_SCHEMA,
        provider_key=KGI_US_PROVIDER_KEY,
        reviewed_sdk_version=KGI_US_REVIEWED_SDK_VERSION,
        status="blocked_live_validation",
        advertised=False,
        provider_policy_enabled=False,
        production_wired=False,
        live_validation="not_attempted",
        entitlement="unknown",
        account_plane_access_allowed=False,
        candidate_capabilities=("quote.snapshot", "intraday.bars"),
        verified_sdk_surfaces=(
            "MarketType.USStock",
            "api.USQuote.Contracts",
            "api.USQuote.subscribe_all(symbol, version)",
            "api.USQuote.subscribe_kbar(symbol, minute)",
            "api.USQuote.get_subscriptions()",
            "api.USQuote.unsubscribe(label)",
            "api.USQuote.unsubscribe_all()",
            "USStock quote suspend and trading_session fields",
            "USStock scalar best bid and ask fields",
        ),
        forbidden_surfaces=(
            "Account",
            "SubAccount",
            "Order",
            "portfolio_get",
        ),
        blocking_gates=(
            KgiUsReadinessGate(
                reason_code="US_BRIDGE_FACADE_NOT_IMPLEMENTED",
                detail=(
                    "The current bridge initializes and subscribes api.Quote; a "
                    "separate api.USQuote lifecycle is required."
                ),
            ),
            KgiUsReadinessGate(
                reason_code="US_QUOTE_FIELD_MAPPING_UNVERIFIED",
                detail=(
                    "The current Taiwan payload extractor expects depth arrays, "
                    "while the SDK's US quote contract exposes scalar best bid/ask "
                    "and trading_session fields."
                ),
            ),
            KgiUsReadinessGate(
                reason_code="US_SYMBOL_VENUE_MAPPING_UNVERIFIED",
                detail=(
                    "A canonical symbol, provider symbol, listing venue, currency, "
                    "and timezone mapping has not been proven with a runtime sample."
                ),
            ),
            KgiUsReadinessGate(
                reason_code="US_SESSION_MAPPING_UNVERIFIED",
                detail=(
                    "The SDK trading_session values have not been mapped to OMI US "
                    "premarket, regular, closing-auction, and after-hours semantics."
                ),
            ),
            KgiUsReadinessGate(
                reason_code="US_ENTITLEMENT_UNVERIFIED",
                detail=(
                    "Source inspection cannot prove account qualification or market-"
                    "data entitlement."
                ),
            ),
            KgiUsReadinessGate(
                reason_code="US_SUBSCRIPTION_CLEANUP_UNVERIFIED",
                detail=(
                    "A bounded single-symbol lease and unsubscribe cleanup have not "
                    "been exercised against the live SDK."
                ),
            ),
        ),
    )


def assess_kgi_us_quote_fixture(
    payload: Mapping[str, Any],
) -> KgiUsQuoteFixtureGate:
    """Validate a sanitized US quote sample for adapter development only.

    Passing this gate means only that the sample contains the minimum source
    fields and no Account/Order secrets.  It does not prove entitlement,
    freshness, session semantics, canonical validity, or production readiness.
    """

    present = {str(key).strip().lower() for key in payload}
    missing = tuple(sorted(KGI_US_REQUIRED_QUOTE_FIXTURE_FIELDS - present))
    forbidden = tuple(sorted(KGI_US_FORBIDDEN_FIXTURE_FIELDS & present))
    return KgiUsQuoteFixtureGate(
        accepted_for_adapter_fixture=not missing and not forbidden,
        missing_fields=missing,
        forbidden_fields=forbidden,
        limitations=(
            "SOURCE_FIXTURE_ONLY",
            "LIVE_ENTITLEMENT_NOT_PROVEN",
            "SESSION_MAPPING_NOT_PROVEN",
            "VENUE_MAPPING_NOT_PROVEN",
        ),
    )


__all__ = [
    "KGI_US_FORBIDDEN_FIXTURE_FIELDS",
    "KGI_US_PROVIDER_KEY",
    "KGI_US_READINESS_SCHEMA",
    "KGI_US_REQUIRED_QUOTE_FIXTURE_FIELDS",
    "KGI_US_REVIEWED_SDK_VERSION",
    "KgiUsQuoteFixtureGate",
    "KgiUsQuoteReadiness",
    "KgiUsReadinessGate",
    "assess_kgi_us_quote_fixture",
    "build_kgi_us_quote_readiness",
]
