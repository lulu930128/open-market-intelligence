"""US-owned full-market EOD lifecycle adapter.

The Shared lifecycle receives this adapter as a typed port.  US ORM, calendar,
Gateway acquisition, transaction rollback, and provider diagnostics remain on
the market-owned side of the boundary.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
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
from app.us_market.catalog_store import us_common_stock_universe_filters
from app.us_market.daily_ohlcv_platform import USDailyOhlcvPlatform
from app.us_market.daily_price_eligibility import us_daily_sql_eligibility_filters
from app.utils.owner_checkpoint import OwnerOutcomeUnknown


class USFullMarketEodLifecycle:
    def refresh_grouped_daily(self, db: Session, *, trade_date: date,
                              now: datetime | None = None, acquisition=None) -> dict:
        """Explicit one-date bulk command through the shared refresh planner."""
        from app.market_data.contracts import InstrumentKey, Market
        from app.market_data.integration_contracts import DatasetTarget, RefreshRequirementV1
        from app.market_data.policies import DataPurpose
        from app.market_data.provider_catalog import plan_refresh_acquisition_v1
        from app.us_market.market_data.descriptors import MASSIVE_GROUPED_DAILY_DESCRIPTOR
        from app.us_market.daily_ohlcv_acquisition import USDailyOhlcvAcquisitionExecutor
        from app.us_market.daily_price_transaction import USDailyPriceTransaction

        if db.new or db.dirty or db.deleted:
            raise ValueError("grouped EOD command requires a clean Session")
        now = now or datetime.now(timezone.utc)
        with db.no_autoflush:
            members = db.query(USStockMaster.symbol, USStockMaster.exchange).filter(*us_common_stock_universe_filters()).all()
        if len(members) > 20_000:
            raise ValueError("US grouped universe exceeds 20000 symbol bound")
        instruments = {row.symbol: InstrumentKey(market=Market.US, symbol=row.symbol,
                       venue=row.exchange, instrument_type=InstrumentType.STOCK)
                       for row in members if row.exchange}
        if not instruments:
            return {"status": "blocked", "reason": "EMPTY_ADMITTED_UNIVERSE", "external_call_count": 0}
        requirement = RefreshRequirementV1(dataset_id=US_DATASET_ID,
            target=DatasetTarget(market=Market.US, dataset_id=US_DATASET_ID, scope_key=US_SCOPE_KEY),
            from_date=trade_date, to_date=trade_date, requested_at=now,
            purpose=DataPurpose.BACKGROUND_COLLECTOR, reason_code="US_GROUPED_COMPLETED_EOD",
            max_provider_attempts=1, max_external_calls=1, timeout_seconds=30,
            max_symbols=len(instruments), max_range_days=1,
            postcondition="Raw completed US daily observations persist with auditable universe coverage")
        plan = plan_refresh_acquisition_v1(requirement, (MASSIVE_GROUPED_DAILY_DESCRIPTOR,))
        if plan.unfillable:
            return {"status": "blocked", "reason": "REFRESH_PLAN_UNFILLABLE", "external_call_count": 0}
        acquired, diagnostics = (acquisition or USDailyOhlcvAcquisitionExecutor()).acquire_grouped_daily(
            requirement, plan, instruments=instruments)
        transaction = USDailyPriceTransaction(db)
        persistence = None
        reconciliation = None
        if acquired.receipts:
            try:
                persistence = transaction.persist_bar_acquisition(requirement, acquired)
            except OwnerOutcomeUnknown:
                # The same payload may be committed already. Verify before allowing any retry.
                reconciliation = transaction.reconcile_bar_acquisition(acquired)
                if reconciliation != "committed":
                    raise
        return {**diagnostics, "external_call_count": acquired.summary.external_calls,
                "missing_identity_count": len(members) - len(instruments),
                "status": "partial" if len(instruments) < len(members) and diagnostics["status"] == "complete" else diagnostics["status"],
                "acquisition": acquired.summary.model_dump(mode="json"),
                "provider_health": [item.model_dump(mode="json") for item in acquired.provider_health],
                "persistence": persistence.model_dump(mode="json") if persistence else None,
                "reconciliation": reconciliation}

    def publish_distribution(self, db: Session, *, now: datetime | None = None) -> dict:
        """Reuse the EOD checkpoint writer; reads never build this projection."""
        from app.market_data.eod_coverage import persist_eod_coverage
        from app.us_market.sector_distribution import build_us_sector_distribution

        now = now or datetime.now(timezone.utc)
        coverage = self.compute_coverage(db, expected_trade_date=self.expected_trade_date(now=now))
        snapshot = build_us_sector_distribution(db, now=now, coverage=coverage)
        row = persist_eod_coverage(db, coverage, detail_extra={"us_sector_distribution": snapshot.model_dump(mode="json")})
        return {"checkpoint_id": row.id, "status": snapshot.status, "coverage": snapshot.coverage}

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
            .filter(*us_common_stock_universe_filters())
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
                .filter(*eligibility_filters)
            )
            usable_expected_symbols = {
                str(symbol)
                for (symbol,) in (
                    canonical_rows.with_entities(USDailyPrice.symbol)
                    .filter(USDailyPrice.symbol.in_(symbols))
                    .filter(USDailyPrice.trade_date == expected_trade_date)
                    .distinct()
                    .all()
                )
            }
            # A canonical row on the requested date already proves its maximum
            # eligible date <= requested date. Avoid joining its entire history.
            # Uncovered symbols retain the exact same canonical eligibility scan.
            # No-current dates use the original scope/predicate once, not an
            # additional full-universe IN filter on an already scoped query.
            remaining_symbols = sorted(set(symbols) - usable_expected_symbols) if usable_expected_symbols else symbols
            historical_latest = {
                str(symbol): latest
                for symbol, latest in (
                    canonical_rows.filter(USDailyPrice.symbol.in_(remaining_symbols)).with_entities(
                        USDailyPrice.symbol,
                        func.max(USDailyPrice.trade_date),
                    )
                    .filter(USDailyPrice.trade_date <= expected_trade_date)
                    .group_by(USDailyPrice.symbol)
                    .all()
                )
                if latest is not None
            } if remaining_symbols else {}
            latest_by_symbol = {symbol: expected_trade_date for symbol in usable_expected_symbols}
            latest_by_symbol.update(historical_latest)
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
        max_external_calls: int = 2,
    ) -> dict[str, Any]:
        try:
            refreshed = USDailyOhlcvPlatform(db).refresh(
                symbol=symbol,
                bars=5,
                to_date=expected_trade_date,
                max_provider_calls=max_external_calls,
            )
        except Exception as exc:
            try:
                db.rollback()
            except Exception as rollback_exc:
                raise OwnerOutcomeUnknown("US_EOD_PROVIDER_ROLLBACK_UNKNOWN") from rollback_exc
            if isinstance(exc, SQLAlchemyError):
                raise OwnerOutcomeUnknown("US_EOD_PROVIDER_PERSISTENCE_UNKNOWN") from exc
            raise
        return {
            "status": (
                "completed" if refreshed.postcondition_satisfied else "partial"
            ),
            "postcondition_met": refreshed.postcondition_satisfied,
            "projection": refreshed.projection,
            "external_call_count": (
                refreshed.result.acquisition.external_calls
                if refreshed.result.acquisition is not None else None
            ),
        }


US_FULL_MARKET_EOD_LIFECYCLE = USFullMarketEodLifecycle()


__all__ = ["US_FULL_MARKET_EOD_LIFECYCLE", "USFullMarketEodLifecycle"]
