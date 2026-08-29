"""Stable Gateway-first US daily OHLCV read and explicit refresh service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.market_data.contracts import ResolvedEvidenceStatus
from app.market_data.gateway import MarketDataGateway
from app.market_data.integration_contracts import (
    BarCapabilityRequest,
    BarCoverageRequirement,
    DataRequirementV2,
    FreshnessRequirement,
    InstrumentTarget,
    MarketDataResultV1,
    RequestBounds,
)
from app.market_data.policies import DataPurpose, RealtimePolicy
from app.market_data.provider_catalog import ProviderCapabilityDescriptorV2
from app.market_data.rollout import CapabilityRolloutState
from app.us_market.daily_market_state import (
    USCompletedDailyState,
    USInstrumentIdentity,
    expected_us_completed_daily_state,
    resolve_us_instrument_identity,
)
from app.us_market.daily_ohlcv_acquisition import USDailyOhlcvAcquisitionExecutor
from app.us_market.daily_rollout import require_us_daily_acquisition_enabled
from app.us_market.daily_price_candidates import USCompletedDailyCandidateReader
from app.us_market.daily_price_repository import USDailyBarRepository
from app.us_market.daily_price_transaction import USDailyPriceTransaction
from app.us_market.market_data.descriptors import (
    US_DAILY_PROVIDER_DESCRIPTORS,
    us_daily_history_descriptors,
)
from app.us_market.market_data_projection import project_resolved_us_daily_bars
from app.us_market.ohlc_continuity import build_us_daily_continuity
from app.us_market.trading_calendar import (
    previous_us_trading_day,
    us_daily_price_finalization_time,
    us_session_close_time,
)


US_EASTERN = ZoneInfo("America/New_York")


@dataclass(frozen=True, slots=True)
class USDailyPlatformResult:
    identity: USInstrumentIdentity
    expected_state: USCompletedDailyState
    result: MarketDataResultV1
    projection: dict
    postcondition_satisfied: bool
    temporal_postcondition_satisfied: bool
    coverage_postcondition_satisfied: bool


class USDailyOhlcvPlatform:
    def __init__(
        self,
        db: Session,
        *,
        gateway: MarketDataGateway | None = None,
        acquisition: USDailyOhlcvAcquisitionExecutor | None = None,
        transaction: USDailyPriceTransaction | None = None,
        rollout_state: CapabilityRolloutState | None = None,
        descriptors: tuple[ProviderCapabilityDescriptorV2, ...] | None = None,
    ) -> None:
        self._db = db
        self._gateway = gateway or MarketDataGateway()
        self._reader = USCompletedDailyCandidateReader(USDailyBarRepository(db))
        self._acquisition = acquisition or USDailyOhlcvAcquisitionExecutor()
        self._transaction = transaction or USDailyPriceTransaction(db)
        self._rollout_state = rollout_state
        self._descriptors = descriptors or US_DAILY_PROVIDER_DESCRIPTORS

    def _requirement(
        self,
        *,
        identity: USInstrumentIdentity,
        expected_date: date,
        bars: int,
        requested_at: datetime,
        allow_acquisition: bool,
        max_provider_calls: int,
        require_history_coverage: bool,
    ) -> DataRequirementV2:
        if bars < 1 or bars > 5000:
            raise ValueError("bars must be between 1 and 5000")
        start_date = expected_date - timedelta(days=max(14, bars * 3))
        return DataRequirementV2(
            target=InstrumentTarget(instrument=identity.instrument),
            request=BarCapabilityRequest(
                capability_id="daily.ohlcv",
                interval="1d",
                start_at=datetime.combine(
                    start_date,
                    time(9, 30),
                    tzinfo=US_EASTERN,
                ),
                end_at=datetime.combine(
                    expected_date,
                    us_session_close_time(expected_date),
                    tzinfo=US_EASTERN,
                ),
                max_bars=bars,
                completed_only=True,
                price_basis="raw",
                coverage=(
                    BarCoverageRequirement(minimum_bar_count=bars)
                    if require_history_coverage
                    else None
                ),
            ),
            purpose=DataPurpose.RESEARCH,
            realtime_policy=(
                RealtimePolicy.PREFER_LIVE
                if allow_acquisition
                else RealtimePolicy.COMPLETED_SESSION
            ),
            session="closed",
            requested_at=requested_at,
            freshness=FreshnessRequirement(max_age_seconds=14 * 86400),
            bounds=RequestBounds(
                max_provider_attempts=max_provider_calls if allow_acquisition else 0,
                max_external_calls=max_provider_calls if allow_acquisition else 0,
                max_subscriptions=0,
                max_candidates=8,
                max_rows=min(5000, max(bars * 6, 30)),
            ),
        )

    def _run(
        self,
        *,
        symbol: str,
        bars: int,
        now: datetime,
        to_date: date | None,
        allow_acquisition: bool,
        max_provider_calls: int = 0,
        require_history_coverage: bool = False,
    ) -> USDailyPlatformResult:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        identity = resolve_us_instrument_identity(self._db, symbol)
        current_state = expected_us_completed_daily_state(now=now)
        expected_date = (
            previous_us_trading_day(to_date, include_value=True)
            if to_date is not None
            else current_state.expected_trade_date
        )
        expected_state = current_state.model_copy(
            update={
                "expected_trade_date": expected_date,
                "release_at": us_daily_price_finalization_time(expected_date),
                "reason_code": (
                    "REQUESTED_COMPLETED_SESSION"
                    if to_date is not None
                    else current_state.reason_code
                ),
            }
        )
        requirement = self._requirement(
            identity=identity,
            expected_date=expected_date,
            bars=bars,
            requested_at=now,
            allow_acquisition=allow_acquisition,
            max_provider_calls=max_provider_calls,
            require_history_coverage=require_history_coverage,
        )
        active_descriptors = (
            us_daily_history_descriptors(self._descriptors)
            if allow_acquisition and require_history_coverage
            else self._descriptors
        )
        result = self._gateway.resolve_bars(
            requirement,
            reader=self._reader,
            descriptors=(active_descriptors if allow_acquisition else ()),
            acquisition_port=(self._acquisition if allow_acquisition else None),
            transaction_port=(self._transaction if allow_acquisition else None),
        )
        projection = project_resolved_us_daily_bars(result.resolved, max_bars=bars)
        latest_date = (
            result.resolved.bars[-1].end_at.astimezone(US_EASTERN).date()
            if result.resolved.bars
            else None
        )
        temporal_postcondition = (
            latest_date == expected_date
            and result.resolved.health.status
            in {ResolvedEvidenceStatus.SELECTED, ResolvedEvidenceStatus.FALLBACK}
            and result.resolved.health.research_usable
        )
        continuity = build_us_daily_continuity(
            available_dates=(
                bar.end_at.astimezone(US_EASTERN).date()
                for bar in result.resolved.bars
            ),
            expected_data_date=expected_date,
            available_bar_count=len(result.resolved.bars),
            requested_bar_count=bars,
            history_fetch_scope="canonical_cache",
        )
        coverage_postcondition = continuity["coverage_status"] == "complete"
        postcondition = temporal_postcondition and (
            coverage_postcondition if require_history_coverage else True
        )
        freshness_status = (
            "missing"
            if latest_date is None
            else "stale"
            if latest_date < expected_date
            else "future"
            if latest_date > expected_date
            else "current"
        )
        facts_usable = bool(result.resolved.health.facts_usable)
        decision_usable = bool(temporal_postcondition)
        projection.update(
            {
                "expected_trade_date": expected_date.isoformat(),
                "latest_trade_date": latest_date.isoformat() if latest_date else None,
                "freshness_status": freshness_status,
                **continuity,
                "request_coverage_status": continuity["coverage_status"],
                "temporal_postcondition_satisfied": temporal_postcondition,
                "coverage_postcondition_satisfied": coverage_postcondition,
                "is_current": temporal_postcondition,
                "refresh_recommended": not temporal_postcondition,
                "coverage_refresh_recommended": not coverage_postcondition,
                "facts_usable": facts_usable,
                "decision_usable": decision_usable,
                "usability_status": (
                    "decision_usable"
                    if decision_usable
                    else "facts_only"
                    if facts_usable
                    else "unusable"
                ),
                "volume_applicability": identity.volume_applicability,
                "identity_source": identity.identity_source,
            }
        )
        return USDailyPlatformResult(
            identity=identity,
            expected_state=expected_state,
            result=result,
            projection=projection,
            postcondition_satisfied=postcondition,
            temporal_postcondition_satisfied=temporal_postcondition,
            coverage_postcondition_satisfied=coverage_postcondition,
        )

    def read(
        self,
        *,
        symbol: str,
        bars: int = 90,
        now: datetime | None = None,
        to_date: date | None = None,
    ) -> USDailyPlatformResult:
        return self._run(
            symbol=symbol,
            bars=bars,
            now=now or datetime.now(timezone.utc),
            to_date=to_date,
            allow_acquisition=False,
            max_provider_calls=0,
            require_history_coverage=False,
        )

    def refresh(
        self,
        *,
        symbol: str,
        bars: int = 90,
        now: datetime | None = None,
        to_date: date | None = None,
        max_provider_calls: int = 2,
    ) -> USDailyPlatformResult:
        if max_provider_calls < 1 or max_provider_calls > 2:
            raise ValueError("max_provider_calls must be between 1 and 2")
        require_us_daily_acquisition_enabled(
            symbol,
            state=self._rollout_state,
        )
        return self._run(
            symbol=symbol,
            bars=bars,
            now=now or datetime.now(timezone.utc),
            to_date=to_date,
            allow_acquisition=True,
            max_provider_calls=max_provider_calls,
            require_history_coverage=False,
        )

    def ensure_history_coverage(
        self,
        *,
        symbol: str,
        bars: int,
        now: datetime | None = None,
        to_date: date | None = None,
        max_provider_calls: int = 2,
    ) -> USDailyPlatformResult:
        """Explicitly ensure one provider-coherent completed Daily history."""

        if max_provider_calls < 1 or max_provider_calls > 2:
            raise ValueError("max_provider_calls must be between 1 and 2")
        require_us_daily_acquisition_enabled(
            symbol,
            state=self._rollout_state,
        )
        return self._run(
            symbol=symbol,
            bars=bars,
            now=now or datetime.now(timezone.utc),
            to_date=to_date,
            allow_acquisition=True,
            max_provider_calls=max_provider_calls,
            require_history_coverage=True,
        )


def refresh_us_daily_ohlcv(
    db: Session,
    *,
    symbol: str,
    outputsize: str = "compact",
    adjusted: bool = False,
) -> dict:
    """Run the canonical explicit refresh and retain the legacy command shape."""

    if outputsize not in {"compact", "full"}:
        raise ValueError("outputsize must be one of: compact, full")
    if adjusted:
        raise ValueError(
            "canonical US daily refresh currently supports price_basis=raw only"
        )
    refreshed = USDailyOhlcvPlatform(db).refresh(
        symbol=symbol,
        bars=5000 if outputsize == "full" else 90,
    )
    persistence = refreshed.result.persistence
    acquisition = refreshed.result.acquisition
    observation_count = (
        persistence.observations_written + persistence.observations_unchanged
    )
    return {
        "status": (
            "success" if refreshed.postcondition_satisfied else "partial_success"
        ),
        "provider": refreshed.projection.get("selected_provider") or "unresolved",
        "symbol": refreshed.identity.instrument.symbol,
        "fetched_count": observation_count,
        "eligible_count": observation_count,
        "skipped_count": len(refreshed.result.candidate_rejections),
        "inserted_count": persistence.observations_inserted,
        "updated_count": persistence.observations_updated,
        "unchanged_count": persistence.observations_unchanged,
        "expected_trade_date": refreshed.expected_state.expected_trade_date,
        "latest_eligible_trade_date": refreshed.projection.get("latest_trade_date"),
        "selected_event_at": refreshed.projection.get("selected_event_at"),
        "selected_source": refreshed.projection.get("selected_source"),
        "fallback_used": bool(refreshed.projection.get("fallback_used")),
        "selection_reason": refreshed.projection.get("selection_reason"),
        "external_call_count": acquisition.external_calls,
        "providers_attempted": list(acquisition.providers_attempted),
        "resource_attempts": [
            {
                "provider": attempt.provider,
                "resource_id": attempt.resource_id,
            }
            for attempt in acquisition.resource_attempts
        ],
        "persistence_committed": persistence.committed,
        "postcondition_satisfied": refreshed.postcondition_satisfied,
        "raw_result_ids": list(persistence.raw_result_ids),
        "warnings": list(
            dict.fromkeys(
                (
                    *refreshed.result.limitations,
                    *refreshed.projection.get("limitations", []),
                    *persistence.limitations,
                )
            )
        ),
        "message": (
            "Canonical US daily refresh satisfied mandatory Gateway reread."
            if refreshed.postcondition_satisfied
            else "Canonical US daily refresh did not satisfy the expected-session postcondition."
        ),
    }


__all__ = [
    "USDailyOhlcvPlatform",
    "USDailyPlatformResult",
    "refresh_us_daily_ohlcv",
]
