"""Read-only official completed-session Taiwan breadth candidates."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timezone
from decimal import Decimal
import logging
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, load_only
from sqlalchemy import inspect, func

from app.market.daily_price_repository import TaiwanOfficialDailyBarRepository, _TRUSTED_OFFICIAL_RELIABILITY
from app.db.models import RawFetchResult, SourceRegistry, TaiwanPublishedBreadthSnapshot
from app.market.taiwan_rules import taiwan_daily_price_release_at
from app.sources.defaults import TWSE_RWD_DAILY_TRADING_SOURCE_NAME
from app.parsers.twse_published_breadth import PublishedStockBreadth, TWSE_AGGREGATE_SCOPE
from app.market_data.contracts import (
    Market,
    MarketBreadthObservation,
    MarketSession,
    ObservationState,
    SourceLineage,
    AuthorityClass,
)


TAIWAN_TZ = ZoneInfo("Asia/Taipei")
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OfficialBreadthRead:
    observation: MarketBreadthObservation | None
    provider_priority: int = 100
    rows_examined: int = 0
    limitations: tuple[str, ...] = ()


class TaiwanOfficialBreadthRepository:
    """Aggregate one coherent canonical daily receipt over an active universe."""

    def __init__(self, db: Session, *, available_at: datetime | None = None) -> None:
        self._db = db
        self._available_at = available_at or datetime.now(timezone.utc)

    def _load_published_breadth(self, trade_date: date) -> OfficialBreadthRead | None:
        """Reuse a release-qualified receipt committed by official daily acquisition.

        The stock aggregate is a different scope from the active-stock bar universe.
        No row-level evaluated coverage is manufactured from published totals.
        """
        if not inspect(self._db.connection()).has_table(TaiwanPublishedBreadthSnapshot.__tablename__):
            return None
        row = self._db.query(TaiwanPublishedBreadthSnapshot, RawFetchResult).join(
            RawFetchResult, RawFetchResult.id == TaiwanPublishedBreadthSnapshot.raw_result_id
        ).join(SourceRegistry, SourceRegistry.id == RawFetchResult.source_id).options(
            load_only(RawFetchResult.id, RawFetchResult.fetched_at, RawFetchResult.content_hash),
        ).filter(
            TaiwanPublishedBreadthSnapshot.venue == "TWSE",
            TaiwanPublishedBreadthSnapshot.trade_date == trade_date,
            RawFetchResult.fetched_at >= taiwan_daily_price_release_at(trade_date).astimezone(timezone.utc).replace(tzinfo=None),
            SourceRegistry.source_name == TWSE_RWD_DAILY_TRADING_SOURCE_NAME,
            func.lower(SourceRegistry.reliability_level).in_(tuple(_TRUSTED_OFFICIAL_RELIABILITY)),
            RawFetchResult.status_code == 200,
            RawFetchResult.error_message.is_(None),
            RawFetchResult.fetched_at <= self._available_at.astimezone(timezone.utc).replace(tzinfo=None),
        ).order_by(RawFetchResult.fetched_at.desc(), RawFetchResult.id.desc()).first()
        if row is None:
            return None
        stored, raw = row
        try:
            if stored.error_code or not stored.payload_json:
                raise ValueError(stored.error_code or "TWSE_AGGREGATE_PAYLOAD_MISSING")
            parsed = PublishedStockBreadth.model_validate_json(stored.payload_json)
            if parsed.trade_date != trade_date:
                raise ValueError("TWSE_AGGREGATE_DATE_MISMATCH")
        except (ValueError, TypeError) as exc:
            logger.warning("Official breadth aggregate receipt %s rejected: %s", raw.id, exc)
            return OfficialBreadthRead(None, limitations=("OFFICIAL_AGGREGATE_RECEIPT_REJECTED",))
        observation = MarketBreadthObservation(
            market=Market.TW, venue="TWSE", trade_date=trade_date,
            lineage=SourceLineage(provider="twse_rwd", source=TWSE_RWD_DAILY_TRADING_SOURCE_NAME,
                authority=AuthorityClass.EXCHANGE, raw_contract_version="twse_mi_index_breadth.v1",
                event_at=datetime.combine(trade_date, time(13, 30), tzinfo=TAIWAN_TZ),
                fetched_at=raw.fetched_at.replace(tzinfo=timezone.utc) if raw.fetched_at.tzinfo is None else raw.fetched_at,
                cache_hit=True, raw_receipt_id=f"raw_fetch_result:{raw.id}", content_hash=raw.content_hash),
            session=MarketSession.CLOSED, scope=TWSE_AGGREGATE_SCOPE,
            universe_source="twse.mi_index.stock_column.all_reported_categories",
            universe_count=parsed.limits.universe_count,
            advance_count=parsed.advance, decline_count=parsed.decline,
            unchanged_count=parsed.unchanged,
            unknown_count=parsed.no_trade + parsed.no_comparison, missing_count=0,
            published_limits=parsed.limits, state=ObservationState.PARTIAL,
            price_semantics="exchange_published_stock_breadth", official=True, provisional=False,
        )
        return OfficialBreadthRead(observation, provider_priority=5, rows_examined=1,
            limitations=("OFFICIAL_AGGREGATE_DISTINCT_SCOPE", "BREADTH_TRADE_VALUE_UNAVAILABLE"))

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
        published_limitations = ()
        if normalized_venue == "TWSE":
            published = self._load_published_breadth(trade_date)
            if published is not None and published.observation is not None:
                return published
            if published is not None:
                published_limitations = published.limitations
        universe = TaiwanOfficialDailyBarRepository(self._db, available_at=self._available_at).load_market_universe(
            trade_date=trade_date,
            include_etf=False,
            venue=normalized_venue,
            max_rows=max_rows,
        )
        if published_limitations:
            universe = replace(universe, limitations=(*universe.limitations, *published_limitations))
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
