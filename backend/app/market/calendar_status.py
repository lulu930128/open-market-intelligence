from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo

from app.market.market_chips import (
    MARKET_CHIP_RELEASE_TIME,
    MARKET_MARGIN_RELEASE_TIME,
    expected_market_chip_date,
    expected_market_margin_chip_date,
)
from app.market.taiwan_rules import (
    TAIWAN_BROKER_BRANCH_RELEASE_TIME,
    TAIWAN_DAILY_PRICE_RELEASE_TIME,
    TAIWAN_DATASET_BROKER_BRANCH,
    TAIWAN_DATASET_DAILY_PRICE,
    TAIWAN_DATASET_INSTITUTIONAL_TRADE,
    TAIWAN_DATASET_LABELS,
    TAIWAN_DATASET_MARGIN_TRADING,
    TAIWAN_DATASET_MONTHLY_REVENUE,
    TAIWAN_DATASET_FINANCIAL_METRICS,
    TAIWAN_DATASET_SHAREHOLDING_DISTRIBUTION,
    TAIWAN_INSTITUTIONAL_TRADE_RELEASE_TIME,
    TAIWAN_MARGIN_TRADE_RELEASE_TIME,
    expected_date_for_dataset,
    financial_metrics_release_window,
    monthly_revenue_release_window,
    shareholding_distribution_release_window,
)
from app.market.trading_calendar import (
    TAIWAN_MARKET_HOLIDAYS,
    TAIWAN_TZ,
    is_taiwan_trading_day,
    next_taiwan_trading_day,
    previous_taiwan_trading_day,
    taiwan_market_holiday_name,
)
from app.market.exchange_calendar_cache import market_calendar_cache_metadata
from app.us_market.trading_calendar import (
    US_DAILY_PRICE_RELEASE_TIME,
    US_MARKET_TIMEZONE,
    US_POST_MARKET_CLOSE_TIME,
    US_PRE_MARKET_OPEN_TIME,
    US_SESSION_CLOSE_TIME,
    US_SESSION_OPEN_TIME,
    expected_us_daily_price_date,
    is_us_trading_day,
    next_us_trading_day,
    previous_us_trading_day,
    us_market_holiday_name,
)
from app.kr_market.trading_calendar import (
    KR_DAILY_PRICE_RELEASE_TIME,
    KR_MARKET_TIMEZONE,
    expected_kr_daily_price_date,
    is_kr_trading_day,
    kr_market_holiday_name,
    next_kr_trading_day,
    previous_kr_trading_day,
)
from app.jp_market.trading_calendar import (
    JPX_CALENDAR_SOURCE,
    JPX_VERIFIED_CALENDAR_YEARS,
    JP_DAILY_PRICE_RELEASE_TIME,
    JP_LUNCH_END_TIME,
    JP_LUNCH_START_TIME,
    JP_MARKET_TIMEZONE,
    JP_SESSION_CLOSE_TIME,
    JP_SESSION_OPEN_TIME,
    expected_jp_daily_price_date,
    is_jp_trading_day,
    jp_calendar_limit,
    jp_market_holiday_name,
    next_jp_trading_day,
    previous_jp_trading_day,
)


MarketCode = Literal["tw", "us", "jp", "kr"]

TAIWAN_PREOPEN_TIME = time(hour=8, minute=30)
TAIWAN_SESSION_OPEN_TIME = time(hour=9, minute=0)
TAIWAN_CLOSING_AUCTION_TIME = time(hour=13, minute=25)
TAIWAN_SESSION_CLOSE_TIME = time(hour=13, minute=30)
KR_SESSION_OPEN_TIME = time(hour=9, minute=0)
KR_SESSION_CLOSE_TIME = time(hour=15, minute=30)
TAIWAN_RELEASE_DATASETS = (
    (TAIWAN_DATASET_DAILY_PRICE, TAIWAN_DAILY_PRICE_RELEASE_TIME),
    (TAIWAN_DATASET_INSTITUTIONAL_TRADE, TAIWAN_INSTITUTIONAL_TRADE_RELEASE_TIME),
    (TAIWAN_DATASET_MARGIN_TRADING, TAIWAN_MARGIN_TRADE_RELEASE_TIME),
    (TAIWAN_DATASET_BROKER_BRANCH, TAIWAN_BROKER_BRANCH_RELEASE_TIME),
)

TAIWAN_CALENDAR_FALLBACK_SOURCE = "TWSE verified holiday snapshot with weekday fallback"
US_CALENDAR_FALLBACK_SOURCE = "NYSE holiday rules with weekday fallback"
KR_CALENDAR_FALLBACK_SOURCE = "KRX fixed-holiday rules with weekday fallback"


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _parse_date_value(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None

    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _as_market_datetime(value: datetime | None, timezone_value: ZoneInfo) -> datetime:
    if value is None:
        return datetime.now(timezone_value)

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone_value)


def _local_datetime(day: date, value: time, timezone_value: ZoneInfo) -> datetime:
    return datetime.combine(day, value, tzinfo=timezone_value)


def _market_reason(
    *,
    value: date,
    is_trading_day: bool,
    holiday_name: str | None,
) -> str:
    if is_trading_day:
        return "trading_day"
    if holiday_name:
        return "holiday"
    return "weekend"


def _calendar_contract(
    *,
    market: MarketCode,
    year: int,
    now: datetime,
    fallback_source: str,
    fallback_verified_years: set[int] | frozenset[int],
    fallback_limit: str | None,
) -> dict[str, Any]:
    metadata = market_calendar_cache_metadata(market, year=year, now=now)
    cached_years = set(metadata.pop("cached_verified_years", []))
    cached_source = metadata.pop("cached_calendar_source", None)
    uses_cached_year = year in cached_years
    return {
        "calendar_source": cached_source if uses_cached_year else fallback_source,
        "calendar_verified_years": sorted(
            set(fallback_verified_years) | cached_years
        ),
        "calendar_limit": None if uses_cached_year else fallback_limit,
        **metadata,
    }


def _session_phase(
    *,
    local_now: datetime,
    is_trading_day: bool,
    preopen_time: time,
    open_time: time,
    close_time: time,
    closing_auction_time: time | None = None,
) -> str:
    if not is_trading_day:
        return "market_closed"

    current_time = local_now.time()
    if current_time < preopen_time:
        return "preopen_pending"
    if current_time < open_time:
        return "preopen"
    if (
        closing_auction_time is not None
        and closing_auction_time <= current_time < close_time
    ):
        return "closing_auction"
    if current_time < close_time:
        return "regular"
    return "post_close"


def _us_session_phase(
    *,
    local_now: datetime,
    is_trading_day: bool,
) -> str:
    if not is_trading_day:
        return "market_closed"

    current_time = local_now.time()
    if current_time < US_PRE_MARKET_OPEN_TIME:
        return "pre_market_pending"
    if current_time < US_SESSION_OPEN_TIME:
        return "pre_market"
    if current_time < US_SESSION_CLOSE_TIME:
        return "regular"
    if current_time < US_POST_MARKET_CLOSE_TIME:
        return "after_hours"
    return "post_close"


def _jp_session_phase(
    *,
    local_now: datetime,
    is_trading_day: bool,
) -> str:
    if not is_trading_day:
        return "market_closed"

    current_time = local_now.time()
    if current_time < JP_SESSION_OPEN_TIME:
        return "pre_market_pending"
    if current_time < JP_LUNCH_START_TIME:
        return "regular"
    if current_time < JP_LUNCH_END_TIME:
        return "lunch_break"
    if current_time < JP_SESSION_CLOSE_TIME:
        return "regular"
    return "post_close"


def _next_session_start_at(
    *,
    current_date: date,
    local_now: datetime,
    is_trading_day: bool,
    preopen_time: time,
    next_trading_day: date,
    timezone_value: ZoneInfo,
) -> datetime:
    today_preopen = _local_datetime(current_date, preopen_time, timezone_value)
    if is_trading_day and local_now < today_preopen:
        return today_preopen

    return _local_datetime(next_trading_day, preopen_time, timezone_value)


def _release_status(
    *,
    local_now: datetime,
    current_date: date,
    is_trading_day: bool,
    release_time: time,
) -> str:
    release_at = _local_datetime(current_date, release_time, local_now.tzinfo)  # type: ignore[arg-type]
    if not is_trading_day:
        return "market_closed"
    if local_now < release_at:
        return "pending"
    return "released"


def _release_window(
    *,
    key: str,
    label: str,
    release_time: time,
    expected_trade_date: date | None,
    local_now: datetime,
    current_date: date,
    is_trading_day: bool,
    next_trading_day: date,
    timezone_value: ZoneInfo,
) -> dict[str, Any]:
    release_at = _local_datetime(current_date, release_time, timezone_value)
    next_release_date = current_date if is_trading_day and local_now < release_at else next_trading_day
    next_release_at = _local_datetime(next_release_date, release_time, timezone_value)
    status = _release_status(
        local_now=local_now,
        current_date=current_date,
        is_trading_day=is_trading_day,
        release_time=release_time,
    )

    return {
        "key": key,
        "label": label,
        "release_time": release_time.strftime("%H:%M"),
        "release_at": release_at.isoformat(),
        "next_release_at": next_release_at.isoformat(),
        "expected_trade_date": _json_value(expected_trade_date),
        "status": status,
        "is_released": status == "released",
    }


def build_taiwan_calendar_status(now: datetime | None = None) -> dict[str, Any]:
    local_now = _as_market_datetime(now, TAIWAN_TZ)
    current_date = local_now.date()
    holiday_name = taiwan_market_holiday_name(current_date)
    is_trading_day = is_taiwan_trading_day(current_date)
    previous_trading_day = previous_taiwan_trading_day(
        current_date,
        include_value=is_trading_day,
    )
    next_trading_day = next_taiwan_trading_day(current_date, include_value=False)
    phase = _session_phase(
        local_now=local_now,
        is_trading_day=is_trading_day,
        preopen_time=TAIWAN_PREOPEN_TIME,
        open_time=TAIWAN_SESSION_OPEN_TIME,
        close_time=TAIWAN_SESSION_CLOSE_TIME,
        closing_auction_time=TAIWAN_CLOSING_AUCTION_TIME,
    )

    release_windows = {
        key: _release_window(
            key=key,
            label=TAIWAN_DATASET_LABELS.get(key, key),
            release_time=release_time,
            expected_trade_date=expected_date_for_dataset(key, now=local_now),
            local_now=local_now,
            current_date=current_date,
            is_trading_day=is_trading_day,
            next_trading_day=next_trading_day,
            timezone_value=TAIWAN_TZ,
        )
        for key, release_time in TAIWAN_RELEASE_DATASETS
    }
    release_windows[TAIWAN_DATASET_SHAREHOLDING_DISTRIBUTION] = {
        **shareholding_distribution_release_window(now=local_now),
        "expected_trade_date": expected_date_for_dataset(
            TAIWAN_DATASET_SHAREHOLDING_DISTRIBUTION,
            now=local_now,
        ).isoformat(),
    }
    release_windows[TAIWAN_DATASET_MONTHLY_REVENUE] = (
        monthly_revenue_release_window(now=local_now)
    )
    release_windows[TAIWAN_DATASET_FINANCIAL_METRICS] = (
        financial_metrics_release_window(now=local_now)
    )
    release_windows["market_chip_daily"] = _release_window(
        key="market_chip_daily",
        label="Market chip daily",
        release_time=MARKET_CHIP_RELEASE_TIME,
        expected_trade_date=expected_market_chip_date(now=local_now),
        local_now=local_now,
        current_date=current_date,
        is_trading_day=is_trading_day,
        next_trading_day=next_trading_day,
        timezone_value=TAIWAN_TZ,
    )
    release_windows["market_chip_margin_daily"] = _release_window(
        key="market_chip_margin_daily",
        label="Market chip margin daily",
        release_time=MARKET_MARGIN_RELEASE_TIME,
        expected_trade_date=expected_market_margin_chip_date(now=local_now),
        local_now=local_now,
        current_date=current_date,
        is_trading_day=is_trading_day,
        next_trading_day=next_trading_day,
        timezone_value=TAIWAN_TZ,
    )

    next_session_start_at = _next_session_start_at(
        current_date=current_date,
        local_now=local_now,
        is_trading_day=is_trading_day,
        preopen_time=TAIWAN_PREOPEN_TIME,
        next_trading_day=next_trading_day,
        timezone_value=TAIWAN_TZ,
    )

    return {
        "market": "tw",
        "timezone": str(TAIWAN_TZ),
        "checked_at": local_now.isoformat(),
        "date": current_date.isoformat(),
        "is_trading_day": is_trading_day,
        "phase": phase,
        "reason": _market_reason(
            value=current_date,
            is_trading_day=is_trading_day,
            holiday_name=holiday_name,
        ),
        "holiday_name": holiday_name,
        "previous_trading_day": previous_trading_day.isoformat(),
        "next_trading_day": next_trading_day.isoformat(),
        "session": {
            "preopen_time": TAIWAN_PREOPEN_TIME.strftime("%H:%M"),
            "open_time": TAIWAN_SESSION_OPEN_TIME.strftime("%H:%M"),
            "close_time": TAIWAN_SESSION_CLOSE_TIME.strftime("%H:%M"),
            "next_session_start_at": next_session_start_at.isoformat(),
            "is_polling_window": phase in {
                "preopen",
                "regular",
                "closing_auction",
            },
            "is_after_close": phase == "post_close",
        },
        "release_windows": release_windows,
        **_calendar_contract(
            market="tw",
            year=current_date.year,
            now=local_now,
            fallback_source=TAIWAN_CALENDAR_FALLBACK_SOURCE,
            fallback_verified_years=set(TAIWAN_MARKET_HOLIDAYS),
            fallback_limit=(
                None
                if current_date.year in TAIWAN_MARKET_HOLIDAYS
                else "TWSE fallback snapshot does not cover this year; weekdays are treated as trading days until the official cache refresh succeeds."
            ),
        ),
    }


def build_us_calendar_status(now: datetime | None = None) -> dict[str, Any]:
    local_now = _as_market_datetime(now, US_MARKET_TIMEZONE)
    current_date = local_now.date()
    holiday_name = us_market_holiday_name(current_date)
    is_trading_day = is_us_trading_day(current_date)
    previous_trading_day = previous_us_trading_day(
        current_date,
        include_value=is_trading_day,
    )
    next_trading_day = next_us_trading_day(current_date, include_value=False)
    phase = _us_session_phase(
        local_now=local_now,
        is_trading_day=is_trading_day,
    )
    release_windows = {
        "us_daily_price": _release_window(
            key="us_daily_price",
            label="US daily price",
            release_time=US_DAILY_PRICE_RELEASE_TIME,
            expected_trade_date=expected_us_daily_price_date(now=local_now),
            local_now=local_now,
            current_date=current_date,
            is_trading_day=is_trading_day,
            next_trading_day=next_trading_day,
            timezone_value=US_MARKET_TIMEZONE,
        )
    }
    next_session_start_at = _next_session_start_at(
        current_date=current_date,
        local_now=local_now,
        is_trading_day=is_trading_day,
        preopen_time=US_PRE_MARKET_OPEN_TIME,
        next_trading_day=next_trading_day,
        timezone_value=US_MARKET_TIMEZONE,
    )

    return {
        "market": "us",
        "timezone": str(US_MARKET_TIMEZONE),
        "checked_at": local_now.isoformat(),
        "date": current_date.isoformat(),
        "is_trading_day": is_trading_day,
        "phase": phase,
        "reason": _market_reason(
            value=current_date,
            is_trading_day=is_trading_day,
            holiday_name=holiday_name,
        ),
        "holiday_name": holiday_name,
        "previous_trading_day": previous_trading_day.isoformat(),
        "next_trading_day": next_trading_day.isoformat(),
        "session": {
            "pre_market_open_time": US_PRE_MARKET_OPEN_TIME.strftime("%H:%M"),
            "open_time": US_SESSION_OPEN_TIME.strftime("%H:%M"),
            "close_time": US_SESSION_CLOSE_TIME.strftime("%H:%M"),
            "after_hours_close_time": US_POST_MARKET_CLOSE_TIME.strftime("%H:%M"),
            "next_session_start_at": next_session_start_at.isoformat(),
            "is_polling_window": phase == "regular",
            "is_extended_polling_window": phase in {"pre_market", "after_hours"},
            "is_after_close": phase in {"after_hours", "post_close"},
        },
        "release_windows": release_windows,
        **_calendar_contract(
            market="us",
            year=current_date.year,
            now=local_now,
            fallback_source=US_CALENDAR_FALLBACK_SOURCE,
            fallback_verified_years=set(),
            fallback_limit="Rule-based NYSE fallback does not model emergency closures or special sessions.",
        ),
    }


def build_kr_calendar_status(now: datetime | None = None) -> dict[str, Any]:
    local_now = _as_market_datetime(now, KR_MARKET_TIMEZONE)
    current_date = local_now.date()
    holiday_name = kr_market_holiday_name(current_date)
    is_trading_day = is_kr_trading_day(current_date)
    previous_trading_day = previous_kr_trading_day(
        current_date,
        include_value=is_trading_day,
    )
    next_trading_day = next_kr_trading_day(current_date, include_value=False)
    phase = _session_phase(
        local_now=local_now,
        is_trading_day=is_trading_day,
        preopen_time=KR_SESSION_OPEN_TIME,
        open_time=KR_SESSION_OPEN_TIME,
        close_time=KR_SESSION_CLOSE_TIME,
    )
    release_windows = {
        "kr_daily_price": _release_window(
            key="kr_daily_price",
            label="KR daily price",
            release_time=KR_DAILY_PRICE_RELEASE_TIME,
            expected_trade_date=expected_kr_daily_price_date(now=local_now),
            local_now=local_now,
            current_date=current_date,
            is_trading_day=is_trading_day,
            next_trading_day=next_trading_day,
            timezone_value=KR_MARKET_TIMEZONE,
        )
    }
    next_session_start_at = _next_session_start_at(
        current_date=current_date,
        local_now=local_now,
        is_trading_day=is_trading_day,
        preopen_time=KR_SESSION_OPEN_TIME,
        next_trading_day=next_trading_day,
        timezone_value=KR_MARKET_TIMEZONE,
    )

    return {
        "market": "kr",
        "timezone": str(KR_MARKET_TIMEZONE),
        "checked_at": local_now.isoformat(),
        "date": current_date.isoformat(),
        "is_trading_day": is_trading_day,
        "phase": phase,
        "reason": _market_reason(
            value=current_date,
            is_trading_day=is_trading_day,
            holiday_name=holiday_name,
        ),
        "holiday_name": holiday_name,
        "previous_trading_day": previous_trading_day.isoformat(),
        "next_trading_day": next_trading_day.isoformat(),
        "session": {
            "open_time": KR_SESSION_OPEN_TIME.strftime("%H:%M"),
            "close_time": KR_SESSION_CLOSE_TIME.strftime("%H:%M"),
            "next_session_start_at": next_session_start_at.isoformat(),
            "is_polling_window": phase == "regular",
            "is_after_close": phase == "post_close",
        },
        "release_windows": release_windows,
        **_calendar_contract(
            market="kr",
            year=current_date.year,
            now=local_now,
            fallback_source=KR_CALENDAR_FALLBACK_SOURCE,
            fallback_verified_years=set(),
            fallback_limit="Fixed-date holidays and weekends only; lunar and ad hoc KRX holidays require a successful official calendar refresh.",
        ),
    }


def build_jp_calendar_status(now: datetime | None = None) -> dict[str, Any]:
    local_now = _as_market_datetime(now, JP_MARKET_TIMEZONE)
    current_date = local_now.date()
    holiday_name = jp_market_holiday_name(current_date)
    is_trading_day = is_jp_trading_day(current_date)
    previous_trading_day = previous_jp_trading_day(
        current_date,
        include_value=is_trading_day,
    )
    next_trading_day = next_jp_trading_day(current_date, include_value=False)
    phase = _jp_session_phase(
        local_now=local_now,
        is_trading_day=is_trading_day,
    )
    release_windows = {
        "jp_daily_price": _release_window(
            key="jp_daily_price",
            label="JP daily price",
            release_time=JP_DAILY_PRICE_RELEASE_TIME,
            expected_trade_date=expected_jp_daily_price_date(now=local_now),
            local_now=local_now,
            current_date=current_date,
            is_trading_day=is_trading_day,
            next_trading_day=next_trading_day,
            timezone_value=JP_MARKET_TIMEZONE,
        )
    }
    next_session_start_at = _next_session_start_at(
        current_date=current_date,
        local_now=local_now,
        is_trading_day=is_trading_day,
        preopen_time=JP_SESSION_OPEN_TIME,
        next_trading_day=next_trading_day,
        timezone_value=JP_MARKET_TIMEZONE,
    )
    if phase == "lunch_break":
        next_session_start_at = _local_datetime(
            current_date,
            JP_LUNCH_END_TIME,
            JP_MARKET_TIMEZONE,
        )

    return {
        "market": "jp",
        "timezone": str(JP_MARKET_TIMEZONE),
        "checked_at": local_now.isoformat(),
        "date": current_date.isoformat(),
        "is_trading_day": is_trading_day,
        "phase": phase,
        "reason": _market_reason(
            value=current_date,
            is_trading_day=is_trading_day,
            holiday_name=holiday_name,
        ),
        "holiday_name": holiday_name,
        "previous_trading_day": previous_trading_day.isoformat(),
        "next_trading_day": next_trading_day.isoformat(),
        "session": {
            "open_time": JP_SESSION_OPEN_TIME.strftime("%H:%M"),
            "lunch_start_time": JP_LUNCH_START_TIME.strftime("%H:%M"),
            "lunch_end_time": JP_LUNCH_END_TIME.strftime("%H:%M"),
            "close_time": JP_SESSION_CLOSE_TIME.strftime("%H:%M"),
            "next_session_start_at": next_session_start_at.isoformat(),
            "is_polling_window": phase == "regular",
            "is_after_close": phase == "post_close",
        },
        "release_windows": release_windows,
        **_calendar_contract(
            market="jp",
            year=current_date.year,
            now=local_now,
            fallback_source=JPX_CALENDAR_SOURCE,
            fallback_verified_years=JPX_VERIFIED_CALENDAR_YEARS,
            fallback_limit=jp_calendar_limit(current_date.year),
        ),
    }


def build_market_calendar_status(
    *,
    market: str = "all",
    now: datetime | None = None,
) -> dict[str, Any]:
    normalized_market = (market or "all").strip().lower()
    if normalized_market not in {"all", "tw", "us", "jp", "kr"}:
        raise ValueError("market must be one of: all, tw, us, jp, kr.")

    markets: dict[str, dict[str, Any]] = {}
    if normalized_market in {"all", "tw"}:
        markets["tw"] = build_taiwan_calendar_status(now=now)
    if normalized_market in {"all", "us"}:
        markets["us"] = build_us_calendar_status(now=now)
    if normalized_market in {"all", "jp"}:
        markets["jp"] = build_jp_calendar_status(now=now)
    if normalized_market in {"all", "kr"}:
        markets["kr"] = build_kr_calendar_status(now=now)

    return {
        "kind": "market_calendar_status",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "markets": markets,
    }


def market_status_from_calendar(
    calendar_status: dict[str, Any],
    *,
    market: MarketCode,
) -> dict[str, Any]:
    markets = calendar_status.get("markets")
    if isinstance(markets, dict) and isinstance(markets.get(market), dict):
        return markets[market]

    if calendar_status.get("market") == market:
        return calendar_status

    return {}


def release_window_from_calendar(
    calendar_status: dict[str, Any],
    *,
    market: MarketCode,
    key: str,
) -> dict[str, Any]:
    status = market_status_from_calendar(calendar_status, market=market)
    release_windows = status.get("release_windows")
    if not isinstance(release_windows, dict):
        return {}

    value = release_windows.get(key)
    return value if isinstance(value, dict) else {}


def expected_trade_date_from_calendar(
    calendar_status: dict[str, Any],
    *,
    market: MarketCode,
    key: str,
) -> date | None:
    release_window = release_window_from_calendar(
        calendar_status,
        market=market,
        key=key,
    )
    return _parse_date_value(release_window.get("expected_trade_date"))


def is_release_released_from_calendar(
    calendar_status: dict[str, Any],
    *,
    market: MarketCode,
    key: str,
) -> bool:
    release_window = release_window_from_calendar(
        calendar_status,
        market=market,
        key=key,
    )
    return release_window.get("is_released") is True


def expected_taiwan_trade_date(
    key: str,
    *,
    include_today: bool | None = None,
    now: datetime | None = None,
) -> date | None:
    if include_today is not None:
        if key == "market_chip_daily":
            return expected_market_chip_date(include_today=include_today, now=now)
        if key == "market_chip_margin_daily":
            return expected_market_margin_chip_date(
                include_today=include_today,
                now=now,
            )
        return expected_date_for_dataset(key, include_today=include_today, now=now)

    return expected_trade_date_from_calendar(
        build_taiwan_calendar_status(now=now),
        market="tw",
        key=key,
    )


def expected_us_trade_date(
    key: str = "us_daily_price",
    *,
    include_today: bool | None = None,
    now: datetime | None = None,
) -> date | None:
    if key != "us_daily_price":
        return None
    if include_today is not None:
        return expected_us_daily_price_date(include_today=include_today, now=now)

    return expected_trade_date_from_calendar(
        build_us_calendar_status(now=now),
        market="us",
        key=key,
    )


def expected_kr_trade_date(
    key: str = "kr_daily_price",
    *,
    include_today: bool | None = None,
    now: datetime | None = None,
) -> date | None:
    if key != "kr_daily_price":
        return None
    if include_today is not None:
        return expected_kr_daily_price_date(include_today=include_today, now=now)

    return expected_trade_date_from_calendar(
        build_kr_calendar_status(now=now),
        market="kr",
        key=key,
    )


def expected_jp_trade_date(
    key: str = "jp_daily_price",
    *,
    include_today: bool | None = None,
    now: datetime | None = None,
) -> date | None:
    if key != "jp_daily_price":
        return None
    if include_today is not None:
        return expected_jp_daily_price_date(include_today=include_today, now=now)

    return expected_trade_date_from_calendar(
        build_jp_calendar_status(now=now),
        market="jp",
        key=key,
    )


__all__ = [
    "build_market_calendar_status",
    "build_jp_calendar_status",
    "build_kr_calendar_status",
    "build_taiwan_calendar_status",
    "build_us_calendar_status",
    "expected_jp_trade_date",
    "expected_kr_trade_date",
    "expected_taiwan_trade_date",
    "expected_trade_date_from_calendar",
    "expected_us_trade_date",
    "is_release_released_from_calendar",
    "market_status_from_calendar",
    "release_window_from_calendar",
]
