"""Provider-neutral storage identities for official Taiwan market indices."""

from datetime import date, datetime, time

from app.market.trading_calendar import TAIWAN_TZ, latest_released_trading_day


# OMI's earliest close-evidence evaluation boundary, not a provider delivery SLA.
# A dated official receipt and canonical qualification remain mandatory.
TAIWAN_INDEX_CLOSE_EVALUATION_TIME = time(13, 35)


def expected_taiwan_index_close_date(*, now: datetime | None = None) -> date:
    return latest_released_trading_day(
        release_time=TAIWAN_INDEX_CLOSE_EVALUATION_TIME, now=now,
    )


def taiwan_index_close_release_at(trade_date: date) -> datetime:
    return datetime.combine(trade_date, TAIWAN_INDEX_CLOSE_EVALUATION_TIME, tzinfo=TAIWAN_TZ)

TW_INDEX_DATASET_ID = "tw.market_index.daily"
TWSE_INDEX_SOURCE_NAME = "TWSE Official Market Index Daily"
TPEX_INDEX_SOURCE_NAME = "TPEx Official Market Index Daily"


__all__ = [
    "TAIWAN_INDEX_CLOSE_EVALUATION_TIME",
    "expected_taiwan_index_close_date",
    "taiwan_index_close_release_at",
    "TPEX_INDEX_SOURCE_NAME",
    "TWSE_INDEX_SOURCE_NAME",
    "TW_INDEX_DATASET_ID",
]
