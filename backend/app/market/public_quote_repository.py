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
from app.market.tw_public_quote_contract import (
    TWSE_MIS_QUOTE_PROVIDER,
    TWSE_MIS_QUOTE_SOURCE_NAME,
)
from app.market.trading_calendar import TAIWAN_TZ
from app.market_data.contracts import (
    AuthorityClass,
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

    def load_latest_quote(
        self,
        instrument: InstrumentKey,
    ) -> PersistedPublicQuoteRead:
        if instrument.market is not Market.TW:
            raise ValueError("Taiwan public quote repository requires market=TW")
        if instrument.venue not in {"TWSE", "TPEX"}:
            raise ValueError("Taiwan public quote venue must be TWSE or TPEX")
        row = (
            self._db.query(TaiwanStockQuoteSnapshot)
            .filter(TaiwanStockQuoteSnapshot.provider == TWSE_MIS_QUOTE_PROVIDER)
            .filter(TaiwanStockQuoteSnapshot.source == TWSE_MIS_QUOTE_SOURCE_NAME)
            .filter(TaiwanStockQuoteSnapshot.stock_id == instrument.symbol)
            .filter(TaiwanStockQuoteSnapshot.market == instrument.venue)
            .order_by(
                TaiwanStockQuoteSnapshot.quote_time.desc(),
                TaiwanStockQuoteSnapshot.id.desc(),
            )
            .first()
        )
        if row is None:
            return PersistedPublicQuoteRead(
                limitations=("PUBLIC_QUOTE_CANDIDATE_MISSING",),
            )
        if row.source_id is None or row.raw_result_id is None:
            return PersistedPublicQuoteRead(
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
                storage_row_id=row.id,
                raw_result_id=row.raw_result_id,
                rows_examined=1,
                limitations=("PUBLIC_QUOTE_LINEAGE_BROKEN",),
            )
        raw, source = joined
        if (
            source.source_name != TWSE_MIS_QUOTE_SOURCE_NAME
            or raw.source_id != source.id
            or row.source != source.source_name
            or row.provider != TWSE_MIS_QUOTE_PROVIDER
        ):
            return PersistedPublicQuoteRead(
                storage_row_id=row.id,
                raw_result_id=row.raw_result_id,
                rows_examined=1,
                limitations=("PUBLIC_QUOTE_SOURCE_IDENTITY_MISMATCH",),
            )
        try:
            state = ObservationState(str(row.observation_state))
            session = MarketSession(str(row.market_session))
            trade_state = TradeObservationState(str(row.trade_state))
        except ValueError:
            return PersistedPublicQuoteRead(
                storage_row_id=row.id,
                raw_result_id=row.raw_result_id,
                rows_examined=1,
                limitations=("PUBLIC_QUOTE_CANONICAL_ENUM_INVALID",),
            )
        if trade_state is TradeObservationState.TRADE_OBSERVED and row.last_price is None:
            return PersistedPublicQuoteRead(
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
                authority=AuthorityClass.EXCHANGE,
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
            provider_priority=max(int(source.priority), 0),
            storage_row_id=row.id,
            raw_result_id=raw.id,
            rows_examined=1,
        )


__all__ = [
    "PersistedPublicQuoteRead",
    "TaiwanPublicQuoteRepository",
]
