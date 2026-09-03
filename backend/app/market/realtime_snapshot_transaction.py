"""Atomic persistence owners for typed Taiwan depth and auction observations."""

from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.db.models import (
    RawFetchResult,
    SourceRegistry,
    StockMaster,
    TaiwanStockAuctionSnapshot,
    TaiwanStockDepthLevel,
    TaiwanStockDepthSnapshot,
)
from app.market.tw_realtime_capabilities import (
    TW_AUCTION_CAPABILITY_ID,
    TW_ORDER_BOOK_CAPABILITY_ID,
    realtime_source_binding,
)
from app.market.trading_calendar import TAIWAN_TZ, taiwan_evidence_session
from app.market_data.contracts import (
    AuctionObservation,
    DepthLevel,
    DepthObservation,
    Market,
    Quantity,
)
from app.market_data.gateway import (
    AuctionAcquisitionResult,
    DepthAcquisitionResult,
)
from app.market_data.integration_contracts import (
    DataRequirementV2,
    InstrumentTarget,
    PersistenceSummary,
    RawFetchReceiptV1,
    SnapshotCapabilityRequest,
)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("realtime transaction timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _quantity_values(quantity: Quantity | None) -> dict[str, object | None]:
    if quantity is None:
        return {
            "value": None,
            "unit": None,
            "original_value": None,
            "original_unit": None,
            "scale": None,
        }
    return {
        "value": quantity.value,
        "unit": quantity.unit.value,
        "original_value": quantity.original_value,
        "original_unit": (
            quantity.original_unit.value
            if quantity.original_unit is not None
            else None
        ),
        "scale": quantity.scale,
    }


def _source_defaults(
    receipt: RawFetchReceiptV1,
    *,
    capability_id: str,
) -> dict[str, object]:
    binding = realtime_source_binding(
        provider=receipt.provider,
        source=receipt.source,
        resource_id=receipt.resource_id,
    )
    if binding is None or binding.descriptor.capability_id != capability_id:
        raise ValueError("unsupported Taiwan realtime provider/source/resource")
    if receipt.parser_version != binding.parser_version:
        raise ValueError("Taiwan realtime receipt parser contract mismatch")
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


class _RealtimeTransactionOwner:
    def __init__(self, db: Session) -> None:
        self._db = db

    def _source(
        self,
        receipt: RawFetchReceiptV1,
        *,
        capability_id: str,
    ) -> SourceRegistry:
        defaults = _source_defaults(receipt, capability_id=capability_id)
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

    def _raw(
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

    def _receipts(
        self,
        receipts: tuple[RawFetchReceiptV1, ...],
        *,
        capability_id: str,
    ) -> tuple[
        dict[tuple[str, str], tuple[SourceRegistry, RawFetchResult, RawFetchReceiptV1]],
        tuple[int, ...],
    ]:
        stored: dict[
            tuple[str, str],
            tuple[SourceRegistry, RawFetchResult, RawFetchReceiptV1],
        ] = {}
        raw_ids: list[int] = []
        for receipt in receipts:
            key = (receipt.provider, receipt.source)
            if key in stored:
                raise ValueError("duplicate Taiwan realtime provider/source receipt")
            source = self._source(receipt, capability_id=capability_id)
            raw = self._raw(source, receipt)
            stored[key] = (source, raw, receipt)
            raw_ids.append(raw.id)
        return stored, tuple(raw_ids)

    def _validate_observation(
        self,
        requirement: DataRequirementV2,
        observation: DepthObservation | AuctionObservation,
        receipt: RawFetchReceiptV1,
    ) -> tuple[datetime, datetime]:
        if not isinstance(requirement.target, InstrumentTarget):
            raise ValueError("Taiwan realtime transaction requires instrument target")
        if observation.instrument != requirement.target.instrument:
            raise ValueError("realtime observation crossed requested instrument")
        if observation.instrument.market is not Market.TW:
            raise ValueError("Taiwan realtime transaction requires market=TW")
        if observation.lineage.provider != receipt.provider:
            raise ValueError("realtime observation provider does not match receipt")
        if observation.lineage.source != receipt.source:
            raise ValueError("realtime observation source does not match receipt")
        if observation.lineage.raw_contract_version != receipt.parser_version:
            raise ValueError("realtime observation parser does not match receipt")
        if observation.lineage.content_hash != receipt.content_hash:
            raise ValueError("realtime observation content hash does not match receipt")
        event_at = observation.lineage.event_at
        if event_at is None:
            raise ValueError("realtime observation requires event_at")
        received_at = observation.lineage.received_at or receipt.fetched_at
        return event_at, received_at

    def _stock_exists(self, stock_id: str) -> None:
        exists = (
            self._db.query(StockMaster.id)
            .filter(StockMaster.stock_id == stock_id)
            .first()
        )
        if exists is None:
            raise ValueError("realtime target is missing from StockMaster")


def _level_signature(level: DepthLevel) -> tuple[object, ...]:
    quantity = _quantity_values(level.quantity)
    return (
        level.level,
        level.price,
        quantity["value"],
        quantity["unit"],
        quantity["original_value"],
        quantity["original_unit"],
        quantity["scale"],
        level.price_state.value,
    )


def _stored_level_signature(row: TaiwanStockDepthLevel) -> tuple[object, ...]:
    return (
        row.level,
        row.price,
        row.quantity_value,
        row.quantity_unit,
        row.original_value,
        row.original_unit,
        row.scale,
        row.price_state,
    )


class TaiwanDepthTransaction(_RealtimeTransactionOwner):
    def _upsert(
        self,
        requirement: DataRequirementV2,
        observation: DepthObservation,
        *,
        source: SourceRegistry,
        raw: RawFetchResult,
        receipt: RawFetchReceiptV1,
    ) -> bool:
        event_at, received_at = self._validate_observation(
            requirement,
            observation,
            receipt,
        )
        evidence_session = taiwan_evidence_session(event_at)
        self._stock_exists(observation.instrument.symbol)
        row = (
            self._db.query(TaiwanStockDepthSnapshot)
            .filter(TaiwanStockDepthSnapshot.provider == receipt.provider)
            .filter(TaiwanStockDepthSnapshot.stock_id == observation.instrument.symbol)
            .filter(TaiwanStockDepthSnapshot.event_at == event_at)
            .first()
        )
        incoming = {
            "source_id": source.id,
            "raw_result_id": raw.id,
            "source": receipt.source,
            "market": observation.instrument.venue,
            "received_at": _as_utc(received_at),
            "fetched_at": _as_utc(receipt.fetched_at),
            "market_session": evidence_session.value,
            "observation_state": observation.state.value,
            "depth_capability": observation.capability.value,
            "raw_contract_version": observation.lineage.raw_contract_version,
        }
        incoming_levels = {
            "bid": tuple(_level_signature(level) for level in observation.bids),
            "ask": tuple(_level_signature(level) for level in observation.asks),
        }
        unchanged = False
        if row is None:
            row = TaiwanStockDepthSnapshot(
                provider=receipt.provider,
                stock_id=observation.instrument.symbol,
                event_at=event_at,
                **incoming,
            )
            self._db.add(row)
            self._db.flush()
        else:
            existing_levels = (
                self._db.query(TaiwanStockDepthLevel)
                .filter(TaiwanStockDepthLevel.snapshot_id == row.id)
                .order_by(
                    TaiwanStockDepthLevel.side,
                    TaiwanStockDepthLevel.level,
                )
                .all()
            )
            stored_levels = {
                side: tuple(
                    _stored_level_signature(level)
                    for level in existing_levels
                    if level.side == side
                )
                for side in ("bid", "ask")
            }
            comparable = {
                key: value
                for key, value in incoming.items()
                if key not in {"source_id", "raw_result_id", "received_at", "fetched_at"}
            }
            unchanged = all(getattr(row, key) == value for key, value in comparable.items())
            unchanged = unchanged and stored_levels == incoming_levels
            if not unchanged:
                for level in existing_levels:
                    self._db.delete(level)
        for key, value in incoming.items():
            setattr(row, key, value)
        if not unchanged:
            for side, levels in (("bid", observation.bids), ("ask", observation.asks)):
                for level in levels:
                    quantity = _quantity_values(level.quantity)
                    self._db.add(
                        TaiwanStockDepthLevel(
                            snapshot_id=row.id,
                            side=side,
                            level=level.level,
                            price=level.price,
                            quantity_value=quantity["value"],
                            quantity_unit=quantity["unit"],
                            original_value=quantity["original_value"],
                            original_unit=quantity["original_unit"],
                            scale=quantity["scale"],
                            price_state=level.price_state.value,
                        )
                    )
        return unchanged

    def persist_depth_acquisition(
        self,
        requirement: DataRequirementV2,
        acquisition: DepthAcquisitionResult,
    ) -> PersistenceSummary:
        if not isinstance(requirement.request, SnapshotCapabilityRequest):
            raise ValueError("depth transaction requires snapshot request")
        if requirement.request.capability_id != TW_ORDER_BOOK_CAPABILITY_ID:
            raise ValueError("depth transaction capability mismatch")
        if not acquisition.summary.attempted:
            raise ValueError("transaction cannot persist non-attempted acquisition")
        written = unchanged = 0
        try:
            receipts, raw_ids = self._receipts(
                acquisition.receipts,
                capability_id=TW_ORDER_BOOK_CAPABILITY_ID,
            )
            for observation in acquisition.observations:
                matched = receipts.get(
                    (observation.lineage.provider, observation.lineage.source)
                )
                if matched is None:
                    raise ValueError("depth observation has no matching raw receipt")
                source, raw, receipt = matched
                if self._upsert(
                    requirement,
                    observation,
                    source=source,
                    raw=raw,
                    receipt=receipt,
                ):
                    unchanged += 1
                else:
                    written += 1
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
            raw_result_ids=raw_ids,
            limitations=acquisition.summary.limitations,
        )


def _auction_quantity_fields(
    prefix: str,
    quantity: Quantity | None,
) -> dict[str, object | None]:
    values = _quantity_values(quantity)
    return {
        f"{prefix}_quantity_value": values["value"],
        f"{prefix}_quantity_unit": values["unit"],
    }


class TaiwanAuctionTransaction(_RealtimeTransactionOwner):
    def _upsert(
        self,
        requirement: DataRequirementV2,
        observation: AuctionObservation,
        *,
        source: SourceRegistry,
        raw: RawFetchResult,
        receipt: RawFetchReceiptV1,
    ) -> bool:
        event_at, received_at = self._validate_observation(
            requirement,
            observation,
            receipt,
        )
        evidence_session = taiwan_evidence_session(event_at)
        self._stock_exists(observation.instrument.symbol)
        indicative = _quantity_values(observation.indicative_quantity)
        incoming: dict[str, object | None] = {
            "source_id": source.id,
            "raw_result_id": raw.id,
            "source": receipt.source,
            "market": observation.instrument.venue,
            "trade_date": event_at.astimezone(TAIWAN_TZ).date(),
            "received_at": _as_utc(received_at),
            "fetched_at": _as_utc(receipt.fetched_at),
            "market_session": evidence_session.value,
            "observation_state": observation.state.value,
            "indicative_price": observation.indicative_price,
            "indicative_quantity_value": indicative["value"],
            "indicative_quantity_unit": indicative["unit"],
            "indicative_original_value": indicative["original_value"],
            "indicative_original_unit": indicative["original_unit"],
            "indicative_scale": indicative["scale"],
            "provisional": observation.provisional,
            "raw_contract_version": observation.lineage.raw_contract_version,
        }
        for prefix, level in (
            ("best_bid", observation.best_bid),
            ("best_ask", observation.best_ask),
        ):
            incoming[f"{prefix}_level"] = level.level if level is not None else None
            incoming[f"{prefix}_price"] = level.price if level is not None else None
            incoming.update(
                _auction_quantity_fields(
                    prefix,
                    level.quantity if level is not None else None,
                )
            )
            incoming[f"{prefix}_price_state"] = (
                level.price_state.value if level is not None else None
            )
        row = (
            self._db.query(TaiwanStockAuctionSnapshot)
            .filter(TaiwanStockAuctionSnapshot.provider == receipt.provider)
            .filter(TaiwanStockAuctionSnapshot.stock_id == observation.instrument.symbol)
            .filter(TaiwanStockAuctionSnapshot.event_at == event_at)
            .filter(
                TaiwanStockAuctionSnapshot.auction_type
                == observation.auction_type.value
            )
            .first()
        )
        comparable = {
            key: value
            for key, value in incoming.items()
            if key not in {"source_id", "raw_result_id", "received_at", "fetched_at"}
        }
        unchanged = row is not None and all(
            getattr(row, key) == value for key, value in comparable.items()
        )
        if row is None:
            row = TaiwanStockAuctionSnapshot(
                provider=receipt.provider,
                stock_id=observation.instrument.symbol,
                event_at=event_at,
                auction_type=observation.auction_type.value,
                **incoming,
            )
            self._db.add(row)
        else:
            for key, value in incoming.items():
                setattr(row, key, value)
        return unchanged

    def persist_auction_acquisition(
        self,
        requirement: DataRequirementV2,
        acquisition: AuctionAcquisitionResult,
    ) -> PersistenceSummary:
        if not isinstance(requirement.request, SnapshotCapabilityRequest):
            raise ValueError("auction transaction requires snapshot request")
        if requirement.request.capability_id != TW_AUCTION_CAPABILITY_ID:
            raise ValueError("auction transaction capability mismatch")
        if requirement.request.auction_type is None:
            raise ValueError("auction transaction requires an explicit auction type")
        if not acquisition.summary.attempted:
            raise ValueError("transaction cannot persist non-attempted acquisition")
        written = unchanged = 0
        try:
            receipts, raw_ids = self._receipts(
                acquisition.receipts,
                capability_id=TW_AUCTION_CAPABILITY_ID,
            )
            for observation in acquisition.observations:
                if observation.auction_type is not requirement.request.auction_type:
                    raise ValueError("auction observation type crossed requested policy")
                matched = receipts.get(
                    (observation.lineage.provider, observation.lineage.source)
                )
                if matched is None:
                    raise ValueError("auction observation has no matching raw receipt")
                source, raw, receipt = matched
                if self._upsert(
                    requirement,
                    observation,
                    source=source,
                    raw=raw,
                    receipt=receipt,
                ):
                    unchanged += 1
                else:
                    written += 1
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
            raw_result_ids=raw_ids,
            limitations=acquisition.summary.limitations,
        )


__all__ = ["TaiwanAuctionTransaction", "TaiwanDepthTransaction"]
