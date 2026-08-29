"""Cache-only canonical repository for persisted US daily OHLCV candidates."""

from __future__ import annotations

from datetime import datetime, time, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.db.models import RawFetchResult, SourceRegistry, USDailyPrice
from app.market_data.candidate_repository import (
    CandidateReadLimitExceeded,
    CandidateRowRejection,
    DailyBarCandidateQuery,
    DailyBarCandidateRead,
    PersistedBarSeries,
)
from app.market_data.contracts import (
    AuthorityClass,
    BarFinalization,
    BarObservation,
    InstrumentType,
    Market,
    Quantity,
    QuantityUnit,
    SourceLineage,
)
from app.us_market.market_data.descriptors import US_DAILY_CANDIDATE_DESCRIPTORS
from app.us_market.symbols import us_symbol_storage_candidates
from app.us_market.trading_calendar import us_session_close_time


US_EASTERN = ZoneInfo("America/New_York")
_PRIORITY = {
    descriptor.provider_key: descriptor.priority
    for descriptor in US_DAILY_CANDIDATE_DESCRIPTORS
}


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _missing_lineage(row: USDailyPrice) -> tuple[str, ...]:
    fields = (
        "source_id",
        "raw_result_id",
        "authority",
        "raw_contract_version",
        "event_at",
        "finalization",
        "price_basis",
        "volume_status",
    )
    return tuple(name for name in fields if getattr(row, name) in (None, ""))


class USDailyBarRepository:
    """Read every bounded provider-coherent series without selecting a winner."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def load_daily_bars(self, query: DailyBarCandidateQuery) -> DailyBarCandidateRead:
        instrument = query.instrument
        if instrument.market is not Market.US:
            raise ValueError("US daily repository requires market=US")
        if instrument.instrument_type not in {
            InstrumentType.STOCK,
            InstrumentType.ETF,
            InstrumentType.INDEX,
        }:
            raise ValueError("US daily repository supports stock, ETF, and index")
        symbols = us_symbol_storage_candidates(instrument.symbol)
        rows_query = (
            self._db.query(USDailyPrice, RawFetchResult, SourceRegistry)
            .outerjoin(RawFetchResult, RawFetchResult.id == USDailyPrice.raw_result_id)
            .outerjoin(SourceRegistry, SourceRegistry.id == USDailyPrice.source_id)
            .filter(USDailyPrice.symbol.in_(symbols))
            .filter(USDailyPrice.trade_date >= query.start_date)
            .filter(USDailyPrice.trade_date <= query.end_date)
        )
        if query.available_at is not None:
            rows_query = rows_query.filter(
                RawFetchResult.fetched_at <= _aware_utc(query.available_at)
            )
        rows = (
            rows_query.order_by(
                USDailyPrice.provider.asc(),
                USDailyPrice.trade_date.asc(),
                USDailyPrice.id.asc(),
            )
            .limit(query.max_rows * max(len(_PRIORITY), 1) + 1)
            .all()
        )
        if len(rows) > query.max_rows * max(len(_PRIORITY), 1):
            raise CandidateReadLimitExceeded(
                "US daily candidate read exceeded max_rows; narrow the requested range"
            )

        bars_by_source: dict[tuple[str, str], list[BarObservation]] = {}
        storage_ids: dict[tuple[str, str], list[int]] = {}
        raw_ids: dict[tuple[str, str], list[int]] = {}
        rejections: list[CandidateRowRejection] = []
        accepted_keys: set[tuple[str, str, object]] = set()
        for row, raw, source in rows:
            provider = str(row.provider or "").strip().lower()
            source_name = str(source.source_name if source is not None else "").strip()
            missing = list(_missing_lineage(row))
            if raw is None:
                missing.append("raw_receipt")
            if source is None:
                missing.append("source")
            for name in ("open_price", "high_price", "low_price", "close_price"):
                if getattr(row, name) is None:
                    missing.append(name)
            raw_id = int(row.raw_result_id or 0)
            if missing:
                rejections.append(
                    CandidateRowRejection(
                        provider=provider or "unknown",
                        source=source_name or "unknown",
                        storage_row_id=row.id,
                        raw_result_id=max(raw_id, 1),
                        event_date=row.trade_date,
                        reason_code="US_DAILY_LINEAGE_INCOMPLETE",
                        missing_fields=tuple(dict.fromkeys(missing)),
                    )
                )
                continue
            if (
                str(source.source_type or "").strip().lower()
                == "compatibility_adapter"
                or source_name.lower().startswith("legacy_compat.")
                or "legacy_compat" in str(row.raw_contract_version or "").lower()
            ):
                rejections.append(
                    CandidateRowRejection(
                        provider=provider or "unknown",
                        source=source_name or "unknown",
                        storage_row_id=row.id,
                        raw_result_id=raw_id,
                        event_date=row.trade_date,
                        reason_code="US_DAILY_LEGACY_COMPAT_LINEAGE_REJECTED",
                    )
                )
                continue
            if provider not in _PRIORITY:
                rejections.append(
                    CandidateRowRejection(
                        provider=provider,
                        source=source_name,
                        storage_row_id=row.id,
                        raw_result_id=raw_id,
                        event_date=row.trade_date,
                        reason_code="US_DAILY_PROVIDER_UNREGISTERED",
                    )
                )
                continue
            if raw.content_hash != row.raw_payload_hash:
                rejections.append(
                    CandidateRowRejection(
                        provider=provider,
                        source=source_name,
                        storage_row_id=row.id,
                        raw_result_id=raw_id,
                        event_date=row.trade_date,
                        reason_code="US_DAILY_CONTENT_HASH_MISMATCH",
                    )
                )
                continue
            key = (provider, source_name, row.trade_date)
            if key in accepted_keys:
                rejections.append(
                    CandidateRowRejection(
                        provider=provider,
                        source=source_name,
                        storage_row_id=row.id,
                        raw_result_id=raw_id,
                        event_date=row.trade_date,
                        reason_code="US_DAILY_DUPLICATE_STORAGE_ALIAS",
                    )
                )
                continue
            accepted_keys.add(key)
            start_at = datetime.combine(row.trade_date, time(9, 30), tzinfo=US_EASTERN)
            end_at = datetime.combine(
                row.trade_date,
                us_session_close_time(row.trade_date),
                tzinfo=US_EASTERN,
            )
            try:
                volume = None
                if row.volume_status == "observed":
                    if row.trade_volume is None or row.volume_unit != "shares":
                        raise ValueError("observed volume requires shares")
                    volume = Quantity(
                        value=Decimal(row.trade_volume),
                        unit=QuantityUnit.SHARE,
                    )
                elif row.volume_status != "not_applicable":
                    raise ValueError("unsupported volume_status")
                bar = BarObservation(
                    instrument=instrument,
                    lineage=SourceLineage(
                        provider=provider,
                        source=source_name,
                        authority=AuthorityClass(row.authority),
                        raw_contract_version=row.raw_contract_version,
                        event_at=_aware_utc(row.event_at),
                        fetched_at=_aware_utc(raw.fetched_at),
                        cache_hit=True,
                        observation_id=f"us_daily_price:{row.id}",
                        raw_receipt_id=f"raw_fetch_result:{raw.id}",
                        content_hash=raw.content_hash,
                    ),
                    interval="1d",
                    start_at=start_at,
                    end_at=end_at,
                    open_price=Decimal(str(row.open_price)),
                    high_price=Decimal(str(row.high_price)),
                    low_price=Decimal(str(row.low_price)),
                    close_price=Decimal(str(row.close_price)),
                    volume=volume,
                    volume_status=row.volume_status,
                    price_basis=row.price_basis,
                    finalization=BarFinalization(row.finalization),
                )
            except (TypeError, ValueError, ValidationError):
                rejections.append(
                    CandidateRowRejection(
                        provider=provider,
                        source=source_name,
                        storage_row_id=row.id,
                        raw_result_id=raw_id,
                        event_date=row.trade_date,
                        reason_code="INVALID_CANONICAL_BAR",
                    )
                )
                continue
            series_key = (provider, source_name)
            bars_by_source.setdefault(series_key, []).append(bar)
            storage_ids.setdefault(series_key, []).append(row.id)
            raw_ids.setdefault(series_key, []).append(raw.id)

        series = tuple(
            PersistedBarSeries(
                provider=provider,
                source=source,
                authority=bars[0].lineage.authority,
                provider_priority=_PRIORITY[provider],
                bars=tuple(bars),
                storage_row_ids=tuple(storage_ids[(provider, source)]),
                raw_result_ids=tuple(raw_ids[(provider, source)]),
                limitations=(
                    ("PRICE_BASIS_RAW",)
                    if all(
                        row.price_basis == "raw"
                        for row, _raw, src in rows
                        if src is not None
                        and row.provider == provider
                        and src.source_name == source
                    )
                    else ("PRICE_BASIS_MIXED_OR_UNKNOWN",)
                ),
            )
            for (provider, source), bars in bars_by_source.items()
            if bars
        )
        return DailyBarCandidateRead(
            query=query,
            series=series,
            rejections=tuple(rejections),
            rows_examined=len(rows),
            rows_accepted=sum(len(bars) for bars in bars_by_source.values()),
        )


__all__ = ["USDailyBarRepository"]
