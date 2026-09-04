"""Taiwan-owned instrument trading-mode and auction applicability policy.

Market session is a market-wide fact.  Disposition batch matching is an
instrument-specific regulatory fact and must not be inferred from a false-y
or missing cache result.  This module is deliberately pure: it performs no
provider I/O, persistence, selection, or session discovery.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from datetime import datetime
from typing import Any, Mapping

from app.market.trading_calendar import (
    TAIWAN_CLOSING_AUCTION_TIME,
    TAIWAN_SESSION_OPEN_TIME,
    TAIWAN_TZ,
)
from app.market_data.contracts import AuctionType, MarketSession


TAIWAN_TRADING_POLICY_VERSION = "tw.instrument_trading_policy.v2"


class TaiwanInstrumentTradingMode(str, Enum):
    UNKNOWN = "unknown"
    CONTINUOUS = "continuous"
    DISPOSITION_BATCH_AUCTION = "disposition_batch_auction"


class TaiwanAnalysisBasis(str, Enum):
    UNKNOWN = "unknown"
    TIME_BARS = "time_bars"
    EFFECTIVE_MATCHES = "effective_matches"


@dataclass(frozen=True, slots=True)
class TaiwanInstrumentTradingPolicy:
    market_semantics_usable: bool
    trading_mode: TaiwanInstrumentTradingMode
    analysis_basis: TaiwanAnalysisBasis
    disposition_active: bool | None
    cache_status: str
    reason_codes: tuple[str, ...]

    def projection(self) -> dict[str, Any]:
        return {
            "market_semantics_usable": self.market_semantics_usable,
            "trading_mode": self.trading_mode.value,
            "analysis_basis": self.analysis_basis.value,
            "disposition_active": self.disposition_active,
            "market_semantics_reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True, slots=True)
class TaiwanAuctionApplicability:
    applicable: bool | None
    auction_type: AuctionType | None
    trading_policy: TaiwanInstrumentTradingPolicy
    reason_codes: tuple[str, ...]


def is_taiwan_continuous_time_bar_start(value: datetime) -> bool:
    """Return whether a timestamp can anchor a continuous-matching time bar.

    The 13:25-13:30 closing auction is event evidence, not a regular 1m time
    bar.  Every provider/materializer calls this owner instead of maintaining a
    local clock range.
    """

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Taiwan bar timestamps must be timezone-aware")
    clock = value.astimezone(TAIWAN_TZ).time().replace(tzinfo=None)
    return TAIWAN_SESSION_OPEN_TIME <= clock < TAIWAN_CLOSING_AUCTION_TIME


def resolve_taiwan_instrument_trading_policy(
    disposition: Mapping[str, Any] | None,
) -> TaiwanInstrumentTradingPolicy:
    payload = disposition if isinstance(disposition, Mapping) else {}
    cache_status = str(payload.get("cache_status") or "missing").strip().lower()
    if cache_status != "current":
        return TaiwanInstrumentTradingPolicy(
            market_semantics_usable=False,
            trading_mode=TaiwanInstrumentTradingMode.UNKNOWN,
            analysis_basis=TaiwanAnalysisBasis.UNKNOWN,
            disposition_active=None,
            cache_status=cache_status,
            reason_codes=(f"DISPOSITION_CACHE_{cache_status.upper()}",),
        )

    active_value = payload.get("is_active")
    if not isinstance(active_value, bool):
        return TaiwanInstrumentTradingPolicy(
            market_semantics_usable=False,
            trading_mode=TaiwanInstrumentTradingMode.UNKNOWN,
            analysis_basis=TaiwanAnalysisBasis.UNKNOWN,
            disposition_active=None,
            cache_status=cache_status,
            reason_codes=("DISPOSITION_ACTIVE_UNKNOWN",),
        )

    active = active_value
    return TaiwanInstrumentTradingPolicy(
        market_semantics_usable=True,
        trading_mode=(
            TaiwanInstrumentTradingMode.DISPOSITION_BATCH_AUCTION
            if active
            else TaiwanInstrumentTradingMode.CONTINUOUS
        ),
        analysis_basis=(
            TaiwanAnalysisBasis.EFFECTIVE_MATCHES
            if active
            else TaiwanAnalysisBasis.TIME_BARS
        ),
        disposition_active=active,
        cache_status=cache_status,
        reason_codes=(
            (
                "DISPOSITION_BATCH_AUCTION_ACTIVE"
                if active
                else "DISPOSITION_NOT_ACTIVE"
            ),
        ),
    )


def continuous_taiwan_trading_policy(
    *,
    reason_code: str = "INSTRUMENT_CONTINUOUS_TIME_BARS",
) -> TaiwanInstrumentTradingPolicy:
    """Create the explicit policy for instruments not governed by disposition."""

    return TaiwanInstrumentTradingPolicy(
        market_semantics_usable=True,
        trading_mode=TaiwanInstrumentTradingMode.CONTINUOUS,
        analysis_basis=TaiwanAnalysisBasis.TIME_BARS,
        disposition_active=False,
        cache_status="not_applicable",
        reason_codes=(reason_code,),
    )


def resolve_taiwan_auction_applicability(
    *,
    session: MarketSession,
    disposition: Mapping[str, Any] | None,
) -> TaiwanAuctionApplicability:
    trading_policy = resolve_taiwan_instrument_trading_policy(disposition)
    if session is MarketSession.PRE_OPEN:
        return TaiwanAuctionApplicability(
            applicable=False,
            auction_type=None,
            trading_policy=trading_policy,
            reason_codes=("OPENING_AUCTION_NOT_STARTED",),
        )
    if session is MarketSession.OPENING_AUCTION:
        return TaiwanAuctionApplicability(
            applicable=True,
            auction_type=AuctionType.OPENING,
            trading_policy=trading_policy,
            reason_codes=("MARKET_OPENING_AUCTION",),
        )
    if session is MarketSession.CLOSING_AUCTION:
        return TaiwanAuctionApplicability(
            applicable=True,
            auction_type=AuctionType.CLOSING,
            trading_policy=trading_policy,
            reason_codes=("MARKET_CLOSING_AUCTION",),
        )
    if session is MarketSession.CONTINUOUS:
        if not trading_policy.market_semantics_usable:
            return TaiwanAuctionApplicability(
                applicable=None,
                auction_type=None,
                trading_policy=trading_policy,
                reason_codes=trading_policy.reason_codes,
            )
        if (
            trading_policy.trading_mode
            is TaiwanInstrumentTradingMode.DISPOSITION_BATCH_AUCTION
        ):
            return TaiwanAuctionApplicability(
                applicable=True,
                auction_type=AuctionType.INTRADAY,
                trading_policy=trading_policy,
                reason_codes=("DISPOSITION_INTRADAY_AUCTION",),
            )
        return TaiwanAuctionApplicability(
            applicable=False,
            auction_type=None,
            trading_policy=trading_policy,
            reason_codes=("CONTINUOUS_INSTRUMENT_NOT_AUCTION",),
        )
    if session is MarketSession.CLOSE_RESOLUTION:
        return TaiwanAuctionApplicability(
            applicable=False,
            auction_type=None,
            trading_policy=trading_policy,
            reason_codes=("MARKET_CLOSE_RESOLUTION_NOT_AUCTION",),
        )
    if session in {MarketSession.POST_CLOSE, MarketSession.CLOSED}:
        return TaiwanAuctionApplicability(
            applicable=False,
            auction_type=None,
            trading_policy=trading_policy,
            reason_codes=("MARKET_SESSION_NOT_AUCTION",),
        )
    return TaiwanAuctionApplicability(
        applicable=None,
        auction_type=None,
        trading_policy=trading_policy,
        reason_codes=("MARKET_SESSION_UNKNOWN",),
    )


__all__ = [
    "TAIWAN_TRADING_POLICY_VERSION",
    "TaiwanAnalysisBasis",
    "TaiwanAuctionApplicability",
    "TaiwanInstrumentTradingMode",
    "TaiwanInstrumentTradingPolicy",
    "continuous_taiwan_trading_policy",
    "is_taiwan_continuous_time_bar_start",
    "resolve_taiwan_auction_applicability",
    "resolve_taiwan_instrument_trading_policy",
]
