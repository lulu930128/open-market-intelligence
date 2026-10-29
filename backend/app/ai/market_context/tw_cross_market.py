from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.jp_market.daily_projection import read_daily_context_asset
from app.ai.agentic_common import _json_value
from app.db.models import (
    CryptoTickerSnapshot,
    JPDailyPrice,
    KRIndexDailyPrice,
    ResourceQuoteSnapshot,
)
from app.us_market.daily_ohlcv_platform import USDailyOhlcvPlatform


US_TARGETS = (
    ("^GSPC", "S&P 500"),
    ("^IXIC", "Nasdaq Composite"),
    ("^SOX", "Philadelphia Semiconductor Index"),
)
JP_TARGETS = (("^N225", "Nikkei 225"),)
KR_TARGETS = (("KOSPI", "KOSPI"), ("KOSDAQ", "KOSDAQ"))
RESOURCE_TARGETS = (
    ("USD-TWD", "USD/TWD"),
    ("GC", "Gold Futures"),
    ("CL", "WTI Crude Oil Futures"),
)
CRYPTO_TARGETS = (("BTC-USDT", "Bitcoin"),)


def _daily_status(value: date | None, *, now: datetime) -> str:
    if value is None:
        return "missing"
    age_days = (now.date() - value).days
    return "current" if age_days <= 7 else "stale"


def _event_status(value: datetime | None, *, now: datetime) -> str:
    if value is None:
        return "missing"
    normalized = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    reference = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    age_seconds = max(0.0, (reference.astimezone(timezone.utc) - normalized.astimezone(timezone.utc)).total_seconds())
    if age_seconds <= 15 * 60:
        return "current"
    if age_seconds <= 24 * 60 * 60:
        return "delayed"
    return "stale"


def _daily_asset(
    db: Session,
    *,
    model: Any,
    identity_field: str,
    identity: str,
    label: str,
    close_field: str,
    now: datetime,
) -> dict[str, Any] | None:
    identity_column = getattr(model, identity_field)
    rows = (
        db.query(model)
        .filter(identity_column == identity)
        .order_by(model.trade_date.desc(), model.fetched_at.desc(), model.id.desc())
        .limit(2)
        .all()
    )
    if not rows:
        return None
    latest = rows[0]
    previous = rows[1] if len(rows) > 1 else None
    close = getattr(latest, close_field, None)
    previous_close = getattr(previous, close_field, None) if previous is not None else None
    if close is None:
        close = getattr(latest, "close_price", None)
    if close is None:
        close = getattr(latest, "close_value", None)
    if previous is not None and previous_close is None:
        previous_close = getattr(previous, "close_price", None)
    if previous is not None and previous_close is None:
        previous_close = getattr(previous, "close_value", None)
    change_pct = getattr(latest, "change_pct", None)
    if change_pct is None and isinstance(close, (int, float)) and isinstance(previous_close, (int, float)) and previous_close:
        change_pct = (float(close) - float(previous_close)) / float(previous_close) * 100
    return {
        "id": identity,
        "label": label,
        "price": close,
        "change_pct": change_pct,
        "as_of": latest.trade_date.isoformat(),
        "provider": latest.provider,
        "currency": getattr(latest, "currency", None),
        "status": _daily_status(latest.trade_date, now=now),
        "source_url": getattr(latest, "source_url", None),
    }


def _us_daily_asset(
    db: Session,
    *,
    symbol: str,
    label: str,
    now: datetime,
) -> dict[str, Any] | None:
    try:
        result = USDailyOhlcvPlatform(db).read(
            symbol=symbol,
            bars=90,
            now=now,
        )
    except (LookupError, ValueError):
        return None
    from app.us_market.trading_calendar import latest_completed_us_intraday_trade_date, previous_us_trading_day
    from app.us_market.market_truth import read_us_market_truth_snapshot
    from app.us_market.market_truth_contracts import USCloseEvidenceKind
    bars = list(result.result.resolved.bars)
    expected = latest_completed_us_intraday_trade_date(now=now)
    if not bars or bars[-1].end_at.date() != expected:
        truth = read_us_market_truth_snapshot(db, symbol=symbol, evaluated_at=now)
        close = next((item for item in truth.close_evidence
            if item.evidence_id == truth.close_roles.latest_completed_id
            and item.trade_date == expected and item.display_usable
            and item.evidence_kind is USCloseEvidenceKind.FINALIZED_REGULAR_INTERVAL_CLOSE), None)
        if close is not None:
            prior_date = previous_us_trading_day(expected, include_value=False)
            previous = next((bar for bar in bars if bar.end_at.date() == prior_date), None)
            previous_close = float(previous.close_price) if previous else None
            available_at = max(close.fetched_at, close.interval_end_at,
                previous.lineage.fetched_at if previous else close.fetched_at)
            return dict(id=symbol, label=label, price=float(close.price),
                change_pct=(float(close.price) / previous_close - 1) * 100 if previous_close else None,
                as_of=expected.isoformat(), trade_date=expected.isoformat(), expected_trade_date=expected.isoformat(),
                previous_trade_date=prior_date.isoformat() if previous else None,
                change_reason=None if previous else 'EXACT_PREVIOUS_COMPLETED_SESSION_MISSING',
                available_at=available_at.isoformat(), session_end_at=close.interval_end_at.isoformat(),
                provider=close.provider, source=close.source, authority=close.authority.value,
                finalization=close.finalization.value, evidence_kind=close.evidence_kind.value,
                display_usable=True, research_usable=False, official_close_proof=close.official_close_proof.value,
                status='provisional', currency='USD', source_url=None,
                freshness_reason='regular 末分鐘收盤，非官方／日線修訂待確認')
    if not bars:
        return None
    latest = bars[-1]
    prior_date = previous_us_trading_day(latest.end_at.date(), include_value=False)
    previous = next((bar for bar in bars if bar.end_at.date() == prior_date), None)
    close = float(latest.close_price)
    previous_close = float(previous.close_price) if previous is not None else None
    change_pct = (
        (close - previous_close) / previous_close * 100
        if previous_close not in (None, 0)
        else None
    )
    # The US owner has already applied its calendar, release, receipt cutoff
    # and finalization gates. A session date is not an availability timestamp.
    # Include both receipts because the reported change uses the prior close.
    used_bars = (previous, latest) if previous is not None else (latest,)
    available_at = max(max(bar.end_at, bar.lineage.fetched_at) for bar in used_bars)
    return {
        "id": symbol,
        "label": label,
        "price": close,
        "change_pct": change_pct,
        "change_reason": None if previous else "EXACT_PREVIOUS_COMPLETED_SESSION_MISSING",
        "as_of": latest.end_at.date().isoformat(),
        "trade_date": latest.end_at.date().isoformat(),
        "expected_trade_date": result.expected_state.expected_trade_date.isoformat(),
        "session_end_at": latest.end_at.isoformat(),
        "available_at": available_at.isoformat(),
        "previous_trade_date": previous.end_at.date().isoformat() if previous else None,
        "finalization": latest.finalization.value,
        "authority": latest.lineage.authority.value,
        "provider": latest.lineage.provider,
        "currency": "USD",
        "status": "current" if result.postcondition_satisfied else "stale",
        "source_url": None,
        "source": latest.lineage.source,
        "freshness_reason": result.projection.get("selection_reason"),
    }


def _latest_resource_asset(
    db: Session,
    *,
    symbol: str,
    label: str,
    now: datetime,
) -> dict[str, Any] | None:
    row = (
        db.query(ResourceQuoteSnapshot)
        .filter(ResourceQuoteSnapshot.symbol == symbol)
        .order_by(ResourceQuoteSnapshot.event_time.desc(), ResourceQuoteSnapshot.fetched_at.desc())
        .first()
    )
    if row is None:
        return None
    event_time = row.event_time or row.fetched_at
    return {
        "id": symbol,
        "label": label,
        "price": row.last_price,
        "change_pct": row.price_change_pct,
        "as_of": _json_value(event_time),
        "provider": row.provider,
        "currency": row.quote_asset,
        "status": "delayed" if _event_status(event_time, now=now) == "current" else _event_status(event_time, now=now),
        "source_url": row.source_url,
        "watch_only": True,
        "provider_quality": "best_effort_delayed",
    }


def _latest_crypto_asset(
    db: Session,
    *,
    symbol: str,
    label: str,
    now: datetime,
) -> dict[str, Any] | None:
    row = (
        db.query(CryptoTickerSnapshot)
        .filter(CryptoTickerSnapshot.symbol == symbol)
        .order_by(CryptoTickerSnapshot.event_time.desc(), CryptoTickerSnapshot.fetched_at.desc())
        .first()
    )
    if row is None:
        return None
    event_time = row.event_time or row.fetched_at
    return {
        "id": symbol,
        "label": label,
        "price": row.last_price,
        "change_pct": row.price_change_pct_24h,
        "as_of": _json_value(event_time),
        "provider": row.provider,
        "currency": row.quote_asset,
        "status": _event_status(event_time, now=now),
        "source_url": row.source_url,
    }


def _market_pack(
    *,
    market: str,
    requested: tuple[tuple[str, str], ...],
    assets: list[dict[str, Any] | None],
) -> tuple[dict[str, Any], list[str]]:
    available = [asset for asset in assets if isinstance(asset, dict)]
    available_ids = {str(asset.get("id")) for asset in available}
    missing = [f"{market}.{identity}" for identity, _label in requested if identity not in available_ids]
    problem_count = sum(1 for asset in available if asset.get("status") not in {"current", "delayed"})
    status = "missing" if not available else "partial" if missing or problem_count else "ready"
    return {
        "market": market,
        "status": status,
        "requested_count": len(requested),
        "available_count": len(available),
        "assets": available,
        "missing": missing,
    }, missing


def read_tw_cross_market_context(
    db: Session,
    *,
    now: datetime,
) -> dict[str, Any]:
    us_assets = [
        _us_daily_asset(
            db,
            symbol=symbol,
            label=label,
            now=now,
        )
        for symbol, label in US_TARGETS
    ]
    jp_assets = [
        read_daily_context_asset(db, symbol=symbol, label=label, now=now)
        if settings.jp_canonical_daily_mode == "on" else
        _daily_asset(
            db,
            model=JPDailyPrice,
            identity_field="symbol",
            identity=symbol,
            label=label,
            close_field="adjusted_close",
            now=now,
        )
        for symbol, label in JP_TARGETS
    ]
    kr_assets = [
        _daily_asset(
            db,
            model=KRIndexDailyPrice,
            identity_field="index_id",
            identity=index_id,
            label=label,
            close_field="close_value",
            now=now,
        )
        for index_id, label in KR_TARGETS
    ]
    resource_assets = [
        _latest_resource_asset(db, symbol=symbol, label=label, now=now)
        for symbol, label in RESOURCE_TARGETS
    ]
    crypto_assets = [
        _latest_crypto_asset(db, symbol=symbol, label=label, now=now)
        for symbol, label in CRYPTO_TARGETS
    ]

    markets: dict[str, Any] = {}
    missing: list[str] = []
    for market, requested, assets in (
        ("us", US_TARGETS, us_assets),
        ("jp", JP_TARGETS, jp_assets),
        ("kr", KR_TARGETS, kr_assets),
        ("resource", RESOURCE_TARGETS, resource_assets),
        ("crypto", CRYPTO_TARGETS, crypto_assets),
    ):
        pack, pack_missing = _market_pack(market=market, requested=requested, assets=assets)
        markets[market] = pack
        missing.extend(pack_missing)

    as_of_values = [
        str(asset.get("as_of"))
        for pack in markets.values()
        for asset in pack.get("assets") or []
        if asset.get("as_of")
    ]
    ready_count = sum(1 for pack in markets.values() if pack.get("status") == "ready")
    available_count = sum(int(pack.get("available_count") or 0) for pack in markets.values())
    status = "missing" if available_count == 0 else "ready" if ready_count == len(markets) else "partial"
    return {
        "kind": "tw_cross_market_context",
        "scope": "taiwan_auxiliary_context",
        "status": status,
        "as_of": max(as_of_values) if as_of_values else None,
        "markets": markets,
        "missing": missing,
        "warnings": [
            "Cross-market pack reads bounded local cache only and does not refresh providers on the market overview read path.",
            "US/JP/KR, resource, and crypto signals are auxiliary Taiwan context, not Taiwan market breadth.",
        ],
        "source_refs": [
            {"type": "table", "name": "us_daily_price"},
            {"type": "table", "name": "jp_daily_price"},
            {"type": "table", "name": "kr_index_daily_price"},
            {"type": "table", "name": "resource_quote_snapshot"},
            {"type": "table", "name": "crypto_ticker_snapshot"},
        ],
    }
