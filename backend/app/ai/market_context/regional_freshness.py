from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.ai.evidence_passport import build_evidence_passport
from app.ai.market_payload_contract import slot_envelope
from app.db.models import (
    CryptoDerivativesMetric,
    CryptoMarketCapSnapshot,
    CryptoOhlcvBar,
    CryptoOrderBookSnapshot,
    CryptoTickerSnapshot,
    JPCompanyFundamental,
    JPDailyPrice,
    JPInvestorType,
    JPMarginInterest,
    JPStockMaster,
    KRCompanyFundamental,
    KRDailyPrice,
    KRInvestorTradeDaily,
    KRStockMaster,
    USCompanyProfile,
    USCorporateAction,
    USDailyPrice,
    USSecCompanyFact,
    USShortVolumeDaily,
    USStockMaster,
)
from app.jp_market.trading_calendar import expected_jp_daily_price_date
from app.kr_market.trading_calendar import expected_kr_daily_price_date
from app.market.calendar_status import expected_us_trade_date


SUPPORTED_REGIONAL_FRESHNESS_MARKETS = {"US", "JP", "KR", "CRYPTO"}


@dataclass(frozen=True)
class RegionalTableSpec:
    name: str
    model: Any
    latest_column: Any
    symbol_column: Any | None = None
    expected_date: Callable[[datetime], date | None] | None = None


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _us_expected(now: datetime) -> date | None:
    return expected_us_trade_date("us_daily_price", now=now)


def _jp_expected(now: datetime) -> date | None:
    return expected_jp_daily_price_date(now=now)


def _kr_expected(now: datetime) -> date | None:
    return expected_kr_daily_price_date(now=now)


REGIONAL_TABLE_SPECS: dict[str, tuple[RegionalTableSpec, ...]] = {
    "US": (
        RegionalTableSpec("us_stock_master", USStockMaster, USStockMaster.last_seen_at, USStockMaster.symbol),
        RegionalTableSpec("us_daily_price", USDailyPrice, USDailyPrice.trade_date, USDailyPrice.symbol, _us_expected),
        RegionalTableSpec("us_company_profile", USCompanyProfile, USCompanyProfile.fetched_at, USCompanyProfile.symbol),
        RegionalTableSpec("us_sec_company_fact", USSecCompanyFact, USSecCompanyFact.filed_date, USSecCompanyFact.symbol),
        RegionalTableSpec("us_corporate_action", USCorporateAction, USCorporateAction.event_date, USCorporateAction.symbol),
        RegionalTableSpec("us_short_volume_daily", USShortVolumeDaily, USShortVolumeDaily.trade_date, USShortVolumeDaily.symbol, _us_expected),
    ),
    "JP": (
        RegionalTableSpec("jp_stock_master", JPStockMaster, JPStockMaster.last_seen_at, JPStockMaster.symbol),
        RegionalTableSpec("jp_daily_price", JPDailyPrice, JPDailyPrice.trade_date, JPDailyPrice.symbol, _jp_expected),
        RegionalTableSpec("jp_company_fundamental", JPCompanyFundamental, JPCompanyFundamental.disclosed_date, JPCompanyFundamental.symbol),
        RegionalTableSpec("jp_margin_interest", JPMarginInterest, JPMarginInterest.report_date, JPMarginInterest.symbol),
        RegionalTableSpec("jp_investor_type", JPInvestorType, JPInvestorType.published_date),
    ),
    "KR": (
        RegionalTableSpec("kr_stock_master", KRStockMaster, KRStockMaster.last_seen_at, KRStockMaster.symbol),
        RegionalTableSpec("kr_daily_price", KRDailyPrice, KRDailyPrice.trade_date, KRDailyPrice.symbol, _kr_expected),
        RegionalTableSpec("kr_company_fundamental", KRCompanyFundamental, KRCompanyFundamental.disclosed_date, KRCompanyFundamental.symbol),
        RegionalTableSpec("kr_investor_trade_daily", KRInvestorTradeDaily, KRInvestorTradeDaily.trade_date, KRInvestorTradeDaily.symbol, _kr_expected),
    ),
    "CRYPTO": (
        RegionalTableSpec("crypto_ticker_snapshot", CryptoTickerSnapshot, CryptoTickerSnapshot.event_time, CryptoTickerSnapshot.symbol),
        RegionalTableSpec("crypto_order_book_snapshot", CryptoOrderBookSnapshot, CryptoOrderBookSnapshot.event_time, CryptoOrderBookSnapshot.symbol),
        RegionalTableSpec("crypto_ohlcv_bar", CryptoOhlcvBar, CryptoOhlcvBar.bar_time, CryptoOhlcvBar.symbol),
        RegionalTableSpec("crypto_derivatives_metric", CryptoDerivativesMetric, CryptoDerivativesMetric.event_time, CryptoDerivativesMetric.symbol),
        RegionalTableSpec("crypto_market_cap_snapshot", CryptoMarketCapSnapshot, CryptoMarketCapSnapshot.last_updated, CryptoMarketCapSnapshot.symbol),
    ),
}


def _table_state(
    db: Session,
    *,
    spec: RegionalTableSpec,
    symbol: str | None,
    checked_at: datetime,
) -> dict[str, Any]:
    query = db.query(func.max(spec.latest_column), func.count(spec.model.id))
    if symbol and spec.symbol_column is not None:
        query = query.filter(spec.symbol_column == symbol)
    latest, row_count = query.one()
    count = int(row_count or 0)
    availability = "available" if latest is not None and count > 0 else "missing"
    expected = spec.expected_date(checked_at) if spec.expected_date is not None else None
    if availability == "missing":
        freshness = "missing"
    elif expected is None:
        freshness = "unknown"
    elif isinstance(latest, date) and latest >= expected:
        freshness = "current"
    else:
        freshness = "stale"
    return {
        "latest": _json_value(latest),
        "row_count": count,
        "availability": availability,
        "freshness": freshness,
        "expected": _json_value(expected),
    }


def read_regional_data_freshness(
    db: Session,
    *,
    market: str,
    symbol: str | None = None,
    now: Callable[[], datetime],
) -> dict[str, Any]:
    normalized_market = str(market or "").strip().upper()
    if normalized_market not in SUPPORTED_REGIONAL_FRESHNESS_MARKETS:
        raise ValueError(f"Unsupported data freshness market: {market}")
    normalized_symbol = str(symbol or "").strip().upper() or None
    checked_at = now()
    tables = {
        spec.name: _table_state(
            db,
            spec=spec,
            symbol=normalized_symbol,
            checked_at=checked_at,
        )
        for spec in REGIONAL_TABLE_SPECS[normalized_market]
    }
    missing = [name for name, info in tables.items() if info["availability"] == "missing"]
    stale = [name for name, info in tables.items() if info["freshness"] == "stale"]
    unknown = [name for name, info in tables.items() if info["freshness"] == "unknown"]
    overall_freshness = (
        "missing"
        if missing
        else "stale"
        if stale
        else "unknown"
        if unknown
        else "current"
    )
    warnings: list[str] = []
    if stale:
        warnings.append(f"Stale {normalized_market} local datasets: {', '.join(stale)}.")
    if unknown:
        warnings.append(
            f"Release calendar or TTL is not defined for {normalized_market}: {', '.join(unknown)}."
        )
    slot_status = {
        "current": "ready",
        "stale": "stale",
        "unknown": "partial",
        "missing": "missing",
    }
    slots = {
        name: slot_envelope(
            status=slot_status[info["freshness"]],
            capability=f"local_table_{name}",
            payload_ref=f"tables.{name}",
            payload_level="compact",
            as_of=info["latest"],
            missing=[name] if info["availability"] == "missing" else None,
            warnings=(
                [f"availability={info['availability']}; freshness={info['freshness']}"]
                if info["freshness"] != "current"
                else None
            ),
        )
        for name, info in tables.items()
    }
    target = {
        "type": "data_freshness",
        "id": normalized_symbol,
        "label": f"{normalized_market} data freshness",
        "market": normalized_market,
    }
    compact = {
        "kind": "data_freshness_compact_evidence",
        "version": "market_compact_evidence.v1",
        "payload_level": "compact",
        "target": target,
        "status": overall_freshness,
        "tables": tables,
        "freshness_by_domain": {
            name: info["freshness"]
            for name, info in tables.items()
        },
        "slots": slots,
    }
    as_of_values = [str(info["latest"]) for info in tables.values() if info["latest"]]
    envelope = {
        "kind": "data_freshness",
        "generated_at": checked_at,
        "as_of": max(as_of_values) if as_of_values else None,
        "scope": {"market": normalized_market, "symbol": normalized_symbol},
        "data": {
            "status": overall_freshness,
            "tables": tables,
            "compact": compact,
            "slots": slots,
        },
        "missing": missing,
        "warnings": warnings,
        "source_refs": [
            {"type": "database", "name": "open_market_intelligence.db", "market": normalized_market}
        ],
    }
    envelope["evidence_passport"] = build_evidence_passport(
        kind="data_freshness",
        as_of=envelope["as_of"],
        source_refs=envelope["source_refs"],
        missing=missing,
        warnings=warnings,
        freshness={
            "status": overall_freshness,
            "is_current": False if stale else True if not missing and not unknown else None,
            "missing": missing,
            "warnings": warnings,
        },
    )
    return envelope


__all__ = [
    "SUPPORTED_REGIONAL_FRESHNESS_MARKETS",
    "read_regional_data_freshness",
]
