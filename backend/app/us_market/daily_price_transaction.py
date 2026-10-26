"""Explicit transaction owner for US daily raw receipts and canonical bars."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import tuple_
from app.utils.owner_checkpoint import OwnerOutcomeUnknown

from sqlalchemy.orm import Session

from app.db.models import RawFetchResult, SourceRegistry, USDailyPrice
from app.market_data.contracts import (
    BarFinalization,
    InstrumentType,
    Market,
    QuantityUnit,
)
from app.market_data.gateway import BarAcquisitionResult
from app.market_data.integration_contracts import (
    BarCapabilityRequest,
    DataRequirementV2,
    PersistenceSummary,
    RawFetchReceiptV1,
    RefreshRequirementV1,
)
from app.us_market.market_data.descriptors import (
    MASSIVE_GROUPED_DAILY_RESOURCE_ID,
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

    def reconcile_bar_acquisition(self, acquisition: BarAcquisitionResult) -> str:
        """Read-only proof after an uncertain commit; never replay external IO."""
        from app.us_market.daily_price_eligibility import us_daily_exact_volume

        with self._db.no_autoflush:
            for receipt in acquisition.receipts:
                raw = (self._db.query(RawFetchResult).join(SourceRegistry)
                       .filter(SourceRegistry.source_name == receipt.source,
                               RawFetchResult.content_hash == receipt.content_hash,
                               RawFetchResult.parser_version == receipt.parser_version).first())
                if raw is None:
                    return "unknown"
            by_key = {}
            keys = [(o.lineage.provider, o.instrument.symbol, o.end_at.date()) for o in acquisition.observations]
            for offset in range(0, len(keys), 250):
                for row in self._db.query(USDailyPrice).filter(
                    tuple_(USDailyPrice.provider, USDailyPrice.symbol, USDailyPrice.trade_date).in_(keys[offset:offset + 250])
                ).all():
                    by_key[(row.provider, row.symbol, row.trade_date)] = row
            for observation, key in zip(acquisition.observations, keys):
                row = by_key.get(key)
                if row is None or row.raw_payload_hash != observation.lineage.content_hash or row.price_basis != "raw":
                    return "unknown"
                if any(Decimal(str(getattr(row, field))) != getattr(observation, field)
                       for field in ("open_price", "high_price", "low_price", "close_price")):
                    return "unknown"
                if us_daily_exact_volume(row) != (observation.volume.value if observation.volume else None):
                    return "unknown"
        return "committed" if acquisition.receipts else "unknown"

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
        if self._db.new or self._db.dirty or self._db.deleted:
            raise ValueError("US daily transaction requires a clean Session")
        commit_started = False
        grouped = any(receipt.resource_id == MASSIVE_GROUPED_DAILY_RESOURCE_ID for receipt in acquisition.receipts)
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

            # Bounded batch lookup, not one SELECT per stock. No destructive replacement.
            identities = {(o.lineage.provider, o.instrument.symbol, o.end_at.date()) for o in acquisition.observations}
            if len(identities) != len(acquisition.observations):
                raise ValueError("duplicate canonical observation identity")
            existing = {}
            keys = sorted(identities)
            for offset in range(0, len(keys), 250):
                for row in self._db.query(USDailyPrice).filter(
                    tuple_(USDailyPrice.provider, USDailyPrice.symbol, USDailyPrice.trade_date).in_(keys[offset:offset + 250])
                ).all():
                    existing[(row.provider, row.symbol, row.trade_date)] = row
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
                row = existing.get((observation.lineage.provider, observation.instrument.symbol, trade_date))
                volume_status = observation.volume_status
                if volume_status is None:
                    raise ValueError("US daily canonical bar requires volume_status")
                if observation.instrument.instrument_type is InstrumentType.INDEX:
                    if volume_status != "not_applicable" or observation.volume is not None:
                        raise ValueError(
                            "US index daily volume must be null and not_applicable"
                        )
                elif (
                    volume_status != "observed"
                    or observation.volume is None
                    or observation.volume.unit is not QuantityUnit.SHARE
                ):
                    raise ValueError("stock/ETF daily volume must be observed shares")
                if observation.price_basis != "raw":
                    raise ValueError("US daily canonical bar requires explicit raw price basis")
                exact_volume = observation.volume.value if observation.volume else None
                volume_text = format(exact_volume, "f") if exact_volume is not None else None
                if volume_text is not None and len(volume_text) > 64:
                    raise ValueError("canonical volume exceeds exact storage bound")
                volume = (int(exact_volume) if exact_volume is not None
                          and exact_volume == exact_volume.to_integral_value()
                          and exact_volume <= 9223372036854775807 else None)
                incoming = {
                    "open_price": float(observation.open_price),
                    "high_price": float(observation.high_price),
                    "low_price": float(observation.low_price),
                    "close_price": float(observation.close_price),
                    "trade_volume": volume,
                    "trade_volume_decimal": volume_text,
                    "source_id": source.id,
                    "raw_result_id": raw.id,
                    "raw_payload_hash": raw.content_hash,
                    "fetched_at": raw.fetched_at,
                    "authority": observation.lineage.authority.value,
                    "raw_contract_version": observation.lineage.raw_contract_version,
                    "event_at": observation.lineage.event_at.astimezone(timezone.utc),
                    "finalization": observation.finalization.value,
                    "price_basis": observation.price_basis,
                    "volume_unit": "shares" if exact_volume is not None else None,
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
            commit_started = True
            self._db.commit()
        except Exception as exc:
            try:
                self._db.rollback()
            except Exception as rollback_exc:
                raise OwnerOutcomeUnknown("US_DAILY_ROLLBACK_OUTCOME_UNKNOWN") from rollback_exc
            if commit_started and grouped:
                raise OwnerOutcomeUnknown("US_DAILY_COMMIT_OUTCOME_UNKNOWN_RECONCILE_BEFORE_RETRY") from exc
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
