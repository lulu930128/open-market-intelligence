"""KR consumer projections from one Shared-resolved, persisted daily series."""

from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import KRBarEvidence, RawFetchResult
from app.kr_market.daily_ohlcv_platform import KRDailyOhlcvPlatform, KRDailyResult
from app.kr_market.chart_projection import aggregate_daily_rows
from app.kr_market.schemas import KRDailyPriceRead
from app.kr_market.trading_calendar import KR_MARKET_TIMEZONE


def _read_partial_after_refresh(db, owner, result, *, symbol, bars, now, to_date):
    if result.result.resolved.bars:
        return result
    # Advance availability only to receipts committed by this bounded command.
    # A wall-clock reread would admit unrelated concurrent/backfilled evidence.
    receipt_ids = result.result.persistence.raw_result_ids
    cutoff = now
    if receipt_ids:
        with db.no_autoflush:
            fetched_times = db.query(RawFetchResult.fetched_at).filter(RawFetchResult.id.in_(receipt_ids)).all()
        cutoff = max((value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
                      for (value,) in fetched_times), default=now)
        cutoff = max(now, cutoff)
    partial = owner.read(symbol=symbol, bars=bars, now=cutoff, to_date=to_date)
    if partial.result.resolved.bars:
        partial.projection["limitations"] = list(dict.fromkeys((
            *result.projection["limitations"], *partial.projection["limitations"],
            "KR_HISTORY_COVERAGE_UNMET")))
        partial.projection["decision_usable"] = False
        return partial
    return result


def rows_from_result(db: Session, result: KRDailyResult) -> list[KRDailyPriceRead]:
    bars = tuple(reversed(result.result.resolved.bars))
    if not bars:
        return []
    ids = tuple(bar.lineage.observation_id for bar in bars)
    with db.no_autoflush:
        row_ids = dict(db.query(KRBarEvidence.observation_id, KRBarEvidence.id).filter(
            KRBarEvidence.observation_id.in_(ids)).all())
    output = []
    for bar in bars:
        fetched = bar.lineage.fetched_at
        output.append(KRDailyPriceRead(
            id=row_ids[bar.lineage.observation_id], provider=bar.lineage.provider,
            symbol=result.identity.storage_symbol, currency=result.identity.currency,
            trade_date=bar.end_at.astimezone(KR_MARKET_TIMEZONE).date(),
            open_price=float(bar.open_price), high_price=float(bar.high_price),
            low_price=float(bar.low_price), close_price=float(bar.close_price),
            trade_volume=int(bar.volume.value) if bar.volume else None,
            raw_payload_hash=bar.lineage.content_hash, fetched_at=fetched,
            created_at=fetched, updated_at=fetched,
            evidence_id=bar.lineage.observation_id, raw_receipt_id=bar.lineage.raw_receipt_id,
            price_basis=bar.price_basis, facts_usable=result.projection["facts_usable"],
            decision_usable=result.projection["decision_usable"], limitations=result.projection["limitations"],
        ))
    return output


def read_daily_rows(db: Session, *, symbol: str, limit=500, offset=0,
                    from_date: date | None = None, to_date: date | None = None, now=None):
    if not 1 <= limit <= 2500 or offset < 0 or limit + offset > 2500:
        raise ValueError("KR resolved daily pagination exceeds the 2500-bar bound")
    result = KRDailyOhlcvPlatform(db).read(symbol=symbol, bars=limit + offset, now=now, to_date=to_date)
    rows = rows_from_result(db, result)
    if from_date:
        rows = [row for row in rows if row.trade_date >= from_date]
    return rows[offset:offset + limit]


def read_chart(db: Session, *, symbol: str, timeframe="daily", bars=90, to_date=None, now=None, acquire=False):
    if timeframe not in {"daily", "weekly", "monthly"} or not 1 <= bars <= 5000:
        raise ValueError("Invalid KR chart timeframe or bar bound")
    now = now or datetime.now(timezone.utc)
    required_daily = bars * {"daily": 1, "weekly": 5, "monthly": 23}[timeframe]
    owner = KRDailyOhlcvPlatform(db)
    result = (owner.refresh if acquire else owner.read)(symbol=symbol,
        bars=min(2500, required_daily), now=now, to_date=to_date,
        require_history_coverage=acquire)
    persistence = result.result.persistence
    if acquire and not result.result.resolved.bars:
        # A failed coverage requirement must not hide separately usable facts.
        # This is a pure reread; it cannot start another acquisition attempt.
        result = _read_partial_after_refresh(db, owner, result, symbol=symbol,
            bars=min(2500, required_daily), now=now, to_date=to_date)
    rows = rows_from_result(db, result)
    points = result.projection["points"] if timeframe == "daily" else aggregate_daily_rows(list(reversed(rows)), timeframe)
    points = points[-bars:]
    evidence = {key: value for key, value in result.projection.items() if key != "points"}
    if evidence["coverage_status"] != "complete":
        evidence["decision_usable"] = False
    if required_daily > 2500:
        evidence["limitations"] = [*evidence["limitations"], "KR_CHART_HISTORY_BOUND_REACHED"]
        evidence["coverage_status"] = "partial" if points else "missing"
        evidence["decision_usable"] = False
    start, end = result.result.requirement.request.start_at, result.result.requirement.request.end_at
    return {
        "symbol": result.identity.storage_symbol, "timeframe": timeframe, "bars": bars,
        "lookback_days": (end - start).days, "from_date": start.date(), "to_date": end.date(),
        "point_count": len(points), "points": points, "volume_unit": "shares",
        "volume_semantics": "daily_total", "volume_status": "available" if points and all(p.get("volume") is not None for p in points) else "not_provided",
        "latest_data_date": evidence["latest_trade_date"], "expected_data_date": evidence["expected_trade_date"],
        "freshness_status": evidence["freshness_status"], "is_current": evidence["freshness_status"] == "current",
        "refresh_recommended": evidence["freshness_status"] != "current" or evidence["coverage_status"] != "complete",
        "resolved_evidence": evidence,
        "backfill": persistence.model_dump(mode="json") if acquire else None,
    }


def refresh_daily(db: Session, *, symbol, outputsize="compact", to_date=None):
    if outputsize not in {"compact", "full"}:
        raise ValueError("outputsize must be compact or full")
    owner = KRDailyOhlcvPlatform(db)
    now = datetime.now(timezone.utc)
    bars = 250 if outputsize == "compact" else 2500
    result = owner.refresh(symbol=symbol, bars=bars, now=now,
        to_date=to_date, require_history_coverage=True)
    persistence = result.result.persistence
    result = _read_partial_after_refresh(db, owner, result, symbol=symbol, bars=bars, now=now, to_date=to_date)
    return {"status": "success" if result.projection["decision_usable"] else "partial_success" if result.projection["facts_usable"] else "failed",
        "provider": result.projection["selected_provider"] or "unavailable", "symbol": result.identity.storage_symbol,
        "fetched_count": len(result.result.resolved.bars), "inserted_count": persistence.observations_inserted,
        "updated_count": 0, "message": "; ".join(result.projection["limitations"]),
        "resolved_evidence": {key: value for key, value in result.projection.items() if key != "points"}}
