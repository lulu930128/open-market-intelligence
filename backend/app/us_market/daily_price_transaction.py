"""Explicit transaction owner for US daily raw receipts and canonical bars."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import RawFetchResult, SourceRegistry, USDailyPrice
from app.market_data.contracts import BarFinalization, InstrumentType, Market
from app.market_data.gateway import BarAcquisitionResult
from app.market_data.integration_contracts import (
    BarCapabilityRequest,
    DataRequirementV2,
    PersistenceSummary,
    RawFetchReceiptV1,
    RefreshRequirementV1,
)
from app.us_market.market_data.descriptors import (
    us_daily_descriptor_for_resource,
    us_provider_auth_type,
)


def _same_value(current: object, incoming: object) -> bool:
    if isinstance(current, datetime) and isinstance(incoming, datetime):
        current_utc = (
            current.replace(tzinfo=timezone.utc)
            if current.tzinfo is None or current.utcoffset() is None
            else current.astimezone(timezone.utc)
        )
        incoming_utc = (
            incoming.replace(tzinfo=timezone.utc)
            if incoming.tzinfo is None or incoming.utcoffset() is None
            else incoming.astimezone(timezone.utc)
        )
        return current_utc == incoming_utc
    return current == incoming


class USDailyPriceTransaction:
    def __init__(self, db: Session) -> None:
        self._db = db

    def _source(self, receipt: RawFetchReceiptV1) -> SourceRegistry:
        source = (
            self._db.query(SourceRegistry)
            .filter(SourceRegistry.source_name == receipt.source)
            .first()
        )
        if source is None:
            descriptor = us_daily_descriptor_for_resource(receipt.resource_id)
            if descriptor.provider_key != receipt.provider:
                raise ValueError("receipt provider/resource registration mismatch")
            source = SourceRegistry(
                source_name=receipt.source,
                source_type="api",
                category="market_data",
                endpoint_url=receipt.url,
                enabled=True,
                priority=descriptor.priority,
                parser_type=receipt.parser_version,
                auth_type=us_provider_auth_type(receipt.provider),
                reliability_level="vendor",
            )
            self._db.add(source)
            self._db.flush()
        return source

    def _raw_receipt(
        self,
        source: SourceRegistry,
        receipt: RawFetchReceiptV1,
    ) -> tuple[RawFetchResult, bool]:
        existing = (
            self._db.query(RawFetchResult)
            .filter(RawFetchResult.source_id == source.id)
            .filter(RawFetchResult.content_hash == receipt.content_hash)
            .filter(RawFetchResult.parser_version == receipt.parser_version)
            .first()
        )
        if existing is not None:
            return existing, False
        raw = RawFetchResult(
            source_id=source.id,
            fetched_at=receipt.fetched_at.astimezone(timezone.utc),
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
        return raw, True

    def persist_bar_acquisition(
        self,
        requirement: DataRequirementV2 | RefreshRequirementV1,
        acquisition: BarAcquisitionResult,
    ) -> PersistenceSummary:
        if not acquisition.summary.attempted:
            raise ValueError("transaction cannot persist a non-attempted acquisition")
        if isinstance(requirement, DataRequirementV2):
            if not isinstance(requirement.request, BarCapabilityRequest):
                raise ValueError("US daily transaction requires a bar request")
            if requirement.request.price_basis != "raw":
                raise ValueError("US daily canonical persistence currently requires raw prices")

        receipt_index: dict[tuple[str, str], tuple[SourceRegistry, RawFetchResult]] = {}
        raw_ids: list[int] = []
        receipts_written = 0
        observations_written = 0
        observations_inserted = 0
        observations_updated = 0
        observations_unchanged = 0
        try:
            for receipt in acquisition.receipts:
                key = (receipt.provider, receipt.source)
                if key in receipt_index:
                    raise ValueError("duplicate provider/source receipt in acquisition")
                source = self._source(receipt)
                raw, created = self._raw_receipt(source, receipt)
                receipt_index[key] = (source, raw)
                raw_ids.append(raw.id)
                receipts_written += int(created)

            for observation in acquisition.observations:
                if observation.instrument.market is not Market.US:
                    raise ValueError("US daily transaction requires market=US")
                if observation.interval != "1d":
                    raise ValueError("US daily transaction requires interval=1d")
                if observation.finalization not in {
                    BarFinalization.FINAL,
                    BarFinalization.CORRECTED,
                }:
                    raise ValueError("US daily transaction requires final/corrected bars")
                key = (
                    observation.lineage.provider,
                    observation.lineage.source,
                )
                source_raw = receipt_index.get(key)
                if source_raw is None:
                    raise ValueError(
                        "canonical observation has no matching raw provider/source receipt"
                    )
                source, raw = source_raw
                if observation.lineage.content_hash != raw.content_hash:
                    raise ValueError("canonical observation content hash mismatches receipt")
                trade_date = observation.end_at.date()
                row = (
                    self._db.query(USDailyPrice)
                    .filter(USDailyPrice.provider == observation.lineage.provider)
                    .filter(USDailyPrice.symbol == observation.instrument.symbol)
                    .filter(USDailyPrice.trade_date == trade_date)
                    .first()
                )
                volume_status = observation.volume_status
                if volume_status is None:
                    raise ValueError("US daily canonical bar requires volume_status")
                if volume_status == "missing":
                    raise ValueError("stock/ETF daily volume cannot be silently missing")
                if (
                    volume_status == "not_applicable"
                    and observation.instrument.instrument_type is not InstrumentType.INDEX
                ):
                    raise ValueError("volume not_applicable is only valid for US indexes")
                if observation.price_basis != "raw":
                    raise ValueError("US daily canonical bar requires explicit raw price basis")
                volume = int(observation.volume.value) if observation.volume else None
                incoming = {
                    "open_price": float(observation.open_price),
                    "high_price": float(observation.high_price),
                    "low_price": float(observation.low_price),
                    "close_price": float(observation.close_price),
                    "trade_volume": volume,
                    "source_id": source.id,
                    "raw_result_id": raw.id,
                    "raw_payload_hash": raw.content_hash,
                    "fetched_at": raw.fetched_at,
                    "authority": observation.lineage.authority.value,
                    "raw_contract_version": observation.lineage.raw_contract_version,
                    "event_at": observation.lineage.event_at.astimezone(timezone.utc),
                    "finalization": observation.finalization.value,
                    "price_basis": observation.price_basis,
                    "volume_unit": "shares" if volume is not None else None,
                    "volume_status": volume_status,
                }
                if row is None:
                    row = USDailyPrice(
                        provider=observation.lineage.provider,
                        symbol=observation.instrument.symbol,
                        trade_date=trade_date,
                        currency="USD",
                        source_url=raw.url,
                        **incoming,
                    )
                    self._db.add(row)
                    observations_written += 1
                    observations_inserted += 1
                else:
                    unchanged = all(
                        _same_value(getattr(row, name), value)
                        for name, value in incoming.items()
                    )
                    for name, value in incoming.items():
                        setattr(row, name, value)
                    row.source_url = raw.url
                    if unchanged:
                        observations_unchanged += 1
                    else:
                        observations_written += 1
                        observations_updated += 1
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise
        return PersistenceSummary(
            attempted=True,
            committed=True,
            receipts_written=receipts_written,
            observations_written=observations_written,
            observations_inserted=observations_inserted,
            observations_updated=observations_updated,
            observations_unchanged=observations_unchanged,
            raw_result_ids=tuple(dict.fromkeys(raw_ids)),
            limitations=acquisition.summary.limitations,
        )


__all__ = ["USDailyPriceTransaction"]
