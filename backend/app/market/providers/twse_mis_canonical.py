"""Pure TWSE MIS message adapter for the canonical market-data boundary."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from app.market.twse_mis_observation import resolve_twse_mis_actual_trade
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
    Market,
    MarketSession,
    MarketSessionContext,
    ObservationState,
    Quantity,
    QuantityUnit,
    QuoteObservation,
    SourceLineage,
    TradeObservationState,
)


TAIWAN_TZ = ZoneInfo("Asia/Taipei")
MIS_PROVIDER = "twse_mis"
MIS_SOURCE = "twse_mis_quote_depth"
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


def _trade_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return None


def _event_at(message: dict[str, Any]) -> datetime | None:
    observed_date = _trade_date(message.get("d"))
    text = str(message.get("t") or message.get("%") or "").strip()
    if observed_date is None or not text:
        return None
    parts = text.split(":")
    if len(parts) != 3:
        return None
    try:
        return datetime.combine(
            observed_date,
            time(int(parts[0]), int(parts[1]), int(parts[2])),
            tzinfo=TAIWAN_TZ,
        )
    except ValueError:
        return None


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


def _split(value: Any) -> list[str]:
    return str(value).split("_") if value is not None else []


def _depth_levels(prices: Any, volumes: Any) -> tuple[DepthLevel, ...]:
    raw_prices = _split(prices)
    raw_volumes = _split(volumes)
    levels: list[DepthLevel] = []
    for index in range(5):
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


def canonical_snapshot_from_twse_mis(
    *,
    instrument: InstrumentKey,
    message: dict[str, Any],
    session: str | MarketSession,
    fetched_at: datetime,
    expected_trade_date: date | None = None,
    auction_type: AuctionType | None = None,
) -> CanonicalMarketSnapshot:
    """Normalize one already-acquired MIS message without I/O or persistence."""

    if instrument.market is not Market.TW:
        raise ValueError("TWSE MIS adapter requires a TW instrument")
    if str(message.get("c") or "").strip().upper() != instrument.symbol:
        raise ValueError("TWSE MIS message symbol does not match the instrument")
    if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
        raise ValueError("TWSE MIS fetched_at must be timezone-aware")

    observed_date = _trade_date(message.get("d"))
    event_at = _event_at(message)
    lineage = SourceLineage(
        provider=MIS_PROVIDER,
        source=MIS_SOURCE,
        authority=AuthorityClass.EXCHANGE,
        raw_contract_version="twse.mis.getStockInfo.v1",
        event_at=event_at,
        fetched_at=fetched_at,
    )
    session_value = _session(session)
    session_context = MarketSessionContext(
        market=Market.TW,
        session=session_value,
        observed_at=event_at or fetched_at.astimezone(TAIWAN_TZ),
        trade_date=observed_date,
    )
    trial = str(message.get("ts") or "").strip() not in {"", "0"}
    raw_last_price = _decimal(message.get("z"), positive=True)
    last_trade_volume = _decimal(message.get("tv"), positive=False)
    cumulative_volume = _decimal(message.get("v"), positive=False)
    actual_trade = resolve_twse_mis_actual_trade(
        expected_trade_date=expected_trade_date or observed_date,
        observation_trade_date=observed_date,
        provider_event_time=event_at,
        trial_status=message.get("ts"),
        last_trade_price=float(raw_last_price) if raw_last_price is not None else None,
        last_trade_volume_lots=(
            int(last_trade_volume) if last_trade_volume is not None else None
        ),
        cumulative_volume_lots=(
            int(cumulative_volume) if cumulative_volume is not None else None
        ),
    )
    actual_price = (
        raw_last_price if actual_trade["actual_trade_price_available"] else None
    )
    quote_observation = QuoteObservation(
        instrument=instrument,
        lineage=lineage,
        trade_date=observed_date,
        currency="TWD",
        state=(
            ObservationState.INDICATIVE
            if trial
            else ObservationState.AVAILABLE
            if actual_price is not None
            else ObservationState.PARTIAL
        ),
        trade_state=(
            TradeObservationState.INDICATIVE_OBSERVED
            if trial
            else TradeObservationState.TRADE_OBSERVED
            if actual_price is not None
            else TradeObservationState.AWAITING_FIRST_TRADE
        ),
        last_trade_price=actual_price,
        last_trade_quantity=(
            _lots_to_shares(message.get("tv")) if actual_price is not None else None
        ),
        cumulative_quantity=_lots_to_shares(message.get("v")),
        open_price=_decimal(message.get("o"), positive=True),
        high_price=_decimal(message.get("h"), positive=True),
        low_price=_decimal(message.get("l"), positive=True),
        previous_close=_decimal(message.get("y"), positive=True),
    )

    bids = _depth_levels(message.get("b"), message.get("g"))
    asks = _depth_levels(message.get("a"), message.get("f"))
    depth_observation = DepthObservation(
        instrument=instrument,
        lineage=lineage,
        capability=_depth_capability(bids, asks),
        bids=bids,
        asks=asks,
        state=ObservationState.INDICATIVE if trial else ObservationState.AVAILABLE,
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
    indicative_price = _decimal(message.get("pz"), positive=True)
    indicative_quantity = _lots_to_shares(message.get("ps"))
    if (
        trial
        and resolved_auction_type is not None
        and (indicative_price is not None or indicative_quantity is not None)
    ):
        auction = AuctionObservation(
            instrument=instrument,
            lineage=lineage,
            auction_type=resolved_auction_type,
            indicative_price=indicative_price,
            indicative_quantity=indicative_quantity,
            best_bid=bids[0] if bids else None,
            best_ask=asks[0] if asks else None,
        )

    return CanonicalMarketSnapshot(
        instrument=instrument,
        session=session_context,
        quote=quote_observation,
        depth=depth_observation,
        auction=auction,
    )


__all__ = ["canonical_snapshot_from_twse_mis"]
