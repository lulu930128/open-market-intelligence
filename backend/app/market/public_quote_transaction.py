"""Atomic raw receipt and canonical quote persistence for public TW quotes."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json

from sqlalchemy.orm import Session

from app.db.models import (
    DataQualityCheck,
    RawFetchResult,
    SourceRegistry,
    StockMaster,
    TaiwanStockQuoteSnapshot,
)
from app.market.tw_public_quote_contract import (
    TW_PUBLIC_LAST_TRADE_CAPABILITY_ID,
    exchange_channel_for_quote,
)
from app.market.tw_realtime_capabilities import realtime_source_binding
from app.market_data.contracts import (
    Market,
    MarketSession,
    Quantity,
    QuantityUnit,
    QuoteObservation,
)
from app.market_data.gateway import QuoteAcquisitionResult
from app.market_data.integration_contracts import (
    DataRequirementV2,
    InstrumentTarget,
    PersistenceSummary,
    RawFetchReceiptV1,
    SnapshotCapabilityRequest,
)


_LEGACY_SESSION_PHASE = {
    MarketSession.PRE_OPEN: "preopen_auction",
    MarketSession.OPENING_AUCTION: "preopen_auction",
    MarketSession.CONTINUOUS: "regular_live",
    MarketSession.CLOSING_AUCTION: "closing_auction",
    MarketSession.POST_CLOSE: "post_close_snapshot",
    MarketSession.CLOSED: "market_closed",
    MarketSession.UNKNOWN: "unknown",
}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("quote transaction timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _lots(quantity: Quantity | None) -> int | None:
    if quantity is None:
        return None
    value: Decimal
    if quantity.original_unit is QuantityUnit.BOARD_LOT:
        assert quantity.original_value is not None
        value = quantity.original_value
    elif quantity.unit is QuantityUnit.SHARE:
        value = quantity.value / Decimal(1000)
    else:
        raise ValueError("Taiwan quote quantity must use shares or board lots")
    if value != value.to_integral_value():
        raise ValueError("Taiwan quote board-lot quantity must be an integer")
    return int(value)


def _pct(change: float | None, previous_close: float | None) -> float | None:
    if change is None or previous_close in {None, 0}:
        return None
    assert previous_close is not None
    return (change / previous_close) * 100


def _source_defaults(receipt: RawFetchReceiptV1) -> dict[str, object]:
    binding = realtime_source_binding(
        provider=receipt.provider,
        source=receipt.source,
        resource_id=receipt.resource_id,
    )
    if (
        binding is None
        or binding.descriptor.capability_id
        != TW_PUBLIC_LAST_TRADE_CAPABILITY_ID
    ):
        raise ValueError(
            "unsupported Taiwan public quote provider/source/resource"
        )
    if receipt.parser_version != binding.parser_version:
        raise ValueError("public quote receipt parser contract mismatch")
    return {
        "source_name": receipt.source,
        "source_type": binding.source_type,
        "category": "market_data",
        "endpoint_url": receipt.url,
        "enabled": True,
        "priority": binding.descriptor.priority,
        "parser_type": receipt.parser_version,
        "auth_type": binding.auth_type,
        "reliability_level": binding.reliability_level,
    }


class TaiwanPublicQuoteTransaction:
    def __init__(self, db: Session) -> None:
        self._db = db

    def _source(self, receipt: RawFetchReceiptV1) -> SourceRegistry:
        defaults = _source_defaults(receipt)
        source = (
            self._db.query(SourceRegistry)
            .filter(SourceRegistry.source_name == receipt.source)
            .first()
        )
        if source is None:
            source = SourceRegistry(**defaults)
            self._db.add(source)
            self._db.flush()
        return source

    def _raw_receipt(
        self,
        source: SourceRegistry,
        receipt: RawFetchReceiptV1,
    ) -> RawFetchResult:
        fetched_at = _as_utc(receipt.fetched_at)
        raw = RawFetchResult(
            source_id=source.id,
            fetched_at=fetched_at,
            url=receipt.url,
            method=receipt.method,
            status_code=receipt.status_code,
            content_type=receipt.content_type,
            content_hash=receipt.content_hash,
            raw_text=receipt.raw_text,
            parser_version=receipt.parser_version,
            error_message=receipt.error_message,
        )
        self._db.add(raw)
        self._db.flush()
        if receipt.error_message is None:
            source.last_success_at = fetched_at
            source.last_error_at = None
            source.last_error_message = None
        else:
            source.last_error_at = fetched_at
            source.last_error_message = receipt.error_message
        return raw

    def _upsert(
        self,
        observation: QuoteObservation,
        *,
        session: MarketSession,
        source: SourceRegistry,
        raw: RawFetchResult,
        receipt: RawFetchReceiptV1,
    ) -> bool:
        if observation.instrument.market is not Market.TW:
            raise ValueError("Taiwan public quote transaction requires market=TW")
        if observation.lineage.event_at is None or observation.trade_date is None:
            raise ValueError("Taiwan public quote requires event time and trade date")
        if observation.lineage.provider != receipt.provider:
            raise ValueError("quote observation provider does not match receipt")
        if observation.lineage.source != receipt.source:
            raise ValueError("quote observation source does not match receipt")
        if observation.lineage.raw_contract_version != receipt.parser_version:
            raise ValueError("quote observation parser contract does not match receipt")
        if observation.lineage.content_hash != receipt.content_hash:
            raise ValueError("quote observation content hash does not match receipt")
        received_at = observation.lineage.received_at or receipt.fetched_at
        if received_at.tzinfo is None or received_at.utcoffset() is None:
            raise ValueError("quote received_at must be timezone-aware")
        stock = (
            self._db.query(StockMaster)
            .filter(StockMaster.stock_id == observation.instrument.symbol)
            .first()
        )
        if stock is None:
            raise ValueError("quote target is missing from StockMaster")
        last_price = (
            float(observation.last_trade_price)
            if observation.last_trade_price is not None
            else None
        )
        previous_close = (
            float(observation.previous_close)
            if observation.previous_close is not None
            else None
        )
        change = (
            last_price - previous_close
            if last_price is not None and previous_close is not None
            else None
        )
        incoming = {
            "source_id": source.id,
            "raw_result_id": raw.id,
            "market": observation.instrument.venue,
            "stock_name": stock.stock_name,
            "exchange_channel": exchange_channel_for_quote(observation.instrument),
            "session_phase": _LEGACY_SESSION_PHASE[session],
            "trade_date": observation.trade_date,
            "open_price": (
                float(observation.open_price)
                if observation.open_price is not None
                else None
            ),
            "high_price": (
                float(observation.high_price)
                if observation.high_price is not None
                else None
            ),
            "low_price": (
                float(observation.low_price)
                if observation.low_price is not None
                else None
            ),
            "last_price": last_price,
            "previous_close": previous_close,
            "change": change,
            "change_pct": _pct(change, previous_close),
            "total_volume_lots": _lots(observation.cumulative_quantity),
            "last_trade_volume_lots": _lots(observation.last_trade_quantity),
            "source": observation.lineage.source,
            "source_url": receipt.url,
            "raw_payload_json": receipt.raw_text,
            "received_at": _as_utc(received_at),
            "observation_state": observation.state.value,
            "market_session": session.value,
            "trade_state": observation.trade_state.value,
            "raw_contract_version": observation.lineage.raw_contract_version,
            "fetched_at": _as_utc(receipt.fetched_at),
        }
        row = (
            self._db.query(TaiwanStockQuoteSnapshot)
            .filter(TaiwanStockQuoteSnapshot.provider == receipt.provider)
            .filter(
                TaiwanStockQuoteSnapshot.stock_id
                == observation.instrument.symbol
            )
            .filter(
                TaiwanStockQuoteSnapshot.quote_time
                == observation.lineage.event_at
            )
            .first()
        )
        comparable = {
            key: value
            for key, value in incoming.items()
            if key
            not in {
                "source_id",
                "raw_result_id",
                "received_at",
                "fetched_at",
            }
        }
        if row is None:
            row = TaiwanStockQuoteSnapshot(
                provider=receipt.provider,
                stock_id=observation.instrument.symbol,
                quote_time=observation.lineage.event_at,
                **incoming,
            )
            self._db.add(row)
            return False
        unchanged = all(getattr(row, key) == value for key, value in comparable.items())
        for key, value in incoming.items():
            setattr(row, key, value)
        return unchanged

    def _quality_check(
        self,
        *,
        source: SourceRegistry,
        raw: RawFetchResult,
        receipt: RawFetchReceiptV1,
        observation_count: int,
        actual_trade_count: int,
        limitations: tuple[str, ...],
    ) -> None:
        if receipt.error_message:
            status = "error"
            message = receipt.error_message
        elif observation_count == 0:
            status = "warning"
            message = "Public quote receipt has no accepted observation."
        elif actual_trade_count == 0:
            status = "warning"
            message = "Public quote observation has no verified actual trade."
        elif limitations:
            status = "warning"
            message = "Public quote receipt has explicit limitations."
        else:
            status = "valid"
            message = "Public quote receipt and actual-trade observation are valid."
        self._db.add(
            DataQualityCheck(
                source_id=source.id,
                raw_result_id=raw.id,
                status=status,
                check_name="data_core_public_last_trade_quote_receipt",
                message=message,
                row_count=observation_count,
                is_duplicate=False,
                detail_json=json.dumps(
                    {
                        "provider": receipt.provider,
                        "resource_id": receipt.resource_id,
                        "parser_version": receipt.parser_version,
                        "actual_trade_count": actual_trade_count,
                        "limitations": list(limitations),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            )
        )

    def persist_quote_acquisition(
        self,
        requirement: DataRequirementV2,
        acquisition: QuoteAcquisitionResult,
    ) -> PersistenceSummary:
        if not isinstance(requirement.target, InstrumentTarget):
            raise ValueError("public quote transaction requires instrument target")
        if not isinstance(requirement.request, SnapshotCapabilityRequest):
            raise ValueError("public quote transaction requires snapshot request")
        if requirement.request.capability_id != TW_PUBLIC_LAST_TRADE_CAPABILITY_ID:
            raise ValueError("public quote transaction capability mismatch")
        if not acquisition.summary.attempted:
            raise ValueError("transaction cannot persist non-attempted acquisition")
        receipts: dict[
            tuple[str, str],
            tuple[SourceRegistry, RawFetchResult, RawFetchReceiptV1],
        ] = {}
        raw_ids: list[int] = []
        observation_counts: dict[tuple[str, str], int] = {}
        actual_trade_counts: dict[tuple[str, str], int] = {}
        written = unchanged = 0
        try:
            for receipt in acquisition.receipts:
                key = (receipt.provider, receipt.source)
                if key in receipts:
                    raise ValueError("duplicate public quote provider/source receipt")
                source = self._source(receipt)
                raw = self._raw_receipt(source, receipt)
                receipts[key] = (source, raw, receipt)
                raw_ids.append(raw.id)
            for observation in acquisition.observations:
                if observation.instrument != requirement.target.instrument:
                    raise ValueError("quote observation crossed requested instrument")
                key = (
                    observation.lineage.provider,
                    observation.lineage.source,
                )
                matched = receipts.get(key)
                if matched is None:
                    raise ValueError("quote observation has no matching raw receipt")
                source, raw, receipt = matched
                was_unchanged = self._upsert(
                    observation,
                    session=requirement.session,
                    source=source,
                    raw=raw,
                    receipt=receipt,
                )
                observation_counts[key] = observation_counts.get(key, 0) + 1
                if observation.last_trade_price is not None:
                    actual_trade_counts[key] = actual_trade_counts.get(key, 0) + 1
                if was_unchanged:
                    unchanged += 1
                else:
                    written += 1
            for key, (source, raw, receipt) in receipts.items():
                self._quality_check(
                    source=source,
                    raw=raw,
                    receipt=receipt,
                    observation_count=observation_counts.get(key, 0),
                    actual_trade_count=actual_trade_counts.get(key, 0),
                    limitations=acquisition.summary.limitations,
                )
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise
        return PersistenceSummary(
            attempted=True,
            committed=True,
            receipts_written=len(acquisition.receipts),
            observations_written=written,
            observations_unchanged=unchanged,
            raw_result_ids=tuple(raw_ids),
            limitations=acquisition.summary.limitations,
        )


__all__ = ["TaiwanPublicQuoteTransaction"]
