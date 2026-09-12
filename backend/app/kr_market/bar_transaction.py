"""Atomic KR receipt/bar persistence. Reads never call this transaction owner."""

import hashlib
from datetime import timezone

from sqlalchemy.orm import Session

from app.db.models import KRBarEvidence, RawFetchResult, SourceRegistry
from app.kr_market.daily_semantics import validate_completed_daily_bar
from app.kr_market.market_data.descriptors import KR_DAILY_DESCRIPTOR_BY_PROVIDER, KR_DAILY_PARSER_VERSION
from app.kr_market.trading_calendar import KR_MARKET_TIMEZONE
from app.market_data.contracts import Market
from app.market_data.integration_contracts import PersistenceSummary


def observation_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class KRBarTransaction:
    def __init__(self, db: Session):
        self.db = db

    def persist_bar_acquisition(self, requirement, acquisition) -> PersistenceSummary:
        db = self.db
        written = unchanged = receipts_written = 0
        raw_ids = []
        receipt_map = {}
        # A caller's pending work is outside this transaction's ownership.
        if db.new or db.dirty or db.deleted:
            raise ValueError("KR canonical transaction requires a clean session")
        try:
            if len(acquisition.observations) > requirement.bounds.max_rows:
                raise ValueError("KR acquisition exceeds the persistence row bound")
            for receipt in acquisition.receipts:
                descriptor = KR_DAILY_DESCRIPTOR_BY_PROVIDER.get(receipt.provider)
                if (descriptor is None or receipt.resource_id != descriptor.resource_id
                    or receipt.source != descriptor.resource_id or receipt.parser_version != KR_DAILY_PARSER_VERSION):
                    raise ValueError("Unregistered KR receipt resource")
                if receipt.error_message or receipt.status_code != 200 or receipt.raw_text is None:
                    raise ValueError("KR bar persistence requires a successful raw receipt")
                if observation_digest(receipt.raw_text) != receipt.content_hash:
                    raise ValueError("KR receipt content hash mismatch")
                source_name = f"kr.canonical.{receipt.resource_id}"
                source = db.query(SourceRegistry).filter_by(source_name=source_name).one_or_none()
                if source is None:
                    source = SourceRegistry(source_name=source_name, source_type="api", category="kr_market",
                                            parser_type=receipt.parser_version)
                    db.add(source)
                    db.flush()
                raw = db.query(RawFetchResult).filter_by(
                    source_id=source.id, content_hash=receipt.content_hash,
                    fetched_at=receipt.fetched_at.astimezone(timezone.utc), parser_version=receipt.parser_version,
                ).one_or_none()
                if raw is None:
                    raw = RawFetchResult(source_id=source.id, fetched_at=receipt.fetched_at.astimezone(timezone.utc),
                                         url=receipt.url, method=receipt.method, status_code=receipt.status_code,
                                         content_type=receipt.content_type, content_hash=receipt.content_hash,
                                         raw_text=receipt.raw_text, parser_version=receipt.parser_version)
                    db.add(raw)
                    db.flush()
                    receipts_written += 1
                key = (receipt.provider, receipt.source)
                if key in receipt_map:
                    raise ValueError("Duplicate KR acquisition receipt")
                receipt_map[key] = (receipt, raw)
                raw_ids.append(raw.id)
            for bar in acquisition.observations:
                validate_completed_daily_bar(bar)
                if bar.instrument != requirement.target.instrument or bar.instrument.market != Market.KR:
                    raise ValueError("KR acquired instrument mismatch")
                if bar.interval != requirement.request.interval or bar.price_basis != requirement.request.price_basis:
                    raise ValueError("KR acquired bar semantics mismatch")
                if not requirement.request.start_at <= bar.start_at < bar.end_at <= requirement.request.end_at:
                    raise ValueError("KR acquired bar lies outside the requested interval")
                receipt, raw = receipt_map[(bar.lineage.provider, bar.lineage.source)]
                descriptor = KR_DAILY_DESCRIPTOR_BY_PROVIDER[bar.lineage.provider]
                if bar.lineage.content_hash != receipt.content_hash or bar.lineage.fetched_at != receipt.fetched_at:
                    raise ValueError("KR observation receipt identity mismatch")
                if bar.lineage.authority != descriptor.authority or bar.lineage.raw_contract_version != receipt.parser_version:
                    raise ValueError("KR observation authority/parser mismatch")
                persisted = bar.model_copy(update={"lineage": bar.lineage.model_copy(update={"raw_receipt_id": str(raw.id)})})
                payload = persisted.model_dump_json()
                digest = observation_digest(payload)
                observation_id = f"kr.bar:{digest}"
                existing = db.query(KRBarEvidence).filter_by(observation_id=observation_id).one_or_none()
                if existing:
                    if existing.observation_json != payload or existing.observation_hash != digest:
                        raise ValueError("KR immutable observation conflict")
                    unchanged += 1
                    continue
                db.add(KRBarEvidence(observation_id=observation_id,
                    symbol=bar.instrument.symbol, venue=bar.instrument.venue, provider=bar.lineage.provider,
                    interval=bar.interval, trade_date=bar.end_at.astimezone(KR_MARKET_TIMEZONE).date(),
                    available_at=receipt.fetched_at.astimezone(timezone.utc), raw_result_id=raw.id,
                    observation_json=payload, observation_hash=digest))
                written += 1
            db.commit()
        except Exception:
            db.rollback()
            raise
        return PersistenceSummary(attempted=True, committed=True, receipts_written=receipts_written,
                                  observations_written=written, observations_inserted=written,
                                  observations_unchanged=unchanged, raw_result_ids=tuple(raw_ids))
