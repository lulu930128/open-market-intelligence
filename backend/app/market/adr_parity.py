from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import math
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import (
    MarketDailyPrice,
    ResourceQuoteSnapshot,
    TaiwanStockQuoteSnapshot,
    USDailyPrice,
)
from app.market.trading_calendar import (
    next_taiwan_trading_day,
    previous_taiwan_trading_day,
)


FX_STALE_AFTER_SECONDS = 72 * 60 * 60


@dataclass(frozen=True)
class AdrMapping:
    stock_id: str
    stock_name: str
    adr_symbol: str
    adr_name: str
    adr_exchange: str
    local_shares_per_adr: int
    source_label: str
    source_url: str
    verified_on: date


ADR_MAPPINGS: dict[str, AdrMapping] = {
    "2330": AdrMapping(
        stock_id="2330",
        stock_name="台積電",
        adr_symbol="TSM",
        adr_name="TSMC ADR",
        adr_exchange="NYSE",
        local_shares_per_adr=5,
        source_label="TSMC 2025 Form 20-F",
        source_url="https://www.sec.gov/Archives/edgar/data/1046179/000162828026025362/tsm-20251231.htm",
        verified_on=date(2026, 7, 22),
    ),
    "2303": AdrMapping(
        stock_id="2303",
        stock_name="聯電",
        adr_symbol="UMC",
        adr_name="UMC ADR",
        adr_exchange="NYSE",
        local_shares_per_adr=5,
        source_label="UMC 2025 Form 20-F",
        source_url="https://www.sec.gov/Archives/edgar/data/1033767/000119312526193757/d91630d20f.htm",
        verified_on=date(2026, 7, 22),
    ),
    "3711": AdrMapping(
        stock_id="3711",
        stock_name="日月光投控",
        adr_symbol="ASX",
        adr_name="ASE Technology ADR",
        adr_exchange="NYSE",
        local_shares_per_adr=2,
        source_label="ASE Technology 2025 Form 20-F",
        source_url="https://www.sec.gov/Archives/edgar/data/1122411/000119312526135585/d50802d20f.htm",
        verified_on=date(2026, 7, 22),
    ),
    "8150": AdrMapping(
        stock_id="8150",
        stock_name="南茂",
        adr_symbol="IMOS",
        adr_name="ChipMOS ADR",
        adr_exchange="NASDAQ",
        local_shares_per_adr=20,
        source_label="ChipMOS 2025 Form 20-F",
        source_url="https://www.sec.gov/Archives/edgar/data/1123134/000119312526153743/imos-20251231.htm",
        verified_on=date(2026, 7, 22),
    ),
}


def get_adr_mapping(stock_id: str) -> AdrMapping | None:
    return ADR_MAPPINGS.get(stock_id.strip())


def calculate_implied_tw_price(
    *,
    adr_close_usd: float,
    usd_twd: float,
    local_shares_per_adr: int,
) -> float:
    if not _positive(adr_close_usd):
        raise ValueError("adr_close_usd must be a finite positive number")
    if not _positive(usd_twd):
        raise ValueError("usd_twd must be a finite positive number")
    if local_shares_per_adr <= 0:
        raise ValueError("local_shares_per_adr must be positive")
    return adr_close_usd * usd_twd / local_shares_per_adr


def build_adr_parity_report(
    db: Session,
    stock_id: str,
    *,
    stock_name: str | None = None,
    expected_adr_trade_date: date | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any] | None:
    mapping = get_adr_mapping(stock_id)
    if mapping is None:
        return None

    now = generated_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    missing: list[str] = []
    warnings: list[str] = []
    stale_reasons: list[str] = []

    adr_row = _latest_adr_row(db, mapping.adr_symbol)
    if adr_row is None:
        missing.append(f"us_daily_price.{mapping.adr_symbol}")

    fx = _latest_usd_twd(db)
    if fx is None:
        missing.append("resource_quote_snapshot.USD-TWD")

    adr_trade_date = adr_row.trade_date if adr_row is not None else None
    tw_reference = (
        _latest_tw_daily_at_or_before(db, mapping.stock_id, adr_trade_date)
        if adr_trade_date is not None
        else None
    )
    if adr_trade_date is not None and tw_reference is None:
        missing.append(f"market_daily_price.{mapping.stock_id}.reference")

    target_tw_trade_date = (
        next_taiwan_trading_day(adr_trade_date, include_value=False)
        if adr_trade_date is not None
        else None
    )
    comparison = _latest_tw_comparison(db, mapping.stock_id)

    adr_close_usd = _number(adr_row.close_price) if adr_row is not None else None
    usd_twd = fx["usd_twd"] if fx is not None else None
    tw_reference_price_twd = (
        _number(tw_reference.close_price) if tw_reference is not None else None
    )

    implied_tw_price_twd: float | None = None
    implied_gap_pct: float | None = None
    parity_adr_price_usd: float | None = None
    remaining_gap_pct: float | None = None
    if (
        adr_close_usd is not None
        and usd_twd is not None
        and tw_reference_price_twd is not None
    ):
        implied_tw_price_twd = calculate_implied_tw_price(
            adr_close_usd=adr_close_usd,
            usd_twd=usd_twd,
            local_shares_per_adr=mapping.local_shares_per_adr,
        )
        implied_gap_pct = _pct_gap(implied_tw_price_twd, tw_reference_price_twd)
        parity_adr_price_usd = (
            tw_reference_price_twd * mapping.local_shares_per_adr / usd_twd
        )

    comparison_price = comparison["price"] if comparison is not None else None
    if implied_tw_price_twd is not None and comparison_price is not None:
        remaining_gap_pct = _pct_gap(implied_tw_price_twd, comparison_price)

    if (
        adr_trade_date is not None
        and expected_adr_trade_date is not None
        and adr_trade_date < expected_adr_trade_date
    ):
        stale_reasons.append("adr_close")
        warnings.append(
            f"ADR 收盤日 {adr_trade_date.isoformat()} 落後預期 {expected_adr_trade_date.isoformat()}。"
        )

    if fx is not None:
        fx_age_seconds = _age_seconds(now, fx["as_of"])
        fx["age_seconds"] = fx_age_seconds
        if fx["source_symbol"] == "TWD-USD":
            warnings.append("USD/TWD 由 TWD-USD 反向換算。")
        if fx_age_seconds is not None and fx_age_seconds > FX_STALE_AFTER_SECONDS:
            stale_reasons.append("fx")
            warnings.append("USD/TWD 匯率快取已超過 72 小時。")

    if adr_trade_date is not None and tw_reference is not None:
        expected_tw_reference_date = previous_taiwan_trading_day(
            adr_trade_date,
            include_value=True,
        )
        if tw_reference.trade_date < expected_tw_reference_date:
            stale_reasons.append("tw_reference")
            warnings.append(
                "台股參考收盤日 "
                f"{tw_reference.trade_date.isoformat()} 落後預期 {expected_tw_reference_date.isoformat()}。"
            )

    status = "partial" if missing else "stale" if stale_reasons else "ready"
    comparison_mode = _comparison_mode(
        comparison_trade_date=(comparison or {}).get("trade_date"),
        comparison_source=(comparison or {}).get("source"),
        target_tw_trade_date=target_tw_trade_date,
    )

    mapping_payload = asdict(mapping)
    mapping_payload["verified_on"] = mapping.verified_on.isoformat()
    source_refs = [
        {
            "type": "filing",
            "name": mapping.source_label,
            "url": mapping.source_url,
        },
        {"type": "table", "name": "us_daily_price"},
        {"type": "table", "name": "market_daily_price"},
        {"type": "table", "name": "resource_quote_snapshot"},
        {"type": "derived", "name": "app.market.adr_parity"},
    ]

    return {
        "kind": "tw_adr_parity",
        "status": status,
        "is_current": status == "ready",
        "stock_id": mapping.stock_id,
        "stock_name": stock_name or mapping.stock_name,
        "mapping": mapping_payload,
        "formula": "adr_close_usd * usd_twd / local_shares_per_adr",
        "adr_close_usd": _round(adr_close_usd),
        "adr_trade_date": _iso(adr_trade_date),
        "adr_provider": adr_row.provider if adr_row is not None else None,
        "expected_adr_trade_date": _iso(expected_adr_trade_date),
        "usd_twd": _round(usd_twd, 6),
        "fx_source_symbol": fx["source_symbol"] if fx is not None else None,
        "fx_provider": fx["provider"] if fx is not None else None,
        "fx_as_of": _iso(fx["as_of"] if fx is not None else None),
        "fx_age_seconds": fx.get("age_seconds") if fx is not None else None,
        "tw_reference_price_twd": _round(tw_reference_price_twd),
        "tw_reference_trade_date": _iso(
            tw_reference.trade_date if tw_reference is not None else None
        ),
        "tw_reference_semantics": (
            "taiwan_close_at_or_before_adr_trade_date_used_as_the_aligned_gap_baseline"
        ),
        "target_tw_trade_date": _iso(target_tw_trade_date),
        "implied_tw_price_twd": _round(implied_tw_price_twd),
        "implied_gap_pct": _round(implied_gap_pct),
        "parity_adr_price_usd": _round(parity_adr_price_usd),
        "tw_comparison_price_twd": _round(comparison_price),
        "tw_comparison_trade_date": _iso(
            comparison["trade_date"] if comparison is not None else None
        ),
        "tw_comparison_as_of": _iso(
            comparison["as_of"] if comparison is not None else None
        ),
        "tw_comparison_source": comparison["source"] if comparison is not None else None,
        "tw_comparison_semantics": (
            "latest_available_taiwan_price_used_only_for_remaining_gap"
        ),
        "tw_session_phase": comparison.get("session_phase") if comparison is not None else None,
        "comparison_mode": comparison_mode,
        "remaining_gap_pct": _round(remaining_gap_pct),
        "missing": list(dict.fromkeys(missing)),
        "warnings": list(dict.fromkeys(warnings)),
        "source_refs": source_refs,
        "freshness": {
            "adr_is_current": bool(
                adr_trade_date is not None
                and (
                    expected_adr_trade_date is None
                    or adr_trade_date >= expected_adr_trade_date
                )
            ),
            "fx_is_current": bool(fx is not None and "fx" not in stale_reasons),
            "tw_reference_is_current": bool(
                tw_reference is not None and "tw_reference" not in stale_reasons
            ),
            "stale_reasons": list(dict.fromkeys(stale_reasons)),
        },
    }


def _latest_adr_row(db: Session, symbol: str) -> USDailyPrice | None:
    rows = (
        db.query(USDailyPrice)
        .filter(USDailyPrice.symbol == symbol)
        .order_by(
            USDailyPrice.trade_date.desc(),
            USDailyPrice.updated_at.desc(),
            USDailyPrice.id.desc(),
        )
        .limit(8)
        .all()
    )
    return next((row for row in rows if _positive(row.close_price)), None)


def _latest_tw_daily_at_or_before(
    db: Session,
    stock_id: str,
    reference_date: date,
) -> MarketDailyPrice | None:
    rows = (
        db.query(MarketDailyPrice)
        .filter(
            MarketDailyPrice.stock_id == stock_id,
            MarketDailyPrice.trade_date <= reference_date,
        )
        .order_by(
            MarketDailyPrice.trade_date.desc(),
            MarketDailyPrice.updated_at.desc(),
            MarketDailyPrice.id.desc(),
        )
        .limit(12)
        .all()
    )
    return next((row for row in rows if _positive(row.close_price)), None)


def _latest_tw_comparison(db: Session, stock_id: str) -> dict[str, Any] | None:
    daily_rows = (
        db.query(MarketDailyPrice)
        .filter(MarketDailyPrice.stock_id == stock_id)
        .order_by(
            MarketDailyPrice.trade_date.desc(),
            MarketDailyPrice.updated_at.desc(),
            MarketDailyPrice.id.desc(),
        )
        .limit(12)
        .all()
    )
    daily = next((row for row in daily_rows if _positive(row.close_price)), None)

    quote_rows = (
        db.query(TaiwanStockQuoteSnapshot)
        .filter(TaiwanStockQuoteSnapshot.stock_id == stock_id)
        .order_by(
            TaiwanStockQuoteSnapshot.quote_time.desc(),
            TaiwanStockQuoteSnapshot.id.desc(),
        )
        .limit(12)
        .all()
    )
    quote = next(
        (
            row
            for row in quote_rows
            if row.trade_date is not None and _positive(row.last_price)
        ),
        None,
    )

    if quote is not None and (daily is None or quote.trade_date >= daily.trade_date):
        return {
            "price": float(quote.last_price),
            "trade_date": quote.trade_date,
            "as_of": quote.quote_time,
            "source": "taiwan_stock_quote_snapshot",
            "session_phase": quote.session_phase,
        }
    if daily is None:
        return None
    return {
        "price": float(daily.close_price),
        "trade_date": daily.trade_date,
        "as_of": None,
        "source": "market_daily_price",
        "session_phase": "daily_close",
    }


def _latest_usd_twd(db: Session) -> dict[str, Any] | None:
    for symbol in ("USD-TWD", "TWD-USD"):
        rows = (
            db.query(ResourceQuoteSnapshot)
            .filter(ResourceQuoteSnapshot.symbol == symbol)
            .order_by(
                ResourceQuoteSnapshot.fetched_at.desc(),
                ResourceQuoteSnapshot.id.desc(),
            )
            .all()
        )
        for row in rows:
            if not _positive(row.last_price):
                continue
            usd_twd = (
                float(row.last_price)
                if symbol == "USD-TWD"
                else 1 / float(row.last_price)
            )
            return {
                "usd_twd": usd_twd,
                "source_symbol": row.symbol,
                "provider": row.provider,
                "as_of": row.event_time or row.fetched_at,
            }
    return None


def _comparison_mode(
    *,
    comparison_trade_date: date | None,
    comparison_source: str | None,
    target_tw_trade_date: date | None,
) -> str:
    if target_tw_trade_date is None or comparison_trade_date is None:
        return "reference_only"
    if comparison_trade_date < target_tw_trade_date:
        return "next_tw_session"
    if comparison_trade_date == target_tw_trade_date:
        return (
            "target_session_tracking"
            if comparison_source == "taiwan_stock_quote_snapshot"
            else "target_session_review"
        )
    return "historical_review"


def _age_seconds(now: datetime, value: datetime | None) -> int | None:
    if value is None:
        return None
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return max(0, int((now.astimezone(timezone.utc) - normalized.astimezone(timezone.utc)).total_seconds()))


def _pct_gap(value: float, reference: float) -> float | None:
    if not _positive(value) or not _positive(reference):
        return None
    return ((value / reference) - 1) * 100


def _number(value: Any) -> float | None:
    return float(value) if _positive(value) else None


def _positive(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def _round(value: Any, digits: int = 4) -> float | None:
    return (
        round(float(value), digits)
        if isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        else None
    )


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
