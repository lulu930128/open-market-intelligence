from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time
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
from app.market.trading_calendar import latest_released_trading_day


TAIWAN_DAILY_PRICE_RELEASE_TIME = time(hour=15, minute=15)
TAIWAN_INSTITUTIONAL_TRADE_RELEASE_TIME = time(hour=18, minute=10)
TAIWAN_MARGIN_TRADE_RELEASE_TIME = time(hour=21, minute=10)
TAIWAN_BROKER_BRANCH_RELEASE_TIME = time(hour=15, minute=15)
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
        equity_only=True,
        refresh_step=TAIWAN_REFRESH_SHAREHOLDING_DISTRIBUTION,
    ),
    TaiwanDatasetSpec(
        key=TAIWAN_DATASET_MONTHLY_REVENUE,
        label="Monthly revenue",
        frequency="monthly",
        model=MonthlyRevenue,
        latest_column=MonthlyRevenue.period,
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
    "is_equity_only_dataset_required",
    "normalize_refresh_profile",
    "refresh_profile_step_count",
    "refresh_profile_steps",
]
