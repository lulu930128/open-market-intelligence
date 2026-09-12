"""Bounded, cache-only JP candidate reader. Never parses raw provider payloads."""

from datetime import timezone

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import JPBarEvidence, RawFetchResult, SourceRegistry
from app.jp_market.market_data.descriptors import daily_descriptor
from app.jp_market.trading_calendar import JP_MARKET_TIMEZONE, is_jp_trading_day
from app.market_data.candidate_repository import (
    CandidateReadLimitExceeded, CandidateRowRejection, DailyBarCandidateQuery,
    DailyBarCandidateRead, PersistedBarSeries,
)
from app.market_data.contracts import BarFinalization, BarObservation, InstrumentKey, InstrumentType, Market


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class JPDailyBarRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def load_daily_bars(self, query: DailyBarCandidateQuery) -> DailyBarCandidateRead:
        if query.instrument.market is not Market.JP:
            raise ValueError("JP candidate query requires market JP")
        # Select only receipt identity columns: raw_text must never enter this read.
        rows_query = self._db.query(
            JPBarEvidence, RawFetchResult.content_hash, SourceRegistry.source_name,
        ).outerjoin(RawFetchResult, RawFetchResult.id == JPBarEvidence.raw_result_id).outerjoin(
            SourceRegistry, SourceRegistry.id == RawFetchResult.source_id,
        ).filter(
            JPBarEvidence.symbol == query.instrument.symbol,
            JPBarEvidence.venue == query.instrument.venue,
            JPBarEvidence.instrument_type == query.instrument.instrument_type.value,
            JPBarEvidence.interval == "1d", JPBarEvidence.price_basis == "raw",
            JPBarEvidence.trade_date >= query.start_date,
            JPBarEvidence.trade_date <= query.end_date,
        )
        if query.available_at is not None:
            rows_query = rows_query.filter(JPBarEvidence.available_at <= query.available_at.astimezone(timezone.utc))
        with self._db.no_autoflush:
            rows = rows_query.order_by(JPBarEvidence.available_at.desc(), JPBarEvidence.id.desc()).limit(query.max_rows + 1).all()
        if len(rows) > query.max_rows:
            raise CandidateReadLimitExceeded("JP daily revision read exceeded max_rows; narrow the date range")
        return self.decode_rows(query, rows)

    def load_recent_by_instrument(self, *, available_at, max_rows=20000):
        """One bounded SQL snapshot for market overview; no per-symbol DB queries."""
        identity = (JPBarEvidence.symbol, JPBarEvidence.venue, JPBarEvidence.instrument_type,
                    JPBarEvidence.provider)
        dates = self._db.query(
            JPBarEvidence.id.label("id"), JPBarEvidence.symbol.label("symbol"),
            JPBarEvidence.venue.label("venue"), JPBarEvidence.instrument_type.label("instrument_type"),
            JPBarEvidence.provider.label("provider"), JPBarEvidence.trade_date.label("trade_date"),
            func.dense_rank().over(partition_by=identity,
                order_by=JPBarEvidence.trade_date.desc()).label("date_rank"),
        ).filter(JPBarEvidence.interval == "1d", JPBarEvidence.price_basis == "raw",
                 JPBarEvidence.available_at <= available_at.astimezone(timezone.utc)).subquery()
        query = self._db.query(JPBarEvidence, RawFetchResult.content_hash, SourceRegistry.source_name).outerjoin(
            RawFetchResult, RawFetchResult.id == JPBarEvidence.raw_result_id,
        ).outerjoin(SourceRegistry, SourceRegistry.id == RawFetchResult.source_id).filter(
            JPBarEvidence.id.in_(select(dates.c.id).where(dates.c.date_rank <= 2)),
        )
        with self._db.no_autoflush:
            rows = query.order_by(JPBarEvidence.available_at.desc(), JPBarEvidence.id.desc()).limit(max_rows + 1).all()
        if len(rows) > max_rows:
            raise CandidateReadLimitExceeded("JP overview exceeds the bounded canonical snapshot")
        grouped = {}
        for row in rows:
            key = InstrumentKey(market=Market.JP, symbol=row[0].symbol, venue=row[0].venue,
                                instrument_type=InstrumentType(row[0].instrument_type))
            grouped.setdefault(key.model_dump_json(), (key, []))[1].append(row)
        return tuple(grouped.values())

    @staticmethod
    def decode_rows(query, rows) -> DailyBarCandidateRead:
        groups = {}
        rejections = []
        selected_keys = set()
        for row, content_hash, source_name in rows:
            reason = None
            try:
                descriptor = daily_descriptor(row.provider)
                bar = BarObservation.model_validate_json(row.observation_json)
                if (bar.instrument != query.instrument or bar.lineage.observation_id != row.observation_id
                        or bar.lineage.provider != row.provider or bar.interval != row.interval
                        or bar.price_basis != row.price_basis
                        or bar.start_at != _utc(row.start_at) or bar.end_at != _utc(row.end_at)
                        or bar.end_at.astimezone(JP_MARKET_TIMEZONE).date() != row.trade_date
                        or bar.lineage.content_hash != content_hash
                        or not content_hash or bar.lineage.source != source_name
                        or source_name != descriptor.resource_id
                        or bar.lineage.authority != descriptor.authority
                        or bar.lineage.raw_receipt_id != str(row.raw_result_id)
                        or bar.lineage.fetched_at != _utc(row.available_at)):
                    reason = "CANONICAL_STORAGE_IDENTITY_MISMATCH"
                elif not is_jp_trading_day(row.trade_date):
                    reason = "NON_TRADING_DATE"
                elif bar.finalization not in (BarFinalization.FINAL, BarFinalization.CORRECTED):
                    reason = "BAR_NOT_FINALIZED"
                elif query.available_at is not None and bar.end_at > query.available_at:
                    reason = "FUTURE_EVENT"
                key = (row.provider, row.trade_date)
                if reason is None and key in selected_keys:
                    reason = "SUPERSEDED_REVISION"
            except (ValueError, ValidationError):
                reason = "INVALID_CANONICAL_STORAGE"
            if reason is not None:
                rejections.append(CandidateRowRejection(
                    provider=row.provider, source=source_name or "unknown",
                    storage_row_id=row.id, raw_result_id=row.raw_result_id,
                    event_date=row.trade_date, reason_code=reason,
                ))
                continue
            selected_keys.add(key)
            groups.setdefault(row.provider, []).append((bar, row.id, row.raw_result_id))
        series = []
        for provider, items in sorted(groups.items()):
            items.sort(key=lambda item: item[0].start_at)
            descriptor = daily_descriptor(provider)
            series.append(PersistedBarSeries(
                provider=provider, source=descriptor.resource_id, authority=descriptor.authority,
                provider_priority=descriptor.priority, bars=tuple(item[0] for item in items),
                storage_row_ids=tuple(item[1] for item in items),
                raw_result_ids=tuple(item[2] for item in items),
            ))
        return DailyBarCandidateRead(
            query=query, series=tuple(series), rejections=tuple(rejections),
            rows_examined=len(rows), rows_accepted=sum(len(s.bars) for s in series),
        )
