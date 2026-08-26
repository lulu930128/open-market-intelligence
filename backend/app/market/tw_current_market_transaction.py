"""Atomic transaction owner for Taiwan current-session index and breadth."""

from __future__ import annotations

from datetime import datetime, timezone
import json

from sqlalchemy.orm import Session

from app.db.models import (
    RawFetchResult,
    SourceRegistry,
    TaiwanCurrentBreadthSnapshot,
    TaiwanCurrentIndexSnapshot,
    utc_now,
)
from app.market.tw_current_market_capabilities import (
    TW_CURRENT_BREADTH_CAPABILITY_ID,
    TW_CURRENT_INDEX_CAPABILITY_ID,
    current_source_binding,
)
from app.market_data.contracts import (
    MarketBreadthObservation,
    MarketIndexObservation,
    Quantity,
)
from app.market_data.gateway import (
    MarketBreadthAcquisitionResult,
    MarketIndexAcquisitionResult,
)
from app.market_data.integration_contracts import (
    DataRequirementV2,
    DatasetCapabilityRequest,
    DatasetTarget,
    PersistenceSummary,
    RawFetchReceiptV1,
)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("current market lineage timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _integer(quantity: Quantity | None) -> int | None:
    if quantity is None:
        return None
    if quantity.value != quantity.value.to_integral_value():
        raise ValueError("current index volume must be integral")
    return int(quantity.value)


class TaiwanCurrentMarketTransaction:
    def __init__(self, db: Session) -> None:
        self._db = db

    def _source(self, receipt: RawFetchReceiptV1, capability: str) -> SourceRegistry:
        binding = current_source_binding(
            provider=receipt.provider,
            source=receipt.source,
            capability_id=capability,
        )
        if (
            binding is None
            or receipt.resource_id != binding.descriptor.resource_id
            or receipt.parser_version != binding.parser_version
        ):
            raise ValueError("unsupported Taiwan current market receipt identity")
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
                reliability_level=binding.descriptor.authority.value,
            )
            self._db.add(source)
            self._db.flush()
        return source

    def _raw(self, source: SourceRegistry, receipt: RawFetchReceiptV1) -> RawFetchResult:
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
    def _validate_identity(
        requirement: DataRequirementV2,
        observation: MarketIndexObservation | MarketBreadthObservation,
        receipt: RawFetchReceiptV1,
        capability: str,
    ) -> None:
        if not isinstance(requirement.target, DatasetTarget):
            raise ValueError("current market transaction requires dataset target")
        if requirement.request.capability_id != capability:
            raise ValueError("current market transaction capability mismatch")
        if (
            observation.lineage.provider != receipt.provider
            or observation.lineage.source != receipt.source
            or observation.lineage.content_hash != receipt.content_hash
            or observation.lineage.raw_contract_version != receipt.parser_version
        ):
            raise ValueError("current market observation raw identity mismatch")
        if observation.lineage.event_at is None:
            raise ValueError("current market observation requires event_at")

    def _upsert_index(
        self,
        requirement: DataRequirementV2,
        observation: MarketIndexObservation,
        *,
        source: SourceRegistry,
        raw: RawFetchResult,
        receipt: RawFetchReceiptV1,
    ) -> bool:
        self._validate_identity(
            requirement,
            observation,
            receipt,
            TW_CURRENT_INDEX_CAPABILITY_ID,
        )
        if observation.index_id != requirement.target.scope_key:
            raise ValueError("current index observation crossed target")
        event_at = observation.lineage.event_at
        existing = (
            self._db.query(TaiwanCurrentIndexSnapshot)
            .filter(TaiwanCurrentIndexSnapshot.provider == receipt.provider)
            .filter(TaiwanCurrentIndexSnapshot.source == receipt.source)
            .filter(TaiwanCurrentIndexSnapshot.index_id == observation.index_id)
            .filter(TaiwanCurrentIndexSnapshot.event_at == event_at)
            .first()
        )
        values = {
            "source_id": source.id,
            "raw_result_id": raw.id,
            "provider": receipt.provider,
            "source": receipt.source,
            "authority": observation.lineage.authority.value,
            "raw_contract_version": observation.lineage.raw_contract_version,
            "index_id": observation.index_id,
            "venue": observation.venue,
            "trade_date": observation.trade_date,
            "event_at": event_at,
            "received_at": _as_utc(observation.lineage.received_at or receipt.fetched_at),
            "fetched_at": _as_utc(receipt.fetched_at),
            "session": observation.session.value,
            "close_value": float(observation.close_value),
            "price_change": float(observation.price_change),
            "trade_volume": _integer(observation.trade_volume),
            "trade_volume_unit": (
                observation.trade_volume.unit.value
                if observation.trade_volume is not None
                else None
            ),
            "trade_value": (
                int(observation.trade_value)
                if observation.trade_value is not None
                else None
            ),
            "currency": observation.currency,
            "transaction_count": observation.transaction_count,
            "observation_state": observation.state.value,
            "value_semantics": observation.value_semantics,
            "finalization": observation.finalization.value,
            "official": observation.official,
            "provisional": observation.provisional,
        }
        unchanged = existing is not None and all(
            getattr(existing, key) == value
            for key, value in values.items()
            if key not in {"raw_result_id", "fetched_at", "received_at"}
        )
        if existing is None:
            self._db.add(TaiwanCurrentIndexSnapshot(**values))
        else:
            for key, value in values.items():
                setattr(existing, key, value)
            existing.updated_at = utc_now()
        return unchanged

    def _upsert_breadth(
        self,
        requirement: DataRequirementV2,
        observation: MarketBreadthObservation,
        *,
        source: SourceRegistry,
        raw: RawFetchResult,
        receipt: RawFetchReceiptV1,
    ) -> bool:
        self._validate_identity(
            requirement,
            observation,
            receipt,
            TW_CURRENT_BREADTH_CAPABILITY_ID,
        )
        if observation.venue != requirement.target.scope_key:
            raise ValueError("current breadth observation crossed target")
        event_at = observation.lineage.event_at
        existing = (
            self._db.query(TaiwanCurrentBreadthSnapshot)
            .filter(TaiwanCurrentBreadthSnapshot.provider == receipt.provider)
            .filter(TaiwanCurrentBreadthSnapshot.source == receipt.source)
            .filter(TaiwanCurrentBreadthSnapshot.venue == observation.venue)
            .filter(TaiwanCurrentBreadthSnapshot.event_at == event_at)
            .first()
        )
        decision_usable = (
            observation.state.value == "available"
            and observation.unknown_count == 0
            and observation.missing_count == 0
        )
        values = {
            "source_id": source.id,
            "raw_result_id": raw.id,
            "provider": receipt.provider,
            "source": receipt.source,
            "authority": observation.lineage.authority.value,
            "raw_contract_version": observation.lineage.raw_contract_version,
            "venue": observation.venue,
            "trade_date": observation.trade_date,
            "event_at": event_at,
            "received_at": _as_utc(observation.lineage.received_at or receipt.fetched_at),
            "fetched_at": _as_utc(receipt.fetched_at),
            "session": observation.session.value,
            "scope": observation.scope,
            "universe_source": observation.universe_source,
            "universe_count": observation.universe_count,
            "advance_count": observation.advance_count,
            "decline_count": observation.decline_count,
            "unchanged_count": observation.unchanged_count,
            "received_unclassified_count": observation.unknown_count,
            "not_received_count": observation.missing_count,
            "trade_value": (
                int(observation.trade_value)
                if observation.trade_value is not None
                else None
            ),
            "currency": observation.currency,
            "observation_state": observation.state.value,
            "price_semantics": observation.price_semantics,
            "official": observation.official,
            "provisional": observation.provisional,
            "decision_usable": decision_usable,
            "limitations_json": json.dumps(
                [
                    code
                    for condition, code in (
                        (observation.unknown_count > 0, "RECEIVED_UNCLASSIFIED"),
                        (observation.missing_count > 0, "UNIVERSE_NOT_RECEIVED"),
                        (observation.trade_value is None, "TRADE_VALUE_UNAVAILABLE"),
                    )
                    if condition
                ]
            ),
        }
        unchanged = existing is not None and all(
            getattr(existing, key) == value
            for key, value in values.items()
            if key not in {"raw_result_id", "fetched_at", "received_at"}
        )
        if existing is None:
            self._db.add(TaiwanCurrentBreadthSnapshot(**values))
        else:
            for key, value in values.items():
                setattr(existing, key, value)
            existing.updated_at = utc_now()
        return unchanged

    def _persist(
        self,
        requirement: DataRequirementV2,
        acquisition: MarketIndexAcquisitionResult | MarketBreadthAcquisitionResult,
        *,
        capability: str,
    ) -> PersistenceSummary:
        if not isinstance(requirement.request, DatasetCapabilityRequest):
            raise ValueError("current market transaction requires dataset capability")
        if requirement.request.capability_id != capability:
            raise ValueError("current market transaction capability mismatch")
        if not acquisition.summary.attempted:
            raise ValueError("transaction cannot persist non-attempted acquisition")
        stored: dict[tuple[str, str], tuple[SourceRegistry, RawFetchResult, RawFetchReceiptV1]] = {}
        raw_ids: list[int] = []
        written = unchanged = 0
        try:
            for receipt in acquisition.receipts:
                key = (receipt.provider, receipt.source)
                if key in stored:
                    raise ValueError("duplicate current market provider/source receipt")
                source = self._source(receipt, capability)
                raw = self._raw(source, receipt)
                stored[key] = (source, raw, receipt)
                raw_ids.append(raw.id)
            for observation in acquisition.observations:
                matched = stored.get(
                    (observation.lineage.provider, observation.lineage.source)
                )
                if matched is None:
                    raise ValueError("current market observation has no raw receipt")
                source, raw, receipt = matched
                is_unchanged = (
                    self._upsert_index(
                        requirement,
                        observation,
                        source=source,
                        raw=raw,
                        receipt=receipt,
                    )
                    if isinstance(observation, MarketIndexObservation)
                    else self._upsert_breadth(
                        requirement,
                        observation,
                        source=source,
                        raw=raw,
                        receipt=receipt,
                    )
                )
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
            receipts_written=len(acquisition.receipts),
            observations_written=written,
            observations_unchanged=unchanged,
            raw_result_ids=tuple(raw_ids),
            limitations=acquisition.summary.limitations,
        )

    def persist_market_index_acquisition(
        self,
        requirement: DataRequirementV2,
        acquisition: MarketIndexAcquisitionResult,
    ) -> PersistenceSummary:
        return self._persist(
            requirement,
            acquisition,
            capability=TW_CURRENT_INDEX_CAPABILITY_ID,
        )

    def persist_market_breadth_acquisition(
        self,
        requirement: DataRequirementV2,
        acquisition: MarketBreadthAcquisitionResult,
    ) -> PersistenceSummary:
        return self._persist(
            requirement,
            acquisition,
            capability=TW_CURRENT_BREADTH_CAPABILITY_ID,
        )


__all__ = ["TaiwanCurrentMarketTransaction"]
