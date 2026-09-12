"""Bounded persisted KR candidates with receipt and point-in-time validation."""

from collections import defaultdict
from datetime import timedelta, timezone
import hashlib

from pydantic import ValidationError
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.db.models import KRBarEvidence, RawFetchResult, SourceRegistry
from app.kr_market.daily_semantics import validate_completed_daily_bar
from app.kr_market.market_data.descriptors import KR_DAILY_DESCRIPTOR_BY_PROVIDER, KR_DAILY_PARSER_VERSION
from app.kr_market.trading_calendar import KR_MARKET_TIMEZONE, is_kr_trading_day, kr_calendar_limit
from app.market_data.candidate_repository import CandidateRowRejection
from app.market_data.contracts import BarObservation, EvidenceFreshness, MarketSession
from app.market_data.gateway import BarCandidateBatch
from app.market_data.resolution import BarSeriesCandidate


def aware_utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class KRDailyCandidateReader:
    def __init__(self, db: Session):
        self.db = db

    def read_bar_candidates(self, requirement) -> BarCandidateBatch:
        if not inspect(self.db.get_bind()).has_table(KRBarEvidence.__tablename__):
            return BarCandidateBatch(limitations=("KR_CANONICAL_SCHEMA_NOT_ADOPTED",))
        instrument = requirement.target.instrument
        request = requirement.request
        expected_date = request.end_at.astimezone(KR_MARKET_TIMEZONE).date()
        with self.db.no_autoflush:
            # Only receipt metadata is loaded; GET never reparses provider raw payloads.
            rows = self.db.query(
                KRBarEvidence, RawFetchResult.content_hash, RawFetchResult.parser_version,
                RawFetchResult.fetched_at, SourceRegistry.source_name,
                RawFetchResult.status_code, RawFetchResult.error_message,
            ).outerjoin(RawFetchResult, RawFetchResult.id == KRBarEvidence.raw_result_id).outerjoin(
                SourceRegistry, SourceRegistry.id == RawFetchResult.source_id,
            ).filter(
                KRBarEvidence.symbol == instrument.symbol,
                KRBarEvidence.venue == instrument.venue,
                KRBarEvidence.interval == request.interval,
                KRBarEvidence.trade_date >= request.start_at.astimezone(KR_MARKET_TIMEZONE).date(),
                KRBarEvidence.trade_date <= expected_date,
                KRBarEvidence.available_at <= requirement.requested_at.astimezone(timezone.utc),
            ).order_by(KRBarEvidence.trade_date.desc(), KRBarEvidence.available_at.desc(),
                       KRBarEvidence.id.desc()).limit(requirement.bounds.max_rows).all()
        groups = defaultdict(dict)
        rejections = []
        for row, raw_hash, parser_version, fetched_at, source_name, status_code, error_message in rows:
            try:
                descriptor = KR_DAILY_DESCRIPTOR_BY_PROVIDER.get(row.provider)
                if descriptor is None:
                    raise ValueError("KR_UNREGISTERED_PROVIDER")
                if hashlib.sha256(row.observation_json.encode("utf-8")).hexdigest() != row.observation_hash:
                    raise ValueError("KR_OBSERVATION_HASH_MISMATCH")
                if row.observation_id != f"kr.bar:{row.observation_hash}":
                    raise ValueError("KR_OBSERVATION_ID_MISMATCH")
                bar = BarObservation.model_validate_json(row.observation_json)
                validate_completed_daily_bar(bar)
                if (bar.instrument != instrument or bar.interval != request.interval
                    or bar.price_basis != request.price_basis or bar.lineage.provider != row.provider
                    or bar.lineage.authority != descriptor.authority
                    or bar.lineage.source != descriptor.resource_id):
                    raise ValueError("KR_BAR_IDENTITY_MISMATCH")
                if (status_code != 200 or error_message or parser_version != KR_DAILY_PARSER_VERSION
                    or not raw_hash or bar.lineage.content_hash != raw_hash
                    or bar.lineage.raw_receipt_id != str(row.raw_result_id)
                    or bar.lineage.raw_contract_version != parser_version
                    or source_name != f"kr.canonical.{descriptor.resource_id}"
                    or fetched_at is None or bar.lineage.fetched_at != aware_utc(fetched_at)
                    or aware_utc(row.available_at) != aware_utc(fetched_at)):
                    raise ValueError("KR_RECEIPT_LINEAGE_MISMATCH")
                if (not request.start_at <= bar.start_at < bar.end_at <= request.end_at
                    or bar.end_at.astimezone(KR_MARKET_TIMEZONE).date() != row.trade_date):
                    raise ValueError("KR_BAR_TIME_MISMATCH")
                key = (row.provider, bar.lineage.source, bar.price_basis)
                # SQL order makes the latest available revision win within a provider.
                groups[key].setdefault(bar.start_at, bar.model_copy(update={
                    "lineage": bar.lineage.model_copy(update={"cache_hit": True,
                                                               "observation_id": row.observation_id})}))
            except (ValueError, ValidationError) as exc:
                reason = str(exc) if str(exc).startswith("KR_") else "KR_BAR_CONTRACT_INVALID"
                rejections.append(CandidateRowRejection(provider=row.provider or "unknown", source="kr_bar_evidence",
                    storage_row_id=row.id, raw_result_id=row.raw_result_id, event_date=row.trade_date,
                    reason_code=reason[:64]))
        candidates = []
        series_limitations = []
        for (provider, _, _), by_time in groups.items():
            bars = tuple(by_time[key] for key in sorted(by_time))[-request.max_bars:]
            descriptor = KR_DAILY_DESCRIPTOR_BY_PROVIDER[provider]
            if request.coverage:
                dates = {bar.end_at.astimezone(KR_MARKET_TIMEZONE).date() for bar in bars}
                cursor = min(dates)
                has_gap = False
                while cursor <= max(dates):
                    has_gap |= is_kr_trading_day(cursor) and cursor not in dates
                    cursor += timedelta(days=1)
                if has_gap:
                    series_limitations.append("KR_DAILY_HISTORY_GAP")
                    continue
            candidates.append(BarSeriesCandidate(bars=bars,
                freshness=EvidenceFreshness.FRESH if bars[-1].end_at.astimezone(KR_MARKET_TIMEZONE).date() == expected_date else EvidenceFreshness.STALE,
                provider_priority=descriptor.priority, session=MarketSession.CLOSED,
                limitations=descriptor.limitations))
        limitations = tuple(dict.fromkeys((*series_limitations, *(rejection.reason_code for rejection in rejections))))
        if len(rows) == requirement.bounds.max_rows:
            limitations += ("KR_CANDIDATE_READ_BOUND_REACHED",)
        if kr_calendar_limit(expected_date.year):
            limitations += ("KR_CALENDAR_COVERAGE_UNVERIFIED",)
        return BarCandidateBatch(candidates=tuple(candidates), rejections=tuple(rejections), limitations=limitations)
