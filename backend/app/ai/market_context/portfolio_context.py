from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.ai.evidence_passport import build_evidence_passport
from app.ai.market_payload_contract import bounded_int_param, payload_level, slot_envelope
from app.db.models import (
    JPDailyPrice,
    KRDailyPrice,
    MarketDailyPrice,
    TaiwanStockQuoteSnapshot,
    USDailyPrice,
)


@dataclass(frozen=True)
class PortfolioContextDependencies:
    portfolio_service: Any
    now: Any


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _latest_tw_price(db: Session, symbol: str) -> dict[str, Any]:
    quote = (
        db.query(TaiwanStockQuoteSnapshot)
        .filter(TaiwanStockQuoteSnapshot.stock_id == symbol)
        .order_by(TaiwanStockQuoteSnapshot.quote_time.desc(), TaiwanStockQuoteSnapshot.id.desc())
        .first()
    )
    if quote is not None and quote.last_price is not None:
        return {
            "price": quote.last_price,
            "as_of": quote.quote_time,
            "provider": quote.provider,
            "source": "taiwan_stock_quote_snapshot",
        }
    daily = (
        db.query(MarketDailyPrice)
        .filter(MarketDailyPrice.stock_id == symbol)
        .order_by(MarketDailyPrice.trade_date.desc(), MarketDailyPrice.id.desc())
        .first()
    )
    return {
        "price": daily.close_price if daily else None,
        "as_of": daily.trade_date if daily else None,
        "provider": "omi_market_daily" if daily else None,
        "source": "market_daily_price",
    }


def _latest_regional_price(db: Session, market: str, symbol: str) -> dict[str, Any]:
    model = {"us": USDailyPrice, "jp": JPDailyPrice, "kr": KRDailyPrice}.get(market)
    if model is None:
        return {"price": None, "as_of": None, "provider": None, "source": None}
    row = (
        db.query(model)
        .filter(model.symbol == symbol)
        .order_by(model.trade_date.desc(), model.id.desc())
        .first()
    )
    price = None
    if row is not None:
        price = getattr(row, "adjusted_close", None)
        if price is None:
            price = getattr(row, "close_price", None)
    return {
        "price": price,
        "as_of": row.trade_date if row else None,
        "provider": row.provider if row else None,
        "source": f"{market}_daily_price",
    }


def _price_context(db: Session, market: str, symbol: str) -> dict[str, Any]:
    if market == "tw":
        return _latest_tw_price(db, symbol)
    return _latest_regional_price(db, market, symbol)


def _age_days(value: Any, *, now_value: datetime) -> int | None:
    if isinstance(value, datetime):
        comparable = value
        if comparable.tzinfo is None:
            comparable = comparable.replace(tzinfo=timezone.utc)
        now_comparable = now_value
        if now_comparable.tzinfo is None:
            now_comparable = now_comparable.replace(tzinfo=timezone.utc)
        return max(0, (now_comparable - comparable).days)
    if isinstance(value, date):
        return max(0, (now_value.date() - value).days)
    return None


def read_portfolio_context(
    db: Session,
    *,
    market_data_params: dict[str, Any] | None,
    trusted: bool,
    dependencies: PortfolioContextDependencies,
) -> dict[str, Any]:
    params = market_data_params if isinstance(market_data_params, dict) else {}
    level = payload_level(params)
    now_value = dependencies.now()
    target = {
        "type": "portfolio",
        "id": "active",
        "label": "Active portfolio",
        "market": "multi",
    }
    if not trusted:
        warning = "Portfolio context requires a server-trusted caller because it contains private position data."
        slots = {
            "holdings": slot_envelope(
                status="blocked",
                capability="private_portfolio_holdings",
                payload_level=level,
                priority="core",
                warnings=[warning],
            ),
            "valuation": slot_envelope(
                status="blocked",
                capability="portfolio_valuation",
                payload_level=level,
                warnings=[warning],
            ),
            "data_quality": slot_envelope(
                status="blocked",
                capability="portfolio_data_quality",
                payload_level=level,
                warnings=[warning],
            ),
        }
        envelope = {
            "kind": "portfolio_context",
            "generated_at": now_value,
            "as_of": None,
            "scope": {"target": target},
            "data": {
                "access": {"status": "blocked", "reason": "server_trust_required"},
                "holdings": [],
                "summary": {"holding_count": 0},
                "compact": {
                    "kind": "portfolio_compact_evidence",
                    "version": "market_compact_evidence.v1",
                    "payload_level": level,
                    "target": target,
                    "resources": {"access": "blocked"},
                    "freshness_by_domain": {"portfolio": "blocked"},
                    "slots": slots,
                },
                "slots": slots,
            },
            "missing": ["trusted_portfolio_access"],
            "warnings": [warning],
            "source_refs": [{"type": "user_input", "name": "portfolio_holding"}],
        }
        envelope["evidence_passport"] = build_evidence_passport(
            kind=envelope["kind"],
            missing=envelope["missing"],
            warnings=envelope["warnings"],
            source_refs=envelope["source_refs"],
            freshness={"is_current": False, "missing": envelope["missing"]},
        )
        return envelope

    market_filter = str(params.get("market") or "").strip().lower() or None
    if market_filter and market_filter not in dependencies.portfolio_service.SUPPORTED_MARKETS:
        raise ValueError("portfolio market filter must be one of: tw, us, jp, kr.")
    holding_limit = bounded_int_param(
        params,
        ("limit", "holding_limit"),
        default=200,
        minimum=1,
        maximum=500,
    )
    holdings = dependencies.portfolio_service.list_holdings(
        db,
        market=market_filter,
        is_active=True,
        limit=holding_limit,
    )
    priced_holdings: list[dict[str, Any]] = []
    missing_prices: list[str] = []
    as_of_values: list[date | datetime] = []
    cost_by_currency: dict[str, float] = {}
    market_value_by_currency: dict[str, float] = {}
    pnl_by_currency: dict[str, float] = {}

    for holding in holdings:
        market = str(holding.get("market") or "")
        symbol = str(holding.get("symbol") or "")
        price = _price_context(db, market, symbol)
        latest_price = price.get("price")
        quantity = float(holding.get("quantity") or 0)
        cost_amount = float(holding.get("cost_amount") or 0)
        market_value = latest_price * quantity if isinstance(latest_price, (int, float)) else None
        unrealized_pnl = market_value - cost_amount if market_value is not None else None
        currency = str(holding.get("currency") or "unknown").upper()
        cost_by_currency[currency] = cost_by_currency.get(currency, 0.0) + cost_amount
        if market_value is not None:
            market_value_by_currency[currency] = market_value_by_currency.get(currency, 0.0) + market_value
            pnl_by_currency[currency] = pnl_by_currency.get(currency, 0.0) + (unrealized_pnl or 0.0)
        else:
            missing_prices.append(f"portfolio_price.{market}.{symbol}")
        if isinstance(price.get("as_of"), (date, datetime)):
            as_of_values.append(price["as_of"])
        priced_holdings.append(
            {
                **{
                    key: _json_value(value)
                    for key, value in holding.items()
                    if key not in {"note", "position_context", "created_at", "updated_at"}
                },
                "latest_price": latest_price,
                "price_as_of": _json_value(price.get("as_of")),
                "price_age_days": _age_days(price.get("as_of"), now_value=now_value),
                "price_provider": price.get("provider"),
                "price_source": price.get("source"),
                "market_value": market_value,
                "unrealized_pnl": unrealized_pnl,
                "unrealized_pnl_pct": (
                    (unrealized_pnl / cost_amount) * 100
                    if unrealized_pnl is not None and cost_amount > 0
                    else None
                ),
            }
        )

    for row in priced_holdings:
        currency = str(row.get("currency") or "unknown").upper()
        denominator = market_value_by_currency.get(currency) or 0.0
        market_value = row.get("market_value")
        row["weight_within_currency"] = (
            market_value / denominator
            if isinstance(market_value, (int, float)) and denominator > 0
            else None
        )

    stale_price_count = sum(
        1
        for row in priced_holdings
        if isinstance(row.get("price_age_days"), int) and row["price_age_days"] > 7
    )
    latest_as_of = max(
        as_of_values,
        key=lambda value: value.isoformat(),
        default=None,
    )
    warnings = [
        "Portfolio values are grouped by native currency; OMI does not silently convert currencies without an explicit FX valuation contract."
    ]
    if not holdings:
        warnings.append("No active portfolio holdings match the requested filter.")
    if stale_price_count:
        warnings.append(f"{stale_price_count} portfolio price snapshots are older than seven calendar days.")
    if missing_prices:
        warnings.append(f"{len(missing_prices)} holdings have no cached valuation price.")
    valuation_status = (
        "not_applicable"
        if not holdings
        else "missing"
        if len(missing_prices) == len(holdings)
        else "stale"
        if stale_price_count
        else "partial"
        if missing_prices
        else "ready"
    )
    holdings_status = "ready"
    slots = {
        "holdings": slot_envelope(
            status=holdings_status,
            capability="private_portfolio_holdings",
            payload_ref="data.holdings",
            payload_level=level,
            priority="core",
        ),
        "valuation": slot_envelope(
            status=valuation_status,
            capability="portfolio_native_currency_valuation",
            payload_ref="data.valuation",
            payload_level=level,
            priority="core",
            as_of=_json_value(latest_as_of),
            missing=missing_prices,
        ),
        "fx_normalization": slot_envelope(
            status="not_requested",
            capability="portfolio_fx_normalization",
            payload_level=level,
            next_fill="Use explicit resource-market FX quotes with caller-selected base currency before aggregating cross-currency value.",
        ),
        "data_quality": slot_envelope(
            status="partial" if missing_prices or stale_price_count else "ready",
            capability="portfolio_coverage",
            payload_ref="data.summary",
            payload_level=level,
            priority="core",
            missing=missing_prices,
            warnings=warnings,
        ),
    }
    summary = {
        "holding_count": len(holdings),
        "priced_holding_count": len(holdings) - len(missing_prices),
        "missing_price_count": len(missing_prices),
        "stale_price_count": stale_price_count,
        "market_counts": {
            market: sum(1 for row in priced_holdings if row.get("market") == market)
            for market in sorted({str(row.get("market")) for row in priced_holdings})
        },
        "currencies": sorted(cost_by_currency),
    }
    envelope = {
        "kind": "portfolio_context",
        "generated_at": now_value,
        "as_of": _json_value(latest_as_of),
        "scope": {"target": target},
        "data": {
            "access": {"status": "ready", "trust": "server_trusted"},
            "filters": {"market": market_filter, "limit": holding_limit},
            "summary": summary,
            "valuation": {
                "cost_by_currency": cost_by_currency,
                "market_value_by_currency": market_value_by_currency,
                "unrealized_pnl_by_currency": pnl_by_currency,
                "cross_currency_total": None,
            },
            "holdings": priced_holdings,
            "compact": {
                "kind": "portfolio_compact_evidence",
                "version": "market_compact_evidence.v1",
                "payload_level": level,
                "target": target,
                "resources": {
                    **summary,
                    "valuation": {
                        "cost_by_currency": cost_by_currency,
                        "market_value_by_currency": market_value_by_currency,
                        "unrealized_pnl_by_currency": pnl_by_currency,
                    },
                },
                "freshness_by_domain": {"valuation": valuation_status},
                "slots": slots,
            },
            "slots": slots,
        },
        "missing": list(dict.fromkeys(missing_prices)),
        "warnings": list(dict.fromkeys(warnings)),
        "source_refs": [
            {"type": "user_input", "name": "portfolio_holding"},
            {"type": "table", "name": "taiwan_stock_quote_snapshot"},
            {"type": "table", "name": "market_daily_price"},
            {"type": "table", "name": "us_daily_price"},
            {"type": "table", "name": "jp_daily_price"},
            {"type": "table", "name": "kr_daily_price"},
        ],
    }
    envelope["evidence_passport"] = build_evidence_passport(
        kind=envelope["kind"],
        as_of=envelope["as_of"],
        source_refs=envelope["source_refs"],
        missing=envelope["missing"],
        warnings=envelope["warnings"],
        freshness={
            "is_current": valuation_status in {"ready", "not_applicable"},
            "missing": envelope["missing"],
        },
    )
    return envelope
