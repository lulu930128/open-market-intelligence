from __future__ import annotations

import re

from app.us_market.sec_fundamentals.contracts import (
    PeriodResolution,
    SecFact,
    UnitResolution,
)


_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")
_PER_SHARE_PATTERN = re.compile(r"^([A-Z]{3})/shares$")
_FISCAL_QUARTERS = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4, "FY": 4}


def _duration_bucket(duration_days: int) -> str:
    if 70 <= duration_days <= 120:
        return "3m"
    if 150 <= duration_days <= 220:
        return "6m"
    if 240 <= duration_days <= 310:
        return "9m"
    if 330 <= duration_days <= 400:
        return "12m"
    return "ambiguous"


def resolve_period(fact: SecFact, *, statement_kind: str) -> PeriodResolution:
    fiscal_period = (fact.fiscal_period or "").upper()
    fiscal_quarter = _FISCAL_QUARTERS.get(fiscal_period)
    issues: list[str] = []

    if statement_kind == "instant":
        if fact.period_end_date is None:
            return PeriodResolution(
                statement_kind="instant",
                scope="ambiguous",
                fiscal_year=fact.fiscal_year,
                fiscal_quarter=fiscal_quarter,
                period_start=fact.period_start_date,
                period_end=None,
                duration_days=None,
                status="blocked",
                issue_codes=("missing_period_end",),
            )
        if fact.period_start_date is not None:
            issues.append("instant_fact_has_start_date")
        if not fiscal_period:
            issues.append("missing_fiscal_period")
        return PeriodResolution(
            statement_kind="instant",
            scope="instant",
            fiscal_year=fact.fiscal_year,
            fiscal_quarter=fiscal_quarter,
            period_start=fact.period_start_date,
            period_end=fact.period_end_date,
            duration_days=None,
            status="partial" if issues else "ready",
            issue_codes=tuple(issues),
        )

    if statement_kind != "duration":
        raise ValueError(f"Unsupported statement kind: {statement_kind}")

    if fact.period_start_date is None or fact.period_end_date is None:
        missing = (
            "missing_period_start"
            if fact.period_start_date is None
            else "missing_period_end"
        )
        return PeriodResolution(
            statement_kind="duration",
            scope="ambiguous",
            fiscal_year=fact.fiscal_year,
            fiscal_quarter=fiscal_quarter,
            period_start=fact.period_start_date,
            period_end=fact.period_end_date,
            duration_days=None,
            status="blocked",
            issue_codes=(missing,),
        )

    duration_days = (fact.period_end_date - fact.period_start_date).days + 1
    if duration_days <= 0:
        return PeriodResolution(
            statement_kind="duration",
            scope="ambiguous",
            fiscal_year=fact.fiscal_year,
            fiscal_quarter=fiscal_quarter,
            period_start=fact.period_start_date,
            period_end=fact.period_end_date,
            duration_days=duration_days,
            status="blocked",
            issue_codes=("invalid_period_range",),
        )

    bucket = _duration_bucket(duration_days)
    if bucket == "ambiguous":
        return PeriodResolution(
            statement_kind="duration",
            scope="ambiguous",
            fiscal_year=fact.fiscal_year,
            fiscal_quarter=fiscal_quarter,
            period_start=fact.period_start_date,
            period_end=fact.period_end_date,
            duration_days=duration_days,
            status="blocked",
            issue_codes=("ambiguous_duration",),
        )

    if bucket == "3m":
        scope = "ytd_3m" if fiscal_period == "Q1" else "discrete_3m"
    elif bucket == "6m":
        scope = "ytd_6m"
    elif bucket == "9m":
        scope = "ytd_9m"
    else:
        scope = "annual_12m"

    expected_buckets = {
        "Q1": frozenset({"3m"}),
        "Q2": frozenset({"3m", "6m"}),
        "Q3": frozenset({"3m", "9m"}),
        "Q4": frozenset({"3m"}),
        "FY": frozenset({"3m", "12m"}),
    }
    blocked_by_metadata = False
    if not fiscal_period:
        issues.append("missing_fiscal_period")
    elif fiscal_period not in expected_buckets:
        issues.append("unsupported_fiscal_period")
        blocked_by_metadata = True
    elif bucket not in expected_buckets[fiscal_period]:
        issues.append("fiscal_period_duration_mismatch")
        blocked_by_metadata = True

    if fiscal_period == "FY" and bucket == "3m":
        issues.append("q4_direct_from_annual_filing")

    return PeriodResolution(
        statement_kind="duration",
        scope=scope,
        fiscal_year=fact.fiscal_year,
        fiscal_quarter=fiscal_quarter,
        period_start=fact.period_start_date,
        period_end=fact.period_end_date,
        duration_days=duration_days,
        status="blocked" if blocked_by_metadata else ("partial" if issues else "ready"),
        issue_codes=tuple(issues),
    )


def resolve_unit(raw_unit: str) -> UnitResolution:
    unit = raw_unit.strip()
    if _CURRENCY_PATTERN.fullmatch(unit):
        return UnitResolution(
            raw_unit=raw_unit,
            kind="money",
            normalized_unit=unit,
            currency=unit,
            status="ready",
            issue_codes=(),
        )

    per_share_match = _PER_SHARE_PATTERN.fullmatch(unit)
    if per_share_match:
        currency = per_share_match.group(1)
        return UnitResolution(
            raw_unit=raw_unit,
            kind="per_share",
            normalized_unit=f"{currency}/shares",
            currency=currency,
            status="ready",
            issue_codes=(),
        )

    if unit == "shares":
        return UnitResolution(
            raw_unit=raw_unit,
            kind="shares",
            normalized_unit="shares",
            currency=None,
            status="ready",
            issue_codes=(),
        )

    if unit == "pure":
        return UnitResolution(
            raw_unit=raw_unit,
            kind="pure",
            normalized_unit="pure",
            currency=None,
            status="ready",
            issue_codes=(),
        )

    return UnitResolution(
        raw_unit=raw_unit,
        kind="unsupported",
        normalized_unit=None,
        currency=None,
        status="blocked",
        issue_codes=("unsupported_unit",),
    )
