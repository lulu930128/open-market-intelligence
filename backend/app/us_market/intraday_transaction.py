"""Atomic transaction owner for canonical US quote and intraday evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import (
    MarketIntradayBar,
    MarketIntradayBarLineage,
    RawFetchResult,
    SourceRegistry,
    USQuoteSnapshot,
    utc_now,
)
from app.market_data.contracts import BarObservation, Market, Quantity, QuoteObservation
from app.market_data.gateway import BarAcquisitionResult, QuoteAcquisitionResult
from app.market_data.integration_contracts import (
    BarCapabilityRequest,
    DataRequirementV2,
    InstrumentTarget,
    PersistenceSummary,
    RawFetchReceiptV1,
    SnapshotCapabilityRequest,
)
from app.us_market.market_data.descriptors import (
    us_intraday_descriptor_for_resource,
    us_provider_auth_type,
    us_quote_descriptor_for_resource,
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("US market lineage timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


def _number(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _quantity(value: Quantity | None) -> int | None:
    if value is None:
        return None
    if value.value != value.value.to_integral_value():
        raise ValueError("US market quantities must contain integral shares")
    return int(value.value)


class _USRawReceiptTransaction:
    def __init__(self, db: Session, *, capability: str) -> None:
        self._db = db
        self._capability = capability

    def _descriptor(self, receipt: RawFetchReceiptV1):
        descriptor = (
            us_quote_descriptor_for_resource(receipt.resource_id)
            if self._capability == "quote.snapshot"
            else us_intraday_descriptor_for_resource(receipt.resource_id)
        )
        if descriptor.provider_key != receipt.provider:
            raise ValueError("US receipt provider/resource registration mismatch")
        return descriptor

    def source_and_raw(self, receipt: RawFetchReceiptV1) -> tuple[SourceRegistry, RawFetchResult, bool]:
        descriptor = self._descriptor(receipt)
        source = self._db.query(SourceRegistry).filter(SourceRegistry.source_name == receipt.source).first()
        if source is None:
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
        elif source.parser_type not in {None, receipt.parser_version}:
            raise ValueError("US receipt parser conflicts with registered source")
        raw = (
            self._db.query(RawFetchResult)
            .filter(RawFetchResult.source_id == source.id)
            .filter(RawFetchResult.content_hash == receipt.content_hash)
            .filter(RawFetchResult.parser_version == receipt.parser_version)
            .first()
        )
        created = raw is None
        if raw is None:
            raw = RawFetchResult(
                source_id=source.id,
                fetched_at=_utc(receipt.fetched_at),
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
        return source, raw, created


class USQuoteTransaction:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._raw = _USRawReceiptTransaction(db, capability="quote.snapshot")

    def persist_quote_acquisition(self, requirement: DataRequirementV2, acquisition: QuoteAcquisitionResult) -> PersistenceSummary:
        if not isinstance(requirement.target, InstrumentTarget) or not isinstance(requirement.request, SnapshotCapabilityRequest) or requirement.request.capability_id != "quote.snapshot":
            raise ValueError("US quote transaction capability mismatch")
        if not acquisition.summary.attempted:
            raise ValueError("transaction cannot persist non-attempted acquisition")
        stored: dict[tuple[str, str], tuple[SourceRegistry, RawFetchResult, RawFetchReceiptV1]] = {}
        raw_ids: list[int] = []
        receipts_written = inserted = updated = unchanged = 0
        try:
            for receipt in acquisition.receipts:
                key = (receipt.provider, receipt.source)
                if key in stored:
                    raise ValueError("duplicate US quote provider/source receipt")
                source, raw, created = self._raw.source_and_raw(receipt)
                stored[key] = (source, raw, receipt)
                raw_ids.append(raw.id)
                receipts_written += int(created)
            for quote in acquisition.observations:
                if quote.instrument != requirement.target.instrument or quote.instrument.market is not Market.US:
                    raise ValueError("US quote observation crossed requested instrument")
                matched = stored.get((quote.lineage.provider, quote.lineage.source))
                if matched is None:
                    raise ValueError("US quote observation has no raw receipt")
                source, raw, receipt = matched
                event_at = quote.lineage.event_at
                if event_at is None or quote.lineage.content_hash != raw.content_hash:
                    raise ValueError("US quote observation raw lineage mismatch")
                if quote.lineage.raw_contract_version != receipt.parser_version:
                    raise ValueError("US quote parser identity mismatch")
                incoming = {
                    "source_id": source.id,
                    "raw_result_id": raw.id,
                    "source": quote.lineage.source,
                    "venue": quote.instrument.venue,
                    "instrument_type": quote.instrument.instrument_type.value,
                    "trade_date": quote.trade_date,
                    "received_at": _utc(quote.lineage.received_at or receipt.fetched_at),
                    "fetched_at": _utc(receipt.fetched_at),
                    "currency": quote.currency,
                    "observation_state": quote.state.value,
                    "trade_state": quote.trade_state.value,
                    "last_trade_price": _number(quote.last_trade_price),
                    "last_trade_quantity": _quantity(quote.last_trade_quantity),
                    "cumulative_quantity": _quantity(quote.cumulative_quantity),
                    "open_price": _number(quote.open_price),
                    "high_price": _number(quote.high_price),
                    "low_price": _number(quote.low_price),
                    "previous_close": _number(quote.previous_close),
                    "authority": quote.lineage.authority.value,
                    "raw_contract_version": quote.lineage.raw_contract_version,
                    "raw_payload_hash": raw.content_hash,
                }
                row = (
                    self._db.query(USQuoteSnapshot)
                    .filter(USQuoteSnapshot.provider == quote.lineage.provider)
                    .filter(USQuoteSnapshot.symbol == quote.instrument.symbol)
                    .filter(USQuoteSnapshot.event_at == _utc(event_at))
                    .first()
                )
                if row is None:
                    self._db.add(USQuoteSnapshot(provider=quote.lineage.provider, symbol=quote.instrument.symbol, event_at=_utc(event_at), **incoming))
                    inserted += 1
                else:
                    is_unchanged = all(getattr(row, key) == value for key, value in incoming.items())
                    for key, value in incoming.items():
                        setattr(row, key, value)
                    if is_unchanged:
                        unchanged += 1
                    else:
                        updated += 1
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise
        return PersistenceSummary(
            attempted=True,
            committed=True,
            receipts_written=receipts_written,
            observations_written=inserted + updated,
            observations_inserted=inserted,
            observations_updated=updated,
            observations_unchanged=unchanged,
            raw_result_ids=tuple(dict.fromkeys(raw_ids)),
            limitations=acquisition.summary.limitations,
        )


class USIntradayBarTransaction:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._raw = _USRawReceiptTransaction(db, capability="intraday.bars")

    def persist_bar_acquisition(self, requirement: DataRequirementV2, acquisition: BarAcquisitionResult) -> PersistenceSummary:
        if not isinstance(requirement.target, InstrumentTarget) or not isinstance(requirement.request, BarCapabilityRequest) or requirement.request.capability_id != "intraday.bars":
            raise ValueError("US intraday transaction capability mismatch")
        if not acquisition.summary.attempted:
            raise ValueError("transaction cannot persist non-attempted acquisition")
        stored: dict[tuple[str, str], tuple[SourceRegistry, RawFetchResult, RawFetchReceiptV1]] = {}
        raw_ids: list[int] = []
        receipts_written = written = unchanged = 0
        try:
            for receipt in acquisition.receipts:
                key = (receipt.provider, receipt.source)
                if key in stored:
                    raise ValueError("duplicate US intraday provider/source receipt")
                source, raw, created = self._raw.source_and_raw(receipt)
                stored[key] = (source, raw, receipt)
                raw_ids.append(raw.id)
                receipts_written += int(created)
            for bar in acquisition.observations:
                if bar.instrument != requirement.target.instrument or bar.instrument.market is not Market.US or bar.interval != requirement.request.interval:
                    raise ValueError("US intraday observation identity mismatch")
                matched = stored.get((bar.lineage.provider, bar.lineage.source))
                if matched is None:
                    raise ValueError("US intraday observation has no raw receipt")
                source, raw, receipt = matched
                if bar.lineage.event_at is None or bar.lineage.content_hash != raw.content_hash:
                    raise ValueError("US intraday observation raw lineage mismatch")
                parser = bar.lineage.raw_contract_version or ""
                if not (parser == receipt.parser_version or parser.startswith(f"{receipt.parser_version}+")):
                    raise ValueError("US intraday parser identity mismatch")
                incoming = {
                    "provider": receipt.provider,
                    "stock_id": bar.instrument.symbol,
                    "market": bar.instrument.venue,
                    "symbol": bar.instrument.symbol,
                    "interval": bar.interval,
                    "bar_time": _utc(bar.start_at),
                    "open_price": _number(bar.open_price),
                    "high_price": _number(bar.high_price),
                    "low_price": _number(bar.low_price),
                    "close_price": _number(bar.close_price),
                    "trade_volume": _quantity(bar.volume),
                    "trade_value": int(bar.turnover_value) if bar.turnover_value is not None else None,
                    "source": receipt.source,
                    "source_url": receipt.url,
                }
                row = (
                    self._db.query(MarketIntradayBar)
                    .filter(MarketIntradayBar.provider == receipt.provider)
                    .filter(MarketIntradayBar.stock_id == bar.instrument.symbol)
                    .filter(MarketIntradayBar.interval == bar.interval)
                    .filter(MarketIntradayBar.bar_time == _utc(bar.start_at))
                    .first()
                )
                is_unchanged = row is not None and all(getattr(row, key) == value for key, value in incoming.items())
                if row is None:
                    row = MarketIntradayBar(**incoming)
                    self._db.add(row)
                    self._db.flush()
                else:
                    for key, value in incoming.items():
                        setattr(row, key, value)
                    row.updated_at = utc_now()
                lineage = self._db.query(MarketIntradayBarLineage).filter(MarketIntradayBarLineage.bar_id == row.id).first()
                if lineage is None:
                    lineage = MarketIntradayBarLineage(bar_id=row.id)
                    self._db.add(lineage)
                lineage.source_id = source.id
                lineage.raw_result_id = raw.id
                lineage.provider = receipt.provider
                lineage.source = receipt.source
                lineage.authority = bar.lineage.authority.value
                lineage.raw_contract_version = parser
                lineage.event_at = _utc(bar.lineage.event_at)
                lineage.received_at = _utc(bar.lineage.received_at or receipt.fetched_at)
                lineage.fetched_at = _utc(receipt.fetched_at)
                lineage.finalization = bar.finalization.value
                lineage.source_interval = bar.interval
                lineage.calculation_version = None
                lineage.component_raw_result_ids_json = None
                lineage.updated_at = utc_now()
                if is_unchanged:
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
            receipts_written=receipts_written,
            observations_written=written,
            observations_unchanged=unchanged,
            raw_result_ids=tuple(dict.fromkeys(raw_ids)),
            limitations=acquisition.summary.limitations,
        )


__all__ = ["USIntradayBarTransaction", "USQuoteTransaction"]
