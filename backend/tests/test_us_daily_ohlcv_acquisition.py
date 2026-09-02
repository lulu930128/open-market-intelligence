from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.market_data.contracts import (
    InstrumentKey,
    InstrumentType,
    Market,
    MarketSession,
)
from app.market_data.integration_contracts import (
    BarCapabilityRequest,
    DataRequirementV2,
    FreshnessRequirement,
    InstrumentTarget,
    RequestBounds,
)
from app.config import Settings
from app.market_data.policies import DataPurpose, RealtimePolicy
from app.market_data.provider_catalog import plan_data_acquisition_v2
from app.observability.provider_http import (
    ProviderHttpError,
    ProviderHttpFailure,
    ProviderRequestContext,
)
from app.us_market.daily_ohlcv_acquisition import (
    USDailyOhlcvAcquisitionExecutor,
    USProviderPayload,
)
from app.us_market.market_data.descriptors import (
    ALPACA_SIP_DAILY_RESOURCE_ID,
    US_DAILY_ALPACA_ROLLOUT_DESCRIPTORS,
    US_DAILY_PROVIDER_DESCRIPTORS,
    YAHOO_DAILY_DESCRIPTOR,
    YAHOO_DAILY_RESOURCE_ID,
)


EASTERN = ZoneInfo("America/New_York")
NOW = datetime(2026, 8, 22, 8, 0, tzinfo=EASTERN)


def _requirement(
    *,
    instrument_type: InstrumentType = InstrumentType.STOCK,
    max_provider_calls: int = 1,
) -> DataRequirementV2:
    symbol = "^SOX" if instrument_type is InstrumentType.INDEX else "TSM"
    return DataRequirementV2(
        target=InstrumentTarget(
            instrument=InstrumentKey(
                market=Market.US,
                symbol=symbol,
                instrument_type=instrument_type,
                venue="NASDAQ" if instrument_type is InstrumentType.INDEX else "NYSE",
            )
        ),
        request=BarCapabilityRequest(
            capability_id="daily.ohlcv",
            interval="1d",
            start_at=datetime.combine(date(2026, 8, 21), time(9, 30), tzinfo=EASTERN),
            end_at=datetime.combine(date(2026, 8, 21), time(16), tzinfo=EASTERN),
            max_bars=1,
            completed_only=True,
            price_basis="raw",
        ),
        purpose=DataPurpose.RESEARCH,
        realtime_policy=RealtimePolicy.PREFER_LIVE,
        session=MarketSession.CLOSED,
        requested_at=NOW,
        freshness=FreshnessRequirement(max_age_seconds=86400),
        bounds=RequestBounds(
            max_provider_attempts=max_provider_calls,
            max_external_calls=max_provider_calls,
            max_rows=10,
        ),
    )


def _yahoo_payload(symbol: str, *, volume: int | None = 1000) -> dict:
    timestamp = int(datetime(2026, 8, 21, 12, 0, tzinfo=EASTERN).timestamp())
    return {
        "chart": {
            "result": [
                {
                    "meta": {"symbol": symbol, "currency": "USD"},
                    "timestamp": [timestamp],
                    "indicators": {
                        "quote": [
                            {
                                "open": [240.0],
                                "high": [245.0],
                                "low": [239.0],
                                "close": [244.0],
                                "volume": [volume],
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }


def _alpaca_payload(symbol: str, *, close: float | None = 244.2) -> dict:
    return {
        "symbol": symbol,
        "bars": [
            {
                "t": "2026-08-21T04:00:00Z",
                "o": 240.0,
                "h": 245.0,
                "l": 239.0,
                "c": close,
                "v": 1234567,
            }
        ],
        "next_page_token": None,
    }


def test_executor_runs_only_shared_plan_routes_and_preserves_receipt_lineage() -> None:
    requirement = _requirement()
    plan = plan_data_acquisition_v2(requirement, US_DAILY_PROVIDER_DESCRIPTORS)
    calls = []

    def fetch(route, received):
        calls.append((route.resource_id, received))
        return USProviderPayload(
            payload=_yahoo_payload("TSM"),
            url="https://query.example.invalid/chart/TSM",
        )

    result = USDailyOhlcvAcquisitionExecutor(
        fetchers={YAHOO_DAILY_RESOURCE_ID: fetch},
        clock=lambda: NOW,
    ).acquire_bar_observations(requirement, plan)

    assert [item[0] for item in calls] == [route.resource_id for route in plan.routes]
    assert result.summary.external_calls == 1
    assert len(result.receipts) == 1
    assert len(result.observations) == 1
    assert result.observations[0].lineage.provider == "yahoo_chart"
    assert result.observations[0].lineage.content_hash == result.receipts[0].content_hash
    assert result.observations[0].finalization.value == "final"


@pytest.mark.parametrize("raw_volume", [None, 0])
def test_index_daily_volume_can_remain_absent_without_fake_zero(
    raw_volume: int | None,
) -> None:
    requirement = _requirement(instrument_type=InstrumentType.INDEX)
    plan = plan_data_acquisition_v2(requirement, (YAHOO_DAILY_DESCRIPTOR,))
    result = USDailyOhlcvAcquisitionExecutor(
        fetchers={
            YAHOO_DAILY_RESOURCE_ID: lambda route, received: USProviderPayload(
                payload=_yahoo_payload("^SOX", volume=raw_volume),
                url="https://query.example.invalid/chart/%5ESOX",
            )
        },
        clock=lambda: NOW,
    ).acquire_bar_observations(requirement, plan)

    assert len(result.observations) == 1
    assert result.observations[0].volume is None
    assert result.observations[0].volume_status == "not_applicable"
    assert result.provider_health[0].detail_code == "US_DAILY_OBSERVED"
    assert result.provider_health[0].operational.value == "healthy"


def test_alpaca_pagination_token_never_claims_history_coverage_complete() -> None:
    from app.market_data.integration_contracts import BarCoverageRequirement
    from app.us_market.market_data.descriptors import (
        ALPACA_SIP_DAILY_RESOURCE_ID,
        ALPACA_SIP_DAILY_DESCRIPTOR,
    )

    base = _requirement()
    requirement = base.model_copy(
        update={
            "request": base.request.model_copy(
                update={"coverage": BarCoverageRequirement(minimum_bar_count=1)}
            )
        }
    )
    plan = plan_data_acquisition_v2(requirement, (ALPACA_SIP_DAILY_DESCRIPTOR,))
    payload = _alpaca_payload("TSM")
    payload["next_page_token"] = "more"
    result = USDailyOhlcvAcquisitionExecutor(
        fetchers={
            ALPACA_SIP_DAILY_RESOURCE_ID: lambda route, received: USProviderPayload(
                payload=payload,
                url="https://data.example.invalid/v2/stocks/TSM/bars?feed=sip",
            )
        },
        clock=lambda: NOW,
    ).acquire_bar_observations(requirement, plan)

    assert result.summary.status.value == "partial"
    assert "ALPACA_PAGINATION_TRUNCATED" in result.summary.limitations
    assert result.provider_health[0].operational.value == "degraded"


def test_provider_failure_is_visible_and_does_not_create_receipt_or_bar() -> None:
    requirement = _requirement()
    plan = plan_data_acquisition_v2(requirement, US_DAILY_PROVIDER_DESCRIPTORS)

    def fail(route, received):
        raise TimeoutError("fixture timeout")

    result = USDailyOhlcvAcquisitionExecutor(
        fetchers={YAHOO_DAILY_RESOURCE_ID: fail},
        clock=lambda: NOW,
    ).acquire_bar_observations(requirement, plan)

    assert result.summary.status.value == "failed"
    assert result.receipts == ()
    assert result.observations == ()
    assert "PROVIDER_REQUEST_FAILED" in result.summary.limitations


def test_complete_yahoo_daily_short_circuits_alpaca_fallback() -> None:
    requirement = _requirement(max_provider_calls=2)
    plan = plan_data_acquisition_v2(
        requirement,
        US_DAILY_ALPACA_ROLLOUT_DESCRIPTORS,
    )
    calls = []

    def yahoo(route, received):
        calls.append(route.resource_id)
        return USProviderPayload(
            payload=_yahoo_payload("TSM"),
            url="https://query.example.invalid/chart/TSM",
        )

    def alpaca(route, received):
        calls.append(route.resource_id)
        return USProviderPayload(
            payload=_alpaca_payload("TSM"),
            url="https://data.example.invalid/v2/stocks/TSM/bars?feed=sip",
        )

    result = USDailyOhlcvAcquisitionExecutor(
        fetchers={
            YAHOO_DAILY_RESOURCE_ID: yahoo,
            ALPACA_SIP_DAILY_RESOURCE_ID: alpaca,
        },
        clock=lambda: NOW,
    ).acquire_bar_observations(requirement, plan)

    assert calls == [YAHOO_DAILY_RESOURCE_ID]
    assert result.summary.external_calls == 1
    assert result.summary.providers_attempted == ("yahoo_chart",)


def test_malformed_yahoo_daily_continues_to_alpaca() -> None:
    requirement = _requirement(max_provider_calls=2)
    plan = plan_data_acquisition_v2(
        requirement,
        US_DAILY_ALPACA_ROLLOUT_DESCRIPTORS,
    )
    yahoo_payload = _yahoo_payload("TSM")
    yahoo_payload["chart"]["result"][0]["indicators"]["quote"][0]["close"] = [None]
    calls = []

    def fetch(route, received):
        calls.append(route.resource_id)
        return USProviderPayload(
            payload=(
                yahoo_payload
                if route.resource_id == YAHOO_DAILY_RESOURCE_ID
                else _alpaca_payload("TSM")
            ),
            url=f"https://provider.example.invalid/{route.resource_id}",
        )

    result = USDailyOhlcvAcquisitionExecutor(
        fetchers={
            YAHOO_DAILY_RESOURCE_ID: fetch,
            ALPACA_SIP_DAILY_RESOURCE_ID: fetch,
        },
        clock=lambda: NOW,
    ).acquire_bar_observations(requirement, plan)

    assert calls == [YAHOO_DAILY_RESOURCE_ID, ALPACA_SIP_DAILY_RESOURCE_ID]
    assert result.summary.external_calls == 2
    assert result.summary.providers_attempted == ("yahoo_chart", "alpaca")
    assert [receipt.provider for receipt in result.receipts] == [
        "yahoo_chart",
        "alpaca",
    ]
    assert [bar.lineage.provider for bar in result.observations] == ["alpaca"]
    assert [item.resource_id for item in result.provider_health] == [
        YAHOO_DAILY_RESOURCE_ID,
        ALPACA_SIP_DAILY_RESOURCE_ID,
    ]


def test_index_plan_never_routes_to_alpaca_stock_endpoint() -> None:
    requirement = _requirement(instrument_type=InstrumentType.INDEX)
    plan = plan_data_acquisition_v2(
        requirement,
        US_DAILY_ALPACA_ROLLOUT_DESCRIPTORS,
    )
    assert [route.resource_id for route in plan.routes] == [YAHOO_DAILY_RESOURCE_ID]
    assert any(
        item.resource_id == ALPACA_SIP_DAILY_RESOURCE_ID
        and item.reason_code == "INSTRUMENT_TYPE_NOT_SUPPORTED_BY_RESOURCE"
        for item in plan.skipped_resources
    )


def test_alpaca_missing_credentials_is_disabled_not_provider_outage() -> None:
    requirement = _requirement()
    plan = plan_data_acquisition_v2(
        requirement,
        (US_DAILY_ALPACA_ROLLOUT_DESCRIPTORS[1],),
    )
    result = USDailyOhlcvAcquisitionExecutor(
        settings=Settings(alpaca_api_key_id=None, alpaca_api_secret_key=None),
        clock=lambda: NOW,
    ).acquire_bar_observations(requirement, plan)

    assert result.summary.limitations == ("ALPACA_CREDENTIALS_NOT_CONFIGURED",)
    assert result.provider_health[0].resource_id == ALPACA_SIP_DAILY_RESOURCE_ID
    assert result.provider_health[0].enablement.value == "disabled"
    assert result.provider_health[0].connection.value == "not_applicable"
    assert result.provider_health[0].entitlement.value == "unknown"


def test_alpaca_recent_sip_range_is_plan_restricted_before_network_io() -> None:
    request = _requirement().request.model_copy(
        update={
            "start_at": NOW - timedelta(minutes=10),
            "end_at": NOW - timedelta(minutes=5),
        }
    )
    requirement = _requirement().model_copy(update={"request": request})
    plan = plan_data_acquisition_v2(
        requirement,
        (US_DAILY_ALPACA_ROLLOUT_DESCRIPTORS[1],),
    )
    result = USDailyOhlcvAcquisitionExecutor(
        settings=Settings(
            alpaca_api_key_id="fixture-key",
            alpaca_api_secret_key="fixture-secret",
        ),
        clock=lambda: NOW,
    ).acquire_bar_observations(requirement, plan)

    assert result.summary.limitations == ("ALPACA_SIP_DELAY_WINDOW_NOT_ELIGIBLE",)
    assert result.provider_health[0].connection.value == "connected"
    assert result.provider_health[0].entitlement.value == "plan_restricted"
    assert result.provider_health[0].operational.value == "failed"


@pytest.mark.parametrize(
    (
        "status_code",
        "rate_limited",
        "expected_code",
        "expected_entitlement",
        "expected_operational",
    ),
    [
        (401, False, "ALPACA_AUTH_FAILED", "auth_failed", "failed"),
        (403, False, "ALPACA_PLAN_RESTRICTED", "plan_restricted", "failed"),
        (429, True, "ALPACA_RATE_LIMITED", "unknown", "rate_limited"),
    ],
)
def test_alpaca_http_failures_keep_auth_plan_and_rate_health_distinct(
    status_code: int,
    rate_limited: bool,
    expected_code: str,
    expected_entitlement: str,
    expected_operational: str,
) -> None:
    requirement = _requirement()
    plan = plan_data_acquisition_v2(
        requirement,
        (US_DAILY_ALPACA_ROLLOUT_DESCRIPTORS[1],),
    )
    failure = ProviderHttpFailure(
        context=ProviderRequestContext(
            market="us",
            provider="alpaca",
            resource="sip_historical_bars",
            target="TSM",
        ),
        status="rate_limited" if rate_limited else "error",
        source_url="https://data.example.invalid/v2/stocks/TSM/bars",
        http_status_code=status_code,
        rate_limited=rate_limited,
    )

    def fail(route, received):
        raise ProviderHttpError("fixture provider failure", failure=failure)

    result = USDailyOhlcvAcquisitionExecutor(
        fetchers={ALPACA_SIP_DAILY_RESOURCE_ID: fail},
        clock=lambda: NOW,
    ).acquire_bar_observations(requirement, plan)

    assert result.summary.limitations == (expected_code,)
    assert result.provider_health[0].detail_code == expected_code
    assert result.provider_health[0].entitlement.value == expected_entitlement
    assert result.provider_health[0].operational.value == expected_operational
