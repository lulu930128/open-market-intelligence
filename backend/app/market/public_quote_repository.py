"""Read persisted public Taiwan quote candidates without provider I/O."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import and_, func, inspect, or_
from sqlalchemy.orm import Session

from app.db.models import (
    RawFetchResult,
    SourceRegistry,
    TaiwanStockQuoteSnapshot,
)
from app.market.trading_calendar import TAIWAN_TZ, TAIWAN_SESSION_CLOSE_TIME, TAIWAN_CLOSE_RESOLUTION_TIME
from app.market.trading_calendar import taiwan_market_session, taiwan_presentation_session
from app.market.tw_current_market_repository import read_breadth_price_states
from app.market.tw_realtime_capabilities import (
    TW_QUOTE_SNAPSHOT_CAPABILITY_ID,
    TW_REALTIME_SOURCE_BINDINGS,
    quote_source_binding,
)
from app.market_data.contracts import (
    InstrumentKey,
    BreadthPriceState,
    InstrumentType,
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
    market_session: MarketSession | None = None
    confirmed_at: datetime | None = None
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
        self._session_close_batch: dict[str, tuple[PersistedPublicQuoteRead, ...]] | None = None

    def _decode_row(
        self,
        instrument: InstrumentKey,
        row: TaiwanStockQuoteSnapshot,
        *,
        joined_lineage: tuple[RawFetchResult, SourceRegistry] | None = None,
        lineage_preloaded: bool = False,
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
        joined = joined_lineage if lineage_preloaded else (
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
            market_session=session,
            confirmed_at=max(
                _as_utc(row.received_at),
                _as_utc(raw.fetched_at),
            ),
            rows_examined=1,
        )

    @staticmethod
    def _session_close_storage_predicates(trade_date: date) -> tuple:
        close_at = datetime.combine(trade_date, TAIWAN_SESSION_CLOSE_TIME, tzinfo=TAIWAN_TZ)
        confirmed_at = datetime.combine(trade_date, TAIWAN_CLOSE_RESOLUTION_TIME, tzinfo=TAIWAN_TZ)
        return (
            TaiwanStockQuoteSnapshot.quote_time >= close_at,
            TaiwanStockQuoteSnapshot.quote_time <= confirmed_at,
            or_(TaiwanStockQuoteSnapshot.received_at >= _as_utc(confirmed_at),
                RawFetchResult.fetched_at >= _as_utc(confirmed_at)),
        )

    def preload_session_close_candidates(
        self, instruments: tuple[InstrumentKey, ...], *, requested_at: datetime,
    ) -> None:
        """Request-local, bounded batch; the existing candidate reader still qualifies closes."""
        if len(instruments) > 5000:
            raise ValueError("session-close batch exceeds ordinary-universe bound")
        expected = taiwan_presentation_session(requested_at)["trade_date"]
        collected: dict[str, list[PersistedPublicQuoteRead]] = {item.symbol: [] for item in instruments}
        for offset in range(0, len(instruments), 400):
            chunk = {item.symbol: item for item in instruments[offset:offset + 400]}
            # Latest actual closeout per source. Role qualification precedes the
            # window bound, so a later no-trade receipt cannot erase the close.
            ranked = self._db.query(
                TaiwanStockQuoteSnapshot.id.label("id"),
                func.row_number().over(
                    partition_by=(TaiwanStockQuoteSnapshot.stock_id, TaiwanStockQuoteSnapshot.market,
                                  TaiwanStockQuoteSnapshot.provider, TaiwanStockQuoteSnapshot.source),
                    order_by=(TaiwanStockQuoteSnapshot.quote_time.desc(), TaiwanStockQuoteSnapshot.id.desc()),
                ).label("ordinal"),
            ).outerjoin(RawFetchResult, RawFetchResult.id == TaiwanStockQuoteSnapshot.raw_result_id).filter(
                TaiwanStockQuoteSnapshot.stock_id.in_(chunk),
                or_(*(and_(TaiwanStockQuoteSnapshot.provider == binding.descriptor.provider_key,
                           TaiwanStockQuoteSnapshot.source == binding.source)
                      for binding in TW_REALTIME_SOURCE_BINDINGS
                      if binding.descriptor.capability_id == TW_QUOTE_SNAPSHOT_CAPABILITY_ID)),
                TaiwanStockQuoteSnapshot.trade_date == expected,
                *self._session_close_storage_predicates(expected),
                TaiwanStockQuoteSnapshot.market_session.in_(("closing_auction", "close_resolution", "post_close")),
                TaiwanStockQuoteSnapshot.trade_state == TradeObservationState.TRADE_OBSERVED.value,
                TaiwanStockQuoteSnapshot.last_price.isnot(None),
                TaiwanStockQuoteSnapshot.received_at <= _as_utc(requested_at),
                RawFetchResult.fetched_at <= _as_utc(requested_at),
            ).subquery()
            rows = self._db.query(TaiwanStockQuoteSnapshot, RawFetchResult, SourceRegistry).join(
                ranked, ranked.c.id == TaiwanStockQuoteSnapshot.id,
            ).outerjoin(RawFetchResult, RawFetchResult.id == TaiwanStockQuoteSnapshot.raw_result_id).outerjoin(
                SourceRegistry, SourceRegistry.id == TaiwanStockQuoteSnapshot.source_id,
            ).filter(ranked.c.ordinal == 1).all()
            for row, raw, source in rows:
                instrument = chunk[row.stock_id]
                if row.market != instrument.venue:
                    continue
                collected[row.stock_id].append(self._decode_row(
                    instrument, row, joined_lineage=(raw, source) if raw is not None and source is not None else None,
                    lineage_preloaded=True,
                ))
        for venue in sorted({item.venue for item in instruments}):
            venue_instruments = [item for item in instruments if item.venue == venue]
            price_states = read_breadth_price_states(self._db, venue=venue,
                requested_at=requested_at, trade_date=expected,
                symbols=tuple(item.symbol for item in venue_instruments))
            for instrument in venue_instruments:
                collected[instrument.symbol] = self._merge_price_state(
                    instrument, collected[instrument.symbol], price_states.get(instrument.symbol),
                    trade_date=expected, allowed_sessions=(MarketSession.CLOSING_AUCTION, MarketSession.CLOSE_RESOLUTION, MarketSession.POST_CLOSE),
                )
        self._session_close_batch = {
            symbol: tuple(sorted(reads, key=lambda item: (
                -(item.observation.lineage.event_at.timestamp() if item.observation and item.observation.lineage.event_at else 0),
                item.provider_priority,
            ))[:8]) for symbol, reads in collected.items()
        }

    @staticmethod
    def _merge_price_state(instrument: InstrumentKey, reads: list[PersistedPublicQuoteRead], state: dict | None, *, trade_date: date | None = None, allowed_sessions: tuple[MarketSession, ...] | None = None) -> list[PersistedPublicQuoteRead]:
        if state is not None:
            state = BreadthPriceState.model_validate(state)
            if ((trade_date is not None and state.trade_date != trade_date)
                or (allowed_sessions and taiwan_market_session(state.price_as_of) not in allowed_sessions)):
                state = None
        if state is not None:
            existing = next((item for item in reads if item.provider == state.lineage.provider), None)
            if existing is None or existing.observation is None or (
                existing.observation.last_trade_price is None
                or existing.observation.lineage.event_at < state.price_as_of
            ):
                quote = QuoteObservation(
                    instrument=instrument, lineage=state.lineage.model_copy(update={
                        "cache_hit": True,
                        "observation_id": state.lineage.observation_id
                        or f"{state.lineage.raw_receipt_id}:stock:{instrument.symbol}",
                    }),
                    latest_observation_lineage=(
                        existing.observation.latest_observation_lineage or existing.observation.lineage
                        if existing is not None and existing.observation is not None
                        and existing.observation.trade_date == state.trade_date
                        and (existing.observation.latest_observation_lineage or existing.observation.lineage).event_at >= state.price_as_of
                        else None
                    ),
                    trade_date=state.trade_date, currency="TWD",
                    state=ObservationState.AVAILABLE,
                    trade_state=TradeObservationState.TRADE_OBSERVED,
                    last_trade_price=state.price,
                    previous_close=state.previous_close,
                    cumulative_quantity=_quantity_from_lots(state.cumulative_volume_lots),
                )
                reads = [item for item in reads if item.provider != state.lineage.provider]
                reads.append(PersistedPublicQuoteRead(
                    observation=quote, provider=quote.lineage.provider,
                    source=quote.lineage.source,
                    provider_priority=quote_source_binding(
                        provider=quote.lineage.provider, source="twse_mis_quote_depth",
                    ).descriptor.priority,
                    raw_result_id=int(quote.lineage.raw_receipt_id.split(":")[1]),
                    market_session=taiwan_market_session(state.price_as_of),
                    confirmed_at=max(
                        (value for value in (quote.lineage.received_at, quote.lineage.fetched_at)
                         if value is not None),
                        default=None,
                    ),
                    limitations=("CURRENT_SESSION_LAST_ACTUAL_TRADE",),
                ))
        return reads

    def load_quote_candidates(
        self,
        instrument: InstrumentKey,
        *,
        max_candidates: int = 8,
        trade_date: date | None = None,
        allowed_sessions: tuple[MarketSession, ...] | None = None,
        requested_at: datetime | None = None,
    ) -> tuple[PersistedPublicQuoteRead, ...]:
        if instrument.market is not Market.TW:
            raise ValueError("Taiwan public quote repository requires market=TW")
        if instrument.venue not in {"TWSE", "TPEX"}:
            raise ValueError("Taiwan public quote venue must be TWSE or TPEX")
        if not 1 <= max_candidates <= 8:
            raise ValueError("public quote max_candidates must be between 1 and 8")
        if self._session_close_batch is not None:
            return self._session_close_batch.get(instrument.symbol, ())[:max_candidates]
        base_query = (
            self._db.query(TaiwanStockQuoteSnapshot)
            .filter(TaiwanStockQuoteSnapshot.stock_id == instrument.symbol)
            .filter(TaiwanStockQuoteSnapshot.market == instrument.venue)
        )
        if trade_date is not None:
            base_query = base_query.filter(
                TaiwanStockQuoteSnapshot.trade_date == trade_date
            )
        if allowed_sessions:
            base_query = base_query.filter(
                TaiwanStockQuoteSnapshot.market_session.in_(
                    tuple(session.value for session in allowed_sessions)
                )
            )
        if requested_at is not None:
            # Visibility is a storage predicate, not a freshness override. A
            # later receipt must not hide the candidate visible at request time.
            base_query = base_query.outerjoin(
                RawFetchResult, RawFetchResult.id == TaiwanStockQuoteSnapshot.raw_result_id,
            ).filter(
                or_(TaiwanStockQuoteSnapshot.received_at.is_(None),
                    TaiwanStockQuoteSnapshot.received_at <= _as_utc(requested_at)),
                or_(RawFetchResult.id.is_(None), RawFetchResult.fetched_at <= _as_utc(requested_at)),
            )
        if trade_date is not None and allowed_sessions and requested_at is not None:
            base_query = base_query.filter(*self._session_close_storage_predicates(trade_date))
        quote_bindings = sorted(
            (
                binding
                for binding in TW_REALTIME_SOURCE_BINDINGS
                if binding.descriptor.capability_id
                == TW_QUOTE_SNAPSHOT_CAPABILITY_ID
            ),
            key=lambda binding: binding.descriptor.priority,
        )
        rows_by_id: dict[int, TaiwanStockQuoteSnapshot] = {}
        latest_rows: dict[tuple[str, str], TaiwanStockQuoteSnapshot] = {}
        for binding in quote_bindings:
            row = (
                base_query.filter(
                    TaiwanStockQuoteSnapshot.provider
                    == binding.descriptor.provider_key
                )
                .filter(TaiwanStockQuoteSnapshot.source == binding.source)
                .order_by(
                    TaiwanStockQuoteSnapshot.quote_time.desc(),
                    TaiwanStockQuoteSnapshot.id.desc(),
                )
                .limit(1)
                .first()
            )
            if row is not None:
                latest_rows[(row.provider, row.source)] = row
                # A no-trade message is an observation, not a deletion of the
                # last actual trade. Query by role before applying the bound.
                if row.last_price is None and row.trade_state != TradeObservationState.INDICATIVE_OBSERVED.value:
                    actual = base_query.filter(
                        TaiwanStockQuoteSnapshot.provider == row.provider,
                        TaiwanStockQuoteSnapshot.source == row.source,
                        TaiwanStockQuoteSnapshot.trade_date == row.trade_date,
                        TaiwanStockQuoteSnapshot.trade_state == TradeObservationState.TRADE_OBSERVED.value,
                        TaiwanStockQuoteSnapshot.last_price.isnot(None),
                    ).order_by(TaiwanStockQuoteSnapshot.quote_time.desc(), TaiwanStockQuoteSnapshot.id.desc()).first()
                    if actual is not None:
                        row = actual
                rows_by_id[row.id] = row
                # Inspect at most one role-qualified row per registered source.
                # The outward candidate bound applies after semantic ranking.
        if len(rows_by_id) < max_candidates:
            fallback_rows = (
                base_query.order_by(
                    TaiwanStockQuoteSnapshot.quote_time.desc(),
                    TaiwanStockQuoteSnapshot.id.desc(),
                )
                .limit(max_candidates)
                .all()
            )
            for row in fallback_rows:
                if (row.provider, row.source) in latest_rows:
                    continue
                rows_by_id.setdefault(row.id, row)
                if len(rows_by_id) >= max_candidates:
                    break
        rows = sorted(
            rows_by_id.values(),
            key=lambda row: (row.quote_time, row.id),
            reverse=True,
        )
        if not rows and requested_at is None:
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
            read = self._decode_row(instrument, row)
            latest_row = latest_rows.get(identity)
            if read.observation is not None and latest_row is not None and latest_row.id != row.id:
                latest_read = self._decode_row(instrument, latest_row)
                if latest_read.observation is not None:
                    read = replace(read, observation=read.observation.model_copy(update={
                        "latest_observation_lineage": latest_read.observation.lineage,
                    }))
            reads.append(read)
        if requested_at is not None:
            state = read_current_stock_price_states(
                self._db, venue=instrument.venue, requested_at=requested_at,
                symbols=(instrument.symbol,), trade_date=trade_date,
            ).get(instrument.symbol)
            reads = self._merge_price_state(instrument, reads, state, trade_date=trade_date, allowed_sessions=allowed_sessions)
        expected_date = trade_date or (
            taiwan_presentation_session(requested_at)["trade_date"]
            if requested_at is not None else None
        )
        def candidate_rank(item: PersistedPublicQuoteRead) -> tuple:
            observation = item.observation
            valid = observation is not None
            same_date = valid and (expected_date is None or observation.trade_date == expected_date)
            actual = valid and observation.last_trade_price is not None and observation.trade_state is TradeObservationState.TRADE_OBSERVED
            event = observation.lineage.event_at if valid else None
            return (not same_date, not valid, not actual,
                    -(event.timestamp() if event is not None else 0),
                    item.provider_priority, item.source or "")
        reads.sort(key=candidate_rank)
        return tuple(reads[:max_candidates]) or (PersistedPublicQuoteRead(
            limitations=("PUBLIC_QUOTE_CANDIDATE_MISSING",),
        ),)

    def load_latest_quote(
        self,
        instrument: InstrumentKey,
    ) -> PersistedPublicQuoteRead:
        """Compatibility single-row read; new callers should read all candidates."""

        return self.load_quote_candidates(instrument, max_candidates=1)[0]


def read_current_stock_price_states(
    db: Session, *, venue: str, requested_at: datetime,
    symbols: tuple[str, ...] | None = None,
    trade_date: date | None = None,
) -> dict[str, dict]:
    """One receipt-backed same-session state reader for quote and breadth.

    The two acquisition paths retain their original source identities. Only
    actual trade evidence participates; neither a read nor a provider failure
    creates a new observation or changes a trade's event/receipt time.
    """
    expected_date = trade_date or requested_at.astimezone(TAIWAN_TZ).date()
    if expected_date > requested_at.astimezone(TAIWAN_TZ).date():
        return {}
    states = read_breadth_price_states(db, venue=venue, requested_at=requested_at,
        symbols=symbols, trade_date=expected_date)
    if symbols is not None:
        states = {code: value for code, value in states.items() if code in symbols}
    if not inspect(db.connection()).has_table(TaiwanStockQuoteSnapshot.__tablename__):
        return states
    query = db.query(TaiwanStockQuoteSnapshot.stock_id, func.max(TaiwanStockQuoteSnapshot.quote_time).label("event_at")).filter(
        TaiwanStockQuoteSnapshot.market == venue,
        TaiwanStockQuoteSnapshot.provider == "twse_mis",
        TaiwanStockQuoteSnapshot.source == "twse_mis_quote_depth",
        TaiwanStockQuoteSnapshot.trade_date == expected_date,
        TaiwanStockQuoteSnapshot.quote_time <= requested_at.astimezone(TAIWAN_TZ),
        TaiwanStockQuoteSnapshot.received_at <= _as_utc(requested_at),
        TaiwanStockQuoteSnapshot.trade_state == TradeObservationState.TRADE_OBSERVED.value,
        TaiwanStockQuoteSnapshot.last_price > 0,
    )
    if symbols is not None:
        query = query.filter(TaiwanStockQuoteSnapshot.stock_id.in_(symbols))
    latest = query.group_by(TaiwanStockQuoteSnapshot.stock_id).subquery()
    rows = db.query(TaiwanStockQuoteSnapshot).join(latest,
        (TaiwanStockQuoteSnapshot.stock_id == latest.c.stock_id)
        & (TaiwanStockQuoteSnapshot.quote_time == latest.c.event_at),
    ).filter(TaiwanStockQuoteSnapshot.market == venue,
             TaiwanStockQuoteSnapshot.trade_date == expected_date,
             TaiwanStockQuoteSnapshot.provider == "twse_mis",
             TaiwanStockQuoteSnapshot.source == "twse_mis_quote_depth").all()
    repository = TaiwanPublicQuoteRepository(db)
    for row in rows:
        instrument = InstrumentKey(market=Market.TW, venue=venue,
            symbol=row.stock_id, instrument_type=InstrumentType.STOCK)
        quote = repository._decode_row(instrument, row).observation
        if quote is None or quote.last_trade_price is None:
            continue
        prior = states.get(row.stock_id)
        if prior is not None and prior["price_as_of"] >= quote.lineage.event_at:
            continue
        states[row.stock_id] = BreadthPriceState(
            trade_date=quote.trade_date, price=quote.last_trade_price,
            price_as_of=quote.lineage.event_at, lineage=quote.lineage,
            previous_close=quote.previous_close,
            cumulative_volume_lots=row.total_volume_lots,
        ).model_dump(mode="python")
    return states


__all__ = [
    "PersistedPublicQuoteRead",
    "TaiwanPublicQuoteRepository",
]
