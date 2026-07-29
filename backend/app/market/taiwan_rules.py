from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from app.db.models import (
    BrokerBranchTradeDaily,
    FinancialMetricQuarterly,
    InstitutionalTradeDaily,
    MarginTradingDaily,
    MarketDailyPrice,
    MonthlyRevenue,
    ShareholdingDistributionWeekly,
)
from app.market.trading_calendar import (
    TAIWAN_TZ,
    latest_released_trading_day,
    previous_taiwan_trading_day,
)


TAIWAN_DAILY_PRICE_RELEASE_TIME = time(hour=15, minute=15)
TAIWAN_INSTITUTIONAL_TRADE_RELEASE_TIME = time(hour=20, minute=0)
TAIWAN_MARGIN_TRADE_RELEASE_TIME = time(hour=21, minute=0)
TAIWAN_BROKER_BRANCH_RELEASE_TIME = time(hour=16, minute=0)
TAIWAN_SHAREHOLDING_RELEASE_TIME = time(hour=12, minute=0)
TAIWAN_DEFAULT_DAILY_METRIC_RELEASE_TIME = TAIWAN_MARGIN_TRADE_RELEASE_TIME

TAIWAN_REFRESH_DAILY_PRICE = "daily_price"
TAIWAN_REFRESH_INSTITUTIONAL_TRADE = "institutional_trade"
TAIWAN_REFRESH_MARGIN_TRADING = "margin_trading"
TAIWAN_REFRESH_BROKER_BRANCH = "broker_branch"
TAIWAN_REFRESH_SHAREHOLDING_DISTRIBUTION = "shareholding_distribution"
TAIWAN_REFRESH_MONTHLY_REVENUE = "monthly_revenue"
TAIWAN_REFRESH_FINANCIAL_METRICS = "financial_metrics"

TaiwanRefreshProfile = str

TAIWAN_DAILY_METRIC_RELEASE_TIMES: dict[str, time] = {
    TAIWAN_REFRESH_DAILY_PRICE: TAIWAN_DAILY_PRICE_RELEASE_TIME,
    TAIWAN_REFRESH_INSTITUTIONAL_TRADE: TAIWAN_INSTITUTIONAL_TRADE_RELEASE_TIME,
    TAIWAN_REFRESH_MARGIN_TRADING: TAIWAN_MARGIN_TRADE_RELEASE_TIME,
    TAIWAN_REFRESH_BROKER_BRANCH: TAIWAN_BROKER_BRANCH_RELEASE_TIME,
}

TAIWAN_REFRESH_STEP_LABELS: dict[str, str] = {
    TAIWAN_REFRESH_DAILY_PRICE: "日K",
    TAIWAN_REFRESH_INSTITUTIONAL_TRADE: "法人",
    TAIWAN_REFRESH_MARGIN_TRADING: "融資融券",
    TAIWAN_REFRESH_BROKER_BRANCH: "分點",
    TAIWAN_REFRESH_SHAREHOLDING_DISTRIBUTION: "股權分散",
    TAIWAN_REFRESH_MONTHLY_REVENUE: "營收",
    TAIWAN_REFRESH_FINANCIAL_METRICS: "盈餘",
}

TAIWAN_REFRESH_PROFILE_STEPS: dict[TaiwanRefreshProfile, tuple[str, ...]] = {
    "basic": (
        TAIWAN_REFRESH_DAILY_PRICE,
        TAIWAN_REFRESH_INSTITUTIONAL_TRADE,
    ),
    "chips": (
        TAIWAN_REFRESH_INSTITUTIONAL_TRADE,
        TAIWAN_REFRESH_MARGIN_TRADING,
        TAIWAN_REFRESH_BROKER_BRANCH,
        TAIWAN_REFRESH_SHAREHOLDING_DISTRIBUTION,
    ),
    "branch": (TAIWAN_REFRESH_BROKER_BRANCH,),
    "fundamental": (
        TAIWAN_REFRESH_MONTHLY_REVENUE,
        TAIWAN_REFRESH_FINANCIAL_METRICS,
    ),
    "full": (
        TAIWAN_REFRESH_DAILY_PRICE,
        TAIWAN_REFRESH_INSTITUTIONAL_TRADE,
        TAIWAN_REFRESH_MARGIN_TRADING,
        TAIWAN_REFRESH_BROKER_BRANCH,
        TAIWAN_REFRESH_SHAREHOLDING_DISTRIBUTION,
        TAIWAN_REFRESH_MONTHLY_REVENUE,
        TAIWAN_REFRESH_FINANCIAL_METRICS,
    ),
}
TAIWAN_REFRESH_PROFILE_PATTERN = "^(" + "|".join(TAIWAN_REFRESH_PROFILE_STEPS) + ")$"


@dataclass(frozen=True)
class TaiwanDatasetSpec:
    key: str
    label: str
    frequency: str
    model: Any
    latest_column: Any
    has_expected_date: bool = False
    equity_only: bool = False
    refresh_step: str | None = None


def daily_metric_release_time(category: str) -> time:
    return TAIWAN_DAILY_METRIC_RELEASE_TIMES.get(
        category,
        TAIWAN_DEFAULT_DAILY_METRIC_RELEASE_TIME,
    )


def expected_daily_price_date(
    *,
    include_today: bool | None = None,
    now: datetime | None = None,
) -> date:
    return latest_released_trading_day(
        release_time=TAIWAN_DAILY_PRICE_RELEASE_TIME,
        include_today=include_today,
        now=now,
    )


def expected_institutional_trade_date(
    *,
    include_today: bool | None = None,
    now: datetime | None = None,
) -> date:
    return latest_released_trading_day(
        release_time=TAIWAN_INSTITUTIONAL_TRADE_RELEASE_TIME,
        include_today=include_today,
        now=now,
    )


def expected_margin_trade_date(
    *,
    include_today: bool | None = None,
    now: datetime | None = None,
) -> date:
    return latest_released_trading_day(
        release_time=TAIWAN_MARGIN_TRADE_RELEASE_TIME,
        include_today=include_today,
        now=now,
    )


def expected_broker_branch_date(
    *,
    include_today: bool | None = None,
    now: datetime | None = None,
) -> date:
    return latest_released_trading_day(
        release_time=TAIWAN_BROKER_BRANCH_RELEASE_TIME,
        include_today=include_today,
        now=now,
    )


def expected_shareholding_distribution_date(
    *,
    include_today: bool | None = None,
    now: datetime | None = None,
) -> date:
    """Return the latest TDCC observation whose release window has opened."""
    del include_today
    return shareholding_distribution_release_window(now=now)[
        "expected_trade_date"
    ]


def shareholding_distribution_release_window(
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Model the conservative weekly TDCC publication boundary.

    TDCC describes the dataset as the final-business-day balance of each week
    but does not publish an exact availability time. OMI therefore advances
    the expected observation at Saturday 12:00 Asia/Taipei and exposes the
    assumption in the returned contract.
    """
    local_now = now or datetime.now(TAIWAN_TZ)
    if local_now.tzinfo is None:
        local_now = local_now.replace(tzinfo=TAIWAN_TZ)
    else:
        local_now = local_now.astimezone(TAIWAN_TZ)
    current_date = local_now.date()
    current_week_friday = current_date + timedelta(
        days=4 - current_date.weekday()
    )
    current_observation_date = previous_taiwan_trading_day(
        current_week_friday,
        include_value=True,
    )
    release_at = datetime.combine(
        current_week_friday + timedelta(days=1),
        TAIWAN_SHAREHOLDING_RELEASE_TIME,
        tzinfo=TAIWAN_TZ,
    )
    is_released = local_now >= release_at
    if is_released:
        expected_trade_date = current_observation_date
        next_friday = current_week_friday + timedelta(days=7)
        next_release_at = datetime.combine(
            next_friday + timedelta(days=1),
            TAIWAN_SHAREHOLDING_RELEASE_TIME,
            tzinfo=TAIWAN_TZ,
        )
    else:
        previous_friday = current_week_friday - timedelta(days=7)
        expected_trade_date = previous_taiwan_trading_day(
            previous_friday,
            include_value=True,
        )
        next_release_at = release_at
    return {
        "key": TAIWAN_DATASET_SHAREHOLDING_DISTRIBUTION,
        "label": "Shareholding distribution",
        "release_time": TAIWAN_SHAREHOLDING_RELEASE_TIME.strftime("%H:%M"),
        "release_at": release_at.isoformat(),
        "next_release_at": next_release_at.isoformat(),
        "expected_trade_date": expected_trade_date,
        "status": "released" if is_released else "pending",
        "is_released": is_released,
        "assumption": "conservative_saturday_noon_asia_taipei",
    }


def expected_monthly_revenue_period(
    *,
    include_today: bool | None = None,
    now: datetime | None = None,
) -> date:
    """Return the latest revenue month whose filing deadline has passed.

    Most Taiwan public companies file by the 10th day of the following month.
    From 2026, insurers and public companies with an insurance subsidiary can
    file by the 15th.  Because this table-level check does not know the issuer's
    exemption status, use the 15th as the conservative market-wide deadline.
    ``MonthlyRevenue.period`` stores the first day of the revenue month.
    """
    del include_today
    local_now = now or datetime.now(TAIWAN_TZ)
    if local_now.tzinfo is not None:
        local_now = local_now.astimezone(TAIWAN_TZ)

    month_offset = 1 if local_now.day > 15 else 2
    year = local_now.year
    month = local_now.month - month_offset
    while month <= 0:
        year -= 1
        month += 12
    return date(year, month, 1)


def expected_financial_metrics_period(
    *,
    include_today: bool | None = None,
    now: datetime | None = None,
) -> str:
    """Return the latest fiscal quarter whose statutory deadline has ended.

    The general Taiwan public-company deadlines are three months after year
    end and 45 days after Q1/Q2/Q3.  OMI advances the expected key at 00:00 on
    the following day so the filing deadline itself remains fully available.
    """
    del include_today
    local_now = now or datetime.now(TAIWAN_TZ)
    if local_now.tzinfo is not None:
        local_now = local_now.astimezone(TAIWAN_TZ)
    current = local_now.date()
    year = current.year

    if current >= date(year, 11, 15):
        return f"{year}Q3"
    if current >= date(year, 8, 15):
        return f"{year}Q2"
    if current >= date(year, 5, 16):
        return f"{year}Q1"
    if current >= date(year, 4, 1):
        return f"{year - 1}Q4"
    return f"{year - 1}Q3"


def monthly_revenue_release_window(
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Expose the conservative market-wide MOPS revenue deadline."""
    local_now = now or datetime.now(TAIWAN_TZ)
    if local_now.tzinfo is None:
        local_now = local_now.replace(tzinfo=TAIWAN_TZ)
    else:
        local_now = local_now.astimezone(TAIWAN_TZ)
    current_date = local_now.date()
    current_boundary = datetime(
        current_date.year,
        current_date.month,
        16,
        tzinfo=TAIWAN_TZ,
    )
    if local_now >= current_boundary:
        next_month = current_date.month + 1
        next_year = current_date.year
        if next_month > 12:
            next_month = 1
            next_year += 1
        release_at = current_boundary
        next_release_at = datetime(
            next_year,
            next_month,
            16,
            tzinfo=TAIWAN_TZ,
        )
        status = "released"
    else:
        previous_month = current_date.month - 1
        previous_year = current_date.year
        if previous_month < 1:
            previous_month = 12
            previous_year -= 1
        release_at = datetime(
            previous_year,
            previous_month,
            16,
            tzinfo=TAIWAN_TZ,
        )
        next_release_at = current_boundary
        status = "pending"
    expected_period = expected_monthly_revenue_period(now=local_now)
    expected_key = expected_period.isoformat()
    return {
        "key": TAIWAN_DATASET_MONTHLY_REVENUE,
        "label": "Monthly revenue",
        "release_time": "00:00",
        "release_at": release_at.isoformat(),
        "next_release_at": next_release_at.isoformat(),
        "expected_trade_date": expected_key,
        "expected_data_key": expected_key,
        "status": status,
        "is_released": status == "released",
        "assumption": "market_wide_insurance_deadline",
    }


def financial_metrics_release_window(
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Expose the latest completed general financial filing deadline."""
    local_now = now or datetime.now(TAIWAN_TZ)
    if local_now.tzinfo is None:
        local_now = local_now.replace(tzinfo=TAIWAN_TZ)
    else:
        local_now = local_now.astimezone(TAIWAN_TZ)
    year = local_now.year
    boundaries: list[tuple[datetime, str]] = []
    for candidate_year in range(year - 1, year + 2):
        boundaries.extend(
            [
                (
                    datetime(candidate_year, 4, 1, tzinfo=TAIWAN_TZ),
                    f"{candidate_year - 1}Q4",
                ),
                (
                    datetime(candidate_year, 5, 16, tzinfo=TAIWAN_TZ),
                    f"{candidate_year}Q1",
                ),
                (
                    datetime(candidate_year, 8, 15, tzinfo=TAIWAN_TZ),
                    f"{candidate_year}Q2",
                ),
                (
                    datetime(candidate_year, 11, 15, tzinfo=TAIWAN_TZ),
                    f"{candidate_year}Q3",
                ),
            ]
        )
    boundaries.sort(key=lambda item: item[0])
    released = [item for item in boundaries if item[0] <= local_now]
    pending = [item for item in boundaries if item[0] > local_now]
    release_at, expected_key = released[-1]
    next_release_at, _ = pending[0]
    return {
        "key": TAIWAN_DATASET_FINANCIAL_METRICS,
        "label": "Quarterly financial metrics",
        "release_time": "00:00",
        "release_at": release_at.isoformat(),
        "next_release_at": next_release_at.isoformat(),
        "expected_trade_date": None,
        "expected_data_key": expected_key,
        "status": "released",
        "is_released": True,
        "assumption": "general_statutory_filing_deadline",
    }


TAIWAN_DATASET_DAILY_PRICE = "market_daily_price"
TAIWAN_DATASET_INSTITUTIONAL_TRADE = "institutional_trade_daily"
TAIWAN_DATASET_MARGIN_TRADING = "margin_trading_daily"
TAIWAN_DATASET_BROKER_BRANCH = "broker_branch_trade_daily"
TAIWAN_DATASET_SHAREHOLDING_DISTRIBUTION = "shareholding_distribution_weekly"
TAIWAN_DATASET_MONTHLY_REVENUE = "monthly_revenue"
TAIWAN_DATASET_FINANCIAL_METRICS = "financial_metric_quarterly"

TAIWAN_STOCK_MASTER_DATASET = {
    "key": "stock_master",
    "label": "Stock master",
    "frequency": "master",
}

TAIWAN_DATASET_SPECS: tuple[TaiwanDatasetSpec, ...] = (
    TaiwanDatasetSpec(
        key=TAIWAN_DATASET_DAILY_PRICE,
        label="Daily price",
        frequency="daily",
        model=MarketDailyPrice,
        latest_column=MarketDailyPrice.trade_date,
        has_expected_date=True,
        refresh_step=TAIWAN_REFRESH_DAILY_PRICE,
    ),
    TaiwanDatasetSpec(
        key=TAIWAN_DATASET_INSTITUTIONAL_TRADE,
        label="Institutional trade",
        frequency="daily",
        model=InstitutionalTradeDaily,
        latest_column=InstitutionalTradeDaily.trade_date,
        has_expected_date=True,
        refresh_step=TAIWAN_REFRESH_INSTITUTIONAL_TRADE,
    ),
    TaiwanDatasetSpec(
        key=TAIWAN_DATASET_MARGIN_TRADING,
        label="Margin trading",
        frequency="daily",
        model=MarginTradingDaily,
        latest_column=MarginTradingDaily.trade_date,
        has_expected_date=True,
        refresh_step=TAIWAN_REFRESH_MARGIN_TRADING,
    ),
    TaiwanDatasetSpec(
        key=TAIWAN_DATASET_BROKER_BRANCH,
        label="Broker branch trade",
        frequency="daily",
        model=BrokerBranchTradeDaily,
        latest_column=BrokerBranchTradeDaily.trade_date,
        has_expected_date=True,
        refresh_step=TAIWAN_REFRESH_BROKER_BRANCH,
    ),
    TaiwanDatasetSpec(
        key=TAIWAN_DATASET_SHAREHOLDING_DISTRIBUTION,
        label="Shareholding distribution",
        frequency="weekly",
        model=ShareholdingDistributionWeekly,
        latest_column=ShareholdingDistributionWeekly.data_date,
        has_expected_date=True,
        equity_only=True,
        refresh_step=TAIWAN_REFRESH_SHAREHOLDING_DISTRIBUTION,
    ),
    TaiwanDatasetSpec(
        key=TAIWAN_DATASET_MONTHLY_REVENUE,
        label="Monthly revenue",
        frequency="monthly",
        model=MonthlyRevenue,
        latest_column=MonthlyRevenue.period,
        has_expected_date=True,
        equity_only=True,
        refresh_step=TAIWAN_REFRESH_MONTHLY_REVENUE,
    ),
    TaiwanDatasetSpec(
        key=TAIWAN_DATASET_FINANCIAL_METRICS,
        label="Quarterly financial metrics",
        frequency="quarterly",
        model=FinancialMetricQuarterly,
        latest_column=FinancialMetricQuarterly.period,
        equity_only=True,
        refresh_step=TAIWAN_REFRESH_FINANCIAL_METRICS,
    ),
)

TAIWAN_DATASET_BY_KEY = {spec.key: spec for spec in TAIWAN_DATASET_SPECS}
TAIWAN_DATASET_LABELS = {
    TAIWAN_STOCK_MASTER_DATASET["key"]: TAIWAN_STOCK_MASTER_DATASET["label"],
    **{spec.key: spec.label for spec in TAIWAN_DATASET_SPECS},
}
TAIWAN_DATASET_FREQUENCIES = {
    TAIWAN_STOCK_MASTER_DATASET["key"]: TAIWAN_STOCK_MASTER_DATASET["frequency"],
    **{spec.key: spec.frequency for spec in TAIWAN_DATASET_SPECS},
}

_EXPECTED_DATE_BY_DATASET: dict[
    str,
    Callable[[bool | None, datetime | None], date],
] = {
    TAIWAN_DATASET_DAILY_PRICE: lambda include_today, now: expected_daily_price_date(
        include_today=include_today,
        now=now,
    ),
    TAIWAN_DATASET_INSTITUTIONAL_TRADE: (
        lambda include_today, now: expected_institutional_trade_date(
            include_today=include_today,
            now=now,
        )
    ),
    TAIWAN_DATASET_MARGIN_TRADING: lambda include_today, now: expected_margin_trade_date(
        include_today=include_today,
        now=now,
    ),
    TAIWAN_DATASET_BROKER_BRANCH: lambda include_today, now: expected_broker_branch_date(
        include_today=include_today,
        now=now,
    ),
    TAIWAN_DATASET_SHAREHOLDING_DISTRIBUTION: (
        lambda include_today, now: expected_shareholding_distribution_date(
            include_today=include_today,
            now=now,
        )
    ),
    TAIWAN_DATASET_MONTHLY_REVENUE: (
        lambda include_today, now: expected_monthly_revenue_period(
            include_today=include_today,
            now=now,
        )
    ),
}


def expected_date_for_dataset(
    key: str,
    *,
    include_today: bool | None = None,
    now: datetime | None = None,
) -> date | None:
    expected_date = _EXPECTED_DATE_BY_DATASET.get(key)

    if expected_date is None:
        return None

    return expected_date(include_today, now)


def normalize_refresh_profile(profile: str | None) -> TaiwanRefreshProfile:
    normalized = (profile or "full").strip().lower()

    if normalized not in TAIWAN_REFRESH_PROFILE_STEPS:
        available = ", ".join(TAIWAN_REFRESH_PROFILE_STEPS)
        raise ValueError(f"profile must be one of: {available}.")

    return normalized


def refresh_profile_steps(profile: str | None) -> tuple[str, ...]:
    return TAIWAN_REFRESH_PROFILE_STEPS[normalize_refresh_profile(profile)]


def refresh_profile_step_count(profile: str | None) -> int:
    return len(refresh_profile_steps(profile))


def is_equity_only_dataset_required(
    spec: TaiwanDatasetSpec,
    stock: Any | None,
) -> bool:
    if not spec.equity_only:
        return True

    if stock is None:
        return True

    instrument_type = (getattr(stock, "instrument_type", None) or "").strip().lower()
    return instrument_type not in {"etf", "warrant"}


__all__ = [
    "TAIWAN_BROKER_BRANCH_RELEASE_TIME",
    "TAIWAN_DAILY_METRIC_RELEASE_TIMES",
    "TAIWAN_DAILY_PRICE_RELEASE_TIME",
    "TAIWAN_DATASET_BY_KEY",
    "TAIWAN_DATASET_BROKER_BRANCH",
    "TAIWAN_DATASET_DAILY_PRICE",
    "TAIWAN_DATASET_FINANCIAL_METRICS",
    "TAIWAN_DATASET_FREQUENCIES",
    "TAIWAN_DATASET_INSTITUTIONAL_TRADE",
    "TAIWAN_DATASET_LABELS",
    "TAIWAN_DATASET_MARGIN_TRADING",
    "TAIWAN_DATASET_MONTHLY_REVENUE",
    "TAIWAN_DATASET_SHAREHOLDING_DISTRIBUTION",
    "TAIWAN_DATASET_SPECS",
    "TAIWAN_DEFAULT_DAILY_METRIC_RELEASE_TIME",
    "TAIWAN_INSTITUTIONAL_TRADE_RELEASE_TIME",
    "TAIWAN_MARGIN_TRADE_RELEASE_TIME",
    "TAIWAN_SHAREHOLDING_RELEASE_TIME",
    "TAIWAN_REFRESH_BROKER_BRANCH",
    "TAIWAN_REFRESH_DAILY_PRICE",
    "TAIWAN_REFRESH_FINANCIAL_METRICS",
    "TAIWAN_REFRESH_INSTITUTIONAL_TRADE",
    "TAIWAN_REFRESH_MARGIN_TRADING",
    "TAIWAN_REFRESH_MONTHLY_REVENUE",
    "TAIWAN_REFRESH_PROFILE_PATTERN",
    "TAIWAN_REFRESH_PROFILE_STEPS",
    "TAIWAN_REFRESH_SHAREHOLDING_DISTRIBUTION",
    "TAIWAN_REFRESH_STEP_LABELS",
    "TAIWAN_STOCK_MASTER_DATASET",
    "TaiwanDatasetSpec",
    "TaiwanRefreshProfile",
    "daily_metric_release_time",
    "expected_broker_branch_date",
    "expected_daily_price_date",
    "expected_date_for_dataset",
    "expected_institutional_trade_date",
    "expected_margin_trade_date",
    "expected_financial_metrics_period",
    "expected_monthly_revenue_period",
    "expected_shareholding_distribution_date",
    "is_equity_only_dataset_required",
    "normalize_refresh_profile",
    "refresh_profile_step_count",
    "refresh_profile_steps",
    "financial_metrics_release_window",
    "monthly_revenue_release_window",
    "shareholding_distribution_release_window",
]
