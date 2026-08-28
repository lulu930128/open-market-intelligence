"""Market-owned cache-only freshness projection for canonical Taiwan daily bars."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.db.models import (
    MarketDailyPrice,
    MarketDatasetCoverageCheckpoint,
    RawFetchResult,
    SourceRegistry,
    StockMaster,
)
from app.market.daily_price_repository import (
    taiwan_official_daily_release_qualified_filter,
)
from app.market.taiwan_rules import (
    expected_daily_price_date,
    taiwan_daily_price_release_at,
)
from app.market.trading_calendar import TAIWAN_TZ
from app.market_data.contracts import DatasetHealth
from app.market_data.registry import DATASET_REGISTRY, evaluate_dataset_health
from app.market_data.eod_coverage import TW_DATASET_ID, TW_SCOPE_KEY
from app.sources.defaults import (
    TPEX_DAILY_QUOTES_SOURCE_NAME,
    TWSE_DAILY_TRADING_SOURCE_NAME,
    TWSE_RWD_DAILY_TRADING_SOURCE_NAME,
)


TW_DAILY_DATASET_ID = "tw.daily.ohlcv"


@dataclass(frozen=True, slots=True)
class TaiwanDailyFreshnessEvidence:
    stock_id: str | None
    latest_date: date | None
    row_count: int
    health: DatasetHealth
    latest_updated_at: datetime | None = None
    storage_latest_date: date | None = None
    storage_row_count: int = 0
    limitations: tuple[str, ...] = ()


def _canonical_daily_filter():
    return or_(
        and_(
            func.upper(StockMaster.market) == "TWSE",
            SourceRegistry.source_name.in_(
                (
                    TWSE_RWD_DAILY_TRADING_SOURCE_NAME,
                    TWSE_DAILY_TRADING_SOURCE_NAME,
                )
            ),
        ),
        and_(
            func.upper(StockMaster.market) == "TPEX",
            SourceRegistry.source_name == TPEX_DAILY_QUOTES_SOURCE_NAME,
        ),
    )


def _base_query(db: Session):
    return (
        db.query(MarketDailyPrice)
        .join(RawFetchResult, RawFetchResult.id == MarketDailyPrice.raw_result_id)
        .join(SourceRegistry, SourceRegistry.id == MarketDailyPrice.source_id)
        .join(StockMaster, StockMaster.stock_id == MarketDailyPrice.stock_id)
        .filter(_canonical_daily_filter())
        .filter(MarketDailyPrice.open_price.isnot(None))
        .filter(MarketDailyPrice.high_price.isnot(None))
        .filter(MarketDailyPrice.low_price.isnot(None))
        .filter(MarketDailyPrice.close_price.isnot(None))
    )


def _release_qualified_query(
    db: Session,
    *,
    expected_date: date,
    available_at: datetime,
):
    """Return rows eligible for completed-session freshness.

    Future dates are excluded, and every row must have a raw receipt obtained
    after that row's own 15:15 Asia/Taipei release boundary. The SQL predicate
    is owned by the canonical daily repository so freshness and daily reads
    share the same eligibility policy.
    """

    available_at_storage = available_at.astimezone(timezone.utc).replace(
        tzinfo=None
    )
    return (
        _base_query(db)
        .filter(MarketDailyPrice.trade_date <= expected_date)
        .filter(RawFetchResult.fetched_at <= available_at_storage)
        .filter(taiwan_official_daily_release_qualified_filter())
    )


def _health(
    *,
    latest_date: date | None,
    expected_date: date | None,
    checked_at: datetime,
    partial: bool = False,
) -> DatasetHealth:
    return evaluate_dataset_health(
        DATASET_REGISTRY.get(TW_DAILY_DATASET_ID),
        expected_date=expected_date,
        latest_date=latest_date,
        checked_at=checked_at,
        eligible=True,
        partial=partial,
    )


def _full_market_checkpoint(
    db: Session,
    *,
    expected_date: date,
    checked_at: datetime,
) -> MarketDatasetCoverageCheckpoint | None:
    release_at_storage = (
        taiwan_daily_price_release_at(expected_date)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )
    return (
        db.query(MarketDatasetCoverageCheckpoint)
        .filter(MarketDatasetCoverageCheckpoint.dataset_id == TW_DATASET_ID)
        .filter(MarketDatasetCoverageCheckpoint.scope_key == TW_SCOPE_KEY)
        .filter(MarketDatasetCoverageCheckpoint.expected_trade_date == expected_date)
        .filter(MarketDatasetCoverageCheckpoint.checked_at >= release_at_storage)
        .filter(
            MarketDatasetCoverageCheckpoint.checked_at
            <= checked_at.astimezone(timezone.utc).replace(tzinfo=None)
        )
        .order_by(
            MarketDatasetCoverageCheckpoint.checked_at.desc(),
            MarketDatasetCoverageCheckpoint.id.desc(),
        )
        .first()
    )


def read_taiwan_daily_freshness(
    db: Session,
    *,
    stock_id: str | None = None,
    venue: str | None = None,
    checked_at: datetime | None = None,
    expected_date: date | None = None,
) -> TaiwanDailyFreshnessEvidence:
    """Read canonical daily storage state without provider I/O or mutation."""

    now = checked_at or datetime.now(TAIWAN_TZ)
    normalized_stock_id = str(stock_id or "").strip() or None
    normalized_venue = str(venue or "").strip().upper() or None
    if normalized_venue not in {None, "TWSE", "TPEX"}:
        raise ValueError("Taiwan daily freshness venue must be TWSE or TPEX")
    resolved_expected = expected_date or expected_daily_price_date(now=now)
    storage_query = _base_query(db)
    if normalized_venue is not None:
        storage_query = storage_query.filter(
            func.upper(StockMaster.market) == normalized_venue
        )
    if normalized_stock_id is not None:
        storage_query = storage_query.filter(
            MarketDailyPrice.stock_id == normalized_stock_id
        )
    storage_latest_date, storage_row_count = storage_query.with_entities(
        func.max(MarketDailyPrice.trade_date),
        func.count(MarketDailyPrice.id),
    ).one()
    query = _release_qualified_query(
        db,
        expected_date=resolved_expected,
        available_at=now,
    )
    if normalized_venue is not None:
        query = query.filter(func.upper(StockMaster.market) == normalized_venue)
    if normalized_stock_id is not None:
        query = query.filter(MarketDailyPrice.stock_id == normalized_stock_id)
    latest_date, row_count, latest_updated_at = query.with_entities(
        func.max(MarketDailyPrice.trade_date),
        func.count(func.distinct(MarketDailyPrice.trade_date)),
        func.max(MarketDailyPrice.updated_at),
    ).one()
    limitations: tuple[str, ...] = ()
    partial = False
    if (
        normalized_stock_id is None
        and normalized_venue is None
        and resolved_expected is not None
    ):
        checkpoint = _full_market_checkpoint(
            db,
            expected_date=resolved_expected,
            checked_at=now,
        )
        if checkpoint is not None:
            latest_date = checkpoint.latest_data_date
            partial = checkpoint.status == "partial"
            limitations = (
                "FULL_MARKET_COVERAGE_CHECKPOINT_APPLIED",
                f"FULL_MARKET_CURRENT_{int(checkpoint.current_count or 0)}_OF_{int(checkpoint.universe_count or 0)}",
                f"FULL_MARKET_PARTIAL_{int(checkpoint.partial_count or 0)}",
                f"FULL_MARKET_STALE_{int(checkpoint.stale_count or 0)}",
                f"FULL_MARKET_MISSING_{int(checkpoint.missing_count or 0)}",
            )
    return TaiwanDailyFreshnessEvidence(
        stock_id=normalized_stock_id,
        latest_date=latest_date,
        row_count=int(row_count or 0),
        latest_updated_at=latest_updated_at,
        storage_latest_date=storage_latest_date,
        storage_row_count=int(storage_row_count or 0),
        health=_health(
            latest_date=latest_date,
            expected_date=resolved_expected,
            checked_at=now,
            partial=partial,
        ),
        limitations=limitations,
    )


def read_taiwan_daily_freshness_batch(
    db: Session,
    *,
    stock_ids: list[str],
    checked_at: datetime | None = None,
    expected_date: date | None = None,
) -> dict[str, TaiwanDailyFreshnessEvidence]:
    """Read latest canonical dates for a bounded stock set in one query."""

    normalized = list(
        dict.fromkeys(value.strip() for value in stock_ids if value.strip())
    )
    if not normalized:
        return {}
    now = checked_at or datetime.now(TAIWAN_TZ)
    resolved_expected = expected_date or expected_daily_price_date(now=now)
    storage_rows = (
        _base_query(db)
        .filter(MarketDailyPrice.stock_id.in_(normalized))
        .with_entities(
            MarketDailyPrice.stock_id,
            func.max(MarketDailyPrice.trade_date),
            func.count(MarketDailyPrice.id),
        )
        .group_by(MarketDailyPrice.stock_id)
        .all()
    )
    storage = {
        str(stock_id): (latest_date, int(row_count or 0))
        for stock_id, latest_date, row_count in storage_rows
    }
    rows = (
        _release_qualified_query(
            db,
            expected_date=resolved_expected,
            available_at=now,
        )
        .filter(MarketDailyPrice.stock_id.in_(normalized))
        .with_entities(
            MarketDailyPrice.stock_id,
            func.max(MarketDailyPrice.trade_date),
            func.count(func.distinct(MarketDailyPrice.trade_date)),
            func.max(MarketDailyPrice.updated_at),
        )
        .group_by(MarketDailyPrice.stock_id)
        .all()
    )
    stored = {
        str(stock_id): (latest_date, int(row_count or 0), latest_updated_at)
        for stock_id, latest_date, row_count, latest_updated_at in rows
    }
    return {
        stock_id: TaiwanDailyFreshnessEvidence(
            stock_id=stock_id,
            latest_date=stored.get(stock_id, (None, 0, None))[0],
            row_count=stored.get(stock_id, (None, 0, None))[1],
            latest_updated_at=stored.get(stock_id, (None, 0, None))[2],
            storage_latest_date=storage.get(stock_id, (None, 0))[0],
            storage_row_count=storage.get(stock_id, (None, 0))[1],
            health=_health(
                latest_date=stored.get(stock_id, (None, 0, None))[0],
                expected_date=resolved_expected,
                checked_at=now,
            ),
        )
        for stock_id in normalized
    }


__all__ = [
    "TW_DAILY_DATASET_ID",
    "TaiwanDailyFreshnessEvidence",
    "read_taiwan_daily_freshness",
    "read_taiwan_daily_freshness_batch",
]
