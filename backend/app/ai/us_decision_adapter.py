from __future__ import annotations

from typing import Any


US_HORIZON_WEIGHTS = {
    "intraday": {
        "price_trend": 0.45,
        "volume": 0.25,
        "fundamentals": 0.10,
        "short_volume": 0.10,
        "source_health": 0.10,
    },
    "short": {
        "price_trend": 0.45,
        "volume": 0.25,
        "fundamentals": 0.10,
        "short_volume": 0.10,
        "source_health": 0.10,
    },
    "swing": {
        "price_trend": 0.40,
        "volume": 0.15,
        "fundamentals": 0.25,
        "short_volume": 0.10,
        "source_health": 0.10,
    },
    "long": {
        "price_trend": 0.20,
        "volume": 0.10,
        "fundamentals": 0.45,
        "short_volume": 0.05,
        "source_health": 0.20,
    },
}


def _numeric(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _clip(value: float, low: int = -100, high: int = 100) -> int:
    return int(max(low, min(high, round(value))))


def _horizon(value: str | None) -> str:
    normalized = (value or "swing").strip().lower()
    if normalized in {"today", "intraday"}:
        return "intraday"
    if normalized in {"short", "daily"}:
        return "short"
    if normalized in {"long", "position"}:
        return "long"
    return "swing"


def _daily_rows(context: dict[str, Any]) -> list[dict[str, Any]]:
    data = context.get("data") if isinstance(context.get("data"), dict) else {}
    rows = data.get("daily_prices") if isinstance(data.get("daily_prices"), list) else []
    return [row for row in rows if isinstance(row, dict)]


def _source_health(context: dict[str, Any]) -> dict[str, Any]:
    data = context.get("data") if isinstance(context.get("data"), dict) else {}
    health = data.get("source_health") if isinstance(data.get("source_health"), dict) else {}
    return health


def _source_health_entries(context: dict[str, Any]) -> list[dict[str, Any]]:
    entries = _source_health(context).get("entries")
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def _profile(context: dict[str, Any]) -> dict[str, Any]:
    summary = context.get("summary") if isinstance(context.get("summary"), dict) else {}
    profile = summary.get("profile") if isinstance(summary.get("profile"), dict) else {}
    if profile:
        return profile
    data = context.get("data") if isinstance(context.get("data"), dict) else {}
    stock = data.get("stock") if isinstance(data.get("stock"), dict) else {}
    return stock


def _sec_metric_count(context: dict[str, Any]) -> int:
    data = context.get("data") if isinstance(context.get("data"), dict) else {}
    sec = data.get("sec_fundamentals") if isinstance(data.get("sec_fundamentals"), dict) else {}
    try:
        return int(sec.get("metric_count") or 0)
    except (TypeError, ValueError):
        return 0


def _short_volume_rows(context: dict[str, Any]) -> list[dict[str, Any]]:
    data = context.get("data") if isinstance(context.get("data"), dict) else {}
    rows = data.get("short_volume") if isinstance(data.get("short_volume"), list) else []
    return [row for row in rows if isinstance(row, dict)]


def _component(key: str, score: int, weight: float, included: bool, summary: str) -> dict[str, Any]:
    return {
        "key": key,
        "score": score,
        "weight": weight,
        "included": included,
        "summary": summary,
    }


def _price_trend_component(rows: list[dict[str, Any]], weight: float) -> dict[str, Any]:
    latest = rows[0] if rows else {}
    previous = rows[1] if len(rows) > 1 else {}
    latest_close = _numeric(latest.get("close_price"))
    previous_close = _numeric(previous.get("close_price"))
    if latest_close is None or previous_close in (None, 0):
        return _component("price_trend", 0, weight, False, "Daily close comparison is unavailable.")

    change_pct = ((latest_close - float(previous_close)) / float(previous_close)) * 100
    score = _clip(change_pct * 4, -35, 35)
    return _component(
        "price_trend",
        score,
        weight,
        True,
        f"Close change {change_pct:.2f}% from previous local daily bar.",
    )


def _volume_component(rows: list[dict[str, Any]], weight: float) -> dict[str, Any]:
    if len(rows) < 4:
        return _component("volume", 0, weight, False, "Not enough daily rows for relative volume.")

    latest_volume = _numeric(rows[0].get("trade_volume"))
    prior_volumes = [
        volume
        for row in rows[1:6]
        if (volume := _numeric(row.get("trade_volume"))) is not None and volume > 0
    ]
    if latest_volume is None or not prior_volumes:
        return _component("volume", 0, weight, False, "Volume data is unavailable.")

    average_volume = sum(prior_volumes) / len(prior_volumes)
    ratio = latest_volume / average_volume if average_volume else 0
    if ratio >= 1.5:
        score = 12
    elif ratio >= 1.15:
        score = 6
    elif ratio <= 0.65:
        score = -6
    else:
        score = 0

    return _component(
        "volume",
        score,
        weight,
        True,
        f"Relative volume {ratio:.2f}x versus the prior {len(prior_volumes)} local bars.",
    )


def _fundamentals_component(context: dict[str, Any], weight: float) -> dict[str, Any]:
    profile = _profile(context)
    metric_count = _sec_metric_count(context)
    profit_margin = _numeric(profile.get("profit_margin"))
    pe_ratio = _numeric(profile.get("pe_ratio"))
    score = 0
    details: list[str] = []

    if metric_count:
        score += 8
        details.append(f"SEC metrics {metric_count}")
    if profit_margin is not None:
        if profit_margin >= 0.15:
            score += 8
        elif profit_margin < 0:
            score -= 10
        details.append(f"profit margin {profit_margin:.2f}")
    if pe_ratio is not None:
        if pe_ratio > 80:
            score -= 5
        elif 0 < pe_ratio <= 25:
            score += 3
        details.append(f"PE {pe_ratio:.2f}")

    included = bool(profile) or bool(metric_count)
    return _component(
        "fundamentals",
        _clip(score, -25, 25),
        weight,
        included,
        "; ".join(details) if details else "Profile and SEC fundamentals are unavailable.",
    )


def _short_volume_component(context: dict[str, Any], weight: float) -> dict[str, Any]:
    rows = _short_volume_rows(context)
    if not rows:
        return _component("short_volume", 0, weight, False, "FINRA short volume is unavailable.")

    latest = rows[0]
    ratio = _numeric(latest.get("short_ratio"))
    if ratio is None:
        return _component("short_volume", 0, weight, False, "Latest short ratio is unavailable.")

    if ratio >= 0.55:
        score = -12
    elif ratio >= 0.40:
        score = -6
    elif ratio <= 0.25:
        score = 4
    else:
        score = 0
    return _component(
        "short_volume",
        score,
        weight,
        True,
        f"Latest FINRA short ratio {ratio:.2%} on {latest.get('trade_date')}.",
    )


def _source_health_component(context: dict[str, Any], weight: float) -> dict[str, Any]:
    entries = _source_health_entries(context)
    if not entries:
        return _component("source_health", -6, weight, False, "US source health is unavailable.")

    critical = {
        "daily_price",
        "profile",
        "sec_facts",
    }
    stale_count = sum(1 for entry in entries if entry.get("status") == "stale")
    empty_critical = sum(
        1
        for entry in entries
        if entry.get("resource") in critical and entry.get("status") == "empty"
    )
    score = -(stale_count * 6) - (empty_critical * 8)
    if score == 0:
        score = 8
    return _component(
        "source_health",
        _clip(score, -30, 12),
        weight,
        True,
        f"Source health stale={stale_count}, empty critical={empty_critical}.",
    )


def build_us_stock_decision_adapter(
    context: dict[str, Any],
    requested_horizon: str,
) -> dict[str, Any]:
    horizon = _horizon(requested_horizon)
    weights = US_HORIZON_WEIGHTS[horizon]
    rows = _daily_rows(context)
    components = [
        _price_trend_component(rows, weights["price_trend"]),
        _volume_component(rows, weights["volume"]),
        _fundamentals_component(context, weights["fundamentals"]),
        _short_volume_component(context, weights["short_volume"]),
        _source_health_component(context, weights["source_health"]),
    ]
    weighted_score = sum(component["score"] * component["weight"] for component in components)
    missing = context.get("missing") if isinstance(context.get("missing"), list) else []
    warnings = context.get("warnings") if isinstance(context.get("warnings"), list) else []
    weighted_score -= min(len(missing) * 3, 18)
    weighted_score -= min(len(warnings) * 2, 12)
    score = _clip(weighted_score)

    if not rows:
        stance = "insufficient_data"
        title = "美股資料不足"
        confidence = "low"
    elif score >= 18:
        stance = "bullish"
        title = "美股偏強"
        confidence = "high" if score >= 30 and not missing else "medium"
    elif score <= -12:
        stance = "bearish"
        title = "美股偏弱"
        confidence = "medium" if rows else "low"
    else:
        stance = "neutral"
        title = "美股中性"
        confidence = "medium" if not missing else "low"

    data_limits = [
        component["summary"]
        for component in components
        if not component["included"]
    ]
    data_limits.extend(str(item) for item in missing[:5])

    return {
        "kind": "us_stock_decision_adapter_v1",
        "requested_horizon": requested_horizon,
        "selected_horizon": horizon,
        "selected_timeframe": "us_daily",
        "selected_score": score,
        "selected_title": title,
        "selected_confidence": confidence,
        "stance": stance,
        "components": components,
        "data_limits": list(dict.fromkeys(data_limits)),
    }


__all__ = ["build_us_stock_decision_adapter"]
