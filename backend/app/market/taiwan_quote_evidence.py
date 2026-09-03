"""Provider-neutral Taiwan quote evidence bundle for research consumers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.market.daily_ohlcv_platform import read_taiwan_official_daily
from app.market.providers.twse_mis_realtime_acquisition import (
    TwseMisRealtimeAcquisitionAdapter,
)
from app.market.public_quote_platform import (
    acquire_taiwan_session_close,
    project_taiwan_session_close,
    read_taiwan_quote_snapshot,
    read_taiwan_session_close,
)
from app.market.taiwan_realtime_platform import (
    read_taiwan_auction,
    read_taiwan_depth,
    refresh_taiwan_realtime_snapshot,
)
from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_realtime_capabilities import (
    TW_AUCTION_CAPABILITY_ID,
    TW_ORDER_BOOK_CAPABILITY_ID,
    TW_QUOTE_SNAPSHOT_CAPABILITY_ID,
)
from app.market_data.contracts import MarketSession
from app.market_data.integration_contracts import MarketDataResultV1
from app.market_data.policies import RealtimePolicy


TW_QUOTE_EVIDENCE_CAPABILITIES = (
    "quote.snapshot",
    "quote.session_close",
    TW_ORDER_BOOK_CAPABILITY_ID,
    TW_AUCTION_CAPABILITY_ID,
    "quote.official_close",
)
_QUOTE_EVIDENCE_ALIASES = {
    TW_QUOTE_SNAPSHOT_CAPABILITY_ID: "quote.snapshot",
}


@dataclass(frozen=True, slots=True)
class TaiwanQuoteEvidenceAcquisitionScope:
    requested_capabilities: tuple[str, ...]
    acquired_resources: tuple[str, ...]
    materialized_capabilities: tuple[str, ...]
    providers_attempted: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def projection(self) -> dict[str, object]:
        return {
            "contract_version": "omi.market.tw_quote_acquisition_scope.v1",
            "requested_capabilities": list(self.requested_capabilities),
            "acquired_resources": list(self.acquired_resources),
            "materialized_capabilities": list(self.materialized_capabilities),
            "providers_attempted": list(self.providers_attempted),
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True, slots=True)
class TaiwanQuoteEvidenceBundle:
    """Independent canonical results sharing one request timestamp."""

    requested_at: datetime
    quote: MarketDataResultV1
    session_close: MarketDataResultV1
    depth: MarketDataResultV1
    auction: MarketDataResultV1
    official_close: MarketDataResultV1
    acquisition_scope: TaiwanQuoteEvidenceAcquisitionScope | None = None

    @property
    def component_results(self) -> dict[str, MarketDataResultV1]:
        return {
            "quote.snapshot": self.quote,
            "quote.session_close": self.session_close,
            "quote.order_book": self.depth,
            "quote.auction": self.auction,
            "quote.official_close": self.official_close,
        }


def _auction_session(session: MarketSession) -> MarketSession:
    return (
        MarketSession.OPENING_AUCTION
        if session is MarketSession.PRE_OPEN
        else session
    )


def _normalize_requested_capabilities(
    values: Iterable[str] | None,
) -> tuple[str, ...]:
    if values is None:
        return TW_QUOTE_EVIDENCE_CAPABILITIES
    requested = {
        _QUOTE_EVIDENCE_ALIASES.get(
            str(value or "").strip(),
            str(value or "").strip(),
        )
        for value in values
    }
    requested.discard("")
    unsupported = requested - set(TW_QUOTE_EVIDENCE_CAPABILITIES)
    if unsupported:
        raise ValueError(
            "unsupported Taiwan quote evidence capabilities: "
            + ", ".join(sorted(unsupported))
        )
    return tuple(
        capability
        for capability in TW_QUOTE_EVIDENCE_CAPABILITIES
        if capability in requested
    )


def _acquisition_scope(
    *,
    requested_capabilities: tuple[str, ...],
    results: dict[str, MarketDataResultV1],
) -> TaiwanQuoteEvidenceAcquisitionScope:
    acquired_resources = tuple(
        dict.fromkeys(
            attempt.resource_id
            for result in results.values()
            for attempt in result.acquisition.resource_attempts
        )
    )
    providers_attempted = tuple(
        dict.fromkeys(
            provider
            for result in results.values()
            for provider in result.acquisition.providers_attempted
        )
    )
    resolved_fields = {
        "quote.snapshot": "quote",
        "quote.session_close": "quote",
        "quote.order_book": "depth",
        "quote.auction": "auction",
        "quote.official_close": "bars",
    }

    def is_materialized(capability: str, result: MarketDataResultV1) -> bool:
        if capability == "quote.session_close":
            return bool(project_taiwan_session_close(result)["available"])
        field = resolved_fields[capability]
        value = getattr(result.resolved, field, None)
        return bool(value) if field == "bars" else value is not None

    materialized = tuple(
        capability
        for capability, result in results.items()
        if is_materialized(capability, result)
    )
    limitations = tuple(
        f"REQUESTED_CAPABILITY_NOT_MATERIALIZED:{capability}"
        for capability in requested_capabilities
        if capability not in materialized
    )
    return TaiwanQuoteEvidenceAcquisitionScope(
        requested_capabilities=requested_capabilities,
        acquired_resources=acquired_resources,
        materialized_capabilities=materialized,
        providers_attempted=providers_attempted,
        limitations=limitations,
    )


def read_taiwan_quote_evidence_bundle(
    db: Session,
    *,
    stock_id: str,
    requested_at: datetime | None = None,
) -> TaiwanQuoteEvidenceBundle:
    """Read all canonical quote components without provider I/O or mutation."""

    now = requested_at or datetime.now(TAIWAN_TZ)
    quote = read_taiwan_quote_snapshot(
        db,
        stock_id=stock_id,
        requested_at=now,
    )
    session_close = read_taiwan_session_close(
        db,
        stock_id=stock_id,
        requested_at=now,
    )
    depth = read_taiwan_depth(
        db,
        stock_id=stock_id,
        requested_at=now,
        session=quote.requirement.session,
        closing_snapshot=quote.requirement.session
        in {MarketSession.POST_CLOSE, MarketSession.CLOSED},
    )
    auction = read_taiwan_auction(
        db,
        stock_id=stock_id,
        requested_at=now,
        session=_auction_session(quote.requirement.session),
    )
    official_close = read_taiwan_official_daily(
        db,
        stock_id=stock_id,
        limit=1,
        requested_at=now,
    )
    return TaiwanQuoteEvidenceBundle(
        requested_at=now,
        quote=quote,
        session_close=session_close,
        depth=depth,
        auction=auction,
        official_close=official_close,
    )


def acquire_taiwan_quote_evidence_bundle(
    db: Session,
    *,
    stock_id: str,
    policy: RealtimePolicy = RealtimePolicy.PREFER_LIVE,
    requested_at: datetime | None = None,
    requested_capabilities: Iterable[str] | None = None,
    acquisition: TwseMisRealtimeAcquisitionAdapter | None = None,
) -> TaiwanQuoteEvidenceBundle:
    """Run the explicit bounded market refresh, then expose canonical results."""

    if policy not in {RealtimePolicy.PREFER_LIVE, RealtimePolicy.REQUIRE_LIVE}:
        raise ValueError("Taiwan quote evidence acquisition requires a live policy")
    now = requested_at or datetime.now(TAIWAN_TZ)
    requested = _normalize_requested_capabilities(requested_capabilities)
    refreshed = refresh_taiwan_realtime_snapshot(
        db,
        stock_id=stock_id,
        policy=policy,
        requested_at=now,
        requested_capabilities=(
            (
                TW_QUOTE_SNAPSHOT_CAPABILITY_ID
                if capability == "quote.snapshot"
                else capability
            )
            for capability in requested
            if capability
            not in {"quote.official_close", "quote.session_close"}
        ),
        acquisition=acquisition,
    )
    session_close = (
        acquire_taiwan_session_close(
            db,
            stock_id=stock_id,
            requested_at=now,
            acquisition=acquisition,
        )
        if "quote.session_close" in requested
        else read_taiwan_session_close(
            db,
            stock_id=stock_id,
            requested_at=now,
        )
    )
    quote = (
        read_taiwan_quote_snapshot(db, stock_id=stock_id, requested_at=now)
        if "quote.session_close" in requested
        else refreshed.quote
    )
    auction = refreshed.auction or read_taiwan_auction(
        db,
        stock_id=stock_id,
        requested_at=now,
        session=_auction_session(refreshed.quote.requirement.session),
    )
    official_close = read_taiwan_official_daily(
        db,
        stock_id=stock_id,
        limit=1,
        requested_at=now,
    )
    realtime_results = {
        "quote.snapshot": quote,
        "quote.session_close": session_close,
        "quote.order_book": refreshed.depth,
        "quote.auction": auction,
        "quote.official_close": official_close,
    }
    return TaiwanQuoteEvidenceBundle(
        requested_at=now,
        quote=quote,
        session_close=session_close,
        depth=refreshed.depth,
        auction=auction,
        official_close=official_close,
        acquisition_scope=_acquisition_scope(
            requested_capabilities=requested,
            results=realtime_results,
        ),
    )


__all__ = [
    "TW_QUOTE_EVIDENCE_CAPABILITIES",
    "TaiwanQuoteEvidenceAcquisitionScope",
    "TaiwanQuoteEvidenceBundle",
    "acquire_taiwan_quote_evidence_bundle",
    "read_taiwan_quote_evidence_bundle",
]
