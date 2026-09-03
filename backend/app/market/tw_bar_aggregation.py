"""Single deterministic aggregation owner for Taiwan Bar projections."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import json

from app.market.trading_calendar import (
    TAIWAN_CLOSING_AUCTION_TIME,
    TAIWAN_SESSION_CLOSE_TIME,
    TAIWAN_SESSION_OPEN_TIME,
    TAIWAN_TZ,
)
from app.market.tw_bar_contracts import (
    TAIWAN_DAILY_MATERIALIZATION_VERSION,
    BarBucketCoverage,
    BarBucketCoverageStatus,
    TaiwanDerivedBucketCoverage,
    TaiwanDerivedBucketCoverageStatus,
)
from app.market.tw_instrument_trading_policy import (
    TaiwanInstrumentTradingMode,
    TaiwanInstrumentTradingPolicy,
)
from app.market_data.contracts import (
    AuthorityClass,
    BarFinalization,
    BarObservation,
    Quantity,
    SourceLineage,
)


TAIWAN_BAR_AGGREGATION_VERSION = "tw.bar.aggregate.v1"
_TARGET_MINUTES = {
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
}


class TaiwanDailyMaterializationComponentsOverlapError(ValueError):
    """Component intervals overlap and cannot form one truthful daily Bar."""


def _local(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Taiwan aggregation requires timezone-aware timestamps")
    return value.astimezone(TAIWAN_TZ)


def _session_bounds(trade_date: date) -> tuple[datetime, datetime]:
    return (
        datetime.combine(trade_date, TAIWAN_SESSION_OPEN_TIME, tzinfo=TAIWAN_TZ),
        datetime.combine(trade_date, TAIWAN_SESSION_CLOSE_TIME, tzinfo=TAIWAN_TZ),
    )


def observed_trade_coverage(
    bars: tuple[BarObservation, ...],
    *,
    trading_policy_version: str,
) -> tuple[BarBucketCoverage, ...]:
    """Project only positively observed base buckets.

    This helper intentionally does not infer absent rows. A market-owned
    coverage evaluator must add verified_no_trade, missing_evidence, or
    not_applicable buckets before a series can claim complete coverage.
    """

    return tuple(
        BarBucketCoverage(
            bucket_start=bar.start_at,
            bucket_end=bar.end_at,
            status=BarBucketCoverageStatus.OBSERVED_TRADE,
            expected_by_trading_policy=True,
            evidence_refs=tuple(
                item
                for item in (
                    bar.lineage.content_hash,
                    bar.lineage.raw_receipt_id,
                    bar.lineage.observation_id,
                )
                if item
            ),
            source_observation_count=1,
            reason_code="CANONICAL_BASE_BAR_OBSERVED",
            qualification_method="canonical_bar_lineage",
            verified_by="taiwan_bar_coverage_evaluator",
            trading_policy_version=trading_policy_version,
            coverage_algorithm_version="tw.bar.coverage.v1",
        )
        for bar in bars
    )


def continuous_session_coverage(
    bars: tuple[BarObservation, ...],
    *,
    trade_date: date,
    trading_policy_version: str,
    trading_policy: TaiwanInstrumentTradingPolicy | None = None,
    as_of: datetime | None = None,
) -> tuple[BarBucketCoverage, ...]:
    """Build conservative coverage for a proven continuous-matching policy.

    The closing-auction window is not a time-bar expectation while the 13:30
    closing-match component contract remains deferred. Missing continuous
    minutes are always ``missing_evidence``; row absence never becomes
    ``verified_no_trade``.
    """

    by_start = {_local(bar.start_at): bar for bar in bars}
    session_start, session_end = _session_bounds(trade_date)
    continuous_end = datetime.combine(
        trade_date,
        TAIWAN_CLOSING_AUCTION_TIME,
        tzinfo=TAIWAN_TZ,
    )
    result: list[BarBucketCoverage] = []
    cursor = session_start
    coverage_end = session_end
    if as_of is not None:
        local_as_of = _local(as_of)
        if local_as_of.date() < trade_date:
            coverage_end = session_start
        elif local_as_of.date() == trade_date:
            # Only fully elapsed one-minute buckets are eligible for coverage.
            # The bucket containing ``as_of`` is active/provisional evidence,
            # not a missing completed bucket.
            completed_bucket_end = local_as_of.replace(second=0, microsecond=0)
            coverage_end = min(session_end, completed_bucket_end)
    while cursor < coverage_end:
        end = cursor + timedelta(minutes=1)
        bar = by_start.get(cursor)
        if cursor >= continuous_end:
            result.append(
                BarBucketCoverage(
                    bucket_start=cursor,
                    bucket_end=end,
                    status=BarBucketCoverageStatus.NOT_APPLICABLE,
                    expected_by_trading_policy=False,
                    reason_code="CLOSING_AUCTION_NOT_TIME_BAR",
                    qualification_method="taiwan_session_policy",
                    verified_by="taiwan_bar_coverage_evaluator",
                    trading_policy_version=trading_policy_version,
                    coverage_algorithm_version="tw.bar.coverage.v2",
                )
            )
        elif bar is not None:
            result.extend(
                observed_trade_coverage(
                    (bar,),
                    trading_policy_version=trading_policy_version,
                )
            )
        elif (
            trading_policy is not None
            and trading_policy.trading_mode
            is TaiwanInstrumentTradingMode.DISPOSITION_BATCH_AUCTION
        ):
            result.append(
                BarBucketCoverage(
                    bucket_start=cursor,
                    bucket_end=end,
                    status=BarBucketCoverageStatus.NOT_APPLICABLE,
                    expected_by_trading_policy=False,
                    reason_code="DISPOSITION_BATCH_AUCTION_NOT_TIME_BAR",
                    qualification_method="taiwan_session_policy",
                    verified_by="taiwan_bar_coverage_evaluator",
                    trading_policy_version=trading_policy_version,
                    coverage_algorithm_version="tw.bar.coverage.v2",
                )
            )
        else:
            result.append(
                BarBucketCoverage(
                    bucket_start=cursor,
                    bucket_end=end,
                    status=BarBucketCoverageStatus.MISSING_EVIDENCE,
                    expected_by_trading_policy=True,
                    reason_code="EXPECTED_BUCKET_EVIDENCE_MISSING",
                    qualification_method="taiwan_session_policy",
                    verified_by="taiwan_bar_coverage_evaluator",
                    trading_policy_version=trading_policy_version,
                    coverage_algorithm_version="tw.bar.coverage.v2",
                )
            )
        cursor = end
    return tuple(result)


def _bucket_start(value: datetime, *, minutes: int) -> datetime:
    local = _local(value)
    session_start, _ = _session_bounds(local.date())
    offset = int((local - session_start).total_seconds() // 60)
    if offset < 0:
        raise ValueError("base bar precedes Taiwan session open")
    return session_start + timedelta(minutes=(offset // minutes) * minutes)


def _coverage_summary(
    bucket_start: datetime,
    bucket_end: datetime,
    coverage: tuple[BarBucketCoverage, ...],
    component_count: int,
    *,
    nominal_end: datetime,
) -> TaiwanDerivedBucketCoverage:
    relevant = tuple(
        item
        for item in coverage
        if item.bucket_start >= bucket_start and item.bucket_start < bucket_end
    )
    counts = {
        status: sum(item.status is status for item in relevant)
        for status in BarBucketCoverageStatus
    }
    missing_count = counts[BarBucketCoverageStatus.MISSING_EVIDENCE]
    status = (
        TaiwanDerivedBucketCoverageStatus.MISSING
        if component_count == 0 and missing_count
        else TaiwanDerivedBucketCoverageStatus.PARTIAL
        if missing_count
        else TaiwanDerivedBucketCoverageStatus.COMPLETE
    )
    return TaiwanDerivedBucketCoverage(
        bucket_start=bucket_start,
        bucket_end=bucket_end,
        status=status,
        component_count=component_count,
        expected_component_count=len(relevant),
        observed_trade_count=counts[BarBucketCoverageStatus.OBSERVED_TRADE],
        verified_no_trade_count=counts[BarBucketCoverageStatus.VERIFIED_NO_TRADE],
        missing_evidence_count=missing_count,
        not_applicable_count=counts[BarBucketCoverageStatus.NOT_APPLICABLE],
        session_truncated=bucket_end < nominal_end,
    )


def _component_lineage_hash(items: tuple[BarObservation, ...]) -> str:
    payload = [
        {
            "provider": item.lineage.provider,
            "source": item.lineage.source,
            "raw_contract_version": item.lineage.raw_contract_version,
            "content_hash": item.lineage.content_hash,
            "start_at": item.start_at.isoformat(),
        }
        for item in items
    ]
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _summed_quantity(
    items: tuple[BarObservation, ...],
) -> tuple[Quantity | None, str]:
    statuses = {item.volume_status for item in items}
    if statuses == {"not_applicable"}:
        return None, "not_applicable"
    if any(item.volume is None for item in items):
        return None, "missing"
    units = {item.volume.unit for item in items if item.volume is not None}
    if len(units) != 1:
        return None, "missing"
    return (
        Quantity(
            value=sum(
                (item.volume.value for item in items if item.volume is not None),
                Decimal(0),
            ),
            unit=next(iter(units)),
        ),
        "observed",
    )


def aggregate_completed_session_to_1d(
    components: tuple[BarObservation, ...],
    *,
    output_provider: str,
    output_source: str,
    source_interval: str,
    coverage_complete: bool,
    as_of: datetime,
    formal_close_component: BarObservation | None = None,
) -> BarObservation:
    """Materialize one completed-session daily candidate using Bar math once."""

    if not components:
        raise ValueError("daily materialization requires component bars")
    ordered = tuple(sorted(components, key=lambda item: item.start_at))
    instrument = ordered[0].instrument
    trade_date = _local(ordered[0].start_at).date()
    if any(
        item.instrument != instrument
        or item.interval != source_interval
        or _local(item.start_at).date() != trade_date
        for item in ordered
    ):
        raise ValueError("daily materialization crossed component identity")
    if any(
        current.end_at > following.start_at
        for current, following in zip(ordered, ordered[1:])
    ):
        raise TaiwanDailyMaterializationComponentsOverlapError(
            "daily materialization components overlap"
        )
    start_at, end_at = _session_bounds(trade_date)
    qualified_formal_close = bool(
        formal_close_component is not None
        and formal_close_component.instrument == instrument
        and formal_close_component.interval in {"5s", "closing_match"}
        and _local(formal_close_component.end_at).date() == trade_date
        and _local(formal_close_component.end_at) == end_at
        and formal_close_component.finalization
        in {BarFinalization.FINAL, BarFinalization.CORRECTED}
    )
    complete_numeric = coverage_complete and qualified_formal_close
    close_component = formal_close_component if qualified_formal_close else ordered[-1]
    numeric_components = (
        (*ordered, formal_close_component)
        if qualified_formal_close and formal_close_component not in ordered
        else ordered
    )
    volume, volume_status = _summed_quantity(tuple(numeric_components))
    turnover_value = (
        sum((item.turnover_value for item in numeric_components), Decimal(0))
        if complete_numeric
        and all(item.turnover_value is not None for item in numeric_components)
        else None
    )
    trade_count = (
        sum(
            item.trade_count
            for item in numeric_components
            if item.trade_count is not None
        )
        if complete_numeric
        and all(item.trade_count is not None for item in numeric_components)
        else None
    )
    return BarObservation(
        instrument=instrument,
        lineage=SourceLineage(
            provider=output_provider,
            source=output_source,
            authority=AuthorityClass.DERIVED,
            raw_contract_version=TAIWAN_DAILY_MATERIALIZATION_VERSION,
            event_at=close_component.lineage.event_at or close_component.end_at,
            received_at=(
                ordered[-1].lineage.received_at
                or ordered[-1].lineage.fetched_at
                or ordered[-1].lineage.event_at
                or ordered[-1].end_at
            ),
            fetched_at=(
                ordered[-1].lineage.fetched_at
                or ordered[-1].lineage.received_at
                or ordered[-1].lineage.event_at
                or ordered[-1].end_at
            ),
            content_hash=_component_lineage_hash(tuple(numeric_components)),
        ),
        interval="1d",
        start_at=start_at,
        end_at=end_at,
        open_price=ordered[0].open_price,
        high_price=max(item.high_price for item in numeric_components),
        low_price=min(item.low_price for item in numeric_components),
        close_price=close_component.close_price,
        volume=(volume if complete_numeric else None),
        volume_status=(volume_status if complete_numeric else "missing"),
        price_basis="raw",
        turnover_value=turnover_value,
        turnover_currency=(
            ordered[0].turnover_currency if turnover_value is not None else None
        ),
        trade_count=trade_count,
        finalization=(
            BarFinalization.FINAL
            if complete_numeric and end_at <= _local(as_of)
            else BarFinalization.PROVISIONAL
        ),
    )


def aggregate_daily_1d(
    bars: tuple[BarObservation, ...],
    *,
    target_interval: str,
) -> tuple[BarObservation, ...]:
    """Derive 1w/1mo only from resolved canonical 1d bars."""

    if target_interval not in {"1w", "1mo"}:
        raise ValueError("daily aggregation target must be 1w or 1mo")
    ordered = tuple(sorted(bars, key=lambda item: item.start_at))
    if any(item.interval != "1d" for item in ordered):
        raise ValueError("daily aggregation requires canonical 1d bars")
    groups: dict[date, list[BarObservation]] = {}
    for item in ordered:
        local_date = _local(item.start_at).date()
        key = (
            local_date - timedelta(days=local_date.weekday())
            if target_interval == "1w"
            else date(local_date.year, local_date.month, 1)
        )
        groups.setdefault(key, []).append(item)
    result: list[BarObservation] = []
    for items in groups.values():
        components = tuple(items)
        volume, volume_status = _summed_quantity(components)
        turnover = (
            sum((item.turnover_value for item in components), Decimal(0))
            if all(item.turnover_value is not None for item in components)
            else None
        )
        trade_count = (
            sum(item.trade_count for item in components if item.trade_count is not None)
            if all(item.trade_count is not None for item in components)
            else None
        )
        result.append(
            BarObservation(
                instrument=components[0].instrument,
                lineage=SourceLineage(
                    provider="omi_taiwan_bar_service",
                    source="tw.bar.aggregate",
                    authority=AuthorityClass.DERIVED,
                    raw_contract_version=TAIWAN_BAR_AGGREGATION_VERSION,
                    event_at=components[-1].lineage.event_at,
                    received_at=components[-1].lineage.received_at,
                    fetched_at=components[-1].lineage.fetched_at,
                    content_hash=_component_lineage_hash(components),
                ),
                interval=target_interval,
                start_at=components[0].start_at,
                end_at=components[-1].end_at,
                open_price=components[0].open_price,
                high_price=max(item.high_price for item in components),
                low_price=min(item.low_price for item in components),
                close_price=components[-1].close_price,
                volume=volume,
                volume_status=volume_status,
                price_basis="raw",
                turnover_value=turnover,
                turnover_currency=(
                    components[0].turnover_currency
                    if turnover is not None
                    else None
                ),
                trade_count=trade_count,
                finalization=(
                    BarFinalization.PROVISIONAL
                    if any(
                        item.finalization is BarFinalization.PROVISIONAL
                        for item in components
                    )
                    else BarFinalization.CORRECTED
                    if any(
                        item.finalization is BarFinalization.CORRECTED
                        for item in components
                    )
                    else BarFinalization.FINAL
                ),
            )
        )
    return tuple(result)


def _aggregate_bucket(
    items: tuple[BarObservation, ...],
    *,
    target_interval: str,
    bucket_start: datetime,
    bucket_end: datetime,
    as_of: datetime,
    coverage: TaiwanDerivedBucketCoverage,
) -> BarObservation:
    if not items:
        raise ValueError("cannot aggregate an empty observed bucket")
    if len({item.instrument for item in items}) != 1:
        raise ValueError("aggregate bucket crossed instrument identity")
    if any(item.interval != "1m" for item in items):
        raise ValueError("intraday aggregation requires canonical 1m bars")
    price_bases = {item.price_basis for item in items}
    if len(price_bases) != 1:
        raise ValueError("aggregate bucket crossed price basis")

    volume, volume_status = _summed_quantity(items)
    if coverage.missing_evidence_count:
        volume, volume_status = None, "missing"

    complete_turnover = coverage.missing_evidence_count == 0 and all(
        item.turnover_value is not None for item in items
    )
    currencies = {
        item.turnover_currency for item in items if item.turnover_currency is not None
    }
    if complete_turnover and len(currencies) != 1:
        raise ValueError("aggregate bucket crossed turnover currency")
    turnover_value = (
        sum(
            (item.turnover_value for item in items if item.turnover_value is not None),
            Decimal(0),
        )
        if complete_turnover
        else None
    )
    turnover_currency = next(iter(currencies)) if turnover_value is not None else None

    complete_trade_count = coverage.missing_evidence_count == 0 and all(
        item.trade_count is not None for item in items
    )
    trade_count = (
        sum(item.trade_count for item in items if item.trade_count is not None)
        if complete_trade_count
        else None
    )
    finalization = (
        BarFinalization.FINAL
        if _local(as_of) >= bucket_end
        and all(
            item.finalization in {BarFinalization.FINAL, BarFinalization.CORRECTED}
            for item in items
        )
        else BarFinalization.PROVISIONAL
    )
    content_hash = _component_lineage_hash(items)
    latest = items[-1].lineage
    return BarObservation(
        instrument=items[0].instrument,
        lineage=SourceLineage(
            provider="omi_taiwan_bar_service",
            source="tw.bar.aggregate",
            authority=AuthorityClass.DERIVED,
            raw_contract_version=TAIWAN_BAR_AGGREGATION_VERSION,
            event_at=bucket_end,
            received_at=latest.received_at,
            fetched_at=latest.fetched_at,
            cache_hit=True,
            observation_id=f"tw-derived:{target_interval}:{content_hash}",
            content_hash=content_hash,
        ),
        interval=target_interval,
        start_at=bucket_start,
        end_at=bucket_end,
        open_price=items[0].open_price,
        high_price=max(item.high_price for item in items),
        low_price=min(item.low_price for item in items),
        close_price=items[-1].close_price,
        volume=volume,
        volume_status=volume_status,
        price_basis=items[0].price_basis,
        turnover_value=turnover_value,
        turnover_currency=turnover_currency,
        trade_count=trade_count,
        finalization=finalization,
    )


def aggregate_intraday_1m(
    bars: tuple[BarObservation, ...],
    *,
    target_interval: str,
    bucket_coverage: tuple[BarBucketCoverage, ...],
    as_of: datetime,
) -> tuple[tuple[BarObservation, ...], tuple[TaiwanDerivedBucketCoverage, ...]]:
    """Aggregate canonical 1m bars without filling or crossing sessions."""

    minutes = _TARGET_MINUTES.get(target_interval)
    if minutes is None:
        raise ValueError("target_interval must be 5m, 15m, 30m, 1h, or 4h")
    _local(as_of)
    ordered = tuple(sorted(bars, key=lambda item: item.start_at))
    if len({item.start_at for item in ordered}) != len(ordered):
        raise ValueError("resolved Base-1m series contains duplicate timestamps")
    groups: dict[tuple[date, datetime], list[BarObservation]] = defaultdict(list)
    dates = {_local(item.start_at).date() for item in ordered}
    dates.update(_local(item.bucket_start).date() for item in bucket_coverage)
    for item in ordered:
        local = _local(item.start_at)
        session_start, session_end = _session_bounds(local.date())
        if not (session_start <= local < session_end):
            raise ValueError("base bar is outside Taiwan regular/closing session")
        start = _bucket_start(local, minutes=minutes)
        groups[(local.date(), start)].append(item)

    derived_bars: list[BarObservation] = []
    derived_coverage: list[TaiwanDerivedBucketCoverage] = []
    for trade_date in sorted(dates):
        session_start, session_end = _session_bounds(trade_date)
        cursor = session_start
        while cursor < session_end:
            nominal_end = cursor + timedelta(minutes=minutes)
            end = min(nominal_end, session_end)
            items = tuple(sorted(groups.get((trade_date, cursor), ()), key=lambda item: item.start_at))
            summary = _coverage_summary(
                cursor,
                end,
                bucket_coverage,
                len(items),
                nominal_end=nominal_end,
            )
            derived_coverage.append(summary)
            if items:
                derived_bars.append(
                    _aggregate_bucket(
                        items,
                        target_interval=target_interval,
                        bucket_start=cursor,
                        bucket_end=end,
                        as_of=as_of,
                        coverage=summary,
                    )
                )
            cursor = end
    return tuple(derived_bars), tuple(derived_coverage)


__all__ = [
    "TAIWAN_BAR_AGGREGATION_VERSION",
    "TaiwanDailyMaterializationComponentsOverlapError",
    "aggregate_completed_session_to_1d",
    "aggregate_daily_1d",
    "aggregate_intraday_1m",
    "continuous_session_coverage",
    "observed_trade_coverage",
]
