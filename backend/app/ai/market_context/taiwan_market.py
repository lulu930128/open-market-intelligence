from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Protocol

from sqlalchemy.orm import Session

from app.ai.market_context.common import append_source_ref_once as _append_source_ref_once
from app.ai.market_context.taiwan_projection import (
    _build_tw_market_slots,
    _compact_index_quote,
    _compact_single_intraday_series,
    _with_evidence_passport,
)
from app.ai.market_payload_contract import (
    intraday_point_limit as _intraday_point_limit,
    market_data_params as _market_data_params,
    payload_level as _payload_level,
)
from app.db.models import StockMaster
from app.market.taiwan_industries import normalize_tw_industry_label


class MarketService(Protocol):
    def get_latest_trade_date(self, db: Session) -> Any: ...

    def list_market_daily_prices(
        self,
        *,
        db: Session,
        trade_date: Any,
        limit: int,
    ) -> list[Any]: ...


@dataclass(frozen=True)
class TaiwanMarketDependencies:
    market_service: MarketService
    get_market_index_intraday: Callable[[str], dict[str, Any]]
    now: Callable[[], datetime]


def _market_index_ids_from_params(params: dict[str, Any] | None) -> list[str]:
    data_params = _market_data_params(params)
    raw_value = data_params.get("index_ids") or data_params.get("indices") or ("TAIEX", "TPEX")
    if isinstance(raw_value, str):
        values = [item.strip().upper() for item in raw_value.split(",")]
    elif isinstance(raw_value, list):
        values = [str(item).strip().upper() for item in raw_value]
    else:
        values = ["TAIEX", "TPEX"]
    supported = {"TAIEX", "TPEX"}
    selected = [value for value in values if value in supported]
    return list(dict.fromkeys(selected or ["TAIEX", "TPEX"]))[:2]


def _market_index_intraday_pack(
    *,
    dependencies: TaiwanMarketDependencies,
    include_intraday: bool,
    market_data_params: dict[str, Any] | None,
    missing: list[str],
    warnings: list[str],
    source_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    payload_level = _payload_level(market_data_params)
    point_limit = _intraday_point_limit(market_data_params)
    index_ids = _market_index_ids_from_params(market_data_params)
    if not include_intraday:
        return {
            "kind": "market_index_intraday_pack",
            "enabled": False,
            "payload_level": payload_level,
            "bar_limit": point_limit,
            "index_ids": index_ids,
            "indices": [],
            "warnings": [],
        }

    rows: list[dict[str, Any]] = []
    local_warnings: list[str] = []
    _append_source_ref_once(source_refs, {"type": "external_or_cache", "name": "market_index_intraday"})
    for index_id in index_ids:
        try:
            intraday = dependencies.get_market_index_intraday(index_id)
        except Exception as exc:
            message = f"{index_id} index intraday unavailable: {exc}"
            warnings.append(message)
            local_warnings.append(message)
            missing.append(f"market_index_intraday.{index_id}")
            continue

        intraday_bars = _compact_single_intraday_series(
            raw_payload=intraday,
            interval="1m",
            include_intraday=True,
            market_data_params=market_data_params,
        )
        quote = _compact_index_quote(
            index_id=index_id,
            index_snapshot=None,
            intraday=intraday,
        )
        rows.append(
            {
                "index_id": index_id,
                "quote": quote,
                "intraday_bars": intraday_bars,
            }
        )
        series = intraday_bars.get("series") if isinstance(intraday_bars.get("series"), dict) else {}
        if not any(isinstance(item, dict) and item.get("returned_point_count") for item in series.values()):
            missing.append(f"market_index_intraday.{index_id}")

    return {
        "kind": "market_index_intraday_pack",
        "enabled": True,
        "payload_level": payload_level,
        "bar_limit": point_limit,
        "index_ids": index_ids,
        "indices": rows,
        "warnings": local_warnings,
    }


def read_market_overview(
    db: Session,
    limit: int = 10,
    *,
    include_intraday: bool = False,
    market_data_params: dict[str, Any] | None = None,
    dependencies: TaiwanMarketDependencies,
) -> dict[str, Any]:
    latest_trade_date = dependencies.market_service.get_latest_trade_date(db)
    missing: list[str] = []
    warnings: list[str] = []
    source_refs: list[dict[str, Any]] = [{"type": "table", "name": "market_daily_price"}]
    payload_level = _payload_level(market_data_params)
    index_intraday = _market_index_intraday_pack(
        dependencies=dependencies,
        include_intraday=include_intraday,
        market_data_params=market_data_params,
        missing=missing,
        warnings=warnings,
        source_refs=source_refs,
    )

    if latest_trade_date is None:
        envelope = {
            "kind": "market_overview",
            "generated_at": dependencies.now(),
            "as_of": None,
            "scope": {},
            "data": {
                "latest_trade_date": None,
                "breadth": {},
                "top_gainers": [],
                "top_losers": [],
                "index_intraday": index_intraday,
                "slots": _build_tw_market_slots(
                    as_of=None,
                    payload_level=payload_level,
                    breadth={},
                    distribution={},
                    industry_rows=[],
                    index_intraday=index_intraday,
                    missing=list(dict.fromkeys(["market_daily_price", *missing])),
                    warnings=[
                        "No market daily rows are available in the local database.",
                        *warnings,
                    ],
                ),
            },
            "missing": list(dict.fromkeys(["market_daily_price", *missing])),
            "warnings": [
                "No market daily rows are available in the local database.",
                *warnings,
            ],
            "source_refs": source_refs,
        }
        return _with_evidence_passport(
            envelope,
            freshness={
                "is_current": False,
                "missing": envelope["missing"],
                "warnings": envelope["warnings"],
            },
        )

    rows = dependencies.market_service.list_market_daily_prices(
        db=db,
        trade_date=latest_trade_date,
        limit=10000,
    )
    stock_ids = sorted({row.stock_id for row in rows if row.stock_id})
    stock_industries: dict[str, str | None] = {}
    for index in range(0, len(stock_ids), 500):
        chunk = stock_ids[index : index + 500]
        for stock in db.query(StockMaster).filter(StockMaster.stock_id.in_(chunk)).all():
            stock_industries[stock.stock_id] = normalize_tw_industry_label(
                stock.industry or stock.category,
                fallback="未分類",
            )
    ranked = [
        {
            "stock_id": row.stock_id,
            "stock_name": row.stock_name,
            "close_price": row.close_price,
            "price_change": row.price_change,
            "change_pct": (
                (row.price_change / (row.close_price - row.price_change)) * 100
                if row.price_change is not None
                and row.close_price is not None
                and row.close_price != row.price_change
                else None
            ),
            "trade_volume": row.trade_volume,
            "trade_value": row.trade_value,
            "transaction_count": row.transaction_count,
            "industry": stock_industries.get(row.stock_id),
        }
        for row in rows
    ]
    ranked_with_change = [row for row in ranked if row["change_pct"] is not None]
    top_gainers = sorted(ranked_with_change, key=lambda row: row["change_pct"], reverse=True)[:limit]
    top_losers = sorted(ranked_with_change, key=lambda row: row["change_pct"])[:limit]
    value_leaders = sorted(
        [row for row in ranked if row["trade_value"] is not None],
        key=lambda row: row["trade_value"] or 0,
        reverse=True,
    )[:limit]

    advance_count = sum(1 for row in rows if (row.price_change or 0) > 0)
    decline_count = sum(1 for row in rows if (row.price_change or 0) < 0)
    unchanged_count = sum(1 for row in rows if (row.price_change or 0) == 0)
    total_trade_value = sum(row.trade_value or 0 for row in rows) or None
    total_count = len(rows)
    average_change_pct = (
        sum(row["change_pct"] for row in ranked_with_change) / len(ranked_with_change)
        if ranked_with_change
        else None
    )
    positive_ratio = advance_count / len(ranked_with_change) if ranked_with_change else None
    advance_decline_ratio = advance_count / decline_count if decline_count else None
    top_value_sum = sum(row["trade_value"] or 0 for row in value_leaders)
    top_value_share = (
        top_value_sum / total_trade_value
        if total_trade_value and value_leaders
        else None
    )
    breadth = {
        "advance_count": advance_count,
        "decline_count": decline_count,
        "unchanged_count": unchanged_count,
        "total_count": total_count,
        "trade_value": total_trade_value,
        "average_change_pct": average_change_pct,
        "positive_ratio": positive_ratio,
        "advance_decline_ratio": advance_decline_ratio,
        "top_value_share": top_value_share,
    }
    distribution = {
        "limit_up_count": sum(
            1 for row in ranked_with_change if (row["change_pct"] or 0) >= 9.5
        ),
        "strong_up_count": sum(
            1 for row in ranked_with_change if 5 <= (row["change_pct"] or 0) < 9.5
        ),
        "mild_up_count": sum(
            1 for row in ranked_with_change if 0 < (row["change_pct"] or 0) < 5
        ),
        "flat_count": unchanged_count,
        "mild_down_count": sum(
            1 for row in ranked_with_change if -5 < (row["change_pct"] or 0) < 0
        ),
        "strong_down_count": sum(
            1 for row in ranked_with_change if -9.5 < (row["change_pct"] or 0) <= -5
        ),
        "limit_down_count": sum(
            1 for row in ranked_with_change if (row["change_pct"] or 0) <= -9.5
        ),
    }
    industry_groups: dict[str, list[dict[str, Any]]] = {}
    for row in ranked_with_change:
        industry = normalize_tw_industry_label(row.get("industry"), fallback="未分類")
        industry_groups.setdefault(industry, []).append(row)

    industry_summary = []
    for industry, group_rows in industry_groups.items():
        changes = [
            row["change_pct"]
            for row in group_rows
            if isinstance(row.get("change_pct"), (int, float))
        ]
        if not changes:
            continue
        trade_value = sum(row.get("trade_value") or 0 for row in group_rows) or None
        top_row = max(
            group_rows,
            key=lambda row: (
                row.get("trade_value") or 0,
                row.get("change_pct") or 0,
            ),
        )
        industry_summary.append(
            {
                "industry": industry,
                "count": len(group_rows),
                "advance_count": sum(1 for value in changes if value > 0),
                "decline_count": sum(1 for value in changes if value < 0),
                "average_change_pct": sum(changes) / len(changes),
                "trade_value": trade_value,
                "top_stock_id": top_row.get("stock_id"),
                "top_stock_name": top_row.get("stock_name"),
            }
        )
    top_industries = sorted(
        [row for row in industry_summary if row["industry"] != "未分類" and row["count"] >= 2],
        key=lambda row: (
            row["average_change_pct"],
            row.get("trade_value") or 0,
        ),
        reverse=True,
    )[:6]
    weak_industries = sorted(
        [row for row in industry_summary if row["industry"] != "未分類" and row["count"] >= 2],
        key=lambda row: (
            row["average_change_pct"],
            -(row.get("trade_value") or 0),
        ),
    )[:6]

    if not ranked_with_change:
        missing.append("market_daily_price.change_pct")

    warnings.extend(
        [
            (
                "This overview includes bounded Taiwan index intraday data, but stock breadth still uses latest local daily rows."
                if include_intraday
                else "This overview uses the latest local daily market rows and does not fetch live quotes."
            )
        ]
    )

    envelope = {
        "kind": "market_overview",
        "generated_at": dependencies.now(),
        "as_of": latest_trade_date.isoformat(),
        "scope": {},
        "data": {
            "latest_trade_date": latest_trade_date.isoformat(),
            "breadth": breadth,
            "distribution": distribution,
            "top_gainers": top_gainers,
            "top_losers": top_losers,
            "value_leaders": value_leaders,
            "top_industries": top_industries,
            "weak_industries": weak_industries,
            "index_intraday": index_intraday,
            "slots": _build_tw_market_slots(
                as_of=latest_trade_date.isoformat(),
                payload_level=payload_level,
                breadth=breadth,
                distribution=distribution,
                industry_rows=[*top_industries, *weak_industries],
                index_intraday=index_intraday,
                missing=missing,
                warnings=warnings,
            ),
        },
        "missing": missing,
        "warnings": warnings,
        "source_refs": source_refs,
    }
    return _with_evidence_passport(
        envelope,
        freshness={
            "is_current": not missing,
            "missing": missing,
            "warnings": envelope["warnings"],
        },
    )
