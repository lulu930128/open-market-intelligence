from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.db.models import (
    MarketDailyPrice,
    RadarEvaluationEventLink,
    RadarFeatureSnapshot,
    RadarOutcomeEventLink,
    RadarOutcomePath,
    RadarRuleEvaluation,
    utc_now,
)
from app.market.trading_calendar import next_taiwan_trading_day
from app.watchlists.radar_rule_contract import (
    RADAR_V2_OUTCOME_CONFIG,
    RADAR_V2_OUTCOME_CONFIG_HASH,
    RADAR_V2_OUTCOME_CONTRACT_VERSION,
)
from app.watchlists.radar_v2_service import ensure_rule_config, json_dumps, json_loads


DEFAULT_HORIZONS = tuple(
    int(value) for value in RADAR_V2_OUTCOME_CONFIG["horizons"]
)
DIRECTIONAL_BUCKETS = {
    "limit_up_lock",
    "surge_up",
    "limit_down_liquidity",
    "selloff_risk",
    "support_break",
    "volume_down",
    "bearish_momentum",
    "breakout_high",
    "trend_reclaim",
    "volume_up",
    "pullback",
    "momentum",
    "breakout",
    "limit_up_move",
    "limit_down_move",
}
COMPRESSION_BUCKETS = {"compression_watch"}
VOLATILITY_BUCKETS = {"volatility_risk", "volume", "watch"}
OVERHEAT_BUCKETS = {"overheated"}


class RadarV2EvaluationNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class OutcomePathBar:
    trade_date: date
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: int | None = None
    source: str = "market_daily_price"


def trading_dates_after(signal_trade_date: date, horizon: int) -> list[date]:
    if horizon <= 0:
        raise ValueError("Radar outcome horizon must be greater than zero.")
    dates: list[date] = []
    current = signal_trade_date
    for _ in range(horizon):
        current = next_taiwan_trading_day(current, include_value=False)
        dates.append(current)
    return dates


def _pct_change(value: float | None, base: float | None) -> float | None:
    if value is None or base is None or base <= 0:
        return None
    return ((value / base) - 1.0) * 100.0


def _positive_ratio(value: float, base: float | None) -> float | None:
    if base is None or base <= 0:
        return None
    return max(0.0, value / base)


def _outcome_kind(bucket: str, direction: int) -> str:
    if bucket in COMPRESSION_BUCKETS:
        return "compression"
    if bucket in VOLATILITY_BUCKETS:
        return "volatility"
    if bucket in OVERHEAT_BUCKETS:
        return "overheat"
    if bucket in DIRECTIONAL_BUCKETS or direction != 0:
        return "directional"
    return "observation"


def _directional_summary(
    *,
    intraday_triggered: bool,
    close_confirmed: bool,
    adverse_triggered: bool,
    reversed_flag: bool,
    whipsaw: bool,
    invalidated: bool,
) -> str:
    if whipsaw:
        return "whipsaw"
    if reversed_flag:
        return "reversed"
    if close_confirmed:
        return "close_confirmed"
    if intraday_triggered:
        return "intraday_only"
    if invalidated:
        return "invalidated"
    if adverse_triggered:
        return "adverse_only"
    return "neutral"


def _non_directional_summary(
    *,
    outcome_kind: str,
    upside_r: float | None,
    downside_r: float | None,
    signal_close_return_pct: float | None,
    directional_summary: str,
) -> str:
    thresholds = RADAR_V2_OUTCOME_CONFIG["non_directional_thresholds"]
    up = (upside_r or 0.0) >= thresholds["upside_expansion_r"]
    down = (downside_r or 0.0) >= thresholds["downside_expansion_r"]
    if outcome_kind == "overheat":
        close_threshold = float(thresholds["close_direction_pct"])
        close_return = signal_close_return_pct or 0.0
        if up and down:
            return "two_way_whipsaw"
        if up and close_return >= close_threshold:
            return "expanded_up"
        if down and close_return <= -close_threshold:
            return "expanded_down"
        if up:
            return "upside_rejected"
        if down:
            return "downside_recovered"
        if abs(close_return) >= close_threshold:
            return "high_level_consolidation"
        return "neutral"
    if outcome_kind == "compression":
        if up and down:
            return "two_way_expansion"
        if up:
            return "expanded_up"
        if down:
            return "expanded_down"
        return "no_price_expansion"
    if up and down:
        return "two_way_volatility"
    if up or down:
        return "range_expanded"
    return "normalized"


def calculate_outcome_path(
    *,
    bars: Iterable[OutcomePathBar],
    reference_price: float,
    signal_atr: float | None,
    direction: int,
    outcome_kind: str = "directional",
) -> dict[str, Any]:
    path = list(bars)
    if not path:
        raise ValueError("Radar outcome path requires at least one bar.")
    if reference_price <= 0:
        raise ValueError("Radar outcome reference price must be greater than zero.")
    if direction not in {-1, 0, 1}:
        raise ValueError("Radar outcome direction must be -1, 0, or 1.")
    for bar in path:
        prices = (
            bar.open_price,
            bar.high_price,
            bar.low_price,
            bar.close_price,
        )
        if any(value <= 0 for value in prices):
            raise ValueError("Radar outcome path prices must be greater than zero.")
        if bar.high_price < max(bar.open_price, bar.low_price, bar.close_price):
            raise ValueError("Radar outcome bar high price is inconsistent.")
        if bar.low_price > min(bar.open_price, bar.high_price, bar.close_price):
            raise ValueError("Radar outcome bar low price is inconsistent.")

    entry_price = path[0].open_price
    path_high = max(bar.high_price for bar in path)
    path_low = min(bar.low_price for bar in path)
    path_close = path[-1].close_price
    path_volume_values = [bar.volume for bar in path if bar.volume is not None]
    path_volume = sum(path_volume_values) if path_volume_values else None

    signal_open_gap_pct = _pct_change(entry_price, reference_price)
    signal_close_return_pct = _pct_change(path_close, reference_price)
    entry_close_return_pct = _pct_change(path_close, entry_price)

    if direction > 0:
        signal_favorable_move = path_high - reference_price
        signal_adverse_move = reference_price - path_low
        entry_favorable_move = path_high - entry_price
        entry_adverse_move = entry_price - path_low
        directional_close_move = path_close - entry_price
    elif direction < 0:
        signal_favorable_move = reference_price - path_low
        signal_adverse_move = path_high - reference_price
        entry_favorable_move = entry_price - path_low
        entry_adverse_move = path_high - entry_price
        directional_close_move = entry_price - path_close
    else:
        signal_favorable_move = 0.0
        signal_adverse_move = 0.0
        entry_favorable_move = 0.0
        entry_adverse_move = 0.0
        directional_close_move = 0.0

    signal_mfe_pct = (
        max(0.0, signal_favorable_move) / reference_price * 100.0
        if direction != 0
        else None
    )
    signal_mae_pct = (
        max(0.0, signal_adverse_move) / reference_price * 100.0
        if direction != 0
        else None
    )
    entry_mfe_pct = (
        max(0.0, entry_favorable_move) / entry_price * 100.0
        if direction != 0 and entry_price > 0
        else None
    )
    entry_mae_pct = (
        max(0.0, entry_adverse_move) / entry_price * 100.0
        if direction != 0 and entry_price > 0
        else None
    )

    close_r = (
        directional_close_move / signal_atr
        if direction != 0 and signal_atr is not None and signal_atr > 0
        else None
    )
    mfe_r = (
        _positive_ratio(entry_favorable_move, signal_atr)
        if direction != 0
        else None
    )
    mae_r = (
        _positive_ratio(entry_adverse_move, signal_atr)
        if direction != 0
        else None
    )
    upside_r = _positive_ratio(path_high - entry_price, signal_atr)
    downside_r = _positive_ratio(entry_price - path_low, signal_atr)

    thresholds = RADAR_V2_OUTCOME_CONFIG["directional_thresholds"]
    intraday_triggered = (
        mfe_r is not None and mfe_r >= thresholds["intraday_trigger_r"]
    )
    close_confirmed = (
        close_r is not None and close_r >= thresholds["close_confirm_r"]
    )
    adverse_triggered = (
        mae_r is not None and mae_r >= thresholds["adverse_trigger_r"]
    )
    reversed_flag = (
        intraday_triggered
        and close_r is not None
        and close_r <= thresholds["reverse_close_r"]
    )
    whipsaw = intraday_triggered and adverse_triggered
    invalidated = (
        mfe_r is not None
        and mfe_r < thresholds["invalidated_mfe_r_lt"]
        and close_r is not None
        and close_r <= thresholds["reverse_close_r"]
    )
    directional_summary = _directional_summary(
        intraday_triggered=intraday_triggered,
        close_confirmed=close_confirmed,
        adverse_triggered=adverse_triggered,
        reversed_flag=reversed_flag,
        whipsaw=whipsaw,
        invalidated=invalidated,
    )
    summary_state = (
        directional_summary
        if outcome_kind == "directional"
        else _non_directional_summary(
            outcome_kind=outcome_kind,
            upside_r=upside_r,
            downside_r=downside_r,
            signal_close_return_pct=signal_close_return_pct,
            directional_summary=directional_summary,
        )
    )

    return {
        "status": "evaluated",
        "summary_state": summary_state,
        "reference_direction": direction,
        "reference_price": reference_price,
        "reference_price_type": RADAR_V2_OUTCOME_CONFIG["reference_price_type"],
        "entry_proxy_price": entry_price,
        "entry_proxy_price_type": RADAR_V2_OUTCOME_CONFIG[
            "entry_proxy_price_type"
        ],
        "entry_proxy_trade_date": path[0].trade_date,
        "signal_atr": signal_atr,
        "path_open_price": entry_price,
        "path_high_price": path_high,
        "path_low_price": path_low,
        "path_close_price": path_close,
        "path_volume": path_volume,
        "signal_open_gap_pct": signal_open_gap_pct,
        "signal_close_return_pct": signal_close_return_pct,
        "signal_mfe_pct": signal_mfe_pct,
        "signal_mae_pct": signal_mae_pct,
        "entry_close_return_pct": entry_close_return_pct,
        "entry_mfe_pct": entry_mfe_pct,
        "entry_mae_pct": entry_mae_pct,
        "close_r": close_r,
        "mfe_r": mfe_r,
        "mae_r": mae_r,
        "intraday_triggered": intraday_triggered,
        "close_confirmed": close_confirmed,
        "adverse_triggered": adverse_triggered,
        "reversed": reversed_flag,
        "whipsaw": whipsaw,
        "invalidated": invalidated,
        "path_order_quality": RADAR_V2_OUTCOME_CONFIG["path_order_quality"],
        "tradability_status": RADAR_V2_OUTCOME_CONFIG["tradability_status"],
        "raw_path_json": json_dumps(
            {
                "bars": [
                    {
                        "trade_date": bar.trade_date,
                        "open": bar.open_price,
                        "high": bar.high_price,
                        "low": bar.low_price,
                        "close": bar.close_price,
                        "volume": bar.volume,
                        "source": bar.source,
                    }
                    for bar in path
                ],
                "outcome_kind": outcome_kind,
                "upside_r": upside_r,
                "downside_r": downside_r,
            }
        ),
    }


def _daily_bars(
    *,
    db: Session,
    stock_id: str,
    expected_dates: list[date],
) -> tuple[list[OutcomePathBar], list[date], list[str]]:
    rows = (
        db.query(MarketDailyPrice)
        .filter(MarketDailyPrice.stock_id == stock_id)
        .filter(MarketDailyPrice.trade_date.in_(expected_dates))
        .order_by(
            MarketDailyPrice.trade_date.asc(),
            MarketDailyPrice.updated_at.desc(),
            MarketDailyPrice.id.desc(),
        )
        .all()
    )
    selected: dict[date, MarketDailyPrice] = {}
    for row in rows:
        selected.setdefault(row.trade_date, row)

    bars: list[OutcomePathBar] = []
    invalid_dates: list[str] = []
    for trade_date in expected_dates:
        row = selected.get(trade_date)
        if row is None:
            continue
        values = (
            row.open_price,
            row.high_price,
            row.low_price,
            row.close_price,
        )
        if any(value is None or float(value) <= 0 for value in values):
            invalid_dates.append(trade_date.isoformat())
            continue
        bars.append(
            OutcomePathBar(
                trade_date=trade_date,
                open_price=float(row.open_price),
                high_price=float(row.high_price),
                low_price=float(row.low_price),
                close_price=float(row.close_price),
                volume=row.trade_volume,
            )
        )
    missing_dates = [
        trade_date for trade_date in expected_dates if trade_date not in selected
    ]
    return bars, missing_dates, invalid_dates


def _corporate_action_context(
    *,
    stock_id: str,
    date_from: date,
    date_to: date,
) -> tuple[str, list[dict[str, Any]], list[str]]:
    try:
        from app.market.tw_corporate_events import list_taiwan_corporate_events

        payload = list_taiwan_corporate_events(
            stock_id=stock_id,
            event_types={"ex_dividend"},
            date_from=date_from,
            date_to=date_to,
            limit=100,
        )
    except Exception as exc:
        return (
            "unavailable",
            [],
            [f"corporate_action_check_failed:{type(exc).__name__}"],
        )

    events = [
        event
        for event in (payload.get("results") or [])
        if isinstance(event, dict)
    ]
    if events:
        return "detected_unadjusted", events, ["corporate_action_unadjusted"]
    if payload.get("warning") or not payload.get("sources"):
        return "unavailable", [], ["corporate_action_coverage_unavailable"]
    return (
        "partial_coverage",
        [],
        [
            "corporate_action_types_unavailable:"
            "ex_rights,capital_reduction,stock_split,reverse_split,merger"
        ],
    )


def _serialize_outcome(
    row: RadarOutcomePath,
    *,
    signal_event_ids: list[int] | None = None,
) -> dict[str, Any]:
    return {
        "id": row.id,
        "evaluation_id": row.evaluation_id,
        "signal_event_id": row.signal_event_id,
        "signal_event_ids": signal_event_ids or (
            [row.signal_event_id] if row.signal_event_id is not None else []
        ),
        "stock_id": row.stock_id,
        "signal_trade_date": row.signal_trade_date,
        "horizon_trading_days": row.horizon_trading_days,
        "horizon_end_trade_date": row.horizon_end_trade_date,
        "outcome_contract_version": row.outcome_contract_version,
        "outcome_config_hash": row.outcome_config_hash,
        "status": row.status,
        "summary_state": row.summary_state,
        "direction": row.direction,
        "reference_direction": row.reference_direction,
        "reference_price": row.reference_price,
        "reference_price_type": row.reference_price_type,
        "entry_proxy_price": row.entry_proxy_price,
        "entry_proxy_price_type": row.entry_proxy_price_type,
        "entry_proxy_trade_date": row.entry_proxy_trade_date,
        "signal_atr": row.signal_atr,
        "path_open_price": row.path_open_price,
        "path_high_price": row.path_high_price,
        "path_low_price": row.path_low_price,
        "path_close_price": row.path_close_price,
        "path_volume": row.path_volume,
        "signal_open_gap_pct": row.signal_open_gap_pct,
        "signal_close_return_pct": row.signal_close_return_pct,
        "signal_mfe_pct": row.signal_mfe_pct,
        "signal_mae_pct": row.signal_mae_pct,
        "entry_close_return_pct": row.entry_close_return_pct,
        "entry_mfe_pct": row.entry_mfe_pct,
        "entry_mae_pct": row.entry_mae_pct,
        "close_r": row.close_r,
        "mfe_r": row.mfe_r,
        "mae_r": row.mae_r,
        "flags": {
            "intraday_triggered": row.intraday_triggered,
            "close_confirmed": row.close_confirmed,
            "adverse_triggered": row.adverse_triggered,
            "reversed": row.reversed,
            "whipsaw": row.whipsaw,
            "invalidated": row.invalidated,
        },
        "return_basis": row.return_basis,
        "corporate_action_status": row.corporate_action_status,
        "corporate_actions": json_loads(row.corporate_actions_json, []),
        "outcome_source": row.outcome_source,
        "outcome_quality": row.outcome_quality,
        "path_order_quality": row.path_order_quality,
        "tradability_status": row.tradability_status,
        "limitations": json_loads(row.limitations_json, []),
        "raw_path": json_loads(row.raw_path_json, {}),
        "evaluated_at": row.evaluated_at,
    }


def evaluate_radar_outcome_v2(
    *,
    db: Session,
    evaluation_id: int,
    horizons: Iterable[int] = DEFAULT_HORIZONS,
    signal_event_id: int | None = None,
    commit: bool = True,
    now: datetime | None = None,
    outcome_contract_version: str = RADAR_V2_OUTCOME_CONTRACT_VERSION,
    outcome_config_hash: str = RADAR_V2_OUTCOME_CONFIG_HASH,
    outcome_config: dict[str, Any] = RADAR_V2_OUTCOME_CONFIG,
    contract_status: str = "shadow",
) -> list[dict[str, Any]]:
    evaluation = (
        db.query(RadarRuleEvaluation)
        .filter(RadarRuleEvaluation.id == evaluation_id)
        .one_or_none()
    )
    if evaluation is None:
        raise RadarV2EvaluationNotFoundError(
            f"Radar v2 evaluation id={evaluation_id} was not found."
        )
    feature = (
        db.query(RadarFeatureSnapshot)
        .filter(RadarFeatureSnapshot.id == evaluation.feature_snapshot_id)
        .one()
    )
    linked_event_ids = [
        int(value)
        for (value,) in (
            db.query(RadarEvaluationEventLink.signal_event_id)
            .filter(
                RadarEvaluationEventLink.evaluation_id
                == evaluation.id
            )
            .order_by(RadarEvaluationEventLink.signal_event_id.asc())
            .all()
        )
    ]
    if signal_event_id is not None:
        linked_event_ids = sorted(
            {signal_event_id, *linked_event_ids}
        )
    canonical_signal_event_id = (
        linked_event_ids[0] if len(linked_event_ids) == 1 else None
    )
    normalized_horizons = sorted({int(value) for value in horizons})
    if not normalized_horizons or any(value <= 0 for value in normalized_horizons):
        raise ValueError("Radar outcome horizons must contain positive integers.")

    try:
        ensure_rule_config(
            db=db,
            contract_type="outcome",
            version=outcome_contract_version,
            config_hash=outcome_config_hash,
            config=outcome_config,
            status=contract_status,
            description="Radar v2 ATR-normalized multi-horizon outcome contract.",
        )
        results: list[dict[str, Any]] = []
        for horizon in normalized_horizons:
            expected_dates = trading_dates_after(
                feature.signal_trade_date,
                horizon,
            )
            bars, missing_dates, invalid_dates = _daily_bars(
                db=db,
                stock_id=feature.stock_id,
                expected_dates=expected_dates,
            )
            limitations = ["entry_proxy_not_execution", "daily_ohlc_path_unordered"]
            if feature.data_status != "current":
                limitations.append(f"feature_data_status:{feature.data_status}")
            if feature.freshness_status != "current":
                limitations.append(
                    f"feature_freshness_status:{feature.freshness_status}"
                )
            values: dict[str, Any] = {
                "evaluation_id": evaluation.id,
                "signal_event_id": canonical_signal_event_id,
                "stock_id": feature.stock_id,
                "signal_trade_date": feature.signal_trade_date,
                "horizon_trading_days": horizon,
                "horizon_end_trade_date": expected_dates[-1],
                "outcome_contract_version": outcome_contract_version,
                "outcome_config_hash": outcome_config_hash,
                "direction": evaluation.direction,
                "reference_direction": evaluation.direction,
                "reference_price": feature.close_price,
                "reference_price_type": outcome_config[
                    "reference_price_type"
                ],
                "signal_atr": feature.signal_atr,
                "return_basis": outcome_config["return_basis"],
                "path_order_quality": outcome_config[
                    "path_order_quality"
                ],
                "tradability_status": outcome_config[
                    "tradability_status"
                ],
                "entry_proxy_price": None,
                "entry_proxy_price_type": None,
                "entry_proxy_trade_date": None,
                "path_open_price": None,
                "path_high_price": None,
                "path_low_price": None,
                "path_close_price": None,
                "path_volume": None,
                "signal_open_gap_pct": None,
                "signal_close_return_pct": None,
                "signal_mfe_pct": None,
                "signal_mae_pct": None,
                "entry_close_return_pct": None,
                "entry_mfe_pct": None,
                "entry_mae_pct": None,
                "close_r": None,
                "mfe_r": None,
                "mae_r": None,
                "intraday_triggered": False,
                "close_confirmed": False,
                "adverse_triggered": False,
                "reversed": False,
                "whipsaw": False,
                "invalidated": False,
                "evaluated_at": now or utc_now(),
            }

            if missing_dates:
                values.update(
                    {
                        "status": "pending",
                        "summary_state": "pending",
                        "outcome_quality": "pending",
                        "corporate_action_status": "not_checked",
                        "corporate_actions_json": "[]",
                        "outcome_source": None,
                        "limitations_json": json_dumps(
                            limitations
                            + [
                                "missing_daily_bars:"
                                + ",".join(value.isoformat() for value in missing_dates)
                            ]
                        ),
                        "raw_path_json": json_dumps(
                            {
                                "expected_dates": expected_dates,
                                "available_dates": [
                                    bar.trade_date for bar in bars
                                ],
                            }
                        ),
                    }
                )
            elif invalid_dates:
                values.update(
                    {
                        "status": "unevaluable",
                        "summary_state": "unevaluable",
                        "outcome_quality": "invalid",
                        "corporate_action_status": "not_checked",
                        "corporate_actions_json": "[]",
                        "outcome_source": "market_daily_price",
                        "limitations_json": json_dumps(
                            limitations
                            + ["invalid_daily_bars:" + ",".join(invalid_dates)]
                        ),
                        "raw_path_json": json_dumps(
                            {"expected_dates": expected_dates}
                        ),
                    }
                )
            elif feature.close_price is None or feature.close_price <= 0:
                values.update(
                    {
                        "status": "unevaluable",
                        "summary_state": "unevaluable",
                        "outcome_quality": "invalid",
                        "corporate_action_status": "not_checked",
                        "corporate_actions_json": "[]",
                        "outcome_source": "market_daily_price",
                        "limitations_json": json_dumps(
                            limitations + ["missing_signal_close"]
                        ),
                        "raw_path_json": json_dumps(
                            {"expected_dates": expected_dates}
                        ),
                    }
                )
            else:
                calculation = calculate_outcome_path(
                    bars=bars,
                    reference_price=float(feature.close_price),
                    signal_atr=feature.signal_atr,
                    direction=evaluation.direction,
                    outcome_kind=_outcome_kind(
                        evaluation.primary_bucket,
                        evaluation.direction,
                    ),
                )
                corporate_status, corporate_actions, corporate_limitations = (
                    _corporate_action_context(
                        stock_id=feature.stock_id,
                        date_from=expected_dates[0],
                        date_to=expected_dates[-1],
                    )
                )
                limitations.extend(corporate_limitations)
                if feature.signal_atr is None or feature.signal_atr <= 0:
                    limitations.append("missing_signal_atr")
                    calculation["status"] = "partial"
                    calculation["summary_state"] = "unevaluable"
                values.update(calculation)
                values.update(
                    {
                        "corporate_action_status": corporate_status,
                        "corporate_actions_json": json_dumps(corporate_actions),
                        "outcome_source": "market_daily_price",
                        "outcome_quality": (
                            "final"
                            if corporate_status == "checked_clear"
                            and feature.data_status == "current"
                            and feature.freshness_status == "current"
                            else "partial"
                        ),
                        "limitations_json": json_dumps(
                            list(dict.fromkeys(limitations))
                        ),
                    }
                )

            row = (
                db.query(RadarOutcomePath)
                .filter(RadarOutcomePath.evaluation_id == evaluation.id)
                .filter(
                    RadarOutcomePath.outcome_contract_version
                    == outcome_contract_version
                )
                .filter(
                    RadarOutcomePath.outcome_config_hash
                    == outcome_config_hash
                )
                .filter(RadarOutcomePath.horizon_trading_days == horizon)
                .one_or_none()
            )
            if row is None:
                row = RadarOutcomePath(**values)
                db.add(row)
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            db.flush()
            for linked_event_id in linked_event_ids:
                link = (
                    db.query(RadarOutcomeEventLink)
                    .filter(
                        RadarOutcomeEventLink.outcome_path_id == row.id
                    )
                    .filter(
                        RadarOutcomeEventLink.signal_event_id
                        == linked_event_id
                    )
                    .one_or_none()
                )
                if link is None:
                    db.add(
                        RadarOutcomeEventLink(
                            outcome_path_id=row.id,
                            signal_event_id=linked_event_id,
                        )
                    )
            db.flush()
            results.append(
                _serialize_outcome(
                    row,
                    signal_event_ids=linked_event_ids,
                )
            )

        if commit:
            db.commit()
        return results
    except Exception:
        if commit:
            db.rollback()
        raise


__all__ = [
    "DEFAULT_HORIZONS",
    "OutcomePathBar",
    "RadarV2EvaluationNotFoundError",
    "calculate_outcome_path",
    "evaluate_radar_outcome_v2",
    "trading_dates_after",
]
