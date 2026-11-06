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
    TPEX_DERIVED_DAILY_MATERIALIZATION_VERSION,
    TAIWAN_INDEX_MINUTE_MATERIALIZATION_VERSION,
    TAIWAN_INDEX_MINUTE_RAW_CONTRACT,
    TAIWAN_INDEX_OPENING_MINUTE_RAW_CONTRACT,
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
from app.market.tw_current_market_repository import read_qualified_index_opening
from app.market_data.contracts import BarObservation, InstrumentType, Market
from app.market_data.integration_contracts import PersistenceSummary, RawFetchReceiptV1


class TaiwanBarMaterializationTransaction:
    def __init__(self, db: Session) -> None:
        self._db = db

    def _stored_equal(self, stored: object, incoming: object) -> bool:
        # SQLite's DateTime binder preserves the supplied wall-clock fields but
        # drops tzinfo. Match those persisted bytes; do not shift legacy local
        # bar/event clocks or the explicitly UTC receipt clocks.
        if (
            isinstance(stored, datetime)
            and isinstance(incoming, datetime)
            and self._db.get_bind().dialect.name == "sqlite"
        ):
            return stored.replace(tzinfo=None) == incoming.replace(tzinfo=None)
        return stored == incoming

    def _load_raw_metadata(
        self, candidates: tuple[TaiwanMaterializedBarCandidate, ...],
    ) -> dict[int, tuple[int, str | None, str | None]]:
        # Deduplicate only the SELECT binds. Each candidate's original component
        # sequence is still validated at its original point in _upsert.
        ids = tuple(dict.fromkeys(raw_id for candidate in candidates
            for raw_id in candidate.component_raw_result_ids))
        metadata = {}
        for offset in range(0, len(ids), 400):
            rows = (
                self._db.query(RawFetchResult.id, RawFetchResult.source_id,
                    RawFetchResult.parser_version, RawFetchResult.content_hash)
                .filter(RawFetchResult.id.in_(ids[offset:offset + 400]))
                .all()
            )
            metadata.update({row.id: (row.source_id, row.parser_version, row.content_hash) for row in rows})
        return metadata

    def _validate(
        self, candidate: TaiwanMaterializedBarCandidate,
        raw_metadata: dict[int, tuple[int, str | None, str | None]],
    ) -> SourceRegistry:
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
        opening_id = candidate.opening_raw_result_id
        expected_contract = (TAIWAN_INDEX_OPENING_MINUTE_RAW_CONTRACT
            if opening_id is not None else TAIWAN_INDEX_MINUTE_RAW_CONTRACT)
        if observation.lineage.raw_contract_version != expected_contract:
            raise ValueError("materialized bar contract mismatch")
        source = self._db.get(SourceRegistry, candidate.source_id)
        if source is None or source.source_name != observation.lineage.source:
            raise ValueError("materialized bar source registry mismatch")
        raw_rows = {raw_id: raw_metadata[raw_id]
            for raw_id in candidate.component_raw_result_ids if raw_id in raw_metadata}
        if not candidate.component_raw_result_ids or len(raw_rows) != len(
            candidate.component_raw_result_ids
        ):
            raise ValueError("materialized bar component evidence missing")
        if opening_id is not None:
            raw = self._db.get(RawFetchResult, opening_id)
            opening = read_qualified_index_opening(self._db, raw=raw,
                provider=observation.lineage.provider, index_id=observation.instrument.symbol,
                trade_date=observation.start_at.date()) if raw is not None else None
            if (candidate.component_raw_result_ids[0] != opening_id or opening is None
                    or opening.value != observation.open_price
                    or not observation.start_at <= opening.lineage.event_at < observation.end_at
                    or opening.lineage.fetched_at > observation.lineage.fetched_at):
                raise ValueError("materialized bar opening evidence mismatch")
        if any(
            source_id != source.id
            or parser_version != binding.parser_version
            or not content_hash
            for raw_id, (source_id, parser_version, content_hash) in raw_rows.items()
            if raw_id != opening_id
        ):
            raise ValueError("materialized bar component lineage mismatch")
        if set(candidate.component_content_hashes) != {
            str(content_hash) for _, _, content_hash in raw_rows.values()
        }:
            raise ValueError("materialized bar component digest mismatch")
        return source

    def _upsert(
        self,
        candidate: TaiwanMaterializedBarCandidate,
        lineages_by_bar_id: dict[int, MarketIntradayBarLineage],
        source: SourceRegistry,
    ) -> bool:
        observation = candidate.observation
        existing = (
            self._db.query(MarketIntradayBar)
            # The legacy provider key remains a DB constraint, including rows
            # that predate canonical identity. Promote that same row and its
            # lineage instead of inserting a competing source-scoped candidate.
            .filter(MarketIntradayBar.provider == observation.lineage.provider)
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
            unchanged = all(
                self._stored_equal(getattr(existing, key), value)
                for key, value in incoming.items()
            )
            if not unchanged:
                for key, value in incoming.items():
                    setattr(existing, key, value)
                existing.updated_at = utc_now()
        # With production autoflush=False, a query cannot see the lineage added
        # for an earlier candidate sharing this provider key in the same batch.
        lineage = lineages_by_bar_id.get(existing.id)
        if lineage is None:
            lineage = (
                self._db.query(MarketIntradayBarLineage)
                .filter(MarketIntradayBarLineage.bar_id == existing.id)
                .first()
            )
        lineage_incoming = {
            "source_id": source.id,
            "raw_result_id": None,
            "provider": observation.lineage.provider,
            "source": observation.lineage.source,
            "authority": observation.lineage.authority.value,
            "raw_contract_version": observation.lineage.raw_contract_version,
            "event_at": observation.lineage.event_at,
            "received_at": (
                observation.lineage.received_at or observation.lineage.event_at
            ).astimezone(timezone.utc),
            "fetched_at": (
                observation.lineage.fetched_at or observation.lineage.event_at
            ).astimezone(timezone.utc),
            "finalization": observation.finalization.value,
            "source_interval": "event",
            "calculation_version": TAIWAN_INDEX_MINUTE_MATERIALIZATION_VERSION,
            "component_raw_result_ids_json": json.dumps(
                candidate.component_raw_result_ids, separators=(",", ":"),
            ),
        }
        lineage_unchanged = lineage is not None and all(
            self._stored_equal(getattr(lineage, key), value)
            for key, value in lineage_incoming.items()
        )
        if lineage is None:
            lineage = MarketIntradayBarLineage(bar_id=existing.id)
            self._db.add(lineage)
        lineages_by_bar_id[existing.id] = lineage
        if not lineage_unchanged:
            for key, value in lineage_incoming.items():
                setattr(lineage, key, value)
            lineage.updated_at = utc_now()
        return unchanged and lineage_unchanged

    def persist_materialized_bars(
        self,
        candidates: tuple[TaiwanMaterializedBarCandidate, ...],
    ) -> PersistenceSummary:
        written = unchanged = 0
        coalesced = 0
        lineages_by_bar_id: dict[int, MarketIntradayBarLineage] = {}
        try:
            raw_metadata = self._load_raw_metadata(candidates)
            # The existing legacy unique key cannot retain two sources of one
            # provider/minute. Preserve its existing final-in-batch result,
            # while avoiding transient A -> B rewrites on every scheduler pass.
            # This is write coalescing, not a new Resolver selection policy.
            keys = [(c.observation.lineage.provider, c.observation.instrument.symbol,
                     c.observation.interval, c.observation.start_at) for c in candidates]
            sources_by_key = {}
            last_by_key = {}
            for index, (key, candidate) in enumerate(zip(keys, candidates)):
                sources_by_key.setdefault(key, set()).add((candidate.source_id, candidate.observation.lineage.source))
                last_by_key[key] = index
            for index, (key, candidate) in enumerate(zip(keys, candidates)):
                # Validate even overwritten evidence; invalid earlier candidates
                # still roll back the whole transaction, as before.
                source = self._validate(candidate, raw_metadata)
                if len(sources_by_key[key]) > 1 and last_by_key[key] != index:
                    coalesced += 1
                    continue
                if self._upsert(candidate, lineages_by_bar_id, source):
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
            limitations=((f"TW_INDEX_LEGACY_STORAGE_KEY_COALESCED:{coalesced}",) if coalesced else ()),
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
                parser_type=TPEX_DERIVED_DAILY_MATERIALIZATION_VERSION,
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
            "aggregation_version": TPEX_DERIVED_DAILY_MATERIALIZATION_VERSION,
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
            lineage.materialization_version = TPEX_DERIVED_DAILY_MATERIALIZATION_VERSION
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
                        "version": TPEX_DERIVED_DAILY_MATERIALIZATION_VERSION,
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
        formal_close_component: BarObservation,
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
                formal_close_component=formal_close_component,
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
