from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    FinancialMetricQuarterly,
    InstitutionalTradeDaily,
    MarginTradingDaily,
    MarketDailyPrice,
    MonthlyRevenue,
    ShareholdingDistributionWeekly,
    StockMaster,
)
from app.market.backfill import backfill_tpex_trading_stock, backfill_twse_stock_day
from app.market.intraday import get_intraday_trend
from app.market.ohlc_overlay import aggregate_ohlc_points, append_intraday_overlay
from app.market.taiwan_rules import expected_daily_price_date
from app.market.trading_calendar import previous_taiwan_trading_day


CHART_LOOKBACK_MULTIPLIER = {
    "daily": 2,
    "weekly": 7,
    "monthly": 31,
}
MAX_CHART_BARS = 5000


def list_market_daily_prices(
    db: Session,
    trade_date: date | None = None,
    stock_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[MarketDailyPrice]:
    query = db.query(MarketDailyPrice)

    if trade_date is not None:
        query = query.filter(MarketDailyPrice.trade_date == trade_date)

    if stock_id is not None:
        query = query.filter(MarketDailyPrice.stock_id == stock_id)

    return (
        query.order_by(
            MarketDailyPrice.trade_date.desc(),
            MarketDailyPrice.stock_id.asc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )


def get_latest_trade_date(db: Session) -> date | None:
    return db.query(func.max(MarketDailyPrice.trade_date)).scalar()


def list_latest_market_daily_prices(
    db: Session,
    limit: int = 100,
    offset: int = 0,
) -> list[MarketDailyPrice]:
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
) -> MarketDailyPrice | None:
    return (
        db.query(MarketDailyPrice)
        .filter(MarketDailyPrice.stock_id == stock_id)
        .order_by(MarketDailyPrice.trade_date.desc())
        .first()
    )


def list_stock_daily_history(
    db: Session,
    stock_id: str,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 250,
    ascending: bool = True,
) -> list[MarketDailyPrice]:
    query = db.query(MarketDailyPrice).filter(MarketDailyPrice.stock_id == stock_id)

    if from_date is not None:
        query = query.filter(MarketDailyPrice.trade_date >= from_date)

    if to_date is not None:
        query = query.filter(MarketDailyPrice.trade_date <= to_date)

    # Get latest N rows first, then reverse to chronological order for charting.
    rows = (
        query.order_by(MarketDailyPrice.trade_date.desc())
        .limit(limit)
        .all()
    )

    if ascending:
        rows.reverse()

    return rows


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


def _chart_row(row: MarketDailyPrice, time_value: date | None = None) -> dict:
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


def _aggregate_market_rows(
    rows: list[MarketDailyPrice],
    timeframe: str,
) -> list[dict]:
    return aggregate_ohlc_points(
        points=[_chart_row(row) for row in rows],
        timeframe=timeframe,
        sum_fields=("volume", "trade_value", "transaction_count"),
    )


def _get_stock_market(db: Session, stock_id: str) -> str | None:
    stock = db.query(StockMaster).filter(StockMaster.stock_id == stock_id).first()

    if stock is None:
        return None

    return stock.market.upper()


def _ensure_stock_history(
    db: Session,
    stock_id: str,
    start_date: date,
    end_date: date,
    sleep_seconds: float,
) -> dict | None:
    market = _get_stock_market(db=db, stock_id=stock_id)

    if market == "TWSE":
        return backfill_twse_stock_day(
            db=db,
            stock_id=stock_id,
            start_date=start_date,
            end_date=end_date,
            sleep_seconds=sleep_seconds,
            skip_existing_months=True,
        )

    if market == "TPEX":
        return backfill_tpex_trading_stock(
            db=db,
            stock_id=stock_id,
            start_date=start_date,
            end_date=end_date,
            sleep_seconds=sleep_seconds,
            skip_existing_months=True,
        )

    return {
        "stock_id": stock_id,
        "stock_name": None,
        "source_id": 0,
        "start_date": start_date,
        "end_date": end_date,
        "requested_month_count": 0,
        "fetched_month_count": 0,
        "skipped_existing_month_count": 0,
        "parsed_count": 0,
        "inserted_count": 0,
        "skipped_count": 0,
        "status": "skipped",
        "message": f"History backfill is not configured for market='{market}'.",
        "months": [],
    }


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
    if timeframe not in CHART_LOOKBACK_MULTIPLIER:
        raise ValueError("timeframe must be one of: daily, weekly, monthly.")

    if bars <= 0:
        raise ValueError("bars must be greater than 0.")

    if bars > MAX_CHART_BARS:
        raise ValueError(f"bars must be less than or equal to {MAX_CHART_BARS}.")

    end_date = to_date or date.today()
    resolved_expected_data_date = (
        previous_taiwan_trading_day(end_date, include_value=True)
        if to_date is not None
        else expected_daily_price_date()
    )
    lookback_days = bars * CHART_LOOKBACK_MULTIPLIER[timeframe]
    start_date = end_date - timedelta(days=lookback_days)

    backfill_result = None
    rows = list_stock_daily_history(
        db=db,
        stock_id=stock_id,
        from_date=start_date,
        to_date=end_date,
        limit=5000,
        ascending=True,
    )
    daily_points = [_chart_row(row) for row in rows]
    base_points = aggregate_ohlc_points(
        points=daily_points,
        timeframe=timeframe,
        sum_fields=("volume", "trade_value", "transaction_count"),
    )[-bars:]
    latest_data_date = rows[-1].trade_date if rows else None
    refresh_reasons: list[str] = []
    if len(base_points) < bars:
        refresh_reasons.append("insufficient_history")
    if latest_data_date is None or latest_data_date < resolved_expected_data_date:
        refresh_reasons.append("stale_latest_date")

    if ensure_history and refresh_reasons:
        try:
            refresh_result = _ensure_stock_history(
                db=db,
                stock_id=stock_id,
                start_date=start_date,
                end_date=resolved_expected_data_date,
                sleep_seconds=sleep_seconds,
            )
            backfill_result = (
                {**refresh_result, "refresh_reasons": refresh_reasons}
                if refresh_result is not None
                else None
            )
        except Exception as exc:
            db.rollback()
            if not rows:
                raise
            backfill_result = {
                "status": "error",
                "stock_id": stock_id,
                "refresh_reasons": refresh_reasons,
                "message": f"Taiwan daily refresh failed; using cached rows: {exc}",
            }

        rows = list_stock_daily_history(
            db=db,
            stock_id=stock_id,
            from_date=start_date,
            to_date=end_date,
            limit=5000,
            ascending=True,
        )
        daily_points = [_chart_row(row) for row in rows]
        latest_data_date = rows[-1].trade_date if rows else None

    intraday_overlay = None
    if include_intraday:
        daily_points, intraday_overlay = append_intraday_overlay(
            points=daily_points,
            intraday=get_intraday_trend(db=db, stock_id=stock_id),
            end_date=end_date,
            null_fields=("trade_value", "transaction_count"),
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

    return {
        "stock_id": stock_id,
        "timeframe": timeframe,
        "bars": bars,
        "lookback_days": lookback_days,
        "from_date": start_date,
        "to_date": end_date,
        "point_count": len(points),
        "points": points,
        "backfill": backfill_result,
        "intraday_overlay": intraday_overlay,
        "latest_data_date": latest_data_date,
        "expected_data_date": resolved_expected_data_date,
        "freshness_status": freshness_status,
        "is_current": freshness_status in {"current", "future"},
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
