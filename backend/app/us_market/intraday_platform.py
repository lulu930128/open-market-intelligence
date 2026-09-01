"""Gateway-first US quote and intraday application boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.market_data.contracts import (
    BarObservation,
    MarketSession,
    ResolvedEvidenceStatus,
)
from app.market_data.gateway import MarketDataGateway
from app.market_data.integration_contracts import (
    BarCapabilityRequest,
    DataRequirementV2,
    EvidenceTarget,
    FreshnessBasis,
    FreshnessRequirement,
    InstrumentTarget,
    MarketDataResultV1,
    QualityRequirement,
    RequestBounds,
    SnapshotCapabilityRequest,
)
from app.market_data.policies import DataPurpose, RealtimePolicy
from app.market_data.provider_catalog import ProviderCapabilityDescriptorV2
from app.us_market.daily_market_state import USInstrumentIdentity, resolve_us_instrument_identity
from app.us_market.intraday_acquisition import USIntradayAcquisitionExecutor
from app.us_market.intraday_profiles import (
    US_BOOTSTRAP_INTRADAY_PROFILE,
    US_RECURRING_INTRADAY_PROFILE,
    USIntradayOperationProfile,
)
from app.us_market.intraday_repository import (
    USIntradayBarRepository,
    USIntradayVolumeSession,
    USQuoteRepository,
)
from app.us_market.intraday_transaction import USIntradayBarTransaction, USQuoteTransaction
from app.us_market.market_data.descriptors import US_INTRADAY_PROVIDER_DESCRIPTORS, US_QUOTE_PROVIDER_DESCRIPTORS
from app.us_market.market_data_projection import project_resolved_us_bars, project_resolved_us_quote
from app.us_market.session_policy import us_session_for_timestamp
from app.us_market.trading_calendar import is_us_trading_day


US_EASTERN = ZoneInfo("America/New_York")
US_INTRADAY_CACHE_HISTORY_DAYS = 35
# Compatibility export for callers that only need the historical hard ceiling.
US_INTRADAY_ACQUISITION_HISTORY_DAYS = (
    US_BOOTSTRAP_INTRADAY_PROFILE.acquisition_history_days
)
@dataclass(frozen=True, slots=True)
class USIntradayPlatformResult:
    identity: USInstrumentIdentity
    result: MarketDataResultV1
    projection: dict
    profile_id: str
    postcondition_satisfied: bool
    postcondition_reasons: tuple[str, ...] = ()


def _postcondition(
    result: MarketDataResultV1,
    *,
    profile: USIntradayOperationProfile,
) -> tuple[bool, tuple[str, ...]]:
    resolved = result.resolved
    selected = bool(
        getattr(resolved, "quote", None) is not None
        or getattr(resolved, "bars", ())
    )
    health = resolved.health
    reasons: list[str] = []
    if not selected:
        reasons.append("REQUIRED_EVIDENCE_MISSING")
    if not health.facts_usable:
        reasons.append("REQUIRED_FACTS_UNUSABLE")
    if health.status is ResolvedEvidenceStatus.POLICY_UNSATISFIED:
        reasons.append("RESOLUTION_POLICY_UNSATISFIED")
    if health.status is ResolvedEvidenceStatus.STALE:
        if (
            profile.evidence_target is EvidenceTarget.LATEST_AVAILABLE
            and selected
            and health.facts_usable
        ):
            reasons.append("LATEST_AVAILABLE_STALE_ACCEPTED")
        else:
            reasons.append("FRESHNESS_POSTCONDITION_UNSATISFIED")
    blocking = {
        "REQUIRED_EVIDENCE_MISSING",
        "REQUIRED_FACTS_UNUSABLE",
        "RESOLUTION_POLICY_UNSATISFIED",
        "FRESHNESS_POSTCONDITION_UNSATISFIED",
    }
    return not any(reason in blocking for reason in reasons), tuple(reasons)


def _session(now: datetime) -> MarketSession:
    local = now.astimezone(US_EASTERN)
    if not is_us_trading_day(local.date()):
        return MarketSession.CLOSED
    return us_session_for_timestamp(now)


def _baseline(current_volume: int | None, samples: list[tuple[object, int]], days: int) -> dict:
    selected = samples[-days:]
    values = [value for _trade_date, value in selected]
    baseline = float(median(values)) if values else None
    return {
        "requested_days": days,
        "sample_days": len(values),
        "median_cumulative_volume": baseline,
        "pace_ratio": (
            current_volume / baseline
            if current_volume is not None and baseline not in {None, 0}
            else None
        ),
        "sample_trade_dates": [str(trade_date) for trade_date, _value in selected],
    }


def build_us_resolved_volume_pace(
    *,
    symbol: str,
    intraday_bars: tuple[BarObservation, ...],
    daily_bars: tuple[BarObservation, ...],
    historical_sessions: tuple[USIntradayVolumeSession, ...] | None = None,
) -> dict:
    """Build volume pace only from already-resolved Intraday and Daily series."""

    regular = [
        bar
        for bar in intraday_bars
        if bar.volume is not None
        and us_session_for_timestamp(bar.start_at) is MarketSession.CONTINUOUS
    ]
    if not regular:
        return {
            "kind": "stock_same_time_volume_pace",
            "stock_id": symbol,
            "market": "US",
            "session_scope": "regular",
            "status": "empty",
            "current_cumulative_volume": None,
            "same_time_baseline_5d": _baseline(None, [], 5),
            "same_time_baseline_20d": _baseline(None, [], 20),
            "warnings": ["Resolved regular-session intraday volume is unavailable."],
            "source_refs": [
                {"type": "dataset", "name": "us.intraday.bars"},
                {"type": "dataset", "name": "us.daily.ohlcv"},
            ],
        }
    grouped: dict[object, list[BarObservation]] = {}
    for bar in regular:
        trade_date = bar.start_at.astimezone(US_EASTERN).date()
        grouped.setdefault(trade_date, []).append(bar)
    current_date = max(grouped)
    current_bars = sorted(grouped[current_date], key=lambda item: item.start_at)
    latest = current_bars[-1].start_at.astimezone(US_EASTERN)
    comparison = (latest.hour, latest.minute)
    current_volume = sum(int(bar.volume.value) for bar in current_bars if bar.volume is not None)
    daily_totals = {
        bar.end_at.astimezone(US_EASTERN).date(): int(bar.volume.value)
        for bar in daily_bars
        if bar.volume is not None
    }
    samples: list[tuple[object, int]] = []
    incomplete: list[str] = []
    missing_daily: list[str] = []
    historical = (
        tuple(
            (
                item.trade_date,
                item.cumulative_volume,
                item.total_volume,
            )
            for item in historical_sessions
            if item.trade_date < current_date
        )
        if historical_sessions is not None
        else tuple(
            (
                trade_date,
                sum(
                    int(bar.volume.value)
                    for bar in grouped[trade_date]
                    if bar.volume is not None
                    and (
                        bar.start_at.astimezone(US_EASTERN).hour,
                        bar.start_at.astimezone(US_EASTERN).minute,
                    )
                    <= comparison
                ),
                sum(
                    int(bar.volume.value)
                    for bar in grouped[trade_date]
                    if bar.volume is not None
                ),
            )
            for trade_date in sorted(date for date in grouped if date < current_date)
        )
    )
    for trade_date, cumulative, intraday_total in historical:
        daily_total = daily_totals.get(trade_date)
        if daily_total is None or daily_total <= 0:
            missing_daily.append(str(trade_date))
            continue
        completion_ratio = intraday_total / daily_total
        if not 0.85 <= completion_ratio <= 1.15:
            incomplete.append(str(trade_date))
            continue
        samples.append((trade_date, cumulative))
    baseline_5d = _baseline(current_volume, samples, 5)
    baseline_20d = _baseline(current_volume, samples, 20)
    warnings: list[str] = []
    if baseline_5d["sample_days"] < 5:
        warnings.append("Fewer than 5 resolved complete prior sessions are available; volume pace is provisional.")
    if baseline_20d["sample_days"] < 20:
        warnings.append("Fewer than 20 resolved complete prior sessions are available; the 20-day volume pace baseline is provisional.")
    if incomplete:
        warnings.append(f"Excluded {len(incomplete)} incomplete resolved intraday session(s) after Daily reconciliation.")
    if missing_daily:
        warnings.append(f"Excluded {len(missing_daily)} session(s) without resolved Daily volume.")
    if any(bar.lineage.provider == "twelve_data" for bar in current_bars):
        warnings.append("Twelve Data US volume is partial provider evidence and is not consolidated SIP volume.")
    return {
        "kind": "stock_same_time_volume_pace",
        "stock_id": symbol,
        "market": "US",
        "session_scope": "regular",
        "status": (
            "ready"
            if baseline_5d["sample_days"] >= 5
            and baseline_20d["sample_days"] >= 20
            else "partial"
        ),
        "as_of": latest.isoformat(),
        "trade_date": str(current_date),
        "comparison_minute": latest.strftime("%H:%M"),
        "calculation_basis": "Resolved current cumulative share volume versus resolved complete prior sessions at the same US market minute.",
        "current_cumulative_volume": current_volume,
        "same_time_baseline_5d": baseline_5d,
        "same_time_baseline_20d": baseline_20d,
        "excluded_incomplete_trade_dates": incomplete,
        "excluded_missing_daily_trade_dates": missing_daily,
        "warnings": warnings,
        "source_refs": [
            {"type": "dataset", "name": "us.intraday.bars"},
            {"type": "dataset", "name": "us.daily.ohlcv"},
        ],
    }


class USIntradayMarketPlatform:
    def __init__(
        self,
        db: Session,
        *,
        gateway: MarketDataGateway | None = None,
        acquisition: USIntradayAcquisitionExecutor | None = None,
        quote_transaction: USQuoteTransaction | None = None,
        bar_transaction: USIntradayBarTransaction | None = None,
        quote_descriptors: tuple[ProviderCapabilityDescriptorV2, ...] | None = None,
        bar_descriptors: tuple[ProviderCapabilityDescriptorV2, ...] | None = None,
    ) -> None:
        self._db = db
        self._gateway = gateway or MarketDataGateway()
        self._acquisition = acquisition or USIntradayAcquisitionExecutor()
        self._quote_reader = USQuoteRepository(db)
        self._bar_reader = USIntradayBarRepository(db)
        self._quote_transaction = quote_transaction or USQuoteTransaction(db)
        self._bar_transaction = bar_transaction or USIntradayBarTransaction(db)
        self._quote_descriptors = quote_descriptors or US_QUOTE_PROVIDER_DESCRIPTORS
        self._bar_descriptors = bar_descriptors or US_INTRADAY_PROVIDER_DESCRIPTORS

    @staticmethod
    def _validate_now(now: datetime) -> None:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")

    def _quote_requirement(self, identity: USInstrumentIdentity, *, now: datetime, allow_acquisition: bool, require_live: bool, max_provider_calls: int, profile: USIntradayOperationProfile) -> DataRequirementV2:
        return DataRequirementV2(
            target=InstrumentTarget(instrument=identity.instrument),
            request=SnapshotCapabilityRequest(
                capability_id="quote.snapshot",
                required_fields=("last_trade_price",),
            ),
            purpose=profile.purpose if allow_acquisition else DataPurpose.VIEWER,
            realtime_policy=RealtimePolicy.REQUIRE_LIVE if require_live else RealtimePolicy.PREFER_LIVE if allow_acquisition else RealtimePolicy.CACHE_ONLY,
            session=_session(now),
            requested_at=now,
            freshness=FreshnessRequirement(
                max_age_seconds=(
                    profile.producer_refresh_due_seconds
                    if allow_acquisition
                    else profile.consumer_stale_after_seconds
                ),
                basis=FreshnessBasis.FETCHED_TIME,
                evidence_target=profile.evidence_target,
            ),
            quality=QualityRequirement(required_fields=("last_trade_price",), allow_partial=True, require_canonical_lineage=True),
            bounds=RequestBounds(
                max_provider_attempts=max_provider_calls if allow_acquisition else 0,
                max_external_calls=max_provider_calls if allow_acquisition else 0,
                max_subscriptions=0,
                max_candidates=8,
                max_rows=64,
            ),
        )

    def _bar_requirement(
        self,
        identity: USInstrumentIdentity,
        *,
        now: datetime,
        bars: int,
        history_days: int,
        allow_acquisition: bool,
        require_live: bool,
        max_provider_calls: int,
        profile: USIntradayOperationProfile = US_RECURRING_INTRADAY_PROFILE,
    ) -> DataRequirementV2:
        if bars < 1 or bars > 5000:
            raise ValueError("bars must be between 1 and 5000")
        if history_days < 1 or history_days > US_INTRADAY_CACHE_HISTORY_DAYS:
            raise ValueError("history_days exceeds the bounded US intraday cache horizon")
        return DataRequirementV2(
            target=InstrumentTarget(instrument=identity.instrument),
            request=BarCapabilityRequest(
                capability_id="intraday.bars",
                interval="1m",
                start_at=now - timedelta(days=history_days),
                end_at=now + timedelta(minutes=1),
                max_bars=bars,
                completed_only=False,
                price_basis="raw",
            ),
            purpose=profile.purpose if allow_acquisition else DataPurpose.VIEWER,
            realtime_policy=RealtimePolicy.REQUIRE_LIVE if require_live else RealtimePolicy.PREFER_LIVE if allow_acquisition else RealtimePolicy.CACHE_ONLY,
            session=_session(now),
            requested_at=now,
            freshness=FreshnessRequirement(
                max_age_seconds=(
                    profile.producer_refresh_due_seconds
                    if allow_acquisition
                    else profile.consumer_stale_after_seconds
                ),
                basis=FreshnessBasis.EVENT_TIME,
                evidence_target=profile.evidence_target,
            ),
            quality=QualityRequirement(required_fields=("open_price", "high_price", "low_price", "close_price"), allow_partial=True, require_canonical_lineage=True),
            bounds=RequestBounds(
                max_provider_attempts=max_provider_calls if allow_acquisition else 0,
                max_external_calls=max_provider_calls if allow_acquisition else 0,
                max_subscriptions=0,
                max_candidates=8,
                max_rows=min(5000, max(bars * len(self._bar_descriptors), 64)),
            ),
        )

    def _platform_result(
        self,
        *,
        identity: USInstrumentIdentity,
        result: MarketDataResultV1,
        projection: dict,
        profile: USIntradayOperationProfile,
    ) -> USIntradayPlatformResult:
        satisfied, reasons = _postcondition(result, profile=profile)
        capability_id = result.requirement.request.capability_id
        descriptors = (
            self._quote_descriptors
            if capability_id == "quote.snapshot"
            else self._bar_descriptors
        )
        interval = getattr(result.requirement.request, "interval", None)
        eligible_providers = tuple(
            dict.fromkeys(
                descriptor.provider_key
                for descriptor in descriptors
                if identity.instrument.instrument_type in descriptor.instrument_types
                and (not interval or not descriptor.intervals or interval in descriptor.intervals)
            )
        )
        single_source = len(eligible_providers) == 1
        limitations = list(projection.get("limitations") or [])
        if single_source and "US_SINGLE_ELIGIBLE_PROVIDER" not in limitations:
            limitations.append("US_SINGLE_ELIGIBLE_PROVIDER")
        projection.update(
            {
                "eligible_providers": list(eligible_providers),
                "eligible_provider_count": len(eligible_providers),
                "single_source": single_source,
                "limitations": limitations,
            }
        )
        return USIntradayPlatformResult(
            identity=identity,
            result=result,
            projection=projection,
            profile_id=profile.profile_id,
            postcondition_satisfied=satisfied,
            postcondition_reasons=reasons,
        )

    def read_quote(self, *, symbol: str, now: datetime | None = None, profile: USIntradayOperationProfile = US_RECURRING_INTRADAY_PROFILE) -> USIntradayPlatformResult:
        requested_at = now or datetime.now(timezone.utc)
        self._validate_now(requested_at)
        identity = resolve_us_instrument_identity(self._db, symbol)
        requirement = self._quote_requirement(identity, now=requested_at, allow_acquisition=False, require_live=False, max_provider_calls=0, profile=profile)
        result = self._gateway.resolve_quote(requirement, reader=self._quote_reader)
        return self._platform_result(identity=identity, result=result, projection=project_resolved_us_quote(result.resolved), profile=profile)

    def refresh_quote(self, *, symbol: str, now: datetime | None = None, require_live: bool = False, max_provider_calls: int = 2, profile: USIntradayOperationProfile = US_RECURRING_INTRADAY_PROFILE) -> USIntradayPlatformResult:
        if max_provider_calls < 1 or max_provider_calls > 2:
            raise ValueError("max_provider_calls must be between 1 and 2")
        requested_at = now or datetime.now(timezone.utc)
        self._validate_now(requested_at)
        identity = resolve_us_instrument_identity(self._db, symbol)
        requirement = self._quote_requirement(identity, now=requested_at, allow_acquisition=True, require_live=require_live, max_provider_calls=max_provider_calls, profile=profile)
        result = self._gateway.resolve_quote(requirement, reader=self._quote_reader, descriptors=self._quote_descriptors, acquisition_port=self._acquisition, transaction_port=self._quote_transaction)
        return self._platform_result(identity=identity, result=result, projection=project_resolved_us_quote(result.resolved), profile=profile)

    def read_intraday_bars(self, *, symbol: str, bars: int = 500, now: datetime | None = None, profile: USIntradayOperationProfile = US_RECURRING_INTRADAY_PROFILE) -> USIntradayPlatformResult:
        requested_at = now or datetime.now(timezone.utc)
        self._validate_now(requested_at)
        identity = resolve_us_instrument_identity(self._db, symbol)
        requirement = self._bar_requirement(
            identity,
            now=requested_at,
            bars=bars,
            history_days=US_INTRADAY_CACHE_HISTORY_DAYS,
            allow_acquisition=False,
            require_live=False,
            max_provider_calls=0,
            profile=profile,
        )
        result = self._gateway.resolve_bars(requirement, reader=self._bar_reader)
        return self._platform_result(identity=identity, result=result, projection=project_resolved_us_bars(result.resolved, max_bars=bars), profile=profile)

    def read_volume_sessions(
        self,
        *,
        symbol: str,
        provider: str,
        source: str,
        current_trade_date,
        comparison_time,
        max_sessions: int = 20,
    ) -> tuple[USIntradayVolumeSession, ...]:
        identity = resolve_us_instrument_identity(self._db, symbol)
        return self._bar_reader.read_volume_sessions(
            instrument=identity.instrument,
            provider=provider,
            source=source,
            current_trade_date=current_trade_date,
            comparison_time=comparison_time,
            lookback_days=US_INTRADAY_CACHE_HISTORY_DAYS,
            max_sessions=max_sessions,
        )

    def refresh_intraday_bars(self, *, symbol: str, bars: int = 500, now: datetime | None = None, require_live: bool = False, max_provider_calls: int = 2, profile: USIntradayOperationProfile = US_RECURRING_INTRADAY_PROFILE) -> USIntradayPlatformResult:
        if max_provider_calls < 1 or max_provider_calls > 2:
            raise ValueError("max_provider_calls must be between 1 and 2")
        requested_at = now or datetime.now(timezone.utc)
        self._validate_now(requested_at)
        identity = resolve_us_instrument_identity(self._db, symbol)
        requirement = self._bar_requirement(
            identity,
            now=requested_at,
            bars=bars,
            history_days=US_INTRADAY_CACHE_HISTORY_DAYS,
            allow_acquisition=True,
            require_live=require_live,
            max_provider_calls=max_provider_calls,
            profile=profile,
        )
        acquisition_requirement = self._bar_requirement(
            identity,
            now=requested_at,
            bars=bars,
            history_days=profile.acquisition_history_days,
            allow_acquisition=True,
            require_live=require_live,
            max_provider_calls=max_provider_calls,
            profile=profile,
        )
        result = self._gateway.resolve_bars(
            requirement,
            reader=self._bar_reader,
            descriptors=self._bar_descriptors,
            acquisition_port=self._acquisition,
            transaction_port=self._bar_transaction,
            acquisition_requirement=acquisition_requirement,
        )
        return self._platform_result(identity=identity, result=result, projection=project_resolved_us_bars(result.resolved, max_bars=bars), profile=profile)


__all__ = [
    "USIntradayMarketPlatform",
    "USIntradayPlatformResult",
    "US_INTRADAY_ACQUISITION_HISTORY_DAYS",
    "US_INTRADAY_CACHE_HISTORY_DAYS",
    "build_us_resolved_volume_pace",
]
