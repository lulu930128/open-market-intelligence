"""Cache-only Taiwan Stock/ETF watchlist price projection.

The watchlist is a consumer of canonical instrument evidence.  It does not own
provider selection, acquisition, persistence, breadth membership, or market
session rules.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from sqlalchemy.orm import Session

from app.market.daily_ohlcv_platform import (
    TaiwanLatestDailyEvidence,
    read_taiwan_latest_daily_evidence,
    build_taiwan_daily_cache_requirement,
    project_taiwan_latest_daily_evidence,
)
from app.db.models import StockMaster
from app.market.daily_price_candidates import TaiwanCompletedDailyCandidateReader
from app.market.daily_price_repository import TaiwanOfficialDailyBarRepository
from app.market.public_quote_repository import TaiwanPublicQuoteRepository
from app.market.public_quote_platform import (
    project_taiwan_public_last_trade_quote,
    project_taiwan_session_close,
    read_taiwan_quote_snapshot,
    read_taiwan_session_close,
    read_taiwan_session_closes,
    build_taiwan_public_quote_requirement,
    TaiwanPublicQuoteCandidateReader,
)
from app.market.taiwan_rules import expected_daily_price_date
from app.market.trading_calendar import (
    TAIWAN_TZ,
    taiwan_market_session_phase,
    taiwan_presentation_session,
)
from app.market.tw_instrument import (
    resolve_taiwan_instrument, project_taiwan_instrument,
    normalize_taiwan_instrument_id, TaiwanInstrumentResolutionError,
)
from app.market_data.contracts import InstrumentKey
from app.market_data.gateway import MarketDataGateway
from app.market_data.policies import RealtimePolicy


TW_WATCHLIST_STATE_VERSION = "omi.market.tw_watchlist_state.v1"


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _daily_projection(
    evidence: TaiwanLatestDailyEvidence | None,
) -> dict[str, object] | None:
    daily = evidence.daily if evidence is not None else None
    if daily is None:
        return None
    close = _number(daily.close_price)
    change = _number(daily.price_change)
    previous_close = (
        close - change
        if close is not None and change is not None
        else None
    )
    change_pct = (
        change / previous_close * 100
        if change is not None
        and previous_close is not None
        and previous_close != 0
        else None
    )
    return {
        "trade_date": daily.trade_date,
        "price": close,
        "previous_close": previous_close,
        "change_pct": change_pct,
        "provider": daily.provider,
        "source": daily.source,
        "as_of": daily.event_at,
    }


def _base_projection(
    instrument: InstrumentKey,
    *,
    requested_at: datetime,
) -> dict[str, object]:
    presentation = taiwan_presentation_session(requested_at)
    expected_trade_date = presentation["trade_date"]
    assert isinstance(expected_trade_date, date)
    return {
        "contract_version": TW_WATCHLIST_STATE_VERSION,
        "instrument_id": instrument.symbol,
        "instrument_type": instrument.instrument_type.value,
        "market": instrument.venue,
        "status": "missing",
        "price": None,
        "previous_close": None,
        "change_pct": None,
        "price_semantics": "unavailable",
        "trade_date": None,
        "expected_trade_date": expected_trade_date,
        "as_of": None,
        "freshness_status": "missing",
        "provider": None,
        "source": None,
        "reason_code": "WATCHLIST_EVIDENCE_MISSING",
        "warning": "No canonical quote, session-close, or official-daily evidence is available.",
        "cache_only": True,
    }


def project_taiwan_watchlist_instrument_state(
    instrument: InstrumentKey,
    *,
    requested_at: datetime,
    quote: dict[str, object] | None,
    session_close: dict[str, object] | None,
    daily: TaiwanLatestDailyEvidence | None,
) -> dict[str, object]:
    """Select one display price without merging distinct evidence identities."""

    if requested_at.tzinfo is None or requested_at.utcoffset() is None:
        raise ValueError("requested_at must be timezone-aware")
    requested_at = requested_at.astimezone(TAIWAN_TZ)
    result = _base_projection(instrument, requested_at=requested_at)
    expected_trade_date = result["expected_trade_date"]
    assert isinstance(expected_trade_date, date)
    released_daily_date = expected_daily_price_date(now=requested_at)
    phase = taiwan_market_session_phase(requested_at)
    daily_item = _daily_projection(daily)

    quote_freshness = (
        quote.get("freshness")
        if isinstance(quote, dict) and isinstance(quote.get("freshness"), dict)
        else {}
    )
    quote_trade_date = quote.get("trade_date") if isinstance(quote, dict) else None
    quote_actual = bool(
        isinstance(quote, dict)
        and quote.get("actual_trade_occurred") is True
        and quote.get("last_trade_price") is not None
    )
    quote_is_current = bool(
        quote_actual and quote_trade_date == expected_trade_date
    )

    def use_quote(*, stale: bool = False) -> dict[str, object]:
        assert quote is not None
        freshness_status = str(quote_freshness.get("status") or "unknown")
        is_stale = stale or freshness_status in {"stale", "missing", "unknown"}
        return {
            **result,
            "status": "stale" if is_stale else "observed",
            "price": _number(quote.get("last_trade_price")),
            "previous_close": _number(quote.get("previous_close")),
            "change_pct": _number(quote.get("change_pct")),
            "price_semantics": "actual_trade",
            "trade_date": quote_trade_date,
            "as_of": quote.get("last_trade_time") or quote.get("event_time"),
            "freshness_status": "stale" if is_stale else "current",
            "provider": quote.get("provider"),
            "source": quote.get("source"),
            "reason_code": (
                "WATCHLIST_LAST_TRADE_STALE"
                if is_stale
                else "WATCHLIST_CURRENT_LAST_TRADE"
            ),
            "warning": (
                "Latest canonical last trade is stale."
                if is_stale
                else None
            ),
        }

    # While the session is active, current actual-trade evidence is the price
    # identity the user is looking at.  It must not be displaced by yesterday's
    # completed daily bar.
    if phase in {"regular", "closing_auction", "close_resolution"} and quote_is_current:
        return use_quote()

    if (
        daily_item is not None
        and daily_item["trade_date"] == expected_trade_date
        and daily_item["trade_date"] == released_daily_date
    ):
        return {
            **result,
            **daily_item,
            "status": "official_close",
            "price_semantics": "official_close",
            "freshness_status": "current",
            "reason_code": "WATCHLIST_OFFICIAL_CLOSE",
            "warning": None,
        }

    if (
        isinstance(session_close, dict)
        and session_close.get("available") is True
        and session_close.get("status") == "session_final"
        and session_close.get("trade_date") == expected_trade_date
        and session_close.get("price") is not None
    ):
        previous_close = (
            _number(quote.get("previous_close"))
            if isinstance(quote, dict)
            else None
        )
        price = _number(session_close.get("price"))
        change_pct = (
            (price - previous_close) / previous_close * 100
            if price is not None
            and previous_close is not None
            and previous_close != 0
            else None
        )
        return {
            **result,
            "status": "session_final",
            "price": price,
            "previous_close": previous_close,
            "change_pct": change_pct,
            "price_semantics": "session_close",
            "trade_date": session_close.get("trade_date"),
            "as_of": session_close.get("event_time"),
            "freshness_status": "current",
            "provider": session_close.get("provider"),
            "source": session_close.get("source"),
            "reason_code": "WATCHLIST_SESSION_FINAL",
            "warning": None,
        }

    if quote_is_current:
        return use_quote()

    if daily_item is not None:
        is_latest_completed = daily_item["trade_date"] == released_daily_date
        return {
            **result,
            **daily_item,
            "status": (
                "latest_completed_session" if is_latest_completed else "stale"
            ),
            "price_semantics": "latest_completed_session_close",
            "freshness_status": "stale",
            "reason_code": (
                "WATCHLIST_LATEST_COMPLETED_SESSION"
                if is_latest_completed
                else "WATCHLIST_DAILY_STALE"
            ),
            "warning": (
                None
                if is_latest_completed
                else "Latest canonical official daily close is stale."
            ),
        }

    if quote_actual:
        return use_quote(stale=True)

    if phase in {"preopen_pending", "preopen", "regular", "closing_auction", "close_resolution"}:
        return {
            **result,
            "status": "pending",
            "freshness_status": "pending",
            "reason_code": "WATCHLIST_CURRENT_SESSION_PENDING",
            "warning": "Current-session canonical price evidence is pending.",
        }
    return result


def read_taiwan_watchlist_instrument_state(
    db: Session,
    *,
    instrument_id: str,
    requested_at: datetime | None = None,
) -> dict[str, object]:
    """Read one Stock/ETF state without provider I/O or persistence."""

    effective_requested_at = requested_at or datetime.now(TAIWAN_TZ)
    instrument = resolve_taiwan_instrument(db, instrument_id)
    phase = taiwan_market_session_phase(effective_requested_at)
    presentation = taiwan_presentation_session(effective_requested_at)
    presentation_trade_date = presentation["trade_date"]
    released_daily_date = expected_daily_price_date(now=effective_requested_at)
    daily = None
    if (
        phase in {"post_close", "market_closed"}
        and released_daily_date == presentation_trade_date
    ):
        daily = read_taiwan_latest_daily_evidence(
            db,
            instrument.symbol,
            requested_at=effective_requested_at,
        )
        daily_projection = project_taiwan_watchlist_instrument_state(
            instrument,
            requested_at=effective_requested_at,
            quote=None,
            session_close=None,
            daily=daily,
        )
        if daily_projection["status"] == "official_close":
            return daily_projection

    quote = project_taiwan_public_last_trade_quote(
        read_taiwan_quote_snapshot(
            db,
            stock_id=instrument.symbol,
            requested_at=effective_requested_at,
        )
    )
    session_close = None
    if phase in {"close_resolution", "post_close", "market_closed"}:
        session_close = project_taiwan_session_close(
            read_taiwan_session_close(
                db,
                stock_id=instrument.symbol,
                requested_at=effective_requested_at,
            )
        )
    if daily is None:
        daily = read_taiwan_latest_daily_evidence(
            db,
            instrument.symbol,
            requested_at=effective_requested_at,
        )
    return project_taiwan_watchlist_instrument_state(
        instrument,
        requested_at=effective_requested_at,
        quote=quote,
        session_close=session_close,
        daily=daily,
    )


def read_taiwan_watchlist_instrument_states(
    db: Session, *, instrument_ids: tuple[str, ...], requested_at: datetime,
) -> dict[str, dict[str, object]]:
    """Bounded request-local batch, using the same canonical resolvers as one read.

    Unmapped identities are omitted for the outward caller's explicit missing
    projection. No persistent cache, repair or provider acquisition is created.
    """
    if requested_at.tzinfo is None or requested_at.utcoffset() is None:
        raise ValueError("requested_at must be timezone-aware")
    if len(instrument_ids) > 100:
        raise ValueError("watchlist batch exceeds 100 instruments")
    ids = tuple(dict.fromkeys(normalize_taiwan_instrument_id(item) for item in instrument_ids))
    if not ids:
        return {}
    with db.no_autoflush:
        masters = {row.stock_id: row for row in db.query(StockMaster).filter(StockMaster.stock_id.in_(ids)).all()}
        instruments = []
        for symbol in ids:
            try:
                instruments.append(project_taiwan_instrument(symbol, masters.get(symbol)))
            except TaiwanInstrumentResolutionError:
                continue
        active = tuple(item for item in instruments if masters[item.symbol].is_active)
        daily_repository = TaiwanOfficialDailyBarRepository(db, available_at=requested_at)
        released = expected_daily_price_date(now=requested_at)
        daily_repository.preload_latest_stock_daily(active, end_date=released)
        daily_reader = TaiwanCompletedDailyCandidateReader(daily_repository)
        gateway = MarketDataGateway()
        daily = {
            item.symbol: project_taiwan_latest_daily_evidence(gateway.resolve_bars(
                build_taiwan_daily_cache_requirement(
                    instrument=item, from_date=daily_repository.latest_candidate_start_date(
                        instrument=item, end_date=released, max_rows=1,
                    ) or released, to_date=released, requested_at=requested_at, max_rows=1,
                ), reader=daily_reader,
            )) for item in active
        }
        quote_repository = TaiwanPublicQuoteRepository(db)
        quote_repository.preload_quote_candidates(active, requested_at=requested_at)
        quote_reader = TaiwanPublicQuoteCandidateReader(quote_repository)
        phase = taiwan_market_session_phase(requested_at)
        closes = read_taiwan_session_closes(db, instruments=active, requested_at=requested_at) if phase in {
            "close_resolution", "post_close", "market_closed",
        } else {}
        return {
            item.symbol: project_taiwan_watchlist_instrument_state(
                item, requested_at=requested_at,
                quote=project_taiwan_public_last_trade_quote(gateway.resolve_quote(
                    build_taiwan_public_quote_requirement(
                        instrument=item, policy=RealtimePolicy.CACHE_ONLY,
                        requested_at=requested_at, require_actual_trade=False,
                    ), reader=quote_reader,
                )),
                session_close=project_taiwan_session_close(closes[item.symbol]) if item.symbol in closes else None,
                daily=daily.get(item.symbol),
            ) for item in active
        }


__all__ = [
    "TW_WATCHLIST_STATE_VERSION",
    "project_taiwan_watchlist_instrument_state",
    "read_taiwan_watchlist_instrument_state",
    "read_taiwan_watchlist_instrument_states",
]
