from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Query, Session

from app.db.models import (
    MacroSeriesObservation,
    USDailyPrice,
    USCompanyProfile,
    USCorporateAction,
    USSecCompanyFact,
    USSec13FFiling,
    USSec13FSymbolQuarter,
    USSec13FWarehousePartition,
    USSecDatasetRelease,
    USSecOwnershipFiling,
    USSecOwnershipSyncState,
    USSecOwnershipTransaction,
    USShortVolumeDaily,
    USStockMaster,
    USSecurityIdentifierMap,
)
from app.market.calendar_status import expected_us_trade_date
from app.observability.provider_health import (
    enrich_source_health_entries,
    sync_source_health_snapshots,
)
from app.observability.source_health_contract import (
    daily_row_status,
    freshness_lag_days as _freshness_lag,
    generated_at as _generated_at,
    summarize_source_health,
)
from app.us_market.sources import normalize_us_symbol
from app.us_market.market_data_policy import us_provider_order
from app.us_market.sec_fundamentals.freshness import evaluate_sec_filing_freshness
from app.us_market.sec_fundamentals.submissions import (
    SEC_SUBMISSIONS_CACHE,
    submissions_cache_path_for_session,
)
from app.config import settings
from app.us_market.trading_calendar import (
    is_us_daily_price_finalized,
    us_daily_price_finalization_time,
)


DAILY_PROVIDER_ORDER = us_provider_order("daily.ohlcv")


@dataclass(frozen=True)
class USSourceHealthEntry:
    resource: str
    provider: str
    target: str
    status: str
    ok: bool
    row_count: int
    latest_data_date: date | None = None
    latest_fetched_at: datetime | None = None
    expected_data_date: date | None = None
    freshness_lag_days: int | None = None
    latest_row_finalized: bool | None = None
    latest_finalized_data_date: date | None = None
    finalization_expected_at: datetime | None = None
    source_url: str | None = None
    data_quality: str = "unknown"
    reason: str = ""
    rate_limited: bool = False
    retry_after_seconds: int | None = None
    error_message: str | None = None
    latest_accession_number: str | None = None
    expected_accession_number: str | None = None
    latest_filing_date: date | None = None
    last_checked_at: datetime | None = None
    freshness_basis: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource": self.resource,
            "provider": self.provider,
            "target": self.target,
            "status": self.status,
            "ok": self.ok,
            "row_count": self.row_count,
            "latest_data_date": self.latest_data_date.isoformat() if self.latest_data_date else None,
            "latest_fetched_at": self.latest_fetched_at.isoformat() if self.latest_fetched_at else None,
            "expected_data_date": self.expected_data_date.isoformat() if self.expected_data_date else None,
            "freshness_lag_days": self.freshness_lag_days,
            "latest_row_finalized": self.latest_row_finalized,
            "latest_finalized_data_date": (
                self.latest_finalized_data_date.isoformat()
                if self.latest_finalized_data_date
                else None
            ),
            "finalization_expected_at": (
                self.finalization_expected_at.isoformat()
                if self.finalization_expected_at
                else None
            ),
            "source_url": self.source_url,
            "data_quality": self.data_quality,
            "reason": self.reason,
            "rate_limited": self.rate_limited,
            "retry_after_seconds": self.retry_after_seconds,
            "error_message": self.error_message,
            "latest_accession_number": self.latest_accession_number,
            "expected_accession_number": self.expected_accession_number,
            "latest_filing_date": (
                self.latest_filing_date.isoformat() if self.latest_filing_date else None
            ),
            "last_checked_at": (
                self.last_checked_at.isoformat() if self.last_checked_at else None
            ),
            "freshness_basis": self.freshness_basis,
        }


def _target(*, symbol: str | None = None, series_id: str | None = None) -> str:
    return symbol or series_id or "all"


def _status_for(
    *,
    row_count: int,
    latest_data_date: date | None,
    expected_data_date: date | None = None,
    freshness_required: bool = False,
) -> tuple[str, bool, str, str]:
    return daily_row_status(
        row_count=row_count,
        latest_data_date=latest_data_date,
        expected_data_date=expected_data_date,
        freshness_required=freshness_required,
        empty_reason="No local rows are available for this provider/resource.",
        current_reason="Latest local row is aligned with the expected US trade date.",
        available_reason="Local rows are available; no daily freshness target is enforced.",
    )


def _latest_or_none(query: Query, *order_by):
    return query.order_by(*order_by).first()


def _entry_from_query(
    *,
    query: Query,
    resource: str,
    provider: str,
    target: str,
    latest_data_attr: str | None,
    latest_fetched_attr: str | None,
    expected_data_date: date | None = None,
    freshness_required: bool = False,
    source_url_attr: str | None = "source_url",
    order_by: tuple[Any, ...],
) -> USSourceHealthEntry:
    row_count = query.count()
    latest = _latest_or_none(query, *order_by)
    latest_data_date = getattr(latest, latest_data_attr, None) if latest and latest_data_attr else None
    latest_fetched_at = getattr(latest, latest_fetched_attr, None) if latest and latest_fetched_attr else None
    source_url = getattr(latest, source_url_attr, None) if latest and source_url_attr else None
    status_value, ok, data_quality, reason = _status_for(
        row_count=row_count,
        latest_data_date=latest_data_date,
        expected_data_date=expected_data_date,
        freshness_required=freshness_required,
    )

    return USSourceHealthEntry(
        resource=resource,
        provider=provider,
        target=target,
        status=status_value,
        ok=ok,
        row_count=row_count,
        latest_data_date=latest_data_date,
        latest_fetched_at=latest_fetched_at,
        expected_data_date=expected_data_date,
        freshness_lag_days=_freshness_lag(expected_data_date, latest_data_date),
        source_url=source_url,
        data_quality=data_quality,
        reason=reason,
    )


def _daily_price_entries(
    db: Session,
    *,
    symbol: str | None,
    expected_daily_price_date: date | None,
) -> list[USSourceHealthEntry]:
    entries: list[USSourceHealthEntry] = []
    target = _target(symbol=symbol)

    for provider in DAILY_PROVIDER_ORDER:
        query = db.query(USDailyPrice).filter(USDailyPrice.provider == provider)
        if symbol is not None:
            query = query.filter(USDailyPrice.symbol == symbol)

        row_count = query.count()
        order_by = (
            USDailyPrice.trade_date.desc(),
            USDailyPrice.fetched_at.desc(),
            USDailyPrice.id.desc(),
        )
        latest = _latest_or_none(query, *order_by)

        if latest is None:
            entries.append(
                USSourceHealthEntry(
                    resource="daily_price",
                    provider=provider,
                    target=target,
                    status="empty",
                    ok=False,
                    row_count=row_count,
                    expected_data_date=expected_daily_price_date,
                    data_quality="empty",
                    reason="No local rows are available for this provider/resource.",
                )
            )
            continue

        latest_row_finalized = is_us_daily_price_finalized(
            trade_date=latest.trade_date,
            fetched_at=latest.fetched_at,
        )
        finalization_expected_at = us_daily_price_finalization_time(latest.trade_date)
        latest_finalized_data_date = latest.trade_date if latest_row_finalized else None

        if not latest_row_finalized:
            older_candidates = (
                query.filter(USDailyPrice.trade_date < latest.trade_date)
                .order_by(*order_by)
                .limit(100)
                .all()
            )
            for candidate in older_candidates:
                if is_us_daily_price_finalized(
                    trade_date=candidate.trade_date,
                    fetched_at=candidate.fetched_at,
                ):
                    latest_finalized_data_date = candidate.trade_date
                    break

            entries.append(
                USSourceHealthEntry(
                    resource="daily_price",
                    provider=provider,
                    target=target,
                    status="partial",
                    ok=False,
                    row_count=row_count,
                    latest_data_date=latest.trade_date,
                    latest_fetched_at=latest.fetched_at,
                    expected_data_date=expected_daily_price_date,
                    freshness_lag_days=_freshness_lag(
                        expected_daily_price_date,
                        latest_finalized_data_date,
                    ),
                    latest_row_finalized=False,
                    latest_finalized_data_date=latest_finalized_data_date,
                    finalization_expected_at=finalization_expected_at,
                    source_url=latest.source_url,
                    data_quality="partial",
                    reason=(
                        f"Latest local row for {latest.trade_date.isoformat()} was fetched "
                        f"before its daily finalization time "
                        f"{finalization_expected_at.isoformat()}; the row is excluded "
                        "from completed daily data."
                    ),
                )
            )
            continue

        status_value, ok, data_quality, reason = _status_for(
            row_count=row_count,
            latest_data_date=latest.trade_date,
            expected_data_date=expected_daily_price_date,
            freshness_required=True,
        )
        entries.append(
            USSourceHealthEntry(
                resource="daily_price",
                provider=provider,
                target=target,
                status=status_value,
                ok=ok,
                row_count=row_count,
                latest_data_date=latest.trade_date,
                latest_fetched_at=latest.fetched_at,
                expected_data_date=expected_daily_price_date,
                freshness_lag_days=_freshness_lag(
                    expected_daily_price_date,
                    latest.trade_date,
                ),
                latest_row_finalized=True,
                latest_finalized_data_date=latest.trade_date,
                finalization_expected_at=finalization_expected_at,
                source_url=latest.source_url,
                data_quality=data_quality,
                reason=reason,
            )
        )

    return entries


def _symbol_master_entry(db: Session, *, symbol: str | None) -> USSourceHealthEntry:
    query = db.query(USStockMaster)
    if symbol is not None:
        query = query.filter(USStockMaster.symbol == symbol)

    return _entry_from_query(
        query=query,
        resource="symbol_master",
        provider="nasdaq_trader+sec_edgar+yahoo_chart",
        target=_target(symbol=symbol),
        latest_data_attr=None,
        latest_fetched_attr="last_seen_at",
        source_url_attr=None,
        order_by=(USStockMaster.last_seen_at.desc(), USStockMaster.id.desc()),
    )


def _profile_entry(db: Session, *, symbol: str | None) -> USSourceHealthEntry:
    query = db.query(USCompanyProfile)
    if symbol is not None:
        query = query.filter(USCompanyProfile.symbol == symbol)

    return _entry_from_query(
        query=query,
        resource="profile",
        provider="alphavantage",
        target=_target(symbol=symbol),
        latest_data_attr="latest_quarter",
        latest_fetched_attr="fetched_at",
        order_by=(USCompanyProfile.fetched_at.desc(), USCompanyProfile.id.desc()),
    )


def _sec_facts_entry(
    db: Session,
    *,
    symbol: str | None,
    now: datetime | None,
) -> USSourceHealthEntry:
    query = db.query(USSecCompanyFact)
    if symbol is not None:
        query = query.filter(USSecCompanyFact.symbol == symbol)

    if symbol is None:
        return _entry_from_query(
            query=query,
            resource="sec_facts",
            provider="sec_edgar",
            target="all",
            latest_data_attr="period_end_date",
            latest_fetched_attr="fetched_at",
            order_by=(
                USSecCompanyFact.period_end_date.desc(),
                USSecCompanyFact.fetched_at.desc(),
                USSecCompanyFact.id.desc(),
            ),
        )

    row_count = query.count()
    latest = (
        query.filter(USSecCompanyFact.form.in_(("10-K", "10-K/A", "10-Q", "10-Q/A")))
        .filter(USSecCompanyFact.accession_number.isnot(None))
        .order_by(
            USSecCompanyFact.filed_date.desc(),
            USSecCompanyFact.accession_number.desc(),
            USSecCompanyFact.fetched_at.desc(),
            USSecCompanyFact.id.desc(),
        )
        .first()
    )
    stock = (
        db.query(USStockMaster)
        .filter(USStockMaster.symbol == symbol)
        .first()
    )
    snapshot = (
        SEC_SUBMISSIONS_CACHE.get(
            stock.cik,
            cache_path=submissions_cache_path_for_session(
                db,
                configured_path=settings.us_sec_submissions_cache_path,
            ),
        )
        if stock and stock.cik
        else None
    )
    remote = snapshot.latest_relevant_filing if snapshot else None
    freshness = evaluate_sec_filing_freshness(
        local_accession_number=latest.accession_number if latest else None,
        local_filing_date=latest.filed_date if latest else None,
        local_fetched_at=latest.fetched_at if latest else None,
        expected_accession_number=remote.accession_number if remote else None,
        expected_filing_date=remote.filing_date if remote else None,
        last_checked_at=snapshot.fetched_at if snapshot else None,
        now=now,
        stale_after=timedelta(hours=24),
    )
    status = "empty" if freshness.status == "missing" else freshness.status
    reason = {
        "current": "Local SEC facts match the latest checked filing accession or were refreshed within the filing freshness window.",
        "stale": "Local SEC facts require an explicit filing-aware refresh.",
        "empty": "No local SEC filing facts are available for this symbol.",
    }.get(status, "SEC filing freshness is unknown.")
    return USSourceHealthEntry(
        resource="sec_facts",
        provider="sec_edgar",
        target=symbol,
        status=status,
        ok=freshness.decision_usable,
        row_count=row_count,
        latest_data_date=latest.period_end_date if latest else None,
        latest_fetched_at=latest.fetched_at if latest else None,
        source_url=latest.source_url if latest else None,
        data_quality=status,
        reason=reason,
        latest_accession_number=freshness.local_accession_number,
        expected_accession_number=freshness.expected_accession_number,
        latest_filing_date=freshness.latest_filing_date,
        last_checked_at=freshness.last_checked_at,
        freshness_basis=freshness.basis,
    )


def _sec_insider_transactions_entry(
    db: Session,
    *,
    symbol: str | None,
    now: datetime | None,
) -> USSourceHealthEntry:
    filing_query = db.query(USSecOwnershipFiling)
    transaction_query = (
        db.query(USSecOwnershipTransaction)
        .join(
            USSecOwnershipFiling,
            USSecOwnershipTransaction.filing_id == USSecOwnershipFiling.id,
        )
    )
    state_query = db.query(USSecOwnershipSyncState)
    if symbol is not None:
        filing_query = filing_query.filter(USSecOwnershipFiling.issuer_trading_symbol == symbol)
        transaction_query = transaction_query.filter(
            USSecOwnershipFiling.issuer_trading_symbol == symbol
        )
        state_query = state_query.filter(USSecOwnershipSyncState.symbol == symbol)

    latest_filing = filing_query.order_by(
        USSecOwnershipFiling.filing_date.desc(),
        USSecOwnershipFiling.accepted_at.desc(),
        USSecOwnershipFiling.id.desc(),
    ).first()
    state = state_query.order_by(
        USSecOwnershipSyncState.last_checked_at.desc(),
        USSecOwnershipSyncState.id.desc(),
    ).first()
    target = _target(symbol=symbol)
    if state is None:
        return USSourceHealthEntry(
            resource="sec_insider_transactions",
            provider="sec_edgar",
            target=target,
            status="empty",
            ok=False,
            row_count=transaction_query.count(),
            latest_data_date=latest_filing.filing_date if latest_filing else None,
            latest_fetched_at=latest_filing.fetched_at if latest_filing else None,
            source_url=latest_filing.source_url if latest_filing else None,
            data_quality="missing",
            reason="SEC Form 4 submissions have not been checked for this target.",
            latest_accession_number=(
                latest_filing.accession_number if latest_filing else None
            ),
            latest_filing_date=latest_filing.filing_date if latest_filing else None,
            freshness_basis="observation_missing",
        )

    observed_at = state.last_checked_at
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    if observed_at is not None and observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    observation_stale = (
        observed_at is None
        or current_time - observed_at
        > timedelta(hours=settings.us_sec_ownership_observation_hours)
    )
    status = "stale" if observation_stale else state.status
    ok = status in {"current", "ready_empty"}
    if status == "ready_empty":
        reason = "SEC submissions were checked within the observation window and contained no Form 4 filings in scope."
    elif status == "current":
        reason = "Local Form 4 transactions match the latest bounded SEC submissions observation."
    elif status == "stale":
        reason = "The last SEC Form 4 submissions observation is outside the freshness window."
    elif status == "partial":
        reason = "The latest SEC Form 4 synchronization completed with visible partial failures."
    else:
        reason = "SEC Form 4 synchronization did not produce decision-usable data."

    return USSourceHealthEntry(
        resource="sec_insider_transactions",
        provider="sec_edgar",
        target=target,
        status=status,
        ok=ok,
        row_count=transaction_query.count(),
        latest_data_date=latest_filing.filing_date if latest_filing else state.latest_filing_date,
        latest_fetched_at=latest_filing.fetched_at if latest_filing else state.last_success_at,
        source_url=state.source_url or (latest_filing.source_url if latest_filing else None),
        data_quality=status,
        reason=reason,
        latest_accession_number=(
            state.latest_accession_number
            or (latest_filing.accession_number if latest_filing else None)
        ),
        latest_filing_date=state.latest_filing_date,
        last_checked_at=state.last_checked_at,
        freshness_basis="sec_submissions_observation_window",
    )


def _sec_institutional_holdings_entry(
    db: Session,
    *,
    symbol: str | None,
) -> USSourceHealthEntry:
    partitions = (
        db.query(USSec13FWarehousePartition)
        .filter(
            USSec13FWarehousePartition.is_current.is_(True),
            USSec13FWarehousePartition.status == "completed",
        )
        .order_by(USSec13FWarehousePartition.period_key.desc())
        .all()
    )
    target = _target(symbol=symbol)
    if not partitions:
        return USSourceHealthEntry(
            resource="sec_institutional_holdings",
            provider="sec_edgar+openfigi",
            target=target,
            status="empty",
            ok=False,
            row_count=0,
            data_quality="missing",
            reason="No promoted SEC Form 13F analytical partition is available.",
            freshness_basis="promoted_sec_form13f_release_missing",
        )
    latest_partition = partitions[0]
    release = (
        db.query(USSecDatasetRelease)
        .filter(USSecDatasetRelease.id == latest_partition.dataset_release_id)
        .first()
    )
    latest_filing_date = db.query(func.max(USSec13FFiling.filing_date)).scalar()
    row_count = sum(item.row_count for item in partitions)
    if symbol is not None:
        projection = (
            db.query(USSec13FSymbolQuarter)
            .filter(
                USSec13FSymbolQuarter.symbol == symbol,
                USSec13FSymbolQuarter.mapping_version == settings.openfigi_mapping_version,
            )
            .order_by(USSec13FSymbolQuarter.report_period_end.desc())
            .first()
        )
        if projection is None:
            status = "partial"
            ok = False
            data_quality = "missing_mapping"
            reason = (
                "SEC Form 13F partitions are current, but this symbol has no approved "
                "versioned CUSIP mapping projection."
            )
            latest_data_date = None
        else:
            status = "current"
            ok = True
            data_quality = "current"
            reason = (
                "The symbol has an approved CUSIP mapping and a projection from the latest "
                "promoted SEC Form 13F release; global unresolved mapping remains visible in coverage."
            )
            latest_data_date = projection.report_period_end
            row_count = projection.reported_row_count
    else:
        approved = (
            db.query(USSecurityIdentifierMap)
            .filter(
                USSecurityIdentifierMap.mapping_version == settings.openfigi_mapping_version,
                USSecurityIdentifierMap.status == "approved",
            )
            .count()
        )
        distinct_cusips = sum(item.distinct_cusip_count for item in partitions)
        status = "current" if approved >= distinct_cusips and distinct_cusips else "partial"
        ok = status == "current"
        data_quality = status
        reason = (
            "SEC Form 13F partitions are promoted, but versioned symbol mapping coverage is partial."
            if status == "partial"
            else "SEC Form 13F partitions and identifier mappings are current."
        )
        latest_data_date = latest_filing_date
    return USSourceHealthEntry(
        resource="sec_institutional_holdings",
        provider="sec_edgar+openfigi",
        target=target,
        status=status,
        ok=ok,
        row_count=row_count,
        latest_data_date=latest_data_date,
        latest_fetched_at=latest_partition.updated_at,
        source_url=release.source_url if release else None,
        data_quality=data_quality,
        reason=reason,
        latest_filing_date=latest_filing_date,
        last_checked_at=release.checked_at if release else None,
        freshness_basis="latest_promoted_sec_form13f_dataset_release",
    )


def _corporate_actions_entry(db: Session, *, symbol: str | None) -> USSourceHealthEntry:
    query = db.query(USCorporateAction)
    if symbol is not None:
        query = query.filter(USCorporateAction.symbol == symbol)

    return _entry_from_query(
        query=query,
        resource="corporate_actions",
        provider="alphavantage",
        target=_target(symbol=symbol),
        latest_data_attr="event_date",
        latest_fetched_attr="fetched_at",
        order_by=(
            USCorporateAction.event_date.desc(),
            USCorporateAction.fetched_at.desc(),
            USCorporateAction.id.desc(),
        ),
    )


def _short_volume_entry(
    db: Session,
    *,
    symbol: str | None,
    expected_daily_price_date: date | None,
) -> USSourceHealthEntry:
    query = db.query(USShortVolumeDaily)
    if symbol is not None:
        query = query.filter(USShortVolumeDaily.symbol == symbol)

    return _entry_from_query(
        query=query,
        resource="short_volume",
        provider="finra",
        target=_target(symbol=symbol),
        latest_data_attr="trade_date",
        latest_fetched_attr="fetched_at",
        expected_data_date=expected_daily_price_date,
        freshness_required=True,
        order_by=(
            USShortVolumeDaily.trade_date.desc(),
            USShortVolumeDaily.fetched_at.desc(),
            USShortVolumeDaily.id.desc(),
        ),
    )


def _macro_entry(db: Session, *, series_id: str | None) -> USSourceHealthEntry:
    normalized_series_id = series_id.strip().upper() if series_id else None
    query = db.query(MacroSeriesObservation)
    if normalized_series_id is not None:
        query = query.filter(MacroSeriesObservation.series_id == normalized_series_id)

    return _entry_from_query(
        query=query,
        resource="macro_series",
        provider="fred",
        target=_target(series_id=normalized_series_id),
        latest_data_attr="observation_date",
        latest_fetched_attr="fetched_at",
        order_by=(
            MacroSeriesObservation.observation_date.desc(),
            MacroSeriesObservation.fetched_at.desc(),
            MacroSeriesObservation.id.desc(),
        ),
    )


def _summary(entries: list[USSourceHealthEntry]) -> dict[str, int]:
    return summarize_source_health(
        entries,
        counted_statuses=("empty", "stale", "partial", "error", "blocked"),
    )


def build_us_source_health(
    db: Session,
    *,
    symbol: str | None = None,
    series_id: str | None = None,
    now: datetime | None = None,
    expected_daily_price_date: date | None = None,
) -> dict[str, Any]:
    normalized_symbol = normalize_us_symbol(symbol) if symbol else None
    normalized_series_id = series_id.strip().upper() if series_id else None
    expected_date = expected_daily_price_date or expected_us_trade_date(
        "us_daily_price",
        now=now,
    )
    entries = [
        _symbol_master_entry(db, symbol=normalized_symbol),
        *_daily_price_entries(
            db,
            symbol=normalized_symbol,
            expected_daily_price_date=expected_date,
        ),
        _profile_entry(db, symbol=normalized_symbol),
        _sec_facts_entry(db, symbol=normalized_symbol, now=now),
        _sec_insider_transactions_entry(db, symbol=normalized_symbol, now=now),
        _sec_institutional_holdings_entry(db, symbol=normalized_symbol),
        _corporate_actions_entry(db, symbol=normalized_symbol),
        _short_volume_entry(
            db,
            symbol=normalized_symbol,
            expected_daily_price_date=expected_date,
        ),
        _macro_entry(db, series_id=normalized_series_id),
    ]
    generated_at = _generated_at()
    entry_dicts = enrich_source_health_entries(
        db,
        market="us",
        entries=[entry.to_dict() for entry in entries],
    )
    sync_source_health_snapshots(
        db,
        market="us",
        entries=entry_dicts,
        checked_at=generated_at,
    )

    return {
        "kind": "us_source_health",
        "generated_at": generated_at.isoformat(),
        "filters": {
            "symbol": normalized_symbol,
            "series_id": normalized_series_id,
        },
        "expected_daily_price_date": expected_date.isoformat() if expected_date else None,
        "summary": _summary(entries),
        "entries": entry_dicts,
    }


__all__ = [
    "USSourceHealthEntry",
    "build_us_source_health",
]
