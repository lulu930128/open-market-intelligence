from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.db.models import CrossMarketRelation, StockMaster
from app.market.adr_parity import AdrMapping, get_adr_mapping, resolve_adr_mapping
from app.market.cross_market.proxy_signal_engine import PROXY_BENCHMARK_RULES
from app.market.cross_market.relation_store import build_relation_registry_read


CROSS_MARKET_OVERNIGHT_CAPABILITY = "cross_market.overnight"
CROSS_MARKET_RELATIONS_CAPABILITY = "cross_market.relations"
CROSS_MARKET_PARITY_CAPABILITY = "cross_market.parity"
SUPPORTED_CROSS_MARKET_CAPABILITIES = (
    CROSS_MARKET_OVERNIGHT_CAPABILITY,
    CROSS_MARKET_RELATIONS_CAPABILITY,
    CROSS_MARKET_PARITY_CAPABILITY,
)

INDEX_FACTORS = {
    "^GSPC": {"label": "S&P 500", "role": "market", "score_cap": 8.0},
    "^IXIC": {
        "label": "Nasdaq Composite",
        "role": "growth",
        "score_cap": 8.0,
    },
    "^DJI": {"label": "Dow Jones", "role": "cyclical", "score_cap": 8.0},
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
    "TSM": {"label": "台積電 ADR", "role": "taiwan_adr", "score_cap": 12.0},
    "NVDA": {
        "label": "NVIDIA",
        "role": "ai_semiconductor",
        "score_cap": 12.0,
    },
    "MU": {"label": "Micron", "role": "memory", "score_cap": 12.0},
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


def normalize_requested_capabilities(
    values: Iterable[str] | None,
) -> tuple[str, ...]:
    if values is None:
        return SUPPORTED_CROSS_MARKET_CAPABILITIES
    requested = tuple(
        dict.fromkeys(str(value).strip() for value in values if str(value).strip())
    )
    unsupported = sorted(set(requested) - set(SUPPORTED_CROSS_MARKET_CAPABILITIES))
    if unsupported:
        raise ValueError(
            "unsupported cross-market capabilities: " + ", ".join(unsupported)
        )
    return requested


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


def resolve_tw_overnight_mapping(stock: StockMaster) -> dict[str, Any]:
    industry = (stock.industry or "").strip()
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


def factor_weights_for_mapping(
    mapping: dict[str, Any],
) -> tuple[dict[str, float], dict[str, float]]:
    profiles = set(mapping.get("profiles") or [])
    factor_weights = {"^GSPC": 0.36, "^DJI": 0.20, "^IXIC": 0.24, "QQQ": 0.20}
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
        basket_weights = {"ETF_科技": 0.12}
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


def required_factor_symbols(
    mapping: dict[str, Any],
    *,
    direct_mapping: AdrMapping | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    factor_weights, _ = factor_weights_for_mapping(mapping)
    ranked = sorted(factor_weights.items(), key=lambda item: (-item[1], item[0]))
    symbols: list[dict[str, Any]] = []
    direct_mapping = direct_mapping or get_adr_mapping(str(mapping.get("stock_id") or ""))
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
    return symbols if limit is None else symbols[: max(limit, 1)]


def resolve_cross_market_source_requirements(
    db: Session,
    stock_ids: list[str],
    *,
    requested_capabilities: Iterable[str] | None,
    generated_at,
) -> dict[str, Any]:
    capabilities = normalize_requested_capabilities(requested_capabilities)
    capability_set = set(capabilities)
    requirements: dict[tuple[str, str], dict[str, Any]] = {}
    mapping_entries: list[dict[str, Any]] = []
    missing_relations: list[str] = []

    def add_requirement(
        *,
        source_kind: str,
        symbol: str,
        stock_id: str,
        role: str,
        capability: str,
        priority: int,
    ) -> None:
        key = (source_kind, symbol)
        item = requirements.setdefault(
            key,
            {
                "source_kind": source_kind,
                "symbol": symbol,
                "targets": set(),
                "roles": set(),
                "required_for": set(),
                "refresh_priority": priority,
            },
        )
        item["targets"].add(stock_id)
        item["roles"].add(role)
        item["required_for"].add(capability)
        item["refresh_priority"] = min(int(item["refresh_priority"]), priority)

    for stock_id in stock_ids:
        stock = db.query(StockMaster).filter(StockMaster.stock_id == stock_id).first()
        adr_resolution = resolve_adr_mapping(
            db,
            stock_id,
            as_of=generated_at.date(),
            data_available_at=generated_at,
        )
        adr_mapping = adr_resolution.mapping
        registry = build_relation_registry_read(
            db,
            stock_id,
            as_of=generated_at.date(),
            generated_at=generated_at,
            data_available_at=generated_at,
        )
        mapping_entries.append(
            {
                "stock_id": stock_id,
                "mapping_resolution": adr_resolution.as_payload(),
                "adr_symbol": adr_mapping.adr_symbol if adr_mapping is not None else None,
            }
        )

        if CROSS_MARKET_OVERNIGHT_CAPABILITY in capability_set and stock is not None:
            mapping = resolve_tw_overnight_mapping(stock)
            for factor_priority, factor in enumerate(
                required_factor_symbols(mapping, direct_mapping=adr_mapping)
            ):
                add_requirement(
                    source_kind="us_daily_price",
                    symbol=str(factor["symbol"]),
                    stock_id=stock_id,
                    role=str(factor["role"]),
                    capability=CROSS_MARKET_OVERNIGHT_CAPABILITY,
                    priority=factor_priority,
                )

        usable_relations = [item for item in registry.relations if item.decision_usable]
        if CROSS_MARKET_RELATIONS_CAPABILITY in capability_set:
            for relation in usable_relations:
                source_symbol = str(relation.source.provider_symbol or "").strip().upper()
                if relation.source.market == "US" and source_symbol:
                    add_requirement(
                        source_kind="us_daily_price",
                        symbol=source_symbol,
                        stock_id=stock_id,
                        role=(
                            "direct_source"
                            if relation.bucket == "direct_equivalent"
                            else "proxy_source"
                        ),
                        capability=CROSS_MARKET_RELATIONS_CAPABILITY,
                        priority=50,
                    )
                rule = PROXY_BENCHMARK_RULES.get(str(relation.relation_subtype or ""))
                if rule is not None:
                    add_requirement(
                        source_kind="us_daily_price",
                        symbol=rule.benchmark_symbol.strip().upper(),
                        stock_id=stock_id,
                        role="proxy_benchmark",
                        capability=CROSS_MARKET_RELATIONS_CAPABILITY,
                        priority=60,
                    )

        if CROSS_MARKET_PARITY_CAPABILITY in capability_set and adr_mapping is not None:
            add_requirement(
                source_kind="us_daily_price",
                symbol=adr_mapping.adr_symbol,
                stock_id=stock_id,
                role="direct_source",
                capability=CROSS_MARKET_PARITY_CAPABILITY,
                priority=50,
            )
            add_requirement(
                source_kind="resource_quote",
                symbol="USD-TWD",
                stock_id=stock_id,
                role="fx_alignment",
                capability=CROSS_MARKET_PARITY_CAPABILITY,
                priority=90,
            )

        if adr_mapping is None and not usable_relations:
            missing_relations.append(stock_id)

    serialized = []
    for item in requirements.values():
        serialized.append(
            {
                **item,
                "targets": sorted(item["targets"]),
                "roles": sorted(item["roles"]),
                "required_for": sorted(item["required_for"]),
            }
        )
    serialized.sort(
        key=lambda item: (
            int(item["refresh_priority"]),
            item["source_kind"],
            item["symbol"],
        )
    )
    return {
        "requested_capabilities": list(capabilities),
        "requirements": serialized,
        "mapping_entries": mapping_entries,
        "missing_relations": missing_relations,
    }


def list_active_cross_market_us_requirement_symbols(
    db: Session,
    *,
    max_stock_ids: int = 32,
    generated_at: datetime | None = None,
) -> tuple[str, ...]:
    """Return bounded US Daily inputs for the existing priority producer."""

    if max_stock_ids < 1 or max_stock_ids > 32:
        raise ValueError("max_stock_ids must be between 1 and 32")
    rows = (
        db.query(CrossMarketRelation.target_provider_symbol)
        .join(
            StockMaster,
            StockMaster.stock_id == CrossMarketRelation.target_provider_symbol,
        )
        .filter(CrossMarketRelation.target_market == "TW")
        .filter(CrossMarketRelation.review_status == "approved")
        .filter(CrossMarketRelation.is_active.is_(True))
        .distinct()
        .order_by(CrossMarketRelation.target_provider_symbol.asc())
        .limit(max_stock_ids)
        .all()
    )
    stock_ids = [str(row[0]).strip() for row in rows if str(row[0]).strip()]
    if not stock_ids:
        return ()
    resolved = resolve_cross_market_source_requirements(
        db,
        stock_ids,
        requested_capabilities=SUPPORTED_CROSS_MARKET_CAPABILITIES,
        generated_at=generated_at or datetime.now(timezone.utc),
    )
    return tuple(
        dict.fromkeys(
            str(item["symbol"])
            for item in resolved["requirements"]
            if item["source_kind"] == "us_daily_price"
        )
    )


__all__ = [
    "CROSS_MARKET_OVERNIGHT_CAPABILITY",
    "CROSS_MARKET_PARITY_CAPABILITY",
    "CROSS_MARKET_RELATIONS_CAPABILITY",
    "INDEX_FACTORS",
    "SUPPORTED_CROSS_MARKET_CAPABILITIES",
    "factor_weights_for_mapping",
    "list_active_cross_market_us_requirement_symbols",
    "normalize_requested_capabilities",
    "required_factor_symbols",
    "resolve_cross_market_source_requirements",
    "resolve_tw_overnight_mapping",
]
