"""JP transaction owner for immutable receipts and typed canonical bar revisions."""

from datetime import timezone
from hashlib import sha256

from sqlalchemy.orm import Session

from app.db.models import JPBarEvidence, RawFetchResult, SourceRegistry
from app.jp_market.market_data.adapters import DailyAdapterResult
from app.jp_market.market_data.descriptors import daily_descriptor
from app.jp_market.trading_calendar import JP_MARKET_TIMEZONE
from app.market_data.contracts import BarFinalization, BarObservation, Market
from app.market_data.integration_contracts import PersistenceSummary


class JPBarTransaction:
    def __init__(self, db: Session) -> None:
        self._db = db

    def persist_daily(self, result: DailyAdapterResult) -> PersistenceSummary:
        return self._persist_daily(result, commit=True)

    def persist_bar_acquisition(self, requirement, acquisition) -> PersistenceSummary:
        from app.market_data.integration_contracts import BarCapabilityRequest, InstrumentTarget
        if (not isinstance(requirement.target, InstrumentTarget)
                or not isinstance(requirement.request, BarCapabilityRequest)
                or requirement.target.instrument.market is not Market.JP
                or not acquisition.summary.attempted):
            raise ValueError("JP transaction requires an attempted instrument bar acquisition")
        indexed = {(r.provider, r.source, r.content_hash): r for r in acquisition.receipts}
        if len(indexed) != len(acquisition.receipts):
            raise ValueError("Duplicate JP acquisition receipts")
        for bar in acquisition.observations:
            if (bar.instrument != requirement.target.instrument
                    or not requirement.request.start_at <= bar.start_at < bar.end_at <= requirement.request.end_at
                    or (bar.lineage.provider, bar.lineage.source, bar.lineage.content_hash) not in indexed):
                raise ValueError("JP acquisition observation is outside request or lacks receipt")
        summaries = []
        try:
            for key, receipt in indexed.items():
                bars = tuple(b for b in acquisition.observations if (b.lineage.provider, b.lineage.source, b.lineage.content_hash) == key)
                summaries.append(self._persist_daily(DailyAdapterResult(receipt, bars, ()), commit=False))
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise
        return PersistenceSummary(
            attempted=True, committed=True,
            receipts_written=sum(s.receipts_written for s in summaries),
            observations_written=sum(s.observations_written for s in summaries),
            observations_inserted=sum(s.observations_inserted for s in summaries),
            observations_unchanged=sum(s.observations_unchanged for s in summaries),
            raw_result_ids=tuple(i for s in summaries for i in s.raw_result_ids),
        )

    def _persist_daily(self, result: DailyAdapterResult, *, commit: bool) -> PersistenceSummary:
        receipt = result.receipt
        descriptor = daily_descriptor(receipt.provider)
        if receipt.resource_id != descriptor.resource_id or receipt.source != descriptor.resource_id:
            raise ValueError("JP receipt registration mismatch")
        if receipt.raw_text is None or sha256(receipt.raw_text.encode("utf-8")).hexdigest() != receipt.content_hash:
            raise ValueError("JP receipt content hash mismatch")
        if len(result.bars) > 5000:
            raise ValueError("JP daily persistence exceeds observation bound")
        inserted = unchanged = 0
        try:
            source = self._db.query(SourceRegistry).filter_by(source_name=receipt.source).one_or_none()
            if source is None:
                source = SourceRegistry(
                    source_name=receipt.source, source_type="api", category="market_data",
                    endpoint_url=None, enabled=True, priority=descriptor.priority,
                    parser_type=receipt.parser_version,
                    auth_type="api_key" if receipt.provider == "jquants" else "none",
                    reliability_level=descriptor.authority.value,
                )
                self._db.add(source)
                self._db.flush()
            raw = self._db.query(RawFetchResult).filter_by(
                source_id=source.id, content_hash=receipt.content_hash,
                parser_version=receipt.parser_version,
            ).order_by(RawFetchResult.id).first()
            created = raw is None
            if raw is None:
                raw = RawFetchResult(
                    source_id=source.id, fetched_at=receipt.fetched_at.astimezone(timezone.utc),
                    url=receipt.url, method=receipt.method, status_code=receipt.status_code,
                    content_type=receipt.content_type, content_hash=receipt.content_hash,
                    raw_text=receipt.raw_text, parser_version=receipt.parser_version,
                )
                self._db.add(raw)
                self._db.flush()
            for bar in result.bars:
                if (bar.instrument.market is not Market.JP or bar.interval != "1d"
                        or bar.instrument.venue not in descriptor.venue_scope
                        or bar.instrument.instrument_type not in descriptor.instrument_types
                        or bar.price_basis != "raw"
                        or bar.finalization not in (BarFinalization.FINAL, BarFinalization.CORRECTED)
                        or bar.lineage.provider != receipt.provider
                        or bar.lineage.source != receipt.source
                        or bar.lineage.authority != descriptor.authority
                        or bar.lineage.content_hash != receipt.content_hash
                        or bar.lineage.raw_contract_version != receipt.parser_version
                        or not bar.lineage.observation_id
                        or bar.lineage.fetched_at != receipt.fetched_at
                        or bar.end_at > receipt.fetched_at):
                    raise ValueError("JP observation/receipt contract mismatch")
                existing = self._db.query(JPBarEvidence).filter_by(
                    observation_id=bar.lineage.observation_id,
                ).one_or_none()
                if existing is not None:
                    # Same receipt is replay-safe. A collision must never overwrite evidence.
                    previous = BarObservation.model_validate_json(existing.observation_json)
                    if previous.model_dump(exclude={"lineage"}) != bar.model_dump(exclude={"lineage"}) or existing.raw_result_id != raw.id:
                        raise ValueError("JP immutable observation identity conflict")
                    unchanged += 1
                    continue
                latest = self._db.query(JPBarEvidence).filter_by(
                    symbol=bar.instrument.symbol, venue=bar.instrument.venue,
                    instrument_type=bar.instrument.instrument_type.value,
                    provider=bar.lineage.provider, interval=bar.interval,
                    start_at=bar.start_at.astimezone(timezone.utc), price_basis=bar.price_basis,
                ).order_by(JPBarEvidence.available_at.desc(), JPBarEvidence.id.desc()).first()
                if latest is not None:
                    previous = BarObservation.model_validate_json(latest.observation_json)
                    if (previous.model_dump(exclude={"lineage"}) == bar.model_dump(exclude={"lineage"})
                            and previous.lineage.raw_contract_version == bar.lineage.raw_contract_version):
                        unchanged += 1
                        continue
                stored = bar.model_copy(update={"lineage": bar.lineage.model_copy(update={
                    "raw_receipt_id": str(raw.id), "cache_hit": True,
                })})
                self._db.add(JPBarEvidence(
                    observation_id=stored.lineage.observation_id,
                    symbol=stored.instrument.symbol, venue=stored.instrument.venue,
                    instrument_type=stored.instrument.instrument_type.value,
                    provider=stored.lineage.provider, interval=stored.interval,
                    trade_date=stored.end_at.astimezone(JP_MARKET_TIMEZONE).date(),
                    start_at=stored.start_at.astimezone(timezone.utc),
                    end_at=stored.end_at.astimezone(timezone.utc), price_basis=stored.price_basis,
                    available_at=receipt.fetched_at.astimezone(timezone.utc),
                    raw_result_id=raw.id, observation_json=stored.model_dump_json(),
                ))
                self._db.flush()
                inserted += 1
            raw_id = raw.id
            if commit:
                self._db.commit()
        except Exception:
            self._db.rollback()
            raise
        return PersistenceSummary(
            attempted=True, committed=commit, receipts_written=int(created),
            observations_written=inserted, observations_inserted=inserted,
            observations_unchanged=unchanged, raw_result_ids=(raw_id,),
            limitations=tuple(sorted({reason for _, reason in result.rejections})),
        )
