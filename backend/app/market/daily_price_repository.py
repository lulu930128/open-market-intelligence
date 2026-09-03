"""Read-only Taiwan official daily-price candidate repository.

This adapter converts existing normalized persistence rows into provider-neutral
canonical bars. It deliberately performs no provider I/O, refresh, fallback,
selection, commit, or rollback.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
import json

from pydantic import ValidationError
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, load_only

from app.db.models import (
    MarketDailyPrice,
    MarketDailyPriceLineage,
    MarketDailyPriceReconciliation,
    RawFetchResult,
    SourceRegistry,
    StockMaster,
)
from app.market.tw_bar_contracts import (
    TAIEX_OFFICIAL_DAILY_PROVIDER,
    TAIEX_OFFICIAL_DAILY_SOURCE,
    TAIWAN_DAILY_MATERIALIZATION_VERSION,
    TPEX_DERIVED_DAILY_MATERIALIZATION_VERSION,
    TPEX_DERIVED_DAILY_KIND,
    TPEX_DERIVED_DAILY_PROVIDER,
    TPEX_DERIVED_DAILY_SOURCE,
)
from app.market.taiwan_rules import taiwan_daily_price_release_at
from app.market.trading_calendar import TAIWAN_TZ
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
    InstrumentKey,
    InstrumentType,
    Market,
    Quantity,
    QuantityUnit,
    SourceLineage,
)
from app.sources.defaults import (
    TPEX_DAILY_QUOTES_SOURCE_NAME,
    TWSE_DAILY_TRADING_SOURCE_NAME,
    TWSE_RWD_DAILY_TRADING_SOURCE_NAME,
)


_RAW_FETCH_LINEAGE_COLUMNS = (
    RawFetchResult.id,
    RawFetchResult.fetched_at,
    RawFetchResult.content_hash,
    RawFetchResult.parser_version,
)


@dataclass(frozen=True, slots=True)
class _OfficialDailySourceBinding:
    venue: str
    provider: str
    source_name: str
    authority: AuthorityClass = AuthorityClass.EXCHANGE
    materialized: bool = False


@dataclass(frozen=True, slots=True)
class TaiwanOfficialDailyUniverseRead:
    """One resolver-eligible official bar per instrument for an exact session."""

    trade_date: date
    bars: tuple[BarObservation, ...] = ()
    universe_count: int = 0
    universe_count_by_market: tuple[tuple[str, int], ...] = ()
    selected_count_by_market: tuple[tuple[str, int], ...] = ()
    rows_examined: int = 0
    rows_rejected: int = 0
    duplicate_candidate_count: int = 0
    limitations: tuple[str, ...] = ()


_SOURCES_BY_VENUE = {
    "TWSE": (
        _OfficialDailySourceBinding(
            venue="TWSE",
            provider="twse_rwd",
            source_name=TWSE_RWD_DAILY_TRADING_SOURCE_NAME,
        ),
        _OfficialDailySourceBinding(
            venue="TWSE",
            provider="twse_openapi",
            source_name=TWSE_DAILY_TRADING_SOURCE_NAME,
        ),
    ),
    "TPEX": (
        _OfficialDailySourceBinding(
            venue="TPEX",
            provider="tpex_openapi",
            source_name=TPEX_DAILY_QUOTES_SOURCE_NAME,
        ),
    ),
}
_TRUSTED_OFFICIAL_RELIABILITY = {
    "official",
    "regulated_filing",
    "verified_official_mirror",
}


def _bindings_for_instrument(
    instrument: InstrumentKey,
) -> tuple[_OfficialDailySourceBinding, ...]:
    if instrument.market is not Market.TW:
        raise ValueError("Taiwan daily repository requires market=TW")
    if instrument.instrument_type is InstrumentType.INDEX:
        if instrument.symbol == "TAIEX" and instrument.venue == "TWSE":
            return (
                _OfficialDailySourceBinding(
                    venue="TWSE",
                    provider=TAIEX_OFFICIAL_DAILY_PROVIDER,
                    source_name=TAIEX_OFFICIAL_DAILY_SOURCE,
                ),
            )
        if instrument.symbol == "TPEX" and instrument.venue == "TPEX":
            return (
                _OfficialDailySourceBinding(
                    venue="TPEX",
                    provider=TPEX_DERIVED_DAILY_PROVIDER,
                    source_name=TPEX_DERIVED_DAILY_SOURCE,
                    authority=AuthorityClass.DERIVED,
                    materialized=True,
                ),
            )
        raise ValueError("unsupported Taiwan index daily identity")
    if instrument.instrument_type not in {InstrumentType.STOCK, InstrumentType.ETF}:
        raise ValueError("unsupported Taiwan daily instrument type")
    venue = str(instrument.venue or "").strip().upper()
    bindings = _SOURCES_BY_VENUE.get(venue)
    if bindings is None:
        raise ValueError("Taiwan daily repository requires venue=TWSE or TPEX")
    return bindings


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _decimal(value: float | int) -> Decimal:
    return Decimal(str(value))


def _receipt_is_release_qualified(
    *,
    trade_date: date,
    fetched_at: datetime,
) -> bool:
    release_at = taiwan_daily_price_release_at(trade_date).astimezone(timezone.utc)
    return _as_aware_utc(fetched_at) >= release_at


def taiwan_official_daily_release_qualified_filter():
    """Return the persisted-receipt equivalent of the per-row release gate.

    Raw receipt timestamps are stored as UTC-naive values in the local SQLite
    database. A later UTC date is necessarily after release; a same-date
    receipt must be at or after 07:15 UTC (15:15 Asia/Taipei).
    """

    fetched_date = func.date(RawFetchResult.fetched_at)
    trade_date = func.date(MarketDailyPrice.trade_date)
    fetched_time = func.time(RawFetchResult.fetched_at)
    return or_(
        fetched_date > trade_date,
        and_(fetched_date == trade_date, fetched_time >= "07:15:00"),
    )


def _missing_ohlc(row: MarketDailyPrice) -> tuple[str, ...]:
    return tuple(
        name
        for name in ("open_price", "high_price", "low_price", "close_price")
        if getattr(row, name) is None
    )


class TaiwanOfficialDailyBarRepository:
    """Load one venue-scoped instrument from existing official daily storage."""

    def __init__(self, db: Session, *, available_at: datetime | None = None) -> None:
        self._db = db
        self._available_at = (
            _as_aware_utc(available_at).replace(tzinfo=None)
            if available_at is not None
            else None
        )

    def latest_candidate_start_date(
        self,
        *,
        instrument: InstrumentKey,
        end_date: date,
        max_rows: int,
    ) -> date | None:
        """Return the exact lower bound for a latest-N cache read.

        The normal candidate reader intentionally fails closed when a caller
        supplies a date range containing more rows than ``max_rows``.  Default
        latest reads therefore discover a precise persisted lower bound first,
        rather than guessing a calendar multiplier or silently truncating.
        """

        if max_rows < 1 or max_rows > 5000:
            raise ValueError("Taiwan daily read max_rows must be between 1 and 5000")
        bindings = _bindings_for_instrument(instrument)
        source_names = tuple(item.source_name for item in bindings)
        binding_by_source = {item.source_name: item for item in bindings}
        query = (
            self._db.query(
                MarketDailyPrice,
                RawFetchResult,
                SourceRegistry,
                MarketDailyPriceLineage,
            )
            .outerjoin(RawFetchResult, RawFetchResult.id == MarketDailyPrice.raw_result_id)
            .join(SourceRegistry, SourceRegistry.id == MarketDailyPrice.source_id)
            .outerjoin(
                MarketDailyPriceLineage,
                MarketDailyPriceLineage.daily_price_id == MarketDailyPrice.id,
            )
            .filter(MarketDailyPrice.stock_id == instrument.symbol)
            .filter(MarketDailyPrice.trade_date <= end_date)
            .filter(SourceRegistry.source_name.in_(source_names))
        )
        if self._available_at is not None:
            query = query.filter(
                or_(
                    RawFetchResult.fetched_at <= self._available_at,
                    and_(
                        RawFetchResult.id.is_(None),
                        MarketDailyPrice.updated_at <= self._available_at,
                    ),
                )
            )
        rows = (
            query.order_by(MarketDailyPrice.trade_date.desc(), MarketDailyPrice.id.desc())
            .limit(5000 * len(bindings) + 1)
            .all()
        )
        eligible_dates: list[date] = []
        seen_dates: set[date] = set()
        for row, raw, source, lineage in rows:
            if row.trade_date in seen_dates:
                continue
            binding = binding_by_source.get(source.source_name)
            component_hashes: tuple[str, ...] = ()
            if lineage is not None and lineage.component_content_hashes_json:
                try:
                    component_hashes = tuple(
                        str(value)
                        for value in json.loads(
                            lineage.component_content_hashes_json
                        )
                        if str(value)
                    )
                except (TypeError, ValueError, json.JSONDecodeError):
                    component_hashes = ()
            eligible = bool(
                binding is not None
                and (
                    (
                        binding.materialized
                        and raw is None
                        and row.raw_result_id is None
                        and row.canonical_market == Market.TW.value
                        and row.venue == instrument.venue
                        and row.instrument_type == InstrumentType.INDEX.value
                        and row.finalization in {"final", "corrected"}
                        and row.authority == binding.authority.value
                        and row.official is False
                        and row.derivation_kind == TPEX_DERIVED_DAILY_KIND
                        and row.aggregation_version
                        == TPEX_DERIVED_DAILY_MATERIALIZATION_VERSION
                        and lineage is not None
                        and lineage.evidence_kind == "materialized"
                        and lineage.source_interval == "5s"
                        and lineage.materialization_version
                        == TPEX_DERIVED_DAILY_MATERIALIZATION_VERSION
                        and component_hashes
                        and lineage.lineage_digest
                    )
                    or (
                        not binding.materialized
                        and raw is not None
                        and (
                            instrument.instrument_type is not InstrumentType.INDEX
                            or (
                                row.canonical_market == Market.TW.value
                                and row.venue == instrument.venue
                                and row.instrument_type
                                == InstrumentType.INDEX.value
                                and row.authority == binding.authority.value
                                and row.official is True
                                and row.release_status == "released"
                            )
                        )
                        and _receipt_is_release_qualified(
                            trade_date=row.trade_date,
                            fetched_at=raw.fetched_at,
                        )
                    )
                )
            )
            if not eligible:
                continue
            seen_dates.add(row.trade_date)
            eligible_dates.append(row.trade_date)
            if len(eligible_dates) >= max_rows:
                break
        return eligible_dates[-1] if eligible_dates else None

    def load_daily_bars(self, query: DailyBarCandidateQuery) -> DailyBarCandidateRead:
        instrument = query.instrument
        bindings = _bindings_for_instrument(instrument)
        binding_by_source = {item.source_name: item for item in bindings}

        stored_query = (
            self._db.query(
                MarketDailyPrice,
                RawFetchResult,
                SourceRegistry,
                MarketDailyPriceLineage,
            )
            .options(load_only(*_RAW_FETCH_LINEAGE_COLUMNS))
            .outerjoin(
                RawFetchResult,
                RawFetchResult.id == MarketDailyPrice.raw_result_id,
            )
            .join(SourceRegistry, SourceRegistry.id == MarketDailyPrice.source_id)
            .outerjoin(
                MarketDailyPriceLineage,
                MarketDailyPriceLineage.daily_price_id == MarketDailyPrice.id,
            )
            .filter(MarketDailyPrice.stock_id == instrument.symbol)
            .filter(MarketDailyPrice.trade_date >= query.start_date)
            .filter(MarketDailyPrice.trade_date <= query.end_date)
            .filter(SourceRegistry.source_name.in_(tuple(binding_by_source)))
        )
        if self._available_at is not None:
            stored_query = stored_query.filter(
                or_(
                    RawFetchResult.fetched_at <= self._available_at,
                    and_(
                        RawFetchResult.id.is_(None),
                        MarketDailyPrice.updated_at <= self._available_at,
                    ),
                )
            )
        rows = (
            stored_query.order_by(MarketDailyPrice.trade_date.asc(), MarketDailyPrice.id.asc())
            .limit(query.max_rows * len(bindings) + 129)
            .all()
        )
        if len(rows) > query.max_rows * len(bindings) + 128:
            raise CandidateReadLimitExceeded(
                "daily candidate read exceeded max_rows; narrow the requested range"
            )

        bars_by_source: dict[str, list[BarObservation]] = {}
        storage_ids_by_source: dict[str, list[int]] = {}
        raw_ids_by_source: dict[str, list[int | None]] = {}
        priority_by_source: dict[str, int] = {}
        rejections: list[CandidateRowRejection] = []
        for row, raw_result, source, materialized_lineage in rows:
            binding = binding_by_source.get(source.source_name)
            if binding is None:
                continue
            priority_by_source[source.source_name] = max(int(source.priority), 0)
            component_hashes: tuple[str, ...] = ()
            if binding.materialized:
                try:
                    component_hashes = tuple(
                        str(value)
                        for value in json.loads(
                            materialized_lineage.component_content_hashes_json
                            if materialized_lineage is not None
                            else "[]"
                        )
                        if str(value)
                    )
                except (TypeError, ValueError, json.JSONDecodeError):
                    component_hashes = ()
                materialized_valid = bool(
                    raw_result is None
                    and row.raw_result_id is None
                    and row.canonical_market == Market.TW.value
                    and row.venue == instrument.venue
                    and row.instrument_type == InstrumentType.INDEX.value
                    and row.authority == AuthorityClass.DERIVED.value
                    and row.finalization in {"final", "corrected"}
                    and row.official is False
                    and row.derivation_kind == TPEX_DERIVED_DAILY_KIND
                    and row.aggregation_version
                    == TPEX_DERIVED_DAILY_MATERIALIZATION_VERSION
                    and materialized_lineage is not None
                    and materialized_lineage.evidence_kind == "materialized"
                    and materialized_lineage.source_interval == "5s"
                    and materialized_lineage.materialization_version
                    == TPEX_DERIVED_DAILY_MATERIALIZATION_VERSION
                    and component_hashes
                    and materialized_lineage.lineage_digest
                )
                if not materialized_valid:
                    rejections.append(
                        CandidateRowRejection(
                            provider=binding.provider,
                            source=source.source_name,
                            storage_row_id=row.id,
                            raw_result_id=None,
                            event_date=row.trade_date,
                            reason_code="DAILY_MATERIALIZED_LINEAGE_INVALID",
                        )
                    )
                    continue
            elif raw_result is None or not _receipt_is_release_qualified(
                trade_date=row.trade_date,
                fetched_at=raw_result.fetched_at,
            ):
                rejections.append(
                    CandidateRowRejection(
                        provider=binding.provider,
                        source=source.source_name,
                        storage_row_id=row.id,
                        raw_result_id=(
                            raw_result.id if raw_result is not None else None
                        ),
                        event_date=row.trade_date,
                        reason_code="DAILY_RECEIPT_PREDATES_RELEASE",
                    )
                )
                continue
            if (
                not binding.materialized
                and instrument.instrument_type is InstrumentType.INDEX
                and (
                row.canonical_market != Market.TW.value
                or row.venue != instrument.venue
                or row.instrument_type != InstrumentType.INDEX.value
                or row.authority != binding.authority.value
                or row.official is not True
                or row.release_status != "released"
                )
            ):
                rejections.append(
                    CandidateRowRejection(
                        provider=binding.provider,
                        source=source.source_name,
                        storage_row_id=row.id,
                        raw_result_id=(
                            raw_result.id if raw_result is not None else None
                        ),
                        event_date=row.trade_date,
                        reason_code="DAILY_CANONICAL_IDENTITY_INVALID",
                    )
                )
                continue
            if str(source.reliability_level or "").strip().lower() not in (
                _TRUSTED_OFFICIAL_RELIABILITY
            ):
                rejections.append(
                    CandidateRowRejection(
                        provider=binding.provider,
                        source=source.source_name,
                        storage_row_id=row.id,
                        raw_result_id=(
                            raw_result.id if raw_result is not None else None
                        ),
                        event_date=row.trade_date,
                        reason_code="DAILY_SOURCE_RELIABILITY_UNTRUSTED",
                    )
                )
                continue
            missing_fields = _missing_ohlc(row)
            if missing_fields:
                rejections.append(
                    CandidateRowRejection(
                        provider=binding.provider,
                        source=source.source_name,
                        storage_row_id=row.id,
                        raw_result_id=(
                            raw_result.id if raw_result is not None else None
                        ),
                        event_date=row.trade_date,
                        reason_code="MISSING_REQUIRED_OHLC",
                        missing_fields=missing_fields,
                    )
                )
                continue

            start_at = datetime.combine(row.trade_date, time(9, 0), tzinfo=TAIWAN_TZ)
            end_at = datetime.combine(row.trade_date, time(13, 30), tzinfo=TAIWAN_TZ)
            raw_contract_version = (
                materialized_lineage.materialization_version
                if binding.materialized and materialized_lineage is not None
                else (raw_result.parser_version or source.parser_type)
                if raw_result is not None
                else source.parser_type
            )
            try:
                bar = BarObservation(
                    instrument=instrument,
                    lineage=SourceLineage(
                        provider=binding.provider,
                        source=source.source_name,
                        authority=binding.authority,
                        raw_contract_version=raw_contract_version,
                        event_at=end_at,
                        fetched_at=(
                            _as_aware_utc(raw_result.fetched_at)
                            if raw_result is not None
                            else _as_aware_utc(row.updated_at)
                        ),
                        cache_hit=True,
                        observation_id=f"market_daily_price:{row.id}",
                        raw_receipt_id=(
                            f"raw_fetch_result:{raw_result.id}"
                            if raw_result is not None
                            else None
                        ),
                        content_hash=(
                            raw_result.content_hash
                            if raw_result is not None
                            else materialized_lineage.lineage_digest
                        ),
                        component_content_hashes=component_hashes,
                        materialization_version=(
                            materialized_lineage.materialization_version
                            if binding.materialized
                            and materialized_lineage is not None
                            else None
                        ),
                    ),
                    interval="1d",
                    start_at=start_at,
                    end_at=end_at,
                    open_price=_decimal(row.open_price),
                    high_price=_decimal(row.high_price),
                    low_price=_decimal(row.low_price),
                    close_price=_decimal(row.close_price),
                    volume=(
                        Quantity(
                            value=Decimal(row.trade_volume),
                            unit=QuantityUnit.SHARE,
                        )
                        if row.trade_volume is not None
                        else None
                    ),
                    volume_status=(
                        "not_applicable"
                        if instrument.instrument_type is InstrumentType.INDEX
                        else "observed"
                        if row.trade_volume is not None
                        else "missing"
                    ),
                    price_basis="raw",
                    instrument_name=row.stock_name,
                    turnover_value=(
                        Decimal(row.trade_value)
                        if row.trade_value is not None
                        else None
                    ),
                    turnover_currency=(
                        "TWD" if row.trade_value is not None else None
                    ),
                    trade_count=row.transaction_count,
                    price_change=(
                        _decimal(row.price_change)
                        if row.price_change is not None
                        else None
                    ),
                    finalization=(
                        BarFinalization(row.finalization)
                        if row.finalization
                        else BarFinalization.FINAL
                    ),
                )
            except (TypeError, ValueError, ValidationError):
                rejections.append(
                    CandidateRowRejection(
                        provider=binding.provider,
                        source=source.source_name,
                        storage_row_id=row.id,
                        raw_result_id=(
                            raw_result.id if raw_result is not None else None
                        ),
                        event_date=row.trade_date,
                        reason_code="INVALID_CANONICAL_BAR",
                    )
                )
                continue

            bars_by_source.setdefault(source.source_name, []).append(bar)
            storage_ids_by_source.setdefault(source.source_name, []).append(row.id)
            raw_ids_by_source.setdefault(source.source_name, []).append(
                raw_result.id if raw_result is not None else None
            )

        if any(len(values) > query.max_rows for values in bars_by_source.values()):
            raise CandidateReadLimitExceeded(
                "daily candidate read exceeded max_rows; narrow the requested range"
            )

        series = tuple(
            PersistedBarSeries(
                provider=binding_by_source[source_name].provider,
                source=source_name,
                authority=binding_by_source[source_name].authority,
                provider_priority=priority_by_source.get(source_name, 100),
                bars=tuple(bars),
                storage_row_ids=tuple(storage_ids_by_source[source_name]),
                raw_result_ids=tuple(raw_ids_by_source[source_name]),
            )
            for source_name, bars in bars_by_source.items()
            if bars
        )
        return DailyBarCandidateRead(
            query=query,
            series=series,
            rejections=tuple(rejections),
            rows_examined=len(rows),
            rows_accepted=sum(len(values) for values in bars_by_source.values()),
        )

    def outward_state_metadata(
        self,
        observation_ids: tuple[str, ...],
    ) -> dict[str, dict[str, object | None]]:
        row_ids: list[int] = []
        for observation_id in observation_ids:
            if not observation_id.startswith("market_daily_price:"):
                continue
            try:
                row_ids.append(int(observation_id.rsplit(":", 1)[1]))
            except ValueError:
                continue
        if not row_ids:
            return {}
        rows = (
            self._db.query(MarketDailyPrice)
            .filter(MarketDailyPrice.id.in_(row_ids))
            .all()
        )
        reconciliations = (
            self._db.query(MarketDailyPriceReconciliation)
            .filter(MarketDailyPriceReconciliation.daily_price_id.in_(row_ids))
            .order_by(
                MarketDailyPriceReconciliation.checked_at.desc(),
                MarketDailyPriceReconciliation.id.desc(),
            )
            .all()
        )
        latest_by_row: dict[int, MarketDailyPriceReconciliation] = {}
        for item in reconciliations:
            latest_by_row.setdefault(item.daily_price_id, item)
        return {
            f"market_daily_price:{row.id}": {
                "official": row.official,
                "release_status": row.release_status,
                "reconciliation_status": (
                    latest_by_row[row.id].status
                    if row.id in latest_by_row
                    else row.reconciliation_status
                ),
                "persisted": True,
                "source_interval": "1d",
            }
            for row in rows
        }

    def load_market_universe(
        self,
        *,
        trade_date: date,
        include_etf: bool = False,
        venue: str | None = None,
        symbols: tuple[str, ...] | None = None,
        max_rows: int = 5000,
    ) -> TaiwanOfficialDailyUniverseRead:
        """Load an exact completed-session universe through official lineage.

        The repository applies the same source identity, receipt release and
        required-OHLC gates as the per-instrument candidate path, then selects
        one deterministic provider candidate per stock.  Consumers therefore
        never interpret raw duplicate rows as separate market observations.
        """

        if max_rows < 1 or max_rows > 20_000:
            raise ValueError("Taiwan universe read max_rows must be between 1 and 20000")
        normalized_venue = str(venue or "").strip().upper() or None
        if normalized_venue not in {None, "TWSE", "TPEX"}:
            raise ValueError("Taiwan universe venue must be TWSE or TPEX")
        normalized_symbols = tuple(
            dict.fromkeys(
                value.strip().upper()
                for value in (symbols or ())
                if value and value.strip()
            )
        )
        if len(normalized_symbols) > 500:
            raise ValueError("Taiwan bounded universe symbols cannot exceed 500")
        source_to_binding = {
            binding.source_name: binding
            for bindings in _SOURCES_BY_VENUE.values()
            for binding in bindings
        }
        instrument_types = ["stock"]
        if include_etf:
            instrument_types.extend(("etf", "exchange_traded_fund"))
        universe_query = (
            self._db.query(StockMaster.stock_id, StockMaster.market)
            .filter(StockMaster.is_active.is_(True))
            .filter(StockMaster.market.in_(("TWSE", "TPEX")))
            .filter(func.lower(StockMaster.instrument_type).in_(instrument_types))
        )
        if normalized_venue is not None:
            universe_query = universe_query.filter(
                func.upper(StockMaster.market) == normalized_venue
            )
        if symbols is not None:
            if not normalized_symbols:
                return TaiwanOfficialDailyUniverseRead(
                    trade_date=trade_date,
                    limitations=("REQUESTED_STOCK_UNIVERSE_EMPTY",),
                )
            universe_query = universe_query.filter(
                StockMaster.stock_id.in_(normalized_symbols)
            )
        universe_rows = (
            universe_query.order_by(StockMaster.stock_id.asc())
            .limit(max_rows + 1)
            .all()
        )
        if len(universe_rows) > max_rows:
            raise CandidateReadLimitExceeded(
                "Taiwan universe instrument read exceeded max_rows"
            )
        universe_symbols = tuple(str(row.stock_id) for row in universe_rows)
        universe_counts: dict[str, int] = {"TWSE": 0, "TPEX": 0}
        for row in universe_rows:
            market = str(row.market or "").strip().upper()
            if market in universe_counts:
                universe_counts[market] += 1
        if not universe_symbols:
            return TaiwanOfficialDailyUniverseRead(
                trade_date=trade_date,
                limitations=("ACTIVE_STOCK_UNIVERSE_EMPTY",),
            )
        rows = (
            self._db.query(
                MarketDailyPrice,
                RawFetchResult,
                SourceRegistry,
                StockMaster,
            )
            .options(load_only(*_RAW_FETCH_LINEAGE_COLUMNS))
            .join(RawFetchResult, RawFetchResult.id == MarketDailyPrice.raw_result_id)
            .join(SourceRegistry, SourceRegistry.id == MarketDailyPrice.source_id)
            .join(StockMaster, StockMaster.stock_id == MarketDailyPrice.stock_id)
            .filter(MarketDailyPrice.trade_date == trade_date)
            .filter(SourceRegistry.source_name.in_(tuple(source_to_binding)))
            .filter(MarketDailyPrice.stock_id.in_(universe_symbols))
            .order_by(
                MarketDailyPrice.stock_id.asc(),
                SourceRegistry.priority.asc(),
                MarketDailyPrice.id.desc(),
            )
            .limit(max_rows + 1)
            .all()
        )
        if len(rows) > max_rows:
            raise CandidateReadLimitExceeded(
                "Taiwan universe daily read exceeded max_rows"
            )

        candidates: dict[str, list[tuple[int, BarObservation]]] = {}
        rejected = 0
        for row, raw_result, source, stock in rows:
            binding = source_to_binding.get(source.source_name)
            if binding is None or str(stock.market or "").strip().upper() != binding.venue:
                rejected += 1
                continue
            if not _receipt_is_release_qualified(
                trade_date=row.trade_date,
                fetched_at=raw_result.fetched_at,
            ) or _missing_ohlc(row):
                rejected += 1
                continue
            if str(source.reliability_level or "").strip().lower() not in (
                _TRUSTED_OFFICIAL_RELIABILITY
            ):
                rejected += 1
                continue
            instrument_type = (
                InstrumentType.ETF
                if "etf" in str(stock.instrument_type or "").strip().lower()
                else InstrumentType.STOCK
            )
            try:
                bar = BarObservation(
                    instrument=InstrumentKey(
                        market=Market.TW,
                        symbol=row.stock_id,
                        instrument_type=instrument_type,
                        venue=binding.venue,
                    ),
                    lineage=SourceLineage(
                        provider=binding.provider,
                        source=source.source_name,
                        authority=AuthorityClass.EXCHANGE,
                        raw_contract_version=raw_result.parser_version or source.parser_type,
                        event_at=datetime.combine(row.trade_date, time(13, 30), tzinfo=TAIWAN_TZ),
                        fetched_at=_as_aware_utc(raw_result.fetched_at),
                        cache_hit=True,
                        observation_id=f"market_daily_price:{row.id}",
                        raw_receipt_id=f"raw_fetch_result:{raw_result.id}",
                        content_hash=raw_result.content_hash,
                    ),
                    interval="1d",
                    start_at=datetime.combine(row.trade_date, time(9), tzinfo=TAIWAN_TZ),
                    end_at=datetime.combine(row.trade_date, time(13, 30), tzinfo=TAIWAN_TZ),
                    open_price=_decimal(row.open_price),
                    high_price=_decimal(row.high_price),
                    low_price=_decimal(row.low_price),
                    close_price=_decimal(row.close_price),
                    volume=(
                        Quantity(value=Decimal(row.trade_volume), unit=QuantityUnit.SHARE)
                        if row.trade_volume is not None
                        else None
                    ),
                    instrument_name=row.stock_name or stock.stock_name,
                    turnover_value=(
                        Decimal(row.trade_value) if row.trade_value is not None else None
                    ),
                    turnover_currency="TWD" if row.trade_value is not None else None,
                    trade_count=row.transaction_count,
                    price_change=(
                        _decimal(row.price_change) if row.price_change is not None else None
                    ),
                    finalization=BarFinalization.FINAL,
                )
            except (TypeError, ValueError, ValidationError):
                rejected += 1
                continue
            candidates.setdefault(row.stock_id, []).append(
                (max(int(source.priority), 0), bar)
            )

        selected = tuple(
            sorted(
                (
                    min(
                        values,
                        key=lambda item: (
                            item[0],
                            item[1].lineage.provider,
                            item[1].lineage.source,
                            item[1].lineage.observation_id or "",
                        ),
                    )[1]
                    for values in candidates.values()
                ),
                key=lambda bar: bar.instrument.symbol,
            )
        )
        duplicate_count = sum(max(len(values) - 1, 0) for values in candidates.values())
        selected_counts: dict[str, int] = {"TWSE": 0, "TPEX": 0}
        for bar in selected:
            venue = str(bar.instrument.venue or "").strip().upper()
            if venue in selected_counts:
                selected_counts[venue] += 1
        limitations: list[str] = []
        if rejected:
            limitations.append("DAILY_UNIVERSE_CANDIDATES_REJECTED")
        if duplicate_count:
            limitations.append("DAILY_UNIVERSE_DUPLICATE_CANDIDATES_RECONCILED")
        return TaiwanOfficialDailyUniverseRead(
            trade_date=trade_date,
            bars=selected,
            universe_count=len(universe_symbols),
            universe_count_by_market=tuple(universe_counts.items()),
            selected_count_by_market=tuple(selected_counts.items()),
            rows_examined=len(rows),
            rows_rejected=rejected,
            duplicate_candidate_count=duplicate_count,
            limitations=tuple(limitations),
        )

    def lineage_metadata(
        self,
        observation_ids: tuple[str, ...],
    ) -> dict[str, dict[str, object]]:
        """Return compatibility-only storage identity for selected observations."""

        row_ids: list[int] = []
        for value in observation_ids:
            prefix, separator, raw_id = str(value or "").partition(":")
            if prefix != "market_daily_price" or not separator:
                continue
            try:
                row_ids.append(int(raw_id))
            except ValueError:
                continue
        if not row_ids:
            return {}
        rows = (
            self._db.query(MarketDailyPrice, SourceRegistry)
            .join(SourceRegistry, SourceRegistry.id == MarketDailyPrice.source_id)
            .filter(MarketDailyPrice.id.in_(tuple(set(row_ids))))
            .all()
        )
        return {
            f"market_daily_price:{row.id}": {
                "id": row.id,
                "source_id": row.source_id,
                "source_name": source.source_name,
                "raw_result_id": row.raw_result_id,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
            for row, source in rows
        }


__all__ = [
    "TaiwanOfficialDailyBarRepository",
    "TaiwanOfficialDailyUniverseRead",
]
