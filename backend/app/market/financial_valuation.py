from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.market.daily_ohlcv_platform import (
    TaiwanCanonicalDailyRow,
    project_taiwan_daily_rows,
    read_taiwan_official_daily,
)
from app.market.taiwan_rules import expected_daily_price_date
from app.market.trading_calendar import TAIWAN_TZ


DAILY_CLOSE_PRICE_BASIS = "latest_completed_daily_close:canonical_daily"
TRUSTED_DAILY_CLOSE_SOURCE_LEVELS = frozenset(
    {"official", "regulated_filing", "verified_official_mirror"}
)
TAIWAN_SESSION_CLOSE = time(13, 30)

DailyCloseResolutionStatus = Literal[
    "ready",
    "missing",
    "stale",
    "untrusted",
    "invalid",
]


@dataclass(frozen=True, slots=True)
class DailyCloseValuationInput:
    status: DailyCloseResolutionStatus
    price: Decimal | None
    price_as_of: datetime | None
    price_basis: str
    expected_trade_date: date
    trade_date: date | None
    source_id: int | None
    source_name: str | None
    source_reliability: str | None
    raw_result_id: int | None
    row_id: int | None
    issue_codes: tuple[str, ...]

    def valuation_context(self) -> dict[str, Any]:
        return {
            "price_resolution_status": self.status,
            "expected_price_trade_date": self.expected_trade_date.isoformat(),
            "price_trade_date": (
                self.trade_date.isoformat()
                if self.trade_date is not None
                else None
            ),
            "price_source": self.source_name,
            "price_source_id": self.source_id,
            "price_source_reliability": self.source_reliability,
            "price_raw_result_id": self.raw_result_id,
        }

    def source_ref(self) -> dict[str, Any] | None:
        if self.row_id is None:
            return None
        return {
            "type": "canonical_evidence",
            "name": "daily.ohlcv",
            "row_id": self.row_id,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "source_reliability": self.source_reliability,
            "raw_result_id": self.raw_result_id,
            "trade_date": (
                self.trade_date.isoformat()
                if self.trade_date is not None
                else None
            ),
            "semantics": "latest_completed_daily_close",
            "price_basis": self.price_basis,
        }


def _aware_as_of(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _unavailable(
    *,
    status: DailyCloseResolutionStatus,
    expected_trade_date: date,
    issue_code: str,
    row: TaiwanCanonicalDailyRow | None = None,
) -> DailyCloseValuationInput:
    return DailyCloseValuationInput(
        status=status,
        price=None,
        price_as_of=None,
        price_basis=DAILY_CLOSE_PRICE_BASIS,
        expected_trade_date=expected_trade_date,
        trade_date=row.trade_date if row is not None else None,
        source_id=row.source_id if row is not None else None,
        source_name=row.selected_source if row is not None else None,
        source_reliability="official" if row is not None else None,
        raw_result_id=row.raw_result_id if row is not None else None,
        row_id=row.id if row is not None else None,
        issue_codes=(issue_code,),
    )


def resolve_latest_completed_daily_close(
    db: Session,
    *,
    stock_id: str,
    as_of: datetime | None = None,
) -> DailyCloseValuationInput:
    resolved_as_of = _aware_as_of(as_of)
    expected_trade_date = expected_daily_price_date(now=resolved_as_of)
    result = read_taiwan_official_daily(
        db,
        stock_id=stock_id,
        to_date=expected_trade_date,
        limit=1,
        requested_at=resolved_as_of,
    )
    rows = project_taiwan_daily_rows(db, result)
    if not rows:
        untrusted = any(
            item.reason_code == "DAILY_SOURCE_RELIABILITY_UNTRUSTED"
            for item in result.candidate_rejections
        )
        return _unavailable(
            status="untrusted" if untrusted else "missing",
            expected_trade_date=expected_trade_date,
            issue_code=(
                "valuation_price_source_untrusted"
                if untrusted
                else "valuation_price_missing_expected_close"
            ),
        )

    row = rows[-1]
    if row.trade_date != expected_trade_date:
        return _unavailable(
            status="stale",
            expected_trade_date=expected_trade_date,
            issue_code="valuation_price_expected_close_stale",
            row=row,
        )
    try:
        price = Decimal(str(row.close_price))
    except (InvalidOperation, TypeError, ValueError):
        return _unavailable(
            status="invalid",
            expected_trade_date=expected_trade_date,
            issue_code="valuation_price_invalid",
            row=row,
        )
    if not price.is_finite() or price <= 0:
        return _unavailable(
            status="invalid",
            expected_trade_date=expected_trade_date,
            issue_code="valuation_price_invalid",
            row=row,
        )

    price_as_of = datetime.combine(
        row.trade_date,
        TAIWAN_SESSION_CLOSE,
        tzinfo=TAIWAN_TZ,
    )
    return DailyCloseValuationInput(
        status="ready",
        price=price,
        price_as_of=price_as_of,
        price_basis=DAILY_CLOSE_PRICE_BASIS,
        expected_trade_date=expected_trade_date,
        trade_date=row.trade_date,
        source_id=row.source_id,
        source_name=row.selected_source,
        source_reliability="official",
        raw_result_id=row.raw_result_id,
        row_id=row.id,
        issue_codes=(),
    )
