"""Read persisted public Taiwan quote candidates without provider I/O."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import (
    RawFetchResult,
    SourceRegistry,
    TaiwanStockQuoteSnapshot,
)
from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_realtime_capabilities import quote_source_binding
from app.market_data.contracts import (
    InstrumentKey,
    Market,
    MarketSession,
    ObservationState,
    Quantity,
    QuantityUnit,
    QuoteObservation,
    SourceLineage,
    TradeObservationState,
)


@dataclass(frozen=True, slots=True)
class PersistedPublicQuoteRead:
    observation: QuoteObservation | None = None
    provider: str | None = None
    source: str | None = None
    provider_priority: int = 100
    storage_row_id: int | None = None
    raw_result_id: int | None = None
    rows_examined: int = 0
    limitations: tuple[str, ...] = ()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _as_taiwan(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=TAIWAN_TZ)
    return value.astimezone(TAIWAN_TZ)


def _price(value: float | int | None) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def _quantity_from_lots(value: int | None) -> Quantity | None:
    if value is None:
        return None
    lots = Decimal(value)
    return Quantity(
        value=lots * Decimal(1000),
        unit=QuantityUnit.SHARE,
        original_value=lots,
        original_unit=QuantityUnit.BOARD_LOT,
        scale=Decimal(1000),
    )


class TaiwanPublicQuoteRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def _decode_row(
        self,
        instrument: InstrumentKey,
        row: TaiwanStockQuoteSnapshot,
    ) -> PersistedPublicQuoteRead:
        binding = quote_source_binding(
            provider=row.provider,
            source=row.source,
        )
        if binding is None:
            return PersistedPublicQuoteRead(
                provider=row.provider,
                source=row.source,
                storage_row_id=row.id,
                raw_result_id=row.raw_result_id,
                rows_examined=1,
                limitations=("PUBLIC_QUOTE_SOURCE_UNSUPPORTED",),
            )
        if row.source_id is None or row.raw_result_id is None:
            return PersistedPublicQuoteRead(
                provider=row.provider,
                source=row.source,
                provider_priority=binding.descriptor.priority,
                storage_row_id=row.id,
                rows_examined=1,
                limitations=("PUBLIC_QUOTE_LINEAGE_MISSING",),
            )
        if any(
            value is None
            for value in (
                row.received_at,
                row.observation_state,
                row.market_session,
                row.trade_state,
                row.raw_contract_version,
            )
        ):
            return PersistedPublicQuoteRead(
                provider=row.provider,
                source=row.source,
                provider_priority=binding.descriptor.priority,
                storage_row_id=row.id,
                raw_result_id=row.raw_result_id,
                rows_examined=1,
                limitations=("PUBLIC_QUOTE_CANONICAL_STATE_MISSING",),
            )
        joined = (
            self._db.query(RawFetchResult, SourceRegistry)
            .join(SourceRegistry, SourceRegistry.id == RawFetchResult.source_id)
            .filter(RawFetchResult.id == row.raw_result_id)
            .filter(SourceRegistry.id == row.source_id)
            .first()
        )
        if joined is None:
            return PersistedPublicQuoteRead(
                provider=row.provider,
                source=row.source,
                provider_priority=binding.descriptor.priority,
                storage_row_id=row.id,
                raw_result_id=row.raw_result_id,
                rows_examined=1,
                limitations=("PUBLIC_QUOTE_LINEAGE_BROKEN",),
            )
        raw, source = joined
        if (
            source.source_name != binding.source
            or raw.source_id != source.id
            or row.source != source.source_name
            or row.provider != binding.descriptor.provider_key
            or row.raw_contract_version != binding.parser_version
            or raw.parser_version != binding.parser_version
        ):
            return PersistedPublicQuoteRead(
                provider=row.provider,
                source=row.source,
                provider_priority=binding.descriptor.priority,
                storage_row_id=row.id,
                raw_result_id=row.raw_result_id,
                rows_examined=1,
                limitations=("PUBLIC_QUOTE_SOURCE_IDENTITY_MISMATCH",),
            )
        if raw.content_hash is None:
            return PersistedPublicQuoteRead(
                provider=row.provider,
                source=row.source,
                provider_priority=binding.descriptor.priority,
                storage_row_id=row.id,
                raw_result_id=row.raw_result_id,
                rows_examined=1,
                limitations=("PUBLIC_QUOTE_CONTENT_HASH_MISSING",),
            )
        try:
            state = ObservationState(str(row.observation_state))
            session = MarketSession(str(row.market_session))
            trade_state = TradeObservationState(str(row.trade_state))
        except ValueError:
            return PersistedPublicQuoteRead(
                provider=row.provider,
                source=row.source,
                provider_priority=binding.descriptor.priority,
                storage_row_id=row.id,
                raw_result_id=row.raw_result_id,
                rows_examined=1,
                limitations=("PUBLIC_QUOTE_CANONICAL_ENUM_INVALID",),
            )
        if trade_state is TradeObservationState.TRADE_OBSERVED and row.last_price is None:
            return PersistedPublicQuoteRead(
                provider=row.provider,
                source=row.source,
                provider_priority=binding.descriptor.priority,
                storage_row_id=row.id,
                raw_result_id=row.raw_result_id,
                rows_examined=1,
                limitations=("PUBLIC_QUOTE_ACTUAL_TRADE_PRICE_MISSING",),
            )
        if (
            trade_state is not TradeObservationState.TRADE_OBSERVED
            and row.last_price is not None
        ):
            return PersistedPublicQuoteRead(
                provider=row.provider,
                source=row.source,
                provider_priority=binding.descriptor.priority,
                storage_row_id=row.id,
                raw_result_id=row.raw_result_id,
                rows_examined=1,
                limitations=("PUBLIC_QUOTE_TRADE_STATE_CONFLICT",),
            )
        quote = QuoteObservation(
            instrument=instrument,
            lineage=SourceLineage(
                provider=row.provider,
                source=source.source_name,
                authority=binding.descriptor.authority,
                raw_contract_version=(
                    row.raw_contract_version
                    or raw.parser_version
                    or source.parser_type
                ),
                event_at=_as_taiwan(row.quote_time),
                received_at=_as_utc(row.received_at),
                fetched_at=_as_utc(raw.fetched_at),
                cache_hit=True,
                observation_id=f"taiwan_stock_quote_snapshot:{row.id}",
                raw_receipt_id=f"raw_fetch_result:{raw.id}",
                content_hash=raw.content_hash,
            ),
            trade_date=row.trade_date,
            currency="TWD",
            state=state,
            trade_state=trade_state,
            last_trade_price=_price(row.last_price),
            last_trade_quantity=_quantity_from_lots(
                row.last_trade_volume_lots
            ),
            cumulative_quantity=_quantity_from_lots(row.total_volume_lots),
            open_price=_price(row.open_price),
            high_price=_price(row.high_price),
            low_price=_price(row.low_price),
            previous_close=_price(row.previous_close),
        )
        return PersistedPublicQuoteRead(
            observation=quote,
            provider=row.provider,
            source=row.source,
            provider_priority=binding.descriptor.priority,
            storage_row_id=row.id,
            raw_result_id=raw.id,
            rows_examined=1,
        )

    def load_quote_candidates(
        self,
        instrument: InstrumentKey,
        *,
        max_candidates: int = 8,
    ) -> tuple[PersistedPublicQuoteRead, ...]:
        if instrument.market is not Market.TW:
            raise ValueError("Taiwan public quote repository requires market=TW")
        if instrument.venue not in {"TWSE", "TPEX"}:
            raise ValueError("Taiwan public quote venue must be TWSE or TPEX")
        if not 1 <= max_candidates <= 8:
            raise ValueError("public quote max_candidates must be between 1 and 8")
        rows = (
            self._db.query(TaiwanStockQuoteSnapshot)
            .filter(TaiwanStockQuoteSnapshot.stock_id == instrument.symbol)
            .filter(TaiwanStockQuoteSnapshot.market == instrument.venue)
            .order_by(
                TaiwanStockQuoteSnapshot.quote_time.desc(),
                TaiwanStockQuoteSnapshot.id.desc(),
            )
            .limit(32)
            .all()
        )
        if not rows:
            return (
                PersistedPublicQuoteRead(
                    limitations=("PUBLIC_QUOTE_CANDIDATE_MISSING",),
                ),
            )
        reads: list[PersistedPublicQuoteRead] = []
        seen_sources: set[tuple[str, str]] = set()
        for row in rows:
            identity = (row.provider, row.source)
            if identity in seen_sources:
                continue
            seen_sources.add(identity)
            reads.append(self._decode_row(instrument, row))
            if len(reads) >= max_candidates:
                break
        return tuple(reads)

    def load_latest_quote(
        self,
        instrument: InstrumentKey,
    ) -> PersistedPublicQuoteRead:
        """Compatibility single-row read; new callers should read all candidates."""

        return self.load_quote_candidates(instrument, max_candidates=1)[0]


__all__ = [
    "PersistedPublicQuoteRead",
    "TaiwanPublicQuoteRepository",
]
