from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from typing import Any


RADAR_V1_RULE_VERSION = "radar_v1.0"
RADAR_V1_FEATURE_VERSION = "technical_v1.0"
RADAR_V1_OUTCOME_CONTRACT_VERSION = "outcome_v1.0"
RADAR_V1_LIFECYCLE_STATUS = "frozen"
RADAR_V1_FROZEN_AT = "2026-08-01"
RADAR_V1_WRITE_ENABLED = False
RADAR_V1_LIFECYCLE: dict[str, Any] = {
    "status": RADAR_V1_LIFECYCLE_STATUS,
    "frozen_at": RADAR_V1_FROZEN_AT,
    "write_enabled": RADAR_V1_WRITE_ENABLED,
    "retention_policy": "read_only_history_and_rollback",
}

RADAR_V2_RULE_VERSION = "radar_v2.0-shadow"
RADAR_V2_FEATURE_VERSION = "technical_v2.0-shadow"
RADAR_V2_OUTCOME_CONTRACT_VERSION = "outcome_v2.0-shadow"

RADAR_V2_ACTIVE_RULE_VERSION = "radar_v2.0"
RADAR_V2_ACTIVE_FEATURE_VERSION = "technical_v2.0"
RADAR_V2_ACTIVE_OUTCOME_CONTRACT_VERSION = "outcome_v2.0"


V1_HIGH_MOVE_PCT_THRESHOLD = 7.0

V1_TECHNICAL_SIGNAL_WEIGHTS: dict[str, float] = {
    "cross_below_ma60": 4.2,
    "donchian_breakdown": 3.5,
    "structure_support_break": 3.6,
    "bollinger_breakdown": 3.2,
    "cross_below_ma20": 3.0,
    "volume_price_down": 2.8,
    "ema_bearish_cross": 2.6,
    "adx_bear_trend": 2.5,
    "macd_negative": 2.3,
    "roc_negative": 2.2,
    "rsi_overheated": 2.1,
    "kd_bearish_cross": 2.1,
    "kd_overbought": 2.0,
    "atr_high_volatility": 2.2,
    "atr_expanding": 1.8,
    "mfi_outflow": 2.0,
    "rsi_weak": 1.8,
    "cross_above_ma60": 3.8,
    "donchian_breakout": 3.2,
    "structure_resistance_breakout": 3.3,
    "bollinger_breakout": 3.0,
    "volume_price_up": 2.8,
    "cross_above_ma20": 2.6,
    "ema_bullish_cross": 2.5,
    "adx_bull_trend": 2.4,
    "macd_positive": 2.2,
    "roc_positive": 2.1,
    "kd_bullish_cross": 2.0,
    "mfi_inflow": 2.0,
    "rsi_bull_zone": 1.8,
    "volume_expansion": 1.7,
    "volume_above_ma5": 1.5,
    "bollinger_squeeze": 1.4,
    "near_support": 1.1,
    "near_resistance": 1.1,
    "kd_oversold": 1.0,
    "above_ma5": 0.8,
    "below_ma5": 0.8,
    "above_ma20": 1.4,
    "below_ma20": 1.4,
    "above_ma60": 1.8,
    "below_ma60": 2.0,
    "ma5_above_ma20": 1.2,
    "ma5_below_ma20": 1.2,
    "ma20_above_ma60": 1.0,
    "ma20_below_ma60": 1.0,
}

V1_BUCKET_PRIORITY_BASES: dict[str, float] = {
    "limit_move": 100,
    "limit_down_liquidity": 105,
    "selloff_risk": 102,
    "limit_up_lock": 100,
    "surge_up": 96,
    "support_break": 94,
    "volume_down": 90,
    "bearish_momentum": 86,
    "overheated": 84,
    "volatility_risk": 88,
    "breakout_high": 82,
    "trend_reclaim": 78,
    "volume_up": 72,
    "limit_up_move": 100,
    "limit_down_move": 100,
    "risk": 90,
    "breakout": 80,
    "volume": 70,
    "compression_watch": 68,
    "pullback": 65,
    "momentum": 60,
    "watch": 40,
    "quiet": 10,
    "no_data": 0,
    "error": 0,
}

V1_MOMENTUM_OUTCOME_BUCKETS = frozenset(
    {
        "limit_up_lock",
        "surge_up",
        "breakout_high",
        "trend_reclaim",
        "volume_up",
        "momentum",
        "pullback",
        "breakout",
        "limit_up_move",
    }
)
V1_RISK_OUTCOME_BUCKETS = frozenset(
    {
        "limit_down_liquidity",
        "selloff_risk",
        "support_break",
        "volume_down",
        "bearish_momentum",
        "risk",
        "limit_down_move",
    }
)
V1_OVERHEAT_OUTCOME_BUCKETS = frozenset({"overheated", "volatility_risk"})
V1_STRUCTURE_WATCH_OUTCOME_BUCKETS = frozenset(
    {"compression_watch", "volume", "watch"}
)
V1_NON_SCORING_OUTCOME_BUCKETS = frozenset({"quiet", "no_data", "error"})

V1_OUTCOME_THRESHOLDS: dict[str, dict[str, float]] = {
    "momentum": {
        "hit_close_return_gte": 0.0,
        "hit_favorable_gte": 2.0,
        "miss_close_return_lte": -2.0,
        "miss_adverse_lte": -4.0,
    },
    "risk": {
        "hit_close_return_lte": 0.0,
        "hit_adverse_lte": -2.0,
        "miss_close_return_gte": 2.0,
        "miss_adverse_gt": -1.0,
    },
    "overheat": {
        "hit_close_return_lt": 0.0,
        "hit_adverse_lte": -2.0,
        "miss_close_return_gte": 2.0,
        "miss_adverse_gt": -1.0,
    },
    "structure_watch": {
        "hit_abs_close_return_gte": 2.0,
        "hit_intraday_range_gte": 3.0,
    },
}


def canonical_config_json(config: Any) -> str:
    return json.dumps(
        config,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def config_hash(config: Any) -> str:
    return sha256(canonical_config_json(config).encode("utf-8")).hexdigest()


RADAR_V1_CONTRACT: dict[str, Any] = {
    "rule_version": RADAR_V1_RULE_VERSION,
    "feature_version": RADAR_V1_FEATURE_VERSION,
    "outcome_contract_version": RADAR_V1_OUTCOME_CONTRACT_VERSION,
    "classification": {
        "high_move_pct_threshold": V1_HIGH_MOVE_PCT_THRESHOLD,
    },
    "technical_signal_weights": V1_TECHNICAL_SIGNAL_WEIGHTS,
    "bucket_priority_bases": V1_BUCKET_PRIORITY_BASES,
    "outcome": {
        "evaluation_order": ["hit", "miss", "neutral"],
        "bucket_groups": {
            "momentum": sorted(V1_MOMENTUM_OUTCOME_BUCKETS),
            "risk": sorted(V1_RISK_OUTCOME_BUCKETS),
            "overheat": sorted(V1_OVERHEAT_OUTCOME_BUCKETS),
            "structure_watch": sorted(V1_STRUCTURE_WATCH_OUTCOME_BUCKETS),
            "non_scoring": sorted(V1_NON_SCORING_OUTCOME_BUCKETS),
        },
        "thresholds": V1_OUTCOME_THRESHOLDS,
    },
}

RADAR_V1_CONFIG_HASH = config_hash(RADAR_V1_CONTRACT)

RADAR_V2_OUTCOME_CONFIG: dict[str, Any] = {
    "outcome_contract_version": RADAR_V2_OUTCOME_CONTRACT_VERSION,
    "horizons": [1, 3, 5],
    "reference_price_type": "signal_close",
    "entry_proxy_price_type": "next_trading_day_open",
    "return_basis": "raw_price",
    "directional_thresholds": {
        "intraday_trigger_r": 1.0,
        "close_confirm_r": 0.5,
        "adverse_trigger_r": 1.0,
        "reverse_close_r": -0.5,
        "invalidated_mfe_r_lt": 0.5,
    },
    "directional_summary_precedence": [
        "whipsaw",
        "reversed",
        "close_confirmed",
        "intraday_only",
        "invalidated",
        "adverse_only",
        "neutral",
    ],
    "non_directional_thresholds": {
        "upside_expansion_r": 1.0,
        "downside_expansion_r": 1.0,
        "close_direction_pct": 0.5,
    },
    "overheat_summary_states": [
        "two_way_whipsaw",
        "expanded_up",
        "expanded_down",
        "upside_rejected",
        "downside_recovered",
        "high_level_consolidation",
        "neutral",
    ],
    "corporate_action_coverage": {
        "supported_event_types": ["ex_dividend"],
        "required_price_path_event_types": [
            "ex_dividend",
            "ex_rights",
            "capital_reduction",
            "stock_split",
            "reverse_split",
            "merger",
        ],
    },
    "path_order_quality": "unordered_daily_ohlc",
    "tradability_status": "entry_proxy_only",
}
RADAR_V2_OUTCOME_CONFIG_HASH = config_hash(RADAR_V2_OUTCOME_CONFIG)

RADAR_V2_ACTIVE_OUTCOME_CONFIG: dict[str, Any] = deepcopy(
    RADAR_V2_OUTCOME_CONFIG
)
RADAR_V2_ACTIVE_OUTCOME_CONFIG["outcome_contract_version"] = (
    RADAR_V2_ACTIVE_OUTCOME_CONTRACT_VERSION
)
RADAR_V2_ACTIVE_OUTCOME_CONFIG_HASH = config_hash(
    RADAR_V2_ACTIVE_OUTCOME_CONFIG
)

RADAR_V2_FEATURE_CONFIG: dict[str, Any] = {
    "feature_version": RADAR_V2_FEATURE_VERSION,
    "source_contract": "watchlist_latest_ranking",
    "time_contract": {
        "daily_effective_time": "13:30:00 Asia/Taipei",
        "intraday_effective_time": "source event time",
        "source_available_at": "explicit source time or observation-time fallback",
        "observed_at": "persistence observation time",
    },
    "technical_inputs": [
        "close",
        "previous_close",
        "volume",
        "signal_keys",
        "indicator_snapshot",
    ],
    "signal_measurement": {
        "version": "distance_and_indicator_strength_v1",
        "default_strength_when_unmeasured": 0.5,
        "freshness_source": "item_data_quality",
        "timeframe_conflict_source": "context_snapshot_or_signal_direction",
    },
    "identity_excludes": [
        "market_regime",
        "watchlist_group",
        "mode",
        "rank",
        "persistence_time",
    ],
}
RADAR_V2_FEATURE_CONFIG_HASH = config_hash(RADAR_V2_FEATURE_CONFIG)

RADAR_V2_ACTIVE_FEATURE_CONFIG: dict[str, Any] = deepcopy(
    RADAR_V2_FEATURE_CONFIG
)
RADAR_V2_ACTIVE_FEATURE_CONFIG["feature_version"] = (
    RADAR_V2_ACTIVE_FEATURE_VERSION
)
RADAR_V2_ACTIVE_FEATURE_CONFIG["source_contract"] = (
    "watchlist_latest_ranking_complete_calculation_universe"
)
RADAR_V2_ACTIVE_FEATURE_CONFIG_HASH = config_hash(
    RADAR_V2_ACTIVE_FEATURE_CONFIG
)

RADAR_V2_SIGNAL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "price_up": {
        "family": "momentum",
        "direction": 1,
        "signal_type": "state",
        "base_weight": 0.8,
        "risk_weight": 0.0,
        "state_tags": ["price_up"],
        "risk_tags": [],
    },
    "price_down": {
        "family": "momentum",
        "direction": -1,
        "signal_type": "state",
        "base_weight": 0.8,
        "risk_weight": 0.4,
        "state_tags": ["price_down"],
        "risk_tags": ["price_weakness"],
    },
    "above_ma5": {
        "family": "trend",
        "direction": 1,
        "signal_type": "state",
        "base_weight": 0.6,
        "risk_weight": 0.0,
        "state_tags": ["above_short_trend"],
        "risk_tags": [],
    },
    "below_ma5": {
        "family": "trend",
        "direction": -1,
        "signal_type": "state",
        "base_weight": 0.6,
        "risk_weight": 0.2,
        "state_tags": ["below_short_trend"],
        "risk_tags": [],
    },
    "above_ma20": {
        "family": "trend",
        "direction": 1,
        "signal_type": "state",
        "base_weight": 1.0,
        "risk_weight": 0.0,
        "state_tags": ["above_medium_trend"],
        "risk_tags": [],
    },
    "below_ma20": {
        "family": "trend",
        "direction": -1,
        "signal_type": "state",
        "base_weight": 1.0,
        "risk_weight": 0.6,
        "state_tags": ["below_medium_trend"],
        "risk_tags": ["support_pressure"],
    },
    "above_ma60": {
        "family": "trend",
        "direction": 1,
        "signal_type": "state",
        "base_weight": 1.2,
        "risk_weight": 0.0,
        "state_tags": ["above_long_trend"],
        "risk_tags": [],
    },
    "below_ma60": {
        "family": "trend",
        "direction": -1,
        "signal_type": "state",
        "base_weight": 1.2,
        "risk_weight": 0.9,
        "state_tags": ["below_long_trend"],
        "risk_tags": ["long_trend_weakness"],
    },
    "ma5_above_ma20": {
        "family": "trend",
        "direction": 1,
        "signal_type": "state",
        "base_weight": 1.0,
        "risk_weight": 0.0,
        "state_tags": ["bullish_ma_alignment"],
        "risk_tags": [],
    },
    "ma5_below_ma20": {
        "family": "trend",
        "direction": -1,
        "signal_type": "state",
        "base_weight": 1.0,
        "risk_weight": 0.4,
        "state_tags": ["bearish_ma_alignment"],
        "risk_tags": [],
    },
    "ma20_above_ma60": {
        "family": "trend",
        "direction": 1,
        "signal_type": "state",
        "base_weight": 1.1,
        "risk_weight": 0.0,
        "state_tags": ["bullish_long_alignment"],
        "risk_tags": [],
    },
    "ma20_below_ma60": {
        "family": "trend",
        "direction": -1,
        "signal_type": "state",
        "base_weight": 1.1,
        "risk_weight": 0.5,
        "state_tags": ["bearish_long_alignment"],
        "risk_tags": [],
    },
    "cross_above_ma20": {
        "family": "structure",
        "direction": 1,
        "signal_type": "event",
        "base_weight": 2.4,
        "risk_weight": 0.0,
        "state_tags": ["trend_reclaim"],
        "risk_tags": [],
    },
    "cross_below_ma20": {
        "family": "structure",
        "direction": -1,
        "signal_type": "event",
        "base_weight": 2.5,
        "risk_weight": 1.4,
        "state_tags": ["support_break"],
        "risk_tags": ["support_break"],
    },
    "cross_above_ma60": {
        "family": "structure",
        "direction": 1,
        "signal_type": "event",
        "base_weight": 3.0,
        "risk_weight": 0.0,
        "state_tags": ["long_trend_reclaim"],
        "risk_tags": [],
    },
    "cross_below_ma60": {
        "family": "structure",
        "direction": -1,
        "signal_type": "event",
        "base_weight": 3.1,
        "risk_weight": 1.8,
        "state_tags": ["long_support_break"],
        "risk_tags": ["long_support_break"],
    },
    "ema_fast_above_slow": {
        "family": "trend",
        "direction": 1,
        "signal_type": "state",
        "base_weight": 0.8,
        "risk_weight": 0.0,
        "state_tags": ["ema_bullish"],
        "risk_tags": [],
    },
    "ema_fast_below_slow": {
        "family": "trend",
        "direction": -1,
        "signal_type": "state",
        "base_weight": 0.8,
        "risk_weight": 0.3,
        "state_tags": ["ema_bearish"],
        "risk_tags": [],
    },
    "ema_bullish_cross": {
        "family": "structure",
        "direction": 1,
        "signal_type": "event",
        "base_weight": 2.2,
        "risk_weight": 0.0,
        "state_tags": ["trend_reclaim"],
        "risk_tags": [],
    },
    "ema_bearish_cross": {
        "family": "structure",
        "direction": -1,
        "signal_type": "event",
        "base_weight": 2.3,
        "risk_weight": 1.2,
        "state_tags": ["trend_loss"],
        "risk_tags": ["trend_loss"],
    },
    "macd_positive": {
        "family": "momentum",
        "direction": 1,
        "signal_type": "state",
        "base_weight": 1.2,
        "risk_weight": 0.0,
        "state_tags": ["momentum_up"],
        "risk_tags": [],
    },
    "macd_negative": {
        "family": "momentum",
        "direction": -1,
        "signal_type": "state",
        "base_weight": 1.2,
        "risk_weight": 0.5,
        "state_tags": ["momentum_down"],
        "risk_tags": [],
    },
    "adx_bull_trend": {
        "family": "trend",
        "direction": 1,
        "signal_type": "state",
        "base_weight": 1.2,
        "risk_weight": 0.0,
        "state_tags": ["trend_up"],
        "risk_tags": [],
    },
    "adx_bear_trend": {
        "family": "trend",
        "direction": -1,
        "signal_type": "state",
        "base_weight": 1.2,
        "risk_weight": 0.7,
        "state_tags": ["trend_down"],
        "risk_tags": ["trend_down"],
    },
    "donchian_breakout": {
        "family": "structure",
        "direction": 1,
        "signal_type": "event",
        "base_weight": 2.8,
        "risk_weight": 0.0,
        "state_tags": ["breakout_up"],
        "risk_tags": [],
    },
    "donchian_breakdown": {
        "family": "structure",
        "direction": -1,
        "signal_type": "event",
        "base_weight": 2.9,
        "risk_weight": 1.6,
        "state_tags": ["breakout_down"],
        "risk_tags": ["support_break"],
    },
    "rsi_bull_zone": {
        "family": "momentum",
        "direction": 1,
        "signal_type": "state",
        "base_weight": 0.9,
        "risk_weight": 0.0,
        "state_tags": ["momentum_up"],
        "risk_tags": [],
    },
    "rsi_weak": {
        "family": "momentum",
        "direction": -1,
        "signal_type": "state",
        "base_weight": 0.9,
        "risk_weight": 0.5,
        "state_tags": ["momentum_down"],
        "risk_tags": ["momentum_weakness"],
    },
    "rsi_overheated": {
        "family": "location",
        "direction": 0,
        "signal_type": "modifier",
        "base_weight": 0.0,
        "risk_weight": 1.5,
        "state_tags": ["overheated"],
        "risk_tags": ["overheated"],
    },
    "mfi_inflow": {
        "family": "volume",
        "direction": 1,
        "signal_type": "state",
        "base_weight": 1.1,
        "risk_weight": 0.0,
        "state_tags": ["money_flow_in"],
        "risk_tags": [],
    },
    "mfi_outflow": {
        "family": "volume",
        "direction": -1,
        "signal_type": "state",
        "base_weight": 1.1,
        "risk_weight": 0.6,
        "state_tags": ["money_flow_out"],
        "risk_tags": ["money_flow_out"],
    },
    "roc_positive": {
        "family": "momentum",
        "direction": 1,
        "signal_type": "state",
        "base_weight": 1.0,
        "risk_weight": 0.0,
        "state_tags": ["momentum_up"],
        "risk_tags": [],
    },
    "roc_negative": {
        "family": "momentum",
        "direction": -1,
        "signal_type": "state",
        "base_weight": 1.0,
        "risk_weight": 0.5,
        "state_tags": ["momentum_down"],
        "risk_tags": [],
    },
    "volume_price_up": {
        "family": "volume",
        "direction": 1,
        "signal_type": "event",
        "base_weight": 2.0,
        "risk_weight": 0.0,
        "state_tags": ["volume_up"],
        "risk_tags": [],
    },
    "volume_price_down": {
        "family": "volume",
        "direction": -1,
        "signal_type": "event",
        "base_weight": 2.0,
        "risk_weight": 1.3,
        "state_tags": ["volume_down"],
        "risk_tags": ["distribution"],
    },
    "volume_expansion": {
        "family": "volume",
        "direction": 0,
        "signal_type": "modifier",
        "base_weight": 0.0,
        "risk_weight": 0.4,
        "state_tags": ["volume_expansion"],
        "risk_tags": [],
    },
    "volume_above_ma5": {
        "family": "volume",
        "direction": 0,
        "signal_type": "modifier",
        "base_weight": 0.0,
        "risk_weight": 0.2,
        "state_tags": ["volume_active"],
        "risk_tags": [],
    },
    "structure_support_break": {
        "family": "structure",
        "direction": -1,
        "signal_type": "event",
        "base_weight": 3.0,
        "risk_weight": 1.8,
        "state_tags": ["support_break"],
        "risk_tags": ["support_break"],
    },
    "structure_resistance_breakout": {
        "family": "structure",
        "direction": 1,
        "signal_type": "event",
        "base_weight": 3.0,
        "risk_weight": 0.0,
        "state_tags": ["breakout_up"],
        "risk_tags": [],
    },
    "near_support": {
        "family": "location",
        "direction": 0,
        "signal_type": "modifier",
        "base_weight": 0.0,
        "risk_weight": 0.4,
        "state_tags": ["near_support"],
        "risk_tags": ["support_proximity"],
    },
    "near_resistance": {
        "family": "location",
        "direction": 0,
        "signal_type": "modifier",
        "base_weight": 0.0,
        "risk_weight": 0.5,
        "state_tags": ["near_resistance"],
        "risk_tags": ["resistance_proximity"],
    },
    "bollinger_breakout": {
        "family": "structure",
        "direction": 1,
        "signal_type": "event",
        "base_weight": 2.5,
        "risk_weight": 0.2,
        "state_tags": ["breakout_up"],
        "risk_tags": [],
    },
    "bollinger_breakdown": {
        "family": "structure",
        "direction": -1,
        "signal_type": "event",
        "base_weight": 2.6,
        "risk_weight": 1.4,
        "state_tags": ["breakout_down"],
        "risk_tags": ["support_break"],
    },
    "bollinger_squeeze": {
        "family": "volatility",
        "direction": 0,
        "signal_type": "modifier",
        "base_weight": 0.0,
        "risk_weight": 0.4,
        "state_tags": ["compression"],
        "risk_tags": ["volatility_transition"],
    },
    "kd_bullish_cross": {
        "family": "momentum",
        "direction": 1,
        "signal_type": "event",
        "base_weight": 1.6,
        "risk_weight": 0.0,
        "state_tags": ["momentum_up"],
        "risk_tags": [],
    },
    "kd_bearish_cross": {
        "family": "momentum",
        "direction": -1,
        "signal_type": "event",
        "base_weight": 1.6,
        "risk_weight": 0.8,
        "state_tags": ["momentum_down"],
        "risk_tags": ["momentum_weakness"],
    },
    "kd_overbought": {
        "family": "location",
        "direction": 0,
        "signal_type": "modifier",
        "base_weight": 0.0,
        "risk_weight": 1.2,
        "state_tags": ["overheated"],
        "risk_tags": ["overheated"],
    },
    "kd_oversold": {
        "family": "location",
        "direction": 0,
        "signal_type": "modifier",
        "base_weight": 0.0,
        "risk_weight": 0.7,
        "state_tags": ["oversold"],
        "risk_tags": ["oversold"],
    },
    "atr_high_volatility": {
        "family": "volatility",
        "direction": 0,
        "signal_type": "modifier",
        "base_weight": 0.0,
        "risk_weight": 2.4,
        "state_tags": ["high_volatility"],
        "risk_tags": ["high_volatility"],
    },
    "atr_expanding": {
        "family": "volatility",
        "direction": 0,
        "signal_type": "modifier",
        "base_weight": 0.0,
        "risk_weight": 1.6,
        "state_tags": ["volatility_expansion"],
        "risk_tags": ["volatility_expansion"],
    },
}

RADAR_V2_SCORING_CONFIG: dict[str, Any] = {
    "rule_version": RADAR_V2_RULE_VERSION,
    "feature_version": RADAR_V2_FEATURE_VERSION,
    "normalization": "fixed_absolute",
    "signal_definitions": RADAR_V2_SIGNAL_DEFINITIONS,
    "signal_type_factors": {
        "event": 1.0,
        "state": 0.45,
        "modifier": 0.0,
    },
    "directional_families": [
        "trend",
        "structure",
        "momentum",
        "volume",
    ],
    "family_direction_weights": {
        "trend": 1.0,
        "structure": 1.15,
        "momentum": 0.9,
        "volume": 0.85,
    },
    "family_saturation": {
        "cap": 10.0,
        "k": 6.0,
    },
    "risk_saturation": {
        "cap": 10.0,
        "k": 5.0,
    },
    "conflict_weights": {
        "within_family": 0.45,
        "cross_family": 0.45,
        "timeframe": 0.10,
    },
    "confidence": {
        "conflict_penalty": 0.75,
    },
    "direction_threshold": 8.0,
    "evidence_grades": {
        "strong": {
            "minimum_evidence": 55.0,
            "minimum_confidence": 45.0,
        },
        "medium": {
            "minimum_evidence": 30.0,
            "minimum_confidence": 20.0,
        },
        "weak": {
            "minimum_evidence": 12.0,
        },
    },
    "urgency_scores": {
        "low": 20.0,
        "medium": 55.0,
        "high": 85.0,
    },
    "priority_weights": {
        "direction_strength": 0.30,
        "confidence": 0.30,
        "risk": 0.20,
        "urgency": 0.10,
        "event_actionability": 0.10,
    },
    "context_policy": "reported_separately_not_in_technical_direction",
}
RADAR_V2_SCORING_CONFIG_HASH = config_hash(RADAR_V2_SCORING_CONFIG)

RADAR_V2_REGIME_CONFIG: dict[str, Any] = {
    "instrument_regime": {
        "adx_trend_threshold": 25.0,
        "adx_range_threshold": 20.0,
        "minimum_directional_vote": 1.0,
        "bollinger_compression_bandwidth_pct": 8.0,
        "atr_high_volatility_pct": 5.0,
        "family_weight_multipliers": {
            "trend_up": {
                "trend": 1.15,
                "structure": 1.10,
                "momentum": 0.95,
                "volume": 0.90,
            },
            "trend_down": {
                "trend": 1.15,
                "structure": 1.10,
                "momentum": 0.95,
                "volume": 0.90,
            },
            "range": {
                "trend": 0.75,
                "structure": 0.90,
                "momentum": 1.10,
                "volume": 1.00,
            },
            "compression": {
                "trend": 0.70,
                "structure": 1.10,
                "momentum": 0.80,
                "volume": 0.90,
            },
            "transition": {
                "trend": 1.00,
                "structure": 1.00,
                "momentum": 1.00,
                "volume": 1.00,
            },
            "insufficient": {
                "trend": 1.00,
                "structure": 1.00,
                "momentum": 1.00,
                "volume": 1.00,
            },
        },
    },
    "market_regime": {
        "minimum_breadth_coverage": 0.90,
        "strong_breadth_ratio": 0.30,
        "moderate_breadth_ratio": 0.12,
        "strong_index_change_pct": 1.50,
        "moderate_index_change_pct": 0.60,
        "accepted_quality_statuses": ["ready"],
        "accepted_breadth_scopes": ["full_market"],
    },
    "combined_clarity": {
        "instrument_weight": 0.75,
        "market_weight": 0.25,
        "missing_market_clarity": 0.50,
    },
    "activation_policy": "shadow_until_walk_forward_incremental_value",
}

RADAR_V2_RULE_CONFIG: dict[str, Any] = {
    "rule_version": RADAR_V2_RULE_VERSION,
    "scoring": RADAR_V2_SCORING_CONFIG,
    "regime": RADAR_V2_REGIME_CONFIG,
}
RADAR_V2_RULE_CONFIG_HASH = config_hash(RADAR_V2_RULE_CONFIG)

RADAR_V2_ACTIVE_SCORING_CONFIG: dict[str, Any] = deepcopy(
    RADAR_V2_SCORING_CONFIG
)
RADAR_V2_ACTIVE_SCORING_CONFIG["rule_version"] = (
    RADAR_V2_ACTIVE_RULE_VERSION
)
RADAR_V2_ACTIVE_SCORING_CONFIG["feature_version"] = (
    RADAR_V2_ACTIVE_FEATURE_VERSION
)
RADAR_V2_ACTIVE_SCORING_CONFIG["urgency_policy"] = (
    "derived_from_v2_event_risk_direction_and_evidence"
)
RADAR_V2_ACTIVE_SCORING_CONFIG_HASH = config_hash(
    RADAR_V2_ACTIVE_SCORING_CONFIG
)

RADAR_V2_ACTIVE_REGIME_CONFIG: dict[str, Any] = deepcopy(
    RADAR_V2_REGIME_CONFIG
)
RADAR_V2_ACTIVE_REGIME_CONFIG["activation_policy"] = (
    "operational_default_with_separate_validation_readiness"
)
RADAR_V2_ACTIVE_REGIME_CONFIG["validation_policy"] = {
    "required_evidence": "purged_walk_forward_incremental_value",
    "missing_evidence_status": "unverified",
}

RADAR_V2_ACTIVE_RULE_CONFIG: dict[str, Any] = {
    "rule_version": RADAR_V2_ACTIVE_RULE_VERSION,
    "scoring": RADAR_V2_ACTIVE_SCORING_CONFIG,
    "regime": RADAR_V2_ACTIVE_REGIME_CONFIG,
    "projection": {
        "input_scope": "complete_calculation_universe",
        "mode_filter_owner": "radar_v2",
        "ranking_owner": "radar_v2",
        "public_action_reason_owner": "backend_radar_v2",
        "rollback_version": RADAR_V1_RULE_VERSION,
    },
}
RADAR_V2_ACTIVE_RULE_CONFIG_HASH = config_hash(
    RADAR_V2_ACTIVE_RULE_CONFIG
)

RADAR_V2_SHADOW_CONTRACT: dict[str, Any] = {
    "mode": "shadow",
    "status": "shadow",
    "rule_version": RADAR_V2_RULE_VERSION,
    "rule_config_hash": RADAR_V2_RULE_CONFIG_HASH,
    "rule_config": RADAR_V2_RULE_CONFIG,
    "feature_version": RADAR_V2_FEATURE_VERSION,
    "feature_config_hash": RADAR_V2_FEATURE_CONFIG_HASH,
    "feature_config": RADAR_V2_FEATURE_CONFIG,
    "outcome_contract_version": RADAR_V2_OUTCOME_CONTRACT_VERSION,
    "outcome_config_hash": RADAR_V2_OUTCOME_CONFIG_HASH,
    "outcome_config": RADAR_V2_OUTCOME_CONFIG,
    "scoring_config": RADAR_V2_SCORING_CONFIG,
}

RADAR_V2_ACTIVE_CONTRACT: dict[str, Any] = {
    "mode": "active",
    "status": "active",
    "rule_version": RADAR_V2_ACTIVE_RULE_VERSION,
    "rule_config_hash": RADAR_V2_ACTIVE_RULE_CONFIG_HASH,
    "rule_config": RADAR_V2_ACTIVE_RULE_CONFIG,
    "feature_version": RADAR_V2_ACTIVE_FEATURE_VERSION,
    "feature_config_hash": RADAR_V2_ACTIVE_FEATURE_CONFIG_HASH,
    "feature_config": RADAR_V2_ACTIVE_FEATURE_CONFIG,
    "outcome_contract_version": RADAR_V2_ACTIVE_OUTCOME_CONTRACT_VERSION,
    "outcome_config_hash": RADAR_V2_ACTIVE_OUTCOME_CONFIG_HASH,
    "outcome_config": RADAR_V2_ACTIVE_OUTCOME_CONFIG,
    "scoring_config": RADAR_V2_ACTIVE_SCORING_CONFIG,
}


__all__ = [
    "RADAR_V1_CONFIG_HASH",
    "RADAR_V1_CONTRACT",
    "RADAR_V1_FEATURE_VERSION",
    "RADAR_V1_FROZEN_AT",
    "RADAR_V1_LIFECYCLE",
    "RADAR_V1_LIFECYCLE_STATUS",
    "RADAR_V1_OUTCOME_CONTRACT_VERSION",
    "RADAR_V1_RULE_VERSION",
    "RADAR_V1_WRITE_ENABLED",
    "RADAR_V2_FEATURE_VERSION",
    "RADAR_V2_FEATURE_CONFIG",
    "RADAR_V2_FEATURE_CONFIG_HASH",
    "RADAR_V2_ACTIVE_FEATURE_VERSION",
    "RADAR_V2_ACTIVE_FEATURE_CONFIG",
    "RADAR_V2_ACTIVE_FEATURE_CONFIG_HASH",
    "RADAR_V2_ACTIVE_OUTCOME_CONTRACT_VERSION",
    "RADAR_V2_ACTIVE_OUTCOME_CONFIG",
    "RADAR_V2_ACTIVE_OUTCOME_CONFIG_HASH",
    "RADAR_V2_ACTIVE_RULE_VERSION",
    "RADAR_V2_ACTIVE_RULE_CONFIG",
    "RADAR_V2_ACTIVE_RULE_CONFIG_HASH",
    "RADAR_V2_ACTIVE_SCORING_CONFIG",
    "RADAR_V2_ACTIVE_SCORING_CONFIG_HASH",
    "RADAR_V2_ACTIVE_REGIME_CONFIG",
    "RADAR_V2_ACTIVE_CONTRACT",
    "RADAR_V2_OUTCOME_CONFIG",
    "RADAR_V2_OUTCOME_CONFIG_HASH",
    "RADAR_V2_OUTCOME_CONTRACT_VERSION",
    "RADAR_V2_REGIME_CONFIG",
    "RADAR_V2_RULE_CONFIG",
    "RADAR_V2_RULE_CONFIG_HASH",
    "RADAR_V2_RULE_VERSION",
    "RADAR_V2_SCORING_CONFIG",
    "RADAR_V2_SCORING_CONFIG_HASH",
    "RADAR_V2_SHADOW_CONTRACT",
    "RADAR_V2_SIGNAL_DEFINITIONS",
    "V1_BUCKET_PRIORITY_BASES",
    "V1_HIGH_MOVE_PCT_THRESHOLD",
    "V1_MOMENTUM_OUTCOME_BUCKETS",
    "V1_NON_SCORING_OUTCOME_BUCKETS",
    "V1_OUTCOME_THRESHOLDS",
    "V1_OVERHEAT_OUTCOME_BUCKETS",
    "V1_RISK_OUTCOME_BUCKETS",
    "V1_STRUCTURE_WATCH_OUTCOME_BUCKETS",
    "V1_TECHNICAL_SIGNAL_WEIGHTS",
    "canonical_config_json",
    "config_hash",
]
