"""Cache-only canonical readers for persisted US quote and intraday evidence."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from app.db.models import (
    MarketIntradayBar,
    MarketIntradayBarLineage,
    RawFetchResult,
    SourceRegistry,
    USQuoteSnapshot,
)
from app.market_data.candidate_repository import CandidateRowRejection
from app.market_data.contracts import (
    AuthorityClass,
    BarFinalization,
    BarObservation,
    DatasetHealth,
    DatasetHealthStatus,
    EvidenceFreshness,
    InstrumentKey,
    InstrumentType,
    Market,
    ObservationState,
    Quantity,
    QuantityUnit,
    QuoteObservation,
    SourceLineage,
    TradeObservationState,
)
from app.market_data.gateway import BarCandidateBatch, QuoteCandidateBatch
from app.market_data.integration_contracts import (
    BarCapabilityRequest,
    DataRequirementV2,
    InstrumentTarget,
    SnapshotCapabilityRequest,
    freshness_timestamp,
)
from app.market_data.resolution import BarSeriesCandidate, ResolutionCandidate
from app.us_market.market_data.descriptors import (
    TWELVE_INTRADAY_DESCRIPTOR,
    TWELVE_QUOTE_DESCRIPTOR,
    YAHOO_INTRADAY_DESCRIPTOR,
    YAHOO_QUOTE_DESCRIPTOR,
)
from app.us_market.providers.canonical import us_session_for_timestamp
from app.us_market.trading_calendar import is_us_trading_day, us_session_close_time


_QUOTE_DESCRIPTORS = {
    "yahoo_chart": YAHOO_QUOTE_DESCRIPTOR,
    "twelve_data": TWELVE_QUOTE_DESCRIPTOR,
}
_INTRADAY_DESCRIPTORS = {
    "yahoo_chart": YAHOO_INTRADAY_DESCRIPTOR,
    "twelve_data": TWELVE_INTRADAY_DESCRIPTOR,
}
US_EASTERN = ZoneInfo("America/New_York")


@dataclass(frozen=True, slots=True)
class USIntradayVolumeSession:
    trade_date: date
    provider: str
    source: str
    cumulative_volume: int
    total_volume: int


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _interval_delta(interval: str) -> timedelta:
    if interval.endswith("m") and interval[:-1].isdigit():
        return timedelta(minutes=int(interval[:-1]))
    if interval.endswith("h") and interval[:-1].isdigit():
        return timedelta(hours=int(interval[:-1]))
    raise ValueError("unsupported US persisted intraday interval")


def _freshness(
    requirement: DataRequirementV2,
    lineage: SourceLineage,
) -> EvidenceFreshness:
    observed_at = freshness_timestamp(lineage, requirement.freshness.basis)
    if observed_at is None:
        return EvidenceFreshness.UNKNOWN
    return _timestamp_freshness(requirement, observed_at)


def _timestamp_freshness(
    requirement: DataRequirementV2,
    observed_at: datetime,
) -> EvidenceFreshness:
    age = (requirement.requested_at - _utc(observed_at)).total_seconds()
    return EvidenceFreshness.LIVE if -300 <= age <= requirement.freshness.max_age_seconds else EvidenceFreshness.STALE


def _descriptor_applies(
    descriptor,
    *,
    instrument_type: InstrumentType,
    venue: str,
    interval: str | None = None,
) -> bool:
    if descriptor.instrument_types and instrument_type not in descriptor.instrument_types:
        return False
    if descriptor.venue_scope and venue not in descriptor.venue_scope:
        return False
    if interval is not None and descriptor.intervals and interval not in descriptor.intervals:
        return False
    return True


def _fair_budgets(total_rows: int, provider_count: int) -> tuple[int, ...]:
    if provider_count < 1:
        return ()
    quotient, remainder = divmod(total_rows, provider_count)
    return tuple(
        quotient + (1 if index < remainder else 0)
        for index in range(provider_count)
    )


def _dataset_health(requirement: DataRequirementV2, *, dataset_id: str, events: list[datetime], partial: bool) -> DatasetHealth:
    latest = max(events) if events else None
    current = latest is not None and _timestamp_freshness(requirement, latest) is EvidenceFreshness.LIVE
    status = DatasetHealthStatus.PARTIAL if partial and events else DatasetHealthStatus.HEALTHY if current else DatasetHealthStatus.STALE if events else DatasetHealthStatus.MISSING
    return DatasetHealth(
        dataset_id=dataset_id,
        market=Market.US,
        status=status,
        latest_date=_utc(latest).date() if latest is not None else None,
        checked_at=requirement.requested_at,
        refreshable=True,
        refresh_operation="us.refresh_quote" if dataset_id == "us.quote.snapshot" else "us.refresh_intraday_bars",
        detail_code="US_CANONICAL_CACHE_PARTIAL" if partial else "US_CANONICAL_CACHE_AVAILABLE" if events else "US_CANONICAL_CACHE_MISSING",
    )


class USQuoteRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def read_quote_candidates(self, requirement: DataRequirementV2) -> QuoteCandidateBatch:
        if not isinstance(requirement.target, InstrumentTarget) or not isinstance(requirement.request, SnapshotCapabilityRequest) or requirement.request.capability_id != "quote.snapshot" or requirement.target.instrument.market is not Market.US:
            raise ValueError("US quote repository capability mismatch")
        instrument = requirement.target.instrument
        eligible_descriptors = tuple(
            descriptor
            for descriptor in _QUOTE_DESCRIPTORS.values()
            if _descriptor_applies(
                descriptor,
                instrument_type=instrument.instrument_type,
                venue=instrument.venue,
            )
        )
        row_budget = min(requirement.bounds.max_rows, 32)
        rows = []
        for descriptor, budget in zip(
            eligible_descriptors,
            _fair_budgets(row_budget, len(eligible_descriptors)),
        ):
            if budget <= 0:
                continue
            rows.extend(
                self._db.query(USQuoteSnapshot, RawFetchResult, SourceRegistry)
                .join(RawFetchResult, RawFetchResult.id == USQuoteSnapshot.raw_result_id)
                .join(SourceRegistry, SourceRegistry.id == USQuoteSnapshot.source_id)
                .filter(USQuoteSnapshot.symbol == instrument.symbol)
                .filter(USQuoteSnapshot.provider == descriptor.provider_key)
                .order_by(USQuoteSnapshot.event_at.desc(), USQuoteSnapshot.id.desc())
                .limit(budget)
                .all()
            )
        rows.sort(key=lambda item: (item[0].event_at, item[0].id), reverse=True)
        candidates: list[ResolutionCandidate[QuoteObservation]] = []
        rejections: list[CandidateRowRejection] = []
        events: list[datetime] = []
        seen: set[tuple[str, str]] = set()
        for row, raw, source in rows:
            identity = (row.provider, row.source)
            if identity in seen:
                continue
            descriptor = _QUOTE_DESCRIPTORS.get(row.provider)
            identity_invalid = (
                row.symbol != instrument.symbol
                or row.venue != instrument.venue
                or row.instrument_type != instrument.instrument_type.value
            )
            applicability_invalid = descriptor is None or not _descriptor_applies(
                descriptor,
                instrument_type=instrument.instrument_type,
                venue=instrument.venue,
            )
            if identity_invalid:
                rejections.append(CandidateRowRejection(provider=row.provider, source=row.source, storage_row_id=row.id, raw_result_id=row.raw_result_id, event_date=_utc(row.event_at).date(), reason_code="US_QUOTE_INSTRUMENT_IDENTITY_MISMATCH"))
                continue
            if applicability_invalid:
                rejections.append(CandidateRowRejection(provider=row.provider, source=row.source, storage_row_id=row.id, raw_result_id=row.raw_result_id, event_date=_utc(row.event_at).date(), reason_code="US_QUOTE_DESCRIPTOR_APPLICABILITY_MISMATCH"))
                continue
            assert descriptor is not None
            invalid = (
                source.source_name != row.source
                or raw.source_id != source.id
                or raw.parser_version != row.raw_contract_version
                or raw.content_hash != row.raw_payload_hash
            )
            if invalid:
                rejections.append(CandidateRowRejection(provider=row.provider, source=row.source, storage_row_id=row.id, raw_result_id=row.raw_result_id, event_date=_utc(row.event_at).date(), reason_code="US_QUOTE_LINEAGE_IDENTITY_MISMATCH"))
                continue
            try:
                quote = QuoteObservation(
                    instrument=instrument,
                    lineage=SourceLineage(
                        provider=row.provider,
                        source=row.source,
                        authority=AuthorityClass(row.authority),
                        raw_contract_version=row.raw_contract_version,
                        event_at=_utc(row.event_at),
                        received_at=_utc(row.received_at),
                        fetched_at=_utc(raw.fetched_at),
                        cache_hit=True,
                        observation_id=f"us_quote_snapshot:{row.id}",
                        raw_receipt_id=f"raw_fetch_result:{raw.id}",
                        content_hash=raw.content_hash,
                    ),
                    trade_date=row.trade_date,
                    currency=row.currency,
                    state=ObservationState(row.observation_state),
                    trade_state=TradeObservationState(row.trade_state),
                    last_trade_price=Decimal(str(row.last_trade_price)) if row.last_trade_price is not None else None,
                    last_trade_quantity=Quantity(value=Decimal(row.last_trade_quantity), unit=QuantityUnit.SHARE) if row.last_trade_quantity is not None else None,
                    cumulative_quantity=Quantity(value=Decimal(row.cumulative_quantity), unit=QuantityUnit.SHARE) if row.cumulative_quantity is not None else None,
                    open_price=Decimal(str(row.open_price)) if row.open_price is not None else None,
                    high_price=Decimal(str(row.high_price)) if row.high_price is not None else None,
                    low_price=Decimal(str(row.low_price)) if row.low_price is not None else None,
                    previous_close=Decimal(str(row.previous_close)) if row.previous_close is not None else None,
                )
            except (TypeError, ValueError, ValidationError):
                rejections.append(CandidateRowRejection(provider=row.provider, source=row.source, storage_row_id=row.id, raw_result_id=row.raw_result_id, event_date=_utc(row.event_at).date(), reason_code="INVALID_CANONICAL_US_QUOTE"))
                continue
            freshness = _freshness(requirement, quote.lineage)
            observed_at = freshness_timestamp(quote.lineage, requirement.freshness.basis)
            if observed_at is not None:
                events.append(_utc(observed_at))
            candidates.append(
                ResolutionCandidate(
                    observation=quote,
                    freshness=freshness,
                    provider_priority=descriptor.priority,
                    session=us_session_for_timestamp(_utc(row.event_at)),
                    limitations=descriptor.limitations,
                )
            )
            seen.add(identity)
        candidates.sort(key=lambda item: item.provider_priority)
        return QuoteCandidateBatch(
            candidates=tuple(candidates[: requirement.bounds.max_candidates]),
            dataset_health=_dataset_health(requirement, dataset_id="us.quote.snapshot", events=events, partial=bool(rejections)),
            rejections=tuple(rejections),
            limitations=(
                ("US_QUOTE_DESCRIPTOR_APPLICABILITY_MISMATCH",)
                if not eligible_descriptors
                else ()
            )
            + (() if candidates else ("US_QUOTE_CANONICAL_CACHE_MISSING",)),
        )


class USIntradayBarRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def read_bar_candidates(self, requirement: DataRequirementV2) -> BarCandidateBatch:
        if not isinstance(requirement.target, InstrumentTarget) or not isinstance(requirement.request, BarCapabilityRequest) or requirement.request.capability_id != "intraday.bars" or requirement.target.instrument.market is not Market.US:
            raise ValueError("US intraday repository capability mismatch")
        request = requirement.request
        instrument = requirement.target.instrument
        eligible_descriptors = tuple(
            descriptor
            for descriptor in _INTRADAY_DESCRIPTORS.values()
            if _descriptor_applies(
                descriptor,
                instrument_type=instrument.instrument_type,
                venue=instrument.venue,
                interval=request.interval,
            )
        )
        base = (
            self._db.query(MarketIntradayBar)
            .filter(MarketIntradayBar.stock_id == requirement.target.instrument.symbol)
            .filter(MarketIntradayBar.market == requirement.target.instrument.venue)
            .filter(MarketIntradayBar.interval == request.interval)
            .filter(MarketIntradayBar.bar_time >= request.start_at)
            .filter(MarketIntradayBar.bar_time <= request.end_at)
        )
        legacy_row_exists = (
            base.outerjoin(
                MarketIntradayBarLineage,
                MarketIntradayBarLineage.bar_id == MarketIntradayBar.id,
            )
            .filter(MarketIntradayBarLineage.id.is_(None))
            .with_entities(MarketIntradayBar.id)
            .first()
            is not None
        )
        row_budget = min(
            requirement.bounds.max_rows,
            request.max_bars * max(len(eligible_descriptors), 1),
        )

        def provider_rows(provider: str, *, offset: int, limit: int):
            if limit <= 0:
                return []
            return (
                self._db.query(MarketIntradayBar, MarketIntradayBarLineage, RawFetchResult, SourceRegistry)
                .join(MarketIntradayBarLineage, MarketIntradayBarLineage.bar_id == MarketIntradayBar.id)
                .join(RawFetchResult, RawFetchResult.id == MarketIntradayBarLineage.raw_result_id)
                .join(SourceRegistry, SourceRegistry.id == MarketIntradayBarLineage.source_id)
                .filter(MarketIntradayBar.stock_id == instrument.symbol)
                .filter(MarketIntradayBar.market == instrument.venue)
                .filter(MarketIntradayBar.provider == provider)
                .filter(MarketIntradayBar.interval == request.interval)
                .filter(MarketIntradayBar.bar_time >= request.start_at)
                .filter(MarketIntradayBar.bar_time <= request.end_at)
                .order_by(MarketIntradayBar.bar_time.desc(), MarketIntradayBar.id.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )

        rows = []
        read_by_provider: dict[str, int] = {}
        for descriptor, budget in zip(
            eligible_descriptors,
            _fair_budgets(row_budget, len(eligible_descriptors)),
        ):
            current = provider_rows(descriptor.provider_key, offset=0, limit=budget)
            rows.extend(current)
            read_by_provider[descriptor.provider_key] = len(current)
        remaining_budget = row_budget - len(rows)
        if remaining_budget > 0:
            for descriptor in eligible_descriptors:
                already_read = read_by_provider.get(descriptor.provider_key, 0)
                extra_limit = min(
                    remaining_budget,
                    max(0, request.max_bars - already_read),
                )
                extra = provider_rows(
                    descriptor.provider_key,
                    offset=already_read,
                    limit=extra_limit,
                )
                rows.extend(extra)
                read_by_provider[descriptor.provider_key] = already_read + len(extra)
                remaining_budget -= len(extra)
                if remaining_budget <= 0:
                    break
        if len(rows) > requirement.bounds.max_rows:
            raise ValueError("US intraday repository read exceeded bounds.max_rows")
        by_source: dict[tuple[str, str], list[BarObservation]] = defaultdict(list)
        priorities: dict[tuple[str, str], int] = {}
        rejections: list[CandidateRowRejection] = []
        minute_bucket_counts: dict[tuple[str, datetime], int] = defaultdict(int)
        for row, _lineage, _raw, _source in rows:
            minute_bucket_counts[
                (
                    row.provider,
                    _utc(row.bar_time).replace(second=0, microsecond=0),
                )
            ] += 1
        duplicate_minute_bucket_exists = any(
            count > 1 for count in minute_bucket_counts.values()
        )
        noncanonical_minute_identity_exists = False
        for row, lineage, raw, source in rows:
            identity = (row.provider, row.source)
            if len(by_source[identity]) >= request.max_bars:
                continue
            descriptor = _INTRADAY_DESCRIPTORS.get(row.provider)
            identity_invalid = (
                row.stock_id != instrument.symbol
                or row.symbol != instrument.symbol
                or row.market != instrument.venue
            )
            applicability_invalid = descriptor is None or not _descriptor_applies(
                descriptor,
                instrument_type=instrument.instrument_type,
                venue=instrument.venue,
                interval=request.interval,
            )
            if identity_invalid:
                rejections.append(CandidateRowRejection(provider=row.provider, source=row.source, storage_row_id=row.id, raw_result_id=lineage.raw_result_id, event_date=_utc(row.bar_time).date(), reason_code="US_INTRADAY_INSTRUMENT_IDENTITY_MISMATCH"))
                continue
            if applicability_invalid or lineage.source_interval != row.interval:
                rejections.append(CandidateRowRejection(provider=row.provider, source=row.source, storage_row_id=row.id, raw_result_id=lineage.raw_result_id, event_date=_utc(row.bar_time).date(), reason_code="US_INTRADAY_DESCRIPTOR_APPLICABILITY_MISMATCH"))
                continue
            assert descriptor is not None
            invalid = (
                source.source_name != row.source
                or lineage.provider != row.provider
                or lineage.source != row.source
                or raw.source_id != source.id
                or raw.parser_version is None
                or not (lineage.raw_contract_version == raw.parser_version or lineage.raw_contract_version.startswith(f"{raw.parser_version}+"))
                or raw.content_hash is None
            )
            if invalid:
                rejections.append(CandidateRowRejection(provider=row.provider, source=row.source, storage_row_id=row.id, raw_result_id=lineage.raw_result_id, event_date=_utc(row.bar_time).date(), reason_code="US_INTRADAY_LINEAGE_IDENTITY_MISMATCH"))
                continue
            missing = tuple(name for name in ("open_price", "high_price", "low_price", "close_price") if getattr(row, name) is None)
            if missing:
                rejections.append(CandidateRowRejection(provider=row.provider, source=row.source, storage_row_id=row.id, raw_result_id=raw.id, event_date=_utc(row.bar_time).date(), reason_code="MISSING_REQUIRED_OHLC", missing_fields=missing))
                continue
            start_at = _utc(row.bar_time)
            if row.interval == "1m" and start_at != start_at.replace(
                second=0,
                microsecond=0,
            ):
                noncanonical_minute_identity_exists = True
                rejections.append(
                    CandidateRowRejection(
                        provider=row.provider,
                        source=row.source,
                        storage_row_id=row.id,
                        raw_result_id=raw.id,
                        event_date=start_at.date(),
                        reason_code="NON_CANONICAL_MINUTE_IDENTITY",
                    )
                )
                continue
            try:
                bar = BarObservation(
                    instrument=instrument,
                    lineage=SourceLineage(
                        provider=row.provider,
                        source=row.source,
                        authority=AuthorityClass(lineage.authority),
                        raw_contract_version=lineage.raw_contract_version,
                        event_at=_utc(lineage.event_at),
                        received_at=_utc(lineage.received_at),
                        fetched_at=_utc(lineage.fetched_at),
                        cache_hit=True,
                        observation_id=f"market_intraday_bar:{row.id}",
                        raw_receipt_id=f"raw_fetch_result:{raw.id}",
                        content_hash=raw.content_hash,
                    ),
                    interval=row.interval,
                    start_at=start_at,
                    end_at=start_at + _interval_delta(row.interval),
                    open_price=Decimal(str(row.open_price)),
                    high_price=Decimal(str(row.high_price)),
                    low_price=Decimal(str(row.low_price)),
                    close_price=Decimal(str(row.close_price)),
                    volume=Quantity(value=Decimal(row.trade_volume), unit=QuantityUnit.SHARE) if row.trade_volume is not None else None,
                    volume_status="observed" if row.trade_volume is not None else "missing",
                    price_basis="raw",
                    turnover_value=Decimal(row.trade_value) if row.trade_value is not None else None,
                    turnover_currency="USD" if row.trade_value is not None else None,
                    finalization=BarFinalization(lineage.finalization),
                )
            except (TypeError, ValueError, ValidationError):
                rejections.append(CandidateRowRejection(provider=row.provider, source=row.source, storage_row_id=row.id, raw_result_id=raw.id, event_date=start_at.date(), reason_code="INVALID_CANONICAL_US_INTRADAY_BAR"))
                continue
            by_source[identity].append(bar)
            priorities[identity] = descriptor.priority
        candidates: list[BarSeriesCandidate] = []
        events: list[datetime] = []
        for identity, reverse_bars in by_source.items():
            bars = tuple(sorted(reverse_bars, key=lambda item: item.start_at))
            if not bars:
                continue
            event_at = bars[-1].lineage.event_at or bars[-1].end_at
            events.append(event_at)
            descriptor = _INTRADAY_DESCRIPTORS[identity[0]]
            candidates.append(
                BarSeriesCandidate(
                    bars=bars,
                    freshness=_freshness(requirement, bars[-1].lineage),
                    provider_priority=priorities[identity],
                    session=us_session_for_timestamp(event_at),
                    limitations=descriptor.limitations,
                )
            )
        candidates.sort(key=lambda item: item.provider_priority)
        limitations: list[str] = []
        if legacy_row_exists:
            limitations.append("US_INTRADAY_LEGACY_ROWS_WITHOUT_CANONICAL_LINEAGE_IGNORED")
        if noncanonical_minute_identity_exists:
            limitations.append("NON_CANONICAL_MINUTE_IDENTITY")
        if duplicate_minute_bucket_exists:
            limitations.append("DUPLICATE_MINUTE_BUCKET")
        if not eligible_descriptors:
            limitations.append("US_INTRADAY_DESCRIPTOR_APPLICABILITY_MISMATCH")
        if not candidates:
            limitations.append("US_INTRADAY_CANONICAL_CACHE_MISSING")
        return BarCandidateBatch(
            candidates=tuple(candidates[: requirement.bounds.max_candidates]),
            dataset_health=_dataset_health(requirement, dataset_id="us.intraday.bars", events=events, partial=bool(rejections) or legacy_row_exists),
            rejections=tuple(rejections),
            limitations=tuple(limitations),
        )

    def read_volume_sessions(
        self,
        *,
        instrument: InstrumentKey,
        provider: str,
        source: str,
        current_trade_date: date,
        comparison_time: time,
        lookback_days: int = 35,
        max_sessions: int = 20,
    ) -> tuple[USIntradayVolumeSession, ...]:
        """Read bounded canonical volume aggregates for one Resolver-selected source."""

        if instrument.market is not Market.US:
            raise ValueError("US intraday volume sessions require market=US")
        if lookback_days < 1 or lookback_days > 35:
            raise ValueError("US intraday volume lookback must be between 1 and 35 days")
        if max_sessions < 1 or max_sessions > 20:
            raise ValueError("US intraday volume sessions must be between 1 and 20")
        descriptor = _INTRADAY_DESCRIPTORS.get(provider)
        if descriptor is None or not _descriptor_applies(
            descriptor,
            instrument_type=instrument.instrument_type,
            venue=instrument.venue,
            interval="1m",
        ):
            raise ValueError("US intraday volume source is not descriptor-applicable")

        sessions: list[USIntradayVolumeSession] = []
        cursor = current_trade_date - timedelta(days=1)
        earliest = current_trade_date - timedelta(days=lookback_days)
        while cursor >= earliest and len(sessions) < max_sessions:
            if not is_us_trading_day(cursor):
                cursor -= timedelta(days=1)
                continue
            session_start = datetime.combine(
                cursor,
                time(9, 30),
                tzinfo=US_EASTERN,
            ).astimezone(timezone.utc)
            session_end = datetime.combine(
                cursor,
                us_session_close_time(cursor),
                tzinfo=US_EASTERN,
            ).astimezone(timezone.utc)
            cutoff_local = datetime.combine(
                cursor,
                min(comparison_time, us_session_close_time(cursor)),
                tzinfo=US_EASTERN,
            )
            cutoff = cutoff_local.astimezone(timezone.utc)
            total, cumulative = (
                self._db.query(
                    func.sum(MarketIntradayBar.trade_volume),
                    func.sum(
                        case(
                            (
                                MarketIntradayBar.bar_time <= cutoff,
                                MarketIntradayBar.trade_volume,
                            ),
                            else_=0,
                        )
                    ),
                )
                .join(
                    MarketIntradayBarLineage,
                    MarketIntradayBarLineage.bar_id == MarketIntradayBar.id,
                )
                .join(
                    RawFetchResult,
                    RawFetchResult.id == MarketIntradayBarLineage.raw_result_id,
                )
                .join(
                    SourceRegistry,
                    SourceRegistry.id == MarketIntradayBarLineage.source_id,
                )
                .filter(MarketIntradayBar.stock_id == instrument.symbol)
                .filter(MarketIntradayBar.symbol == instrument.symbol)
                .filter(MarketIntradayBar.market == instrument.venue)
                .filter(MarketIntradayBar.provider == provider)
                .filter(MarketIntradayBar.source == source)
                .filter(MarketIntradayBar.interval == "1m")
                .filter(MarketIntradayBar.bar_time >= session_start)
                .filter(MarketIntradayBar.bar_time < session_end)
                .filter(MarketIntradayBarLineage.provider == provider)
                .filter(MarketIntradayBarLineage.source == source)
                .filter(MarketIntradayBarLineage.source_interval == "1m")
                .filter(SourceRegistry.source_name == source)
                .filter(RawFetchResult.source_id == SourceRegistry.id)
                .filter(RawFetchResult.parser_version.is_not(None))
                .filter(RawFetchResult.content_hash.is_not(None))
                .filter(
                    or_(
                        MarketIntradayBarLineage.raw_contract_version
                        == RawFetchResult.parser_version,
                        MarketIntradayBarLineage.raw_contract_version.startswith(
                            RawFetchResult.parser_version + "+"
                        ),
                    )
                )
                .one()
            )
            if total is not None and int(total) > 0:
                sessions.append(
                    USIntradayVolumeSession(
                        trade_date=cursor,
                        provider=provider,
                        source=source,
                        cumulative_volume=int(cumulative or 0),
                        total_volume=int(total),
                    )
                )
            cursor -= timedelta(days=1)
        return tuple(reversed(sessions))


__all__ = [
    "USIntradayBarRepository",
    "USIntradayVolumeSession",
    "USQuoteRepository",
]
