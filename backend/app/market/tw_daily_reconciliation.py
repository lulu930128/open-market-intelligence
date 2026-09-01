"""Taiwan completed-daily reconciliation without mutating Bar numerics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import json

from sqlalchemy.orm import Session

from app.db.models import (
    MarketDailyPrice,
    MarketDailyPriceReconciliation,
    MarketIndexDailyStat,
    RawFetchResult,
    SourceRegistry,
    utc_now,
)
from app.market.official_index_contract import TPEX_INDEX_SOURCE_NAME
from app.market.tw_bar_contracts import (
    TPEX_DERIVED_DAILY_KIND,
    TaiwanReconciliationStatus,
)
from app.market_data.contracts import AuthorityClass, InstrumentType, Market


@dataclass(frozen=True, slots=True)
class TaiwanDailyReconciliationResult:
    instrument_id: str
    trade_date: date
    status: TaiwanReconciliationStatus
    daily_price_id: int
    reconciliation_id: int
    candidate_close: Decimal
    official_close: Decimal
    numeric_bar_mutated: bool = False


def _decimal(value: float | int | None, *, field: str) -> Decimal:
    if value is None:
        raise ValueError(f"{field} is required for daily reconciliation")
    return Decimal(str(value))


class TaiwanDailyReconciliationTransaction:
    """Persist reconciliation evidence as a side record, never a hybrid Bar."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def reconcile_tpex_daily_stat(
        self,
        *,
        trade_date: date,
    ) -> TaiwanDailyReconciliationResult:
        candidate = (
            self._db.query(MarketDailyPrice)
            .filter(MarketDailyPrice.canonical_market == Market.TW.value)
            .filter(MarketDailyPrice.venue == "TPEX")
            .filter(MarketDailyPrice.instrument_type == InstrumentType.INDEX.value)
            .filter(MarketDailyPrice.stock_id == "TPEX")
            .filter(MarketDailyPrice.trade_date == trade_date)
            .filter(MarketDailyPrice.authority == AuthorityClass.DERIVED.value)
            .filter(MarketDailyPrice.official.is_(False))
            .filter(MarketDailyPrice.derivation_kind == TPEX_DERIVED_DAILY_KIND)
            .one_or_none()
        )
        if candidate is None:
            raise ValueError("TPEX_DERIVED_DAILY_CANDIDATE_MISSING")

        evidence = (
            self._db.query(MarketIndexDailyStat, SourceRegistry, RawFetchResult)
            .join(SourceRegistry, SourceRegistry.id == MarketIndexDailyStat.source_id)
            .join(RawFetchResult, RawFetchResult.id == MarketIndexDailyStat.raw_result_id)
            .filter(MarketIndexDailyStat.index_id == "TPEX")
            .filter(MarketIndexDailyStat.trade_date == trade_date)
            .one_or_none()
        )
        if evidence is None:
            raise ValueError("TPEX_OFFICIAL_DAILY_STAT_EVIDENCE_MISSING")
        official_stat, source, raw = evidence
        if (
            source.source_name != TPEX_INDEX_SOURCE_NAME
            or str(source.reliability_level or "").strip().lower() != "official"
            or raw.source_id != source.id
            or not raw.content_hash
            or official_stat.close_value is None
        ):
            raise ValueError("TPEX_OFFICIAL_DAILY_STAT_EVIDENCE_INVALID")

        candidate_close = _decimal(candidate.close_price, field="candidate_close")
        official_close = _decimal(official_stat.close_value, field="official_close")
        status = (
            TaiwanReconciliationStatus.MATCHED
            if candidate_close == official_close
            else TaiwanReconciliationStatus.MISMATCHED
        )
        numeric_before = (
            candidate.open_price,
            candidate.high_price,
            candidate.low_price,
            candidate.close_price,
        )
        record = (
            self._db.query(MarketDailyPriceReconciliation)
            .filter(MarketDailyPriceReconciliation.daily_price_id == candidate.id)
            .filter(MarketDailyPriceReconciliation.source_id == source.id)
            .filter(MarketDailyPriceReconciliation.raw_result_id == raw.id)
            .one_or_none()
        )
        try:
            if record is None:
                record = MarketDailyPriceReconciliation(
                    daily_price_id=candidate.id,
                    source_id=source.id,
                    raw_result_id=raw.id,
                )
                self._db.add(record)
            record.status = status.value
            record.candidate_close = float(candidate_close)
            record.official_close = float(official_close)
            record.detail_json = json.dumps(
                {
                    "contract_version": "tw.daily.reconciliation.v1",
                    "evidence_role": "official_close_and_market_stat_only",
                    "numeric_patch_applied": False,
                    "raw_content_hash": raw.content_hash,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            record.checked_at = utc_now()
            candidate.reconciliation_status = status.value
            self._db.flush()
            numeric_after = (
                candidate.open_price,
                candidate.high_price,
                candidate.low_price,
                candidate.close_price,
            )
            if numeric_after != numeric_before:
                raise RuntimeError("TPEX daily reconciliation mutated numeric Bar")
            reconciliation_id = record.id
            daily_price_id = candidate.id
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise
        return TaiwanDailyReconciliationResult(
            instrument_id="TPEX",
            trade_date=trade_date,
            status=status,
            daily_price_id=daily_price_id,
            reconciliation_id=reconciliation_id,
            candidate_close=candidate_close,
            official_close=official_close,
        )


__all__ = [
    "TaiwanDailyReconciliationResult",
    "TaiwanDailyReconciliationTransaction",
]
