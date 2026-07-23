from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
import math
from typing import Any

from sqlalchemy.orm import Session

from app.ai.evidence_passport import build_evidence_passport
from app.db.models import StockMaster, USDailyPrice, USWatchlistGroup, USWatchlistItem
from app.market.adr_parity import build_adr_parity_report, get_adr_mapping
from app.market.calendar_status import expected_us_trade_date
from app.market.fx_flow_context import build_fx_flow_context
from app.us_market import service as us_market_service


def expected_us_daily_price_date() -> date:
    expected_date = expected_us_trade_date("us_daily_price")
    if expected_date is None:
        return date.today()

    return expected_date


INDEX_FACTORS = {
    "^GSPC": {
        "label": "S&P 500",
        "role": "market",
        "score_cap": 8.0,
    },
    "^IXIC": {
        "label": "Nasdaq Composite",
        "role": "growth",
        "score_cap": 8.0,
    },
    "^DJI": {
        "label": "Dow Jones",
        "role": "cyclical",
        "score_cap": 8.0,
    },
    "^SOX": {
        "label": "費城半導體",
        "role": "semiconductor",
        "score_cap": 10.0,
    },
    "QQQ": {
        "label": "Nasdaq 100 ETF",
        "role": "growth_etf",
        "score_cap": 10.0,
    },
    "SMH": {
        "label": "半導體 ETF",
        "role": "semiconductor_etf",
        "score_cap": 10.0,
    },
    "TSM": {
        "label": "台積電 ADR",
        "role": "taiwan_adr",
        "score_cap": 12.0,
    },
    "NVDA": {
        "label": "NVIDIA",
        "role": "ai_semiconductor",
        "score_cap": 12.0,
    },
    "MU": {
        "label": "Micron",
        "role": "memory",
        "score_cap": 12.0,
    },
}


TECH_INDUSTRY_CODES = {"24", "25", "26", "27", "28", "29", "30", "31"}
SEMICONDUCTOR_TEXT_HINTS = (
    "半導體",
    "晶圓",
    "晶片",
    "矽",
    "積體電路",
    "台積",
    "聯電",
    "世界",
    "力積",
    "日月光",
)
MEMORY_TEXT_HINTS = (
    "記憶體",
    "南亞科",
    "華邦",
    "威剛",
    "群聯",
    "十銓",
    "創見",
)
ELECTRONICS_TEXT_HINTS = (
    "電子",
    "電腦",
    "週邊",
    "光電",
    "通信",
    "網路",
    "資訊",
    "電機",
    "零組件",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _pct_change(current: Any, previous: Any) -> float | None:
    if not _finite(current) or not _finite(previous) or previous == 0:
        return None
    return round(((current - previous) / previous) * 100, 4)


def _round(value: Any, digits: int = 4) -> float | None:
    if not _finite(value):
        return None
    return round(float(value), digits)


def _tone(value: Any) -> str:
    if not _finite(value):
        return "neutral"
    if value > 0:
        return "positive"
    if value < 0:
        return "negative"
    return "neutral"


def _clamp(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


def _latest_two_daily_rows(db: Session, symbol: str) -> list[USDailyPrice]:
    rows = (
        db.query(USDailyPrice)
        .filter(USDailyPrice.symbol == symbol)
        .order_by(USDailyPrice.trade_date.desc(), USDailyPrice.updated_at.desc(), USDailyPrice.id.desc())
        .limit(8)
        .all()
    )

    unique_by_date: list[USDailyPrice] = []
    seen_dates: set[date] = set()
    for row in rows:
        if row.trade_date in seen_dates or row.close_price is None:
            continue
        unique_by_date.append(row)
        seen_dates.add(row.trade_date)
        if len(unique_by_date) == 2:
            break

    return unique_by_date


def _factor_from_symbol(
    db: Session,
    *,
    symbol: str,
    label: str,
    role: str,
    weight: float,
    score_cap: float,
    source: str,
) -> tuple[dict[str, Any] | None, str | None]:
    rows = _latest_two_daily_rows(db, symbol)
    if len(rows) < 2:
        return None, f"us_daily_price.{symbol}"

    latest, previous = rows[0], rows[1]
    change = (
        latest.close_price - previous.close_price
        if _finite(latest.close_price) and _finite(previous.close_price)
        else None
    )
    change_pct = _pct_change(latest.close_price, previous.close_price)
    if change_pct is None:
        return None, f"us_daily_price.{symbol}.change_pct"

    score_change_pct = _clamp(change_pct, score_cap)
    return (
        {
            "key": symbol.replace("^", "").lower(),
            "symbol": symbol,
            "label": label,
            "role": role,
            "trade_date": latest.trade_date,
            "close": _round(latest.close_price),
            "previous_close": _round(previous.close_price),
            "change": _round(change),
            "change_pct": _round(change_pct),
            "score_change_pct": _round(score_change_pct),
            "weight": weight,
            "weighted_contribution": _round(score_change_pct * weight),
            "tone": _tone(change_pct),
            "source": source,
            "provider": latest.provider,
        },
        None,
    )


def _basket_from_group(
    db: Session,
    *,
    group_name: str,
    role: str,
    weight: float,
) -> tuple[dict[str, Any] | None, str | None]:
    group = (
        db.query(USWatchlistGroup)
        .filter(USWatchlistGroup.group_name == group_name, USWatchlistGroup.is_active.is_(True))
        .first()
    )
    if group is None:
        return None, f"us_watchlist_group.{group_name}"

    items = (
        db.query(USWatchlistItem)
        .filter(USWatchlistItem.group_id == group.id, USWatchlistItem.enabled.is_(True))
        .order_by(USWatchlistItem.priority.asc(), USWatchlistItem.symbol.asc())
        .all()
    )
    if not items:
        return None, f"us_watchlist_item.{group_name}"

    valid: list[dict[str, Any]] = []
    missing_count = 0
    for item in items:
        rows = _latest_two_daily_rows(db, item.symbol)
        if len(rows) < 2:
            missing_count += 1
            continue
        latest, previous = rows[0], rows[1]
        change_pct = _pct_change(latest.close_price, previous.close_price)
        if change_pct is None:
            missing_count += 1
            continue
        valid.append(
            {
                "symbol": item.symbol,
                "trade_date": latest.trade_date,
                "change_pct": change_pct,
                "score_change_pct": _clamp(change_pct, 12.0),
            }
        )

    if not valid:
        return None, f"us_watchlist_item.{group_name}.daily_price"

    average_change_pct = sum(item["change_pct"] for item in valid) / len(valid)
    average_score_change_pct = sum(item["score_change_pct"] for item in valid) / len(valid)
    latest_dates = [item["trade_date"] for item in valid]
    top_symbols = sorted(valid, key=lambda item: item["change_pct"], reverse=True)[:3]
    bottom_symbols = sorted(valid, key=lambda item: item["change_pct"])[:3]

    return (
        {
            "group_id": group.id,
            "group_name": group.group_name,
            "role": role,
            "trade_date": max(latest_dates),
            "symbol_count": len(items),
            "valid_count": len(valid),
            "missing_count": missing_count,
            "average_change_pct": _round(average_change_pct),
            "score_change_pct": _round(average_score_change_pct),
            "weight": weight,
            "weighted_contribution": _round(average_score_change_pct * weight),
            "tone": _tone(average_change_pct),
            "top_symbols": [
                {"symbol": item["symbol"], "change_pct": _round(item["change_pct"])}
                for item in top_symbols
            ],
            "bottom_symbols": [
                {"symbol": item["symbol"], "change_pct": _round(item["change_pct"])}
                for item in bottom_symbols
            ],
            "source": "us_watchlist_group",
        },
        None,
    )


def _stock_text(stock: StockMaster) -> str:
    return " ".join(
        value
        for value in (
            stock.stock_id,
            stock.stock_name,
            stock.market,
            stock.instrument_type,
            stock.industry,
            stock.category,
        )
        if value
    )


def _matches_any(text: str, hints: tuple[str, ...]) -> bool:
    return any(hint in text for hint in hints)


def _resolve_tw_mapping(stock: StockMaster) -> dict[str, Any]:
    industry = (stock.industry or "").strip()
    category = (stock.category or "").strip()
    text = _stock_text(stock)
    profiles: list[str] = []
    reasons: list[str] = []

    if industry == "24" or _matches_any(text, SEMICONDUCTOR_TEXT_HINTS):
        profiles.append("semiconductor")
        reasons.append("台股產業/名稱符合半導體鏈")

    if _matches_any(text, MEMORY_TEXT_HINTS):
        profiles.append("memory")
        reasons.append("名稱符合記憶體/儲存鏈")

    if industry in TECH_INDUSTRY_CODES or _matches_any(text, ELECTRONICS_TEXT_HINTS):
        profiles.append("technology")
        reasons.append("台股產業/名稱符合電子科技族群")

    if not profiles:
        profiles.append("general")
        reasons.append("未命中特定科技鏈，採用美股大盤組合")

    return {
        "stock_id": stock.stock_id,
        "stock_name": stock.stock_name,
        "market": stock.market,
        "industry": stock.industry,
        "category": stock.category,
        "profiles": list(dict.fromkeys(profiles)),
        "reason": "；".join(dict.fromkeys(reasons)),
    }


def _factor_weights_for_mapping(mapping: dict[str, Any]) -> tuple[dict[str, float], dict[str, float]]:
    profiles = set(mapping.get("profiles") or [])
    factor_weights = {
        "^GSPC": 0.36,
        "^DJI": 0.20,
        "^IXIC": 0.24,
        "QQQ": 0.20,
    }
    basket_weights: dict[str, float] = {}

    if "technology" in profiles:
        factor_weights = {
            "^GSPC": 0.18,
            "^IXIC": 0.24,
            "QQQ": 0.18,
            "^SOX": 0.16,
            "SMH": 0.12,
            "TSM": 0.12,
        }
        basket_weights = {
            "ETF_科技": 0.12,
        }

    if "semiconductor" in profiles:
        factor_weights = {
            "^GSPC": 0.10,
            "^IXIC": 0.15,
            "QQQ": 0.10,
            "^SOX": 0.24,
            "SMH": 0.18,
            "TSM": 0.15,
            "NVDA": 0.08,
        }
        basket_weights = {
            "半導體_GPU_ASIC": 0.10,
            "半導體設備_量測": 0.08,
            "晶圓製造_IDM": 0.10,
            "ETF_科技": 0.06,
        }

    if "memory" in profiles:
        factor_weights = {
            "^GSPC": 0.08,
            "^IXIC": 0.14,
            "QQQ": 0.08,
            "^SOX": 0.20,
            "SMH": 0.14,
            "TSM": 0.08,
            "NVDA": 0.08,
            "MU": 0.20,
        }
        basket_weights = {
            "記憶體_儲存": 0.18,
            "半導體_GPU_ASIC": 0.08,
            "ETF_科技": 0.05,
        }

    return factor_weights, basket_weights


def _required_factor_symbols(mapping: dict[str, Any], *, max_symbols: int = 8) -> list[dict[str, Any]]:
    factor_weights, _basket_weights = _factor_weights_for_mapping(mapping)
    limit = max(max_symbols, 1)
    ranked = sorted(
        factor_weights.items(),
        key=lambda item: (-item[1], item[0]),
    )
    symbols: list[dict[str, Any]] = []
    direct_mapping = get_adr_mapping(str(mapping.get("stock_id") or ""))
    if direct_mapping is not None:
        symbols.append(
            {
                "symbol": direct_mapping.adr_symbol,
                "label": direct_mapping.adr_name,
                "role": "direct_adr",
                "weight": factor_weights.get(direct_mapping.adr_symbol, 0.0),
            }
        )

    for symbol, weight in ranked:
        if any(item["symbol"] == symbol for item in symbols):
            continue
        spec = INDEX_FACTORS[symbol]
        symbols.append(
            {
                "symbol": symbol,
                "label": spec["label"],
                "role": spec["role"],
                "weight": weight,
            }
        )
        if len(symbols) >= limit:
            break
    return symbols[:limit]


def scan_us_overnight_impact_gaps(
    db: Session,
    stock_id: str,
    *,
    max_symbols: int = 8,
) -> dict[str, Any]:
    normalized_stock_id = stock_id.strip()
    stock = db.query(StockMaster).filter(StockMaster.stock_id == normalized_stock_id).first()
    if stock is None:
        raise ValueError(f"Stock not found: {normalized_stock_id}")

    mapping = _resolve_tw_mapping(stock)
    required_symbols = _required_factor_symbols(mapping, max_symbols=max_symbols)
    expected_trade_date = expected_us_daily_price_date()
    symbol_status: list[dict[str, Any]] = []
    refresh_symbols: list[str] = []
    missing: list[str] = []

    for item in required_symbols:
        symbol = str(item["symbol"])
        rows = _latest_two_daily_rows(db, symbol)
        latest_date = rows[0].trade_date if rows else None
        previous_date = rows[1].trade_date if len(rows) >= 2 else None

        if len(rows) < 2:
            status = "missing"
            is_current = False
        elif latest_date < expected_trade_date:
            status = "stale"
            is_current = False
        else:
            status = "current"
            is_current = True

        if not is_current:
            refresh_symbols.append(symbol)
            missing.append(f"us_daily_price.{symbol}")

        symbol_status.append(
            {
                **item,
                "status": status,
                "is_current": is_current,
                "latest": _json_value(latest_date),
                "previous": _json_value(previous_date),
                "expected": expected_trade_date.isoformat(),
            }
        )

    warnings: list[str] = []
    if refresh_symbols:
        warnings.append(
            "美股隔夜影響核心因素資料缺漏或過期："
            + ", ".join(refresh_symbols[:6])
            + ("..." if len(refresh_symbols) > 6 else "")
        )

    return {
        "kind": "us_overnight_tw_impact_freshness",
        "scope": {
            "target": {
                "type": "tw_stock",
                "id": normalized_stock_id,
                "market": "TW",
            }
        },
        "stock_id": normalized_stock_id,
        "stock_name": stock.stock_name,
        "mapping": mapping,
        "is_current": not refresh_symbols,
        "refresh_recommended": bool(refresh_symbols),
        "refresh_symbols": refresh_symbols,
        "symbol_status": symbol_status,
        "missing": _dedupe(missing),
        "warnings": warnings,
        "expected_dates": {
            "us_daily_price": expected_trade_date.isoformat(),
        },
    }


def _normalize_weighted_items(items: list[dict[str, Any]]) -> tuple[float | None, float]:
    valid = [
        item
        for item in items
        if _finite(item.get("score_change_pct")) and _finite(item.get("weight")) and item["weight"] > 0
    ]
    total_weight = sum(item["weight"] for item in valid)
    if total_weight <= 0:
        return None, 0.0

    weighted_change = 0.0
    for item in valid:
        normalized_weight = item["weight"] / total_weight
        item["normalized_weight"] = _round(normalized_weight, 4)
        item["weighted_contribution"] = _round(item["score_change_pct"] * normalized_weight)
        weighted_change += item["score_change_pct"] * normalized_weight

    return round(weighted_change, 4), total_weight


def _stance_from_change(value: float | None) -> str:
    if not _finite(value):
        return "unknown"
    if value >= 1.25:
        return "strong_risk_on"
    if value >= 0.35:
        return "risk_on"
    if value <= -1.25:
        return "strong_risk_off"
    if value <= -0.35:
        return "risk_off"
    return "neutral"


def _title_from_stance(stance: str, mapping: dict[str, Any]) -> str:
    profile_label = (
        "記憶體鏈"
        if "memory" in set(mapping.get("profiles") or [])
        else "半導體鏈"
        if "semiconductor" in set(mapping.get("profiles") or [])
        else "科技股"
        if "technology" in set(mapping.get("profiles") or [])
        else "台股"
    )
    if stance == "strong_risk_on":
        return f"美股隔夜明顯偏多，{profile_label}順風"
    if stance == "risk_on":
        return f"美股隔夜偏多，{profile_label}略有支撐"
    if stance == "strong_risk_off":
        return f"美股隔夜明顯偏空，{profile_label}壓力較重"
    if stance == "risk_off":
        return f"美股隔夜偏空，{profile_label}需保守觀察"
    if stance == "neutral":
        return f"美股隔夜中性，{profile_label}方向未明"
    return "美股隔夜資料不足"


def _summary(
    *,
    stance: str,
    weighted_change_pct: float | None,
    top_item: dict[str, Any] | None,
    as_of: date | None,
) -> str:
    if weighted_change_pct is None:
        return "缺少足夠美股日線資料，暫不產生隔夜影響判斷"

    date_text = as_of.isoformat() if as_of else "未知日期"
    direction = {
        "strong_risk_on": "明顯偏多",
        "risk_on": "偏多",
        "strong_risk_off": "明顯偏空",
        "risk_off": "偏空",
        "neutral": "中性",
    }.get(stance, "資料不足")
    lead_text = ""
    if top_item is not None:
        lead_text = f"，主要貢獻因子為 {top_item.get('label') or top_item.get('group_name')}"
    return f"{date_text} 美股隔夜映射為{direction}，加權變動 {weighted_change_pct:+.2f}%{lead_text}"


def _stale_summary(
    *,
    as_of: date | None,
    expected_trade_date: date,
    refresh_attempted: bool,
) -> str:
    date_text = as_of.isoformat() if as_of else "未知日期"
    prefix = "已嘗試刷新，但" if refresh_attempted else ""
    return (
        f"{prefix}美股日線最新日期 {date_text}，落後預期 {expected_trade_date.isoformat()}；"
        "暫不產生隔夜多空判斷。"
    )


def _confidence(
    *,
    weighted_change_pct: float | None,
    valid_weight: float,
    as_of: date | None,
    expected_trade_date: date,
    missing: list[str],
    warnings: list[str],
) -> str:
    if weighted_change_pct is None or valid_weight < 0.45:
        return "low"
    if missing and valid_weight < 0.75:
        return "low"
    if as_of is None or as_of < expected_trade_date:
        return "medium" if valid_weight >= 0.75 else "low"
    if warnings or valid_weight < 0.9:
        return "medium"
    return "high"


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def build_us_overnight_impact_report(
    db: Session,
    stock_id: str,
    *,
    suppress_stale_signal: bool = False,
    refresh_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_stock_id = stock_id.strip()
    stock = db.query(StockMaster).filter(StockMaster.stock_id == normalized_stock_id).first()
    if stock is None:
        raise ValueError(f"Stock not found: {normalized_stock_id}")

    mapping = _resolve_tw_mapping(stock)
    factor_weights, basket_weights = _factor_weights_for_mapping(mapping)
    factors: list[dict[str, Any]] = []
    baskets: list[dict[str, Any]] = []
    missing: list[str] = []
    warnings: list[str] = []

    for symbol, weight in factor_weights.items():
        spec = INDEX_FACTORS[symbol]
        factor, missing_key = _factor_from_symbol(
            db,
            symbol=symbol,
            label=spec["label"],
            role=spec["role"],
            weight=weight,
            score_cap=spec["score_cap"],
            source="us_daily_price",
        )
        if factor is not None:
            factors.append(factor)
        elif missing_key:
            missing.append(missing_key)

    basket_roles = {
        "ETF_科技": "technology_etf_basket",
        "半導體_GPU_ASIC": "semiconductor_basket",
        "半導體設備_量測": "semiconductor_equipment_basket",
        "晶圓製造_IDM": "foundry_basket",
        "記憶體_儲存": "memory_storage_basket",
    }
    for group_name, weight in basket_weights.items():
        basket, missing_key = _basket_from_group(
            db,
            group_name=group_name,
            role=basket_roles.get(group_name, "us_watchlist_basket"),
            weight=weight,
        )
        if basket is not None:
            baskets.append(basket)
        elif missing_key:
            missing.append(missing_key)

    all_items = factors + baskets
    weighted_change_pct, valid_weight = _normalize_weighted_items(all_items)
    contribution_items = [
        item
        for item in all_items
        if _finite(item.get("weighted_contribution"))
    ]
    top_item = (
        max(contribution_items, key=lambda item: abs(float(item.get("weighted_contribution") or 0)))
        if contribution_items
        else None
    )
    as_of_values = [
        item.get("trade_date")
        for item in all_items
        if isinstance(item.get("trade_date"), date)
    ]
    as_of = max(as_of_values) if as_of_values else None
    expected_trade_date = expected_us_daily_price_date()
    generated_at = _now()
    adr_parity = build_adr_parity_report(
        db,
        normalized_stock_id,
        stock_name=stock.stock_name,
        expected_adr_trade_date=expected_trade_date,
        generated_at=generated_at,
    )
    fx_flow_context = build_fx_flow_context(
        db,
        normalized_stock_id,
        generated_at=generated_at,
    )
    stale_dates = [
        value
        for value in as_of_values
        if isinstance(value, date) and value < expected_trade_date
    ]
    if stale_dates:
        warnings.append(
            f"美股日線最新日期 {max(stale_dates).isoformat()}，落後預期 {expected_trade_date.isoformat()}。"
        )
    if as_of_values:
        date_counts = Counter(as_of_values)
        if len(date_counts) > 1:
            warnings.append("美股因素日期不一致；分數以各因素最新可用資料計算。")

    stance = _stance_from_change(weighted_change_pct)
    score = (
        0
        if weighted_change_pct is None
        else int(round(max(-100.0, min(100.0, weighted_change_pct * 20.0))))
    )
    confidence = _confidence(
        weighted_change_pct=weighted_change_pct,
        valid_weight=valid_weight,
        as_of=as_of,
        expected_trade_date=expected_trade_date,
        missing=missing,
        warnings=warnings,
    )
    source_refs = [
        {"type": "table", "name": "stock_master"},
        {"type": "table", "name": "us_daily_price", "provider": "yahoo_chart"},
        {"type": "table", "name": "us_watchlist_group"},
        {"type": "table", "name": "us_watchlist_item"},
        {"type": "derived", "name": "app.market.overnight_impact"},
    ]
    if adr_parity is not None:
        source_refs.extend(adr_parity.get("source_refs") or [])
    source_refs.extend(fx_flow_context.get("source_refs") or [])
    is_current = bool(as_of_values) and not stale_dates and not missing
    freshness = {
        "expected_trade_date": expected_trade_date.isoformat(),
        "latest_trade_date": as_of.isoformat() if as_of else None,
        "is_current": is_current,
        "valid_weight": _round(valid_weight),
    }
    if refresh_metadata:
        freshness["refresh"] = refresh_metadata

    reported_stance = stance
    reported_score = score
    reported_weighted_change_pct = weighted_change_pct
    reported_confidence = confidence
    reported_title = _title_from_stance(stance, mapping)
    reported_summary = _summary(
        stance=stance,
        weighted_change_pct=weighted_change_pct,
        top_item=top_item,
        as_of=as_of,
    )
    reported_missing = _dedupe(missing)

    if suppress_stale_signal and not is_current:
        reported_stance = "unknown"
        reported_score = 0
        reported_weighted_change_pct = None
        reported_confidence = "low"
        reported_title = "美股隔夜資料需更新"
        reported_summary = _stale_summary(
            as_of=as_of,
            expected_trade_date=expected_trade_date,
            refresh_attempted=bool(refresh_metadata and refresh_metadata.get("attempted")),
        )
        reported_missing = _dedupe([*missing, "us_overnight_tw_impact_stale"])

    report = {
        "kind": "us_overnight_tw_impact",
        "stock_id": normalized_stock_id,
        "stock_name": stock.stock_name,
        "as_of": as_of,
        "generated_at": generated_at,
        "stance": reported_stance,
        "title": reported_title,
        "summary": reported_summary,
        "score": reported_score,
        "weighted_change_pct": _round(reported_weighted_change_pct),
        "confidence": reported_confidence,
        "tw_mapping": mapping,
        "adr_parity": adr_parity,
        "fx_flow_context": fx_flow_context,
        "factors": factors,
        "baskets": baskets,
        "missing": reported_missing,
        "warnings": _dedupe(warnings),
        "source_refs": source_refs,
        "freshness": freshness,
    }
    report["evidence_passport"] = build_evidence_passport(
        kind=report["kind"],
        as_of=report["as_of"],
        source_refs=source_refs,
        missing=report["missing"],
        warnings=report["warnings"],
        freshness=freshness,
        analysis={
            "stance": reported_stance,
            "score": reported_score,
            "weighted_change_pct": reported_weighted_change_pct,
            "mapping_profiles": mapping.get("profiles"),
            "adr_parity_status": (
                adr_parity.get("status") if adr_parity is not None else "not_applicable"
            ),
            "adr_implied_gap_pct": (
                adr_parity.get("implied_gap_pct") if adr_parity is not None else None
            ),
            "fx_flow_status": fx_flow_context.get("status"),
            "fx_flow_signal": fx_flow_context.get("signal"),
        },
        confidence=reported_confidence,
    )
    report["as_of"] = _json_value(report["as_of"])
    report["generated_at"] = _json_value(report["generated_at"])
    for item in factors + baskets:
        item["trade_date"] = _json_value(item.get("trade_date"))

    return report


def ensure_current_us_overnight_impact_report(
    db: Session,
    stock_id: str,
    *,
    max_refresh_symbols: int = 8,
    provider: str = "auto",
    outputsize: str = "compact",
) -> dict[str, Any]:
    max_symbols = max(1, min(max_refresh_symbols, 8))
    initial_gaps = scan_us_overnight_impact_gaps(
        db=db,
        stock_id=stock_id,
        max_symbols=max_symbols,
    )
    refresh_symbols = list(initial_gaps.get("refresh_symbols") or [])[:max_symbols]
    refresh_metadata: dict[str, Any] = {
        "attempted": bool(refresh_symbols),
        "symbols": refresh_symbols,
        "results": [],
        "errors": [],
    }

    for symbol in refresh_symbols:
        try:
            result = us_market_service.refresh_us_daily_prices(
                db=db,
                symbol=symbol,
                outputsize=outputsize,
                adjusted=False,
                provider=provider,
            )
            refresh_metadata["results"].append(
                {
                    "symbol": symbol,
                    "status": result.get("status"),
                    "provider": result.get("provider"),
                    "fetched_count": result.get("fetched_count"),
                    "inserted_count": result.get("inserted_count"),
                    "updated_count": result.get("updated_count"),
                }
            )
        except Exception as exc:  # pragma: no cover - exercised through route-level behavior.
            refresh_metadata["errors"].append(
                {
                    "symbol": symbol,
                    "message": str(exc),
                }
            )

    refreshed_gaps = scan_us_overnight_impact_gaps(
        db=db,
        stock_id=stock_id,
        max_symbols=max_symbols,
    )
    refresh_metadata["remaining_symbols"] = list(refreshed_gaps.get("refresh_symbols") or [])
    refresh_metadata["is_current_after_refresh"] = bool(refreshed_gaps.get("is_current"))

    return build_us_overnight_impact_report(
        db=db,
        stock_id=stock_id,
        suppress_stale_signal=True,
        refresh_metadata=refresh_metadata,
    )
