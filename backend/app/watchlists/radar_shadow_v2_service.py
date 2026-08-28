from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timezone
import os
from typing import Any, Mapping

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.db.models import (
    RadarEvaluationEventLink,
    RadarFeatureSnapshot,
    RadarOutcomePath,
    RadarRuleEvaluation,
    RadarSignalEvent,
    RadarUniverseObservation,
    RadarWatchlistProjection,
    TaiwanMarketMinuteState,
    WatchlistRadarSnapshotRun,
    utc_now,
)
from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_daily_freshness import read_taiwan_daily_freshness
from app.market.tw_market_breadth_contract import TW_MARKET_BREADTH_VERSION
from app.watchlists.radar_regime_v2 import (
    classify_instrument_regime,
    classify_market_regime,
    combined_regime_clarity,
    scoring_config_for_instrument_regime,
)
from app.watchlists.radar_rule_contract import (
    RADAR_V1_RULE_VERSION,
    RADAR_V2_ACTIVE_CONTRACT,
    RADAR_V2_FEATURE_CONFIG_HASH,
    RADAR_V2_FEATURE_VERSION,
    RADAR_V2_RULE_CONFIG,
    RADAR_V2_RULE_CONFIG_HASH,
    RADAR_V2_RULE_VERSION,
    RADAR_V2_SHADOW_CONTRACT,
    RADAR_V2_SIGNAL_DEFINITIONS,
    config_hash,
)
from app.watchlists.radar_scoring_v2 import score_radar_signals
from app.watchlists.radar_v2_service import ensure_rule_config, json_dumps


RADAR_V2_SHADOW_ENV = "OMI_RADAR_V2_SHADOW_ENABLED"


def radar_v2_shadow_enabled() -> bool:
    value = os.getenv(RADAR_V2_SHADOW_ENV)
    if value is None:
        return True
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _trade_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _effective_at(item: Mapping[str, Any], signal_trade_date: date) -> datetime:
    raw_value = item.get("time")
    if isinstance(raw_value, datetime):
        parsed = raw_value
    else:
        text = str(raw_value or "").strip()
        if len(text) == 10:
            parsed = datetime.combine(
                signal_trade_date,
                time(13, 30),
                tzinfo=TAIWAN_TZ,
            )
        else:
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                parsed = datetime.combine(
                    signal_trade_date,
                    time(13, 30),
                    tzinfo=TAIWAN_TZ,
                )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TAIWAN_TZ)
    return parsed.astimezone(timezone.utc)


def _source_available_at(
    item: Mapping[str, Any],
    *,
    observed_at: datetime,
) -> tuple[datetime, bool]:
    for key in ("source_available_at", "data_available_at", "provider_updated_at"):
        raw_value = item.get(key)
        if not raw_value:
            continue
        if isinstance(raw_value, datetime):
            parsed = raw_value
        else:
            try:
                parsed = datetime.fromisoformat(
                    str(raw_value).strip().replace("Z", "+00:00")
                )
            except ValueError:
                continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=TAIWAN_TZ)
        return parsed.astimezone(timezone.utc), False
    return _utc_comparable(observed_at), True


def _utc_comparable(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _data_quality(item: Mapping[str, Any]) -> dict[str, Any]:
    status = str(item.get("status") or "unknown")
    stale = bool(item.get("stale"))
    context = item.get("context_snapshot")
    intraday = context.get("intraday") if isinstance(context, Mapping) else None
    provisional = bool(
        isinstance(intraday, Mapping)
        or status == "intraday"
    )
    indicators = item.get("indicator_snapshot")
    indicator_groups = (
        sum(
            isinstance(value, Mapping) and bool(value)
            for value in indicators.values()
        )
        if isinstance(indicators, Mapping)
        else 0
    )
    completeness = min(1.0, indicator_groups / 8.0)
    if status in {"error", "no_data"}:
        data_status = status
        freshness_status = "missing"
        freshness = 0.0
        source_quality = 0.0
    else:
        data_status = "partial" if completeness < 0.75 else "current"
        freshness_status = "stale" if stale else "provisional" if provisional else "current"
        freshness = 0.5 if stale else 0.8 if provisional else 1.0
        source_quality = 1.0
    quality = freshness * completeness * source_quality
    limitations: list[dict[str, Any]] = []
    if stale:
        limitations.append({"code": "stale_feature_input"})
    if provisional:
        limitations.append({"code": "provisional_intraday_overlay"})
    if completeness < 1.0:
        limitations.append(
            {
                "code": "incomplete_indicator_snapshot",
                "completeness_score": round(completeness, 6),
            }
        )
    return {
        "data_status": data_status,
        "freshness_status": freshness_status,
        "freshness_score": round(freshness, 6),
        "completeness_score": round(completeness, 6),
        "source_quality_score": round(source_quality, 6),
        "data_quality_score": round(quality, 6),
        "is_provisional": provisional,
        "is_stale": stale,
        "limitations": limitations,
    }


def latest_market_regime_snapshot(
    *,
    db: Session,
    signal_trade_date: date | None,
    as_of_at: datetime | None = None,
) -> dict[str, Any] | None:
    latest_trade_date = (
        db.query(TaiwanMarketMinuteState.trade_date)
        .filter(
            TaiwanMarketMinuteState.breadth_contract_version
            == TW_MARKET_BREADTH_VERSION
        )
        .filter(TaiwanMarketMinuteState.breadth_decision_usable.is_(True))
        .filter(TaiwanMarketMinuteState.breadth_status == "ready")
        .filter(
            TaiwanMarketMinuteState.trade_date <= signal_trade_date
            if signal_trade_date is not None
            else True
        )
        .order_by(TaiwanMarketMinuteState.trade_date.desc())
        .limit(1)
        .scalar()
    )
    if latest_trade_date is None:
        return None

    rows = (
        db.query(TaiwanMarketMinuteState)
        .filter(TaiwanMarketMinuteState.trade_date == latest_trade_date)
        .filter(
            TaiwanMarketMinuteState.breadth_contract_version
            == TW_MARKET_BREADTH_VERSION
        )
        .filter(TaiwanMarketMinuteState.breadth_decision_usable.is_(True))
        .filter(TaiwanMarketMinuteState.breadth_status == "ready")
        .order_by(TaiwanMarketMinuteState.minute_at.desc())
        .all()
    )
    if as_of_at is not None:
        cutoff = _utc_comparable(as_of_at)
        rows = [
            row
            for row in rows
            if _utc_comparable(row.minute_at) <= cutoff
        ]
    rows_by_minute: dict[
        datetime,
        dict[str, TaiwanMarketMinuteState],
    ] = {}
    for row in rows:
        rows_by_minute.setdefault(row.minute_at, {})[str(row.market)] = row
    if not rows_by_minute:
        return None

    aligned_minutes = [
        minute_at
        for minute_at, market_rows in rows_by_minute.items()
        if all(market in market_rows for market in ("TWSE", "TPEX"))
    ]
    selected_minute = max(aligned_minutes or rows_by_minute.keys())
    latest_by_market = rows_by_minute[selected_minute]
    selected = [
        latest_by_market[market]
        for market in ("TWSE", "TPEX")
        if market in latest_by_market
    ]
    if not selected:
        return None
    taiex = latest_by_market.get("TWSE") or selected[0]
    return {
        "trade_date": latest_trade_date.isoformat(),
        "minute_at": selected_minute.isoformat(),
        "quality_status": (
            "ready"
            if len(selected) == 2
            and all(row.quality_status == "ready" for row in selected)
            else "partial"
        ),
        "breadth_status": (
            "ready"
            if len(selected) == 2
            and all(row.breadth_status == "ready" for row in selected)
            else "partial"
        ),
        "breadth_session_phase": (
            selected[0].breadth_session_phase
            if all(
                row.breadth_session_phase == selected[0].breadth_session_phase
                for row in selected
            )
            else "mixed"
        ),
        "breadth_contract_version": TW_MARKET_BREADTH_VERSION,
        "breadth_decision_usable": all(
            row.breadth_decision_usable for row in selected
        ),
        "breadth_scope": (
            "full_market"
            if len(selected) == 2
            and all(row.breadth_scope == "full_market" for row in selected)
            else "partial"
        ),
        "advance_count": sum(int(row.advance_count or 0) for row in selected),
        "decline_count": sum(int(row.decline_count or 0) for row in selected),
        "unchanged_count": sum(int(row.unchanged_count or 0) for row in selected),
        "total_count": sum(int(row.total_count or 0) for row in selected),
        "unknown_count": sum(int(row.unknown_count or 0) for row in selected),
        "missing_count": sum(int(row.missing_count or 0) for row in selected),
        "index_change_pct": taiex.index_change_pct,
        "source": "+".join(sorted({str(row.source) for row in selected})),
    }


def _context_alignment(item: Mapping[str, Any]) -> float:
    context_score = _number(item.get("context_score")) or 0.0
    return max(-100.0, min(100.0, context_score * 25.0))


def _active_context_alignment(item: Mapping[str, Any]) -> float:
    stance_scores = {
        "confirm": 1.0,
        "contradict": -1.0,
        "risk": -0.5,
        "info": 0.0,
    }
    observed = [
        stance_scores.get(str(signal.get("stance") or ""), 0.0)
        for signal in item.get("context_signals") or []
        if isinstance(signal, Mapping)
    ]
    if not observed:
        return 0.0
    return max(
        -100.0,
        min(100.0, 100.0 * sum(observed) / len(observed)),
    )


def _indicator_number(
    item: Mapping[str, Any],
    group: str,
    key: str,
) -> float | None:
    snapshot = item.get("indicator_snapshot")
    values = snapshot.get(group) if isinstance(snapshot, Mapping) else None
    return _number(values.get(key)) if isinstance(values, Mapping) else None


def _bounded_strength(
    distance: float | None,
    scale: float | None,
    *,
    floor: float = 0.2,
) -> float | None:
    if distance is None or scale is None or scale <= 0:
        return None
    return max(floor, min(1.0, abs(distance) / scale))


def _signal_strengths(
    *,
    item: Mapping[str, Any],
    signal_keys: list[str],
) -> tuple[dict[str, float], list[str]]:
    close = _number(item.get("close"))
    previous_close = _number(item.get("previous_close"))
    atr = _indicator_number(item, "atr", "atr14")
    scale = atr or (abs(close) * 0.02 if close not in {None, 0} else None)
    strengths = {key: 0.5 for key in signal_keys}
    measured: set[str] = set()

    def set_distance(key: str, left: float | None, right: float | None) -> None:
        value = (
            _bounded_strength(left - right, scale)
            if left is not None and right is not None
            else None
        )
        if value is not None:
            strengths[key] = value
            measured.add(key)

    for window in (5, 20, 60):
        ma_value = _indicator_number(item, "ma", f"ma{window}")
        set_distance(f"above_ma{window}", close, ma_value)
        set_distance(f"below_ma{window}", close, ma_value)
        set_distance(f"cross_above_ma{window}", close, ma_value)
        set_distance(f"cross_below_ma{window}", close, ma_value)
    ma5 = _indicator_number(item, "ma", "ma5")
    ma20 = _indicator_number(item, "ma", "ma20")
    ma60 = _indicator_number(item, "ma", "ma60")
    set_distance("ma5_above_ma20", ma5, ma20)
    set_distance("ma5_below_ma20", ma5, ma20)
    set_distance("ma20_above_ma60", ma20, ma60)
    set_distance("ma20_below_ma60", ma20, ma60)

    ema_fast = _indicator_number(item, "ema", "ema12")
    ema_slow = _indicator_number(item, "ema", "ema26")
    for key in (
        "ema_fast_above_slow",
        "ema_fast_below_slow",
        "ema_bullish_cross",
        "ema_bearish_cross",
    ):
        set_distance(key, ema_fast, ema_slow)

    price_change = (
        close - previous_close
        if close is not None and previous_close is not None
        else None
    )
    for key in ("price_up", "price_down"):
        value = _bounded_strength(price_change, scale)
        if value is not None:
            strengths[key] = value
            measured.add(key)

    level_pairs = {
        "donchian_breakout": ("donchian", "upper20"),
        "donchian_breakdown": ("donchian", "lower20"),
        "structure_support_break": ("support_resistance", "support20"),
        "structure_resistance_breakout": (
            "support_resistance",
            "resistance20",
        ),
        "near_support": ("support_resistance", "support20"),
        "near_resistance": ("support_resistance", "resistance20"),
        "bollinger_breakout": ("bollinger", "upper20"),
        "bollinger_breakdown": ("bollinger", "lower20"),
    }
    for key, (group, field) in level_pairs.items():
        level = _indicator_number(item, group, field)
        set_distance(key, close, level)
        if key in {"near_support", "near_resistance"} and key in measured:
            strengths[key] = max(0.2, 1.0 - strengths[key])

    histogram = _indicator_number(item, "macd", "histogram")
    for key in ("macd_positive", "macd_negative"):
        value = _bounded_strength(histogram, scale)
        if value is not None:
            strengths[key] = value
            measured.add(key)

    adx = _indicator_number(item, "adx", "adx14")
    plus_di = _indicator_number(item, "adx", "plus_di14")
    minus_di = _indicator_number(item, "adx", "minus_di14")
    if adx is not None:
        directional_gap = (
            abs(plus_di - minus_di)
            if plus_di is not None and minus_di is not None
            else 0.0
        )
        value = max(
            0.2,
            min(
                1.0,
                max(0.0, adx - 20.0) / 20.0
                + directional_gap / 100.0,
            ),
        )
        for key in ("adx_bull_trend", "adx_bear_trend"):
            strengths[key] = value
            measured.add(key)

    bounded_indicators = {
        "rsi_bull_zone": ("rsi", "rsi14", 50.0, 20.0),
        "rsi_weak": ("rsi", "rsi14", 50.0, 20.0),
        "rsi_overheated": ("rsi", "rsi14", 70.0, 15.0),
        "mfi_inflow": ("mfi", "mfi14", 50.0, 20.0),
        "mfi_outflow": ("mfi", "mfi14", 50.0, 20.0),
        "roc_positive": ("roc", "roc12", 0.0, 10.0),
        "roc_negative": ("roc", "roc12", 0.0, 10.0),
    }
    for key, (group, field, center, denominator) in bounded_indicators.items():
        raw_value = _indicator_number(item, group, field)
        if raw_value is not None:
            strengths[key] = max(
                0.2,
                min(1.0, abs(raw_value - center) / denominator),
            )
            measured.add(key)

    k_value = _indicator_number(item, "kd", "k9")
    d_value = _indicator_number(item, "kd", "d9")
    for key in ("kd_bullish_cross", "kd_bearish_cross"):
        if k_value is not None and d_value is not None:
            strengths[key] = max(
                0.2,
                min(1.0, abs(k_value - d_value) / 20.0),
            )
            measured.add(key)
    for key, boundary in (("kd_overbought", 80.0), ("kd_oversold", 20.0)):
        if k_value is not None:
            strengths[key] = max(
                0.2,
                min(1.0, abs(k_value - boundary) / 20.0),
            )
            measured.add(key)

    volume = _number(item.get("volume"))
    volume_ma5 = _indicator_number(item, "volume_ma", "volume_ma5")
    if volume is not None and volume_ma5 is not None and volume_ma5 > 0:
        volume_ratio = volume / volume_ma5
        value = max(0.2, min(1.0, abs(volume_ratio - 1.0)))
        for key in (
            "volume_price_up",
            "volume_price_down",
            "volume_expansion",
            "volume_above_ma5",
        ):
            strengths[key] = value
            measured.add(key)

    bandwidth = _indicator_number(item, "bollinger", "bandwidth20_pct")
    if bandwidth is not None:
        strengths["bollinger_squeeze"] = max(
            0.2,
            min(1.0, max(0.0, 12.0 - bandwidth) / 8.0),
        )
        measured.add("bollinger_squeeze")
    if atr is not None and close not in {None, 0}:
        atr_pct = atr / abs(close) * 100.0
        strengths["atr_high_volatility"] = max(
            0.2,
            min(1.0, atr_pct / 8.0),
        )
        strengths["atr_expanding"] = max(
            0.2,
            min(1.0, atr_pct / 6.0),
        )
        measured.update({"atr_high_volatility", "atr_expanding"})

    unmeasured = sorted(set(signal_keys) - measured)
    return strengths, unmeasured


def _timeframe_conflict(
    *,
    item: Mapping[str, Any],
    signal_keys: list[str],
) -> tuple[float, bool]:
    context = item.get("context_snapshot")
    intraday = context.get("intraday") if isinstance(context, Mapping) else None
    if not isinstance(intraday, Mapping):
        return 0.0, False
    intraday_change = _number(
        intraday.get("session_change_pct", intraday.get("change_pct"))
    )
    if intraday_change in {None, 0}:
        return 0.0, True
    directional_vote = sum(
        int(RADAR_V2_SIGNAL_DEFINITIONS.get(key, {}).get("direction") or 0)
        for key in signal_keys
    )
    if directional_vote == 0 or directional_vote * intraday_change >= 0:
        return 0.0, True
    return min(1.0, abs(intraday_change) / 5.0), True


def evaluate_radar_v2_item(
    *,
    item: Mapping[str, Any],
    market_regime: Mapping[str, Any],
    contract: Mapping[str, Any] = RADAR_V2_SHADOW_CONTRACT,
) -> dict[str, Any]:
    signal_keys = [
        str(key)
        for key in item.get("signal_keys") or []
        if str(key or "").strip()
    ]
    quality = _data_quality(item)
    instrument = classify_instrument_regime(
        indicator_snapshot=(
            item.get("indicator_snapshot")
            if isinstance(item.get("indicator_snapshot"), Mapping)
            else {}
        ),
        signal_keys=signal_keys,
        close_price=_number(item.get("close")),
        config=contract["rule_config"]["regime"],
    )
    combined_clarity = combined_regime_clarity(
        instrument_regime_clarity=float(
            instrument["instrument_regime_clarity"]
        ),
        market_regime_clarity=_number(
            market_regime.get("market_regime_clarity")
        ),
        config=contract["rule_config"]["regime"],
    )
    strengths, unmeasured_strengths = _signal_strengths(
        item=item,
        signal_keys=signal_keys,
    )
    freshness_by_signal = {
        key: float(quality["freshness_score"])
        for key in signal_keys
    }
    timeframe_conflict_score, timeframe_observed = _timeframe_conflict(
        item=item,
        signal_keys=signal_keys,
    )
    scoring = score_radar_signals(
        signal_keys=signal_keys,
        strengths=strengths,
        freshness_by_signal=freshness_by_signal,
        data_quality_score=float(quality["data_quality_score"]),
        regime_clarity=combined_clarity,
        timeframe_conflict_score=timeframe_conflict_score,
        urgency=(
            None
            if contract.get("mode") == "active"
            else str(item.get("urgency") or "low")
        ),
        context_alignment_score=(
            _active_context_alignment(item)
            if contract.get("mode") == "active"
            else _context_alignment(item)
        ),
        config=scoring_config_for_instrument_regime(
            str(instrument["instrument_regime"]),
            scoring_config=contract["scoring_config"],
            regime_config=contract["rule_config"]["regime"],
        ),
    )
    limitations = [
        *quality["limitations"],
        *instrument["limitations"],
        *market_regime.get("limitations", []),
        *scoring["limitations"],
    ]
    if unmeasured_strengths:
        limitations.append(
            {
                "code": "signal_strength_defaulted",
                "default": 0.5,
                "signal_keys": unmeasured_strengths,
            }
        )
    if not timeframe_observed:
        limitations.append(
            {
                "code": "timeframe_conflict_not_observed",
            }
        )
    return {
        **scoring,
        "rule_version": str(contract["rule_version"]),
        "rule_config_hash": str(contract["rule_config_hash"]),
        "feature_version": str(contract["feature_version"]),
        "feature_config_hash": str(contract["feature_config_hash"]),
        "instrument_regime": instrument["instrument_regime"],
        "instrument_regime_clarity": instrument[
            "instrument_regime_clarity"
        ],
        "market_regime": market_regime["market_regime"],
        "market_regime_clarity": market_regime[
            "market_regime_clarity"
        ],
        "combined_regime_clarity": combined_clarity,
        "volatility_state": instrument["volatility_state"],
        "data_status": quality["data_status"],
        "freshness_status": quality["freshness_status"],
        "data_quality_score": quality["data_quality_score"],
        "limitations": limitations,
    }


def _shadow_item(
    *,
    item: Mapping[str, Any],
    market_regime: Mapping[str, Any],
) -> dict[str, Any]:
    return evaluate_radar_v2_item(
        item=item,
        market_regime=market_regime,
        contract=RADAR_V2_SHADOW_CONTRACT,
    )


def attach_radar_v2_shadow(
    *,
    radar: Mapping[str, Any],
    market_snapshot: Mapping[str, Any] | None = None,
    universe_items: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = deepcopy(dict(radar))
    market_regime = classify_market_regime(market_snapshot=market_snapshot)
    source_universe = list(universe_items or payload.get("results") or [])
    evaluated_universe: list[dict[str, Any]] = []
    shadow_by_stock: dict[str, dict[str, Any]] = {}
    for raw_item in source_universe:
        if not isinstance(raw_item, Mapping):
            continue
        item = deepcopy(dict(raw_item))
        shadow = _shadow_item(item=item, market_regime=market_regime)
        shadow["market_snapshot"] = dict(market_snapshot or {})
        item["radar_v2"] = shadow
        evaluated_universe.append(item)
        stock_id = str(item.get("stock_id") or "")
        if stock_id:
            shadow_by_stock[stock_id] = shadow

    results: list[dict[str, Any]] = []
    direction_changed_count = 0
    bucket_changed_count = 0
    conflict_count = 0
    insufficient_count = 0
    for raw_item in payload.get("results") or []:
        if not isinstance(raw_item, Mapping):
            continue
        item = dict(raw_item)
        stock_id = str(item.get("stock_id") or "")
        shadow = shadow_by_stock.get(stock_id)
        if shadow is None:
            shadow = _shadow_item(item=item, market_regime=market_regime)
            shadow["market_snapshot"] = dict(market_snapshot or {})
        item["radar_v2"] = shadow
        v1_direction = str(item.get("direction") or "neutral")
        v2_direction = int(shadow["direction"])
        comparable_v1_direction = (
            1
            if v1_direction == "bullish"
            else -1
            if v1_direction == "bearish"
            else 0
        )
        direction_changed_count += int(comparable_v1_direction != v2_direction)
        bucket_changed_count += int(
            str(item.get("bucket") or "") != str(shadow["primary_bucket"])
        )
        conflict_count += int(float(shadow["conflict_score"]) >= 30.0)
        insufficient_count += int(shadow["evidence_grade"] == "insufficient")
        results.append(item)
    payload["results"] = results
    payload["radar_engine"] = {
        "active_version": RADAR_V1_RULE_VERSION,
        "shadow_version": RADAR_V2_RULE_VERSION,
        "shadow_config_hash": RADAR_V2_RULE_CONFIG_HASH,
        "mode": "shadow",
        "rollback_version": RADAR_V1_RULE_VERSION,
        "technical_direction_owner": "backend",
    }
    payload["radar_v2_summary"] = {
        "evaluated_count": len(results),
        "universe_evaluated_count": len(evaluated_universe),
        "universe_scope": (
            "complete_calculation_universe"
            if universe_items is not None
            else "presentation_results_fallback"
        ),
        "direction_changed_count": direction_changed_count,
        "bucket_changed_count": bucket_changed_count,
        "conflict_count": conflict_count,
        "insufficient_count": insufficient_count,
        "market_regime": market_regime["market_regime"],
        "market_regime_clarity": market_regime[
            "market_regime_clarity"
        ],
        "market_limitations": market_regime["limitations"],
        "market_snapshot": dict(market_snapshot or {}),
    }
    payload["_radar_v2_universe"] = evaluated_universe
    return payload


def attach_radar_v2_shadow_from_db(
    *,
    db: Session,
    radar: Mapping[str, Any],
    universe_items: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    signal_trade_date = _trade_date(
        radar.get("trade_date") or radar.get("target_trade_date")
    )
    point_in_time_items = list(universe_items or radar.get("results") or [])
    effective_times = [
        _effective_at(item, signal_trade_date)
        for item in point_in_time_items
        if isinstance(item, Mapping) and signal_trade_date is not None
    ]
    as_of_at = min(effective_times) if effective_times else None
    market_snapshot = latest_market_regime_snapshot(
        db=db,
        signal_trade_date=signal_trade_date,
        as_of_at=as_of_at,
    )
    if (
        market_snapshot is not None
        and signal_trade_date is not None
        and market_snapshot.get("trade_date") != signal_trade_date.isoformat()
    ):
        market_snapshot = {
            **market_snapshot,
            "quality_status": "stale",
        }
    return attach_radar_v2_shadow(
        radar=radar,
        market_snapshot=market_snapshot,
        universe_items=universe_items,
    )


def _feature_identity(
    *,
    item: Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    manifest = {
        "market": "TW",
        "stock_id": str(item.get("stock_id") or ""),
        "trade_date": str(item.get("trade_date") or item.get("time") or "")[:10],
        "effective_time_input": str(item.get("time") or ""),
        "close": _number(item.get("close")),
        "previous_close": _number(item.get("previous_close")),
        "volume": item.get("volume"),
        "signal_keys": sorted(
            {
                str(key)
                for key in item.get("signal_keys") or []
                if str(key or "").strip()
            }
        ),
        "indicator_snapshot": item.get("indicator_snapshot") or {},
    }
    return manifest, config_hash(manifest)


def _upsert_feature(
    *,
    db: Session,
    item: Mapping[str, Any],
    shadow: Mapping[str, Any],
    now: datetime,
    market_data_revision: str | None,
) -> tuple[RadarFeatureSnapshot | None, bool]:
    signal_trade_date = _trade_date(
        item.get("trade_date") or item.get("time")
    )
    stock_id = str(item.get("stock_id") or "").strip()
    if signal_trade_date is None or not stock_id:
        return None, False
    manifest, manifest_hash = _feature_identity(
        item=item,
    )
    feature_version = str(shadow["feature_version"])
    feature_config_hash = str(shadow["feature_config_hash"])
    feature_basis = (
        "intraday_provisional"
        if shadow.get("freshness_status") == "provisional"
        else "daily_final"
    )
    row = (
        db.query(RadarFeatureSnapshot)
        .filter(RadarFeatureSnapshot.market == "TW")
        .filter(RadarFeatureSnapshot.stock_id == stock_id)
        .filter(
            RadarFeatureSnapshot.signal_trade_date == signal_trade_date
        )
        .filter(RadarFeatureSnapshot.feature_basis == feature_basis)
        .filter(
            RadarFeatureSnapshot.feature_version
            == feature_version
        )
        .filter(
            RadarFeatureSnapshot.feature_config_hash
            == feature_config_hash
        )
        .filter(
            RadarFeatureSnapshot.input_manifest_hash == manifest_hash
        )
        .one_or_none()
    )
    if row is not None:
        return row, False

    indicator_snapshot = item.get("indicator_snapshot") or {}
    atr = (
        indicator_snapshot.get("atr")
        if isinstance(indicator_snapshot, Mapping)
        else {}
    )
    signal_atr = (
        _number(atr.get("atr14"))
        if isinstance(atr, Mapping)
        else None
    )
    effective_at = _effective_at(item, signal_trade_date)
    source_available_at, source_time_inferred = _source_available_at(
        item,
        observed_at=now,
    )
    limitations = list(shadow.get("limitations") or [])
    if source_time_inferred:
        limitations.append(
            {
                "code": "source_available_at_inferred_from_observed_at",
                "fallback": "observed_at",
            }
        )
    row = RadarFeatureSnapshot(
        market="TW",
        stock_id=stock_id,
        stock_name=item.get("stock_name"),
        signal_trade_date=signal_trade_date,
        effective_at=effective_at,
        available_at=source_available_at,
        source_available_at=source_available_at,
        observed_at=now,
        feature_basis=feature_basis,
        source_timeframe="intraday"
        if feature_basis == "intraday_provisional"
        else "daily",
        feature_version=feature_version,
        feature_config_hash=feature_config_hash,
        input_manifest_hash=manifest_hash,
        market_data_revision=market_data_revision,
        data_status=str(shadow.get("data_status") or "partial"),
        freshness_status=str(
            shadow.get("freshness_status") or "unknown"
        ),
        freshness_score=float(
            _data_quality(item)["freshness_score"]
        ),
        completeness_score=float(
            _data_quality(item)["completeness_score"]
        ),
        source_quality_score=float(
            _data_quality(item)["source_quality_score"]
        ),
        data_quality_score=float(
            shadow.get("data_quality_score") or 0
        ),
        is_provisional=feature_basis == "intraday_provisional",
        is_stale=bool(item.get("stale")),
        close_price=_number(item.get("close")),
        previous_close=_number(item.get("previous_close")),
        volume=(
            int(item["volume"])
            if _number(item.get("volume")) is not None
            else None
        ),
        signal_atr=signal_atr,
        features_json=json_dumps(indicator_snapshot),
        signals_json=json_dumps(item.get("signal_keys") or []),
        input_manifest_json=json_dumps(manifest),
        data_limitations_json=json_dumps(
            limitations
        ),
    )
    db.add(row)
    db.flush()
    return row, True


def _upsert_evaluation(
    *,
    db: Session,
    feature: RadarFeatureSnapshot,
    item: Mapping[str, Any],
    shadow: Mapping[str, Any],
    now: datetime,
) -> tuple[RadarRuleEvaluation, bool]:
    rule_version = str(shadow["rule_version"])
    rule_config_hash = str(shadow["rule_config_hash"])
    row = (
        db.query(RadarRuleEvaluation)
        .filter(
            RadarRuleEvaluation.feature_snapshot_id == feature.id
        )
        .filter(
            RadarRuleEvaluation.rule_version == rule_version
        )
        .filter(
            RadarRuleEvaluation.rule_config_hash
            == rule_config_hash
        )
        .one_or_none()
    )
    if row is not None:
        return row, False

    row = RadarRuleEvaluation(
        feature_snapshot_id=feature.id,
        rule_version=rule_version,
        rule_config_hash=rule_config_hash,
        stock_id=feature.stock_id,
        signal_trade_date=feature.signal_trade_date,
        direction=int(shadow["direction"]),
        direction_score=float(shadow["direction_score"]),
        evidence_score=float(shadow["evidence_score"]),
        within_family_conflict_score=float(
            shadow["within_family_conflict_score"]
        ),
        cross_family_conflict_score=float(
            shadow["cross_family_conflict_score"]
        ),
        timeframe_conflict_score=float(
            shadow["timeframe_conflict_score"]
        ),
        conflict_score=float(shadow["conflict_score"]),
        risk_score=float(shadow["risk_score"]),
        confidence_score=float(shadow["confidence_score"]),
        priority_score=float(shadow["priority_score"]),
        context_alignment_score=float(
            shadow["context_alignment_score"]
        ),
        primary_bucket=str(shadow["primary_bucket"]),
        urgency=str(shadow["urgency"]),
        evidence_grade=str(shadow["evidence_grade"]),
        instrument_regime=str(shadow["instrument_regime"]),
        market_regime=str(shadow["market_regime"]),
        instrument_regime_clarity=float(
            shadow["instrument_regime_clarity"]
        ),
        market_regime_clarity=float(
            shadow["market_regime_clarity"]
        ),
        state_tags_json=json_dumps(shadow["state_tags"]),
        risk_tags_json=json_dumps(shadow["risk_tags"]),
        family_scores_json=json_dumps(shadow["family_scores"]),
        signal_contributions_json=json_dumps(
            shadow["signal_contributions"]
        ),
        context_json=json_dumps(
            {
                "context_snapshot": item.get("context_snapshot") or {},
                "context_signals": item.get("context_signals") or [],
                "context_alignment_score": shadow[
                    "context_alignment_score"
                ],
                "market_snapshot": shadow.get("market_snapshot") or {},
            }
        ),
        limitations_json=json_dumps(shadow["limitations"]),
        raw_evaluation_json=json_dumps(shadow),
        decision_at=max(
            _utc_comparable(feature.effective_at),
            _utc_comparable(feature.source_available_at),
        ),
        evaluated_at=now,
    )
    db.add(row)
    db.flush()
    return row, True


def _upsert_events(
    *,
    db: Session,
    feature: RadarFeatureSnapshot,
    evaluation: RadarRuleEvaluation,
    shadow: Mapping[str, Any],
) -> tuple[int, int, int]:
    rule_version = evaluation.rule_version
    rule_config_hash = evaluation.rule_config_hash
    active_contributions = [
        contribution
        for contribution in shadow.get("signal_contributions") or []
        if contribution.get("signal_type") == "event"
        and int(contribution.get("direction") or 0) != 0
    ]
    active_identities = {
        (
            str(contribution["signal_key"]),
            int(contribution["direction"]),
        )
        for contribution in active_contributions
    }
    open_events = (
        db.query(RadarSignalEvent)
        .filter(RadarSignalEvent.market == feature.market)
        .filter(RadarSignalEvent.stock_id == feature.stock_id)
        .filter(RadarSignalEvent.rule_version == rule_version)
        .filter(
            RadarSignalEvent.rule_config_hash
            == rule_config_hash
        )
        .filter(RadarSignalEvent.status.in_(("active", "unobserved")))
        .all()
    )
    created_count = 0
    updated_count = 0
    for event in open_events:
        if (event.event_key, event.direction) in active_identities:
            continue
        event.status = "exited"
        event.observation_status = "observed_inactive"
        event.last_observed_trade_date = feature.signal_trade_date
        event.exit_trade_date = feature.signal_trade_date
        event.updated_at = utc_now()
        updated_count += 1

    same_onset_events = (
        db.query(RadarSignalEvent)
        .filter(RadarSignalEvent.market == feature.market)
        .filter(RadarSignalEvent.stock_id == feature.stock_id)
        .filter(RadarSignalEvent.rule_version == rule_version)
        .filter(RadarSignalEvent.rule_config_hash == rule_config_hash)
        .filter(RadarSignalEvent.onset_trade_date == feature.signal_trade_date)
        .all()
    )
    by_identity = {
        (event.event_key, event.direction): event
        for event in (*same_onset_events, *open_events)
    }
    for contribution in active_contributions:
        event_key = str(contribution["signal_key"])
        direction = int(contribution["direction"])
        event = by_identity.get((event_key, direction))
        if event is not None:
            was_inactive = event.status != "active"
            event.status = "active"
            event.observation_status = "observed_active"
            event.last_observed_trade_date = feature.signal_trade_date
            event.exit_trade_date = None
            if event.last_active_trade_date < feature.signal_trade_date:
                event.persistence_trading_days += 1
                event.last_active_trade_date = feature.signal_trade_date
            if was_inactive:
                event.retrigger_count += 1
            event.latest_evaluation_id = evaluation.id
            event.event_metadata_json = json_dumps(
                {
                    "latest_contribution": contribution,
                    "observation_basis": "explicit_radar_v2_persist",
                }
            )
            updated_count += 1
            continue
        event = RadarSignalEvent(
            market=feature.market,
            stock_id=feature.stock_id,
            event_key=event_key,
            family=str(contribution["family"]),
            direction=direction,
            signal_type="event",
            status="active",
            rule_version=rule_version,
            rule_config_hash=rule_config_hash,
            onset_feature_snapshot_id=feature.id,
            onset_evaluation_id=evaluation.id,
            latest_evaluation_id=evaluation.id,
            onset_trade_date=feature.signal_trade_date,
            last_active_trade_date=feature.signal_trade_date,
            last_observed_trade_date=feature.signal_trade_date,
            observation_status="observed_active",
            persistence_trading_days=1,
            retrigger_count=0,
            event_metadata_json=json_dumps(
                {
                    "onset_contribution": contribution,
                    "observation_basis": "explicit_radar_v2_persist",
                }
            ),
        )
        db.add(event)
        by_identity[(event_key, direction)] = event
        created_count += 1
    db.flush()
    linked_count = 0
    for contribution in active_contributions:
        event = by_identity[
            (
                str(contribution["signal_key"]),
                int(contribution["direction"]),
            )
        ]
        link = (
            db.query(RadarEvaluationEventLink)
            .filter(
                RadarEvaluationEventLink.evaluation_id == evaluation.id
            )
            .filter(
                RadarEvaluationEventLink.signal_event_id == event.id
            )
            .one_or_none()
        )
        if link is None:
            db.add(
                RadarEvaluationEventLink(
                    evaluation_id=evaluation.id,
                    signal_event_id=event.id,
                    relation="active",
                    contribution_json=json_dumps(contribution),
                )
            )
            linked_count += 1
    db.flush()
    return created_count, updated_count, linked_count


def _upsert_universe_observation(
    *,
    db: Session,
    group_id: int,
    mode: str,
    snapshot_date: date,
    item: Mapping[str, Any],
    evaluation: RadarRuleEvaluation | None,
    selected: bool,
    universe_scope: str,
    observed_at: datetime,
    rule_version: str,
    rule_config_hash: str,
    reason: str | None = None,
) -> RadarUniverseObservation | None:
    stock_id = str(item.get("stock_id") or "").strip()
    if not stock_id:
        return None
    if evaluation is not None:
        observation_status = "evaluated"
    else:
        raw_status = str(item.get("status") or "unknown")
        observation_status = (
            raw_status
            if raw_status in {"error", "no_data"}
            else "unevaluated"
        )
    row = (
        db.query(RadarUniverseObservation)
        .filter(RadarUniverseObservation.group_id == group_id)
        .filter(RadarUniverseObservation.mode == mode)
        .filter(
            RadarUniverseObservation.snapshot_date == snapshot_date
        )
        .filter(RadarUniverseObservation.stock_id == stock_id)
        .filter(
            RadarUniverseObservation.rule_version
            == rule_version
        )
        .filter(
            RadarUniverseObservation.rule_config_hash
            == rule_config_hash
        )
        .one_or_none()
    )
    values = {
        "market": "TW",
        "stock_name": item.get("stock_name"),
        "observation_status": observation_status,
        "selected": selected,
        "evaluation_id": evaluation.id if evaluation is not None else None,
        "source_rank": (
            int(item["source_rank"])
            if _number(item.get("source_rank")) is not None
            else None
        ),
        "reason": reason or item.get("error_message"),
        "universe_scope": universe_scope,
        "observed_at": observed_at,
    }
    if row is None:
        row = RadarUniverseObservation(
            group_id=group_id,
            mode=mode,
            snapshot_date=snapshot_date,
            stock_id=stock_id,
            rule_version=rule_version,
            rule_config_hash=rule_config_hash,
            **values,
        )
        db.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
        row.updated_at = utc_now()
    db.flush()
    return row


def _mark_stock_events_unobserved(
    *,
    db: Session,
    stock_id: str,
    snapshot_date: date,
    rule_version: str,
    rule_config_hash: str,
) -> int:
    evaluated_elsewhere = (
        db.query(RadarUniverseObservation.id)
        .filter(
            RadarUniverseObservation.snapshot_date == snapshot_date
        )
        .filter(RadarUniverseObservation.stock_id == stock_id)
        .filter(
            RadarUniverseObservation.rule_version
            == rule_version
        )
        .filter(
            RadarUniverseObservation.rule_config_hash
            == rule_config_hash
        )
        .filter(
            RadarUniverseObservation.observation_status == "evaluated"
        )
        .first()
    )
    if evaluated_elsewhere is not None:
        return 0
    events = (
        db.query(RadarSignalEvent)
        .filter(RadarSignalEvent.market == "TW")
        .filter(RadarSignalEvent.stock_id == stock_id)
        .filter(RadarSignalEvent.rule_version == rule_version)
        .filter(
            RadarSignalEvent.rule_config_hash
            == rule_config_hash
        )
        .filter(RadarSignalEvent.status == "active")
        .all()
    )
    for event in events:
        event.status = "unobserved"
        event.observation_status = "missing_observation"
        event.last_observed_trade_date = snapshot_date
        event.updated_at = utc_now()
    return len(events)


def _record_absent_previous_scope_stocks(
    *,
    db: Session,
    group_id: int,
    mode: str,
    snapshot_date: date,
    current_stock_ids: set[str],
    universe_scope: str,
    observed_at: datetime,
    rule_version: str,
    rule_config_hash: str,
) -> tuple[int, int]:
    if universe_scope != "complete_calculation_universe":
        return 0, 0
    previous_date = (
        db.query(func.max(RadarUniverseObservation.snapshot_date))
        .filter(RadarUniverseObservation.group_id == group_id)
        .filter(RadarUniverseObservation.mode == mode)
        .filter(
            RadarUniverseObservation.snapshot_date < snapshot_date
        )
        .filter(
            RadarUniverseObservation.rule_version
            == rule_version
        )
        .filter(
            RadarUniverseObservation.rule_config_hash
            == rule_config_hash
        )
        .scalar()
    )
    if previous_date is None:
        return 0, 0
    previous_rows = (
        db.query(RadarUniverseObservation)
        .filter(RadarUniverseObservation.group_id == group_id)
        .filter(RadarUniverseObservation.mode == mode)
        .filter(
            RadarUniverseObservation.snapshot_date == previous_date
        )
        .filter(
            RadarUniverseObservation.rule_version
            == rule_version
        )
        .filter(
            RadarUniverseObservation.rule_config_hash
            == rule_config_hash
        )
        .all()
    )
    absent_ids = sorted(
        {
            row.stock_id
            for row in previous_rows
            if row.stock_id not in current_stock_ids
            and row.observation_status != "absent"
        }
    )
    unobserved_event_count = 0
    for stock_id in absent_ids:
        _upsert_universe_observation(
            db=db,
            group_id=group_id,
            mode=mode,
            snapshot_date=snapshot_date,
            item={"stock_id": stock_id, "status": "absent"},
            evaluation=None,
            selected=False,
            universe_scope=universe_scope,
            observed_at=observed_at,
            rule_version=rule_version,
            rule_config_hash=rule_config_hash,
            reason="absent_from_current_calculation_universe",
        )
        row = (
            db.query(RadarUniverseObservation)
            .filter(RadarUniverseObservation.group_id == group_id)
            .filter(RadarUniverseObservation.mode == mode)
            .filter(
                RadarUniverseObservation.snapshot_date == snapshot_date
            )
            .filter(RadarUniverseObservation.stock_id == stock_id)
            .filter(
                RadarUniverseObservation.rule_version == rule_version
            )
            .filter(
                RadarUniverseObservation.rule_config_hash
                == rule_config_hash
            )
            .one()
        )
        row.observation_status = "absent"
        unobserved_event_count += _mark_stock_events_unobserved(
            db=db,
            stock_id=stock_id,
            snapshot_date=snapshot_date,
            rule_version=rule_version,
            rule_config_hash=rule_config_hash,
        )
    db.flush()
    return len(absent_ids), unobserved_event_count


def _upsert_projection(
    *,
    db: Session,
    evaluation: RadarRuleEvaluation,
    item: Mapping[str, Any],
    group_id: int,
    mode: str,
    snapshot_date: date,
    snapshot_run_id: int | None,
    projection_meta: Mapping[str, Any],
) -> bool:
    row = (
        db.query(RadarWatchlistProjection)
        .filter(
            RadarWatchlistProjection.evaluation_id == evaluation.id
        )
        .filter(RadarWatchlistProjection.group_id == group_id)
        .filter(RadarWatchlistProjection.mode == mode)
        .filter(
            RadarWatchlistProjection.snapshot_date == snapshot_date
        )
        .one_or_none()
    )
    values = {
        "snapshot_run_id": snapshot_run_id,
        "rank": int(item.get("rank") or 0),
        "selected": True,
        "projection_json": json_dumps(
            {
                "v1_bucket": item.get("bucket"),
                "v1_priority_score": item.get("priority_score"),
                "v2_bucket": evaluation.primary_bucket,
                "v2_priority_score": evaluation.priority_score,
                "item": dict(item),
                "radar_meta": dict(projection_meta),
            }
        ),
    }
    if row is None:
        db.add(
            RadarWatchlistProjection(
                evaluation_id=evaluation.id,
                group_id=group_id,
                mode=mode,
                snapshot_date=snapshot_date,
                **values,
            )
        )
        return True
    for key, value in values.items():
        setattr(row, key, value)
    return False


def _upsert_v2_snapshot_run(
    *,
    db: Session,
    radar: Mapping[str, Any],
    group_id: int,
    mode: str,
    snapshot_date: date,
    rule_version: str,
) -> WatchlistRadarSnapshotRun:
    include_children = bool(radar.get("include_children", True))
    enabled_only = True
    row = (
        db.query(WatchlistRadarSnapshotRun)
        .filter(WatchlistRadarSnapshotRun.group_id == group_id)
        .filter(WatchlistRadarSnapshotRun.mode == mode)
        .filter(WatchlistRadarSnapshotRun.snapshot_date == snapshot_date)
        .filter(
            WatchlistRadarSnapshotRun.radar_rule_version
            == rule_version
        )
        .filter(
            WatchlistRadarSnapshotRun.include_children
            == include_children
        )
        .filter(
            WatchlistRadarSnapshotRun.enabled_only == enabled_only
        )
        .one_or_none()
    )
    values = {
        "max_results": int(radar.get("max_results") or 30),
        "calculation_limit": int(
            radar.get("calculation_limit") or 100
        ),
        "trade_date": _trade_date(radar.get("trade_date")),
        "target_trade_date": _trade_date(
            radar.get("target_trade_date")
        ),
        "is_current": bool(radar.get("is_current", True)),
        "current_stock_count": int(
            radar.get("current_stock_count") or 0
        ),
        "stale_stock_count": int(
            radar.get("stale_stock_count") or 0
        ),
        "requested_stock_count": int(
            radar.get("requested_stock_count") or 0
        ),
        "ranked_count": int(radar.get("ranked_count") or 0),
        "matched_count": int(radar.get("matched_count") or 0),
        "radar_count": int(radar.get("radar_count") or 0),
        "no_data_count": int(radar.get("no_data_count") or 0),
        "error_count": int(radar.get("error_count") or 0),
        "buckets_json": json_dumps(radar.get("buckets") or []),
        "data_limitations_json": json_dumps(
            radar.get("data_limitations") or []
        ),
        "request_json": json_dumps(
            {
                "contract": "radar_v2_active",
                "rule_version": rule_version,
                "radar_engine": radar.get("radar_engine") or {},
                "radar_v2_summary": radar.get("radar_v2_summary") or {},
            }
        ),
    }
    if row is None:
        row = WatchlistRadarSnapshotRun(
            group_id=group_id,
            include_children=include_children,
            enabled_only=enabled_only,
            mode=mode,
            snapshot_date=snapshot_date,
            radar_rule_version=rule_version,
            **values,
        )
        db.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
        row.updated_at = utc_now()
    db.flush()
    return row


def persist_radar_v2(
    *,
    db: Session,
    radar: Mapping[str, Any],
    group_id: int,
    mode: str,
    snapshot_run_id: int | None = None,
    now: datetime | None = None,
    contract: Mapping[str, Any] = RADAR_V2_SHADOW_CONTRACT,
) -> dict[str, Any]:
    observed_at = now or utc_now()
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    if radar.get("radar_engine"):
        attached = dict(radar)
    elif contract.get("mode") == "shadow":
        attached = attach_radar_v2_shadow_from_db(db=db, radar=radar)
    else:
        raise ValueError(
            "Radar v2 active persistence requires an attached active projection."
        )
    snapshot_date = _trade_date(
        attached.get("trade_date") or attached.get("target_trade_date")
    )
    if snapshot_date is None:
        raise ValueError("Radar v2 shadow persistence requires a trade date.")
    market_summary = attached.get("radar_v2_summary") or {}
    universe_scope = str(
        market_summary.get("universe_scope")
        or "presentation_results_fallback"
    )
    universe_items = list(
        attached.get("_radar_v2_universe")
        or attached.get("results")
        or []
    )
    selected_by_stock = {
        str(item.get("stock_id") or ""): item
        for item in attached.get("results") or []
        if isinstance(item, Mapping) and item.get("stock_id")
    }
    rule_version = str(contract["rule_version"])
    rule_config_hash = str(contract["rule_config_hash"])
    projection_meta = {
        key: value
        for key, value in attached.items()
        if key
        in {
            "group_id",
            "include_children",
            "mode",
            "max_results",
            "requested_stock_count",
            "ranked_count",
            "matched_count",
            "radar_count",
            "no_data_count",
            "error_count",
            "trade_date",
            "target_trade_date",
            "is_current",
            "current_stock_count",
            "stale_stock_count",
            "buckets",
            "data_limitations",
            "radar_engine",
            "radar_v2_summary",
        }
    }

    try:
        if contract.get("mode") == "active":
            snapshot_run = _upsert_v2_snapshot_run(
                db=db,
                radar=attached,
                group_id=group_id,
                mode=mode,
                snapshot_date=snapshot_date,
                rule_version=rule_version,
            )
            snapshot_run_id = int(snapshot_run.id)
        ensure_rule_config(
            db=db,
            contract_type="rule",
            version=rule_version,
            config_hash=rule_config_hash,
            config=dict(contract["rule_config"]),
            status=str(contract.get("status") or "shadow"),
            description=(
                "Radar v2 scoring, regime, conflict, risk, confidence, "
                "and public projection contract."
            ),
        )
        existing_projections = (
            db.query(RadarWatchlistProjection)
            .join(
                RadarRuleEvaluation,
                RadarRuleEvaluation.id
                == RadarWatchlistProjection.evaluation_id,
            )
            .filter(RadarWatchlistProjection.group_id == group_id)
            .filter(RadarWatchlistProjection.mode == mode)
            .filter(
                RadarWatchlistProjection.snapshot_date == snapshot_date
            )
            .filter(
                RadarRuleEvaluation.rule_version == rule_version
            )
            .filter(
                RadarRuleEvaluation.rule_config_hash
                == rule_config_hash
            )
            .all()
        )
        for projection in existing_projections:
            projection.selected = False
        feature_created_count = 0
        evaluation_created_count = 0
        projection_created_count = 0
        event_created_count = 0
        event_updated_count = 0
        event_link_created_count = 0
        event_unobserved_count = 0
        observation_status_counts: dict[str, int] = {}
        skipped: list[dict[str, Any]] = []
        evaluation_ids: list[int] = []
        current_stock_ids: set[str] = set()
        for item in universe_items:
            if not isinstance(item, Mapping):
                continue
            stock_id = str(item.get("stock_id") or "").strip()
            if stock_id:
                current_stock_ids.add(stock_id)
            selected_item = selected_by_stock.get(stock_id)
            shadow = item.get("radar_v2")
            raw_status = str(item.get("status") or "unknown")
            if raw_status in {"error", "no_data"}:
                observation = _upsert_universe_observation(
                    db=db,
                    group_id=group_id,
                    mode=mode,
                    snapshot_date=snapshot_date,
                    item=item,
                    evaluation=None,
                    selected=selected_item is not None,
                    universe_scope=universe_scope,
                    observed_at=observed_at,
                    rule_version=rule_version,
                    rule_config_hash=rule_config_hash,
                    reason=item.get("error_message"),
                )
                if observation is not None:
                    observation_status_counts[observation.observation_status] = (
                        observation_status_counts.get(
                            observation.observation_status,
                            0,
                        )
                        + 1
                    )
                if stock_id:
                    event_unobserved_count += _mark_stock_events_unobserved(
                        db=db,
                        stock_id=stock_id,
                        snapshot_date=snapshot_date,
                        rule_version=rule_version,
                        rule_config_hash=rule_config_hash,
                    )
                skipped.append(
                    {
                        "stock_id": item.get("stock_id"),
                        "reason": f"universe_status:{raw_status}",
                    }
                )
                continue
            if not isinstance(shadow, Mapping):
                observation = _upsert_universe_observation(
                    db=db,
                    group_id=group_id,
                    mode=mode,
                    snapshot_date=snapshot_date,
                    item=item,
                    evaluation=None,
                    selected=selected_item is not None,
                    universe_scope=universe_scope,
                    observed_at=observed_at,
                    rule_version=rule_version,
                    rule_config_hash=rule_config_hash,
                    reason="missing_radar_v2_evaluation",
                )
                if observation is not None:
                    observation_status_counts[observation.observation_status] = (
                        observation_status_counts.get(
                            observation.observation_status,
                            0,
                        )
                        + 1
                    )
                skipped.append(
                    {
                        "stock_id": item.get("stock_id"),
                        "reason": "missing_radar_v2_evaluation",
                    }
                )
                continue
            feature, feature_created = _upsert_feature(
                db=db,
                item=item,
                shadow=shadow,
                now=observed_at,
                market_data_revision=(
                    f"watchlist_radar_snapshot:{snapshot_run_id}"
                    if snapshot_run_id is not None
                    else None
                ),
            )
            if feature is None:
                observation = _upsert_universe_observation(
                    db=db,
                    group_id=group_id,
                    mode=mode,
                    snapshot_date=snapshot_date,
                    item=item,
                    evaluation=None,
                    selected=selected_item is not None,
                    universe_scope=universe_scope,
                    observed_at=observed_at,
                    rule_version=rule_version,
                    rule_config_hash=rule_config_hash,
                    reason="missing_stock_or_trade_date",
                )
                if observation is not None:
                    observation_status_counts[observation.observation_status] = (
                        observation_status_counts.get(
                            observation.observation_status,
                            0,
                        )
                        + 1
                    )
                skipped.append(
                    {
                        "stock_id": item.get("stock_id"),
                        "reason": "missing_stock_or_trade_date",
                    }
                )
                continue
            feature_created_count += int(feature_created)
            evaluation, evaluation_created = _upsert_evaluation(
                db=db,
                feature=feature,
                item=item,
                shadow=shadow,
                now=observed_at,
            )
            evaluation_created_count += int(evaluation_created)
            evaluation_ids.append(int(evaluation.id))
            created_events, updated_events, created_links = _upsert_events(
                db=db,
                feature=feature,
                evaluation=evaluation,
                shadow=shadow,
            )
            event_created_count += created_events
            event_updated_count += updated_events
            event_link_created_count += created_links
            observation = _upsert_universe_observation(
                db=db,
                group_id=group_id,
                mode=mode,
                snapshot_date=snapshot_date,
                item=item,
                evaluation=evaluation,
                selected=selected_item is not None,
                universe_scope=universe_scope,
                observed_at=observed_at,
                rule_version=rule_version,
                rule_config_hash=rule_config_hash,
            )
            if observation is not None:
                observation_status_counts[observation.observation_status] = (
                    observation_status_counts.get(
                        observation.observation_status,
                        0,
                    )
                    + 1
                )
            if selected_item is not None:
                projection_item = dict(selected_item)
                projection_item["radar_v2"] = shadow
                projection_created_count += int(
                    _upsert_projection(
                        db=db,
                        evaluation=evaluation,
                        item=projection_item,
                        group_id=group_id,
                        mode=mode,
                        snapshot_date=snapshot_date,
                        snapshot_run_id=snapshot_run_id,
                        projection_meta=projection_meta,
                    )
                )
        absent_count, absent_event_count = (
            _record_absent_previous_scope_stocks(
                db=db,
                group_id=group_id,
                mode=mode,
                snapshot_date=snapshot_date,
                current_stock_ids=current_stock_ids,
                universe_scope=universe_scope,
                observed_at=observed_at,
                rule_version=rule_version,
                rule_config_hash=rule_config_hash,
            )
        )
        event_unobserved_count += absent_event_count
        if absent_count:
            observation_status_counts["absent"] = absent_count
        db.commit()
        return {
            "status": "persisted",
            "rule_version": rule_version,
            "rule_config_hash": rule_config_hash,
            "group_id": group_id,
            "mode": mode,
            "snapshot_date": snapshot_date.isoformat(),
            "snapshot_run_id": snapshot_run_id,
            "feature_created_count": feature_created_count,
            "evaluation_created_count": evaluation_created_count,
            "projection_created_count": projection_created_count,
            "event_created_count": event_created_count,
            "event_updated_count": event_updated_count,
            "event_link_created_count": event_link_created_count,
            "event_unobserved_count": event_unobserved_count,
            "universe_scope": universe_scope,
            "universe_observed_count": len(current_stock_ids) + absent_count,
            "universe_evaluated_count": len(evaluation_ids),
            "observation_status_counts": dict(
                sorted(observation_status_counts.items())
            ),
            "evaluation_ids": evaluation_ids,
            "skipped_count": len(skipped),
            "skipped": skipped,
        }
    except Exception:
        db.rollback()
        raise


def persist_radar_v2_shadow(
    *,
    db: Session,
    radar: Mapping[str, Any],
    group_id: int,
    mode: str,
    snapshot_run_id: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    return persist_radar_v2(
        db=db,
        radar=radar,
        group_id=group_id,
        mode=mode,
        snapshot_run_id=snapshot_run_id,
        now=now,
        contract=RADAR_V2_SHADOW_CONTRACT,
    )


def evaluate_pending_radar_v2_outcomes(
    *,
    db: Session,
    evaluation_ids: list[int] | None = None,
    group_id: int | None = None,
    mode: str | None = None,
    limit: int = 200,
    initialize_limit: int = 200,
    rule_version: str | None = None,
    as_of_trade_date: date | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    from app.watchlists.radar_outcome_v2_service import (
        evaluate_radar_outcome_v2,
    )

    attempt_at = now or utc_now()
    bounded_limit = max(1, min(int(limit), 1000))
    bounded_initialize_limit = max(0, min(int(initialize_limit), 1000))
    candidate_ids = list(
        dict.fromkeys(int(value) for value in evaluation_ids or [])
    )
    if evaluation_ids is None and bounded_initialize_limit:
        discovery_contract = (
            RADAR_V2_ACTIVE_CONTRACT
            if rule_version == RADAR_V2_ACTIVE_CONTRACT["rule_version"]
            else RADAR_V2_SHADOW_CONTRACT
            if rule_version == RADAR_V2_SHADOW_CONTRACT["rule_version"]
            else None
        )
        if discovery_contract is not None:
            candidate_query = (
                db.query(RadarUniverseObservation.evaluation_id)
                .join(
                    RadarRuleEvaluation,
                    RadarRuleEvaluation.id
                    == RadarUniverseObservation.evaluation_id,
                )
                .outerjoin(
                    RadarOutcomePath,
                    and_(
                        RadarOutcomePath.evaluation_id
                        == RadarRuleEvaluation.id,
                        RadarOutcomePath.outcome_contract_version
                        == str(
                            discovery_contract[
                                "outcome_contract_version"
                            ]
                        ),
                        RadarOutcomePath.outcome_config_hash
                        == str(
                            discovery_contract["outcome_config_hash"]
                        ),
                    ),
                )
                .filter(
                    RadarRuleEvaluation.rule_version == rule_version
                )
                .filter(
                    RadarUniverseObservation.rule_version == rule_version
                )
            )
            if group_id is not None:
                candidate_query = candidate_query.filter(
                    RadarUniverseObservation.group_id == group_id
                )
            if mode is not None:
                candidate_query = candidate_query.filter(
                    RadarUniverseObservation.mode == mode
                )
            candidate_ids = [
                int(value)
                for (value,) in (
                    candidate_query.group_by(
                        RadarUniverseObservation.evaluation_id
                    )
                    .having(
                        func.count(
                            func.distinct(
                                RadarOutcomePath.horizon_trading_days
                            )
                        )
                        < len(
                            discovery_contract["outcome_config"][
                                "horizons"
                            ]
                        )
                    )
                    .order_by(
                        func.min(
                            RadarUniverseObservation.snapshot_date
                        ).asc(),
                        RadarUniverseObservation.evaluation_id.asc(),
                    )
                    .limit(bounded_initialize_limit)
                    .all()
                )
                if value is not None
            ]
    candidate_ids = candidate_ids[:bounded_initialize_limit]
    evaluated: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    initialized_evaluation_ids: list[int] = []
    initialized_path_count = 0

    for evaluation_id in candidate_ids:
        try:
            evaluation = (
                db.query(RadarRuleEvaluation)
                .filter(RadarRuleEvaluation.id == evaluation_id)
                .one()
            )
            contract = (
                RADAR_V2_ACTIVE_CONTRACT
                if evaluation.rule_version
                == RADAR_V2_ACTIVE_CONTRACT["rule_version"]
                else RADAR_V2_SHADOW_CONTRACT
            )
            configured_horizons = {
                int(value)
                for value in contract["outcome_config"]["horizons"]
            }
            existing_horizons = {
                int(value)
                for (value,) in (
                    db.query(RadarOutcomePath.horizon_trading_days)
                    .filter(
                        RadarOutcomePath.evaluation_id == evaluation_id
                    )
                    .filter(
                        RadarOutcomePath.outcome_contract_version
                        == str(contract["outcome_contract_version"])
                    )
                    .filter(
                        RadarOutcomePath.outcome_config_hash
                        == str(contract["outcome_config_hash"])
                    )
                    .all()
                )
            }
            missing_horizons = sorted(
                configured_horizons - existing_horizons
            )
            if not missing_horizons:
                continue
            outcomes = evaluate_radar_outcome_v2(
                db=db,
                evaluation_id=evaluation_id,
                horizons=missing_horizons,
                commit=True,
                now=attempt_at,
                outcome_contract_version=str(
                    contract["outcome_contract_version"]
                ),
                outcome_config_hash=str(
                    contract["outcome_config_hash"]
                ),
                outcome_config=dict(contract["outcome_config"]),
                contract_status=str(contract["status"]),
            )
        except Exception as exc:
            db.rollback()
            errors.append(
                {
                    "phase": "initialize",
                    "evaluation_id": evaluation_id,
                    "error_message": str(exc),
                }
            )
            continue
        initialized_evaluation_ids.append(evaluation_id)
        initialized_path_count += len(outcomes)
        evaluated.append(
            {
                "phase": "initialize",
                "evaluation_id": evaluation_id,
                "outcome_count": len(outcomes),
                "horizons": missing_horizons,
                "statuses": sorted(
                    {str(outcome["status"]) for outcome in outcomes}
                ),
            }
        )

    latest_available_trade_date = as_of_trade_date or read_taiwan_daily_freshness(
        db,
        checked_at=attempt_at,
    ).latest_date
    query = (
        db.query(RadarOutcomePath)
        .join(
            RadarRuleEvaluation,
            RadarRuleEvaluation.id == RadarOutcomePath.evaluation_id,
        )
        .filter(RadarOutcomePath.status == "pending")
        .filter(RadarOutcomePath.horizon_end_trade_date.is_not(None))
    )
    if rule_version is not None:
        query = query.filter(
            RadarRuleEvaluation.rule_version == rule_version
        )
    if group_id is not None or mode is not None:
        query = query.join(
            RadarUniverseObservation,
            RadarUniverseObservation.evaluation_id
            == RadarOutcomePath.evaluation_id,
        )
    if group_id is not None:
        query = query.filter(
            RadarUniverseObservation.group_id == group_id
        )
    if mode is not None:
        query = query.filter(RadarUniverseObservation.mode == mode)
    if rule_version == RADAR_V2_ACTIVE_CONTRACT["rule_version"]:
        query = query.filter(
            RadarOutcomePath.outcome_contract_version
            == str(RADAR_V2_ACTIVE_CONTRACT["outcome_contract_version"])
        ).filter(
            RadarOutcomePath.outcome_config_hash
            == str(RADAR_V2_ACTIVE_CONTRACT["outcome_config_hash"])
        )
    elif rule_version == RADAR_V2_SHADOW_CONTRACT["rule_version"]:
        query = query.filter(
            RadarOutcomePath.outcome_contract_version
            == str(RADAR_V2_SHADOW_CONTRACT["outcome_contract_version"])
        ).filter(
            RadarOutcomePath.outcome_config_hash
            == str(RADAR_V2_SHADOW_CONTRACT["outcome_config_hash"])
        )

    due_query = query.filter(
        RadarOutcomePath.horizon_end_trade_date
        <= latest_available_trade_date
    ) if latest_available_trade_date is not None else query.filter(False)
    due_count_before = int(
        due_query.with_entities(
            func.count(func.distinct(RadarOutcomePath.id))
        ).scalar()
        or 0
    )
    due_rows = (
        due_query.order_by(
            RadarOutcomePath.evaluated_at.asc(),
            RadarOutcomePath.horizon_end_trade_date.asc(),
            RadarOutcomePath.id.asc(),
        )
        .distinct()
        .limit(bounded_limit)
        .all()
    )
    due_horizons_by_evaluation: dict[int, list[int]] = {}
    selected_path_ids: list[int] = []
    for row in due_rows:
        selected_path_ids.append(int(row.id))
        due_horizons_by_evaluation.setdefault(
            int(row.evaluation_id), []
        ).append(int(row.horizon_trading_days))

    reconciled_evaluation_ids: list[int] = []
    for evaluation_id, due_horizons in due_horizons_by_evaluation.items():
        try:
            evaluation = (
                db.query(RadarRuleEvaluation)
                .filter(RadarRuleEvaluation.id == evaluation_id)
                .one()
            )
            contract = (
                RADAR_V2_ACTIVE_CONTRACT
                if evaluation.rule_version
                == RADAR_V2_ACTIVE_CONTRACT["rule_version"]
                else RADAR_V2_SHADOW_CONTRACT
            )
            outcomes = evaluate_radar_outcome_v2(
                db=db,
                evaluation_id=evaluation_id,
                horizons=due_horizons,
                commit=True,
                now=attempt_at,
                outcome_contract_version=str(
                    contract["outcome_contract_version"]
                ),
                outcome_config_hash=str(
                    contract["outcome_config_hash"]
                ),
                outcome_config=dict(contract["outcome_config"]),
                contract_status=str(contract["status"]),
            )
        except Exception as exc:
            db.rollback()
            errors.append(
                {
                    "phase": "reconcile",
                    "evaluation_id": evaluation_id,
                    "error_message": str(exc),
                }
            )
            continue
        reconciled_evaluation_ids.append(evaluation_id)
        evaluated.append(
            {
                "phase": "reconcile",
                "evaluation_id": evaluation_id,
                "outcome_count": len(outcomes),
                "horizons": due_horizons,
                "statuses": sorted(
                    {str(outcome["status"]) for outcome in outcomes}
                ),
            }
        )

    attempted_rows = (
        db.query(RadarOutcomePath)
        .filter(RadarOutcomePath.id.in_(selected_path_ids))
        .all()
        if selected_path_ids
        else []
    )
    finalized_count = sum(
        row.status != "pending" for row in attempted_rows
    )
    awaiting_daily_bar_count = sum(
        row.status == "pending" for row in attempted_rows
    )
    unevaluable_count = sum(
        row.status == "unevaluable" for row in attempted_rows
    )
    remaining_due_count = int(
        due_query.with_entities(
            func.count(func.distinct(RadarOutcomePath.id))
        ).scalar()
        or 0
    )
    oldest_due_trade_date = (
        due_query.with_entities(
            func.min(RadarOutcomePath.horizon_end_trade_date)
        ).scalar()
        if remaining_due_count
        else None
    )
    requested_evaluation_ids = set(initialized_evaluation_ids)
    requested_evaluation_ids.update(reconciled_evaluation_ids)
    return {
        "status": (
            "partial_success"
            if (errors and evaluated) or (not errors and remaining_due_count)
            else "error"
            if errors
            else "success"
        ),
        "requested_count": len(requested_evaluation_ids),
        "evaluated_count": len(requested_evaluation_ids),
        "error_count": len(errors),
        "latest_available_trade_date": latest_available_trade_date,
        "due_before": latest_available_trade_date,
        "initialized_evaluation_count": len(initialized_evaluation_ids),
        "initialized_path_count": initialized_path_count,
        "due_count_before": due_count_before,
        "attempted_evaluation_count": len(reconciled_evaluation_ids),
        "attempted_path_count": len(selected_path_ids),
        "finalized_count": finalized_count,
        "awaiting_daily_bar_count": awaiting_daily_bar_count,
        "unevaluable_count": unevaluable_count,
        "remaining_due_count": remaining_due_count,
        "oldest_due_trade_date": oldest_due_trade_date,
        "evaluated": evaluated,
        "errors": errors,
    }


__all__ = [
    "RADAR_V2_SHADOW_ENV",
    "attach_radar_v2_shadow",
    "attach_radar_v2_shadow_from_db",
    "evaluate_radar_v2_item",
    "evaluate_pending_radar_v2_outcomes",
    "latest_market_regime_snapshot",
    "persist_radar_v2",
    "persist_radar_v2_shadow",
    "radar_v2_shadow_enabled",
]
