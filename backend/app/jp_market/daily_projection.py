"""JP compatibility projections consume only shared-resolved daily evidence."""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.db.models import JPBarEvidence, JPStockMaster
from app.jp_market.daily_platform import JPDailyCandidateReader, JPDailyPlatform
from app.jp_market.daily_repository import JPDailyBarRepository
from app.jp_market.identity import read_jp_instrument
from app.jp_market.schemas import JPDailyPriceRead
from app.jp_market.trading_calendar import JP_MARKET_TIMEZONE, expected_jp_daily_price_date, previous_jp_trading_day
from app.market_data.gateway import MarketDataGateway


def read_daily_rows(db: Session, *, symbol: str, from_date: date | None = None,
                    to_date: date | None = None, limit: int = 500, offset: int = 0,
                    requested_at: datetime | None = None) -> list[JPDailyPriceRead]:
    if not 1 <= limit <= 5000 or offset < 0 or limit + offset > 5000:
        raise ValueError("JP resolved daily pagination exceeds the 5000-bar bound")
    now = requested_at or datetime.now(timezone.utc)
    completed = expected_jp_daily_price_date(now=now)
    expected = min(previous_jp_trading_day(to_date, include_value=True), completed) if to_date else completed
    start = from_date or expected - timedelta(days=3649)
    if start > expected:
        return []
    result = JPDailyPlatform(db).read(
        instrument=read_jp_instrument(db, symbol), start_date=start,
        end_date=expected, requested_at=now, max_bars=limit + offset,
    )
    selected = tuple(reversed(result.resolved.bars))[offset:offset + limit]
    if not selected:
        return []
    ids = tuple(b.lineage.observation_id for b in selected)
    with db.no_autoflush:
        row_ids = dict(db.query(JPBarEvidence.observation_id, JPBarEvidence.id).filter(JPBarEvidence.observation_id.in_(ids)).all())
    health = result.resolved.health
    limitations = tuple(dict.fromkeys((*result.limitations, *health.limitations)))
    rows = []
    for bar in selected:
        fetched = bar.lineage.fetched_at
        rows.append(JPDailyPriceRead(
            id=row_ids[bar.lineage.observation_id], provider=bar.lineage.provider,
            symbol=bar.instrument.symbol, trade_date=bar.end_at.astimezone(JP_MARKET_TIMEZONE).date(),
            currency="JPY", open_price=float(bar.open_price), high_price=float(bar.high_price),
            low_price=float(bar.low_price), close_price=float(bar.close_price), adjusted_close=None,
            trade_volume=int(bar.volume.value) if bar.volume is not None else None,
            raw_payload_hash=bar.lineage.content_hash, fetched_at=fetched,
            created_at=fetched, updated_at=fetched, evidence_id=bar.lineage.observation_id,
            raw_receipt_id=bar.lineage.raw_receipt_id, price_basis=bar.price_basis,
            facts_usable=health.facts_usable, research_usable=health.research_usable,
            resolved_status=health.status.value, limitations=limitations,
        ))
    return rows


def read_daily_context_asset(db: Session, *, symbol: str, label: str, now: datetime):
    rows = read_daily_rows(db, symbol=symbol, limit=2, requested_at=now)
    if not rows:
        return None
    latest = rows[0]
    previous = rows[1] if len(rows) > 1 else None
    if previous and previous.trade_date != previous_jp_trading_day(latest.trade_date, include_value=False):
        previous = None
    expected = expected_jp_daily_price_date(now=now)
    return {
        "id": symbol, "label": label, "price": latest.close_price,
        "change_pct": (latest.close_price - previous.close_price) / previous.close_price * 100 if previous else None,
        "as_of": latest.trade_date.isoformat(), "provider": latest.provider, "currency": "JPY",
        "status": "current" if latest.trade_date == expected and latest.research_usable else latest.resolved_status or "unknown", "source_url": None,
        "evidence_id": latest.evidence_id, "price_basis": latest.price_basis,
        "facts_usable": latest.facts_usable, "research_usable": latest.research_usable,
        "limitations": list(latest.limitations),
    }


class _SnapshotRepository:
    def __init__(self, rows):
        self.rows = rows

    def load_daily_bars(self, query):
        rows = [r for r in self.rows if query.start_date <= r[0].trade_date <= query.end_date]
        return JPDailyBarRepository.decode_rows(query, rows)


def read_overview_rows(db: Session, *, expected_trade_date: date, requested_at: datetime | None = None):
    now = requested_at or datetime.now(timezone.utc)
    snapshots = JPDailyBarRepository(db).load_recent_by_instrument(available_at=now)
    with db.no_autoflush:
        masters = {m.symbol: m for m in db.query(JPStockMaster).filter_by(is_active=True, asset_type="stock").all()}
    result = {}
    for instrument, raw_rows in snapshots:
        master = masters.get(instrument.symbol)
        if master is None or instrument.instrument_type.value != "stock":
            continue
        start = max(min(row[0].trade_date for row in raw_rows), expected_trade_date - timedelta(days=3649))
        if start > expected_trade_date:
            continue
        requirement = JPDailyPlatform.requirement(
            instrument=instrument, start_date=start, end_date=expected_trade_date,
            requested_at=now, max_bars=2,
        )
        resolved = MarketDataGateway().resolve_bars(
            requirement, reader=JPDailyCandidateReader(db, repository=_SnapshotRepository(raw_rows)),
        )
        bars = tuple(reversed(resolved.resolved.bars))
        if not bars:
            continue
        ids = {row[0].observation_id: row[0].id for row in raw_rows}
        result[instrument.symbol] = [{
            "price_id": ids[bar.lineage.observation_id], "symbol": instrument.symbol,
            "trade_date": bar.end_at.astimezone(JP_MARKET_TIMEZONE).date(),
            "close_price": float(bar.close_price), "adjusted_close": None,
            "trade_volume": int(bar.volume.value) if bar.volume else None,
            "provider": bar.lineage.provider, "fetched_at": bar.lineage.fetched_at,
            "security_name": master.security_name, "sector_33_name": master.sector_33_name,
            "date_rank": index + 1, "evidence_id": bar.lineage.observation_id,
        } for index, bar in enumerate(bars)]
    return result
