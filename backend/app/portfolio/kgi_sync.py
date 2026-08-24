from __future__ import annotations

from datetime import datetime, timezone
import math
import re
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.db.models import PortfolioHolding, USStockMaster
from app.market.providers.kgi_superpy import fetch_kgi_superpy_portfolio_holdings
from app.portfolio.service import DEFAULT_CURRENCIES, PortfolioError, normalize_market, normalize_symbol


KGI_PORTFOLIO_MARKETS = {"tw", "us"}
KGI_PORTFOLIO_SOURCE = "kgi_superpy"
KGI_PORTFOLIO_MAX_HOLDINGS = 1000
_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3,10}$")
_US_EXCHANGE_SUFFIXES = {"A", "N", "O", "P"}


class KgiPortfolioSyncError(PortfolioError):
    pass


class KgiPortfolioUnavailableError(KgiPortfolioSyncError):
    pass


class KgiPortfolioPayloadError(KgiPortfolioSyncError):
    pass


def _display_warnings(warnings: list[str]) -> list[str]:
    messages: list[str] = []
    for warning in warnings:
        key, _, raw_count = warning.partition(":")
        count = raw_count if raw_count.isdigit() else "部分"
        if key == "excluded_short_positions":
            messages.append(f"凱基回傳 {count} 檔融券部位；OMI 持股清單只匯入多頭部位。")
        elif key == "missing_cost_basis":
            messages.append(f"凱基未提供 {count} 檔持股成本，OMI 已保留為未提供。")
        else:
            messages.append("凱基持股資料包含未識別的資料限制。")
    return list(dict.fromkeys(messages))


def _finite_positive(value: Any, *, field: str) -> float:
    if value is None or isinstance(value, bool):
        raise KgiPortfolioPayloadError(f"KGI portfolio {field} is missing.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise KgiPortfolioPayloadError(f"KGI portfolio {field} is invalid.") from exc
    if not math.isfinite(number) or number <= 0:
        raise KgiPortfolioPayloadError(f"KGI portfolio {field} must be positive.")
    return number


def _provider_observed_at(value: Any) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise KgiPortfolioPayloadError("KGI portfolio observed_at is invalid.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_kgi_symbol(db: Session, market: str, value: Any) -> str:
    symbol = normalize_symbol(market, str(value or ""))
    if not symbol:
        raise KgiPortfolioPayloadError("KGI portfolio symbol is missing.")
    if market != "us" or "." not in symbol:
        return symbol

    base, suffix = symbol.rsplit(".", maxsplit=1)
    if suffix not in _US_EXCHANGE_SUFFIXES or not base:
        return symbol
    base_exists = db.query(USStockMaster.id).filter(USStockMaster.symbol == base).first()
    return base if base_exists is not None else symbol


def normalize_kgi_holdings(
    db: Session,
    *,
    market: str,
    payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], datetime, list[str]]:
    normalized_market = normalize_market(market)
    if normalized_market not in KGI_PORTFOLIO_MARKETS:
        raise KgiPortfolioPayloadError("KGI portfolio sync supports only tw and us.")
    if payload.get("market") != normalized_market or payload.get("source") != KGI_PORTFOLIO_SOURCE:
        raise KgiPortfolioPayloadError("KGI portfolio response identity is inconsistent.")

    raw_records = payload.get("records")
    if not isinstance(raw_records, list):
        raise KgiPortfolioPayloadError("KGI portfolio records are invalid.")
    if len(raw_records) > KGI_PORTFOLIO_MAX_HOLDINGS:
        raise KgiPortfolioPayloadError("KGI portfolio response exceeds the holding limit.")
    if int(payload.get("holding_count") or 0) != len(raw_records):
        raise KgiPortfolioPayloadError("KGI portfolio response count is inconsistent.")

    normalized: dict[str, dict[str, Any]] = {}
    for raw_record in raw_records:
        if not isinstance(raw_record, dict):
            raise KgiPortfolioPayloadError("KGI portfolio contains an invalid row.")
        symbol = _normalize_kgi_symbol(db, normalized_market, raw_record.get("symbol"))
        quantity = _finite_positive(raw_record.get("quantity"), field="quantity")
        raw_cost = raw_record.get("cost_amount")
        cost_amount = (
            None
            if raw_cost is None
            else _finite_positive(raw_cost, field="cost_amount")
        )
        currency = str(
            raw_record.get("currency") or DEFAULT_CURRENCIES[normalized_market]
        ).strip().upper()
        if not _CURRENCY_PATTERN.fullmatch(currency):
            raise KgiPortfolioPayloadError("KGI portfolio currency is invalid.")
        symbol_name = str(raw_record.get("symbol_name") or "").strip() or None
        if symbol_name is not None:
            symbol_name = symbol_name[:240]

        existing = normalized.get(symbol)
        if existing is None:
            normalized[symbol] = {
                "symbol": symbol,
                "symbol_name": symbol_name,
                "quantity": quantity,
                "cost_amount": cost_amount,
                "currency": currency,
            }
            continue
        if existing["currency"] != currency:
            raise KgiPortfolioPayloadError(
                "KGI portfolio returned conflicting currencies for one symbol."
            )
        existing["quantity"] += quantity
        if existing["cost_amount"] is None or cost_amount is None:
            existing["cost_amount"] = None
        else:
            existing["cost_amount"] += cost_amount
        if not existing["symbol_name"]:
            existing["symbol_name"] = symbol_name

    warnings = payload.get("warnings")
    if not isinstance(warnings, list) or not all(isinstance(item, str) for item in warnings):
        raise KgiPortfolioPayloadError("KGI portfolio warnings are invalid.")
    return (
        [normalized[symbol] for symbol in sorted(normalized)],
        _provider_observed_at(payload.get("observed_at")),
        [item[:200] for item in warnings],
    )


def replace_kgi_holdings(
    db: Session,
    *,
    market: str,
    records: list[dict[str, Any]],
    source_updated_at: datetime,
    warnings: list[str],
) -> dict[str, Any]:
    existing_rows = (
        db.query(PortfolioHolding)
        .filter(PortfolioHolding.market == market)
        .all()
    )
    existing_by_symbol = {row.symbol: row for row in existing_rows}
    desired_symbols = {record["symbol"] for record in records}
    created_count = 0
    updated_count = 0
    removed_count = 0

    try:
        for row in existing_rows:
            if row.symbol not in desired_symbols:
                db.delete(row)
                removed_count += 1

        for record in records:
            row = existing_by_symbol.get(record["symbol"])
            if row is None:
                row = PortfolioHolding(
                    market=market,
                    symbol=record["symbol"],
                    note=None,
                    tags=None,
                    strategy_horizon=None,
                    opened_at=None,
                )
                db.add(row)
                created_count += 1
            else:
                updated_count += 1
            row.symbol_name = record["symbol_name"] or row.symbol_name
            row.quantity = record["quantity"]
            row.cost_amount = record["cost_amount"]
            row.currency = record["currency"]
            row.is_active = True
            row.source = KGI_PORTFOLIO_SOURCE
            row.source_updated_at = source_updated_at

        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "market": market,
        "status": "synced",
        "source": KGI_PORTFOLIO_SOURCE,
        "holding_count": len(records),
        "created_count": created_count,
        "updated_count": updated_count,
        "removed_count": removed_count,
        "missing_cost_basis_count": sum(
            1 for record in records if record["cost_amount"] is None
        ),
        "warnings": _display_warnings(warnings),
        "source_updated_at": source_updated_at,
    }


def sync_kgi_holdings(
    db: Session,
    *,
    market: str,
    fetcher: Callable[[str], dict[str, Any]] = fetch_kgi_superpy_portfolio_holdings,
) -> dict[str, Any]:
    normalized_market = normalize_market(market)
    if normalized_market not in KGI_PORTFOLIO_MARKETS:
        raise KgiPortfolioSyncError("KGI portfolio sync supports only tw and us.")

    provider_payload = fetcher(normalized_market)
    provider_status = str(provider_payload.get("status") or "failed")
    if provider_status not in {"available", "empty"}:
        detail = str(provider_payload.get("error") or "KGI portfolio is unavailable.")[:1000]
        raise KgiPortfolioUnavailableError(detail)

    records, source_updated_at, warnings = normalize_kgi_holdings(
        db,
        market=normalized_market,
        payload=provider_payload,
    )
    return replace_kgi_holdings(
        db,
        market=normalized_market,
        records=records,
        source_updated_at=source_updated_at,
        warnings=warnings,
    )
