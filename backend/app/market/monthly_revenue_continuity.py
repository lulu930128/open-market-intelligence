from __future__ import annotations

from datetime import date
from typing import Any, Sequence


def _value(source: Any, key: str) -> Any:
    if isinstance(source, dict):
        return source.get(key)
    return getattr(source, key, None)


def _month_start(value: Any) -> date | None:
    if isinstance(value, date):
        return value.replace(day=1)
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10]).replace(day=1)
        except ValueError:
            return None
    return None


def _next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _month_range(start: date, end: date) -> list[date]:
    values = []
    current = start
    while current <= end:
        values.append(current)
        current = _next_month(current)
    return values


def analyze_monthly_revenue_continuity(
    rows: Sequence[Any],
    *,
    expected_from: date | None = None,
    expected_to: date | None = None,
) -> dict[str, Any]:
    parsed_periods = [
        period
        for row in rows
        if (period := _month_start(_value(row, "period"))) is not None
    ]
    invalid_period_count = len(rows) - len(parsed_periods)
    period_counts: dict[date, int] = {}
    for period in parsed_periods:
        period_counts[period] = period_counts.get(period, 0) + 1
    unique_periods = sorted(period_counts)
    duplicate_periods = [
        period.isoformat()
        for period, count in sorted(period_counts.items())
        if count > 1
    ]

    issues: list[str] = []
    if invalid_period_count:
        issues.append("monthly_revenue_period_invalid")
    if duplicate_periods:
        issues.append("monthly_revenue_duplicate_period")
    if not unique_periods:
        return {
            "status": "missing",
            "observed_from": None,
            "observed_to": None,
            "expected_from": expected_from.isoformat() if expected_from else None,
            "expected_to": expected_to.isoformat() if expected_to else None,
            "missing_periods": [],
            "duplicate_periods": duplicate_periods,
            "invalid_period_count": invalid_period_count,
            "decision_usable": False,
            "issues": issues + ["monthly_revenue_missing"],
        }

    observed_from = unique_periods[0]
    observed_to = unique_periods[-1]
    range_from = (expected_from or observed_from).replace(day=1)
    range_to = (expected_to or observed_to).replace(day=1)
    observed_set = set(unique_periods)
    missing = [
        period
        for period in _month_range(range_from, range_to)
        if period not in observed_set
    ]
    missing_periods = [period.isoformat()[:7] for period in missing]

    has_leading_gap = any(period < observed_from for period in missing)
    has_trailing_gap = any(period > observed_to for period in missing)
    has_interior_gap = any(observed_from < period < observed_to for period in missing)
    if has_interior_gap:
        status = "interior_gap"
    elif has_leading_gap and has_trailing_gap:
        status = "leading_and_trailing_gap"
    elif has_leading_gap:
        status = "leading_gap"
    elif has_trailing_gap:
        status = "trailing_gap"
    else:
        status = "complete"

    for period in missing_periods:
        issues.append(f"monthly_revenue_missing_{period.replace('-', '_')}")
    decision_usable = (
        status == "complete"
        and not duplicate_periods
        and invalid_period_count == 0
    )
    return {
        "status": status,
        "observed_from": observed_from.isoformat()[:7],
        "observed_to": observed_to.isoformat()[:7],
        "expected_from": range_from.isoformat()[:7],
        "expected_to": range_to.isoformat()[:7],
        "missing_periods": missing_periods,
        "duplicate_periods": duplicate_periods,
        "invalid_period_count": invalid_period_count,
        "decision_usable": decision_usable,
        "issues": list(dict.fromkeys(issues)),
    }
