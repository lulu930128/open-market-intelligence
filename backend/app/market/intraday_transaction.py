"""Atomic transaction owner for canonical Taiwan intraday bars."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import (
    MarketIntradayBar,
    MarketIntradayBarLineage,
    RawFetchResult,
    SourceRegistry,
    utc_now,
)
from app.market.tw_instrument import resolve_taiwan_instrument
from app.market.tw_intraday_capabilities import (
    TW_INTRADAY_BARS_CAPABILITY_ID,
    intraday_source_binding,
)
from app.market_data.contracts import BarObservation, Market, Quantity
from app.market_data.gateway import BarAcquisitionResult
from app.market_data.integration_contracts import (
    BarCapabilityRequest,
    DataRequirementV2,
    InstrumentTarget,
    PersistenceSummary,
    RawFetchReceiptV1,
)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("intraday lineage timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _number(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _integer(quantity: Quantity | None) -> int | None:
    if quantity is None:
        return None
    if quantity.value != quantity.value.to_integral_value():
        raise ValueError("intraday volume must contain integral shares")
    return int(quantity.value)


class TaiwanIntradayBarTransaction:
    def __init__(self, db: Session) -> None:
        self._db = db

    def _source(self, receipt: RawFetchReceiptV1) -> SourceRegistry:
        binding = intraday_source_binding(
            provider=receipt.provider,
            source=receipt.source,
            resource_id=receipt.resource_id,
        )
        if binding is None or receipt.parser_version != binding.parser_version:
            raise ValueError("unsupported Taiwan intraday receipt identity")
        source = (
            self._db.query(SourceRegistry)
            .filter(SourceRegistry.source_name == receipt.source)
            .first()
        )
        if source is None:
            source = SourceRegistry(
                source_name=receipt.source,
                source_type=binding.source_type,
                category="market_data",
                endpoint_url=receipt.url,
                enabled=True,
                priority=binding.descriptor.priority,
                parser_type=binding.parser_version,
                auth_type=binding.auth_type,
                reliability_level=binding.reliability_level,
            )
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

    @staticmethod
    def _validate_observation(
        requirement: DataRequirementV2,
        observation: BarObservation,
        receipt: RawFetchReceiptV1,
    ) -> None:
        if not isinstance(requirement.target, InstrumentTarget):
            raise ValueError("intraday transaction requires instrument target")
        if observation.instrument != requirement.target.instrument:
            raise ValueError("intraday observation crossed requested instrument")
        if observation.instrument.market is not Market.TW:
            raise ValueError("intraday transaction requires market=TW")
        if requirement.request.interval != "1m" or observation.interval != "1m":
            raise ValueError("TW_BASE_BAR_INTERVAL_REQUIRED")
        if observation.interval != requirement.request.interval:
            raise ValueError("intraday observation interval mismatch")
        if (
            observation.start_at.second != 0
            or observation.start_at.microsecond != 0
            or observation.end_at - observation.start_at != timedelta(minutes=1)
        ):
            raise ValueError("Taiwan canonical 1m bar is not minute-grid aligned")
        if (
            observation.lineage.provider != receipt.provider
            or observation.lineage.source != receipt.source
            or observation.lineage.content_hash != receipt.content_hash
        ):
            raise ValueError("intraday observation raw identity mismatch")
        parser = observation.lineage.raw_contract_version
        if not (
            parser == receipt.parser_version
            or parser.startswith(f"{receipt.parser_version}+")
        ):
            raise ValueError("intraday observation parser identity mismatch")
        if observation.lineage.event_at is None:
            raise ValueError("intraday observation requires event_at")

    def _upsert(
        self,
        requirement: DataRequirementV2,
        observation: BarObservation,
        *,
        source: SourceRegistry,
        raw: RawFetchResult,
        receipt: RawFetchReceiptV1,
    ) -> bool:
        self._validate_observation(requirement, observation, receipt)
        resolved_instrument = resolve_taiwan_instrument(
            self._db,
            observation.instrument.symbol,
        )
        if resolved_instrument != observation.instrument:
            raise ValueError("intraday observation instrument identity mismatch")
        existing = (
            self._db.query(MarketIntradayBar)
            .filter(MarketIntradayBar.source_id == source.id)
            .filter(MarketIntradayBar.canonical_market == Market.TW.value)
            .filter(MarketIntradayBar.venue == observation.instrument.venue)
            .filter(
                MarketIntradayBar.instrument_type
                == observation.instrument.instrument_type.value
            )
            .filter(MarketIntradayBar.stock_id == observation.instrument.symbol)
            .filter(MarketIntradayBar.interval == observation.interval)
            .filter(MarketIntradayBar.bar_time == observation.start_at)
            .first()
        )
        incoming = {
            "source_id": source.id,
            "provider": receipt.provider,
            "stock_id": observation.instrument.symbol,
            "market": observation.instrument.venue,
            "canonical_market": Market.TW.value,
            "venue": observation.instrument.venue,
            "instrument_type": observation.instrument.instrument_type.value,
            "symbol": observation.instrument.symbol,
            "interval": observation.interval,
            "bar_time": observation.start_at,
            "open_price": _number(observation.open_price),
            "high_price": _number(observation.high_price),
            "low_price": _number(observation.low_price),
            "close_price": _number(observation.close_price),
            "trade_volume": _integer(observation.volume),
            "trade_value": (
                int(observation.turnover_value)
                if observation.turnover_value is not None
                else None
            ),
            "source": receipt.source,
            "source_url": receipt.url,
        }
        unchanged = False
        if existing is None:
            existing = MarketIntradayBar(**incoming)
            self._db.add(existing)
            self._db.flush()
        else:
            comparable = {
                key: value
                for key, value in incoming.items()
                if key != "bar_time"
            }
            unchanged = all(
                getattr(existing, key) == value for key, value in comparable.items()
            )
            for key, value in incoming.items():
                setattr(existing, key, value)
            existing.updated_at = utc_now()
        lineage = (
            self._db.query(MarketIntradayBarLineage)
            .filter(MarketIntradayBarLineage.bar_id == existing.id)
            .first()
        )
        if lineage is None:
            lineage = MarketIntradayBarLineage(bar_id=existing.id)
            self._db.add(lineage)
        lineage.source_id = source.id
        lineage.raw_result_id = raw.id
        lineage.provider = receipt.provider
        lineage.source = receipt.source
        lineage.authority = observation.lineage.authority.value
        lineage.raw_contract_version = observation.lineage.raw_contract_version
        lineage.event_at = observation.lineage.event_at
        lineage.received_at = _as_utc(
            observation.lineage.received_at or receipt.fetched_at
        )
        lineage.fetched_at = _as_utc(receipt.fetched_at)
        lineage.finalization = observation.finalization.value
        lineage.source_interval = "1m"
        lineage.calculation_version = None
        lineage.component_raw_result_ids_json = None
        lineage.updated_at = utc_now()
        return unchanged

    def persist_bar_acquisition(
        self,
        requirement: DataRequirementV2,
        acquisition: BarAcquisitionResult,
    ) -> PersistenceSummary:
        if not isinstance(requirement.request, BarCapabilityRequest) or (
            requirement.request.capability_id != TW_INTRADAY_BARS_CAPABILITY_ID
        ):
            raise ValueError("intraday transaction capability mismatch")
        if not acquisition.summary.attempted:
            raise ValueError("transaction cannot persist non-attempted acquisition")
        written = unchanged = 0
        raw_ids: list[int] = []
        stored: dict[tuple[str, str], tuple[SourceRegistry, RawFetchResult, RawFetchReceiptV1]] = {}
        try:
            for receipt in acquisition.receipts:
                key = (receipt.provider, receipt.source)
                if key in stored:
                    raise ValueError("duplicate intraday provider/source receipt")
                source = self._source(receipt)
                raw = self._raw(source, receipt)
                stored[key] = (source, raw, receipt)
                raw_ids.append(raw.id)
            for observation in acquisition.observations:
                matched = stored.get(
                    (observation.lineage.provider, observation.lineage.source)
                )
                if matched is None:
                    raise ValueError("intraday observation has no raw receipt")
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
            raw_result_ids=tuple(raw_ids),
            limitations=acquisition.summary.limitations,
        )


__all__ = ["TaiwanIntradayBarTransaction"]
