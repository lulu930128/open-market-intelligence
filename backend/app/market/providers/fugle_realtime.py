"""Fugle stock WebSocket contracts, bounded state, and canonical conversion.

This module performs no network I/O and owns no database transaction.  The
runtime feeds messages into :class:`FugleRealtimeBuffer`; the runtime-owned
cadence materializer converts only the latest bounded records into canonical results.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from threading import Lock
from typing import Any, Iterable

from app.market.tw_current_market_capabilities import (
    FUGLE_CURRENT_INDEX_DESCRIPTOR,
    TW_CURRENT_INDEX_CAPABILITY_ID,
    TW_CURRENT_INDEX_MAX_ABS_CHANGE_RATIO,
)
from app.market.tw_intraday_capabilities import (
    FUGLE_INTRADAY_PARSER_VERSION,
    FUGLE_INTRADAY_PROVIDER,
    FUGLE_INTRADAY_RESOURCE_ID,
    FUGLE_INTRADAY_SOURCE,
)
from app.market.tw_realtime_capabilities import (
    FUGLE_PROVIDER,
    FUGLE_QUOTE_PARSER_VERSION,
    FUGLE_QUOTE_RESOURCE_ID,
    FUGLE_QUOTE_SOURCE,
)
from app.market_data.contracts import (
    AuthorityClass,
    BarFinalization,
    BarObservation,
    ConnectionStatus,
    EnablementStatus,
    EntitlementStatus,
    EvidenceFreshness,
    InstrumentKey,
    Market,
    MarketIndexObservation,
    MarketSession,
    ObservationState,
    OperationalStatus,
    ProviderResourceHealth,
    Quantity,
    QuantityUnit,
    QuoteObservation,
    SourceLineage,
    TradeObservationState,
)
from app.market_data.gateway import (
    BarAcquisitionResult,
    MarketIndexAcquisitionResult,
    QuoteAcquisitionResult,
)
from app.market_data.integration_contracts import (
    AcquisitionResourceAttempt,
    AcquisitionStatus,
    AcquisitionSummary,
    BarCapabilityRequest,
    DataRequirementV2,
    DatasetTarget,
    InstrumentTarget,
    RawFetchReceiptV1,
)


FUGLE_WEBSOCKET_URL = "wss://api.fugle.tw/marketdata/v1.0/stock/streaming"
FUGLE_TAIEX_SYMBOL = "IX0001"
FUGLE_INDEX_SOURCE = "fugle_indices_stream"
FUGLE_INDEX_PARSER_VERSION = "fugle.websocket.indices.v1"
FUGLE_MAX_SUBSCRIPTIONS = 5
FUGLE_INDEX_MAX_ABS_CHANGE_RATIO = TW_CURRENT_INDEX_MAX_ABS_CHANGE_RATIO
TAIPEI_TZ = timezone(timedelta(hours=8))


class FugleIndexValueAnomaly(ValueError):
    """Raised when an index tick is not plausible against its canonical seed."""


class FugleIndexSessionNotMaterializable(ValueError):
    """Raised when a live vendor tick cannot claim completed-session finality."""


@dataclass(frozen=True, order=True, slots=True)
class FugleSubscription:
    channel: str
    symbol: str

    def __post_init__(self) -> None:
        if self.channel not in {"indices", "aggregates", "candles"}:
            raise ValueError("unsupported Fugle subscription channel")
        normalized = str(self.symbol or "").strip().upper()
        if not normalized:
            raise ValueError("Fugle subscription symbol is required")
        object.__setattr__(self, "symbol", normalized)


@dataclass(frozen=True, slots=True)
class FugleSubscriptionCommands:
    unsubscribe_ids: tuple[str, ...]
    subscribe: tuple[FugleSubscription, ...]


class FugleSubscriptionAllocator:
    """Own one provider-wide subscription budget and one active stock."""

    def __init__(self, *, maximum: int = FUGLE_MAX_SUBSCRIPTIONS) -> None:
        if maximum < 3:
            raise ValueError("Fugle allocator requires at least three slots")
        self.maximum = maximum
        self._lock = Lock()
        self._active_stock: str | None = None
        self._server_ids: dict[FugleSubscription, str] = {}

    @property
    def active_stock(self) -> str | None:
        with self._lock:
            return self._active_stock

    def desired(self) -> tuple[FugleSubscription, ...]:
        with self._lock:
            desired = [FugleSubscription("indices", FUGLE_TAIEX_SYMBOL)]
            if self._active_stock:
                desired.extend(
                    (
                        FugleSubscription("aggregates", self._active_stock),
                        FugleSubscription("candles", self._active_stock),
                    )
                )
            if len(desired) > self.maximum:
                raise RuntimeError("Fugle desired subscriptions exceed hard limit")
            return tuple(desired)

    def set_active_stock(self, symbol: str | None) -> bool:
        normalized = str(symbol or "").strip().upper() or None
        if normalized is not None and not normalized.isdigit():
            raise ValueError("Fugle active stock must be a numeric Taiwan symbol")
        with self._lock:
            changed = self._active_stock != normalized
            self._active_stock = normalized
            return changed

    def acknowledge_subscribed(
        self,
        *,
        channel_id: str,
        channel: str,
        symbol: str,
    ) -> None:
        subscription = FugleSubscription(channel, symbol)
        normalized_id = str(channel_id or "").strip()
        if not normalized_id:
            raise ValueError("Fugle channel id is required")
        with self._lock:
            existing = next(
                (
                    item
                    for item, bound_id in self._server_ids.items()
                    if bound_id == normalized_id and item != subscription
                ),
                None,
            )
            if existing is not None:
                raise ValueError("Fugle channel id was reused across subscriptions")
            self._server_ids[subscription] = normalized_id
            if len(self._server_ids) > self.maximum:
                raise RuntimeError("Fugle server subscriptions exceed hard limit")

    def acknowledge_unsubscribed(self, channel_ids: Iterable[str]) -> None:
        removed = {str(item).strip() for item in channel_ids if str(item).strip()}
        with self._lock:
            self._server_ids = {
                subscription: channel_id
                for subscription, channel_id in self._server_ids.items()
                if channel_id not in removed
            }

    def is_bound(self, channel: str, symbol: str) -> bool:
        subscription = FugleSubscription(channel, symbol)
        with self._lock:
            return subscription in self._server_ids

    def commands(self) -> FugleSubscriptionCommands:
        desired = set(self.desired())
        with self._lock:
            obsolete = tuple(
                sorted(
                    channel_id
                    for subscription, channel_id in self._server_ids.items()
                    if subscription not in desired
                )
            )
            # Switching symbols is deliberately two-phase: unsubscribe first,
            # wait for acknowledgement, then consume the released slots.
            subscribe = () if obsolete else tuple(sorted(desired - self._server_ids.keys()))
            return FugleSubscriptionCommands(obsolete, subscribe)

    def reset_server_bindings(self) -> None:
        with self._lock:
            self._server_ids.clear()

    def snapshot(self) -> dict[str, object]:
        desired = self.desired()
        with self._lock:
            return {
                "maximum": self.maximum,
                "active_stock": self._active_stock,
                "desired_count": len(desired),
                "bound_count": len(self._server_ids),
                "desired": [
                    {"channel": item.channel, "symbol": item.symbol}
                    for item in desired
                ],
            }


@dataclass(frozen=True, slots=True)
class FugleStreamRecord:
    channel: str
    symbol: str
    payload: dict[str, Any]
    raw_text: str
    content_hash: str
    event_at: datetime
    received_at: datetime
    ordering_value: int


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Fugle received_at must be timezone-aware")
    return value


def _microsecond_time(value: object) -> datetime | None:
    if isinstance(value, bool):
        return None
    try:
        numeric = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    if numeric <= 0:
        return None
    try:
        return datetime.fromtimestamp(
            numeric / 1_000_000,
            tz=timezone.utc,
        ).astimezone(TAIPEI_TZ)
    except (OSError, OverflowError, ValueError):
        return None


def _iso_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _event_time(channel: str, data: dict[str, Any]) -> datetime | None:
    if channel == "indices":
        return _microsecond_time(data.get("time"))
    if channel == "aggregates":
        last_trade = data.get("lastTrade")
        last_trial = data.get("lastTrial")
        total = data.get("total")
        return (
            _microsecond_time(last_trade.get("time"))
            if isinstance(last_trade, dict)
            else None
        ) or (
            _microsecond_time(last_trial.get("time"))
            if isinstance(last_trial, dict)
            else None
        ) or (
            _microsecond_time(total.get("time")) if isinstance(total, dict) else None
        ) or _microsecond_time(data.get("lastUpdated"))
    return _iso_time(data.get("date")) if channel == "candles" else None


def _ordering_value(channel: str, data: dict[str, Any], event_at: datetime) -> int:
    candidates = (
        data.get("lastUpdated"),
        data.get("serial"),
        int(event_at.timestamp() * 1_000_000),
    )
    for candidate in candidates:
        try:
            value = int(candidate)  # type: ignore[arg-type]
        except (TypeError, ValueError, OverflowError):
            continue
        if value > 0:
            return value
    return int(event_at.timestamp() * 1_000_000)


class FugleRealtimeBuffer:
    """Keep at most one latest record per desired channel/symbol."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._latest: dict[tuple[str, str], FugleStreamRecord] = {}
        self.accepted_count = 0
        self.duplicate_count = 0
        self.out_of_order_count = 0
        self.malformed_count = 0

    def ingest(
        self,
        message: str | dict[str, Any],
        *,
        received_at: datetime,
    ) -> bool:
        received_at = _aware(received_at)
        try:
            envelope = json.loads(message) if isinstance(message, str) else message
            if not isinstance(envelope, dict) or envelope.get("event") != "data":
                return False
            channel = str(envelope.get("channel") or "").strip()
            data = envelope.get("data")
            if channel not in {"indices", "aggregates", "candles"} or not isinstance(data, dict):
                raise ValueError("unsupported Fugle data envelope")
            symbol = str(data.get("symbol") or "").strip().upper()
            event_at = _event_time(channel, data)
            if not symbol or event_at is None:
                raise ValueError("Fugle message lacks symbol/event time")
            raw_text = json.dumps(
                envelope,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            record = FugleStreamRecord(
                channel=channel,
                symbol=symbol,
                payload=dict(data),
                raw_text=raw_text,
                content_hash=sha256(raw_text.encode("utf-8")).hexdigest(),
                event_at=event_at,
                received_at=received_at,
                ordering_value=_ordering_value(channel, data, event_at),
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            with self._lock:
                self.malformed_count += 1
            return False
        key = (record.channel, record.symbol)
        with self._lock:
            current = self._latest.get(key)
            if current is not None and current.content_hash == record.content_hash:
                self.duplicate_count += 1
                return False
            if current is not None and record.ordering_value < current.ordering_value:
                self.out_of_order_count += 1
                return False
            self._latest[key] = record
            self.accepted_count += 1
            return True

    def latest(self, channel: str, symbol: str) -> FugleStreamRecord | None:
        with self._lock:
            return self._latest.get((channel, str(symbol).strip().upper()))

    def clear_symbol(self, symbol: str) -> None:
        normalized = str(symbol or "").strip().upper()
        with self._lock:
            self._latest = {
                key: value for key, value in self._latest.items() if key[1] != normalized
            }

    def metrics(self) -> dict[str, int]:
        with self._lock:
            return {
                "latest_count": len(self._latest),
                "accepted_count": self.accepted_count,
                "duplicate_count": self.duplicate_count,
                "out_of_order_count": self.out_of_order_count,
                "malformed_count": self.malformed_count,
            }


def _decimal(value: object, *, positive: bool = False) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite() or (positive and parsed <= 0):
        return None
    return parsed


def _lots(value: object) -> Quantity | None:
    lots = _decimal(value)
    if lots is None or lots < 0:
        return None
    shares = lots * Decimal(1000)
    if shares != shares.to_integral_value():
        return None
    return Quantity(
        value=shares,
        unit=QuantityUnit.SHARE,
        original_value=lots,
        original_unit=QuantityUnit.BOARD_LOT,
        scale=Decimal(1000),
    )


def _validate_stock_payload_identity(
    payload: dict[str, Any],
    instrument: InstrumentKey,
) -> None:
    expected_market = "TSE" if instrument.venue == "TWSE" else "OTC"
    exchange = str(payload.get("exchange") or "").strip().upper()
    market = str(payload.get("market") or "").strip().upper()
    if exchange != instrument.venue or market != expected_market:
        raise ValueError("Fugle stock payload crossed canonical venue identity")


def _lineage(record: FugleStreamRecord, *, source: str, parser: str) -> SourceLineage:
    return SourceLineage(
        provider=FUGLE_PROVIDER,
        source=source,
        authority=AuthorityClass.VENDOR,
        raw_contract_version=parser,
        event_at=record.event_at,
        received_at=record.received_at,
        fetched_at=record.received_at,
        content_hash=record.content_hash,
    )


def _receipt(
    record: FugleStreamRecord,
    *,
    source: str,
    resource_id: str,
    parser: str,
) -> RawFetchReceiptV1:
    return RawFetchReceiptV1(
        provider=FUGLE_PROVIDER,
        source=source,
        resource_id=resource_id,
        fetched_at=record.received_at,
        method="WEBSOCKET",
        url=FUGLE_WEBSOCKET_URL,
        status_code=101,
        content_type="application/json",
        content_hash=record.content_hash,
        raw_text=record.raw_text,
        parser_version=parser,
    )


def _health(
    requirement: DataRequirementV2,
    *,
    checked_at: datetime,
    resource_id: str,
) -> ProviderResourceHealth:
    return ProviderResourceHealth(
        provider=FUGLE_PROVIDER,
        market=Market.TW,
        capability=requirement.request.capability_id,
        resource_id=resource_id,
        enablement=EnablementStatus.ENABLED,
        connection=ConnectionStatus.CONNECTED,
        entitlement=EntitlementStatus.ENTITLED,
        operational=OperationalStatus.HEALTHY,
        freshness=EvidenceFreshness.LIVE,
        checked_at=checked_at,
        detail_code="FUGLE_STREAM_RECORD_AVAILABLE",
    )


def _summary(
    resource_id: str,
    *,
    limitations: tuple[str, ...] = (),
) -> AcquisitionSummary:
    return AcquisitionSummary(
        attempted=True,
        status=AcquisitionStatus.COMPLETED,
        providers_attempted=(FUGLE_PROVIDER,),
        resource_attempts=(
            AcquisitionResourceAttempt(
                provider=FUGLE_PROVIDER,
                resource_id=resource_id,
            ),
        ),
        external_calls=0,
        subscriptions_created=0,
        limitations=(
            "MATERIALIZED_FROM_EXISTING_SUBSCRIPTION",
            *limitations,
        ),
    )


def fugle_index_acquisition(
    record: FugleStreamRecord,
    requirement: DataRequirementV2,
    *,
    previous_close: Decimal,
) -> MarketIndexAcquisitionResult:
    if not isinstance(requirement.target, DatasetTarget):
        raise ValueError("Fugle index materialization requires dataset target")
    if requirement.request.capability_id != TW_CURRENT_INDEX_CAPABILITY_ID:
        raise ValueError("Fugle index capability mismatch")
    if requirement.target.scope_key != "TAIEX" or record.symbol != FUGLE_TAIEX_SYMBOL:
        raise ValueError("Fugle index materialization is bounded to TAIEX/IX0001")
    if requirement.session in {MarketSession.POST_CLOSE, MarketSession.CLOSED}:
        raise FugleIndexSessionNotMaterializable(
            "Fugle live index cannot materialize completed-session evidence"
        )
    value = _decimal(record.payload.get("index"), positive=True)
    if value is None or previous_close <= 0:
        raise ValueError("Fugle index requires current value and seeded previous close")
    if abs(value - previous_close) / previous_close > FUGLE_INDEX_MAX_ABS_CHANGE_RATIO:
        raise FugleIndexValueAnomaly(
            "Fugle index value exceeds the bounded previous-close deviation"
        )
    observation = MarketIndexObservation(
        market=Market.TW,
        index_id="TAIEX",
        venue="TWSE",
        lineage=_lineage(
            record,
            source=FUGLE_INDEX_SOURCE,
            parser=FUGLE_INDEX_PARSER_VERSION,
        ),
        session=requirement.session,
        trade_date=record.event_at.astimezone(TAIPEI_TZ).date(),
        close_value=value,
        price_change=value - previous_close,
        trade_volume=None,
        trade_value=None,
        currency=None,
        transaction_count=None,
        state=ObservationState.PARTIAL,
        value_semantics="current_index_snapshot",
        finalization=BarFinalization.PROVISIONAL,
        official=False,
        provisional=True,
    )
    receipt = _receipt(
        record,
        source=FUGLE_INDEX_SOURCE,
        resource_id=FUGLE_CURRENT_INDEX_DESCRIPTOR.resource_id,
        parser=FUGLE_INDEX_PARSER_VERSION,
    )
    return MarketIndexAcquisitionResult(
        summary=_summary(
            FUGLE_CURRENT_INDEX_DESCRIPTOR.resource_id,
            limitations=("FUGLE_INDEX_AUXILIARY_METRICS_UNAVAILABLE",),
        ),
        observations=(observation,),
        receipts=(receipt,),
        provider_health=(
            _health(
                requirement,
                checked_at=record.received_at,
                resource_id=FUGLE_CURRENT_INDEX_DESCRIPTOR.resource_id,
            ),
        ),
    )


def fugle_quote_acquisition(
    record: FugleStreamRecord,
    requirement: DataRequirementV2,
) -> QuoteAcquisitionResult:
    if not isinstance(requirement.target, InstrumentTarget):
        raise ValueError("Fugle quote materialization requires instrument target")
    instrument = requirement.target.instrument
    if instrument.venue not in {"TWSE", "TPEX"} or instrument.symbol != record.symbol:
        raise ValueError("Fugle quote crossed active Taiwan instrument")
    data = record.payload
    _validate_stock_payload_identity(data, instrument)
    last_trade = data.get("lastTrade") if isinstance(data.get("lastTrade"), dict) else None
    total = data.get("total") if isinstance(data.get("total"), dict) else {}
    last_price = _decimal(last_trade.get("price"), positive=True) if last_trade else None
    is_trial = data.get("isTrial") is True
    trade_state = (
        TradeObservationState.TRADE_OBSERVED
        if last_price is not None
        else TradeObservationState.INDICATIVE_OBSERVED
        if is_trial
        else TradeObservationState.AWAITING_FIRST_TRADE
    )
    observation = QuoteObservation(
        instrument=instrument,
        lineage=_lineage(
            record,
            source=FUGLE_QUOTE_SOURCE,
            parser=FUGLE_QUOTE_PARSER_VERSION,
        ),
        trade_date=(
            date.fromisoformat(str(data.get("date")))
            if isinstance(data.get("date"), str)
            else record.event_at.astimezone(TAIPEI_TZ).date()
        ),
        currency="TWD",
        state=(
            ObservationState.INDICATIVE
            if is_trial
            else ObservationState.AVAILABLE
            if last_price is not None
            else ObservationState.PARTIAL
        ),
        trade_state=trade_state,
        last_trade_price=last_price,
        last_trade_quantity=_lots(last_trade.get("size")) if last_trade else None,
        cumulative_quantity=_lots(total.get("tradeVolume")),
        open_price=_decimal(data.get("openPrice"), positive=True),
        high_price=_decimal(data.get("highPrice"), positive=True),
        low_price=_decimal(data.get("lowPrice"), positive=True),
        previous_close=_decimal(data.get("previousClose"), positive=True),
    )
    receipt = _receipt(
        record,
        source=FUGLE_QUOTE_SOURCE,
        resource_id=FUGLE_QUOTE_RESOURCE_ID,
        parser=FUGLE_QUOTE_PARSER_VERSION,
    )
    return QuoteAcquisitionResult(
        summary=_summary(FUGLE_QUOTE_RESOURCE_ID),
        observations=(observation,),
        receipts=(receipt,),
        provider_health=(
            _health(
                requirement,
                checked_at=record.received_at,
                resource_id=FUGLE_QUOTE_RESOURCE_ID,
            ),
        ),
    )


def fugle_bar_acquisition(
    record: FugleStreamRecord,
    requirement: DataRequirementV2,
) -> BarAcquisitionResult:
    if not isinstance(requirement.target, InstrumentTarget) or not isinstance(
        requirement.request,
        BarCapabilityRequest,
    ):
        raise ValueError("Fugle bar materialization requires instrument bar target")
    instrument = requirement.target.instrument
    if instrument.venue not in {"TWSE", "TPEX"} or instrument.symbol != record.symbol:
        raise ValueError("Fugle bar crossed active Taiwan instrument")
    if requirement.request.interval != "1m":
        raise ValueError("Fugle stream materializer supports 1m only")
    data = record.payload
    _validate_stock_payload_identity(data, instrument)
    prices = {
        key: _decimal(data.get(key), positive=True)
        for key in ("open", "high", "low", "close")
    }
    if any(value is None for value in prices.values()):
        raise ValueError("Fugle candle lacks valid OHLC")
    start_at = record.event_at
    volume = _lots(data.get("volume"))
    observation = BarObservation(
        instrument=instrument,
        lineage=_lineage(
            record,
            source=FUGLE_INTRADAY_SOURCE,
            parser=FUGLE_INTRADAY_PARSER_VERSION,
        ),
        interval="1m",
        start_at=start_at,
        end_at=start_at + timedelta(minutes=1),
        open_price=prices["open"],  # type: ignore[arg-type]
        high_price=prices["high"],  # type: ignore[arg-type]
        low_price=prices["low"],  # type: ignore[arg-type]
        close_price=prices["close"],  # type: ignore[arg-type]
        volume=volume,
        volume_status="observed" if volume is not None else "missing",
        price_basis="raw",
        turnover_value=None,
        turnover_currency=None,
        finalization=BarFinalization.PROVISIONAL,
    )
    receipt = _receipt(
        record,
        source=FUGLE_INTRADAY_SOURCE,
        resource_id=FUGLE_INTRADAY_RESOURCE_ID,
        parser=FUGLE_INTRADAY_PARSER_VERSION,
    )
    return BarAcquisitionResult(
        summary=_summary(FUGLE_INTRADAY_RESOURCE_ID),
        observations=(observation,),
        receipts=(receipt,),
        provider_health=(
            _health(
                requirement,
                checked_at=record.received_at,
                resource_id=FUGLE_INTRADAY_RESOURCE_ID,
            ),
        ),
    )


__all__ = [
    "FUGLE_INDEX_PARSER_VERSION",
    "FUGLE_INDEX_MAX_ABS_CHANGE_RATIO",
    "FUGLE_INDEX_SOURCE",
    "FUGLE_MAX_SUBSCRIPTIONS",
    "FUGLE_TAIEX_SYMBOL",
    "FUGLE_WEBSOCKET_URL",
    "FugleRealtimeBuffer",
    "FugleIndexSessionNotMaterializable",
    "FugleIndexValueAnomaly",
    "FugleStreamRecord",
    "FugleSubscription",
    "FugleSubscriptionAllocator",
    "FugleSubscriptionCommands",
    "fugle_bar_acquisition",
    "fugle_index_acquisition",
    "fugle_quote_acquisition",
]
