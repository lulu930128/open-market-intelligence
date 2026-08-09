from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any


@dataclass(frozen=True, slots=True)
class TaiwanEtfValuationMetric:
    value: Decimal | None
    as_of_date: date | None
    observed_at: datetime | None
    fetched_at: datetime | None
    source: str | None
    source_url: str | None
    basis: str
    status: str
    issue_codes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "as_of_date": self.as_of_date,
            "observed_at": self.observed_at,
            "fetched_at": self.fetched_at,
            "source": self.source,
            "source_url": self.source_url,
            "basis": self.basis,
            "status": self.status,
            "issue_codes": list(self.issue_codes),
        }


def valuation_metric(
    *,
    value: Decimal | float | int | str | None,
    as_of_date: date | None,
    observed_at: datetime | None,
    fetched_at: datetime | None,
    source: str | None,
    source_url: str | None,
    basis: str,
    status: str,
    issue_codes: tuple[str, ...] = (),
) -> TaiwanEtfValuationMetric:
    normalized_value: Decimal | None
    try:
        normalized_value = Decimal(str(value)) if value is not None else None
    except (InvalidOperation, TypeError, ValueError):
        normalized_value = None
    if normalized_value is not None and (
        not normalized_value.is_finite() or normalized_value <= 0
    ):
        normalized_value = None
    if value is not None and normalized_value is None:
        status = "invalid"
        issue_codes = tuple(dict.fromkeys((*issue_codes, f"{basis}_invalid")))
    return TaiwanEtfValuationMetric(
        value=normalized_value,
        as_of_date=as_of_date,
        observed_at=observed_at,
        fetched_at=fetched_at,
        source=source,
        source_url=source_url,
        basis=basis,
        status=status,
        issue_codes=issue_codes,
    )


def missing_valuation_metric(
    *,
    basis: str,
    status: str = "missing",
    issue_codes: tuple[str, ...] = (),
) -> TaiwanEtfValuationMetric:
    return TaiwanEtfValuationMetric(
        value=None,
        as_of_date=None,
        observed_at=None,
        fetched_at=None,
        source=None,
        source_url=None,
        basis=basis,
        status=status,
        issue_codes=issue_codes,
    )


def _premium_discount_pct(
    market_price: Decimal,
    nav: Decimal,
) -> Decimal:
    return ((market_price / nav) - Decimal("1")) * Decimal("100")


def _unique_issue_codes(
    *groups: tuple[str, ...],
) -> list[str]:
    return list(dict.fromkeys(code for group in groups for code in group))


def compose_taiwan_etf_valuation(
    *,
    expected_nav_date: date,
    session_phase: str,
    inav_status: str,
    daily_market_price: TaiwanEtfValuationMetric,
    daily_nav: TaiwanEtfValuationMetric,
    intraday_market_price: TaiwanEtfValuationMetric,
    intraday_nav: TaiwanEtfValuationMetric,
) -> dict[str, Any]:
    use_intraday = (
        session_phase in {"regular", "closing_auction"}
        and inav_status in {"current", "delayed"}
        and (
            intraday_market_price.value is not None
            or intraday_nav.value is not None
        )
    )
    basis = "intraday" if use_intraday else "daily_close"
    market_price = intraday_market_price if use_intraday else daily_market_price
    nav = intraday_nav if use_intraday else daily_nav

    issue_codes = _unique_issue_codes(
        market_price.issue_codes,
        nav.issue_codes,
    )
    aligned = bool(
        market_price.value is not None
        and nav.value is not None
        and market_price.as_of_date is not None
        and market_price.as_of_date == nav.as_of_date
    )
    if market_price.value is None or nav.value is None:
        premium_discount_pct = None
        premium_discount_status = "input_missing"
        status = (
            "missing"
            if market_price.value is None and nav.value is None
            else "partial"
        )
    elif not aligned:
        premium_discount_pct = None
        premium_discount_status = "date_mismatch"
        status = "partial"
        issue_codes = list(
            dict.fromkeys((*issue_codes, "valuation_price_nav_date_mismatch"))
        )
    else:
        premium_discount_pct = _premium_discount_pct(
            market_price.value,
            nav.value,
        )
        premium_discount_status = "ready"
        if use_intraday:
            status = inav_status
        elif market_price.as_of_date == expected_nav_date:
            status = "current"
        else:
            status = "stale"

    return {
        "status": status,
        "basis": basis,
        "market_price": market_price.to_dict(),
        "nav": nav.to_dict(),
        "premium_discount_pct": premium_discount_pct,
        "premium_discount_status": premium_discount_status,
        "aligned": aligned,
        "issue_codes": issue_codes,
    }


__all__ = [
    "TaiwanEtfValuationMetric",
    "compose_taiwan_etf_valuation",
    "missing_valuation_metric",
    "valuation_metric",
]
