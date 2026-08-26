"""Read persisted official Taiwan index observations without provider I/O."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.db.models import (
    MarketIndexDailyStat,
    RawFetchResult,
    SourceRegistry,
)
from app.market.official_index_contract import (
    TPEX_INDEX_SOURCE_NAME,
    TWSE_INDEX_SOURCE_NAME,
)
from app.market_data.contracts import (
    AuthorityClass,
    BarFinalization,
    Market,
    MarketIndexObservation,
    MarketSession,
    ObservationState,
    Quantity,
    QuantityUnit,
    SourceLineage,
)


TAIWAN_TZ = ZoneInfo("Asia/Taipei")
_INDEX_BINDINGS = {
    "TAIEX": ("TWSE", "twse_openapi", TWSE_INDEX_SOURCE_NAME),
    "TPEX": ("TPEX", "tpex_openapi", TPEX_INDEX_SOURCE_NAME),
}


@dataclass(frozen=True, slots=True)
class OfficialIndexRead:
    observation: MarketIndexObservation | None = None
    provider_priority: int = 100
    rows_examined: int = 0
    limitations: tuple[str, ...] = ()


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class TaiwanOfficialIndexRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def load_market_index(
        self,
        *,
        index_id: str,
        trade_date: date,
    ) -> OfficialIndexRead:
        normalized_index_id = str(index_id or "").strip().upper()
        binding = _INDEX_BINDINGS.get(normalized_index_id)
        if binding is None:
            raise ValueError("official Taiwan index_id must be TAIEX or TPEX")
        venue, provider, source_name = binding
        row = (
            self._db.query(MarketIndexDailyStat)
            .filter(MarketIndexDailyStat.index_id == normalized_index_id)
            .filter(MarketIndexDailyStat.trade_date == trade_date)
            .first()
        )
        if row is None:
            return OfficialIndexRead(limitations=("OFFICIAL_INDEX_DATE_MISSING",))
        if row.source_id is None or row.raw_result_id is None:
            return OfficialIndexRead(
                rows_examined=1,
                limitations=("INDEX_ROW_LINEAGE_MISSING",),
            )
        joined = (
            self._db.query(RawFetchResult, SourceRegistry)
            .join(SourceRegistry, SourceRegistry.id == RawFetchResult.source_id)
            .filter(RawFetchResult.id == row.raw_result_id)
            .filter(SourceRegistry.id == row.source_id)
            .first()
        )
        if joined is None:
            return OfficialIndexRead(
                rows_examined=1,
                limitations=("INDEX_ROW_LINEAGE_BROKEN",),
            )
        raw, source = joined
        if source.source_name != source_name:
            return OfficialIndexRead(
                rows_examined=1,
                limitations=("INDEX_SOURCE_IDENTITY_MISMATCH",),
            )
        if row.close_value is None or row.price_change is None:
            return OfficialIndexRead(
                rows_examined=1,
                limitations=("INDEX_REQUIRED_VALUE_MISSING",),
            )
        incomplete = any(
            value is None
            for value in (
                row.trade_volume,
                row.trade_value,
                row.transaction_count,
            )
        )
        limitations = (
            ("INDEX_MARKET_TOTALS_PARTIAL",) if incomplete else ()
        )
        event_at = datetime.combine(
            trade_date,
            time(13, 30),
            tzinfo=TAIWAN_TZ,
        )
        return OfficialIndexRead(
            observation=MarketIndexObservation(
                market=Market.TW,
                index_id=normalized_index_id,
                venue=venue,
                lineage=SourceLineage(
                    provider=provider,
                    source=source.source_name,
                    authority=AuthorityClass.EXCHANGE,
                    raw_contract_version=raw.parser_version or source.parser_type,
                    event_at=event_at,
                    fetched_at=_as_aware_utc(raw.fetched_at),
                    cache_hit=True,
                    observation_id=(
                        f"market_index:{normalized_index_id}:{trade_date.isoformat()}"
                    ),
                    raw_receipt_id=f"raw_fetch_result:{raw.id}",
                    content_hash=raw.content_hash,
                ),
                session=MarketSession.CLOSED,
                trade_date=trade_date,
                close_value=Decimal(str(row.close_value)),
                price_change=Decimal(str(row.price_change)),
                trade_volume=(
                    Quantity(
                        value=Decimal(row.trade_volume),
                        unit=QuantityUnit.SHARE,
                    )
                    if row.trade_volume is not None
                    else None
                ),
                trade_value=(
                    Decimal(row.trade_value) if row.trade_value is not None else None
                ),
                currency=("TWD" if row.trade_value is not None else None),
                transaction_count=row.transaction_count,
                state=(
                    ObservationState.PARTIAL
                    if incomplete
                    else ObservationState.AVAILABLE
                ),
                value_semantics="official_market_index_close",
                finalization=BarFinalization.FINAL,
                official=True,
                provisional=False,
            ),
            provider_priority=max(int(source.priority), 0),
            rows_examined=1,
            limitations=limitations,
        )


__all__ = ["OfficialIndexRead", "TaiwanOfficialIndexRepository"]
