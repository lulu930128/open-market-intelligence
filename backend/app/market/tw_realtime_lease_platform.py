"""Market-owned provider-neutral lifecycle for Taiwan realtime viewer leases."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import StockMaster
from app.market.providers.kgi_canonical import KGI_PROVIDER
from app.market.providers.kgi_realtime_lease import KgiRealtimeQuoteLeasePort
from app.market.providers.twse_mis_canonical import MIS_SOURCE
from app.market.public_quote_platform import build_taiwan_public_quote_requirement
from app.market.public_quote_platform import acquire_taiwan_public_last_trade_quote
from app.market.taiwan_realtime_platform import (
    acquire_taiwan_auction,
    acquire_taiwan_depth,
)
from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_realtime_capabilities import (
    KGI_AUCTION_DESCRIPTOR,
    KGI_ORDER_BOOK_DESCRIPTOR,
    KGI_QUOTE_SNAPSHOT_DESCRIPTOR,
)
from app.market_data.contracts import (
    InstrumentKey,
    InstrumentType,
    Market,
    MarketSession,
)
from app.market_data.integration_contracts import RequestBounds
from app.market_data.policies import RealtimePolicy
from app.market_data.research_lease import (
    ViewerLeaseCoordinator,
    ViewerLeaseOwnerKind,
    ViewerLeaseState,
)


def _instrument(db: Session, stock_id: str) -> InstrumentKey:
    normalized = str(stock_id or "").strip().upper()
    if not normalized:
        raise ValueError("stock_id is required")
    stock = db.query(StockMaster).filter(StockMaster.stock_id == normalized).first()
    if stock is None:
        raise ValueError(f"Unknown Taiwan stock id: {normalized}")
    venue = str(stock.market or "").strip().upper()
    if venue not in {"TWSE", "TPEX"}:
        raise ValueError("Taiwan realtime lease requires TWSE or TPEX")
    return InstrumentKey(
        market=Market.TW,
        symbol=normalized,
        instrument_type=(
            InstrumentType.ETF
            if str(stock.instrument_type or "").strip().casefold() == "etf"
            else InstrumentType.STOCK
        ),
        venue=venue,
    )


_KGI_REALTIME_PORT = KgiRealtimeQuoteLeasePort()


def _coordinator() -> ViewerLeaseCoordinator:
    return ViewerLeaseCoordinator(
        descriptors=(KGI_QUOTE_SNAPSHOT_DESCRIPTOR,),
        ports={KGI_PROVIDER: _KGI_REALTIME_PORT},
    )


_TAIWAN_REALTIME_VIEWER_LEASES = _coordinator()


def _sync_canonical_snapshot(
    db: Session,
    *,
    stock_id: str,
    requested_at: datetime,
) -> None:
    adapter = _KGI_REALTIME_PORT.acquisition_adapter(clock=lambda: requested_at)
    acquire_taiwan_public_last_trade_quote(
        db,
        stock_id=stock_id,
        policy=RealtimePolicy.REQUIRE_LIVE,
        requested_at=requested_at,
        acquisition=adapter,
        descriptors=(KGI_QUOTE_SNAPSHOT_DESCRIPTOR,),
    )
    depth = acquire_taiwan_depth(
        db,
        stock_id=stock_id,
        policy=RealtimePolicy.REQUIRE_LIVE,
        requested_at=requested_at,
        descriptors=(KGI_ORDER_BOOK_DESCRIPTOR,),
        acquisition=adapter,
    )
    session = depth.requirement.session
    auction_session = (
        MarketSession.OPENING_AUCTION
        if session is MarketSession.PRE_OPEN
        else session
    )
    acquire_taiwan_auction(
        db,
        stock_id=stock_id,
        policy=RealtimePolicy.REQUIRE_LIVE,
        requested_at=requested_at,
        descriptors=(KGI_AUCTION_DESCRIPTOR,),
        acquisition=adapter,
        session=auction_session,
    )


def _sync_if_live(
    db: Session,
    state: ViewerLeaseState,
    *,
    requested_at: datetime,
) -> ViewerLeaseState:
    if state.status != "live" or state.lease_id is None:
        return state
    try:
        _sync_canonical_snapshot(
            db,
            stock_id=state.stock_id,
            requested_at=requested_at,
        )
    except Exception as exc:
        return state.model_copy(
            update={
                "status": "degraded",
                "error": f"CANONICAL_SYNC_FAILED:{type(exc).__name__}",
                "message": "即時連線存在，但canonical snapshot同步失敗；讀取面維持既有resolved cache。",
            }
        )
    return state


def acquire_taiwan_realtime_quote_lease(
    db: Session,
    *,
    stock_id: str,
    owner_kind: ViewerLeaseOwnerKind = "frontend_viewer",
    requested_at: datetime | None = None,
    coordinator: ViewerLeaseCoordinator | None = None,
) -> ViewerLeaseState:
    instrument = _instrument(db, stock_id)
    effective_requested_at = requested_at or datetime.now(TAIWAN_TZ)
    requirement = build_taiwan_public_quote_requirement(
        instrument=instrument,
        policy=RealtimePolicy.REQUIRE_LIVE,
        requested_at=effective_requested_at,
        bounds=RequestBounds(
            max_provider_attempts=1,
            max_external_calls=0,
            max_subscriptions=1,
            timeout_seconds=KGI_QUOTE_SNAPSHOT_DESCRIPTOR.max_timeout_seconds,
            max_candidates=1,
            max_rows=1,
        ),
    )
    result = (coordinator or _TAIWAN_REALTIME_VIEWER_LEASES).acquire(
        requirement,
        owner_kind=owner_kind,
    )
    if result.lease is not None:
        if coordinator is not None:
            return result.lease
        return _sync_if_live(
            db,
            result.lease,
            requested_at=effective_requested_at,
        )
    return ViewerLeaseState(
        stock_id=instrument.symbol,
        provider=result.selected_provider or KGI_QUOTE_SNAPSHOT_DESCRIPTOR.provider_key,
        owner_kind=owner_kind,
        status="unavailable",
        fallback_source=MIS_SOURCE,
        message="即時行情租約目前不可用；行情維持既有resolved fallback。",
        error=result.detail_code,
    )


def heartbeat_taiwan_realtime_quote_lease(
    db: Session,
    lease_id: str,
    *,
    coordinator: ViewerLeaseCoordinator | None = None,
) -> ViewerLeaseState | None:
    state = (coordinator or _TAIWAN_REALTIME_VIEWER_LEASES).heartbeat(lease_id)
    if state is None or coordinator is not None:
        return state
    return _sync_if_live(
        db,
        state,
        requested_at=datetime.now(TAIWAN_TZ),
    )


def release_taiwan_realtime_quote_lease(
    lease_id: str,
    *,
    coordinator: ViewerLeaseCoordinator | None = None,
) -> ViewerLeaseState | None:
    return (coordinator or _TAIWAN_REALTIME_VIEWER_LEASES).release(lease_id)


def summarize_taiwan_realtime_quote_leases(
    *,
    coordinator: ViewerLeaseCoordinator | None = None,
):
    return (coordinator or _TAIWAN_REALTIME_VIEWER_LEASES).summary()


__all__ = [
    "acquire_taiwan_realtime_quote_lease",
    "heartbeat_taiwan_realtime_quote_lease",
    "release_taiwan_realtime_quote_lease",
    "summarize_taiwan_realtime_quote_leases",
]
