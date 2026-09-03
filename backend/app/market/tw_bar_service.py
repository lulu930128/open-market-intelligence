"""Single cache-only outward owner for Taiwan Bar series."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import Session

from app.market.daily_ohlcv_platform import build_taiwan_daily_cache_requirement
from app.market.daily_price_candidates import TaiwanCompletedDailyCandidateReader
from app.market.daily_price_repository import TaiwanOfficialDailyBarRepository
from app.market.intraday_repository import TaiwanIntradayBarRepository
from app.market.trading_calendar import (
    TAIWAN_SESSION_CLOSE_TIME,
    TAIWAN_SESSION_OPEN_TIME,
    TAIWAN_TZ,
    is_taiwan_trading_day,
    previous_taiwan_trading_day,
    taiwan_market_session,
    taiwan_presentation_session,
)
from app.market.tw_bar_aggregation import (
    TAIWAN_BAR_AGGREGATION_VERSION,
    TaiwanDailyMaterializationComponentsOverlapError,
    aggregate_completed_session_to_1d,
    aggregate_daily_1d,
    aggregate_intraday_1m,
    continuous_session_coverage,
    observed_trade_coverage,
)
from app.market.tw_bar_contracts import (
    TAIWAN_1M_HISTORY_SLO_TRADING_SESSIONS,
    TAIWAN_HISTORY_SLO_CALENDAR_DAYS,
    TAIWAN_DAILY_INTERVALS,
    TAIWAN_INTRADAY_INTERVALS,
    BarBucketCoverage,
    BarBucketCoverageStatus,
    TaiwanBarSeriesRead,
    TaiwanBarOutwardState,
    TaiwanHistoryCoverage,
    TaiwanHistoryStatus,
    TaiwanCurrentSessionCoverage,
    TaiwanCurrentSessionCoverageStatus,
    TaiwanCurrentSessionSnapshotPhase,
    TaiwanMissingBarRange,
    TaiwanReconciliationStatus,
    TaiwanReleaseStatus,
    TaiwanSessionResolutionManifest,
    normalize_taiwan_bar_interval,
)
from app.market.tw_bar_identity import build_taiwan_bar_series_identity
from app.market.tw_instrument import resolve_taiwan_instrument
from app.market.tw_disposition import get_taiwan_disposition_status
from app.market.tw_instrument_trading_policy import (
    TAIWAN_TRADING_POLICY_VERSION,
    continuous_taiwan_trading_policy,
    is_taiwan_continuous_time_bar_start,
    resolve_taiwan_instrument_trading_policy,
)
from app.market.tw_intraday_capabilities import (
    TW_INTRADAY_BARS_CAPABILITY_ID,
    TW_INTRADAY_DESCRIPTORS,
)
from app.market_data.contracts import (
    AuthorityClass,
    InstrumentType,
    MarketSession,
    ResolvedBarSeries,
)
from app.market_data.gateway import MarketDataGateway
from app.market_data.integration_contracts import (
    BarCapabilityRequest,
    BarSeriesResolutionMode,
    DataRequirementV2,
    FreshnessBasis,
    FreshnessRequirement,
    InstrumentTarget,
    QualityRequirement,
    RequestBounds,
)
from app.market_data.policies import DataPurpose, RealtimePolicy


def _aware_taipei(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Taiwan Bar read timestamps must be timezone-aware")
    return value.astimezone(TAIWAN_TZ)


def _trading_dates(start: date, end: date) -> tuple[date, ...]:
    if start > end:
        raise ValueError("Taiwan Bar from_time cannot be after to_time")
    values: list[date] = []
    cursor = start
    while cursor <= end:
        if is_taiwan_trading_day(cursor):
            values.append(cursor)
        cursor += timedelta(days=1)
    return tuple(values)


def _default_start(requested_interval: str, requested_at: datetime) -> datetime:
    local_now = _aware_taipei(requested_at)
    if requested_interval == "1m":
        trade_date = taiwan_presentation_session(local_now)["trade_date"]
        if not isinstance(trade_date, date):
            raise RuntimeError("Taiwan presentation session returned invalid trade date")
        first = trade_date
        for _ in range(TAIWAN_1M_HISTORY_SLO_TRADING_SESSIONS - 1):
            first = previous_taiwan_trading_day(first, include_value=False)
        return datetime.combine(first, time.min, tzinfo=TAIWAN_TZ)
    days = TAIWAN_HISTORY_SLO_CALENDAR_DAYS[requested_interval]
    return local_now - timedelta(days=days)


def _session_requirement(
    *,
    instrument,
    trade_date: date,
    requested_at: datetime,
    current_session: bool,
) -> DataRequirementV2:
    start_at = datetime.combine(
        trade_date,
        TAIWAN_SESSION_OPEN_TIME,
        tzinfo=TAIWAN_TZ,
    )
    formal_end_at = datetime.combine(
        trade_date,
        TAIWAN_SESSION_CLOSE_TIME,
        tzinfo=TAIWAN_TZ,
    )
    end_at = formal_end_at
    if current_session:
        # Current-session finalized Bars stop at the latest fully elapsed
        # minute. Keep the request valid before the first minute closes.
        latest_closed_boundary = requested_at.replace(second=0, microsecond=0)
        end_at = min(
            formal_end_at,
            max(start_at + timedelta(minutes=1), latest_closed_boundary),
        )
    policy = (
        RealtimePolicy.CACHE_ONLY
        if current_session
        else RealtimePolicy.COMPLETED_SESSION
    )
    return DataRequirementV2(
        target=InstrumentTarget(instrument=instrument),
        request=BarCapabilityRequest(
            capability_id=TW_INTRADAY_BARS_CAPABILITY_ID,
            interval="1m",
            start_at=start_at,
            end_at=end_at,
            max_bars=500,
            completed_only=not current_session,
            price_basis=(
                "raw"
                if instrument.instrument_type is InstrumentType.INDEX
                else "provider_default"
            ),
            series_resolution=BarSeriesResolutionMode.COMPOSE_BY_TIMESTAMP,
        ),
        purpose=DataPurpose.VIEWER,
        realtime_policy=policy,
        session=(taiwan_market_session(requested_at) if current_session else MarketSession.CLOSED),
        requested_at=requested_at,
        freshness=FreshnessRequirement(
            max_age_seconds=300 if current_session else 2_678_400,
            basis=(
                FreshnessBasis.EVENT_TIME
                if current_session
                else FreshnessBasis.COMPLETED_SESSION_DATE
            ),
        ),
        quality=QualityRequirement(
            require_canonical_lineage=True,
            allow_partial=True,
        ),
        # The executable catalog owns provider inventory. A copied literal of
        # three silently discarded Yahoo whenever all four providers existed.
        bounds=RequestBounds(
            max_candidates=len(TW_INTRADAY_DESCRIPTORS),
            max_rows=500,
        ),
    )


def _candidate_id(provider: str, source: str) -> str:
    return f"{provider}:{source}"


def _missing_ranges(
    coverage: tuple[BarBucketCoverage, ...],
) -> tuple[TaiwanMissingBarRange, ...]:
    missing = tuple(
        item
        for item in coverage
        if item.expected_by_trading_policy
        and item.status is BarBucketCoverageStatus.MISSING_EVIDENCE
    )
    if not missing:
        return ()
    ranges: list[TaiwanMissingBarRange] = []
    start = missing[0].bucket_start
    end = missing[0].bucket_end
    count = 1
    for item in missing[1:]:
        if item.bucket_start == end:
            end = item.bucket_end
            count += 1
            continue
        ranges.append(
            TaiwanMissingBarRange(start_at=start, end_at=end, bucket_count=count)
        )
        start = item.bucket_start
        end = item.bucket_end
        count = 1
    ranges.append(TaiwanMissingBarRange(start_at=start, end_at=end, bucket_count=count))
    return tuple(ranges)


def _current_session_snapshot_phase(
    status: TaiwanCurrentSessionCoverageStatus,
    *,
    expected_bucket_count: int,
    observed_bucket_count: int,
    missing_bucket_count: int,
) -> tuple[TaiwanCurrentSessionSnapshotPhase, str]:
    if status in {
        TaiwanCurrentSessionCoverageStatus.COMPLETE_PREFIX,
        TaiwanCurrentSessionCoverageStatus.COMPLETE_SESSION,
    }:
        return (
            TaiwanCurrentSessionSnapshotPhase.READY,
            "TW_CHART_SNAPSHOT_COMPLETE",
        )
    if status is TaiwanCurrentSessionCoverageStatus.PARTIAL_PREFIX:
        return (
            TaiwanCurrentSessionSnapshotPhase.DEGRADED,
            "TW_CHART_SNAPSHOT_PARTIAL_PREFIX",
        )
    if status is TaiwanCurrentSessionCoverageStatus.SPARSE:
        sparse_gap_limit = max(3, (expected_bucket_count + 19) // 20)
        sparse_is_displayable = bool(
            expected_bucket_count
            and observed_bucket_count >= 2
            and observed_bucket_count * 5 >= expected_bucket_count * 4
            and missing_bucket_count <= sparse_gap_limit
        )
        if not sparse_is_displayable:
            return (
                TaiwanCurrentSessionSnapshotPhase.WARMING,
                "TW_CHART_SNAPSHOT_SPARSE_EXCESSIVE_GAPS",
            )
        return (
            TaiwanCurrentSessionSnapshotPhase.DEGRADED,
            "TW_CHART_SNAPSHOT_SPARSE",
        )
    if status is TaiwanCurrentSessionCoverageStatus.TRAILING_WINDOW:
        return (
            TaiwanCurrentSessionSnapshotPhase.WARMING,
            "TW_CHART_SNAPSHOT_TRAILING_ONLY",
        )
    if status is TaiwanCurrentSessionCoverageStatus.PARTIAL_WINDOW:
        return (
            TaiwanCurrentSessionSnapshotPhase.WARMING,
            "TW_CHART_SNAPSHOT_PARTIAL_WINDOW",
        )
    return (
        TaiwanCurrentSessionSnapshotPhase.WARMING,
        "TW_CHART_SNAPSHOT_MISSING",
    )


def _current_session_coverage(
    coverage: tuple[BarBucketCoverage, ...],
    *,
    instrument,
    snapshot_bars,
    trade_date: date,
    instrument_type: InstrumentType,
) -> TaiwanCurrentSessionCoverage:
    expected = tuple(item for item in coverage if item.expected_by_trading_policy)
    observed = tuple(
        item
        for item in expected
        if item.status
        in {
            BarBucketCoverageStatus.OBSERVED_TRADE,
            BarBucketCoverageStatus.VERIFIED_NO_TRADE,
        }
    )
    missing_ranges = _missing_ranges(coverage)
    missing_count = sum(item.bucket_count for item in missing_ranges)
    starts = {item.bucket_start for item in observed}
    first_covered = bool(expected and expected[0].bucket_start in starts)
    last_covered = bool(expected and expected[-1].bucket_start in starts)
    status = (
        TaiwanCurrentSessionCoverageStatus.MISSING
        if expected and not observed
        else TaiwanCurrentSessionCoverageStatus.COMPLETE_PREFIX
        if expected and missing_count == 0
        else TaiwanCurrentSessionCoverageStatus.SPARSE
        if first_covered and last_covered
        else TaiwanCurrentSessionCoverageStatus.TRAILING_WINDOW
        if not first_covered and last_covered
        else TaiwanCurrentSessionCoverageStatus.PARTIAL_PREFIX
        if first_covered
        else TaiwanCurrentSessionCoverageStatus.PARTIAL_WINDOW
        if expected
        else TaiwanCurrentSessionCoverageStatus.MISSING
    )
    repair_recommended = bool(
        missing_count
        and instrument_type in {InstrumentType.STOCK, InstrumentType.ETF}
    )
    snapshot_phase, snapshot_reason = _current_session_snapshot_phase(
        status,
        expected_bucket_count=len(expected),
        observed_bucket_count=len(observed),
        missing_bucket_count=missing_count,
    )
    snapshot_identity = build_taiwan_bar_series_identity(
        instrument=instrument,
        requested_interval="1m",
        base_interval="1m",
        bars=snapshot_bars,
        coverage=coverage,
        aggregation_version=None,
        state={"scope": "current_session_snapshot"},
    )
    snapshot_available_from = snapshot_bars[0].start_at if snapshot_bars else None
    snapshot_available_to = snapshot_bars[-1].end_at if snapshot_bars else None
    expected_from = (
        expected[0].bucket_start
        if expected
        else datetime.combine(trade_date, TAIWAN_SESSION_OPEN_TIME, tzinfo=TAIWAN_TZ)
    )
    expected_to = expected[-1].bucket_end if expected else expected_from
    return TaiwanCurrentSessionCoverage(
        trade_date=trade_date,
        status=status,
        snapshot_phase=snapshot_phase,
        snapshot_revision=snapshot_identity.series_revision,
        snapshot_bar_count=len(snapshot_bars),
        snapshot_available_from=snapshot_available_from,
        snapshot_available_to=snapshot_available_to,
        snapshot_reason_codes=(snapshot_reason,),
        expected_from=expected_from,
        expected_to=expected_to,
        expected_bucket_count=len(expected),
        observed_bucket_count=len(observed),
        missing_bucket_count=missing_count,
        missing_ranges=missing_ranges,
        repair_recommended=repair_recommended,
        repair_operation_id=(
            "tw.refresh_intraday_bars"
            if repair_recommended
            else None
        ),
    )


class TaiwanBarService:
    """Read resolved Base Bars, then derive requested intervals in Backend."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def read_current_session_bars(
        self,
        *,
        instrument_id: str,
        interval: str = "1m",
        limit: int = 5000,
        include_partial: bool = True,
        requested_at: datetime | None = None,
    ) -> TaiwanBarSeriesRead:
        """Read only the Backend-owned Taiwan presentation session."""

        requested_interval = normalize_taiwan_bar_interval(interval)
        if requested_interval not in TAIWAN_INTRADAY_INTERVALS:
            raise ValueError("current_session requires a Taiwan intraday interval")
        local_now, _trade_date, from_time, to_time = taiwan_current_session_bar_window(
            requested_at
        )
        return self.read_bars(
            instrument_id=instrument_id,
            interval=requested_interval,
            from_time=from_time,
            to_time=to_time,
            limit=limit,
            include_partial=include_partial,
            requested_at=local_now,
        )

    def read_bars(
        self,
        *,
        instrument_id: str,
        interval: str,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        limit: int = 5000,
        include_partial: bool = True,
        requested_at: datetime | None = None,
    ) -> TaiwanBarSeriesRead:
        requested_interval = normalize_taiwan_bar_interval(interval)
        if limit < 1 or limit > 5000:
            raise ValueError("limit must be between 1 and 5000")

        if requested_interval in TAIWAN_DAILY_INTERVALS:
            return self._read_daily_bars(
                instrument_id=instrument_id,
                requested_interval=requested_interval,
                from_time=from_time,
                to_time=to_time,
                limit=limit,
                include_partial=include_partial,
                requested_at=requested_at,
            )
        if requested_interval not in TAIWAN_INTRADAY_INTERVALS:
            raise ValueError("unsupported Taiwan Bar interval")

        now = _aware_taipei(requested_at or datetime.now(TAIWAN_TZ))
        requested_to = _aware_taipei(to_time or now)
        requested_from = _aware_taipei(
            from_time or _default_start(requested_interval, requested_to)
        )
        if requested_to <= requested_from:
            raise ValueError("to_time must be after from_time")

        instrument = resolve_taiwan_instrument(self._db, instrument_id)
        trading_policy = (
            continuous_taiwan_trading_policy(
                reason_code="INDEX_CONTINUOUS_TIME_BARS"
            )
            if instrument.instrument_type is InstrumentType.INDEX
            else resolve_taiwan_instrument_trading_policy(
                get_taiwan_disposition_status(
                    instrument.symbol,
                    market=str(instrument.venue or ""),
                    now=now,
                )
            )
        )
        trade_dates = _trading_dates(requested_from.date(), requested_to.date())
        presentation = taiwan_presentation_session(now)
        presentation_date = presentation["trade_date"]
        current_observing = presentation["state"] in {
            "today_pending",
            "observing",
        }

        base_bars = []
        base_coverage = []
        manifests: list[TaiwanSessionResolutionManifest] = []
        limitations: list[str] = []
        if not trading_policy.market_semantics_usable:
            limitations.extend(trading_policy.reason_codes)
        covered_sessions = 0
        current_coverage: TaiwanCurrentSessionCoverage | None = None
        for trade_date in trade_dates:
            current_session = bool(
                current_observing and trade_date == presentation_date
            )
            requirement = _session_requirement(
                instrument=instrument,
                trade_date=trade_date,
                requested_at=now,
                current_session=current_session,
            )
            result = MarketDataGateway().resolve_bars(
                requirement,
                reader=TaiwanIntradayBarRepository(self._db),
            )
            if not isinstance(result.resolved, ResolvedBarSeries):
                raise RuntimeError("Taiwan Bar gateway returned non-Bar payload")
            resolved_session_bars = tuple(result.resolved.bars)
            session_bars = tuple(
                item
                for item in resolved_session_bars
                if is_taiwan_continuous_time_bar_start(item.start_at)
            )
            if len(session_bars) != len(resolved_session_bars):
                limitations.append("TW_CLOSING_AUCTION_TIME_BAR_REJECTED")
            if session_bars:
                covered_sessions += 1
                base_bars.extend(session_bars)
            session_coverage = continuous_session_coverage(
                session_bars,
                trade_date=trade_date,
                trading_policy_version=TAIWAN_TRADING_POLICY_VERSION,
                trading_policy=trading_policy,
                as_of=now,
            )
            base_coverage.extend(session_coverage)

            if current_session:
                current_coverage = _current_session_coverage(
                    session_coverage,
                    instrument=instrument,
                    snapshot_bars=session_bars,
                    trade_date=trade_date,
                    instrument_type=instrument.instrument_type,
                )
                if current_coverage.repair_recommended:
                    limitations.append(
                        "TW_CURRENT_SESSION_BASELINE_REPAIR_RECOMMENDED"
                    )

            contributors = tuple(
                dict.fromkeys(
                    _candidate_id(item.lineage.provider, item.lineage.source)
                    for item in session_bars
                )
            )
            missing_count = sum(
                item.status.value == "missing_evidence" for item in session_coverage
            )
            coverage_status = (
                TaiwanHistoryStatus.MISSING
                if not session_bars
                else TaiwanHistoryStatus.PARTIAL
                if missing_count or not trading_policy.market_semantics_usable
                else TaiwanHistoryStatus.READY
            )
            rejected_candidate_reasons: dict[str, list[str]] = {}
            for item in result.resolved.candidates:
                if item.eligible:
                    continue
                rejected_candidate_reasons.setdefault(
                    _candidate_id(item.provider, item.source),
                    [],
                ).append(item.reason_code)
            for item in result.candidate_rejections:
                rejected_candidate_reasons.setdefault(
                    _candidate_id(item.provider, item.source),
                    [],
                ).append(item.reason_code)
            manifests.append(
                TaiwanSessionResolutionManifest(
                    trade_date=trade_date,
                    resolution_mode=requirement.request.series_resolution,
                    current_session=current_session,
                    selected_candidate_id=None,
                    contributor_candidate_ids=contributors,
                    rejected_candidate_reasons={
                        candidate_id: tuple(dict.fromkeys(reasons))
                        for candidate_id, reasons in rejected_candidate_reasons.items()
                    },
                    filled_bucket_count=result.resolved.composition.filled_bucket_count,
                    conflict_bucket_count=result.resolved.composition.conflict_bucket_count,
                    coverage_status=coverage_status,
                )
            )
            limitations.extend(result.limitations)

        ordered_base = tuple(sorted(base_bars, key=lambda item: item.start_at))
        ordered_coverage = tuple(
            sorted(base_coverage, key=lambda item: item.bucket_start)
        )
        if requested_interval == "1m":
            outward_bars = ordered_base
            outward_coverage = ordered_coverage
            aggregation_version = None
        else:
            outward_bars, outward_coverage = aggregate_intraday_1m(
                ordered_base,
                target_interval=requested_interval,
                bucket_coverage=ordered_coverage,
                as_of=now,
            )
            aggregation_version = TAIWAN_BAR_AGGREGATION_VERSION

        snapshot_bars = tuple(
            item
            for item in outward_bars
            if item.start_at < requested_to and item.end_at > requested_from
            and (include_partial or item.finalization.value != "provisional")
        )
        outward_coverage = tuple(
            item
            for item in outward_coverage
            if item.bucket_start < requested_to and item.bucket_end > requested_from
        )
        if current_coverage is not None:
            snapshot_identity = build_taiwan_bar_series_identity(
                instrument=instrument,
                requested_interval=requested_interval,
                base_interval="1m",
                bars=snapshot_bars,
                coverage=outward_coverage,
                aggregation_version=aggregation_version,
                state={"scope": "current_session_snapshot"},
            )
            current_coverage = current_coverage.model_copy(
                update={
                    "snapshot_revision": snapshot_identity.series_revision,
                    "snapshot_bar_count": len(snapshot_bars),
                    "snapshot_available_from": (
                        snapshot_bars[0].start_at if snapshot_bars else None
                    ),
                    "snapshot_available_to": (
                        snapshot_bars[-1].end_at if snapshot_bars else None
                    ),
                }
            )
        outward_bars = snapshot_bars[-limit:]
        available_from = outward_bars[0].start_at if outward_bars else None
        available_to = outward_bars[-1].end_at if outward_bars else None
        requested_session_count = len(trade_dates)
        requested_coverage_satisfied = (
            requested_session_count > 0
            and len(manifests) == requested_session_count
            and all(
                item.coverage_status is TaiwanHistoryStatus.READY
                for item in manifests
            )
        )
        history_status = (
            TaiwanHistoryStatus.MISSING
            if covered_sessions == 0
            else TaiwanHistoryStatus.READY
            if requested_coverage_satisfied
            else TaiwanHistoryStatus.WARMING_UP
            if from_time is None
            else TaiwanHistoryStatus.PARTIAL
        )
        history_limitations = (
            ()
            if requested_coverage_satisfied
            else ("TW_CANONICAL_1M_HISTORY_INCOMPLETE",)
        )
        history = TaiwanHistoryCoverage(
            requested_from=requested_from,
            requested_to=requested_to,
            available_from=available_from,
            available_to=available_to,
            requested_session_count=requested_session_count,
            covered_session_count=covered_sessions,
            history_status=history_status,
            requested_coverage_satisfied=requested_coverage_satisfied,
            limitations=history_limitations,
        )
        identity = build_taiwan_bar_series_identity(
            instrument=instrument,
            requested_interval=requested_interval,
            base_interval="1m",
            bars=outward_bars,
            coverage=outward_coverage,
            aggregation_version=aggregation_version,
            state={
                "history_status": history_status.value,
                "requested_coverage_satisfied": requested_coverage_satisfied,
                "session_resolution": [
                    {
                        "trade_date": item.trade_date.isoformat(),
                        "resolution_mode": item.resolution_mode.value,
                        "coverage_status": item.coverage_status.value,
                        "filled_bucket_count": item.filled_bucket_count,
                        "conflict_bucket_count": item.conflict_bucket_count,
                    }
                    for item in manifests
                ],
            },
        )
        return TaiwanBarSeriesRead(
            instrument=instrument,
            requested_interval=requested_interval,
            base_interval="1m",
            derived=requested_interval != "1m",
            aggregation_version=aggregation_version,
            bars=outward_bars,
            bar_states=tuple(
                TaiwanBarOutwardState(
                    start_at=item.start_at,
                    finalization=item.finalization,
                    authority=item.lineage.authority,
                    official=False,
                    release_status=TaiwanReleaseStatus.NOT_APPLICABLE,
                    reconciliation_status=(
                        TaiwanReconciliationStatus.NOT_APPLICABLE
                    ),
                    persisted=requested_interval == "1m",
                    source_interval="1m",
                )
                for item in outward_bars
            ),
            bucket_coverage=outward_coverage,
            history=history,
            session_resolution=tuple(manifests),
            current_session_coverage=current_coverage,
            identity=identity,
            limitations=tuple(dict.fromkeys((*limitations, *history_limitations))),
        )

    def _read_daily_bars(
        self,
        *,
        instrument_id: str,
        requested_interval: str,
        from_time: datetime | None,
        to_time: datetime | None,
        limit: int,
        include_partial: bool,
        requested_at: datetime | None,
    ) -> TaiwanBarSeriesRead:
        now = _aware_taipei(requested_at or datetime.now(TAIWAN_TZ))
        requested_to = _aware_taipei(to_time or now)
        instrument = resolve_taiwan_instrument(self._db, instrument_id)
        repository = TaiwanOfficialDailyBarRepository(
            self._db,
            available_at=now,
        )
        base_row_limit = min(
            5000,
            limit
            * (
                1
                if requested_interval == "1d"
                else 6
                if requested_interval == "1w"
                else 24
            ),
        )
        lookback_days = min(
            36_600,
            max(
                limit
                * (
                    2
                    if requested_interval == "1d"
                    else 8
                    if requested_interval == "1w"
                    else 32
                ),
                31,
            ),
        )
        if from_time is not None:
            requested_from = _aware_taipei(from_time)
        else:
            latest_start = repository.latest_candidate_start_date(
                instrument=instrument,
                end_date=requested_to.date(),
                max_rows=base_row_limit,
            )
            requested_from = (
                datetime.combine(latest_start, time.min, tzinfo=TAIWAN_TZ)
                if latest_start is not None
                else requested_to - timedelta(days=lookback_days)
            )
        if requested_to <= requested_from:
            raise ValueError("to_time must be after from_time")
        requirement = build_taiwan_daily_cache_requirement(
            instrument=instrument,
            from_date=requested_from.date(),
            to_date=requested_to.date(),
            requested_at=now,
            max_rows=base_row_limit,
            minimum_authority=AuthorityClass.DERIVED,
        )
        result = MarketDataGateway().resolve_bars(
            requirement,
            reader=TaiwanCompletedDailyCandidateReader(repository),
        )
        if not isinstance(result.resolved, ResolvedBarSeries):
            raise RuntimeError("Taiwan daily gateway returned non-Bar payload")
        base_bars = list(result.resolved.bars)
        projection_limitations: list[str] = []
        metadata = repository.outward_state_metadata(
            tuple(
                item.lineage.observation_id
                for item in base_bars
                if item.lineage.observation_id
            )
        )
        base_states: list[TaiwanBarOutwardState] = []
        for item in base_bars:
            state = metadata.get(item.lineage.observation_id or "", {})
            base_states.append(
                TaiwanBarOutwardState(
                    start_at=item.start_at,
                    finalization=item.finalization,
                    authority=item.lineage.authority,
                    official=bool(
                        state.get("official")
                        if state.get("official") is not None
                        else item.lineage.authority is AuthorityClass.EXCHANGE
                    ),
                    release_status=TaiwanReleaseStatus(
                        state.get("release_status") or "released"
                    ),
                    reconciliation_status=TaiwanReconciliationStatus(
                        state.get("reconciliation_status") or "pending"
                    ),
                    persisted=True,
                    source_interval="1d",
                    technical_eligible=(
                        state.get("reconciliation_status") != "mismatched"
                    ),
                )
            )

        current_date = taiwan_presentation_session(now)["trade_date"]
        if (
            include_partial
            and requested_from.date() <= current_date <= requested_to.date()
            and not any(item.start_at.date() == current_date for item in base_bars)
        ):
            current_1m = self.read_bars(
                instrument_id=instrument.symbol,
                interval="1m",
                from_time=datetime.combine(
                    current_date,
                    TAIWAN_SESSION_OPEN_TIME,
                    tzinfo=TAIWAN_TZ,
                ),
                to_time=min(
                    requested_to,
                    datetime.combine(
                        current_date,
                        TAIWAN_SESSION_CLOSE_TIME,
                        tzinfo=TAIWAN_TZ,
                    ),
                ),
                limit=500,
                include_partial=True,
                requested_at=now,
            )
            expected_coverage = tuple(
                item
                for item in current_1m.bucket_coverage
                if item.expected_by_trading_policy
            )
            coverage_complete = (
                current_1m.history.requested_coverage_satisfied
                and bool(expected_coverage)
                and all(
                    item.status.value
                    in {"observed_trade", "verified_no_trade"}
                    for item in expected_coverage
                )
            )
            if current_1m.bars:
                try:
                    projection = aggregate_completed_session_to_1d(
                        current_1m.bars,
                        output_provider="omi_taiwan_bar_service",
                        output_source="tw.current_session.daily_projection",
                        source_interval="1m",
                        coverage_complete=coverage_complete,
                        as_of=now,
                        formal_close_component=None,
                    )
                except TaiwanDailyMaterializationComponentsOverlapError:
                    projection_limitations.extend(
                        (
                            "TW_CURRENT_SESSION_DAILY_PROJECTION_INVALID",
                            "TW_CURRENT_SESSION_DAILY_COMPONENTS_OVERLAP",
                        )
                    )
                else:
                    base_bars.append(projection)
                    base_states.append(
                        TaiwanBarOutwardState(
                            start_at=projection.start_at,
                            finalization=projection.finalization,
                            authority=AuthorityClass.DERIVED,
                            official=False,
                            release_status=TaiwanReleaseStatus.PENDING_RELEASE,
                            reconciliation_status=TaiwanReconciliationStatus.PENDING,
                            persisted=False,
                            source_interval="1m",
                            technical_eligible=False,
                        )
                    )

        paired = sorted(zip(base_bars, base_states), key=lambda item: item[0].start_at)
        ordered_base = tuple(item[0] for item in paired)
        ordered_states = tuple(item[1] for item in paired)
        if requested_interval == "1d":
            outward_bars = ordered_base
            outward_states = ordered_states
            aggregation_version = None
        else:
            outward_bars = aggregate_daily_1d(
                ordered_base,
                target_interval=requested_interval,
            )
            outward_states = tuple(
                TaiwanBarOutwardState(
                    start_at=item.start_at,
                    finalization=item.finalization,
                    authority=AuthorityClass.DERIVED,
                    official=False,
                    release_status=TaiwanReleaseStatus.NOT_APPLICABLE,
                    reconciliation_status=(
                        TaiwanReconciliationStatus.NOT_APPLICABLE
                    ),
                    persisted=False,
                    source_interval="1d",
                    technical_eligible=all(
                        state.technical_eligible
                        for base, state in zip(ordered_base, ordered_states)
                        if item.start_at <= base.start_at <= item.end_at
                    ),
                )
                for item in outward_bars
            )
            aggregation_version = TAIWAN_BAR_AGGREGATION_VERSION
        selected_pairs = tuple(
            (bar, state)
            for bar, state in zip(outward_bars, outward_states)
            if bar.start_at < requested_to and bar.end_at > requested_from
            and (include_partial or bar.finalization.value != "provisional")
        )[-limit:]
        outward_bars = tuple(item[0] for item in selected_pairs)
        outward_states = tuple(item[1] for item in selected_pairs)
        coverage = observed_trade_coverage(
            outward_bars,
            trading_policy_version="tw.trading_policy.daily.v1",
        )
        requested_dates = _trading_dates(
            requested_from.date(),
            min(requested_to.date(), current_date),
        )
        covered_dates = {item.start_at.date() for item in ordered_base}
        covered_session_count = len(set(requested_dates) & covered_dates)
        history_status = (
            TaiwanHistoryStatus.MISSING
            if not ordered_base
            else TaiwanHistoryStatus.READY
            if covered_session_count == len(requested_dates)
            else TaiwanHistoryStatus.PARTIAL
        )
        history = TaiwanHistoryCoverage(
            requested_from=requested_from,
            requested_to=requested_to,
            available_from=(outward_bars[0].start_at if outward_bars else None),
            available_to=(outward_bars[-1].end_at if outward_bars else None),
            requested_session_count=len(requested_dates),
            covered_session_count=covered_session_count,
            history_status=history_status,
            requested_coverage_satisfied=(
                bool(requested_dates)
                and covered_session_count == len(requested_dates)
            ),
            limitations=(
                ()
                if covered_session_count == len(requested_dates)
                else ("TW_CANONICAL_1D_HISTORY_INCOMPLETE",)
            ),
        )
        identity = build_taiwan_bar_series_identity(
            instrument=instrument,
            requested_interval=requested_interval,
            base_interval="1d",
            bars=outward_bars,
            coverage=coverage,
            aggregation_version=aggregation_version,
            state={
                "history_status": history_status.value,
                "bar_states": [item.model_dump(mode="json") for item in outward_states],
            },
        )
        return TaiwanBarSeriesRead(
            instrument=instrument,
            requested_interval=requested_interval,
            base_interval="1d",
            derived=requested_interval != "1d",
            aggregation_version=aggregation_version,
            bars=outward_bars,
            bar_states=outward_states,
            bucket_coverage=coverage,
            history=history,
            session_resolution=(),
            identity=identity,
            limitations=tuple(
                dict.fromkeys(
                    (
                        *result.limitations,
                        *history.limitations,
                        *projection_limitations,
                        *(
                            ("TW_DAILY_RECONCILIATION_MISMATCH",)
                            if any(
                                item.reconciliation_status
                                is TaiwanReconciliationStatus.MISMATCHED
                                for item in outward_states
                            )
                            else ()
                        ),
                    )
                )
            ),
        )


def read_taiwan_index_intraday_bars(
    db: Session,
    *,
    index_id: str,
    requested_at: datetime | None = None,
) -> TaiwanBarSeriesRead:
    """Read one Taiwan index 1m series through the unified Bar owner."""

    return TaiwanBarService(db).read_current_session_bars(
        instrument_id=index_id,
        interval="1m",
        limit=500,
        requested_at=requested_at,
    )


def taiwan_current_session_bar_window(
    requested_at: datetime | None = None,
) -> tuple[datetime, date, datetime, datetime]:
    """Resolve the one presentation-session time window used by all consumers."""

    local_now = _aware_taipei(requested_at or datetime.now(TAIWAN_TZ))
    presentation = taiwan_presentation_session(local_now)
    trade_date = presentation["trade_date"]
    if not isinstance(trade_date, date):
        raise RuntimeError("Taiwan presentation session returned invalid trade date")
    from_time = datetime.combine(
        trade_date,
        TAIWAN_SESSION_OPEN_TIME,
        tzinfo=TAIWAN_TZ,
    )
    to_time = (
        local_now
        if trade_date == local_now.date()
        else datetime.combine(
            trade_date,
            TAIWAN_SESSION_CLOSE_TIME,
            tzinfo=TAIWAN_TZ,
        )
        + timedelta(minutes=1)
    )
    if to_time <= from_time:
        to_time = from_time + timedelta(minutes=1)
    return local_now, trade_date, from_time, to_time


def project_taiwan_index_intraday_bars(
    series: TaiwanBarSeriesRead,
) -> dict[str, object]:
    """Project the canonical Bar contract without re-resolving providers."""

    payload = series.model_dump(mode="json")
    latest = series.bars[-1] if series.bars else None
    trade_dates = tuple(item.trade_date for item in series.session_resolution)
    return {
        **payload,
        "kind": "taiwan_index_intraday_bars",
        "trade_date": trade_dates[0].isoformat() if len(trade_dates) == 1 else None,
        "provider": latest.lineage.provider if latest is not None else None,
        "source": latest.lineage.source if latest is not None else None,
        "points": [
            {
                "time": bar.start_at.isoformat(),
                "bar_time": bar.start_at.isoformat(),
                "event_time": bar.end_at.isoformat(),
                "price": float(bar.close_price),
                "close": float(bar.close_price),
                "provider": bar.lineage.provider,
                "source": bar.lineage.source,
            }
            for bar in series.bars
        ],
    }


__all__ = [
    "TaiwanBarService",
    "project_taiwan_index_intraday_bars",
    "read_taiwan_index_intraday_bars",
    "taiwan_current_session_bar_window",
]
