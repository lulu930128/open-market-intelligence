from __future__ import annotations

import math
import re
from datetime import date, datetime, time, timezone
from typing import Any, Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    MarketIndexDailyStat,
    TaiwanDerivativesLargeTraderDaily,
    TaiwanFuturesTermStructureDaily,
    TaiwanOptionChainDaily,
    utc_now,
)
from app.market.providers.taifex import OPENAPI_BASE_URL, fetch_openapi_rows
from app.market.trading_calendar import latest_released_trading_day
from app.observability.provider_fallback import observe_provider_fallback


PROVIDER = "taifex_openapi"
OPTION_PRODUCT_CODE = "TXO"
FUTURES_CONTRACT_CODE = "TX"
FUTURES_SYMBOL = "TXF"
DERIVATIVES_RELEASE_TIME = time(hour=16, minute=20)
RISK_FREE_RATE = 0.0
DIVIDEND_YIELD = 0.0
CALCULATION_MODEL = "black_scholes_spot_v1"
MAX_OPTION_READ_LIMIT = 500
MAX_LARGE_TRADER_READ_LIMIT = 200
MAX_TERM_STRUCTURE_READ_LIMIT = 12

OPTION_REPORT_DATASET = "DailyMarketReportOpt"
OPTION_DELTA_DATASET = "DailyOptionsDelta"
FUTURES_REPORT_DATASET = "DailyMarketReportFut"
FUTURES_LARGE_TRADER_DATASET = "OpenInterestOfLargeTradersFutures"
OPTIONS_LARGE_TRADER_DATASET = "OpenInterestOfLargeTradersOptions"


class TaiwanDerivativesFetchError(RuntimeError):
    pass


def expected_taiwan_derivatives_date(*, now: datetime | None = None) -> date:
    return latest_released_trading_day(
        release_time=DERIVATIVES_RELEASE_TIME,
        now=now,
    )


def _clean_text(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or text.upper() in {"-", "--", "NULL", "N/A", "NONE"}:
        return None
    return text


def _number(value: Any) -> float | None:
    text = _clean_text(value)
    if text is None:
        return None
    normalized = text.replace(",", "").replace("%", "").replace("▲", "").replace("▼", "")
    try:
        result = float(normalized)
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def _integer(value: Any) -> int | None:
    parsed = _number(value)
    return int(parsed) if parsed is not None else None


def _date(value: Any) -> date | None:
    text = _clean_text(value)
    if text is None:
        return None
    digits = re.sub(r"\D", "", text)
    if len(digits) != 8:
        return None
    try:
        return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
    except ValueError:
        return None


def _option_type(value: Any) -> str | None:
    text = (_clean_text(value) or "").lower()
    if text in {"call", "c", "買權", "買"}:
        return "call"
    if text in {"put", "p", "賣權", "賣"}:
        return "put"
    return None


def _session(value: Any) -> str | None:
    text = (_clean_text(value) or "").lower()
    if text in {"一般", "regular", "regular_session"}:
        return "regular"
    if text in {"盤後", "after_hours", "after-hours", "night"}:
        return "after_hours"
    return None


def _settlement_bucket(value: Any) -> str | None:
    text = _clean_text(value)
    if text == "666666":
        return "weekly"
    if text == "999912":
        return "all_contracts"
    if text and re.fullmatch(r"\d{6}", text):
        return text
    return None


def _third_wednesday(year: int, month: int) -> date:
    first = date(year, month, 1)
    offset = (2 - first.weekday()) % 7
    return date(year, month, 1 + offset + 14)


def _monthly_expiry(contract_month: str) -> date | None:
    if not re.fullmatch(r"\d{6}", contract_month):
        return None
    try:
        return _third_wednesday(int(contract_month[:4]), int(contract_month[4:6]))
    except ValueError:
        return None


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _normal_pdf(value: float) -> float:
    return math.exp(-0.5 * value * value) / math.sqrt(2.0 * math.pi)


def _black_scholes_price(
    *,
    spot: float,
    strike: float,
    years: float,
    volatility: float,
    option_type: str,
    rate: float = RISK_FREE_RATE,
    dividend_yield: float = DIVIDEND_YIELD,
) -> float:
    sqrt_t = math.sqrt(years)
    d1 = (
        math.log(spot / strike)
        + (rate - dividend_yield + 0.5 * volatility * volatility) * years
    ) / (volatility * sqrt_t)
    d2 = d1 - volatility * sqrt_t
    discounted_spot = spot * math.exp(-dividend_yield * years)
    discounted_strike = strike * math.exp(-rate * years)
    if option_type == "call":
        return discounted_spot * _normal_cdf(d1) - discounted_strike * _normal_cdf(d2)
    return discounted_strike * _normal_cdf(-d2) - discounted_spot * _normal_cdf(-d1)


def _implied_volatility(
    *,
    option_price: float,
    spot: float,
    strike: float,
    years: float,
    option_type: str,
) -> float | None:
    intrinsic = max(spot - strike, 0.0) if option_type == "call" else max(strike - spot, 0.0)
    upper_bound = spot if option_type == "call" else strike
    if option_price < intrinsic - 1e-8 or option_price > upper_bound + 1e-8:
        return None

    low = 0.0001
    high = 5.0
    high_price = _black_scholes_price(
        spot=spot,
        strike=strike,
        years=years,
        volatility=high,
        option_type=option_type,
    )
    if high_price < option_price:
        return None

    for _ in range(100):
        mid = (low + high) / 2.0
        calculated = _black_scholes_price(
            spot=spot,
            strike=strike,
            years=years,
            volatility=mid,
            option_type=option_type,
        )
        if abs(calculated - option_price) <= 1e-7:
            return mid
        if calculated < option_price:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def _greeks(
    *,
    spot: float,
    strike: float,
    years: float,
    volatility: float,
    option_type: str,
) -> dict[str, float]:
    sqrt_t = math.sqrt(years)
    d1 = (
        math.log(spot / strike)
        + (RISK_FREE_RATE - DIVIDEND_YIELD + 0.5 * volatility * volatility) * years
    ) / (volatility * sqrt_t)
    d2 = d1 - volatility * sqrt_t
    density = _normal_pdf(d1)
    discount_spot = math.exp(-DIVIDEND_YIELD * years)
    discount_strike = math.exp(-RISK_FREE_RATE * years)
    if option_type == "call":
        delta = discount_spot * _normal_cdf(d1)
        theta_annual = (
            -(spot * discount_spot * density * volatility) / (2.0 * sqrt_t)
            - RISK_FREE_RATE * strike * discount_strike * _normal_cdf(d2)
            + DIVIDEND_YIELD * spot * discount_spot * _normal_cdf(d1)
        )
    else:
        delta = discount_spot * (_normal_cdf(d1) - 1.0)
        theta_annual = (
            -(spot * discount_spot * density * volatility) / (2.0 * sqrt_t)
            + RISK_FREE_RATE * strike * discount_strike * _normal_cdf(-d2)
            - DIVIDEND_YIELD * spot * discount_spot * _normal_cdf(-d1)
        )
    gamma = discount_spot * density / (spot * volatility * sqrt_t)
    vega_per_vol_pct = spot * discount_spot * density * sqrt_t / 100.0
    return {
        "derived_delta": delta,
        "gamma": gamma,
        "vega_per_vol_pct": vega_per_vol_pct,
        "theta_per_day": theta_annual / 365.0,
    }


def _pricing_input(row: dict[str, Any]) -> tuple[float | None, str | None]:
    settlement = _number(row.get("SettlementPrice"))
    if settlement is not None and settlement > 0:
        return settlement, "settlement"
    bid = _number(row.get("BestBid"))
    ask = _number(row.get("BestAsk"))
    if bid is not None and ask is not None and bid >= 0 and ask > 0 and ask >= bid:
        midpoint = (bid + ask) / 2.0
        if midpoint > 0:
            return midpoint, "bid_ask_midpoint"
    close = _number(row.get("Close"))
    if close is not None and close > 0:
        return close, "close"
    return None, None


def _option_calculation(
    *,
    row: dict[str, Any],
    trade_date: date,
    expiry_date: date | None,
    strike_price: float,
    option_type: str,
    spot_close: float | None,
) -> dict[str, Any]:
    base = {
        "implied_volatility_pct": None,
        "gamma": None,
        "vega_per_vol_pct": None,
        "theta_per_day": None,
        "spot_reference": spot_close,
        "pricing_source": None,
        "calculation_model": CALCULATION_MODEL,
        "calculation_status": "missing_spot" if spot_close is None else "missing_expiry",
        "risk_free_rate": RISK_FREE_RATE,
        "dividend_yield": DIVIDEND_YIELD,
    }
    if spot_close is None or spot_close <= 0:
        return base
    if expiry_date is None:
        return base
    days_to_expiry = (expiry_date - trade_date).days
    if days_to_expiry <= 0:
        return {**base, "calculation_status": "expiry_reached"}
    option_price, pricing_source = _pricing_input(row)
    if option_price is None:
        return {**base, "pricing_source": pricing_source, "calculation_status": "missing_option_price"}

    years = days_to_expiry / 365.0
    volatility = _implied_volatility(
        option_price=option_price,
        spot=spot_close,
        strike=strike_price,
        years=years,
        option_type=option_type,
    )
    if volatility is None:
        return {**base, "pricing_source": pricing_source, "calculation_status": "iv_not_solved"}
    calculated = _greeks(
        spot=spot_close,
        strike=strike_price,
        years=years,
        volatility=volatility,
        option_type=option_type,
    )
    return {
        **base,
        "implied_volatility_pct": volatility * 100.0,
        "gamma": calculated["gamma"],
        "vega_per_vol_pct": calculated["vega_per_vol_pct"],
        "theta_per_day": calculated["theta_per_day"],
        "pricing_source": pricing_source,
        "calculation_status": "ready_derived",
    }


def parse_taifex_option_chain_rows(
    option_rows: Iterable[dict[str, Any]],
    delta_rows: Iterable[dict[str, Any]],
    *,
    spot_close: float | None,
    product_code: str = OPTION_PRODUCT_CODE,
) -> list[dict[str, Any]]:
    normalized_product = product_code.strip().upper()
    delta_by_key: dict[tuple[str, str, float, str], dict[str, Any]] = {}
    for row in delta_rows:
        if str(row.get("Contract") or "").strip().upper() != normalized_product:
            continue
        option_type = _option_type(row.get("CallPut"))
        strike_price = _number(row.get("StrikePrice"))
        contract_month = _clean_text(row.get("ContractMonth(Week)"))
        if option_type is None or strike_price is None or contract_month is None:
            continue
        delta_by_key[(normalized_product, contract_month, strike_price, option_type)] = {
            "official_delta": _number(row.get("Delta")),
            "expiry_date": _date(row.get("ContractSettlementDay")),
        }

    parsed: list[dict[str, Any]] = []
    for row in option_rows:
        if str(row.get("Contract") or "").strip().upper() != normalized_product:
            continue
        trade_date = _date(row.get("Date"))
        contract_month = _clean_text(row.get("ContractMonth(Week)"))
        strike_price = _number(row.get("StrikePrice"))
        option_type = _option_type(row.get("CallPut"))
        session = _session(row.get("TradingSession"))
        if (
            trade_date is None
            or contract_month is None
            or strike_price is None
            or option_type is None
            or session is None
        ):
            continue
        delta = delta_by_key.get(
            (normalized_product, contract_month, strike_price, option_type),
            {},
        )
        expiry_date = delta.get("expiry_date")
        calculation = _option_calculation(
            row=row,
            trade_date=trade_date,
            expiry_date=expiry_date,
            strike_price=strike_price,
            option_type=option_type,
            spot_close=spot_close,
        )
        parsed.append(
            {
                "provider": PROVIDER,
                "trade_date": trade_date,
                "product_code": normalized_product,
                "contract_month": contract_month,
                "expiry_date": expiry_date,
                "strike_price": strike_price,
                "option_type": option_type,
                "session": session,
                "open_price": _number(row.get("Open")),
                "high_price": _number(row.get("High")),
                "low_price": _number(row.get("Low")),
                "close_price": _number(row.get("Close")),
                "settlement_price": _number(row.get("SettlementPrice")),
                "volume": _integer(row.get("Volume")),
                "open_interest": _integer(row.get("OpenInterest")),
                "bid_price": _number(row.get("BestBid")),
                "ask_price": _number(row.get("BestAsk")),
                "historical_high_price": _number(row.get("HistoricalHigh")),
                "historical_low_price": _number(row.get("HistoricalLow")),
                "official_delta": delta.get("official_delta"),
                **calculation,
                "source": "TAIFEX OpenAPI options daily report",
                "source_url": f"{OPENAPI_BASE_URL}/{OPTION_REPORT_DATASET}",
                "delta_source_url": f"{OPENAPI_BASE_URL}/{OPTION_DELTA_DATASET}",
            }
        )
    return parsed


def parse_taifex_large_trader_rows(
    rows: Iterable[dict[str, Any]],
    *,
    instrument_type: str,
) -> list[dict[str, Any]]:
    is_options = instrument_type == "options"
    expected_contract = OPTION_PRODUCT_CODE if is_options else FUTURES_CONTRACT_CODE
    parsed: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("Contract") or "").strip().upper() != expected_contract:
            continue
        trade_date = _date(row.get("Date"))
        settlement_bucket = _settlement_bucket(row.get("SettlementMonth"))
        raw_trader_type = _clean_text(row.get("TypeOfTraders"))
        option_type = _option_type(row.get("CallPut")) if is_options else "not_applicable"
        if trade_date is None or settlement_bucket is None or option_type is None:
            continue
        trader_type = {
            "0": "all_traders",
            "1": "specific_institution",
        }.get(raw_trader_type or "", f"unknown_{raw_trader_type or 'blank'}")
        parsed.append(
            {
                "provider": PROVIDER,
                "trade_date": trade_date,
                "instrument_type": instrument_type,
                "contract_code": expected_contract,
                "contract_name": _clean_text(row.get("ContractName")),
                "option_type": option_type,
                "settlement_bucket": settlement_bucket,
                "trader_type": trader_type,
                "top5_buy": _integer(row.get("Top5Buy")),
                "top5_sell": _integer(row.get("Top5Sell")),
                "top10_buy": _integer(row.get("Top10Buy")),
                "top10_sell": _integer(row.get("Top10Sell")),
                "market_open_interest": _integer(row.get("OIOfMarket")),
                "source": f"TAIFEX OpenAPI {instrument_type} large traders",
                "source_url": f"{OPENAPI_BASE_URL}/{OPTIONS_LARGE_TRADER_DATASET if is_options else FUTURES_LARGE_TRADER_DATASET}",
            }
        )
    return parsed


def parse_taifex_term_structure_rows(
    rows: Iterable[dict[str, Any]],
    *,
    spot_close: float | None,
) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("Contract") or "").strip().upper() != FUTURES_CONTRACT_CODE:
            continue
        contract_month = _clean_text(row.get("ContractMonth(Week)"))
        if contract_month is None or not re.fullmatch(r"\d{6}", contract_month):
            continue
        if _session(row.get("TradingSession")) != "regular":
            continue
        trade_date = _date(row.get("Date"))
        if trade_date is None:
            continue
        expiry_date = _monthly_expiry(contract_month)
        last_price = _number(row.get("Last"))
        settlement_price = _number(row.get("SettlementPrice"))
        reference_price = settlement_price if settlement_price is not None else last_price
        basis_points = None
        basis_pct = None
        annualized_basis_pct = None
        calculation_status = "missing_spot" if spot_close is None else "missing_futures_price"
        if spot_close is not None and spot_close > 0 and reference_price is not None:
            basis_points = reference_price - spot_close
            basis_pct = basis_points / spot_close * 100.0
            calculation_status = "ready"
            days_to_expiry = (expiry_date - trade_date).days if expiry_date else 0
            if days_to_expiry > 0:
                annualized_basis_pct = basis_pct * 365.0 / days_to_expiry
            else:
                calculation_status = "expiry_reached"
        parsed.append(
            {
                "provider": PROVIDER,
                "trade_date": trade_date,
                "symbol": FUTURES_SYMBOL,
                "product_code": FUTURES_CONTRACT_CODE,
                "contract_month": contract_month,
                "expiry_date": expiry_date,
                "last_price": last_price,
                "settlement_price": settlement_price,
                "open_interest": _integer(row.get("OpenInterest")),
                "spot_close": spot_close,
                "basis_points": basis_points,
                "basis_pct": basis_pct,
                "annualized_basis_pct": annualized_basis_pct,
                "calculation_status": calculation_status,
                "source": "TAIFEX OpenAPI futures daily report",
                "source_url": f"{OPENAPI_BASE_URL}/{FUTURES_REPORT_DATASET}",
            }
        )
    return sorted(parsed, key=lambda item: item["contract_month"])


def _latest_payload_date(*payloads: Iterable[dict[str, Any]]) -> date | None:
    available = [
        parsed
        for payload in payloads
        for row in payload
        if (parsed := _date(row.get("Date"))) is not None
    ]
    return max(available) if available else None


def _spot_close(db: Session, trade_date: date | None) -> float | None:
    if trade_date is None:
        return None
    row = (
        db.query(MarketIndexDailyStat)
        .filter(MarketIndexDailyStat.index_id == "TAIEX")
        .filter(MarketIndexDailyStat.trade_date == trade_date)
        .first()
    )
    return float(row.close_value) if row is not None and row.close_value is not None else None


def _upsert_option_rows(
    db: Session,
    rows: list[dict[str, Any]],
    *,
    fetched_at: datetime,
) -> int:
    if not rows:
        return 0
    trade_dates = {row["trade_date"] for row in rows}
    existing = (
        db.query(TaiwanOptionChainDaily)
        .filter(TaiwanOptionChainDaily.provider == PROVIDER)
        .filter(TaiwanOptionChainDaily.trade_date.in_(trade_dates))
        .all()
    )
    by_key = {
        (
            row.trade_date,
            row.product_code,
            row.contract_month,
            row.strike_price,
            row.option_type,
            row.session,
        ): row
        for row in existing
    }
    for payload in rows:
        key = (
            payload["trade_date"],
            payload["product_code"],
            payload["contract_month"],
            payload["strike_price"],
            payload["option_type"],
            payload["session"],
        )
        model = by_key.get(key)
        if model is None:
            model = TaiwanOptionChainDaily(**payload, fetched_at=fetched_at)
            db.add(model)
            by_key[key] = model
        else:
            for field, value in payload.items():
                setattr(model, field, value)
            model.fetched_at = fetched_at
    return len(rows)


def _upsert_large_trader_rows(
    db: Session,
    rows: list[dict[str, Any]],
    *,
    fetched_at: datetime,
) -> int:
    if not rows:
        return 0
    trade_dates = {row["trade_date"] for row in rows}
    existing = (
        db.query(TaiwanDerivativesLargeTraderDaily)
        .filter(TaiwanDerivativesLargeTraderDaily.provider == PROVIDER)
        .filter(TaiwanDerivativesLargeTraderDaily.trade_date.in_(trade_dates))
        .all()
    )
    by_key = {
        (
            row.trade_date,
            row.instrument_type,
            row.contract_code,
            row.option_type,
            row.settlement_bucket,
            row.trader_type,
        ): row
        for row in existing
    }
    for payload in rows:
        key = (
            payload["trade_date"],
            payload["instrument_type"],
            payload["contract_code"],
            payload["option_type"],
            payload["settlement_bucket"],
            payload["trader_type"],
        )
        model = by_key.get(key)
        if model is None:
            model = TaiwanDerivativesLargeTraderDaily(**payload, fetched_at=fetched_at)
            db.add(model)
            by_key[key] = model
        else:
            for field, value in payload.items():
                setattr(model, field, value)
            model.fetched_at = fetched_at
    return len(rows)


def _upsert_term_structure_rows(
    db: Session,
    rows: list[dict[str, Any]],
    *,
    fetched_at: datetime,
) -> int:
    if not rows:
        return 0
    trade_dates = {row["trade_date"] for row in rows}
    existing = (
        db.query(TaiwanFuturesTermStructureDaily)
        .filter(TaiwanFuturesTermStructureDaily.provider == PROVIDER)
        .filter(TaiwanFuturesTermStructureDaily.trade_date.in_(trade_dates))
        .all()
    )
    by_key = {
        (row.trade_date, row.symbol, row.contract_month): row
        for row in existing
    }
    for payload in rows:
        key = (payload["trade_date"], payload["symbol"], payload["contract_month"])
        model = by_key.get(key)
        if model is None:
            model = TaiwanFuturesTermStructureDaily(**payload, fetched_at=fetched_at)
            db.add(model)
            by_key[key] = model
        else:
            for field, value in payload.items():
                setattr(model, field, value)
            model.fetched_at = fetched_at
    return len(rows)


def refresh_taiwan_derivatives(
    db: Session,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    datasets = (
        OPTION_REPORT_DATASET,
        OPTION_DELTA_DATASET,
        FUTURES_REPORT_DATASET,
        FUTURES_LARGE_TRADER_DATASET,
        OPTIONS_LARGE_TRADER_DATASET,
    )
    payloads: dict[str, list[dict[str, Any]]] = {}
    errors: dict[str, str] = {}
    for dataset in datasets:
        target = OPTION_PRODUCT_CODE if "Opt" in dataset or "Options" in dataset else FUTURES_SYMBOL
        try:
            payloads[dataset] = fetch_openapi_rows(dataset, target=target)
        except Exception as exc:
            errors[dataset] = str(exc)
            observe_provider_fallback(
                exc,
                operation=f"tw_derivatives.{dataset}",
            )

    if not payloads:
        detail = "; ".join(f"{key}: {value}" for key, value in errors.items())
        raise TaiwanDerivativesFetchError(
            f"All TAIFEX derivatives datasets failed: {detail}"
        )

    expected_trade_date = expected_taiwan_derivatives_date(now=now)
    dataset_trade_dates = {
        dataset: _latest_payload_date(rows)
        for dataset, rows in payloads.items()
    }
    stale_datasets = sorted(
        dataset
        for dataset, trade_date in dataset_trade_dates.items()
        if trade_date is not None and trade_date != expected_trade_date
    )
    unverified_date_datasets = sorted(
        dataset
        for dataset, trade_date in dataset_trade_dates.items()
        if trade_date is None
    )
    latest_date = _latest_payload_date(*payloads.values())
    spot_close = _spot_close(db, latest_date)
    option_rows = parse_taifex_option_chain_rows(
        payloads.get(OPTION_REPORT_DATASET, []),
        payloads.get(OPTION_DELTA_DATASET, []),
        spot_close=spot_close,
    )
    curve_rows = parse_taifex_term_structure_rows(
        payloads.get(FUTURES_REPORT_DATASET, []),
        spot_close=spot_close,
    )
    large_trader_rows = [
        *parse_taifex_large_trader_rows(
            payloads.get(FUTURES_LARGE_TRADER_DATASET, []),
            instrument_type="futures",
        ),
        *parse_taifex_large_trader_rows(
            payloads.get(OPTIONS_LARGE_TRADER_DATASET, []),
            instrument_type="options",
        ),
    ]
    fetched_at = utc_now()
    try:
        counts = {
            "options_chain": _upsert_option_rows(db, option_rows, fetched_at=fetched_at),
            "large_traders": _upsert_large_trader_rows(
                db,
                large_trader_rows,
                fetched_at=fetched_at,
            ),
            "term_structure": _upsert_term_structure_rows(
                db,
                curve_rows,
                fetched_at=fetched_at,
            ),
        }
        db.commit()
    except Exception:
        db.rollback()
        raise

    status = (
        "ready"
        if (
            not errors
            and not stale_datasets
            and all(counts.values())
            and spot_close is not None
        )
        else "partial"
    )
    return {
        "status": status,
        "as_of": latest_date,
        "expected_trade_date": expected_trade_date,
        "is_stale": bool(stale_datasets),
        "dataset_trade_dates": dataset_trade_dates,
        "stale_datasets": stale_datasets,
        "unverified_date_datasets": unverified_date_datasets,
        "provider": PROVIDER,
        "provider_request_count": len(datasets),
        "successful_request_count": len(payloads),
        "failed_request_count": len(errors),
        "counts": counts,
        "calculation": {
            "model": CALCULATION_MODEL,
            "risk_free_rate": RISK_FREE_RATE,
            "dividend_yield": DIVIDEND_YIELD,
            "spot_reference": spot_close,
            "is_official": False,
        },
        "errors": errors,
        "warnings": [
            "TAIFEX option and large-trader datasets are official post-close data, not live night-session positioning.",
            "Implied volatility, Gamma, Vega, Theta, basis, and curve slope are OMI-derived research approximations.",
            *(
                [
                    "Some TAIFEX derivatives datasets have not reached the expected trade date; successful older rows remain cached but the refresh is incomplete."
                ]
                if stale_datasets
                else []
            ),
            *(
                [
                    "Some TAIFEX latest-snapshot datasets do not expose an independent trade-date field; their request succeeded but date verification is unavailable."
                ]
                if unverified_date_datasets
                else []
            ),
        ],
    }


def _latest_model_date(db: Session, model: Any) -> date | None:
    value = db.query(func.max(model.trade_date)).scalar()
    return value if isinstance(value, date) else None


def list_taiwan_option_chain(
    db: Session,
    *,
    trade_date: date | None = None,
    product_code: str = OPTION_PRODUCT_CODE,
    contract_month: str | None = None,
    session: str = "regular",
    option_type: str | None = None,
    center_strike: float | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[TaiwanOptionChainDaily]:
    if not 1 <= limit <= MAX_OPTION_READ_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_OPTION_READ_LIMIT}.")
    if offset < 0 or offset > 10000:
        raise ValueError("offset must be between 0 and 10000.")
    if session not in {"regular", "after_hours", "all"}:
        raise ValueError("session must be regular, after_hours, or all.")
    if option_type not in {None, "call", "put"}:
        raise ValueError("option_type must be call or put.")
    normalized_product = product_code.strip().upper()
    resolved_date = trade_date or _latest_model_date(db, TaiwanOptionChainDaily)
    if resolved_date is None:
        return []
    query = (
        db.query(TaiwanOptionChainDaily)
        .filter(TaiwanOptionChainDaily.trade_date == resolved_date)
        .filter(TaiwanOptionChainDaily.product_code == normalized_product)
    )
    if contract_month:
        query = query.filter(TaiwanOptionChainDaily.contract_month == contract_month)
    if session != "all":
        query = query.filter(TaiwanOptionChainDaily.session == session)
    if option_type:
        query = query.filter(TaiwanOptionChainDaily.option_type == option_type)
    if center_strike is not None:
        query = query.order_by(
            func.abs(TaiwanOptionChainDaily.strike_price - float(center_strike)),
            TaiwanOptionChainDaily.contract_month.asc(),
            TaiwanOptionChainDaily.strike_price.asc(),
            TaiwanOptionChainDaily.option_type.asc(),
        )
    else:
        query = query.order_by(
            TaiwanOptionChainDaily.contract_month.asc(),
            TaiwanOptionChainDaily.strike_price.asc(),
            TaiwanOptionChainDaily.option_type.asc(),
        )
    return query.offset(offset).limit(limit).all()


def list_taiwan_large_traders(
    db: Session,
    *,
    trade_date: date | None = None,
    instrument_type: str | None = None,
    settlement_bucket: str | None = None,
    trader_type: str | None = None,
    limit: int = 100,
) -> list[TaiwanDerivativesLargeTraderDaily]:
    if not 1 <= limit <= MAX_LARGE_TRADER_READ_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LARGE_TRADER_READ_LIMIT}.")
    if instrument_type not in {None, "futures", "options"}:
        raise ValueError("instrument_type must be futures or options.")
    if trader_type not in {None, "all_traders", "specific_institution"}:
        raise ValueError("trader_type must be all_traders or specific_institution.")
    resolved_date = trade_date or _latest_model_date(db, TaiwanDerivativesLargeTraderDaily)
    if resolved_date is None:
        return []
    query = db.query(TaiwanDerivativesLargeTraderDaily).filter(
        TaiwanDerivativesLargeTraderDaily.trade_date == resolved_date
    )
    if instrument_type:
        query = query.filter(
            TaiwanDerivativesLargeTraderDaily.instrument_type == instrument_type
        )
    if settlement_bucket:
        query = query.filter(
            TaiwanDerivativesLargeTraderDaily.settlement_bucket == settlement_bucket
        )
    if trader_type:
        query = query.filter(TaiwanDerivativesLargeTraderDaily.trader_type == trader_type)
    return (
        query.order_by(
            TaiwanDerivativesLargeTraderDaily.instrument_type.asc(),
            TaiwanDerivativesLargeTraderDaily.option_type.asc(),
            TaiwanDerivativesLargeTraderDaily.settlement_bucket.asc(),
            TaiwanDerivativesLargeTraderDaily.trader_type.asc(),
        )
        .limit(limit)
        .all()
    )


def list_taiwan_term_structure(
    db: Session,
    *,
    trade_date: date | None = None,
    symbol: str = FUTURES_SYMBOL,
    limit: int = MAX_TERM_STRUCTURE_READ_LIMIT,
) -> list[TaiwanFuturesTermStructureDaily]:
    if not 1 <= limit <= MAX_TERM_STRUCTURE_READ_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_TERM_STRUCTURE_READ_LIMIT}.")
    resolved_date = trade_date or _latest_model_date(db, TaiwanFuturesTermStructureDaily)
    if resolved_date is None:
        return []
    return (
        db.query(TaiwanFuturesTermStructureDaily)
        .filter(TaiwanFuturesTermStructureDaily.trade_date == resolved_date)
        .filter(TaiwanFuturesTermStructureDaily.symbol == symbol.strip().upper())
        .order_by(TaiwanFuturesTermStructureDaily.contract_month.asc())
        .limit(limit)
        .all()
    )


def option_chain_row_to_dict(row: TaiwanOptionChainDaily) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def large_trader_row_to_dict(row: TaiwanDerivativesLargeTraderDaily) -> dict[str, Any]:
    result = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    market_oi = row.market_open_interest
    for field in ("top5_buy", "top5_sell", "top10_buy", "top10_sell"):
        value = getattr(row, field)
        result[f"{field}_concentration_pct"] = (
            value / market_oi * 100.0
            if value is not None and market_oi not in {None, 0}
            else None
        )
    return result


def term_structure_row_to_dict(row: TaiwanFuturesTermStructureDaily) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def build_taiwan_derivatives_summary(
    db: Session,
    *,
    option_contract_month: str | None = None,
    option_strike_limit: int = 11,
) -> dict[str, Any]:
    bounded_strike_limit = min(max(option_strike_limit, 3), 25)
    option_date = _latest_model_date(db, TaiwanOptionChainDaily)
    option_query = db.query(TaiwanOptionChainDaily)
    if option_date is not None:
        option_query = option_query.filter(TaiwanOptionChainDaily.trade_date == option_date)
    option_query = option_query.filter(TaiwanOptionChainDaily.session == "regular")
    if option_contract_month:
        option_query = option_query.filter(
            TaiwanOptionChainDaily.contract_month == option_contract_month
        )
    option_rows = option_query.order_by(
        TaiwanOptionChainDaily.contract_month.asc(),
        TaiwanOptionChainDaily.strike_price.asc(),
        TaiwanOptionChainDaily.option_type.asc(),
    ).all() if option_date is not None else []

    selected_expiry = option_contract_month
    if selected_expiry is None and option_rows:
        future_rows = [
            row
            for row in option_rows
            if option_date is not None
            and row.expiry_date is not None
            and row.expiry_date > option_date
        ]
        selection_pool = future_rows or option_rows
        selected_expiry = min(
            selection_pool,
            key=lambda row: (row.expiry_date or date.max, row.contract_month),
        ).contract_month
    expiry_rows = [row for row in option_rows if row.contract_month == selected_expiry]
    spot = next((row.spot_reference for row in expiry_rows if row.spot_reference), None)
    unique_strikes = sorted({row.strike_price for row in expiry_rows})
    if spot is not None:
        unique_strikes = sorted(unique_strikes, key=lambda value: (abs(value - spot), value))
    selected_strikes = set(unique_strikes[:bounded_strike_limit])
    selected_rows = [row for row in expiry_rows if row.strike_price in selected_strikes]
    selected_rows.sort(key=lambda row: (row.strike_price, row.option_type))

    def closest_delta(option_type: str) -> TaiwanOptionChainDaily | None:
        candidates = [
            row
            for row in expiry_rows
            if row.option_type == option_type
            and row.official_delta is not None
            and row.implied_volatility_pct is not None
        ]
        return min(
            candidates,
            key=lambda row: abs(abs(float(row.official_delta)) - 0.25),
            default=None,
        )

    call_25 = closest_delta("call")
    put_25 = closest_delta("put")
    skew = (
        float(put_25.implied_volatility_pct) - float(call_25.implied_volatility_pct)
        if call_25 is not None and put_25 is not None
        else None
    )
    calculated_count = sum(
        1 for row in expiry_rows if row.calculation_status == "ready_derived"
    )

    large_rows = list_taiwan_large_traders(
        db,
        settlement_bucket="all_contracts",
        limit=20,
    )
    curve_rows = list_taiwan_term_structure(db, limit=MAX_TERM_STRUCTURE_READ_LIMIT)
    curve = [term_structure_row_to_dict(row) for row in curve_rows]
    curve_shape = None
    front_next_spread = None
    if len(curve_rows) >= 2:
        front = curve_rows[0].settlement_price or curve_rows[0].last_price
        next_price = curve_rows[1].settlement_price or curve_rows[1].last_price
        if front is not None and next_price is not None:
            front_next_spread = next_price - front
            curve_shape = "contango" if front_next_spread > 0 else "backwardation" if front_next_spread < 0 else "flat"

    resource_dates = {
        "taifex_txo_option_chain": option_date,
        "taifex_large_trader_positions": (
            large_rows[0].trade_date if large_rows else None
        ),
        "taifex_txf_term_structure": (
            curve_rows[0].trade_date if curve_rows else None
        ),
    }
    as_of_candidates = [value for value in resource_dates.values() if value is not None]
    as_of = max(as_of_candidates) if as_of_candidates else None
    expected_date = expected_taiwan_derivatives_date()
    missing: list[str] = []
    if not option_rows:
        missing.append("taifex_txo_option_chain")
    if not large_rows:
        missing.append("taifex_large_trader_positions")
    if not curve_rows:
        missing.append("taifex_txf_term_structure")
    stale = sorted(
        resource
        for resource, trade_date in resource_dates.items()
        if trade_date is not None and trade_date < expected_date
    )
    is_stale = bool(stale) or as_of is None
    status = "missing" if len(missing) == 3 else "partial" if missing or is_stale or calculated_count < len(expiry_rows) else "ready"
    return {
        "status": status,
        "as_of": as_of,
        "expected_trade_date": expected_date,
        "is_stale": is_stale,
        "stale": stale,
        "options_chain": {
            "status": "missing" if not option_rows else "partial" if calculated_count < len(expiry_rows) else "ready",
            "trade_date": option_date,
            "product_code": OPTION_PRODUCT_CODE,
            "contract_month": selected_expiry,
            "spot_reference": spot,
            "available_contract_months": sorted({row.contract_month for row in option_rows}),
            "total_rows_for_contract": len(expiry_rows),
            "calculated_rows": calculated_count,
            "projected_strike_count": len(selected_strikes),
            "rows": [option_chain_row_to_dict(row) for row in selected_rows],
            "iv_skew": {
                "method": "official_delta_nearest_25",
                "put_iv_pct": put_25.implied_volatility_pct if put_25 else None,
                "call_iv_pct": call_25.implied_volatility_pct if call_25 else None,
                "put_minus_call_iv_pct_points": skew,
            },
            "calculation": {
                "model": CALCULATION_MODEL,
                "risk_free_rate": RISK_FREE_RATE,
                "dividend_yield": DIVIDEND_YIELD,
                "is_official": False,
                "official_field": "official_delta",
            },
        },
        "large_traders": {
            "status": "ready" if large_rows else "missing",
            "trade_date": large_rows[0].trade_date if large_rows else None,
            "rows": [large_trader_row_to_dict(row) for row in large_rows],
            "semantics": "Concentration of the top five/ten all traders and the specific-institution subset; not foreign-investor direction.",
        },
        "term_structure": {
            "status": "ready" if curve_rows and all(row.calculation_status == "ready" for row in curve_rows) else "partial" if curve_rows else "missing",
            "trade_date": curve_rows[0].trade_date if curve_rows else None,
            "curve_shape": curve_shape,
            "front_next_spread_points": front_next_spread,
            "rows": curve,
        },
        "missing": missing,
        "warnings": [
            "TAIFEX option chain, Delta, and large-trader concentration are official post-close data, not live night-session positioning.",
            "IV, Gamma, Vega, Theta, basis, annualized basis, and curve shape are OMI-derived research approximations with visible assumptions.",
            "Large-trader concentration must not be interpreted as foreign-investor net long or net short positioning.",
        ],
        "source_refs": [
            {"type": "table", "name": "taiwan_option_chain_daily"},
            {"type": "table", "name": "taiwan_derivatives_large_trader_daily"},
            {"type": "table", "name": "taiwan_futures_term_structure_daily"},
            {"type": "provider", "name": "TAIFEX OpenAPI"},
        ],
    }


__all__ = [
    "CALCULATION_MODEL",
    "DERIVATIVES_RELEASE_TIME",
    "DIVIDEND_YIELD",
    "FUTURES_SYMBOL",
    "MAX_LARGE_TRADER_READ_LIMIT",
    "MAX_OPTION_READ_LIMIT",
    "MAX_TERM_STRUCTURE_READ_LIMIT",
    "OPTION_PRODUCT_CODE",
    "PROVIDER",
    "RISK_FREE_RATE",
    "TaiwanDerivativesFetchError",
    "build_taiwan_derivatives_summary",
    "expected_taiwan_derivatives_date",
    "large_trader_row_to_dict",
    "list_taiwan_large_traders",
    "list_taiwan_option_chain",
    "list_taiwan_term_structure",
    "option_chain_row_to_dict",
    "parse_taifex_large_trader_rows",
    "parse_taifex_option_chain_rows",
    "parse_taifex_term_structure_rows",
    "refresh_taiwan_derivatives",
    "term_structure_row_to_dict",
]
