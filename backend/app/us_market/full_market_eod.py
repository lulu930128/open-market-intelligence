"""US-owned full-market EOD lifecycle adapter.

The Shared lifecycle receives this adapter as a typed port.  US ORM, calendar,
Gateway acquisition, transaction rollback, and provider diagnostics remain on
the market-owned side of the boundary.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.db.models import USDailyPrice, USStockMaster
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
            lineage_filters = (
                USDailyPrice.source_id.isnot(None),
                USDailyPrice.raw_result_id.isnot(None),
                USDailyPrice.authority.isnot(None),
                USDailyPrice.raw_contract_version.isnot(None),
                USDailyPrice.event_at.isnot(None),
                USDailyPrice.finalization.in_(("final", "corrected")),
                USDailyPrice.price_basis.isnot(None),
                USDailyPrice.volume_status.isnot(None),
            )
            latest_by_symbol = {
                str(symbol): latest
                for symbol, latest in (
                    db.query(
                        USDailyPrice.symbol,
                        func.max(USDailyPrice.trade_date),
                    )
                    .filter(USDailyPrice.symbol.in_(symbols))
                    .filter(USDailyPrice.trade_date <= expected_trade_date)
                    .filter(*lineage_filters)
                    .group_by(USDailyPrice.symbol)
                    .all()
                )
                if latest is not None
            }
            usable_expected_symbols = {
                str(symbol)
                for (symbol,) in (
                    db.query(USDailyPrice.symbol)
                    .filter(USDailyPrice.symbol.in_(symbols))
                    .filter(USDailyPrice.trade_date == expected_trade_date)
                    .filter(*lineage_filters)
                    .filter(
                        or_(
                            USDailyPrice.close_price.isnot(None),
                            USDailyPrice.adjusted_close.isnot(None),
                        )
                    )
                    .distinct()
                    .all()
                )
            }
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
