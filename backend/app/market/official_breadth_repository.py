"""Read-only official completed-session Taiwan breadth candidates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.market.daily_price_repository import TaiwanOfficialDailyBarRepository
from app.market_data.contracts import (
    Market,
    MarketBreadthObservation,
    MarketSession,
    ObservationState,
    SourceLineage,
)


TAIWAN_TZ = ZoneInfo("Asia/Taipei")


@dataclass(frozen=True, slots=True)
class OfficialBreadthRead:
    observation: MarketBreadthObservation | None
    provider_priority: int = 100
    rows_examined: int = 0
    limitations: tuple[str, ...] = ()


class TaiwanOfficialBreadthRepository:
    """Aggregate one coherent canonical daily receipt over an active universe."""

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
        if normalized_venue not in {"TWSE", "TPEX"}:
            raise ValueError("official Taiwan breadth requires venue=TWSE or TPEX")
        universe = TaiwanOfficialDailyBarRepository(self._db).load_market_universe(
            trade_date=trade_date,
            include_etf=False,
            venue=normalized_venue,
            max_rows=max_rows,
        )
        if universe.universe_count == 0:
            return OfficialBreadthRead(
                observation=None,
                limitations=universe.limitations or ("ACTIVE_STOCK_UNIVERSE_EMPTY",),
            )
        bars = universe.bars
        if not bars:
            return OfficialBreadthRead(
                observation=None,
                rows_examined=universe.rows_examined,
                limitations=tuple(
                    dict.fromkeys(
                        (*universe.limitations, "OFFICIAL_BREADTH_DATE_MISSING")
                    )
                ),
            )
        raw_receipts = {bar.lineage.raw_receipt_id for bar in bars}
        sources = {(bar.lineage.provider, bar.lineage.source) for bar in bars}
        if len(raw_receipts) != 1 or None in raw_receipts or len(sources) != 1:
            return OfficialBreadthRead(
                observation=None,
                rows_examined=universe.rows_examined,
                limitations=tuple(
                    dict.fromkeys(
                        (
                            *universe.limitations,
                            "BREADTH_COMPONENT_LINEAGE_NOT_COHERENT",
                        )
                    )
                ),
            )
        first_lineage = bars[0].lineage
        advance_count = decline_count = unchanged_count = unknown_count = 0
        missing_count = max(universe.universe_count - len(bars), 0)
        trade_value = 0
        trade_value_complete = missing_count == 0
        for bar in bars:
            if bar.price_change is None:
                unknown_count += 1
            elif bar.price_change > 0:
                advance_count += 1
            elif bar.price_change < 0:
                decline_count += 1
            else:
                unchanged_count += 1
            if bar.turnover_value is None:
                trade_value_complete = False
            else:
                trade_value += int(bar.turnover_value)

        incomplete = unknown_count > 0 or missing_count > 0
        limitations: list[str] = list(universe.limitations)
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
                provider=first_lineage.provider,
                source=first_lineage.source,
                authority=first_lineage.authority,
                raw_contract_version=first_lineage.raw_contract_version,
                event_at=end_at,
                fetched_at=max(bar.lineage.fetched_at for bar in bars),
                cache_hit=True,
                observation_id=(
                    f"market_breadth:{normalized_venue}:{trade_date.isoformat()}"
                ),
                raw_receipt_id=first_lineage.raw_receipt_id,
                content_hash=first_lineage.content_hash,
            ),
            session=MarketSession.CLOSED,
            trade_date=trade_date,
            scope="active_ordinary_stock_universe",
            universe_source=(
                f"stock_master.active.{normalized_venue}.ordinary_stock"
            ),
            universe_count=universe.universe_count,
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
            rows_examined=universe.rows_examined,
            limitations=tuple(dict.fromkeys(limitations)),
        )


__all__ = ["OfficialBreadthRead", "TaiwanOfficialBreadthRepository"]
