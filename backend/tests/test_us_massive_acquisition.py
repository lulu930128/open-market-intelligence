from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from app.market_data.contracts import (
    EntitlementStatus,
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
    ProviderTimeframe,
    RequestBounds,
    SnapshotCapabilityRequest,
)
from app.market_data.policies import DataPurpose, RealtimePolicy
from app.market_data.provider_catalog import plan_data_acquisition_v2
from app.us_market.daily_ohlcv_acquisition import (
    USDailyOhlcvAcquisitionExecutor,
    USProviderPayload,
)
from app.us_market.intraday_acquisition import USIntradayAcquisitionExecutor
from app.us_market.market_data.descriptors import (
    MASSIVE_INDEX_DAILY_DESCRIPTOR,
    MASSIVE_INDEX_DAILY_RESOURCE_ID,
    MASSIVE_INDEX_QUOTE_DESCRIPTOR,
    MASSIVE_INDEX_QUOTE_RESOURCE_ID,
)


EASTERN = ZoneInfo("America/New_York")


def _index(symbol: str) -> InstrumentKey:
    return InstrumentKey(
        market=Market.US,
        symbol=symbol,
        instrument_type=InstrumentType.INDEX,
        venue="INDEX",
    )


def test_massive_delayed_snapshot_cannot_satisfy_require_live() -> None:
    now = datetime(2026, 9, 1, 20, 0, tzinfo=timezone.utc)
    requirement = DataRequirementV2(
        target=InstrumentTarget(instrument=_index("^GSPC")),
        request=SnapshotCapabilityRequest(
            capability_id="quote.snapshot",
            required_fields=("last_trade_price",),
        ),
        purpose=DataPurpose.RESEARCH,
        realtime_policy=RealtimePolicy.REQUIRE_LIVE,
        session=MarketSession.CONTINUOUS,
        requested_at=now,
        freshness=FreshnessRequirement(max_age_seconds=180),
        bounds=RequestBounds(
            max_provider_attempts=1,
            max_external_calls=1,
            max_rows=10,
        ),
    )
    plan = plan_data_acquisition_v2(
        requirement,
        (MASSIVE_INDEX_QUOTE_DESCRIPTOR,),
    )

    result = USIntradayAcquisitionExecutor(
        fetchers={
            MASSIVE_INDEX_QUOTE_RESOURCE_ID: lambda _route, _requirement: (
                {
                    "status": "OK",
                    "results": [
                        {
                            "ticker": "I:SPX",
                            "value": 6512.34,
                            "last_updated": int(now.timestamp() * 1_000_000_000),
                            "timeframe": "DELAYED",
                        }
                    ],
                },
                "https://api.massive.com/v3/snapshot/indices?ticker.any_of=I%3ASPX",
            )
        },
        clock=lambda: now,
    ).acquire_quote_observations(requirement, plan)

    assert result.summary.status.value == "partial"
    assert result.summary.external_calls == 1
    assert result.receipts[0].provider_timeframe is ProviderTimeframe.DELAYED
    assert result.provider_health[0].entitlement is EntitlementStatus.PLAN_RESTRICTED
    assert "MASSIVE_REALTIME_ENTITLEMENT_UNSATISFIED" in result.summary.limitations


def test_massive_daily_canary_preserves_delayed_lineage_and_absent_volume() -> None:
    now = datetime(2026, 9, 2, 8, 0, tzinfo=EASTERN)
    event_at = datetime(2026, 9, 1, 12, 0, tzinfo=EASTERN)
    requirement = DataRequirementV2(
        target=InstrumentTarget(instrument=_index("^IXIC")),
        request=BarCapabilityRequest(
            capability_id="daily.ohlcv",
            interval="1d",
            start_at=datetime.combine(event_at.date(), time(9, 30), tzinfo=EASTERN),
            end_at=datetime.combine(event_at.date(), time(16), tzinfo=EASTERN),
            max_bars=1,
            completed_only=True,
            price_basis="raw",
        ),
        purpose=DataPurpose.RESEARCH,
        realtime_policy=RealtimePolicy.PREFER_LIVE,
        session=MarketSession.CLOSED,
        requested_at=now,
        freshness=FreshnessRequirement(max_age_seconds=86_400),
        bounds=RequestBounds(
            max_provider_attempts=1,
            max_external_calls=1,
            max_rows=10,
        ),
    )
    plan = plan_data_acquisition_v2(
        requirement,
        (MASSIVE_INDEX_DAILY_DESCRIPTOR,),
    )

    result = USDailyOhlcvAcquisitionExecutor(
        fetchers={
            MASSIVE_INDEX_DAILY_RESOURCE_ID: lambda _route, _requirement: USProviderPayload(
                payload={
                    "status": "DELAYED",
                    "ticker": "I:COMP",
                    "results": [
                        {
                            "t": int(event_at.timestamp() * 1000),
                            "o": 22000,
                            "h": 22200,
                            "l": 21900,
                            "c": 22150,
                        }
                    ],
                },
                url="https://api.massive.com/v2/aggs/ticker/I%3ACOMP/range/1/day",
            )
        },
        clock=lambda: now,
    ).acquire_bar_observations(requirement, plan)

    assert result.summary.status.value == "completed"
    assert len(result.observations) == 1
    assert result.observations[0].volume is None
    assert result.observations[0].volume_status == "not_applicable"
    assert result.receipts[0].provider_timeframe is ProviderTimeframe.DELAYED
    assert "MASSIVE_PROVIDER_TIMEFRAME_DELAYED" in result.summary.limitations
