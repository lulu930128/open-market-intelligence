"""Atomic raw-receipt and canonical-row persistence for Taiwan index data."""

from __future__ import annotations

import json
from datetime import timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import (
    DataQualityCheck,
    MarketIndexDailyStat,
    RawFetchResult,
    SourceRegistry,
)
from app.market.official_index_contract import (
    TPEX_INDEX_SOURCE_NAME,
    TWSE_INDEX_SOURCE_NAME,
    TW_INDEX_DATASET_ID,
)
from app.market_data.contracts import (
    BarFinalization,
    Market,
    MarketIndexObservation,
    QuantityUnit,
)
from app.market_data.gateway import MarketIndexAcquisitionResult
from app.market_data.integration_contracts import (
    DatasetTarget,
    PersistenceSummary,
    RawFetchReceiptV1,
    RefreshRequirementV1,
)


def _source_defaults(receipt: RawFetchReceiptV1) -> dict[str, object]:
    if receipt.source not in {TWSE_INDEX_SOURCE_NAME, TPEX_INDEX_SOURCE_NAME}:
        raise ValueError(f"unsupported Taiwan official index source: {receipt.source}")
    return {
        "source_name": receipt.source,
        "source_type": "api",
        "category": "market_data",
        "endpoint_url": receipt.url,
        "enabled": True,
        "priority": 10,
        "parser_type": receipt.parser_version,
        "auth_type": "none",
        "reliability_level": "official",
    }


def _decimal_equal(current: float | int | None, incoming: Decimal | None) -> bool:
    if current is None or incoming is None:
        return current is None and incoming is None
    return Decimal(str(current)) == incoming


class TaiwanOfficialIndexTransaction:
    def __init__(self, db: Session) -> None:
        self._db = db

    def _source(self, receipt: RawFetchReceiptV1) -> SourceRegistry:
        source = (
            self._db.query(SourceRegistry)
            .filter(SourceRegistry.source_name == receipt.source)
            .first()
        )
        if source is None:
            source = SourceRegistry(**_source_defaults(receipt))
            self._db.add(source)
            self._db.flush()
        return source

    def _raw_receipt(
        self,
        source: SourceRegistry,
        receipt: RawFetchReceiptV1,
    ) -> RawFetchResult:
        fetched_at = receipt.fetched_at.astimezone(timezone.utc)
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
        observation: MarketIndexObservation,
        *,
        source: SourceRegistry,
        raw: RawFetchResult,
        receipt: RawFetchReceiptV1,
    ) -> bool:
        if observation.market is not Market.TW:
            raise ValueError("Taiwan index transaction requires market=TW")
        if observation.finalization not in {
            BarFinalization.FINAL,
            BarFinalization.CORRECTED,
        }:
            raise ValueError("Taiwan index transaction requires final evidence")
        if not observation.official or observation.provisional:
            raise ValueError("Taiwan index transaction requires official final evidence")
        trade_volume = None
        if observation.trade_volume is not None:
            if observation.trade_volume.unit is not QuantityUnit.SHARE:
                raise ValueError("Taiwan index trade volume must use share units")
            value = observation.trade_volume.value
            if value != value.to_integral_value():
                raise ValueError("Taiwan index trade volume must be an integer")
            trade_volume = int(value)
        trade_value = None
        if observation.trade_value is not None:
            if observation.trade_value != observation.trade_value.to_integral_value():
                raise ValueError("Taiwan index trade value must be an integer")
            trade_value = int(observation.trade_value)
        row = (
            self._db.query(MarketIndexDailyStat)
            .filter(MarketIndexDailyStat.index_id == observation.index_id)
            .filter(MarketIndexDailyStat.trade_date == observation.trade_date)
            .first()
        )
        incoming = {
            "market": observation.venue,
            "source_id": source.id,
            "raw_result_id": raw.id,
            "trade_volume": trade_volume,
            "trade_value": trade_value,
            "transaction_count": observation.transaction_count,
            "close_value": float(observation.close_value),
            "price_change": float(observation.price_change),
            "source": receipt.provider,
            "source_url": receipt.url,
        }
        unchanged = False
        if row is None:
            row = MarketIndexDailyStat(
                index_id=observation.index_id,
                trade_date=observation.trade_date,
                **incoming,
            )
            self._db.add(row)
        else:
            unchanged = (
                row.market == incoming["market"]
                and row.trade_volume == trade_volume
                and row.trade_value == trade_value
                and row.transaction_count == observation.transaction_count
                and _decimal_equal(row.close_value, observation.close_value)
                and _decimal_equal(row.price_change, observation.price_change)
                and row.source == receipt.provider
                and row.source_url == receipt.url
            )
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
        limitations: tuple[str, ...],
    ) -> None:
        if receipt.error_message:
            quality_status = "error"
            message = receipt.error_message
        elif observation_count == 0:
            quality_status = "warning"
            message = "Official index receipt has no accepted target observation."
        elif limitations:
            quality_status = "warning"
            message = "Official index receipt has explicit limitations."
        else:
            quality_status = "valid"
            message = "Official index receipt and canonical observation are valid."
        self._db.add(
            DataQualityCheck(
                source_id=source.id,
                raw_result_id=raw.id,
                status=quality_status,
                check_name="data_core_official_index_receipt",
                message=message,
                row_count=observation_count,
                is_duplicate=False,
                detail_json=json.dumps(
                    {
                        "provider": receipt.provider,
                        "resource_id": receipt.resource_id,
                        "parser_version": receipt.parser_version,
                        "limitations": list(limitations),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            )
        )

    def persist_index_acquisition(
        self,
        requirement: RefreshRequirementV1,
        acquisition: MarketIndexAcquisitionResult,
    ) -> PersistenceSummary:
        if requirement.dataset_id != TW_INDEX_DATASET_ID:
            raise ValueError("Taiwan index transaction dataset_id mismatch")
        if not isinstance(requirement.target, DatasetTarget):
            raise ValueError("Taiwan index transaction requires dataset target")
        if not acquisition.summary.attempted:
            raise ValueError("transaction cannot persist a non-attempted acquisition")
        receipts_by_source: dict[
            tuple[str, str], tuple[SourceRegistry, RawFetchResult, RawFetchReceiptV1]
        ] = {}
        raw_ids: list[int] = []
        written = unchanged = 0
        observation_counts: dict[tuple[str, str], int] = {}
        try:
            for receipt in acquisition.receipts:
                key = (receipt.provider, receipt.source)
                if key in receipts_by_source:
                    raise ValueError("duplicate provider/source receipt")
                source = self._source(receipt)
                raw = self._raw_receipt(source, receipt)
                receipts_by_source[key] = (source, raw, receipt)
                raw_ids.append(raw.id)
            for observation in acquisition.observations:
                if observation.index_id != requirement.target.scope_key:
                    raise ValueError("index observation crossed requested dataset scope")
                key = (observation.lineage.provider, observation.lineage.source)
                matched = receipts_by_source.get(key)
                if matched is None:
                    raise ValueError("index observation has no matching raw receipt")
                source, raw, receipt = matched
                was_unchanged = self._upsert(
                    observation,
                    source=source,
                    raw=raw,
                    receipt=receipt,
                )
                observation_counts[key] = observation_counts.get(key, 0) + 1
                if was_unchanged:
                    unchanged += 1
                else:
                    written += 1
            for key, (source, raw, receipt) in receipts_by_source.items():
                self._quality_check(
                    source=source,
                    raw=raw,
                    receipt=receipt,
                    observation_count=observation_counts.get(key, 0),
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


__all__ = ["TaiwanOfficialIndexTransaction"]
