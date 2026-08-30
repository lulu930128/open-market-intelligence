"""US-owned full-market EOD lifecycle adapter.

The Shared lifecycle receives this adapter as a typed port.  US ORM, calendar,
Gateway acquisition, transaction rollback, and provider diagnostics remain on
the market-owned side of the boundary.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import RawFetchResult, SourceRegistry, USDailyPrice, USStockMaster
from app.market_data.contracts import InstrumentType
from app.market_data.eod_coverage import (
    CoverageComputation,
    US_DATASET_ID,
    US_SCOPE_KEY,
    UniverseMember,
    _classify_symbols,
    _universe_hash,
)
from app.us_market.daily_market_state import expected_us_completed_daily_state
from app.us_market.daily_ohlcv_platform import USDailyOhlcvPlatform
from app.us_market.daily_price_eligibility import us_daily_sql_eligibility_filters


class USFullMarketEodLifecycle:
    def expected_trade_date(self, *, now: datetime | None = None) -> date:
        decision_time = now or datetime.now(timezone.utc)
        return expected_us_completed_daily_state(now=decision_time).expected_trade_date

    def compute_coverage(
        self,
        db: Session,
        *,
        expected_trade_date: date,
    ) -> CoverageComputation:
        rows = (
            db.query(USStockMaster.symbol, USStockMaster.exchange)
            .filter(USStockMaster.is_active.is_(True))
            .filter(func.lower(USStockMaster.asset_type) == "stock")
            .filter(USStockMaster.is_test_issue.is_(False))
            .order_by(USStockMaster.symbol.asc())
            .all()
        )
        members = tuple(
            UniverseMember(
                symbol=str(row.symbol),
                venue=str(row.exchange or "UNKNOWN"),
            )
            for row in rows
        )
        symbols = [member.symbol for member in members]
        latest_by_symbol: dict[str, date] = {}
        usable_expected_symbols: set[str] = set()
        if symbols:
            eligibility_filters = us_daily_sql_eligibility_filters(
                instrument_type=InstrumentType.STOCK,
            )
            canonical_rows = (
                db.query(USDailyPrice)
                .join(RawFetchResult, RawFetchResult.id == USDailyPrice.raw_result_id)
                .join(SourceRegistry, SourceRegistry.id == USDailyPrice.source_id)
                .filter(USDailyPrice.symbol.in_(symbols))
                .filter(*eligibility_filters)
            )
            latest_by_symbol = {
                str(symbol): latest
                for symbol, latest in (
                    canonical_rows.with_entities(
                        USDailyPrice.symbol,
                        func.max(USDailyPrice.trade_date),
                    )
                    .filter(USDailyPrice.trade_date <= expected_trade_date)
                    .group_by(USDailyPrice.symbol)
                    .all()
                )
                if latest is not None
            }
            usable_expected_symbols = {
                str(symbol)
                for (symbol,) in (
                    canonical_rows.with_entities(USDailyPrice.symbol)
                    .filter(USDailyPrice.trade_date == expected_trade_date)
                    .distinct()
                    .all()
                )
            }
            observed_expected_symbols = {
                str(symbol)
                for (symbol,) in (
                    db.query(USDailyPrice.symbol)
                    .filter(USDailyPrice.symbol.in_(symbols))
                    .filter(USDailyPrice.trade_date == expected_trade_date)
                    .distinct()
                    .all()
                )
            }
            for symbol in observed_expected_symbols - usable_expected_symbols:
                latest_by_symbol[symbol] = expected_trade_date
        current, partial, stale, missing = _classify_symbols(
            members=members,
            latest_by_symbol=latest_by_symbol,
            usable_expected_symbols=usable_expected_symbols,
            expected_trade_date=expected_trade_date,
        )
        return CoverageComputation(
            market="US",
            dataset_id=US_DATASET_ID,
            scope_key=US_SCOPE_KEY,
            universe_source=(
                "us_stock_master.active.nasdaq_trader.non_etf_non_test_stock"
            ),
            expected_trade_date=expected_trade_date,
            latest_data_date=max(latest_by_symbol.values(), default=None),
            universe_hash=_universe_hash(members),
            members=members,
            current_symbols=current,
            partial_symbols=partial,
            stale_symbols=stale,
            missing_symbols=missing,
        )

    def refresh_symbol(
        self,
        db: Session,
        *,
        symbol: str,
        expected_trade_date: date,
    ) -> dict[str, Any]:
        try:
            refreshed = USDailyOhlcvPlatform(db).refresh(
                symbol=symbol,
                bars=5,
                to_date=expected_trade_date,
            )
        except Exception:
            db.rollback()
            raise
        return {
            "status": (
                "completed" if refreshed.postcondition_satisfied else "partial"
            ),
            "postcondition_met": refreshed.postcondition_satisfied,
            "projection": refreshed.projection,
        }


US_FULL_MARKET_EOD_LIFECYCLE = USFullMarketEodLifecycle()


__all__ = ["US_FULL_MARKET_EOD_LIFECYCLE", "USFullMarketEodLifecycle"]
