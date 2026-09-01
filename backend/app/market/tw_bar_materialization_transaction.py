"""Atomic persistence for Taiwan Bars derived from existing canonical evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json

from sqlalchemy.orm import Session

from app.db.models import (
    MarketIntradayBar,
    MarketIntradayBarLineage,
    MarketDailyPrice,
    MarketDailyPriceLineage,
    RawFetchResult,
    SourceRegistry,
    utc_now,
)
from app.market.tw_bar_contracts import (
    TAIWAN_DAILY_MATERIALIZATION_VERSION,
    TAIWAN_INDEX_MINUTE_MATERIALIZATION_VERSION,
    TAIWAN_INDEX_MINUTE_RAW_CONTRACT,
    TPEX_DERIVED_DAILY_KIND,
    TPEX_DERIVED_DAILY_SOURCE,
    TPEX_DERIVED_DAILY_PROVIDER,
    TPEX_OFFICIAL_5S_COMPONENT_SOURCE,
    TPEX_OFFICIAL_5S_PARSER_VERSION,
)
from app.market.tw_bar_materializer import (
    TaiwanMaterializedBarCandidate,
    TaiwanMaterializedDailyCandidate,
    materialize_tpex_completed_daily_candidate,
)
from app.market.tw_current_market_capabilities import (
    TW_CURRENT_INDEX_CAPABILITY_ID,
    current_source_binding,
)
from app.market.tw_instrument import resolve_taiwan_instrument
from app.market_data.contracts import BarObservation, InstrumentType, Market
from app.market_data.integration_contracts import PersistenceSummary, RawFetchReceiptV1


class TaiwanBarMaterializationTransaction:
    def __init__(self, db: Session) -> None:
        self._db = db

    def _validate(self, candidate: TaiwanMaterializedBarCandidate) -> SourceRegistry:
        observation = candidate.observation
        if (
            observation.instrument.market is not Market.TW
            or observation.instrument.instrument_type is not InstrumentType.INDEX
            or observation.interval != "1m"
        ):
            raise ValueError("TW_INDEX_BASE_1M_MATERIALIZATION_REQUIRED")
        if resolve_taiwan_instrument(self._db, observation.instrument.symbol) != (
            observation.instrument
        ):
            raise ValueError("materialized bar instrument identity mismatch")
        binding = current_source_binding(
            provider=observation.lineage.provider,
            source=observation.lineage.source,
            capability_id=TW_CURRENT_INDEX_CAPABILITY_ID,
        )
        if binding is None:
            raise ValueError("unsupported current-index materialization source")
        if observation.lineage.authority is not binding.descriptor.authority:
            raise ValueError("materialized bar authority mismatch")
        if observation.lineage.raw_contract_version != TAIWAN_INDEX_MINUTE_RAW_CONTRACT:
            raise ValueError("materialized bar contract mismatch")
        source = self._db.get(SourceRegistry, candidate.source_id)
        if source is None or source.source_name != observation.lineage.source:
            raise ValueError("materialized bar source registry mismatch")
        raw_rows = (
            self._db.query(RawFetchResult)
            .filter(RawFetchResult.id.in_(candidate.component_raw_result_ids))
            .all()
        )
        if not candidate.component_raw_result_ids or len(raw_rows) != len(
            candidate.component_raw_result_ids
        ):
            raise ValueError("materialized bar component evidence missing")
        if any(
            raw.source_id != source.id
            or raw.parser_version != binding.parser_version
            or not raw.content_hash
            for raw in raw_rows
        ):
            raise ValueError("materialized bar component lineage mismatch")
        if set(candidate.component_content_hashes) != {
            str(raw.content_hash) for raw in raw_rows
        }:
            raise ValueError("materialized bar component digest mismatch")
        return source

    def _upsert(self, candidate: TaiwanMaterializedBarCandidate) -> bool:
        observation = candidate.observation
        source = self._validate(candidate)
        existing = (
            self._db.query(MarketIntradayBar)
            .filter(MarketIntradayBar.source_id == source.id)
            .filter(MarketIntradayBar.canonical_market == Market.TW.value)
            .filter(MarketIntradayBar.venue == observation.instrument.venue)
            .filter(MarketIntradayBar.instrument_type == InstrumentType.INDEX.value)
            .filter(MarketIntradayBar.stock_id == observation.instrument.symbol)
            .filter(MarketIntradayBar.interval == "1m")
            .filter(MarketIntradayBar.bar_time == observation.start_at)
            .first()
        )
        incoming = {
            "source_id": source.id,
            "provider": observation.lineage.provider,
            "stock_id": observation.instrument.symbol,
            "market": observation.instrument.venue,
            "canonical_market": Market.TW.value,
            "venue": observation.instrument.venue,
            "instrument_type": InstrumentType.INDEX.value,
            "symbol": observation.instrument.symbol,
            "interval": "1m",
            "bar_time": observation.start_at,
            "open_price": float(observation.open_price),
            "high_price": float(observation.high_price),
            "low_price": float(observation.low_price),
            "close_price": float(observation.close_price),
            "trade_volume": None,
            "trade_value": None,
            "source": observation.lineage.source,
            "source_url": None,
        }
        unchanged = False
        if existing is None:
            existing = MarketIntradayBar(**incoming)
            self._db.add(existing)
            self._db.flush()
        else:
            unchanged = all(getattr(existing, key) == value for key, value in incoming.items())
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
        lineage.raw_result_id = None
        lineage.provider = observation.lineage.provider
        lineage.source = observation.lineage.source
        lineage.authority = observation.lineage.authority.value
        lineage.raw_contract_version = TAIWAN_INDEX_MINUTE_RAW_CONTRACT
        lineage.event_at = observation.lineage.event_at
        lineage.received_at = (
            observation.lineage.received_at or observation.lineage.event_at
        ).astimezone(timezone.utc)
        lineage.fetched_at = (
            observation.lineage.fetched_at or observation.lineage.event_at
        ).astimezone(timezone.utc)
        lineage.finalization = observation.finalization.value
        lineage.source_interval = "event"
        lineage.calculation_version = TAIWAN_INDEX_MINUTE_MATERIALIZATION_VERSION
        lineage.component_raw_result_ids_json = json.dumps(
            candidate.component_raw_result_ids,
            separators=(",", ":"),
        )
        lineage.updated_at = utc_now()
        return unchanged

    def persist_materialized_bars(
        self,
        candidates: tuple[TaiwanMaterializedBarCandidate, ...],
    ) -> PersistenceSummary:
        written = unchanged = 0
        try:
            for candidate in candidates:
                if self._upsert(candidate):
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
            receipts_written=0,
            observations_written=written,
            observations_unchanged=unchanged,
            raw_result_ids=(),
            limitations=(),
        )

    def _daily_source(self) -> SourceRegistry:
        source = (
            self._db.query(SourceRegistry)
            .filter(SourceRegistry.source_name == TPEX_DERIVED_DAILY_SOURCE)
            .first()
        )
        if source is None:
            source = SourceRegistry(
                source_name=TPEX_DERIVED_DAILY_SOURCE,
                source_type="materializer",
                category="market_data",
                enabled=True,
                priority=10,
                parser_type=TAIWAN_DAILY_MATERIALIZATION_VERSION,
                auth_type="none",
                reliability_level="official",
            )
            self._db.add(source)
            self._db.flush()
        return source

    def persist_materialized_daily_bar(
        self,
        candidate: TaiwanMaterializedDailyCandidate,
    ) -> PersistenceSummary:
        observation = candidate.observation
        if (
            observation.instrument.symbol != "TPEX"
            or observation.instrument.instrument_type is not InstrumentType.INDEX
            or observation.interval != "1d"
            or observation.finalization.value not in {"final", "corrected"}
            or observation.lineage.authority.value != "derived"
            or candidate.source_interval != "5s"
        ):
            raise ValueError("TPEX_COMPLETED_DERIVED_DAILY_REQUIRED")
        if resolve_taiwan_instrument(self._db, "TPEX") != observation.instrument:
            raise ValueError("TPEX daily instrument identity mismatch")
        raw_rows = (
            self._db.query(RawFetchResult)
            .filter(RawFetchResult.id.in_(candidate.component_raw_result_ids))
            .all()
        )
        if not candidate.component_raw_result_ids or len(raw_rows) != len(
            candidate.component_raw_result_ids
        ):
            raise ValueError("TPEX daily component evidence missing")
        if set(candidate.component_content_hashes) != {
            str(item.content_hash) for item in raw_rows if item.content_hash
        }:
            raise ValueError("TPEX daily component content hash mismatch")
        source_ids = {item.source_id for item in raw_rows}
        component_sources = (
            self._db.query(SourceRegistry)
            .filter(SourceRegistry.id.in_(source_ids))
            .all()
        )
        if (
            len(component_sources) != 1
            or component_sources[0].source_name
            != TPEX_OFFICIAL_5S_COMPONENT_SOURCE
            or str(component_sources[0].reliability_level or "").strip().lower()
            != "official"
            or any(
                item.parser_version != TPEX_OFFICIAL_5S_PARSER_VERSION
                for item in raw_rows
            )
        ):
            raise ValueError("TPEX daily component source qualification failed")
        source = self._daily_source()
        trade_date = observation.start_at.date()
        row = (
            self._db.query(MarketDailyPrice)
            .filter(MarketDailyPrice.source_id == source.id)
            .filter(MarketDailyPrice.stock_id == "TPEX")
            .filter(MarketDailyPrice.trade_date == trade_date)
            .first()
        )
        incoming = {
            "source_id": source.id,
            "raw_result_id": None,
            "trade_date": trade_date,
            "stock_id": "TPEX",
            "stock_name": "櫃買指數",
            "canonical_market": Market.TW.value,
            "venue": "TPEX",
            "instrument_type": InstrumentType.INDEX.value,
            "trade_volume": None,
            "trade_value": None,
            "open_price": float(observation.open_price),
            "high_price": float(observation.high_price),
            "low_price": float(observation.low_price),
            "close_price": float(observation.close_price),
            "price_change": None,
            "transaction_count": None,
            "authority": "derived",
            "finalization": observation.finalization.value,
            "official": False,
            "release_status": "pending_release",
            "reconciliation_status": "pending",
            "derivation_kind": TPEX_DERIVED_DAILY_KIND,
            "aggregation_version": TAIWAN_DAILY_MATERIALIZATION_VERSION,
        }
        unchanged = False
        try:
            if row is None:
                row = MarketDailyPrice(**incoming)
                self._db.add(row)
                self._db.flush()
            else:
                unchanged = all(
                    getattr(row, key) == value for key, value in incoming.items()
                )
                for key, value in incoming.items():
                    setattr(row, key, value)
                row.updated_at = utc_now()
            lineage = (
                self._db.query(MarketDailyPriceLineage)
                .filter(MarketDailyPriceLineage.daily_price_id == row.id)
                .first()
            )
            if lineage is None:
                lineage = MarketDailyPriceLineage(daily_price_id=row.id)
                self._db.add(lineage)
            lineage.raw_result_id = None
            lineage.evidence_kind = "materialized"
            lineage.source_interval = candidate.source_interval
            lineage.materialization_version = TAIWAN_DAILY_MATERIALIZATION_VERSION
            lineage.component_raw_result_ids_json = json.dumps(
                candidate.component_raw_result_ids,
                separators=(",", ":"),
            )
            lineage.component_content_hashes_json = json.dumps(
                candidate.component_content_hashes,
                separators=(",", ":"),
            )
            lineage.lineage_digest = sha256(
                json.dumps(
                    {
                        "source": TPEX_DERIVED_DAILY_SOURCE,
                        "version": TAIWAN_DAILY_MATERIALIZATION_VERSION,
                        "component_content_hashes": candidate.component_content_hashes,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            lineage.updated_at = utc_now()
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise
        return PersistenceSummary(
            attempted=True,
            committed=True,
            receipts_written=0,
            observations_written=0 if unchanged else 1,
            observations_unchanged=1 if unchanged else 0,
            raw_result_ids=(),
            limitations=(),
        )

    def persist_tpex_completed_daily_acquisition(
        self,
        *,
        receipt: RawFetchReceiptV1,
        components: tuple[BarObservation, ...],
        as_of: datetime,
    ) -> PersistenceSummary:
        """Atomically persist one real 5s receipt and its derived daily candidate."""

        if (
            receipt.provider != TPEX_DERIVED_DAILY_PROVIDER
            or receipt.source != TPEX_OFFICIAL_5S_COMPONENT_SOURCE
            or receipt.parser_version != TPEX_OFFICIAL_5S_PARSER_VERSION
            or receipt.error_message is not None
        ):
            raise ValueError("TPEX official 5s receipt identity mismatch")
        source = (
            self._db.query(SourceRegistry)
            .filter(SourceRegistry.source_name == TPEX_OFFICIAL_5S_COMPONENT_SOURCE)
            .one_or_none()
        )
        try:
            if source is None:
                source = SourceRegistry(
                    source_name=TPEX_OFFICIAL_5S_COMPONENT_SOURCE,
                    source_type="api",
                    category="market_data",
                    endpoint_url=receipt.url,
                    enabled=True,
                    priority=5,
                    parser_type=TPEX_OFFICIAL_5S_PARSER_VERSION,
                    auth_type="none",
                    reliability_level="official",
                )
                self._db.add(source)
                self._db.flush()
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
                error_message=None,
            )
            self._db.add(raw)
            self._db.flush()
            candidate = materialize_tpex_completed_daily_candidate(
                components,
                component_raw_result_ids=(raw.id,),
                component_content_hashes=(receipt.content_hash,),
                coverage_complete=True,
                as_of=as_of,
            )
            result = self.persist_materialized_daily_bar(candidate)
        except Exception:
            self._db.rollback()
            raise
        return result.model_copy(
            update={
                "receipts_written": 1,
                "raw_result_ids": (raw.id,),
            }
        )


__all__ = ["TaiwanBarMaterializationTransaction"]
