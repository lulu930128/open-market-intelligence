from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.ai.agentic_common import _json_value
from app.db.models import (
    InstitutionalTradeDaily,
    MarginTradingDaily,
    MarketChipDaily,
)
from app.market.calendar_status import build_taiwan_calendar_status
from app.market.market_chips import market_chip_daily_to_dict, project_market_chip_freshness
from app.market.tw_universe import list_taiwan_stock_ids


def _latest_date(db: Session, model: Any) -> Any:
    return db.query(func.max(model.trade_date)).scalar()


def _coverage(
    *,
    covered_count: int,
    eligible_count: int,
    source_count: int = 0,
) -> dict[str, Any]:
    ratio = covered_count / eligible_count if eligible_count else None
    complete = bool(eligible_count and covered_count == eligible_count)
    return {
        "scope": "canonical_ordinary_stock_coverage",
        "universe_class": "ordinary_stock",
        "eligible_count": eligible_count,
        "covered_eligible_count": covered_count,
        "missing_eligible_count": eligible_count - covered_count,
        # Count distinct stock IDs at this dataset's latest date, not raw rows.
        "out_of_universe_source_count": source_count - covered_count,
        "coverage_ratio": ratio,
        "is_full_eligible_coverage": complete,
        # Public compatibility aliases; all now describe the canonical universe.
        "compatibility_aliases": {
            "covered_stock_count": "covered_eligible_count",
            "active_stock_master_count": "eligible_count",
            "is_full_database_coverage": "is_full_eligible_coverage",
        },
        "covered_stock_count": covered_count,
        "active_stock_master_count": eligible_count,
        "is_full_database_coverage": complete,
        "full_market_verification": "not_asserted",
        "label": "普通股 canonical coverage",
    }


def _source_stock_count(db: Session, model: Any, trade_date: Any) -> int:
    return db.query(func.count(func.distinct(model.stock_id))).filter(
        model.trade_date == trade_date,
    ).scalar() or 0


def _institutional_context(
    db: Session,
    *,
    eligible_ids: frozenset[str],
    limit: int,
) -> dict[str, Any]:
    trade_date = _latest_date(db, InstitutionalTradeDaily)
    if trade_date is None:
        return {
            "status": "missing",
            "trade_date": None,
            "coverage": _coverage(covered_count=0, eligible_count=len(eligible_ids)),
            "aggregate": {},
            "top_net_buy": [],
            "top_net_sell": [],
        }

    rows = (
        db.query(
            InstitutionalTradeDaily.stock_id,
            func.max(InstitutionalTradeDaily.stock_name),
            func.sum(func.coalesce(InstitutionalTradeDaily.foreign_investor_net, 0)),
            func.sum(func.coalesce(InstitutionalTradeDaily.investment_trust_net, 0)),
            func.sum(func.coalesce(InstitutionalTradeDaily.dealer_net, 0)),
            func.sum(func.coalesce(InstitutionalTradeDaily.total_institutional_net, 0)),
        )
        .filter(InstitutionalTradeDaily.trade_date == trade_date)
        .filter(InstitutionalTradeDaily.stock_id.in_(eligible_ids))
        .group_by(InstitutionalTradeDaily.stock_id)
        .all()
    )
    serialized = [
        {
            "stock_id": row[0],
            "stock_name": row[1],
            "foreign_investor_net": int(row[2] or 0),
            "investment_trust_net": int(row[3] or 0),
            "dealer_net": int(row[4] or 0),
            "total_institutional_net": int(row[5] or 0),
        }
        for row in rows
    ]
    ranked = sorted(serialized, key=lambda row: row["total_institutional_net"], reverse=True)
    coverage = _coverage(
        covered_count=len(serialized), eligible_count=len(eligible_ids),
        source_count=_source_stock_count(db, InstitutionalTradeDaily, trade_date),
    )
    return {
        "status": "ready" if coverage["is_full_eligible_coverage"] else "partial",
        "trade_date": trade_date.isoformat(),
        "coverage": coverage,
        "aggregate": {
            "foreign_investor_net": sum(row["foreign_investor_net"] for row in serialized),
            "investment_trust_net": sum(row["investment_trust_net"] for row in serialized),
            "dealer_net": sum(row["dealer_net"] for row in serialized),
            "total_institutional_net": sum(row["total_institutional_net"] for row in serialized),
        } if serialized else {},
        "top_net_buy": ranked[:limit],
        "top_net_sell": list(reversed(ranked[-limit:])),
    }


def _margin_context(
    db: Session,
    *,
    eligible_ids: frozenset[str],
    limit: int,
) -> dict[str, Any]:
    trade_date = _latest_date(db, MarginTradingDaily)
    if trade_date is None:
        return {
            "status": "missing",
            "trade_date": None,
            "coverage": _coverage(covered_count=0, eligible_count=len(eligible_ids)),
            "aggregate": {},
            "top_margin_increase": [],
            "top_short_increase": [],
        }

    rows = (
        db.query(
            MarginTradingDaily.stock_id,
            func.max(MarginTradingDaily.stock_name),
            func.sum(func.coalesce(MarginTradingDaily.margin_today_balance, 0)),
            func.sum(func.coalesce(MarginTradingDaily.margin_previous_balance, 0)),
            func.sum(func.coalesce(MarginTradingDaily.short_today_balance, 0)),
            func.sum(func.coalesce(MarginTradingDaily.short_previous_balance, 0)),
        )
        .filter(MarginTradingDaily.trade_date == trade_date)
        .filter(MarginTradingDaily.stock_id.in_(eligible_ids))
        .group_by(MarginTradingDaily.stock_id)
        .all()
    )
    serialized = [
        {
            "stock_id": row[0],
            "stock_name": row[1],
            "margin_balance": int(row[2] or 0),
            "margin_balance_change": int(row[2] or 0) - int(row[3] or 0),
            "short_balance": int(row[4] or 0),
            "short_balance_change": int(row[4] or 0) - int(row[5] or 0),
        }
        for row in rows
    ]
    margin_ranked = sorted(serialized, key=lambda row: row["margin_balance_change"], reverse=True)
    short_ranked = sorted(serialized, key=lambda row: row["short_balance_change"], reverse=True)
    coverage = _coverage(
        covered_count=len(serialized), eligible_count=len(eligible_ids),
        source_count=_source_stock_count(db, MarginTradingDaily, trade_date),
    )
    return {
        "status": "ready" if coverage["is_full_eligible_coverage"] else "partial",
        "trade_date": trade_date.isoformat(),
        "coverage": coverage,
        "aggregate": {
            "margin_balance": sum(row["margin_balance"] for row in serialized),
            "margin_balance_change": sum(row["margin_balance_change"] for row in serialized),
            "short_balance": sum(row["short_balance"] for row in serialized),
            "short_balance_change": sum(row["short_balance_change"] for row in serialized),
        } if serialized else {},
        "top_margin_increase": margin_ranked[:limit],
        "top_short_increase": short_ranked[:limit],
    }


def _official_market_aggregate(db: Session) -> dict[str, Any]:
    rows: list[MarketChipDaily] = []
    for index_id in ("TAIEX", "TPEX"):
        row = (
            db.query(MarketChipDaily)
            .filter(MarketChipDaily.index_id == index_id)
            .order_by(MarketChipDaily.trade_date.desc())
            .first()
        )
        if row is not None:
            rows.append(row)
    if not rows:
        return {
            "status": "missing",
            "scope": "twse_tpex_official_aggregate",
            "markets": [],
            "same_trade_date": False,
            "trade_dates": [],
            "rows": [],
        }
    fields = (
        "index_id",
        "market",
        "trade_date",
        "close_value",
        "price_change_pct",
        "foreign_futures_net_oi",
        "put_call_volume_ratio_pct",
        "put_call_open_interest_ratio_pct",
        "total_institutional_net_value",
        "foreign_investor_net_value",
        "investment_trust_net_value",
        "dealer_net_value",
        "margin_balance_change_value",
        "margin_balance_change_shares",
        "short_balance_change_shares",
        "source_grade",
    )
    serialized = [
        {
            field: _json_value(projected.get(field))
            for field in fields
        }
        for row in rows
        for projected in [market_chip_daily_to_dict(row, db=db)]
    ]
    trade_dates = sorted({str(item["trade_date"]) for item in serialized if item.get("trade_date")})
    markets = [str(item.get("market") or item.get("index_id")) for item in serialized]
    calendar_status = build_taiwan_calendar_status()
    freshness = [
        {"index_id": row.index_id, **project_market_chip_freshness(
            latest_data_date=row.trade_date, row_count=1, calendar_status=calendar_status,
        )}
        for row in rows
    ]
    current = all(item["is_current"] for item in freshness)
    return {
        "status": "stale" if any(item["status"] == "stale" for item in freshness)
        else "ready" if len(rows) == 2 and len(trade_dates) == 1 and current else "partial",
        "scope": "twse_tpex_official_aggregate",
        "markets": markets,
        "same_trade_date": len(trade_dates) == 1,
        "trade_dates": trade_dates,
        "freshness": freshness,
        "rows": serialized,
    }


def read_tw_market_chips_context(
    db: Session,
    *,
    limit: int = 10,
) -> dict[str, Any]:
    bounded_limit = max(1, min(int(limit), 50))
    eligible_ids = frozenset(list_taiwan_stock_ids(db))
    official = _official_market_aggregate(db)
    institutional = _institutional_context(db, eligible_ids=eligible_ids, limit=bounded_limit)
    margin = _margin_context(db, eligible_ids=eligible_ids, limit=bounded_limit)
    statuses = {official["status"], institutional["status"], margin["status"]}
    status = "missing" if statuses == {"missing"} else "ready" if statuses == {"ready"} else "partial"
    missing = [
        key
        for key, value in (
            ("market_chip_daily", official),
            ("institutional_trade_daily", institutional),
            ("margin_trading_daily", margin),
        )
        if value.get("status") == "missing"
    ]
    return {
        "kind": "tw_market_chips_context",
        "status": status,
        "official_market_aggregate": official,
        "institutional_per_stock": institutional,
        "margin_per_stock": margin,
        "missing": missing,
        "warnings": [
            "Official market aggregate and canonical ordinary-stock coverage are separate contracts; per-stock rankings never assert exchange full-market coverage.",
            "Institutional and margin rankings use the latest dates independently and may have different release dates.",
        ],
        "source_refs": [
            {"type": "table", "name": "market_chip_daily"},
            {"type": "table", "name": "institutional_trade_daily"},
            {"type": "table", "name": "margin_trading_daily"},
            {"type": "table", "name": "stock_master"},
        ],
    }
