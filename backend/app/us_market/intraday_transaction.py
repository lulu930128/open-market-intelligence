"""Atomic transaction owner for canonical US quote and intraday evidence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import tuple_
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db.models import (
    MarketIntradayBar,
    MarketIntradayBarLineage,
    RawFetchResult,
    SourceRegistry,
    USIntradayObservationState,
    USQuoteSnapshot,
    utc_now,
)
from app.market_data.contracts import (
    BarObservation,
    InstrumentType,
    Market,
    Quantity,
    QuoteObservation,
)
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


def _stored_utc(value: datetime) -> datetime:
    """Restore SQLite's timezone-less UTC storage representation."""

    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _bar_row_matches(row: MarketIntradayBar, incoming: dict[str, object]) -> bool:
    for key, value in incoming.items():
        current = getattr(row, key)
        if key == "bar_time":
            current = _stored_utc(current)
        if current != value:
            return False
    return True


def _number(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _quantity(value: Quantity | None) -> int | None:
    if value is None:
        return None
    if value.value != value.value.to_integral_value():
        raise ValueError("US market quantities must contain integral shares")
    return int(value.value)


def _validate_intraday_bar_identity(bar: BarObservation) -> None:
    if bar.interval != "1m":
        return
    if bar.start_at.second != 0 or bar.start_at.microsecond != 0:
        raise ValueError("US 1m intraday bar start_at must be minute-aligned")
    if bar.end_at - bar.start_at != timedelta(minutes=1):
        raise ValueError("US 1m intraday bar must cover exactly one minute")
    event_at = bar.lineage.event_at
    fetched_at = bar.lineage.fetched_at
    if event_at is not None and fetched_at is not None and event_at > fetched_at:
        raise ValueError("US intraday event_at cannot be later than fetched_at")


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
                    "provider_timeframe": (
                        receipt.provider_timeframe.value
                        if receipt.provider_timeframe is not None
                        else None
                    ),
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
        # Recovery can replay only the immutable acquisition. Pending caller
        # work must not be rolled back and silently omitted from a success.
        retry_snapshot = not (self._db.new or self._db.dirty or self._db.deleted)
        return self._persist_bar_acquisition_attempt(requirement, acquisition, retry_snapshot=retry_snapshot)

    def _persist_bar_acquisition_attempt(
        self, requirement: DataRequirementV2, acquisition: BarAcquisitionResult, *, retry_snapshot: bool,
    ) -> PersistenceSummary:
        if not isinstance(requirement.target, InstrumentTarget) or not isinstance(requirement.request, BarCapabilityRequest) or requirement.request.capability_id != "intraday.bars":
            raise ValueError("US intraday transaction capability mismatch")
        if not acquisition.summary.attempted:
            raise ValueError("transaction cannot persist non-attempted acquisition")
        stored: dict[tuple[str, str], tuple[SourceRegistry, RawFetchResult, RawFetchReceiptV1]] = {}
        raw_ids: list[int] = []
        receipts_written = written = unchanged = 0
        commit_started = False
        owns_physical_transaction = False
        connection = None
        try:
            # Reserve the writer before receipt/precedence reads. A deferred
            # read-to-write upgrade can fail immediately with SQLITE_BUSY even
            # when the configured busy timeout would allow admission to wait.
            # Acquisition has already finished; the reservation spans only this
            # persistence callback (including no-op validation). Do not restart
            # an existing caller transaction or discard its pending ORM work.
            connection = self._db.connection()
            if connection.dialect.name == "sqlite" and not connection.connection.driver_connection.in_transaction:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                owns_physical_transaction = True
            for receipt in acquisition.receipts:
                key = (receipt.provider, receipt.source)
                if key in stored:
                    raise ValueError("duplicate US intraday provider/source receipt")
                source, raw, created = self._raw.source_and_raw(receipt)
                stored[key] = (source, raw, receipt)
                raw_ids.append(raw.id)
                receipts_written += int(created)
            prepared = []
            for bar in acquisition.observations:
                if bar.instrument != requirement.target.instrument or bar.instrument.market is not Market.US or bar.interval != requirement.request.interval:
                    raise ValueError("US intraday observation identity mismatch")
                _validate_intraday_bar_identity(bar)
                matched = stored.get((bar.lineage.provider, bar.lineage.source))
                if matched is None:
                    raise ValueError("US intraday observation has no raw receipt")
                source, raw, receipt = matched
                if bar.lineage.event_at is None or bar.lineage.content_hash != raw.content_hash:
                    raise ValueError("US intraday observation raw lineage mismatch")
                parser = bar.lineage.raw_contract_version or ""
                if not (parser == receipt.parser_version or parser.startswith(f"{receipt.parser_version}+")):
                    raise ValueError("US intraday parser identity mismatch")
                if bar.volume_status is None:
                    raise ValueError("US intraday canonical bar requires volume_status")
                if bar.instrument.instrument_type is InstrumentType.INDEX:
                    if bar.volume_status != "not_applicable" or bar.volume is not None:
                        raise ValueError(
                            "US index intraday volume must be null and not_applicable"
                        )
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
                    "volume_status": bar.volume_status,
                    "trade_value": int(bar.turnover_value) if bar.turnover_value is not None else None,
                    "source": receipt.source,
                    "source_url": receipt.url,
                }
                prepared.append((bar, source, raw, receipt, parser, incoming))

            storage_keys = tuple(
                (
                    receipt.provider,
                    bar.instrument.symbol,
                    bar.interval,
                    _utc(bar.start_at),
                )
                for bar, _source, _raw, receipt, _parser, _incoming in prepared
            )
            if len(set(storage_keys)) != len(storage_keys):
                raise ValueError("duplicate canonical observation identity")
            existing_rows = (
                self._db.query(MarketIntradayBar)
                .filter(
                    tuple_(
                        MarketIntradayBar.provider,
                        MarketIntradayBar.stock_id,
                        MarketIntradayBar.interval,
                        MarketIntradayBar.bar_time,
                    ).in_(storage_keys)
                )
                .populate_existing()
                .all()
                if storage_keys
                else []
            )
            rows_by_key = {
                (
                    row.provider,
                    row.stock_id,
                    row.interval,
                    _stored_utc(row.bar_time),
                ): row
                for row in existing_rows
            }
            # Read stored provenance before any bar mutation. Keep both lookups
            # batched; refresh identity-map instances from the pinned snapshot.
            stored_lineages = (
                self._db.query(MarketIntradayBarLineage, RawFetchResult.content_hash)
                .outerjoin(RawFetchResult, RawFetchResult.id == MarketIntradayBarLineage.raw_result_id)
                .filter(MarketIntradayBarLineage.bar_id.in_([row.id for row in existing_rows]))
                .populate_existing()
                .all()
                if existing_rows else []
            )
            lineages_by_bar_id = {lineage.bar_id: lineage for lineage, _hash in stored_lineages}
            hashes_by_bar_id = {lineage.bar_id: content_hash for lineage, content_hash in stored_lineages}
            states_by_bar_id = {}
            existing_ids = [row.id for row in existing_rows]
            for offset in range(0, len(existing_ids), 500):
                states = (
                    self._db.query(USIntradayObservationState)
                    .filter(USIntradayObservationState.bar_id.in_(existing_ids[offset:offset + 500]))
                    .populate_existing().all()
                )
                states_by_bar_id.update((state.bar_id, state) for state in states)
            row_records = []
            for bar, source, raw, receipt, parser, incoming in prepared:
                storage_key = (
                    receipt.provider,
                    bar.instrument.symbol,
                    bar.interval,
                    _utc(bar.start_at),
                )
                row = rows_by_key.get(storage_key)
                lineage = lineages_by_bar_id.get(row.id) if row is not None else None
                observed_at = None
                observed_hash = None
                if lineage is not None and lineage.provider == receipt.provider:
                    observed_at = _stored_utc(lineage.fetched_at)
                    observed_hash = hashes_by_bar_id[row.id]
                state = states_by_bar_id.get(row.id) if row is not None else None
                if state is not None and (observed_at is None or _stored_utc(state.observed_fetched_at) >= observed_at):
                    observed_at = _stored_utc(state.observed_fetched_at)
                    observed_hash = state.observed_content_hash
                receipt_at = _utc(receipt.fetched_at)
                if observed_at is not None:
                    if observed_at > receipt_at:
                        unchanged += 1
                        continue
                    if observed_at == receipt_at and observed_hash != receipt.content_hash:
                        raise ValueError("US_INTRADAY_RECEIPT_TIME_CONFLICT")
                advance_observation = observed_at is None or receipt_at > observed_at
                is_unchanged = row is not None and _bar_row_matches(row, incoming)
                if row is None:
                    row = MarketIntradayBar(**incoming)
                    self._db.add(row)
                    rows_by_key[storage_key] = row
                elif not is_unchanged:
                    for key, value in incoming.items():
                        setattr(row, key, value)
                    row.updated_at = utc_now()
                row_records.append(
                    (bar, source, raw, receipt, parser, row, is_unchanged, advance_observation)
                )

            # Allocate IDs for all new rows in one flush. Existing lineage was
            # read above, before any OHLCV or provenance mutation.
            if row_records:
                self._db.flush()
            for bar, source, raw, receipt, parser, row, is_unchanged, advance_observation in row_records:
                lineage = lineages_by_bar_id.get(row.id)
                lineage_compatible = bool(
                    lineage is not None
                    and lineage.provider == receipt.provider
                    and lineage.source == receipt.source
                    and lineage.source_interval == bar.interval
                    and lineage.authority == bar.lineage.authority.value
                    and lineage.finalization == bar.finalization.value
                    and lineage.raw_contract_version
                    and (
                        lineage.raw_contract_version == parser
                        or lineage.raw_contract_version.startswith(f"{parser}+")
                    )
                )
                if advance_observation or not (is_unchanged and lineage_compatible):
                    state = states_by_bar_id.get(row.id)
                    if state is None:
                        state = USIntradayObservationState(bar_id=row.id)
                        self._db.add(state)
                        states_by_bar_id[row.id] = state
                    # Raw deduplication may retain an older fetched_at. This is
                    # the actual validated receipt time, never the raw row time.
                    state.observed_fetched_at = _utc(receipt.fetched_at)
                    state.observed_content_hash = receipt.content_hash
                if is_unchanged and lineage_compatible:
                    # An unchanged observation keeps its original immutable
                    # receipt lineage. Repointing every historical minute to
                    # the newest fetch is both misleading provenance and a
                    # large, unnecessary write amplification source.
                    unchanged += 1
                    continue
                if lineage is None:
                    lineage = MarketIntradayBarLineage(bar_id=row.id)
                    self._db.add(lineage)
                    lineages_by_bar_id[row.id] = lineage
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
                lineage.provider_timeframe = (
                    receipt.provider_timeframe.value
                    if receipt.provider_timeframe is not None
                    else None
                )
                lineage.calculation_version = None
                lineage.component_raw_result_ids_json = None
                lineage.updated_at = utc_now()
                written += int(not is_unchanged or not lineage_compatible)
            # Complete DML before entering commit, so a known snapshot upgrade
            # failure can be rolled back and retried without guessing whether
            # commit started. No commit-phase error is eligible for recovery.
            self._db.flush()
            commit_started = True
            self._db.commit()
        except Exception as exc:
            self._db.rollback()
            if (
                retry_snapshot and owns_physical_transaction and not commit_started
                and connection is not None and connection.dialect.name == "sqlite"
                and isinstance(exc, OperationalError)
                and getattr(exc.orig, "sqlite_errorcode", None) == 517  # SQLITE_BUSY_SNAPSHOT
            ):
                # Rollback succeeded, this owner started the physical tx with
                # no caller pending work, and commit was never entered. A
                # borrowed tx can contain already-flushed caller DML even if
                # the Session's new/dirty/deleted collections are now empty.
                # Reuse only acquired input; rebuild all ORM reads/counters.
                # This does not perform acquisition or retry an unknown commit.
                return self._persist_bar_acquisition_attempt(requirement, acquisition, retry_snapshot=False)
            raise
        if written:
            # Invalidate at the commit boundary, before Gateway reread/projection.
            from app.us_market.intraday_read_model_cache import invalidate_us_intraday_read_cache

            for symbol in {bar.instrument.symbol for bar, *_rest in row_records}:
                invalidate_us_intraday_read_cache(symbol)
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
