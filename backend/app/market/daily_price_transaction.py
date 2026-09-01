"""Atomic persistence owner for official Taiwan daily acquisitions."""

from __future__ import annotations

import json
from datetime import timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.db.models import (
    DataQualityCheck,
    MarketDailyPrice,
    MarketDailyPriceLineage,
    RawFetchResult,
    SourceRegistry,
)
from app.market.tw_bar_contracts import TAIEX_OFFICIAL_DAILY_SOURCE
from app.market_data.contracts import BarFinalization, BarObservation, Market
from app.market_data.gateway import BarAcquisitionResult
from app.market_data.integration_contracts import (
    DataRequirementV2,
    PersistenceSummary,
    RawFetchReceiptV1,
    RefreshRequirementV1,
)
from app.sources.defaults import (
    TPEX_DAILY_QUOTES_SOURCE_NAME,
    TWSE_DAILY_TRADING_SOURCE_NAME,
    TWSE_RWD_DAILY_TRADING_SOURCE_NAME,
)


TAIWAN_TZ = ZoneInfo("Asia/Taipei")


def _source_defaults(receipt: RawFetchReceiptV1) -> dict[str, object]:
    if receipt.source not in {
        TWSE_DAILY_TRADING_SOURCE_NAME,
        TWSE_RWD_DAILY_TRADING_SOURCE_NAME,
        TPEX_DAILY_QUOTES_SOURCE_NAME,
        TAIEX_OFFICIAL_DAILY_SOURCE,
    }:
        raise ValueError(f"unsupported Taiwan official daily source: {receipt.source}")
    return {
        "source_name": receipt.source,
        "source_type": "api",
        "category": "market_data",
        "endpoint_url": receipt.url,
        "enabled": True,
        "priority": (
            5
            if receipt.source == TWSE_RWD_DAILY_TRADING_SOURCE_NAME
            else 20
            if receipt.source == TWSE_DAILY_TRADING_SOURCE_NAME
            else 10
        ),
        "parser_type": receipt.parser_version,
        "auth_type": "none",
        "reliability_level": "official",
    }


def _decimal_equal(current: float | int | None, incoming: Decimal | None) -> bool:
    if current is None or incoming is None:
        return current is None and incoming is None
    return Decimal(str(current)) == incoming


def _integer(value: Decimal | None) -> int | None:
    if value is None:
        return None
    if value != value.to_integral_value():
        raise ValueError("canonical daily integer field contains a fractional value")
    return int(value)


class TaiwanOfficialDailyTransaction:
    """Persist receipts and canonical rows in one explicit SQLAlchemy transaction."""

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
        if source.source_name != receipt.source:
            raise ValueError("receipt source identity mismatch")
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
        source.last_success_at = fetched_at if receipt.error_message is None else source.last_success_at
        if receipt.error_message is None:
            source.last_error_at = None
            source.last_error_message = None
        else:
            source.last_error_at = fetched_at
            source.last_error_message = receipt.error_message
        return raw

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
            message = "Official daily receipt persisted with no accepted target observation."
        elif limitations:
            quality_status = "warning"
            message = "Official daily receipt persisted with explicit limitations."
        else:
            quality_status = "valid"
            message = "Official daily receipt and canonical target observation are valid."
        duplicate = (
            self._db.query(RawFetchResult.id)
            .filter(RawFetchResult.source_id == source.id)
            .filter(RawFetchResult.content_hash == receipt.content_hash)
            .filter(RawFetchResult.id != raw.id)
            .first()
            is not None
        )
        self._db.add(
            DataQualityCheck(
                source_id=source.id,
                raw_result_id=raw.id,
                status=quality_status,
                check_name="data_core_official_daily_receipt",
                message=message,
                row_count=observation_count,
                is_duplicate=duplicate,
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

    def _upsert_bar(
        self,
        observation: BarObservation,
        *,
        source: SourceRegistry,
        raw: RawFetchResult,
    ) -> bool:
        if observation.instrument.market is not Market.TW:
            raise ValueError("Taiwan daily transaction requires market=TW")
        if observation.interval != "1d":
            raise ValueError("Taiwan daily transaction requires interval=1d")
        if observation.finalization not in {
            BarFinalization.FINAL,
            BarFinalization.CORRECTED,
        }:
            raise ValueError("Taiwan daily transaction requires final/corrected bars")
        if not observation.instrument.symbol.strip():
            raise ValueError("Taiwan daily observation requires instrument symbol")
        if not observation.instrument.venue:
            raise ValueError("Taiwan daily observation requires instrument venue")
        trade_date = observation.end_at.astimezone(TAIWAN_TZ).date()
        volume = _integer(observation.volume.value) if observation.volume else None
        trade_value = _integer(observation.turnover_value)
        row = (
            self._db.query(MarketDailyPrice)
            .filter(MarketDailyPrice.source_id == source.id)
            .filter(MarketDailyPrice.stock_id == observation.instrument.symbol)
            .filter(MarketDailyPrice.trade_date == trade_date)
            .first()
        )
        incoming = {
            "source_id": source.id,
            "raw_result_id": raw.id,
            "trade_date": trade_date,
            "stock_id": observation.instrument.symbol,
            "stock_name": observation.instrument_name,
            "canonical_market": Market.TW.value,
            "venue": observation.instrument.venue,
            "instrument_type": observation.instrument.instrument_type.value,
            "trade_volume": volume,
            "trade_value": trade_value,
            "open_price": observation.open_price,
            "high_price": observation.high_price,
            "low_price": observation.low_price,
            "close_price": observation.close_price,
            "transaction_count": observation.trade_count,
            "price_change": observation.price_change,
            "authority": observation.lineage.authority.value,
            "finalization": observation.finalization.value,
            "official": observation.lineage.authority.value == "exchange",
            "release_status": "released",
            "reconciliation_status": "pending",
            "derivation_kind": None,
            "aggregation_version": None,
        }
        unchanged = False
        if row is None:
            row = MarketDailyPrice(
                **{
                    **incoming,
                    "open_price": float(observation.open_price),
                    "high_price": float(observation.high_price),
                    "low_price": float(observation.low_price),
                    "close_price": float(observation.close_price),
                    "price_change": (
                        float(observation.price_change)
                        if observation.price_change is not None
                        else None
                    ),
                },
            )
            self._db.add(row)
        else:
            unchanged = (
                (row.stock_name == incoming["stock_name"] or incoming["stock_name"] is None)
                and row.trade_volume == volume
                and row.trade_value == trade_value
                and _decimal_equal(row.open_price, observation.open_price)
                and _decimal_equal(row.high_price, observation.high_price)
                and _decimal_equal(row.low_price, observation.low_price)
                and _decimal_equal(row.close_price, observation.close_price)
                and row.transaction_count == observation.trade_count
                and _decimal_equal(row.price_change, observation.price_change)
            )
            for key, value in incoming.items():
                if key == "stock_name" and value is None:
                    continue
                setattr(row, key, value)
            row.open_price = float(observation.open_price)
            row.high_price = float(observation.high_price)
            row.low_price = float(observation.low_price)
            row.close_price = float(observation.close_price)
            row.price_change = (
                float(observation.price_change)
                if observation.price_change is not None
                else None
            )
        self._db.flush()
        lineage = (
            self._db.query(MarketDailyPriceLineage)
            .filter(MarketDailyPriceLineage.daily_price_id == row.id)
            .first()
        )
        if lineage is None:
            lineage = MarketDailyPriceLineage(daily_price_id=row.id)
            self._db.add(lineage)
        lineage.raw_result_id = raw.id
        lineage.evidence_kind = "acquired"
        lineage.source_interval = "1d"
        lineage.materialization_version = None
        lineage.component_raw_result_ids_json = None
        lineage.component_content_hashes_json = None
        lineage.lineage_digest = observation.lineage.content_hash
        return unchanged

    def persist_bar_acquisition(
        self,
        _requirement: DataRequirementV2 | RefreshRequirementV1,
        acquisition: BarAcquisitionResult,
    ) -> PersistenceSummary:
        if not acquisition.summary.attempted:
            raise ValueError("transaction cannot persist a non-attempted acquisition")
        receipts_by_source: dict[tuple[str, str], tuple[SourceRegistry, RawFetchResult]] = {}
        raw_ids: list[int] = []
        written = 0
        unchanged = 0
        try:
            for receipt in acquisition.receipts:
                key = (receipt.provider, receipt.source)
                if key in receipts_by_source:
                    raise ValueError("acquisition contains duplicate provider/source receipts")
                source = self._source(receipt)
                raw = self._raw_receipt(source, receipt)
                receipts_by_source[key] = (source, raw)
                raw_ids.append(raw.id)

            observations_by_source: dict[tuple[str, str], int] = {}
            for observation in acquisition.observations:
                key = (
                    observation.lineage.provider,
                    observation.lineage.source,
                )
                source_raw = receipts_by_source.get(key)
                if source_raw is None:
                    raise ValueError(
                        "canonical observation has no matching raw provider/source receipt"
                    )
                source, raw = source_raw
                was_unchanged = self._upsert_bar(
                    observation,
                    source=source,
                    raw=raw,
                )
                observations_by_source[key] = observations_by_source.get(key, 0) + 1
                if was_unchanged:
                    unchanged += 1
                else:
                    written += 1

            for receipt in acquisition.receipts:
                key = (receipt.provider, receipt.source)
                source, raw = receipts_by_source[key]
                self._quality_check(
                    source=source,
                    raw=raw,
                    receipt=receipt,
                    observation_count=observations_by_source.get(key, 0),
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


__all__ = ["TaiwanOfficialDailyTransaction"]
