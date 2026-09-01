"""Market-owned provider-neutral lifecycle for Taiwan realtime viewer leases."""

from __future__ import annotations

from datetime import datetime, timedelta
from threading import Lock

from sqlalchemy.orm import Session

from app.config import settings
from app.market.providers.kgi_canonical import KGI_PROVIDER
from app.market.providers.kgi_intraday_bars import kgi_minute_kbar_acquisition
from app.market.providers.kgi_realtime_lease import KgiRealtimeQuoteLeasePort
from app.market.providers.fugle_realtime_lease import FugleRealtimeQuoteLeasePort
from app.market.providers.fugle_realtime_runtime import get_fugle_realtime_runtime
from app.market.providers.twse_mis_canonical import MIS_SOURCE
from app.market.public_quote_platform import build_taiwan_public_quote_requirement
from app.market.public_quote_platform import acquire_taiwan_public_last_trade_quote
from app.market.taiwan_realtime_platform import (
    acquire_taiwan_auction,
    acquire_taiwan_depth,
    refresh_taiwan_realtime_snapshot,
)
from app.market.intraday_transaction import TaiwanIntradayBarTransaction
from app.market.tw_instrument import resolve_taiwan_instrument
from app.market.tw_intraday_platform import build_taiwan_intraday_requirement
from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_realtime_capabilities import (
    FUGLE_PROVIDER,
    FUGLE_QUOTE_SNAPSHOT_DESCRIPTOR,
    KGI_AUCTION_DESCRIPTOR,
    KGI_ORDER_BOOK_DESCRIPTOR,
    KGI_QUOTE_SNAPSHOT_DESCRIPTOR,
    MIS_ORDER_BOOK_DESCRIPTOR,
    TW_ORDER_BOOK_CAPABILITY_ID,
)
from app.market_data.contracts import (
    InstrumentKey,
    InstrumentType,
    MarketSession,
    ResolvedDepth,
)
from app.market_data.integration_contracts import MarketDataResultV1
from app.market_data.integration_contracts import RequestBounds
from app.market_data.policies import RealtimePolicy
from app.market_data.research_lease import (
    ViewerLeaseCoordinator,
    ViewerLeaseOwnerKind,
    ViewerLeaseState,
)


def _instrument(db: Session, stock_id: str) -> InstrumentKey:
    instrument = resolve_taiwan_instrument(db, stock_id)
    if instrument.instrument_type is InstrumentType.INDEX:
        raise ValueError("Viewer stock lease does not acquire Taiwan index events")
    return instrument


_KGI_REALTIME_PORT = KgiRealtimeQuoteLeasePort()
_FUGLE_REALTIME_PORT = FugleRealtimeQuoteLeasePort()
_KGI_BAR_MATERIALIZATION_LOCK = Lock()
_KGI_LAST_MATERIALIZED_FINAL_BAR: dict[str, str] = {}


def _coordinator() -> ViewerLeaseCoordinator:
    return ViewerLeaseCoordinator(
        descriptors=(
            KGI_QUOTE_SNAPSHOT_DESCRIPTOR,
            FUGLE_QUOTE_SNAPSHOT_DESCRIPTOR,
        ),
        ports={
            KGI_PROVIDER: _KGI_REALTIME_PORT,
            FUGLE_PROVIDER: _FUGLE_REALTIME_PORT,
        },
    )


_TAIWAN_REALTIME_VIEWER_LEASES = _coordinator()


def _has_research_usable_depth(result: MarketDataResultV1) -> bool:
    return (
        isinstance(result.resolved, ResolvedDepth)
        and result.resolved.depth is not None
        and result.resolved.health.research_usable
    )


def _sync_mis_depth_snapshot(
    db: Session,
    *,
    stock_id: str,
    requested_at: datetime,
) -> None:
    """Acquire one bounded public depth fallback through the market owner."""

    refreshed = refresh_taiwan_realtime_snapshot(
        db,
        stock_id=stock_id,
        policy=RealtimePolicy.REQUIRE_LIVE,
        requested_at=requested_at,
        requested_capabilities=(TW_ORDER_BOOK_CAPABILITY_ID,),
    )
    if not _has_research_usable_depth(refreshed.depth):
        raise RuntimeError("MIS_DEPTH_FALLBACK_UNAVAILABLE")


def _sync_canonical_snapshot(
    db: Session,
    *,
    stock_id: str,
    requested_at: datetime,
) -> None:
    adapter = _KGI_REALTIME_PORT.acquisition_adapter(clock=lambda: requested_at)
    quote = acquire_taiwan_public_last_trade_quote(
        db,
        stock_id=stock_id,
        policy=RealtimePolicy.REQUIRE_LIVE,
        requested_at=requested_at,
        acquisition=adapter,
        descriptors=(KGI_QUOTE_SNAPSHOT_DESCRIPTOR,),
    )
    _sync_kgi_minute_bars(
        db,
        stock_id=stock_id,
        requested_at=requested_at,
    )
    if quote.requirement.session is MarketSession.CLOSE_RESOLUTION:
        # During the bounded close-resolution window, the formal-match quote is
        # the only capability that remains applicable. Depth and auction routes
        # intentionally stay fail-closed after the closing auction ends.
        return
    depth = None
    try:
        depth = acquire_taiwan_depth(
            db,
            stock_id=stock_id,
            policy=RealtimePolicy.REQUIRE_LIVE,
            requested_at=requested_at,
            descriptors=(KGI_ORDER_BOOK_DESCRIPTOR,),
            acquisition=adapter,
        )
    except Exception:
        # The public fallback below owns the recovery attempt. The outer lease
        # state reports degradation only if both bounded paths fail.
        pass
    if depth is None or not _has_research_usable_depth(depth):
        _sync_mis_depth_snapshot(
            db,
            stock_id=stock_id,
            requested_at=requested_at,
        )
    session = quote.requirement.session
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


def _sync_kgi_minute_bars(
    db: Session,
    *,
    stock_id: str,
    requested_at: datetime,
) -> None:
    """Materialize at most once for each newly closed buffered minute."""

    stream = _KGI_REALTIME_PORT.market_stream_snapshot(
        stock_id,
        recent_trade_limit=1,
        auction_limit=1,
        kbar_limit=120,
    )
    rows = [
        item
        for item in stream.get("minute_kbars") or []
        if isinstance(item, dict)
    ]
    finalized_rows: list[dict] = []
    for row in rows:
        value = row.get("event_time")
        try:
            start_at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            continue
        if start_at.tzinfo is None or start_at.utcoffset() is None:
            start_at = start_at.replace(tzinfo=TAIWAN_TZ)
        if requested_at >= start_at + timedelta(minutes=1):
            finalized_rows.append(row)
    if not finalized_rows:
        return
    latest_signature = str(
        finalized_rows[-1].get("event_id")
        or finalized_rows[-1].get("event_time")
        or ""
    )
    if not latest_signature:
        return
    with _KGI_BAR_MATERIALIZATION_LOCK:
        if _KGI_LAST_MATERIALIZED_FINAL_BAR.get(stock_id) == latest_signature:
            return
        requirement = build_taiwan_intraday_requirement(
            instrument=_instrument(db, stock_id),
            interval="1m",
            range_value="1d",
            policy=RealtimePolicy.PREFER_LIVE,
            requested_at=requested_at,
            acquiring=True,
        )
        acquisition = kgi_minute_kbar_acquisition(stream, requirement)
        if not acquisition.observations:
            return
        TaiwanIntradayBarTransaction(db).persist_bar_acquisition(
            requirement,
            acquisition,
        )
        _KGI_LAST_MATERIALIZED_FINAL_BAR[stock_id] = latest_signature


def _sync_fugle_snapshot(
    db: Session,
    *,
    stock_id: str,
    requested_at: datetime,
) -> None:
    runtime = get_fugle_realtime_runtime()
    if runtime is None:
        raise RuntimeError("FUGLE_RUNTIME_UNAVAILABLE")
    runtime.materializer.materialize(db, active_stock=stock_id)
    _sync_mis_depth_snapshot(
        db,
        stock_id=stock_id,
        requested_at=requested_at,
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
        if state.provider == FUGLE_PROVIDER:
            _sync_fugle_snapshot(
                db,
                stock_id=state.stock_id,
                requested_at=requested_at,
            )
        else:
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
            max_provider_attempts=2,
            max_external_calls=0,
            max_subscriptions=1,
            timeout_seconds=max(
                KGI_QUOTE_SNAPSHOT_DESCRIPTOR.max_timeout_seconds,
                FUGLE_QUOTE_SNAPSHOT_DESCRIPTOR.max_timeout_seconds,
            ),
            max_candidates=2,
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
    fallback_error: str | None = None
    if requirement.session in MIS_ORDER_BOOK_DESCRIPTOR.supported_sessions:
        try:
            _sync_mis_depth_snapshot(
                db,
                stock_id=instrument.symbol,
                requested_at=effective_requested_at,
            )
        except Exception as exc:
            fallback_error = f"MIS_DEPTH_FALLBACK_FAILED:{type(exc).__name__}"
        else:
            return ViewerLeaseState(
                stock_id=instrument.symbol,
                provider=(
                    result.selected_provider
                    or KGI_QUOTE_SNAPSHOT_DESCRIPTOR.provider_key
                ),
                owner_kind=owner_kind,
                status="degraded",
                fallback_source=MIS_SOURCE,
                message=(
                    "broker即時租約目前不可用；已完成一次有界TWSE MIS五檔備援更新。"
                ),
                error=result.detail_code,
            )
    return ViewerLeaseState(
        stock_id=instrument.symbol,
        provider=result.selected_provider or KGI_QUOTE_SNAPSHOT_DESCRIPTOR.provider_key,
        owner_kind=owner_kind,
        status="unavailable",
        fallback_source=MIS_SOURCE,
        message=(
            "即時行情租約目前不可用；行情維持既有resolved cache。"
            if fallback_error is None
            else "即時行情租約與TWSE MIS五檔備援目前皆不可用。"
        ),
        error=(
            result.detail_code
            if fallback_error is None
            else f"{result.detail_code}:{fallback_error}"
        ),
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


def summarize_fugle_realtime_runtime() -> dict[str, object]:
    """Project provider runtime health through the market-owned boundary."""

    runtime = get_fugle_realtime_runtime()
    if runtime is not None:
        return runtime.health()
    return {
        "provider": FUGLE_PROVIDER,
        "connection": (
            "disabled" if not settings.enable_fugle_realtime else "not_started"
        ),
        "entitlement": "unknown",
        "subscriptions": {
            "maximum": 5,
            "desired_count": 0,
            "bound_count": 0,
        },
    }


__all__ = [
    "acquire_taiwan_realtime_quote_lease",
    "heartbeat_taiwan_realtime_quote_lease",
    "release_taiwan_realtime_quote_lease",
    "summarize_fugle_realtime_runtime",
    "summarize_taiwan_realtime_quote_leases",
]
