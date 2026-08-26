"""Read-only official completed-session Taiwan breadth candidates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    MarketDailyPrice,
    RawFetchResult,
    SourceRegistry,
    StockMaster,
)
from app.market_data.candidate_repository import CandidateReadLimitExceeded
from app.market_data.contracts import (
    AuthorityClass,
    Market,
    MarketBreadthObservation,
    MarketSession,
    ObservationState,
    SourceLineage,
)
from app.sources.defaults import (
    TPEX_DAILY_QUOTES_SOURCE_NAME,
    TWSE_DAILY_TRADING_SOURCE_NAME,
)


TAIWAN_TZ = ZoneInfo("Asia/Taipei")


@dataclass(frozen=True, slots=True)
class OfficialBreadthRead:
    observation: MarketBreadthObservation | None
    provider_priority: int = 100
    rows_examined: int = 0
    limitations: tuple[str, ...] = ()


_SOURCE_BY_VENUE = {
    "TWSE": ("twse_openapi", TWSE_DAILY_TRADING_SOURCE_NAME),
    "TPEX": ("tpex_openapi", TPEX_DAILY_QUOTES_SOURCE_NAME),
}


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class TaiwanOfficialBreadthRepository:
    """Aggregate one coherent official receipt over the active stock universe."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def load_market_breadth(
        self,
        *,
        venue: str,
        trade_date: date,
        max_rows: int,
    ) -> OfficialBreadthRead:
        normalized_venue = str(venue or "").strip().upper()
        binding = _SOURCE_BY_VENUE.get(normalized_venue)
        if binding is None:
            raise ValueError("official Taiwan breadth requires venue=TWSE or TPEX")
        provider, source_name = binding
        universe_rows = (
            self._db.query(StockMaster.stock_id)
            .filter(StockMaster.is_active.is_(True))
            .filter(func.upper(StockMaster.market) == normalized_venue)
            .filter(func.lower(StockMaster.instrument_type) == "stock")
            .order_by(StockMaster.stock_id.asc())
            .limit(max_rows + 1)
            .all()
        )
        if len(universe_rows) > max_rows:
            raise CandidateReadLimitExceeded(
                "Taiwan breadth universe exceeded max_rows"
            )
        universe = tuple(str(row.stock_id) for row in universe_rows)
        if not universe:
            return OfficialBreadthRead(
                observation=None,
                limitations=("ACTIVE_STOCK_UNIVERSE_EMPTY",),
            )

        rows = (
            self._db.query(MarketDailyPrice, RawFetchResult, SourceRegistry)
            .join(RawFetchResult, RawFetchResult.id == MarketDailyPrice.raw_result_id)
            .join(SourceRegistry, SourceRegistry.id == MarketDailyPrice.source_id)
            .filter(SourceRegistry.source_name == source_name)
            .filter(MarketDailyPrice.trade_date == trade_date)
            .filter(MarketDailyPrice.stock_id.in_(universe))
            .order_by(MarketDailyPrice.stock_id.asc())
            .limit(max_rows + 1)
            .all()
        )
        if len(rows) > max_rows:
            raise CandidateReadLimitExceeded(
                "Taiwan breadth row read exceeded max_rows"
            )
        if not rows:
            return OfficialBreadthRead(
                observation=None,
                rows_examined=0,
                limitations=("OFFICIAL_BREADTH_DATE_MISSING",),
            )

        raw_results = {raw.id: raw for _, raw, _ in rows}
        sources = {source.id: source for _, _, source in rows}
        if len(raw_results) != 1 or len(sources) != 1:
            return OfficialBreadthRead(
                observation=None,
                rows_examined=len(rows),
                limitations=("BREADTH_COMPONENT_LINEAGE_NOT_COHERENT",),
            )
        raw = next(iter(raw_results.values()))
        source = next(iter(sources.values()))
        row_by_symbol = {row.stock_id: row for row, _, _ in rows}
        advance_count = decline_count = unchanged_count = unknown_count = 0
        missing_count = 0
        trade_value = 0
        trade_value_complete = True
        for symbol in universe:
            row = row_by_symbol.get(symbol)
            if row is None:
                missing_count += 1
                continue
            if row.price_change is None:
                unknown_count += 1
            elif row.price_change > 0:
                advance_count += 1
            elif row.price_change < 0:
                decline_count += 1
            else:
                unchanged_count += 1
            if row.trade_value is None:
                trade_value_complete = False
            else:
                trade_value += int(row.trade_value)

        incomplete = unknown_count > 0 or missing_count > 0
        limitations: list[str] = []
        if unknown_count:
            limitations.append("BREADTH_PRICE_CHANGE_UNKNOWN")
        if missing_count:
            limitations.append("BREADTH_UNIVERSE_ROWS_MISSING")
        if not trade_value_complete:
            limitations.append("BREADTH_TRADE_VALUE_PARTIAL")
        end_at = datetime.combine(trade_date, time(13, 30), tzinfo=TAIWAN_TZ)
        observation = MarketBreadthObservation(
            market=Market.TW,
            venue=normalized_venue,
            lineage=SourceLineage(
                provider=provider,
                source=source.source_name,
                authority=AuthorityClass.EXCHANGE,
                raw_contract_version=raw.parser_version or source.parser_type,
                event_at=end_at,
                fetched_at=_as_aware_utc(raw.fetched_at),
                cache_hit=True,
                observation_id=(
                    f"market_breadth:{normalized_venue}:{trade_date.isoformat()}"
                ),
                raw_receipt_id=f"raw_fetch_result:{raw.id}",
                content_hash=raw.content_hash,
            ),
            session=MarketSession.CLOSED,
            trade_date=trade_date,
            scope="active_ordinary_stock_universe",
            universe_source=(
                f"stock_master.active.{normalized_venue}.ordinary_stock"
            ),
            universe_count=len(universe),
            advance_count=advance_count,
            decline_count=decline_count,
            unchanged_count=unchanged_count,
            unknown_count=unknown_count,
            missing_count=missing_count,
            trade_value=(Decimal(trade_value) if trade_value_complete else None),
            currency=("TWD" if trade_value_complete else None),
            state=(
                ObservationState.PARTIAL
                if incomplete or not trade_value_complete
                else ObservationState.AVAILABLE
            ),
            price_semantics="official_session_price_change",
            official=True,
            provisional=False,
        )
        return OfficialBreadthRead(
            observation=observation,
            provider_priority=max(int(source.priority), 0),
            rows_examined=len(rows),
            limitations=tuple(limitations),
        )


__all__ = ["OfficialBreadthRead", "TaiwanOfficialBreadthRepository"]
