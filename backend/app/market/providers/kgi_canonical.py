"""Pure KGI SuperPy quote adapter for the canonical market-data boundary."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from app.market_data.contracts import (
    AuctionObservation,
    AuctionType,
    AuthorityClass,
    CanonicalMarketSnapshot,
    DepthCapability,
    DepthLevel,
    DepthObservation,
    DepthPriceState,
    InstrumentKey,
    InstrumentTradability,
    Market,
    MarketSession,
    MarketSessionContext,
    ObservationState,
    Quantity,
    QuantityUnit,
    QuoteObservation,
    SourceLineage,
    TradingStatusObservation,
    TradeObservationState,
)


TAIWAN_TZ = ZoneInfo("Asia/Taipei")
KGI_PROVIDER = "kgi_superpy"
KGI_SOURCE = "kgi_superpy_quote_all"
KGI_RAW_CONTRACT_VERSION = "kgi.superpy.quote_all.v1"
BOARD_LOT_SHARES = Decimal("1000")


def _decimal(value: Any, *, positive: bool) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text or text in {"-", "--"}:
        return None
    try:
        parsed = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite():
        return None
    if positive and parsed <= 0:
        return None
    if not positive and parsed < 0:
        return None
    return parsed


def _signed_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _lots_to_shares(value: Any) -> Quantity | None:
    lots = _decimal(value, positive=False)
    if lots is None:
        return None
    return Quantity(
        value=lots * BOARD_LOT_SHARES,
        unit=QuantityUnit.SHARE,
        original_value=lots,
        original_unit=QuantityUnit.BOARD_LOT,
        scale=BOARD_LOT_SHARES,
    )


def _parse_event_at(value: Any) -> datetime:
    text = str(value or "").strip()
    if len(text) != 14 or not text.isdigit():
        raise ValueError("KGI SuperPy quote datetime must use YYYYMMDDHHMMSS")
    return datetime.strptime(text, "%Y%m%d%H%M%S").replace(tzinfo=TAIWAN_TZ)


def _parse_received_at(value: Any, fallback: datetime | None) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00")) if text else None
        except ValueError as exc:
            raise ValueError("KGI received_at must be an ISO-8601 datetime") from exc
    if parsed is None:
        parsed = fallback
    if parsed is None or parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("KGI canonical adapter requires timezone-aware received_at")
    return parsed


def _session(value: str | MarketSession) -> MarketSession:
    if isinstance(value, MarketSession):
        return value
    normalized = str(value or "").strip().lower()
    if normalized in {"preopen", "preopen_pending", "closed_waiting_preopen"}:
        return MarketSession.PRE_OPEN
    if normalized in {"preopen_auction", "opening_auction", "opening_auction_delayed"}:
        return MarketSession.OPENING_AUCTION
    if normalized in {"regular", "regular_live", "continuous"}:
        return MarketSession.CONTINUOUS
    if normalized in {"closing_auction", "closing_auction_delayed"}:
        return MarketSession.CLOSING_AUCTION
    if normalized in {"post_close", "post_close_snapshot"}:
        return MarketSession.POST_CLOSE
    if normalized in {"closed", "market_closed"}:
        return MarketSession.CLOSED
    return MarketSession.UNKNOWN


def kgi_quote_has_actual_trade_evidence(
    quote: dict[str, Any],
    *,
    session: str | MarketSession | None = None,
) -> bool:
    """Return whether one KGI quote has sufficient evidence of an actual trade."""

    session_value = _session(session) if session is not None else MarketSession.UNKNOWN
    if session_value in {
        MarketSession.PRE_OPEN,
        MarketSession.OPENING_AUCTION,
        MarketSession.CLOSING_AUCTION,
        MarketSession.CLOSED,
    }:
        return False
    if _decimal(quote.get("simtrade"), positive=False) == Decimal("1"):
        return False
    return (
        _decimal(quote.get("close"), positive=True) is not None
        and _decimal(quote.get("volume"), positive=True) is not None
        and _decimal(quote.get("total_volume"), positive=True) is not None
    )


def kgi_quote_is_indicative(
    quote: dict[str, Any],
    *,
    session: str | MarketSession | None = None,
) -> bool:
    """Identify trial/auction evidence without manufacturing an actual trade."""

    if _decimal(quote.get("simtrade"), positive=False) == Decimal("1"):
        return True
    close = _decimal(quote.get("close"), positive=True)
    volume = _decimal(quote.get("volume"), positive=True)
    if close is None or volume is None:
        return False
    session_value = _session(session) if session is not None else MarketSession.UNKNOWN
    if session_value in {
        MarketSession.PRE_OPEN,
        MarketSession.OPENING_AUCTION,
        MarketSession.CLOSING_AUCTION,
    }:
        return True
    cumulative = _decimal(quote.get("total_volume"), positive=False)
    return cumulative == Decimal("0")


def _depth_levels(prices: Any, volumes: Any) -> tuple[DepthLevel, ...]:
    raw_prices = list(prices)[:5] if isinstance(prices, (list, tuple)) else []
    raw_volumes = list(volumes)[:5] if isinstance(volumes, (list, tuple)) else []
    levels: list[DepthLevel] = []
    for index in range(max(len(raw_prices), len(raw_volumes))):
        raw_price = raw_prices[index] if index < len(raw_prices) else None
        raw_volume = raw_volumes[index] if index < len(raw_volumes) else None
        price = _decimal(raw_price, positive=True)
        quantity = _lots_to_shares(raw_volume)
        if price is None and quantity is None:
            continue
        levels.append(
            DepthLevel(
                level=index + 1,
                price=price,
                quantity=quantity,
                price_state=(
                    DepthPriceState.LIMIT_PRICE
                    if price is not None
                    else DepthPriceState.NON_PRICE
                ),
            )
        )
    return tuple(levels)


def _depth_capability(
    bids: tuple[DepthLevel, ...], asks: tuple[DepthLevel, ...]
) -> DepthCapability:
    level_count = max(len(bids), len(asks))
    if level_count == 0:
        return DepthCapability.NONE
    if level_count == 1:
        return DepthCapability.LEVEL_1
    return DepthCapability.LEVEL_5


def canonical_snapshot_from_kgi(
    *,
    instrument: InstrumentKey,
    quote: dict[str, Any],
    session: str | MarketSession,
    received_at: datetime | None = None,
    auction_type: AuctionType | None = None,
) -> CanonicalMarketSnapshot:
    """Normalize one already-acquired KGI quote without I/O or persistence."""

    if instrument.market is not Market.TW:
        raise ValueError("KGI Taiwan quote adapter requires a TW instrument")
    if str(quote.get("symbol") or "").strip().upper() != instrument.symbol:
        raise ValueError("KGI SuperPy quote symbol does not match the instrument")
    odd_lot = str(quote.get("odd_lot") or "").strip().lower()
    if odd_lot in {"1", "true", "yes", "on"}:
        raise ValueError("KGI odd-lot quotes are outside the v1 canonical contract")

    event_at = _parse_event_at(quote.get("datetime"))
    normalized_received_at = _parse_received_at(quote.get("received_at"), received_at)
    lineage = SourceLineage(
        provider=KGI_PROVIDER,
        source=KGI_SOURCE,
        authority=AuthorityClass.BROKER,
        raw_contract_version=KGI_RAW_CONTRACT_VERSION,
        event_at=event_at,
        received_at=normalized_received_at,
    )
    session_value = _session(session)
    session_context = MarketSessionContext(
        market=Market.TW,
        session=session_value,
        observed_at=event_at,
        trade_date=event_at.date(),
    )

    actual_trade = kgi_quote_has_actual_trade_evidence(quote, session=session_value)
    indicative = kgi_quote_is_indicative(quote, session=session_value)
    close = _decimal(quote.get("close"), positive=True)
    price_change = _signed_decimal(quote.get("price_chg"))
    previous_close = (
        close - price_change
        if close is not None and price_change is not None and close - price_change > 0
        else None
    )
    quote_observation = QuoteObservation(
        instrument=instrument,
        lineage=lineage,
        trade_date=event_at.date(),
        currency="TWD",
        state=(
            ObservationState.INDICATIVE
            if indicative
            else ObservationState.AVAILABLE
            if actual_trade
            else ObservationState.PARTIAL
        ),
        trade_state=(
            TradeObservationState.INDICATIVE_OBSERVED
            if indicative
            else TradeObservationState.TRADE_OBSERVED
            if actual_trade
            else TradeObservationState.AWAITING_FIRST_TRADE
        ),
        last_trade_price=close if actual_trade else None,
        last_trade_quantity=(
            _lots_to_shares(quote.get("volume")) if actual_trade else None
        ),
        cumulative_quantity=_lots_to_shares(quote.get("total_volume")),
        open_price=_decimal(quote.get("open"), positive=True),
        high_price=_decimal(quote.get("high"), positive=True),
        low_price=_decimal(quote.get("low"), positive=True),
        previous_close=previous_close,
    )

    bids = _depth_levels(quote.get("bid_prices"), quote.get("bid_volumes"))
    asks = _depth_levels(quote.get("ask_prices"), quote.get("ask_volumes"))
    depth_observation = DepthObservation(
        instrument=instrument,
        lineage=lineage,
        capability=_depth_capability(bids, asks),
        bids=bids,
        asks=asks,
        state=(
            ObservationState.INDICATIVE
            if indicative
            else ObservationState.AVAILABLE
        ),
    )

    resolved_auction_type = auction_type
    if resolved_auction_type is None:
        if session_value is MarketSession.CLOSING_AUCTION:
            resolved_auction_type = AuctionType.CLOSING
        elif session_value in {
            MarketSession.PRE_OPEN,
            MarketSession.OPENING_AUCTION,
        }:
            resolved_auction_type = AuctionType.OPENING
    auction = None
    if indicative and resolved_auction_type is not None:
        auction = AuctionObservation(
            instrument=instrument,
            lineage=lineage,
            auction_type=resolved_auction_type,
            indicative_price=close,
            indicative_quantity=_lots_to_shares(quote.get("volume")),
            best_bid=bids[0] if bids else None,
            best_ask=asks[0] if asks else None,
        )

    trading_status = None
    if "suspend" in quote:
        is_suspended = str(quote.get("suspend") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        trading_status = TradingStatusObservation(
            instrument=instrument,
            lineage=lineage,
            status=(
                InstrumentTradability.SUSPENDED
                if is_suspended
                else InstrumentTradability.UNKNOWN
            ),
            reason=(
                "broker_suspend_hint"
                if is_suspended
                else "broker_suspend_flag_clear_not_official"
            ),
            effective_at=event_at,
            official=False,
        )

    return CanonicalMarketSnapshot(
        instrument=instrument,
        session=session_context,
        quote=quote_observation,
        depth=depth_observation,
        auction=auction,
        trading_status=trading_status,
    )


__all__ = [
    "KGI_PROVIDER",
    "KGI_RAW_CONTRACT_VERSION",
    "KGI_SOURCE",
    "canonical_snapshot_from_kgi",
    "kgi_quote_has_actual_trade_evidence",
    "kgi_quote_is_indicative",
]
