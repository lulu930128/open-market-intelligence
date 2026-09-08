from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
import hashlib
import json
import math
from threading import RLock
import time
from typing import Any

from sqlalchemy.orm import Session

from app.market.next_session_plan import build_tw_stock_next_session_plan
from app.market.taiwan_price_rules import (
    normalize_taiwan_stock_price,
    shift_taiwan_stock_price_by_ticks,
    taiwan_stock_tick_size,
)
from app.market.technical_evidence import build_tw_stock_price_map_evidence
from app.market.technical_parameters import (
    TechnicalAnalysisParameters,
    build_taiwan_technical_parameter_contract,
    get_technical_analysis_parameters,
)
from app.market.technical_report import build_stock_technical_report
from app.market.trading_calendar import taiwan_now
from app.market.tw_corporate_events import get_taiwan_stock_event_history


PRICE_MAP_KIND = "tw_stock_price_map"
PRICE_MAP_VERSION = "tw.stock.price_map.v3"
METHODOLOGY_ID = "tw_stock_price_map_confluence"
METHODOLOGY_VERSION = "2.0.0"
CLUSTER_MIN_TICKS = 2
ZONE_PADDING_PCT = 0.15
ZONE_PADDING_TICKS = 2
ZONE_MERGE_GAP_TICKS = 2
MAX_ZONE_WIDTH_PCT = 3.0
MAX_LEVEL_DISTANCE_PCT = 35.0
DISPLAY_AXIS_PERCENT = 10.0
DISPLAY_AXIS_TICK_PCTS = (10.0, 8.0, 6.0, 4.0, 2.0, 0.0, -2.0, -4.0, -6.0, -8.0, -10.0)
PRICE_MAP_BASIS_CACHE_TTL_SECONDS = 30.0
_PRICE_MAP_BASIS_CACHE: dict[
    tuple[int, str, str, float | None],
    tuple[float, dict[str, Any], dict[str, Any], str | None],
] = {}
_PRICE_MAP_BASIS_CACHE_LOCK = RLock()


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0 else None


def _dict(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _resolve_price_map_status(
    *,
    plan_status: str,
    reference_available: bool,
    levels_available: bool,
    evidence_status: str,
    corporate_complete: bool,
) -> str:
    if plan_status == "not_applicable":
        return "not_applicable"
    if not reference_available:
        return plan_status if plan_status in {"stale", "pending"} else "missing"
    if plan_status in {"stale", "pending"}:
        return plan_status
    if not levels_available or evidence_status in {"missing", "unavailable"}:
        return "partial"
    if (
        plan_status == "missing"
        or evidence_status != "ready"
        or not corporate_complete
    ):
        return "partial"
    return "ready"


def _basis_cache_key(
    db: Session,
    *,
    stock_id: str,
    next_plan: Mapping[str, Any],
) -> tuple[int, str, str, float | None]:
    return (
        id(db.get_bind()),
        stock_id,
        str(next_plan.get("as_of_trade_date") or "missing"),
        _number(next_plan.get("as_of_close")),
    )


def _read_basis_cache(
    key: tuple[int, str, str, float | None],
) -> tuple[dict[str, Any], dict[str, Any], str | None] | None:
    current = time.monotonic()
    with _PRICE_MAP_BASIS_CACHE_LOCK:
        cached = _PRICE_MAP_BASIS_CACHE.get(key)
        if cached is None:
            return None
        expires_at, report, evidence, evidence_error = cached
        if expires_at <= current:
            _PRICE_MAP_BASIS_CACHE.pop(key, None)
            return None
        return report, evidence, evidence_error


def _write_basis_cache(
    key: tuple[int, str, str, float | None],
    *,
    report: dict[str, Any],
    evidence: dict[str, Any],
    evidence_error: str | None,
) -> None:
    expires_at = time.monotonic() + PRICE_MAP_BASIS_CACHE_TTL_SECONDS
    with _PRICE_MAP_BASIS_CACHE_LOCK:
        _PRICE_MAP_BASIS_CACHE[key] = (
            expires_at,
            report,
            evidence,
            evidence_error,
        )
        if len(_PRICE_MAP_BASIS_CACHE) > 512:
            expired = [
                cache_key
                for cache_key, item in _PRICE_MAP_BASIS_CACHE.items()
                if item[0] <= time.monotonic()
            ]
            for cache_key in expired:
                _PRICE_MAP_BASIS_CACHE.pop(cache_key, None)
            while len(_PRICE_MAP_BASIS_CACHE) > 512:
                _PRICE_MAP_BASIS_CACHE.pop(next(iter(_PRICE_MAP_BASIS_CACHE)))


def _role(price: float, reference: float, *, source_type: str) -> str:
    if math.isclose(price, reference, rel_tol=0, abs_tol=taiwan_stock_tick_size(reference) / 2):
        return "pivot"
    if price < reference:
        return "support_candidate"
    if source_type.startswith("projected_ma"):
        return "reclaim"
    return "resistance"


def _distance_pct(price: float, reference: float) -> float:
    return round((price / reference - 1) * 100, 4)


def _display_axis(reference: float | None) -> dict[str, Any]:
    if reference is None:
        return {
            "basis_price": None,
            "lower_bound": None,
            "upper_bound": None,
            "range_kind": "unavailable",
            "range_percent": None,
            "authority": "backend_display_contract",
            "is_legal_limit": False,
            "ticks": [],
            "limitations": ["A completed-session reference price is required for the display axis."],
        }
    ticks = [
        {
            "percent": percent,
            "price": normalize_taiwan_stock_price(reference * (1 + percent / 100)),
        }
        for percent in DISPLAY_AXIS_TICK_PCTS
    ]
    prices = [float(item["price"]) for item in ticks]
    return {
        "basis_price": reference,
        "lower_bound": min(prices),
        "upper_bound": max(prices),
        "range_kind": "display_range",
        "range_percent": DISPLAY_AXIS_PERCENT,
        "authority": "backend_display_contract",
        "is_legal_limit": False,
        "ticks": ticks,
        "limitations": [
            "The axis is a normalized research display range, not an exchange legal price-limit quote."
        ],
    }


def _decision_changes(
    report: Mapping[str, Any],
    *,
    decision_usable: bool,
    zones: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    state = _dict(_dict(report.get("data")).get("decision_state"))
    rows: list[dict[str, Any]] = []
    result_summaries = {
        "first_reclaim": "收復第一道修復條件",
        "structure_repair": "完成結構修復",
        "first_defense": "守住第一道防守條件",
        "risk_break": "弱勢結構延續",
    }
    for raw in state.get("next_conditions") or []:
        item = _dict(raw)
        key = str(item.get("key") or "").strip()
        label = str(item.get("label") or "").strip()
        if not key or not label:
            continue
        relation = (
            "below"
            if key == "risk_break"
            else "at_or_above"
            if key in {"first_reclaim", "structure_repair", "first_defense"}
            else "observe"
        )
        threshold_price = _number(item.get("price"))
        linked_zone, link_reason = _decision_zone_link(
            zones,
            threshold_price=threshold_price,
        )
        if linked_zone is not None:
            linked_zone["trigger_ids"].append(key)
        rows.append(
            {
                "key": key,
                "label": label,
                "tone": str(item.get("tone") or "neutral"),
                "relation": relation,
                "threshold_price": threshold_price,
                "level_key": str(item.get("level_key") or "") or None,
                "timeframe": "daily",
                "evidence_state": "finalized",
                "decision_usable": decision_usable,
                "zone_id": linked_zone["zone_id"] if linked_zone is not None else None,
                "tier_label": linked_zone["tier_label"] if linked_zone is not None else None,
                "result_summary": str(
                    item.get("result_summary")
                    or result_summaries.get(key)
                    or label
                ),
                "link_status": "linked" if linked_zone is not None else "unlinked",
                "link_reason": link_reason,
            }
        )
    return rows[:4]


def _basis_revision(
    *,
    stock_id: str,
    reference: float | None,
    trade_date: Any,
    levels: Iterable[Mapping[str, Any]],
) -> str:
    payload = {
        "price_map_version": PRICE_MAP_VERSION,
        "methodology_version": METHODOLOGY_VERSION,
        "stock_id": stock_id,
        "reference": reference,
        "trade_date": str(trade_date or "missing"),
        "levels": [
            {
                "evidence_id": str(item.get("evidence_id") or ""),
                "price": _number(item.get("price")),
                "timeframe": str(item.get("timeframe") or "unknown"),
                "evidence_state": str(item.get("evidence_state") or "unknown"),
            }
            for item in levels
        ],
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"price-map:{digest[:20]}"


def _level(
    *,
    evidence_id: str,
    label: str,
    source_type: str,
    raw_price: Any,
    reference: float,
    confirmation: str,
    strength: str,
    confidence: str,
    timeframe: str = "daily",
    evidence_state: str = "derived",
    source_ref: Mapping[str, Any] | None = None,
    limitations: Iterable[str] = (),
) -> dict[str, Any] | None:
    price = _number(raw_price)
    if price is None:
        return None
    normalized = normalize_taiwan_stock_price(price)
    distance = _distance_pct(normalized, reference)
    if abs(distance) > MAX_LEVEL_DISTANCE_PCT:
        return None
    return {
        "evidence_id": evidence_id,
        "label": label,
        "source_type": source_type,
        "price": normalized,
        "raw_price": round(price, 4),
        "role": _role(normalized, reference, source_type=source_type),
        "confirmation": confirmation,
        "strength": strength,
        "confidence": confidence,
        "timeframe": timeframe,
        "evidence_state": evidence_state,
        "distance_pct": distance,
        "source_ref": dict(source_ref or {}),
        "limitations": list(dict.fromkeys(str(item) for item in limitations if item)),
    }


def _append(levels: list[dict[str, Any]], value: dict[str, Any] | None) -> None:
    if value is not None and not any(
        item["evidence_id"] == value["evidence_id"] for item in levels
    ):
        levels.append(value)


def _collect_levels(
    *,
    evidence: Mapping[str, Any],
    next_plan: Mapping[str, Any],
    reference: float,
) -> list[dict[str, Any]]:
    levels: list[dict[str, Any]] = []
    for item in next_plan.get("levels") or []:
        row = _dict(item)
        period = int(row.get("period") or 0)
        _append(
            levels,
            _level(
                evidence_id=f"next_session:ma{period}:transition",
                label=f"MA{period} 修復門檻",
                source_type=f"projected_ma{period}_transition",
                raw_price=row.get("normalized_transition_price")
                or row.get("transition_price"),
                reference=reference,
                confirmation="hypothetical_target_close",
                strength="medium",
                confidence="high",
                evidence_state="hypothetical",
                source_ref={"type": "derived", "name": "app.market.next_session_plan"},
                limitations=("A target-session close, not an intraday touch.",),
            ),
        )

    known_range = _dict(next_plan.get("known_range"))
    for key, label in (("support", "20 日區間低點"), ("resistance", "20 日區間高點")):
        _append(
            levels,
            _level(
                evidence_id=f"range:{key}:20d",
                label=label,
                source_type=f"range_{key}",
                raw_price=known_range.get(key),
                reference=reference,
                confirmation="completed_daily_bars",
                strength="high",
                confidence="high",
                evidence_state="observed",
                source_ref={"type": "resolved_market_data", "name": "tw.daily.ohlcv"},
            ),
        )

    indicators = _dict(evidence.get("indicators"))
    daily = _dict(_dict(_dict(indicators.get("timeframes")).get("daily")).get("completed"))
    for family, keys in (
        ("donchian", (("lower20", "Donchian 下緣"), ("upper20", "Donchian 上緣"))),
        (
            "bollinger",
            (
                ("lower20", "布林下緣"),
                ("middle20", "布林中線"),
                ("upper20", "布林上緣"),
            ),
        ),
        (
            "support_resistance",
            (("support20", "結構支撐"), ("resistance20", "結構壓力")),
        ),
    ):
        values = _dict(daily.get(family))
        for key, label in keys:
            _append(
                levels,
                _level(
                    evidence_id=f"indicator:{family}:{key}",
                    label=label,
                    source_type=family,
                    raw_price=values.get(key),
                    reference=reference,
                    confirmation="completed_daily_indicator",
                    strength="medium",
                    confidence="high",
                    evidence_state="derived",
                    source_ref={"type": "derived", "name": "TaiwanTechnicalService"},
                ),
            )

    confirmed_pivots = [
        _dict(item) for item in (_dict(evidence.get("swings")).get("pivots") or [])
    ][-6:]
    for pivot in confirmed_pivots:
        pivot_type = str(pivot.get("type") or "pivot")
        pivot_time = str(pivot.get("pivot_time") or "unknown")
        _append(
            levels,
            _level(
                evidence_id=str(pivot.get("evidence_id") or f"swing:{pivot_type}:{pivot_time}"),
                label=f"確認 swing {'高點' if pivot_type == 'high' else '低點'}",
                source_type=f"swing_{pivot_type}",
                raw_price=pivot.get("price"),
                reference=reference,
                confirmation="confirmed_after_right_bars",
                strength="high",
                confidence="medium",
                evidence_state="observed",
                source_ref={"type": "derived", "name": "tw_technical_swings", "as_of": pivot_time},
            ),
        )

    fibonacci = _dict(evidence.get("fibonacci"))
    for item in fibonacci.get("levels") or []:
        row = _dict(item)
        ratio = row.get("ratio")
        kind = str(row.get("kind") or "level")
        _append(
            levels,
            _level(
                evidence_id=f"fibonacci:{kind}:{ratio}",
                label=f"Fib {ratio}",
                source_type="fibonacci",
                raw_price=row.get("price"),
                reference=reference,
                confirmation="confirmed_swing_anchors",
                strength="medium",
                confidence="medium",
                evidence_state="derived",
                source_ref={"type": "derived", "name": "tw_technical_fibonacci"},
            ),
        )

    anchored_vwap = _dict(evidence.get("anchored_vwap"))
    _append(
        levels,
        _level(
            evidence_id=f"anchored_vwap:{anchored_vwap.get('anchor_time') or 'latest'}",
            label="Swing 錨定 VWAP",
            source_type="anchored_vwap",
            raw_price=anchored_vwap.get("value"),
            reference=reference,
            confirmation="daily_bar_estimate",
            strength="medium",
            confidence=str(anchored_vwap.get("confidence") or "medium"),
            evidence_state="estimated",
            source_ref={"type": "derived", "name": "tw_technical_anchored_vwap"},
            limitations=anchored_vwap.get("limitations") or (),
        ),
    )

    breakout = _dict(evidence.get("breakout"))
    _append(
        levels,
        _level(
            evidence_id=str(breakout.get("breakout_event_id") or "breakout:latest"),
            label="突破／失敗門檻",
            source_type="breakout",
            raw_price=breakout.get("breakout_level") or breakout.get("level"),
            reference=reference,
            confirmation=str(breakout.get("confirmation_state") or "unknown"),
            strength="high",
            confidence="medium",
            evidence_state="derived",
            source_ref={"type": "derived", "name": "tw_technical_breakout"},
        ),
    )

    profile = _dict(evidence.get("volume_profile"))
    profile_limitations = (
        "Estimated volume concentration from daily OHLCV; not execution-grade cost distribution.",
        *(profile.get("limitations") or []),
    )
    for key, label in (("val", "估計價值區下緣"), ("poc", "估計成交密集價"), ("vah", "估計價值區上緣")):
        _append(
            levels,
            _level(
                evidence_id=f"volume_profile:{key}",
                label=label,
                source_type="volume_profile_estimate",
                raw_price=profile.get(key),
                reference=reference,
                confirmation="daily_ohlcv_estimate",
                strength="low",
                confidence="low",
                evidence_state="estimated",
                source_ref={
                    "type": "derived",
                    "name": "tw_technical_volume_profile",
                    "source_granularity": profile.get("source_granularity") or "daily_ohlcv",
                },
                limitations=profile_limitations,
            ),
        )
    return sorted(levels, key=lambda item: (item["price"], item["evidence_id"]))


def _method_family(source_type: str) -> str:
    if source_type.startswith("projected_ma"):
        return "moving_average"
    if source_type.startswith("range_") or source_type in {
        "donchian",
        "support_resistance",
        "breakout",
    }:
        return "price_structure"
    if source_type.startswith("swing_"):
        return "swing"
    if source_type == "bollinger":
        return "volatility_band"
    return source_type or "unknown"


def _raw_zone_side(*, lower: float, upper: float, reference: float) -> str:
    if lower <= reference <= upper:
        return "current"
    return "downside" if upper < reference else "upside"


def _zone_confidence(group: list[dict[str, Any]]) -> str:
    counts = {
        value: sum(str(item.get("confidence") or "low") == value for item in group)
        for value in ("high", "medium", "low")
    }
    if len(group) == 1:
        return str(group[0].get("confidence") or "low")
    if (
        counts["high"] >= 2
        and counts["high"] >= counts["medium"] + counts["low"]
    ):
        return "high"
    if counts["high"] + counts["medium"] > 0:
        return "medium"
    return "low"


def _zone_strength(
    group: list[dict[str, Any]],
    *,
    method_family_count: int,
    structural_evidence_count: int,
    estimated_evidence_count: int,
) -> str:
    if estimated_evidence_count == len(group):
        return "low"
    if method_family_count >= 3 and structural_evidence_count >= 2:
        return "high"
    if method_family_count >= 2 or structural_evidence_count >= 1:
        return "medium"
    return str(group[0].get("strength") or "low")


def _primary_evidence(
    group: list[dict[str, Any]],
    *,
    anchor: float,
) -> dict[str, Any]:
    confidence_rank = {"low": 0, "medium": 1, "high": 2}
    state_rank = {"estimated": 0, "derived": 1, "hypothetical": 2, "observed": 3}
    strength_rank = {"low": 0, "medium": 1, "high": 2}
    return min(
        group,
        key=lambda item: (
            -confidence_rank.get(str(item.get("confidence") or "low"), 0),
            -state_rank.get(str(item.get("evidence_state") or "unknown"), 0),
            -strength_rank.get(str(item.get("strength") or "low"), 0),
            abs(float(item["price"]) - anchor),
            str(item["evidence_id"]),
        ),
    )


def _padded_zone_bounds(
    *,
    evidence_lower: float,
    evidence_upper: float,
    reference: float,
    side: str,
    padding_pct: float,
    padding_ticks: int,
    max_width_pct: float,
) -> tuple[float, float, list[str]]:
    percent_padding = reference * max(padding_pct, 0) / 100
    tick_lower = shift_taiwan_stock_price_by_ticks(
        evidence_lower,
        -max(padding_ticks, 1),
    )
    tick_upper = shift_taiwan_stock_price_by_ticks(
        evidence_upper,
        max(padding_ticks, 1),
    )
    lower = normalize_taiwan_stock_price(
        max(min(tick_lower, evidence_lower - percent_padding), 0.01),
        direction="down",
    )
    upper = normalize_taiwan_stock_price(
        max(tick_upper, evidence_upper + percent_padding),
        direction="up",
    )
    limitations: list[str] = []

    raw_width = evidence_upper - evidence_lower
    max_width = max(raw_width, reference * max(max_width_pct, 0) / 100)
    if upper - lower > max_width:
        extra = max(max_width - raw_width, 0) / 2
        lower = normalize_taiwan_stock_price(
            max(evidence_lower - extra, 0.01),
            direction="down",
        )
        upper = normalize_taiwan_stock_price(
            evidence_upper + extra,
            direction="up",
        )
        limitations.append("Zone padding was capped by the backend maximum-width policy.")

    if side == "downside":
        reference_floor = shift_taiwan_stock_price_by_ticks(reference, -1)
        if upper > reference_floor:
            upper = max(evidence_upper, reference_floor)
            limitations.append("Zone padding was clipped below the completed reference price.")
    elif side == "upside":
        reference_ceiling = shift_taiwan_stock_price_by_ticks(reference, 1)
        if lower < reference_ceiling:
            lower = min(evidence_lower, reference_ceiling)
            limitations.append("Zone padding was clipped above the completed reference price.")

    if lower >= upper:
        lower = shift_taiwan_stock_price_by_ticks(evidence_lower, -1)
        upper = shift_taiwan_stock_price_by_ticks(evidence_upper, 1)
        limitations.append("Minimum one-tick research width was applied.")
    return lower, upper, limitations


def _compose_zone(
    group: list[dict[str, Any]],
    *,
    reference: float,
    padding_pct: float,
    padding_ticks: int,
    max_width_pct: float,
) -> dict[str, Any]:
    ordered = sorted(
        group,
        key=lambda item: (float(item["price"]), str(item["evidence_id"])),
    )
    prices = [float(item["price"]) for item in ordered]
    evidence_lower = min(prices)
    evidence_upper = max(prices)
    anchor = normalize_taiwan_stock_price(sum(prices) / len(prices))
    side = _raw_zone_side(
        lower=evidence_lower,
        upper=evidence_upper,
        reference=reference,
    )
    lower, upper, padding_limitations = _padded_zone_bounds(
        evidence_lower=evidence_lower,
        evidence_upper=evidence_upper,
        reference=reference,
        side=side,
        padding_pct=padding_pct,
        padding_ticks=padding_ticks,
        max_width_pct=max_width_pct,
    )
    method_families = {
        _method_family(str(item.get("source_type") or "")) for item in ordered
    }
    source_refs = {
        (
            str(_dict(item.get("source_ref")).get("type") or "unknown"),
            str(_dict(item.get("source_ref")).get("name") or "unknown"),
        )
        for item in ordered
    }
    structural_count = sum(
        _method_family(str(item.get("source_type") or ""))
        in {"price_structure", "swing"}
        for item in ordered
    )
    estimated_count = sum(
        str(item.get("evidence_state") or "unknown") == "estimated"
        for item in ordered
    )
    high_confidence_count = sum(
        str(item.get("confidence") or "low") == "high" for item in ordered
    )
    primary = _primary_evidence(ordered, anchor=anchor)
    evidence_ids = [str(item["evidence_id"]) for item in ordered]
    digest = hashlib.sha256("|".join(evidence_ids).encode("utf-8")).hexdigest()[:12]
    states = {str(item.get("evidence_state") or "unknown") for item in ordered}
    return {
        "zone_id": f"price-zone-{digest}",
        "evidence_lower_bound": evidence_lower,
        "evidence_upper_bound": evidence_upper,
        "lower_bound": lower,
        "upper_bound": upper,
        "anchor_price": anchor,
        "role": "pivot" if side == "current" else _role(anchor, reference, source_type="cluster"),
        "side": side,
        "tier_index": 0,
        "tier_label": "P0" if side == "current" else "",
        "strength": _zone_strength(
            ordered,
            method_family_count=len(method_families),
            structural_evidence_count=structural_count,
            estimated_evidence_count=estimated_count,
        ),
        "confidence": _zone_confidence(ordered),
        "distance_pct": _distance_pct(anchor, reference),
        "timeframes": sorted(
            {str(item.get("timeframe") or "unknown") for item in ordered}
        ),
        "evidence_state": next(iter(states)) if len(states) == 1 else "mixed",
        "evidence_count": len(ordered),
        "source_count": len(source_refs),
        "method_family_count": len(method_families),
        "strength_components": {
            "evidence_count": len(ordered),
            "method_family_count": len(method_families),
            "high_confidence_count": high_confidence_count,
            "structural_evidence_count": structural_count,
            "estimated_evidence_count": estimated_count,
        },
        "evidence_ids": evidence_ids,
        "labels": list(dict.fromkeys(str(item["label"]) for item in ordered)),
        "primary_evidence_id": str(primary["evidence_id"]),
        "primary_label": str(primary["label"]),
        "trigger_ids": [],
        "limitations": list(dict.fromkeys([
            *(
                str(limitation)
                for item in ordered
                for limitation in item.get("limitations") or []
                if limitation
            ),
            *padding_limitations,
        ])),
    }


def cluster_price_levels(
    levels: Iterable[Mapping[str, Any]],
    *,
    reference: float,
    threshold_pct: float,
    min_ticks: int = CLUSTER_MIN_TICKS,
    zone_padding_pct: float = ZONE_PADDING_PCT,
    zone_padding_ticks: int = ZONE_PADDING_TICKS,
    zone_merge_gap_ticks: int = ZONE_MERGE_GAP_TICKS,
    max_zone_width_pct: float = MAX_ZONE_WIDTH_PCT,
) -> list[dict[str, Any]]:
    ordered = sorted(
        (dict(item) for item in levels),
        key=lambda item: (float(item["price"]), str(item["evidence_id"])),
    )
    if not ordered:
        return []
    threshold = max(
        reference * max(threshold_pct, 0) / 100,
        taiwan_stock_tick_size(reference) * max(min_ticks, 1),
    )
    grouped: list[list[dict[str, Any]]] = []
    for item in ordered:
        if not grouped or float(item["price"]) - float(grouped[-1][0]["price"]) > threshold:
            grouped.append([item])
        else:
            grouped[-1].append(item)

    merged: list[list[dict[str, Any]]] = []
    for group in grouped:
        current_lower = min(float(item["price"]) for item in group)
        current_upper = max(float(item["price"]) for item in group)
        current_side = _raw_zone_side(
            lower=current_lower,
            upper=current_upper,
            reference=reference,
        )
        if merged:
            previous = merged[-1]
            previous_lower = min(float(item["price"]) for item in previous)
            previous_upper = max(float(item["price"]) for item in previous)
            previous_side = _raw_zone_side(
                lower=previous_lower,
                upper=previous_upper,
                reference=reference,
            )
            merge_ceiling = shift_taiwan_stock_price_by_ticks(
                previous_upper,
                max(zone_merge_gap_ticks, 0),
            )
            if previous_side == current_side and current_lower <= merge_ceiling:
                previous.extend(group)
                previous.sort(
                    key=lambda item: (float(item["price"]), str(item["evidence_id"]))
                )
                continue
        merged.append(list(group))

    zones = [
        _compose_zone(
            group,
            reference=reference,
            padding_pct=zone_padding_pct,
            padding_ticks=zone_padding_ticks,
            max_width_pct=max_zone_width_pct,
        )
        for group in merged
    ]
    upside = sorted(
        (zone for zone in zones if zone["side"] == "upside"),
        key=lambda zone: (zone["evidence_lower_bound"], zone["anchor_price"], zone["zone_id"]),
    )
    downside = sorted(
        (zone for zone in zones if zone["side"] == "downside"),
        key=lambda zone: (-zone["evidence_upper_bound"], -zone["anchor_price"], zone["zone_id"]),
    )
    for index, zone in enumerate(upside, start=1):
        zone["tier_index"] = index
        zone["tier_label"] = f"R{index}"
    for index, zone in enumerate(downside, start=1):
        zone["tier_index"] = index
        zone["tier_label"] = f"S{index}"
    return sorted(
        zones,
        key=lambda zone: (zone["evidence_lower_bound"], zone["anchor_price"], zone["zone_id"]),
    )


def _decision_zone_link(
    zones: list[dict[str, Any]],
    *,
    threshold_price: float | None,
) -> tuple[dict[str, Any] | None, str]:
    if threshold_price is None:
        return None, "threshold_missing"
    raw_candidates = [
        zone
        for zone in zones
        if float(zone["evidence_lower_bound"])
        <= threshold_price
        <= float(zone["evidence_upper_bound"])
    ]
    candidates = raw_candidates or [
        zone
        for zone in zones
        if float(zone["lower_bound"]) <= threshold_price <= float(zone["upper_bound"])
    ]
    if not candidates:
        return None, "threshold_outside_research_zones"
    selected = min(
        candidates,
        key=lambda zone: (
            abs(float(zone["anchor_price"]) - threshold_price),
            int(zone["tier_index"]),
            str(zone["zone_id"]),
        ),
    )
    return selected, (
        "threshold_within_raw_evidence_span"
        if raw_candidates
        else "threshold_within_research_zone"
    )


def _nearest(zones: list[dict[str, Any]], reference: float, *, upside: bool) -> dict[str, Any] | None:
    candidates = [
        zone for zone in zones
        if zone["side"] == ("upside" if upside else "downside")
    ]
    if not candidates:
        return None
    zone = min(
        candidates,
        key=lambda item: (int(item["tier_index"]), abs(float(item["anchor_price"]) - reference)),
    )
    return {
        key: zone[key]
        for key in (
            "zone_id",
            "anchor_price",
            "lower_bound",
            "upper_bound",
            "role",
            "side",
            "tier_index",
            "tier_label",
            "strength",
            "distance_pct",
        )
    }


def build_tw_stock_price_map(
    *,
    db: Session,
    stock_id: str,
    candidate_close: float | None = None,
    now: datetime | None = None,
    parameters: TechnicalAnalysisParameters | None = None,
) -> dict[str, Any]:
    normalized_stock_id = str(stock_id or "").strip()
    if not normalized_stock_id:
        raise ValueError("stock_id is required.")
    local_now = taiwan_now(now)
    resolved_parameters = parameters or get_technical_analysis_parameters()
    next_plan = build_tw_stock_next_session_plan(
        db=db,
        stock_id=normalized_stock_id,
        candidate_close=candidate_close,
        now=local_now,
        parameters=resolved_parameters,
    )
    reference = _number(next_plan.get("as_of_close"))
    cache_key = (
        _basis_cache_key(
            db,
            stock_id=normalized_stock_id,
            next_plan=next_plan,
        )
        if now is None
        else None
    )
    cached_basis = _read_basis_cache(cache_key) if cache_key is not None else None
    if cached_basis is not None:
        report, evidence, evidence_error = cached_basis
    else:
        report = build_stock_technical_report(
            db=db,
            stock_id=normalized_stock_id,
            timeframe="daily",
            include_intraday=False,
            include_volume_pace=False,
        )
        evidence = {}
        evidence_error = None
        if reference is not None and next_plan.get("status") != "not_applicable":
            try:
                corporate_history = get_taiwan_stock_event_history(
                    normalized_stock_id,
                    market=str(next_plan.get("market") or "") or None,
                    years=10,
                    max_results=200,
                    now=local_now,
                )
                evidence = build_tw_stock_price_map_evidence(
                    db=db,
                    stock_id=normalized_stock_id,
                    corporate_event_history=corporate_history,
                    to_date=None,
                )
            except Exception as exc:  # truthful partial projection; read path stays cache-only
                evidence_error = type(exc).__name__
        if cache_key is not None:
            _write_basis_cache(
                cache_key,
                report=report,
                evidence=evidence,
                evidence_error=evidence_error,
            )

    corporate_action = dict(_dict(_dict(evidence.get("indicators")).get("corporate_action")))
    levels = (
        _collect_levels(evidence=evidence, next_plan=next_plan, reference=reference)
        if reference is not None
        else []
    )
    zones = (
        cluster_price_levels(
            levels,
            reference=reference,
            threshold_pct=resolved_parameters.near_level_threshold_pct,
        )
        if reference is not None
        else []
    )
    warnings = list(dict.fromkeys([
        *(str(item) for item in next_plan.get("warnings") or []),
        *(str(item) for item in evidence.get("warnings") or []),
        *(str(item) for item in report.get("warnings") or []),
        *([f"Canonical technical evidence unavailable: {evidence_error}"] if evidence_error else []),
    ]))
    missing = list(dict.fromkeys([
        *(str(item) for item in next_plan.get("missing") or []),
        *(str(item) for item in evidence.get("missing") or []),
        *(str(item) for item in report.get("missing") or []),
        *(["technical_evidence"] if evidence_error else []),
    ]))
    plan_status = str(next_plan.get("status") or "missing")
    corporate_complete = corporate_action.get("coverage_status") == "complete"
    status = _resolve_price_map_status(
        plan_status=plan_status,
        reference_available=reference is not None,
        levels_available=bool(levels),
        evidence_status=str(evidence.get("status") or "missing"),
        corporate_complete=corporate_complete,
    )
    decision_usable = bool(
        next_plan.get("readiness", {}).get("decision_usable")
        and reference is not None
        and levels
        and corporate_complete
    )
    axis = _display_axis(reference)
    markers = (
        [
            {
                "kind": "completed_reference",
                "label": "完成日線參考價",
                "price": reference,
                "timeframe": "daily",
                "finalization": "completed_session",
                "decision_usable": decision_usable,
            }
        ]
        if reference is not None
        else []
    )
    decision_changes = _decision_changes(
        report,
        decision_usable=decision_usable,
        zones=zones,
    )
    evidence_timeframes = sorted(
        {str(item.get("timeframe") or "unknown") for item in levels}
    )
    basis_revision = _basis_revision(
        stock_id=normalized_stock_id,
        reference=reference,
        trade_date=next_plan.get("as_of_trade_date"),
        levels=levels,
    )
    candidate_projections = [
        {
            "period": int(item["period"]),
            "candidate_close": float(item["candidate_close"]),
            "projected_ma": float(item["projected_ma_at_candidate"]),
            "transition_price": float(item["normalized_transition_price"]),
            "relation": str(item["candidate_close_relation"]),
            "role": str(item["role_at_candidate_close"]),
        }
        for item in next_plan.get("levels") or []
        if item.get("candidate_close") is not None
        and item.get("projected_ma_at_candidate") is not None
    ]
    return {
        "kind": PRICE_MAP_KIND,
        "version": PRICE_MAP_VERSION,
        "market": str(next_plan.get("market") or "TW"),
        "stock_id": normalized_stock_id,
        "stock_name": next_plan.get("stock_name"),
        "status": status,
        "decision_usable": decision_usable,
        "generated_at": local_now,
        "basis_revision": basis_revision,
        "evidence_timeframes": evidence_timeframes,
        "reference": {
            "price": reference,
            "trade_date": next_plan.get("as_of_trade_date"),
            "finalization": "completed_session" if reference is not None else "missing",
            "authority": "resolved_canonical",
            "source_capability": "tw.daily.ohlcv",
            "freshness_status": _dict(next_plan.get("freshness")).get("status") or "missing",
        },
        "axis": axis,
        "markers": markers,
        "technical": {
            "headline": str(report.get("title") or "資料不足"),
            "summary": str(report.get("summary") or ""),
            "score": int(report.get("score") or 0),
            "value": report.get("value"),
            "value_label": str(report.get("value_label") or ""),
            "confidence": str(report.get("confidence") or "low"),
            "evidence_summary": [
                {
                    "key": row.get("key"),
                    "label": row.get("label"),
                    "display_value": row.get("display_value"),
                    "tone": row.get("tone"),
                    "description": row.get("description"),
                }
                for row in report.get("rows") or []
            ],
        },
        "methodology": {
            "id": METHODOLOGY_ID,
            "version": METHODOLOGY_VERSION,
            "owner": "TaiwanTechnicalService + StockPriceMap projection",
            "cluster_rule": "sorted_cluster_span_lte_threshold",
            "cluster_threshold_pct": resolved_parameters.near_level_threshold_pct,
            "cluster_min_ticks": CLUSTER_MIN_TICKS,
            "zone_padding_pct": ZONE_PADDING_PCT,
            "zone_padding_ticks": ZONE_PADDING_TICKS,
            "zone_merge_gap_ticks": ZONE_MERGE_GAP_TICKS,
            "max_zone_width_pct": MAX_ZONE_WIDTH_PCT,
            "side_rule": "raw_evidence_span_before_padding",
            "tier_rule": "nearest_outward_by_raw_evidence_span",
            "tick_rule": "TWSE/TPEX regular stock price bands",
            "price_basis": str(evidence.get("price_basis") or "raw_unadjusted"),
        },
        "parameter_contract": {
            **build_taiwan_technical_parameter_contract(parameters=resolved_parameters),
            "price_map": {
                "zone_padding_pct": ZONE_PADDING_PCT,
                "zone_padding_ticks": ZONE_PADDING_TICKS,
                "zone_merge_gap_ticks": ZONE_MERGE_GAP_TICKS,
                "max_zone_width_pct": MAX_ZONE_WIDTH_PCT,
            },
        },
        "levels": levels,
        "zones": zones,
        "nearest_upside": _nearest(zones, reference, upside=True) if reference is not None else None,
        "nearest_downside": _nearest(zones, reference, upside=False) if reference is not None else None,
        "decision_changes": decision_changes,
        "candidate": {
            "semantics": "hypothetical_target_session_close",
            "target_trade_date": next_plan.get("target_trade_date"),
            "candidate_close": next_plan.get("candidate_close"),
            "tick_normalized": candidate_close is not None,
            "projections": candidate_projections,
        },
        "corporate_action": corporate_action or {
            "coverage_status": "missing",
            "adjustment_applied": False,
            "absence_semantics": "unknown_outside_checked_range",
        },
        "missing": missing,
        "warnings": warnings,
        "limitations": list(dict.fromkeys([
            *(str(item) for item in next_plan.get("limitations") or []),
            "Price zones are research confluence areas, not executable orders or price forecasts.",
            "Volume-profile levels use daily OHLCV estimates and are not execution-grade cost distribution.",
            *([] if corporate_complete else ["Corporate-action coverage is incomplete; raw unadjusted price levels are decision-blocked."]),
        ])),
        "source_refs": [
            {"type": ref_type, "name": ref_name}
            for ref_type, ref_name in dict.fromkeys(
                (str(item.get("type")), str(item.get("name")))
                for item in [
                *(next_plan.get("source_refs") or []),
                *(evidence.get("source_refs") or []),
                {"type": "derived", "name": "app.market.stock_price_map"},
                ]
                if isinstance(item, Mapping)
            )
        ],
    }


__all__ = [
    "PRICE_MAP_KIND",
    "PRICE_MAP_VERSION",
    "build_tw_stock_price_map",
    "cluster_price_levels",
]
