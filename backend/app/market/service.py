from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    FinancialMetricQuarterly,
    InstitutionalTradeDaily,
    MarginTradingDaily,
    MonthlyRevenue,
    ShareholdingDistributionWeekly,
    StockMaster,
)
from app.market.intraday import get_intraday_trend
from app.market.ohlc_overlay import aggregate_ohlc_points, append_intraday_overlay
from app.market.daily_ohlcv_platform import (
    TaiwanCanonicalDailyRow,
    project_taiwan_daily_bars,
    project_taiwan_daily_rows,
    read_taiwan_official_daily,
)
from app.market.daily_price_repository import TaiwanOfficialDailyBarRepository
from app.market.taiwan_rules import expected_daily_price_date
from app.market.trading_calendar import previous_taiwan_trading_day
from app.market.tw_daily_freshness import read_taiwan_daily_freshness
from app.market_data.contracts import (
    DatasetHealthStatus,
    ResolvedEvidenceStatus,
)
from app.market_data.integration_contracts import MarketDataResultV1


CHART_LOOKBACK_MULTIPLIER = {
    "daily": 2,
    "weekly": 7,
    "monthly": 31,
}
MAX_CHART_BARS = 5000
TAIWAN_TZ = ZoneInfo("Asia/Taipei")


@dataclass(frozen=True, slots=True)
class TaiwanMarketDailySnapshot:
    """One canonical completed-session universe and its matching coverage truth."""

    trade_date: date
    rows: tuple[TaiwanCanonicalDailyRow, ...] = ()
    universe_count: int = 0
    universe_count_by_market: tuple[tuple[str, int], ...] = ()
    selected_count_by_market: tuple[tuple[str, int], ...] = ()
    rows_examined: int = 0
    rows_rejected: int = 0
    duplicate_candidate_count: int = 0
    limitations: tuple[str, ...] = ()


def read_market_daily_snapshot(
    db: Session,
    *,
    trade_date: date | None = None,
    include_etf: bool = False,
) -> TaiwanMarketDailySnapshot:
    """Read rows and coverage metadata from the same canonical repository call."""

    completed_date = expected_daily_price_date()
    effective_date = min(trade_date, completed_date) if trade_date else completed_date
    universe = TaiwanOfficialDailyBarRepository(db).load_market_universe(
        trade_date=effective_date,
        include_etf=include_etf,
    )
    return TaiwanMarketDailySnapshot(
        trade_date=effective_date,
        rows=tuple(project_taiwan_daily_bars(db, universe.bars)),
        universe_count=universe.universe_count,
        universe_count_by_market=universe.universe_count_by_market,
        selected_count_by_market=universe.selected_count_by_market,
        rows_examined=universe.rows_examined,
        rows_rejected=universe.rows_rejected,
        duplicate_candidate_count=universe.duplicate_candidate_count,
        limitations=universe.limitations,
    )


def list_market_daily_prices(
    db: Session,
    trade_date: date | None = None,
    stock_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[TaiwanCanonicalDailyRow]:
    """Read selected official daily observations through the canonical owner."""

    if limit < 1 or limit > 20_000:
        raise ValueError("limit must be between 1 and 20000")
    if offset < 0:
        raise ValueError("offset must be non-negative")
    if stock_id is not None:
        result = read_taiwan_official_daily(
            db,
            stock_id=stock_id,
            from_date=trade_date,
            to_date=trade_date,
            limit=1 if trade_date is not None else min(limit + offset, 5000),
        )
        return project_taiwan_daily_rows(db, result)[offset : offset + limit]

    snapshot = read_market_daily_snapshot(
        db,
        trade_date=trade_date,
        include_etf=True,
    )
    return list(snapshot.rows[offset : offset + limit])


def get_latest_trade_date(
    db: Session,
    *,
    requested_at: datetime | None = None,
) -> date | None:
    """Return the latest release-qualified Taiwan completed-session date."""

    return read_taiwan_daily_freshness(
        db,
        checked_at=requested_at,
    ).latest_date


def list_latest_market_daily_prices(
    db: Session,
    limit: int = 100,
    offset: int = 0,
) -> list[TaiwanCanonicalDailyRow]:
    latest_trade_date = get_latest_trade_date(db)

    if latest_trade_date is None:
        return []

    return list_market_daily_prices(
        db=db,
        trade_date=latest_trade_date,
        limit=limit,
        offset=offset,
    )


def get_latest_stock_daily_price(
    db: Session,
    stock_id: str,
) -> TaiwanCanonicalDailyRow | None:
    result = read_taiwan_official_daily(db, stock_id=stock_id, limit=1)
    rows = project_taiwan_daily_rows(db, result)
    return rows[-1] if rows else None


def list_stock_daily_history(
    db: Session,
    stock_id: str,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 250,
    ascending: bool = True,
) -> list[TaiwanCanonicalDailyRow]:
    result = read_taiwan_official_daily(
        db,
        stock_id=stock_id,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
    )
    rows = project_taiwan_daily_rows(db, result)
    return rows if ascending else list(reversed(rows))


def list_stock_chart_data(
    db: Session,
    stock_id: str,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 250,
) -> list[dict]:
    rows = list_stock_daily_history(
        db=db,
        stock_id=stock_id,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        ascending=True,
    )

    return [
        {
            "time": row.trade_date,
            "open": row.open_price,
            "high": row.high_price,
            "low": row.low_price,
            "close": row.close_price,
            "volume": row.trade_volume,
            "trade_value": row.trade_value,
            "transaction_count": row.transaction_count,
        }
        for row in rows
    ]


def _sum_nullable(values: list[int | None]) -> int | None:
    valid_values = [value for value in values if value is not None]

    if not valid_values:
        return None

    return sum(valid_values)


def _chart_row(row: TaiwanCanonicalDailyRow, time_value: date | None = None) -> dict:
    return {
        "time": time_value or row.trade_date,
        "open": row.open_price,
        "high": row.high_price,
        "low": row.low_price,
        "close": row.close_price,
        "volume": row.trade_volume,
        "trade_value": row.trade_value,
        "transaction_count": row.transaction_count,
    }


def _whole_number(value: Decimal | None) -> int | None:
    if value is None:
        return None
    if value != value.to_integral_value():
        return None
    return int(value)


def _platform_chart_row(bar) -> dict:
    return {
        "time": bar.end_at.astimezone(TAIWAN_TZ).date(),
        "open": float(bar.open_price),
        "high": float(bar.high_price),
        "low": float(bar.low_price),
        "close": float(bar.close_price),
        "volume": _whole_number(bar.volume.value) if bar.volume else None,
        "trade_value": _whole_number(bar.turnover_value),
        "transaction_count": bar.trade_count,
    }


def _platform_daily_read(
    db: Session,
    *,
    stock: StockMaster,
    start_date: date,
    end_date: date,
    requested_to_date: date | None,
) -> tuple[list[dict], MarketDataResultV1]:
    result = read_taiwan_official_daily(
        db,
        stock_id=stock.stock_id,
        from_date=start_date,
        to_date=requested_to_date,
        limit=MAX_CHART_BARS,
    )
    return [_platform_chart_row(bar) for bar in result.resolved.bars], result


def _daily_points_with_platform(
    db: Session,
    *,
    stock_id: str,
    start_date: date,
    end_date: date,
    requested_to_date: date | None,
) -> tuple[list[dict], date | None, MarketDataResultV1 | None]:
    stock = db.query(StockMaster).filter(StockMaster.stock_id == stock_id).first()
    if stock is not None and str(stock.market or "").strip().upper() in {"TWSE", "TPEX"}:
        points, result = _platform_daily_read(
            db,
            stock=stock,
            start_date=start_date,
            end_date=end_date,
            requested_to_date=requested_to_date,
        )
        latest_date = points[-1]["time"] if points else None
        return points, latest_date, result
    return [], None, None


def _platform_quality(result: MarketDataResultV1 | None) -> tuple[str, list[str]]:
    if result is None:
        return "legacy", ["TW_DATA_CORE_INSTRUMENT_METADATA_UNAVAILABLE"]
    warnings = list(result.limitations)
    warnings.extend(result.resolved.health.limitations)
    warnings.extend(item.reason_code for item in result.candidate_rejections)
    dataset_status = result.dataset_health.status if result.dataset_health else None
    if dataset_status is DatasetHealthStatus.PARTIAL:
        quality = "partial"
    elif result.resolved.health.status in {
        ResolvedEvidenceStatus.SELECTED,
        ResolvedEvidenceStatus.FALLBACK,
    }:
        quality = "ok"
    elif result.resolved.health.status is ResolvedEvidenceStatus.STALE:
        quality = "stale"
    else:
        quality = "missing"
    return quality, list(dict.fromkeys(warnings))


def list_stock_ohlc_chart_data(
    db: Session,
    stock_id: str,
    timeframe: str = "daily",
    bars: int = 90,
    ensure_history: bool = False,
    include_intraday: bool = False,
    to_date: date | None = None,
    sleep_seconds: float = 0.1,
) -> dict:
    del sleep_seconds  # retained only for outward compatibility; GET is cache-only
    if timeframe not in CHART_LOOKBACK_MULTIPLIER:
        raise ValueError("timeframe must be one of: daily, weekly, monthly.")

    if bars <= 0:
        raise ValueError("bars must be greater than 0.")

    if bars > MAX_CHART_BARS:
        raise ValueError(f"bars must be less than or equal to {MAX_CHART_BARS}.")

    latest_potentially_released_date = expected_daily_price_date()
    end_date = (
        min(to_date, latest_potentially_released_date)
        if to_date is not None
        else latest_potentially_released_date
    )
    resolved_expected_data_date = previous_taiwan_trading_day(
        end_date,
        include_value=True,
    )
    lookback_days = bars * CHART_LOOKBACK_MULTIPLIER[timeframe]
    start_date = end_date - timedelta(days=lookback_days)

    backfill_result = None
    daily_points, latest_data_date, platform_result = _daily_points_with_platform(
        db,
        stock_id=stock_id,
        start_date=start_date,
        end_date=end_date,
        requested_to_date=to_date,
    )
    available_points = aggregate_ohlc_points(
        points=daily_points,
        timeframe=timeframe,
        sum_fields=("volume", "trade_value", "transaction_count"),
    )
    base_points = available_points[-bars:]
    refresh_reasons: list[str] = []
    if len(base_points) < bars:
        refresh_reasons.append("insufficient_history")
    if latest_data_date is None or latest_data_date < resolved_expected_data_date:
        refresh_reasons.append("stale_latest_date")

    if ensure_history:
        backfill_result = {
            "status": "not_attempted",
            "stock_id": stock_id,
            "refresh_reasons": refresh_reasons,
            "message": (
                "Deprecated ensure_history was ignored because Taiwan OHLC GET "
                "is cache-only; use an explicit bounded refresh operation."
            ),
        }

    intraday_overlay = None
    if include_intraday:
        daily_points, intraday_overlay = append_intraday_overlay(
            points=daily_points,
            intraday=get_intraday_trend(db=db, stock_id=stock_id),
            end_date=end_date,
            null_fields=("trade_value", "transaction_count"),
            finalized_through=latest_data_date,
        )
    points = aggregate_ohlc_points(
        points=daily_points,
        timeframe=timeframe,
        sum_fields=("volume", "trade_value", "transaction_count"),
    )[-bars:]
    freshness_status = (
        "missing"
        if latest_data_date is None
        else "stale"
        if latest_data_date < resolved_expected_data_date
        else "future"
        if latest_data_date > resolved_expected_data_date
        else "current"
    )
    data_quality, warnings = _platform_quality(platform_result)

    return {
        "stock_id": stock_id,
        "timeframe": timeframe,
        "requested_bar_count": bars,
        "available_bar_count": len(available_points),
        "returned_point_count": len(points),
        "bars": bars,
        "bars_legacy_count": bars,
        "deprecated_fields": ["bars"],
        "lookback_days": lookback_days,
        "from_date": start_date,
        "to_date": end_date,
        "requested_to_date": to_date,
        "point_count": len(points),
        "points": points,
        "backfill": backfill_result,
        "intraday_overlay": intraday_overlay,
        "volume_unit": "shares",
        "trade_value_unit": "TWD",
        "currency": "TWD",
        "volume_semantics": (
            "provisional_cumulative_traded_shares_overlay"
            if intraday_overlay is not None
            else "finalized_traded_shares"
        ),
        "volume_status": "available",
        "data_quality": data_quality,
        "warnings": warnings,
        "latest_data_date": latest_data_date,
        "latest_finalized_data_date": latest_data_date,
        "expected_data_date": resolved_expected_data_date,
        "freshness_status": freshness_status,
        "is_current": freshness_status == "current",
        "refresh_recommended": freshness_status in {"missing", "stale"},
    }


def get_latest_institutional_trade_date(db: Session) -> date | None:
    return db.query(func.max(InstitutionalTradeDaily.trade_date)).scalar()


def list_institutional_trades(db: Session, trade_date: date | None = None, stock_id: str | None = None, limit: int = 100, offset: int = 0) -> list[InstitutionalTradeDaily]:
    query = db.query(InstitutionalTradeDaily)
    if trade_date is not None:
        query = query.filter(InstitutionalTradeDaily.trade_date == trade_date)
    if stock_id is not None:
        query = query.filter(InstitutionalTradeDaily.stock_id == stock_id)
    return query.order_by(InstitutionalTradeDaily.trade_date.desc(), InstitutionalTradeDaily.stock_id.asc()).offset(offset).limit(limit).all()


def list_latest_institutional_trades(db: Session, limit: int = 100, offset: int = 0) -> list[InstitutionalTradeDaily]:
    latest_trade_date = get_latest_institutional_trade_date(db)
    if latest_trade_date is None:
        return []
    return list_institutional_trades(db=db, trade_date=latest_trade_date, limit=limit, offset=offset)


def get_latest_stock_institutional_trade(db: Session, stock_id: str) -> InstitutionalTradeDaily | None:
    return db.query(InstitutionalTradeDaily).filter(InstitutionalTradeDaily.stock_id == stock_id).order_by(InstitutionalTradeDaily.trade_date.desc()).first()


def list_stock_institutional_trade_history(db: Session, stock_id: str, from_date: date | None = None, to_date: date | None = None, limit: int = 250, ascending: bool = True) -> list[InstitutionalTradeDaily]:
    query = db.query(InstitutionalTradeDaily).filter(InstitutionalTradeDaily.stock_id == stock_id)
    if from_date is not None:
        query = query.filter(InstitutionalTradeDaily.trade_date >= from_date)
    if to_date is not None:
        query = query.filter(InstitutionalTradeDaily.trade_date <= to_date)
    rows = query.order_by(InstitutionalTradeDaily.trade_date.desc()).limit(limit).all()
    if ascending:
        rows.reverse()
    return rows


def get_latest_margin_trade_date(db: Session) -> date | None:
    return db.query(func.max(MarginTradingDaily.trade_date)).scalar()


def list_margin_trades(
    db: Session,
    trade_date: date | None = None,
    stock_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[MarginTradingDaily]:
    query = db.query(MarginTradingDaily)

    if trade_date is not None:
        query = query.filter(MarginTradingDaily.trade_date == trade_date)

    if stock_id is not None:
        query = query.filter(MarginTradingDaily.stock_id == stock_id)

    return (
        query.order_by(
            MarginTradingDaily.trade_date.desc(),
            MarginTradingDaily.stock_id.asc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )


def list_latest_margin_trades(
    db: Session,
    limit: int = 100,
    offset: int = 0,
) -> list[MarginTradingDaily]:
    latest_trade_date = get_latest_margin_trade_date(db)

    if latest_trade_date is None:
        return []

    return list_margin_trades(
        db=db,
        trade_date=latest_trade_date,
        limit=limit,
        offset=offset,
    )


def get_latest_stock_margin_trade(
    db: Session,
    stock_id: str,
) -> MarginTradingDaily | None:
    return (
        db.query(MarginTradingDaily)
        .filter(MarginTradingDaily.stock_id == stock_id)
        .order_by(MarginTradingDaily.trade_date.desc())
        .first()
    )


def list_stock_margin_trade_history(
    db: Session,
    stock_id: str,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 250,
    ascending: bool = True,
) -> list[MarginTradingDaily]:
    query = db.query(MarginTradingDaily).filter(MarginTradingDaily.stock_id == stock_id)

    if from_date is not None:
        query = query.filter(MarginTradingDaily.trade_date >= from_date)

    if to_date is not None:
        query = query.filter(MarginTradingDaily.trade_date <= to_date)

    rows = (
        query.order_by(MarginTradingDaily.trade_date.desc())
        .limit(limit)
        .all()
    )

    if ascending:
        rows.reverse()

    return rows


def get_latest_shareholding_date(db: Session) -> date | None:
    return db.query(func.max(ShareholdingDistributionWeekly.data_date)).scalar()


def list_shareholding_distributions(
    db: Session,
    data_date: date | None = None,
    stock_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[ShareholdingDistributionWeekly]:
    query = db.query(ShareholdingDistributionWeekly)

    if data_date is not None:
        query = query.filter(ShareholdingDistributionWeekly.data_date == data_date)

    if stock_id is not None:
        query = query.filter(ShareholdingDistributionWeekly.stock_id == stock_id)

    return (
        query.order_by(
            ShareholdingDistributionWeekly.data_date.desc(),
            ShareholdingDistributionWeekly.stock_id.asc(),
            ShareholdingDistributionWeekly.holding_level_order.asc(),
            ShareholdingDistributionWeekly.holding_level.asc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )


def list_latest_stock_shareholding_distribution(
    db: Session,
    stock_id: str,
) -> list[ShareholdingDistributionWeekly]:
    latest_date = (
        db.query(func.max(ShareholdingDistributionWeekly.data_date))
        .filter(ShareholdingDistributionWeekly.stock_id == stock_id)
        .scalar()
    )

    if latest_date is None:
        return []

    return list_shareholding_distributions(
        db=db,
        data_date=latest_date,
        stock_id=stock_id,
        limit=100,
    )


def list_stock_shareholding_history(
    db: Session,
    stock_id: str,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 5000,
) -> list[ShareholdingDistributionWeekly]:
    query = db.query(ShareholdingDistributionWeekly).filter(
        ShareholdingDistributionWeekly.stock_id == stock_id
    )

    if from_date is not None:
        query = query.filter(ShareholdingDistributionWeekly.data_date >= from_date)

    if to_date is not None:
        query = query.filter(ShareholdingDistributionWeekly.data_date <= to_date)

    return (
        query.order_by(
            ShareholdingDistributionWeekly.data_date.asc(),
            ShareholdingDistributionWeekly.holding_level_order.asc(),
            ShareholdingDistributionWeekly.holding_level.asc(),
        )
        .limit(limit)
        .all()
    )


def get_stock_chip_coverage(db: Session, stock_id: str) -> dict:
    shareholding_latest_date = (
        db.query(func.max(ShareholdingDistributionWeekly.data_date))
        .filter(ShareholdingDistributionWeekly.stock_id == stock_id)
        .scalar()
    )
    shareholding_week_count = (
        db.query(func.count(func.distinct(ShareholdingDistributionWeekly.data_date)))
        .filter(ShareholdingDistributionWeekly.stock_id == stock_id)
        .scalar()
        or 0
    )
    shareholding_row_count = (
        db.query(func.count(ShareholdingDistributionWeekly.id))
        .filter(ShareholdingDistributionWeekly.stock_id == stock_id)
        .scalar()
        or 0
    )
    margin_latest_trade_date = (
        db.query(func.max(MarginTradingDaily.trade_date))
        .filter(MarginTradingDaily.stock_id == stock_id)
        .scalar()
    )
    margin_row_count = (
        db.query(func.count(MarginTradingDaily.id))
        .filter(MarginTradingDaily.stock_id == stock_id)
        .scalar()
        or 0
    )

    return {
        "stock_id": stock_id,
        "shareholding_latest_date": shareholding_latest_date,
        "shareholding_week_count": shareholding_week_count,
        "shareholding_row_count": shareholding_row_count,
        "margin_latest_trade_date": margin_latest_trade_date,
        "margin_row_count": margin_row_count,
        "has_shareholding": shareholding_week_count > 0,
        "has_margin": margin_row_count > 0,
    }


def get_latest_monthly_revenue_period(db: Session) -> date | None:
    return db.query(func.max(MonthlyRevenue.period)).scalar()


def list_monthly_revenues(
    db: Session,
    period: date | None = None,
    stock_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[MonthlyRevenue]:
    query = db.query(MonthlyRevenue)

    if period is not None:
        query = query.filter(MonthlyRevenue.period == period)

    if stock_id is not None:
        query = query.filter(MonthlyRevenue.stock_id == stock_id)

    return (
        query.order_by(MonthlyRevenue.period.desc(), MonthlyRevenue.stock_id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def get_latest_stock_monthly_revenue(
    db: Session,
    stock_id: str,
) -> MonthlyRevenue | None:
    return (
        db.query(MonthlyRevenue)
        .filter(MonthlyRevenue.stock_id == stock_id)
        .order_by(MonthlyRevenue.period.desc())
        .first()
    )


def list_stock_monthly_revenue_history(
    db: Session,
    stock_id: str,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 120,
    ascending: bool = True,
) -> list[MonthlyRevenue]:
    query = db.query(MonthlyRevenue).filter(MonthlyRevenue.stock_id == stock_id)

    if from_date is not None:
        query = query.filter(MonthlyRevenue.period >= from_date)

    if to_date is not None:
        query = query.filter(MonthlyRevenue.period <= to_date)

    rows = query.order_by(MonthlyRevenue.period.desc()).limit(limit).all()

    if ascending:
        rows.reverse()

    return rows


def list_financial_metrics(
    db: Session,
    stock_id: str | None = None,
    fiscal_year: int | None = None,
    quarter: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[FinancialMetricQuarterly]:
    query = db.query(FinancialMetricQuarterly)

    if stock_id is not None:
        query = query.filter(FinancialMetricQuarterly.stock_id == stock_id)

    if fiscal_year is not None:
        query = query.filter(FinancialMetricQuarterly.fiscal_year == fiscal_year)

    if quarter is not None:
        query = query.filter(FinancialMetricQuarterly.quarter == quarter)

    return (
        query.order_by(
            FinancialMetricQuarterly.fiscal_year.desc(),
            FinancialMetricQuarterly.quarter.desc(),
            FinancialMetricQuarterly.stock_id.asc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )


def get_latest_stock_financial_metric(
    db: Session,
    stock_id: str,
) -> FinancialMetricQuarterly | None:
    return (
        db.query(FinancialMetricQuarterly)
        .filter(FinancialMetricQuarterly.stock_id == stock_id)
        .order_by(
            FinancialMetricQuarterly.fiscal_year.desc(),
            FinancialMetricQuarterly.quarter.desc(),
        )
        .first()
    )


def list_stock_financial_metric_history(
    db: Session,
    stock_id: str,
    limit: int = 40,
    ascending: bool = True,
) -> list[FinancialMetricQuarterly]:
    rows = (
        db.query(FinancialMetricQuarterly)
        .filter(FinancialMetricQuarterly.stock_id == stock_id)
        .order_by(
            FinancialMetricQuarterly.fiscal_year.desc(),
            FinancialMetricQuarterly.quarter.desc(),
        )
        .limit(limit)
        .all()
    )

    if ascending:
        rows.reverse()

    return rows
