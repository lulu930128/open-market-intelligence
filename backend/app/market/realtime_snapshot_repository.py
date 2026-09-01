"""Cache-only typed repositories for Taiwan depth and auction candidates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import (
    RawFetchResult,
    SourceRegistry,
    TaiwanStockAuctionSnapshot,
    TaiwanStockDepthLevel,
    TaiwanStockDepthSnapshot,
)
from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_realtime_capabilities import (
    TW_AUCTION_CAPABILITY_ID,
    TW_ORDER_BOOK_CAPABILITY_ID,
    TW_REALTIME_SOURCE_BINDINGS,
    capability_source_binding,
)
from app.market_data.contracts import (
    AuctionObservation,
    AuctionType,
    DepthCapability,
    DepthLevel,
    DepthObservation,
    DepthPriceState,
    InstrumentKey,
    Market,
    MarketSession,
    ObservationState,
    Quantity,
    QuantityUnit,
    SourceLineage,
)


@dataclass(frozen=True, slots=True)
class PersistedDepthRead:
    observation: DepthObservation | None = None
    provider: str | None = None
    source: str | None = None
    provider_priority: int = 100
    storage_row_id: int | None = None
    raw_result_id: int | None = None
    market_session: MarketSession | None = None
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PersistedAuctionRead:
    observation: AuctionObservation | None = None
    provider: str | None = None
    source: str | None = None
    provider_priority: int = 100
    storage_row_id: int | None = None
    raw_result_id: int | None = None
    limitations: tuple[str, ...] = ()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _as_taiwan(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=TAIWAN_TZ)
    return value.astimezone(TAIWAN_TZ)


def _quantity(
    *,
    value,
    unit: str | None,
    original_value=None,
    original_unit: str | None = None,
    scale=None,
) -> Quantity | None:
    if value is None or unit is None:
        return None
    try:
        parsed_unit = QuantityUnit(unit)
        parsed_original_unit = (
            QuantityUnit(original_unit) if original_unit is not None else None
        )
    except ValueError as exc:
        raise ValueError("stored realtime quantity unit is invalid") from exc
    values = dict(
        value=value,
        unit=parsed_unit,
        original_value=original_value,
        original_unit=parsed_original_unit,
    )
    if scale is not None:
        values["scale"] = scale
    return Quantity(**values)


class _RealtimeRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    @staticmethod
    def _validate_target(instrument: InstrumentKey) -> None:
        if instrument.market is not Market.TW:
            raise ValueError("Taiwan realtime repository requires market=TW")
        if instrument.venue not in {"TWSE", "TPEX"}:
            raise ValueError("Taiwan realtime venue must be TWSE or TPEX")

    def _lineage(
        self,
        *,
        capability_id: str,
        provider: str,
        source_name: str,
        source_id: int,
        raw_result_id: int,
        raw_contract_version: str,
        event_at: datetime,
        received_at: datetime,
        fetched_at: datetime,
        observation_id: str,
    ) -> tuple[SourceLineage | None, int, tuple[str, ...]]:
        binding = capability_source_binding(
            capability_id=capability_id,
            provider=provider,
            source=source_name,
        )
        if binding is None:
            return None, 100, ("TW_REALTIME_SOURCE_UNSUPPORTED",)
        joined = (
            self._db.query(RawFetchResult, SourceRegistry)
            .join(SourceRegistry, SourceRegistry.id == RawFetchResult.source_id)
            .filter(RawFetchResult.id == raw_result_id)
            .filter(SourceRegistry.id == source_id)
            .first()
        )
        if joined is None:
            return (
                None,
                binding.descriptor.priority,
                ("TW_REALTIME_LINEAGE_BROKEN",),
            )
        raw, source = joined
        if (
            source.source_name != binding.source
            or raw.source_id != source.id
            or raw.parser_version != binding.parser_version
            or raw_contract_version != binding.parser_version
            or raw.content_hash is None
        ):
            return (
                None,
                binding.descriptor.priority,
                ("TW_REALTIME_SOURCE_IDENTITY_MISMATCH",),
            )
        lineage = SourceLineage(
            provider=provider,
            source=source.source_name,
            authority=binding.descriptor.authority,
            raw_contract_version=raw_contract_version,
            event_at=_as_taiwan(event_at),
            received_at=_as_utc(received_at),
            fetched_at=_as_utc(fetched_at),
            cache_hit=True,
            observation_id=observation_id,
            raw_receipt_id=f"raw_fetch_result:{raw.id}",
            content_hash=raw.content_hash,
        )
        return lineage, binding.descriptor.priority, ()


class TaiwanDepthRepository(_RealtimeRepository):
    def _decode(
        self,
        instrument: InstrumentKey,
        row: TaiwanStockDepthSnapshot,
    ) -> PersistedDepthRead:
        lineage, priority, limitations = self._lineage(
            capability_id=TW_ORDER_BOOK_CAPABILITY_ID,
            provider=row.provider,
            source_name=row.source,
            source_id=row.source_id,
            raw_result_id=row.raw_result_id,
            raw_contract_version=row.raw_contract_version,
            event_at=row.event_at,
            received_at=row.received_at,
            fetched_at=row.fetched_at,
            observation_id=f"taiwan_stock_depth_snapshot:{row.id}",
        )
        if lineage is None:
            return PersistedDepthRead(
                provider=row.provider,
                source=row.source,
                provider_priority=priority,
                storage_row_id=row.id,
                raw_result_id=row.raw_result_id,
                limitations=limitations,
            )
        levels = (
            self._db.query(TaiwanStockDepthLevel)
            .filter(TaiwanStockDepthLevel.snapshot_id == row.id)
            .order_by(TaiwanStockDepthLevel.side, TaiwanStockDepthLevel.level)
            .all()
        )
        try:
            state = ObservationState(row.observation_state)
            capability = DepthCapability(row.depth_capability)
            market_session = MarketSession(row.market_session)
            decoded = {
                side: tuple(
                    DepthLevel(
                        level=level.level,
                        price=level.price,
                        quantity=_quantity(
                            value=level.quantity_value,
                            unit=level.quantity_unit,
                            original_value=level.original_value,
                            original_unit=level.original_unit,
                            scale=level.scale,
                        ),
                        price_state=DepthPriceState(level.price_state),
                    )
                    for level in levels
                    if level.side == side
                )
                for side in ("bid", "ask")
            }
            observation = DepthObservation(
                instrument=instrument,
                lineage=lineage,
                capability=capability,
                bids=decoded["bid"],
                asks=decoded["ask"],
                state=state,
            )
        except (ValueError, TypeError):
            return PersistedDepthRead(
                provider=row.provider,
                source=row.source,
                provider_priority=priority,
                storage_row_id=row.id,
                raw_result_id=row.raw_result_id,
                limitations=("TW_DEPTH_CANONICAL_STATE_INVALID",),
            )
        return PersistedDepthRead(
            observation=observation,
            provider=row.provider,
            source=row.source,
            provider_priority=priority,
            storage_row_id=row.id,
            raw_result_id=row.raw_result_id,
            market_session=market_session,
        )

    def load_candidates(
        self,
        instrument: InstrumentKey,
        *,
        max_candidates: int,
    ) -> tuple[PersistedDepthRead, ...]:
        self._validate_target(instrument)
        if not 1 <= max_candidates <= 8:
            raise ValueError("depth max_candidates must be between 1 and 8")
        base_query = (
            self._db.query(TaiwanStockDepthSnapshot)
            .filter(TaiwanStockDepthSnapshot.stock_id == instrument.symbol)
            .filter(TaiwanStockDepthSnapshot.market == instrument.venue)
        )
        rows: list[TaiwanStockDepthSnapshot] = []
        for binding in sorted(
            (
                item
                for item in TW_REALTIME_SOURCE_BINDINGS
                if item.descriptor.capability_id == TW_ORDER_BOOK_CAPABILITY_ID
            ),
            key=lambda item: item.descriptor.priority,
        ):
            row = (
                base_query.filter(
                    TaiwanStockDepthSnapshot.provider
                    == binding.descriptor.provider_key,
                    TaiwanStockDepthSnapshot.source == binding.source,
                )
                .order_by(
                    TaiwanStockDepthSnapshot.event_at.desc(),
                    TaiwanStockDepthSnapshot.id.desc(),
                )
                .first()
            )
            if row is not None:
                rows.append(row)
                if len(rows) >= max_candidates:
                    break
        if not rows:
            return (PersistedDepthRead(limitations=("TW_DEPTH_CANDIDATE_MISSING",)),)
        reads: list[PersistedDepthRead] = []
        seen: set[tuple[str, str]] = set()
        for row in rows:
            identity = (row.provider, row.source)
            if identity in seen:
                continue
            seen.add(identity)
            reads.append(self._decode(instrument, row))
            if len(reads) >= max_candidates:
                break
        return tuple(reads)


def _best_level(
    *,
    level: int | None,
    price,
    quantity_value,
    quantity_unit: str | None,
    price_state: str | None,
) -> DepthLevel | None:
    if level is None and price is None and quantity_value is None:
        return None
    if level is None or price_state is None:
        raise ValueError("stored auction best level is incomplete")
    return DepthLevel(
        level=level,
        price=price,
        quantity=_quantity(value=quantity_value, unit=quantity_unit),
        price_state=DepthPriceState(price_state),
    )


class TaiwanAuctionRepository(_RealtimeRepository):
    def _decode(
        self,
        instrument: InstrumentKey,
        row: TaiwanStockAuctionSnapshot,
    ) -> PersistedAuctionRead:
        lineage, priority, limitations = self._lineage(
            capability_id=TW_AUCTION_CAPABILITY_ID,
            provider=row.provider,
            source_name=row.source,
            source_id=row.source_id,
            raw_result_id=row.raw_result_id,
            raw_contract_version=row.raw_contract_version,
            event_at=row.event_at,
            received_at=row.received_at,
            fetched_at=row.fetched_at,
            observation_id=f"taiwan_stock_auction_snapshot:{row.id}",
        )
        if lineage is None:
            return PersistedAuctionRead(
                provider=row.provider,
                source=row.source,
                provider_priority=priority,
                storage_row_id=row.id,
                raw_result_id=row.raw_result_id,
                limitations=limitations,
            )
        try:
            state = ObservationState(row.observation_state)
            if state is not ObservationState.INDICATIVE or not row.provisional:
                raise ValueError("auction evidence must remain indicative")
            observation = AuctionObservation(
                instrument=instrument,
                lineage=lineage,
                auction_type=AuctionType(row.auction_type),
                state=state,
                indicative_price=row.indicative_price,
                indicative_quantity=_quantity(
                    value=row.indicative_quantity_value,
                    unit=row.indicative_quantity_unit,
                    original_value=row.indicative_original_value,
                    original_unit=row.indicative_original_unit,
                    scale=row.indicative_scale,
                ),
                best_bid=_best_level(
                    level=row.best_bid_level,
                    price=row.best_bid_price,
                    quantity_value=row.best_bid_quantity_value,
                    quantity_unit=row.best_bid_quantity_unit,
                    price_state=row.best_bid_price_state,
                ),
                best_ask=_best_level(
                    level=row.best_ask_level,
                    price=row.best_ask_price,
                    quantity_value=row.best_ask_quantity_value,
                    quantity_unit=row.best_ask_quantity_unit,
                    price_state=row.best_ask_price_state,
                ),
                provisional=True,
            )
        except (ValueError, TypeError):
            return PersistedAuctionRead(
                provider=row.provider,
                source=row.source,
                provider_priority=priority,
                storage_row_id=row.id,
                raw_result_id=row.raw_result_id,
                limitations=("TW_AUCTION_CANONICAL_STATE_INVALID",),
            )
        return PersistedAuctionRead(
            observation=observation,
            provider=row.provider,
            source=row.source,
            provider_priority=priority,
            storage_row_id=row.id,
            raw_result_id=row.raw_result_id,
        )

    def load_candidates(
        self,
        instrument: InstrumentKey,
        *,
        max_candidates: int,
        auction_type: AuctionType,
    ) -> tuple[PersistedAuctionRead, ...]:
        self._validate_target(instrument)
        if not 1 <= max_candidates <= 8:
            raise ValueError("auction max_candidates must be between 1 and 8")
        base_query = (
            self._db.query(TaiwanStockAuctionSnapshot)
            .filter(TaiwanStockAuctionSnapshot.stock_id == instrument.symbol)
            .filter(TaiwanStockAuctionSnapshot.market == instrument.venue)
            .filter(TaiwanStockAuctionSnapshot.auction_type == auction_type.value)
        )
        rows: list[TaiwanStockAuctionSnapshot] = []
        for binding in sorted(
            (
                item
                for item in TW_REALTIME_SOURCE_BINDINGS
                if item.descriptor.capability_id == TW_AUCTION_CAPABILITY_ID
            ),
            key=lambda item: item.descriptor.priority,
        ):
            row = (
                base_query.filter(
                    TaiwanStockAuctionSnapshot.provider
                    == binding.descriptor.provider_key,
                    TaiwanStockAuctionSnapshot.source == binding.source,
                )
                .order_by(
                    TaiwanStockAuctionSnapshot.event_at.desc(),
                    TaiwanStockAuctionSnapshot.id.desc(),
                )
                .first()
            )
            if row is not None:
                rows.append(row)
                if len(rows) >= max_candidates:
                    break
        if not rows:
            return (
                PersistedAuctionRead(
                    limitations=("TW_AUCTION_CANDIDATE_MISSING",)
                ),
            )
        reads: list[PersistedAuctionRead] = []
        seen: set[tuple[str, str]] = set()
        for row in rows:
            identity = (row.provider, row.source)
            if identity in seen:
                continue
            seen.add(identity)
            reads.append(self._decode(instrument, row))
            if len(reads) >= max_candidates:
                break
        return tuple(reads)


__all__ = [
    "PersistedAuctionRead",
    "PersistedDepthRead",
    "TaiwanAuctionRepository",
    "TaiwanDepthRepository",
]
