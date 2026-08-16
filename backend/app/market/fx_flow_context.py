from __future__ import annotations

from datetime import date, datetime, timezone
import math
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.db.models import (
    InstitutionalTradeDaily,
    MarketChipDaily,
    ResourceOhlcvBar,
)
from app.market.market_chips import expected_market_chip_date
from app.market.taiwan_rules import expected_institutional_trade_date
from app.resource_market.fx_freshness import evaluate_fx_freshness, fx_daily_data_date

FX_HISTORY_QUERY_LIMIT = 80
FLOW_WINDOWS = (1, 5, 20)
FX_NEUTRAL_BAND_5D_PCT = 0.15
FX_NEUTRAL_BAND_20D_PCT = 0.30


def build_fx_flow_context(
    db: Session,
    stock_id: str,
    *,
    generated_at: datetime | None = None,
    expected_market_trade_date: date | None = None,
    expected_stock_trade_date: date | None = None,
) -> dict[str, Any]:
    normalized_stock_id = stock_id.strip()
    now = _aware_utc(generated_at or datetime.now(timezone.utc))
    market_expected = expected_market_trade_date or expected_market_chip_date(now=now)
    stock_expected = expected_stock_trade_date or expected_institutional_trade_date(now=now)

    missing: list[str] = []
    warnings: list[str] = []
    stale_reasons: list[str] = []

    fx = _build_fx_trend(db, now=now)
    market_foreign = _build_market_foreign_flow(
        db,
        expected_trade_date=market_expected,
    )
    stock_foreign = _build_stock_foreign_flow(
        db,
        stock_id=normalized_stock_id,
        expected_trade_date=stock_expected,
    )

    if fx["usd_twd"] is None:
        missing.append("resource_ohlcv_bar.USD-TWD.1d")
    elif fx["usd_twd_change_5d_pct"] is None:
        missing.append("resource_ohlcv_bar.USD-TWD.1d.5d_history")
    if fx["usd_twd_change_20d_pct"] is None:
        warnings.append("USD/TWD 20 日趨勢尚無足夠日線資料。")
    if fx["source_symbol"] == "TWD-USD":
        warnings.append("USD/TWD 日線由 TWD-USD 反向換算。")
    if fx["usd_twd"] is not None and not bool(
        (fx.get("freshness") or {}).get("usable")
    ):
        stale_reasons.append("fx")
        warnings.append(
            "USD/TWD 日線未對齊最新已完成 FX session："
            f"資料 {fx.get('data_date')}，"
            f"預期 {(fx.get('freshness') or {}).get('expected_data_date')}。"
        )

    if market_foreign["trade_date"] is None:
        missing.append("market_chip_daily.TAIEX.foreign_investor_net_value")
    elif market_foreign["windows"][1]["net_value_twd"] is None:
        missing.append("market_chip_daily.TAIEX.foreign_investor_net_value.5d_history")
    if market_foreign["windows"][2]["net_value_twd"] is None:
        warnings.append("大盤外資 20 日累計尚無足夠資料。")
    if market_foreign["status"] == "stale":
        stale_reasons.append("market_foreign")
        warnings.append(
            "大盤外資最新日期 "
            f"{market_foreign['trade_date']}，落後預期 {market_expected.isoformat()}。"
        )

    if stock_foreign["trade_date"] is None:
        missing.append(
            f"institutional_trade_daily.{normalized_stock_id}.foreign_investor_net"
        )
    elif stock_foreign["windows"][1]["net_shares"] is None:
        missing.append(
            f"institutional_trade_daily.{normalized_stock_id}.foreign_investor_net.5d_history"
        )
    if stock_foreign["windows"][2]["net_shares"] is None:
        warnings.append("個股外資 20 日累計尚無足夠資料。")
    if stock_foreign["status"] == "stale":
        stale_reasons.append("stock_foreign")
        warnings.append(
            "個股外資最新日期 "
            f"{stock_foreign['trade_date']}，落後預期 {stock_expected.isoformat()}。"
        )

    signal = _combined_signal(
        fx_regime=fx["regime"],
        market_flow_state=market_foreign["state"],
    )
    status = "partial" if missing else "stale" if stale_reasons else "ready"
    source_refs = [
        {
            "type": "table",
            "name": "resource_ohlcv_bar",
            "provider": fx["provider"] or "yahoo_chart",
        },
        {
            "type": "table",
            "name": "market_chip_daily",
            "provider": "TWSE/TPEx",
        },
        {
            "type": "table",
            "name": "institutional_trade_daily",
            "provider": "TWSE/TPEx",
        },
        {"type": "derived", "name": "app.market.fx_flow_context"},
    ]

    return {
        "kind": "tw_fx_foreign_flow_context",
        "status": status,
        "is_current": status == "ready",
        "stock_id": normalized_stock_id,
        "signal": signal,
        "signal_horizon_days": 5,
        "causality": "confirmation_not_causation",
        "fx": fx,
        "market_foreign": market_foreign,
        "stock_foreign": stock_foreign,
        "missing": _dedupe(missing),
        "warnings": _dedupe(warnings),
        "source_refs": source_refs,
        "freshness": {
            "expected_market_trade_date": market_expected.isoformat(),
            "expected_stock_trade_date": stock_expected.isoformat(),
            "fx_freshness_profile": "daily_trend",
            "fx": fx.get("freshness"),
            "stale_reasons": _dedupe(stale_reasons),
        },
    }


def _build_fx_trend(db: Session, *, now: datetime) -> dict[str, Any]:
    observed_points = _latest_fx_daily_points(db)
    observed_latest = observed_points[0] if observed_points else None
    expected_probe = evaluate_fx_freshness(
        purpose="daily_trend",
        now=now,
        event_time=(observed_latest or {}).get("as_of"),
        fetched_at=(observed_latest or {}).get("fetched_at"),
        data_date=(observed_latest or {}).get("data_date"),
    )
    points = [
        point
        for point in observed_points
        if expected_probe.expected_data_date is None
        or point["data_date"] <= expected_probe.expected_data_date
    ]
    latest = points[0] if points else None
    usd_twd_change_1d = _fx_change(points, days=1, inverse=False)
    usd_twd_change_5d = _fx_change(points, days=5, inverse=False)
    usd_twd_change_20d = _fx_change(points, days=20, inverse=False)
    twd_change_1d = _fx_change(points, days=1, inverse=True)
    twd_change_5d = _fx_change(points, days=5, inverse=True)
    twd_change_20d = _fx_change(points, days=20, inverse=True)
    as_of = latest["as_of"] if latest is not None else None
    age_seconds = _age_seconds(now, as_of)
    freshness = evaluate_fx_freshness(
        purpose="daily_trend",
        now=now,
        event_time=as_of,
        fetched_at=latest.get("fetched_at") if latest is not None else None,
        data_date=latest.get("data_date") if latest is not None else None,
    )
    regime = _fx_regime(
        change_5d=usd_twd_change_5d,
        change_20d=usd_twd_change_20d,
    )
    status = (
        "missing"
        if latest is None
        else "partial"
        if usd_twd_change_5d is None
        else "stale"
        if not freshness.usable
        else "ready"
    )
    return {
        "status": status,
        "source_symbol": latest["source_symbol"] if latest is not None else None,
        "provider": latest["provider"] if latest is not None else None,
        "usd_twd": _round(latest["usd_twd"], 6) if latest is not None else None,
        "data_date": _iso(latest["data_date"] if latest is not None else None),
        "as_of": _iso(as_of),
        "age_seconds": age_seconds,
        "freshness": freshness.as_payload(),
        "history_points": len(points),
        "observed_history_points": len(observed_points),
        "excluded_provisional_points": len(observed_points) - len(points),
        "usd_twd_change_1d_pct": _round(usd_twd_change_1d),
        "usd_twd_change_5d_pct": _round(usd_twd_change_5d),
        "usd_twd_change_20d_pct": _round(usd_twd_change_20d),
        "twd_change_1d_pct": _round(twd_change_1d),
        "twd_change_5d_pct": _round(twd_change_5d),
        "twd_change_20d_pct": _round(twd_change_20d),
        "regime": regime,
    }


def _latest_fx_daily_points(db: Session) -> list[dict[str, Any]]:
    for symbol in ("USD-TWD", "TWD-USD"):
        rows = (
            db.query(ResourceOhlcvBar)
            .filter(
                ResourceOhlcvBar.symbol == symbol,
                ResourceOhlcvBar.interval == "1d",
            )
            .order_by(
                ResourceOhlcvBar.bar_time.desc(),
                ResourceOhlcvBar.fetched_at.desc(),
                ResourceOhlcvBar.id.desc(),
            )
            .limit(FX_HISTORY_QUERY_LIMIT)
            .all()
        )
        points: list[dict[str, Any]] = []
        seen_dates: set[date] = set()
        for row in rows:
            if not _positive(row.close_price):
                continue
            data_date = fx_daily_data_date(row.bar_time, row.raw_payload_json)
            if data_date is None:
                continue
            if data_date in seen_dates:
                continue
            close = float(row.close_price)
            points.append(
                {
                    "source_symbol": symbol,
                    "provider": row.provider,
                    "usd_twd": close if symbol == "USD-TWD" else 1 / close,
                    "data_date": data_date,
                    "as_of": row.bar_time,
                    "fetched_at": row.fetched_at,
                }
            )
            seen_dates.add(data_date)
        if points:
            return points
    return []


def _build_market_foreign_flow(
    db: Session,
    *,
    expected_trade_date: date,
) -> dict[str, Any]:
    rows = (
        db.query(MarketChipDaily)
        .filter(
            MarketChipDaily.index_id == "TAIEX",
            MarketChipDaily.trade_date <= expected_trade_date,
        )
        .order_by(MarketChipDaily.trade_date.desc(), MarketChipDaily.id.desc())
        .limit(max(FLOW_WINDOWS))
        .all()
    )
    windows = _flow_windows(
        rows,
        net_getter=lambda row: _integer(row.foreign_investor_net_value),
        turnover_getter=lambda row: _integer(row.trade_value),
        value_field="net_value_twd",
    )
    latest_date = _latest_flow_date(
        rows,
        net_getter=lambda row: _integer(row.foreign_investor_net_value),
    )
    state, basis_days = _flow_state(windows, value_field="net_value_twd")
    return {
        "scope": "market",
        "status": _flow_status(latest_date, expected_trade_date, windows, "net_value_twd"),
        "state": state,
        "state_basis_days": basis_days,
        "trade_date": _iso(latest_date),
        "expected_trade_date": expected_trade_date.isoformat(),
        "windows": windows,
    }


def _build_stock_foreign_flow(
    db: Session,
    *,
    stock_id: str,
    expected_trade_date: date,
) -> dict[str, Any]:
    rows = (
        db.query(InstitutionalTradeDaily)
        .filter(
            InstitutionalTradeDaily.stock_id == stock_id,
            InstitutionalTradeDaily.trade_date <= expected_trade_date,
        )
        .order_by(
            InstitutionalTradeDaily.trade_date.desc(),
            InstitutionalTradeDaily.updated_at.desc(),
            InstitutionalTradeDaily.id.desc(),
        )
        .limit(max(FLOW_WINDOWS) * 3)
        .all()
    )
    unique_rows = _dedupe_rows_by_trade_date(rows)
    windows = _flow_windows(
        unique_rows,
        net_getter=_stock_foreign_net_shares,
        turnover_getter=None,
        value_field="net_shares",
    )
    latest_date = _latest_flow_date(unique_rows, net_getter=_stock_foreign_net_shares)
    state, basis_days = _flow_state(windows, value_field="net_shares")
    return {
        "scope": "stock",
        "status": _flow_status(latest_date, expected_trade_date, windows, "net_shares"),
        "state": state,
        "state_basis_days": basis_days,
        "trade_date": _iso(latest_date),
        "expected_trade_date": expected_trade_date.isoformat(),
        "windows": windows,
    }


def _flow_windows(
    rows: list[Any],
    *,
    net_getter: Callable[[Any], int | None],
    turnover_getter: Callable[[Any], int | None] | None,
    value_field: str,
) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    for days in FLOW_WINDOWS:
        selected = rows[:days]
        net_values = [net_getter(row) for row in selected]
        available_days = sum(value is not None for value in net_values)
        complete = len(selected) == days and available_days == days
        net_total = sum(value for value in net_values if value is not None) if complete else None
        turnover_total: int | None = None
        turnover_ratio_pct: float | None = None
        if turnover_getter is not None:
            turnover_values = [turnover_getter(row) for row in selected]
            turnover_complete = (
                len(selected) == days
                and all(value is not None and value > 0 for value in turnover_values)
            )
            if turnover_complete:
                turnover_total = sum(int(value) for value in turnover_values if value is not None)
                if net_total is not None and turnover_total > 0:
                    turnover_ratio_pct = net_total / turnover_total * 100
        windows.append(
            {
                "days": days,
                "available_days": available_days,
                "net_value_twd": net_total if value_field == "net_value_twd" else None,
                "turnover_twd": turnover_total,
                "turnover_ratio_pct": _round(turnover_ratio_pct),
                "net_shares": net_total if value_field == "net_shares" else None,
            }
        )
    return windows


def _flow_status(
    latest_date: date | None,
    expected_date: date,
    windows: list[dict[str, Any]],
    value_field: str,
) -> str:
    if latest_date is None:
        return "missing"
    if latest_date < expected_date:
        return "stale"
    if windows[1][value_field] is None:
        return "partial"
    return "ready"


def _flow_state(
    windows: list[dict[str, Any]],
    *,
    value_field: str,
) -> tuple[str, int | None]:
    for window in (windows[1], windows[0]):
        value = window[value_field]
        if value is None:
            continue
        if value > 0:
            return "inflow", int(window["days"])
        if value < 0:
            return "outflow", int(window["days"])
        return "neutral", int(window["days"])
    return "missing", None


def _fx_regime(*, change_5d: float | None, change_20d: float | None) -> str:
    if change_5d is None:
        return "unknown"
    if change_20d is None:
        if change_5d > FX_NEUTRAL_BAND_5D_PCT:
            return "twd_weakening"
        if change_5d < -FX_NEUTRAL_BAND_5D_PCT:
            return "twd_strengthening"
        return "neutral"
    if (
        abs(change_5d) < FX_NEUTRAL_BAND_5D_PCT
        and abs(change_20d) < FX_NEUTRAL_BAND_20D_PCT
    ):
        return "neutral"
    if change_5d > FX_NEUTRAL_BAND_5D_PCT and change_20d > 0:
        return "twd_weakening"
    if change_5d < -FX_NEUTRAL_BAND_5D_PCT and change_20d < 0:
        return "twd_strengthening"
    return "mixed"


def _combined_signal(*, fx_regime: str, market_flow_state: str) -> str:
    if fx_regime == "unknown" or market_flow_state == "missing":
        return "unknown"
    if fx_regime == "twd_weakening" and market_flow_state == "outflow":
        return "confirmed_outflow"
    if fx_regime == "twd_strengthening" and market_flow_state == "inflow":
        return "confirmed_inflow"
    if fx_regime == "twd_weakening" and market_flow_state == "inflow":
        return "weak_twd_inflow_divergence"
    if fx_regime == "twd_strengthening" and market_flow_state == "outflow":
        return "strong_twd_outflow_divergence"
    if fx_regime == "twd_weakening":
        return "fx_pressure_only"
    if fx_regime == "twd_strengthening":
        return "fx_support_only"
    if market_flow_state == "outflow":
        return "outflow_only"
    if market_flow_state == "inflow":
        return "inflow_only"
    return "mixed"


def _stock_foreign_net_shares(row: InstitutionalTradeDaily) -> int | None:
    values = [
        value
        for value in (
            _integer(row.foreign_investor_net),
            _integer(row.foreign_dealer_net),
        )
        if value is not None
    ]
    return sum(values) if values else None


def _latest_flow_date(
    rows: list[Any],
    *,
    net_getter: Callable[[Any], int | None],
) -> date | None:
    return next((row.trade_date for row in rows if net_getter(row) is not None), None)


def _dedupe_rows_by_trade_date(rows: list[Any]) -> list[Any]:
    unique_rows: list[Any] = []
    seen_dates: set[date] = set()
    for row in rows:
        if row.trade_date in seen_dates:
            continue
        unique_rows.append(row)
        seen_dates.add(row.trade_date)
    return unique_rows


def _fx_change(
    points: list[dict[str, Any]],
    *,
    days: int,
    inverse: bool,
) -> float | None:
    if len(points) <= days:
        return None
    latest = points[0]["usd_twd"]
    previous = points[days]["usd_twd"]
    if not _positive(latest) or not _positive(previous):
        return None
    if inverse:
        return (previous / latest - 1) * 100
    return (latest / previous - 1) * 100


def _age_seconds(now: datetime, value: datetime | None) -> int | None:
    if value is None:
        return None
    normalized = _aware_utc(value)
    return max(0, int((now - normalized).total_seconds()))


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _positive(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def _integer(value: Any) -> int | None:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


def _round(value: Any, digits: int = 4) -> float | None:
    return (
        round(float(value), digits)
        if isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        else None
    )


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
