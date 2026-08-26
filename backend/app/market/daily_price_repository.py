"""Read-only Taiwan official daily-price candidate repository.

This adapter converts existing normalized persistence rows into provider-neutral
canonical bars. It deliberately performs no provider I/O, refresh, fallback,
selection, commit, or rollback.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.db.models import MarketDailyPrice, RawFetchResult, SourceRegistry
from app.market_data.candidate_repository import (
    CandidateReadLimitExceeded,
    CandidateRowRejection,
    DailyBarCandidateQuery,
    DailyBarCandidateRead,
    PersistedBarSeries,
)
from app.market_data.contracts import (
    AuthorityClass,
    BarFinalization,
    BarObservation,
    InstrumentKey,
    InstrumentType,
    Market,
    Quantity,
    QuantityUnit,
    SourceLineage,
)
from app.sources.defaults import (
    TPEX_DAILY_QUOTES_SOURCE_NAME,
    TWSE_DAILY_TRADING_SOURCE_NAME,
)


TAIWAN_TZ = ZoneInfo("Asia/Taipei")


@dataclass(frozen=True, slots=True)
class _OfficialDailySourceBinding:
    venue: str
    provider: str
    source_name: str


_SOURCE_BY_VENUE = {
    "TWSE": _OfficialDailySourceBinding(
        venue="TWSE",
        provider="twse_openapi",
        source_name=TWSE_DAILY_TRADING_SOURCE_NAME,
    ),
    "TPEX": _OfficialDailySourceBinding(
        venue="TPEX",
        provider="tpex_openapi",
        source_name=TPEX_DAILY_QUOTES_SOURCE_NAME,
    ),
}


def _binding_for_instrument(
    instrument: InstrumentKey,
) -> _OfficialDailySourceBinding:
    if instrument.market is not Market.TW:
        raise ValueError("Taiwan daily repository requires market=TW")
    if instrument.instrument_type not in {InstrumentType.STOCK, InstrumentType.ETF}:
        raise ValueError("Taiwan daily repository supports stock and ETF instruments")
    venue = str(instrument.venue or "").strip().upper()
    binding = _SOURCE_BY_VENUE.get(venue)
    if binding is None:
        raise ValueError("Taiwan daily repository requires venue=TWSE or TPEX")
    return binding


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _decimal(value: float | int) -> Decimal:
    return Decimal(str(value))


def _missing_ohlc(row: MarketDailyPrice) -> tuple[str, ...]:
    return tuple(
        name
        for name in ("open_price", "high_price", "low_price", "close_price")
        if getattr(row, name) is None
    )


class TaiwanOfficialDailyBarRepository:
    """Load one venue-scoped instrument from existing official daily storage."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def latest_candidate_start_date(
        self,
        *,
        instrument: InstrumentKey,
        end_date: date,
        max_rows: int,
    ) -> date | None:
        """Return the exact lower bound for a latest-N cache read.

        The normal candidate reader intentionally fails closed when a caller
        supplies a date range containing more rows than ``max_rows``.  Default
        latest reads therefore discover a precise persisted lower bound first,
        rather than guessing a calendar multiplier or silently truncating.
        """

        if max_rows < 1 or max_rows > 5000:
            raise ValueError("Taiwan daily read max_rows must be between 1 and 5000")
        binding = _binding_for_instrument(instrument)
        rows = (
            self._db.query(MarketDailyPrice.trade_date)
            .join(RawFetchResult, RawFetchResult.id == MarketDailyPrice.raw_result_id)
            .join(SourceRegistry, SourceRegistry.id == MarketDailyPrice.source_id)
            .filter(MarketDailyPrice.stock_id == instrument.symbol)
            .filter(MarketDailyPrice.trade_date <= end_date)
            .filter(SourceRegistry.source_name == binding.source_name)
            .order_by(MarketDailyPrice.trade_date.desc(), MarketDailyPrice.id.desc())
            .limit(max_rows)
            .all()
        )
        return rows[-1][0] if rows else None

    def load_daily_bars(self, query: DailyBarCandidateQuery) -> DailyBarCandidateRead:
        instrument = query.instrument
        binding = _binding_for_instrument(instrument)

        rows = (
            self._db.query(MarketDailyPrice, RawFetchResult, SourceRegistry)
            .join(RawFetchResult, RawFetchResult.id == MarketDailyPrice.raw_result_id)
            .join(SourceRegistry, SourceRegistry.id == MarketDailyPrice.source_id)
            .filter(MarketDailyPrice.stock_id == instrument.symbol)
            .filter(MarketDailyPrice.trade_date >= query.start_date)
            .filter(MarketDailyPrice.trade_date <= query.end_date)
            .filter(SourceRegistry.source_name == binding.source_name)
            .order_by(MarketDailyPrice.trade_date.asc(), MarketDailyPrice.id.asc())
            .limit(query.max_rows + 1)
            .all()
        )
        if len(rows) > query.max_rows:
            raise CandidateReadLimitExceeded(
                "daily candidate read exceeded max_rows; narrow the requested range"
            )

        bars: list[BarObservation] = []
        storage_row_ids: list[int] = []
        raw_result_ids: list[int] = []
        rejections: list[CandidateRowRejection] = []
        provider_priority = 100
        for row, raw_result, source in rows:
            provider_priority = max(int(source.priority), 0)
            missing_fields = _missing_ohlc(row)
            if missing_fields:
                rejections.append(
                    CandidateRowRejection(
                        provider=binding.provider,
                        source=source.source_name,
                        storage_row_id=row.id,
                        raw_result_id=raw_result.id,
                        event_date=row.trade_date,
                        reason_code="MISSING_REQUIRED_OHLC",
                        missing_fields=missing_fields,
                    )
                )
                continue

            start_at = datetime.combine(row.trade_date, time(9, 0), tzinfo=TAIWAN_TZ)
            end_at = datetime.combine(row.trade_date, time(13, 30), tzinfo=TAIWAN_TZ)
            raw_contract_version = raw_result.parser_version or source.parser_type
            try:
                bar = BarObservation(
                    instrument=instrument,
                    lineage=SourceLineage(
                        provider=binding.provider,
                        source=source.source_name,
                        authority=AuthorityClass.EXCHANGE,
                        raw_contract_version=raw_contract_version,
                        event_at=end_at,
                        fetched_at=_as_aware_utc(raw_result.fetched_at),
                        cache_hit=True,
                        observation_id=f"market_daily_price:{row.id}",
                        raw_receipt_id=f"raw_fetch_result:{raw_result.id}",
                        content_hash=raw_result.content_hash,
                    ),
                    interval="1d",
                    start_at=start_at,
                    end_at=end_at,
                    open_price=_decimal(row.open_price),
                    high_price=_decimal(row.high_price),
                    low_price=_decimal(row.low_price),
                    close_price=_decimal(row.close_price),
                    volume=(
                        Quantity(
                            value=Decimal(row.trade_volume),
                            unit=QuantityUnit.SHARE,
                        )
                        if row.trade_volume is not None
                        else None
                    ),
                    instrument_name=row.stock_name,
                    turnover_value=(
                        Decimal(row.trade_value)
                        if row.trade_value is not None
                        else None
                    ),
                    turnover_currency=(
                        "TWD" if row.trade_value is not None else None
                    ),
                    trade_count=row.transaction_count,
                    price_change=(
                        _decimal(row.price_change)
                        if row.price_change is not None
                        else None
                    ),
                    finalization=BarFinalization.FINAL,
                )
            except (TypeError, ValueError, ValidationError):
                rejections.append(
                    CandidateRowRejection(
                        provider=binding.provider,
                        source=source.source_name,
                        storage_row_id=row.id,
                        raw_result_id=raw_result.id,
                        event_date=row.trade_date,
                        reason_code="INVALID_CANONICAL_BAR",
                    )
                )
                continue

            bars.append(bar)
            storage_row_ids.append(row.id)
            raw_result_ids.append(raw_result.id)

        series = (
            PersistedBarSeries(
                provider=binding.provider,
                source=binding.source_name,
                authority=AuthorityClass.EXCHANGE,
                provider_priority=provider_priority,
                bars=tuple(bars),
                storage_row_ids=tuple(storage_row_ids),
                raw_result_ids=tuple(raw_result_ids),
            ),
        ) if bars else ()
        return DailyBarCandidateRead(
            query=query,
            series=series,
            rejections=tuple(rejections),
            rows_examined=len(rows),
            rows_accepted=len(bars),
        )


__all__ = ["TaiwanOfficialDailyBarRepository"]
