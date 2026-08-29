from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from time import monotonic, sleep
from typing import Any, Callable, Protocol

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    MarketDailyPrice,
    MarketDatasetCoverageCheckpoint,
    StockMaster,
    utc_now,
)
from app.market.taiwan_rules import (
    TAIWAN_DAILY_PRICE_RELEASE_TIME,
    expected_daily_price_date,
)
from app.market.trading_calendar import TAIWAN_TZ, is_taiwan_trading_day
from app.market.tw_universe import list_taiwan_stock_universe
from app.market_data.dataset_lifecycle import (
    DatasetLifecycleContract,
    DatasetLifecycleEvaluation,
    dataset_lifecycle_contract,
    evaluate_lifecycle,
    require_refresh_contract,
)
from app.market_data.registry import ExpectedStatePolicy, RefreshBounds
from app.observability.provider_http import provider_http_failure
from app.pipelines.fetch_pipeline import refresh_source
from app.sources.defaults import (
    TPEX_DAILY_QUOTES_SOURCE_NAME,
    TWSE_DAILY_TRADING_SOURCE_NAME,
)
from app.sources.service import get_source_by_name


CHECKPOINT_VERSION = "omi.market.eod_coverage.v1"
FULL_MARKET_SCOPE_KIND = "full_market_stock_universe"
TW_SCOPE_KEY = "twse_tpex_active_ordinary_stocks"
US_SCOPE_KEY = "nasdaq_trader_active_non_etf_non_test_stocks"
TW_DATASET_ID = "tw.daily.ohlcv.full_market"
US_DATASET_ID = "us.daily.ohlcv.full_market"
TW_REFRESH_OPERATION = "tw.reconcile_full_market_eod"
US_REFRESH_OPERATION = "us.reconcile_full_market_eod"
ProgressCallback = Callable[[int | None, int | None, str | None], None]
TaiwanVenueRefresher = Callable[..., dict[str, Any]]


class USFullMarketEodPort(Protocol):
    """US-owned lifecycle port injected at the job/composition boundary."""

    def expected_trade_date(self, *, now: datetime | None = None) -> date: ...

    def compute_coverage(
        self,
        db: Session,
        *,
        expected_trade_date: date,
    ) -> "CoverageComputation": ...

    def refresh_symbol(
        self,
        db: Session,
        *,
        symbol: str,
        expected_trade_date: date,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class UniverseMember:
    symbol: str
    venue: str


@dataclass(frozen=True)
class IneligibleUniverseMember:
    symbol: str
    venue: str
    instrument_type: str
    reason: str


@dataclass(frozen=True)
class CoverageComputation:
    market: str
    dataset_id: str
    scope_key: str
    universe_source: str
    expected_trade_date: date
    latest_data_date: date | None
    universe_hash: str
    members: tuple[UniverseMember, ...]
    current_symbols: frozenset[str]
    partial_symbols: frozenset[str]
    stale_symbols: frozenset[str]
    missing_symbols: frozenset[str]
    ineligible_members: tuple[IneligibleUniverseMember, ...] = ()

    @property
    def universe_count(self) -> int:
        return len(self.members)

    @property
    def current_count(self) -> int:
        return len(self.current_symbols)

    @property
    def partial_count(self) -> int:
        return len(self.partial_symbols)

    @property
    def stale_count(self) -> int:
        return len(self.stale_symbols)

    @property
    def missing_count(self) -> int:
        return len(self.missing_symbols)

    @property
    def status(self) -> str:
        if self.universe_count == 0:
            return "unavailable"
        if self.current_count == self.universe_count:
            return "healthy"
        if self.current_count == 0 and self.partial_count == 0:
            if self.stale_count:
                return "stale"
            return "missing"
        return "partial"

    @property
    def unresolved_symbols(self) -> tuple[str, ...]:
        unresolved = self.partial_symbols | self.stale_symbols | self.missing_symbols
        return tuple(member.symbol for member in self.members if member.symbol in unresolved)

    def detail(self) -> dict[str, Any]:
        denominator = max(self.universe_count, 1)
        venue_breakdown: dict[str, dict[str, Any]] = {}
        for venue in sorted({member.venue for member in self.members}):
            venue_symbols = {
                member.symbol for member in self.members if member.venue == venue
            }
            venue_count = len(venue_symbols)
            current_count = len(venue_symbols & self.current_symbols)
            partial_count = len(venue_symbols & self.partial_symbols)
            stale_count = len(venue_symbols & self.stale_symbols)
            missing_count = len(venue_symbols & self.missing_symbols)
            venue_breakdown[venue] = {
                "universe_count": venue_count,
                "current_count": current_count,
                "partial_count": partial_count,
                "stale_count": stale_count,
                "missing_count": missing_count,
                "coverage_ratio": current_count / max(venue_count, 1),
                "status": (
                    "healthy"
                    if venue_count > 0 and current_count == venue_count
                    else "unavailable"
                    if venue_count == 0
                    else "partial"
                    if current_count or partial_count
                    else "stale"
                    if stale_count
                    else "missing"
                ),
            }
        symbol_classifications = [
            {
                "symbol": member.symbol,
                "venue": member.venue,
                "classification": (
                    "current"
                    if member.symbol in self.current_symbols
                    else "partial"
                    if member.symbol in self.partial_symbols
                    else "stale"
                    if member.symbol in self.stale_symbols
                    else "missing"
                ),
                "reason": (
                    "expected_session_usable_close_present"
                    if member.symbol in self.current_symbols
                    else "expected_session_row_close_missing"
                    if member.symbol in self.partial_symbols
                    else "latest_row_before_expected_session"
                    if member.symbol in self.stale_symbols
                    else "no_row_on_or_before_expected_session"
                ),
            }
            for member in self.members
        ]
        ineligible_classifications = [
            {
                "symbol": member.symbol,
                "venue": member.venue,
                "instrument_type": member.instrument_type,
                "classification": "not_eligible",
                "reason": member.reason,
            }
            for member in self.ineligible_members
        ]
        classification_counts = {
            "current": self.current_count,
            "partial": self.partial_count,
            "stale": self.stale_count,
            "missing": self.missing_count,
            "not_eligible": len(self.ineligible_members),
            "halted_or_suspended": 0,
        }
        classification_total = sum(classification_counts.values())
        instrument_inventory_count = self.universe_count + len(
            self.ineligible_members
        )
        return {
            "coverage_ratio": self.current_count / denominator,
            "observed_ratio": (self.current_count + self.partial_count) / denominator,
            "venue_breakdown": venue_breakdown,
            "current_sample": sorted(self.current_symbols)[:10],
            "partial_sample": sorted(self.partial_symbols)[:10],
            "stale_sample": sorted(self.stale_symbols)[:10],
            "missing_sample": sorted(self.missing_symbols)[:10],
            "instrument_inventory_count": instrument_inventory_count,
            "eligible_count": self.universe_count,
            "not_eligible_count": len(self.ineligible_members),
            "classification_counts": classification_counts,
            "classification_total": classification_total,
            "classification_invariant_satisfied": (
                classification_total == instrument_inventory_count
            ),
            "symbol_classifications": (
                symbol_classifications + ineligible_classifications
            ),
            "classification": {
                "current": "latest row is on expected_trade_date and has a usable close",
                "partial": "latest row is on expected_trade_date but has no usable close",
                "stale": "latest row is before expected_trade_date",
                "missing": "no row exists on or before expected_trade_date",
            },
            "limitations": [
                "Halt/suspension is never inferred from a missing row; the halted_or_suspended class remains zero until authoritative instrument-status evidence is connected.",
                "A no-close same-day observation remains partial instead of being coerced to zero.",
            ],
        }


def eod_lifecycle_contract(market: str) -> DatasetLifecycleContract:
    normalized = normalize_coverage_market(market)
    dataset_id = TW_DATASET_ID if normalized == "TW" else US_DATASET_ID
    lifecycle = dataset_lifecycle_contract(dataset_id)
    if lifecycle.expected_state_policy is not ExpectedStatePolicy.LATEST_COMPLETED_SESSION:
        raise RuntimeError(
            f"full-market EOD dataset '{dataset_id}' must use latest-completed policy"
        )
    if lifecycle.scope_kind != FULL_MARKET_SCOPE_KIND:
        raise RuntimeError(
            f"full-market EOD dataset '{dataset_id}' has incompatible scope"
        )
    return lifecycle


def eod_reconcile_bounds(market: str) -> RefreshBounds:
    normalized = normalize_coverage_market(market)
    lifecycle = eod_lifecycle_contract(normalized)
    operation = (
        TW_REFRESH_OPERATION if normalized == "TW" else US_REFRESH_OPERATION
    )
    return require_refresh_contract(lifecycle, operation=operation)


def normalize_coverage_market(value: str) -> str:
    normalized = str(value or "").strip().upper()
    if normalized not in {"TW", "US"}:
        raise ValueError("market must be one of: TW, US.")
    return normalized


def expected_eod_trade_date(
    market: str,
    *,
    now: datetime | None = None,
    us_port: USFullMarketEodPort | None = None,
) -> date:
    normalized = normalize_coverage_market(market)
    eod_lifecycle_contract(normalized)
    if normalized == "TW":
        return expected_daily_price_date(now=now)
    if us_port is None:
        raise ValueError("US EOD expected state requires an injected market-owned port")
    return us_port.expected_trade_date(now=now)


def taiwan_bulk_eod_refresh_window(
    *,
    expected_trade_date: date,
    now: datetime | None = None,
) -> tuple[bool, datetime | None, str]:
    local_now = now or datetime.now(TAIWAN_TZ)
    if local_now.tzinfo is None:
        local_now = local_now.replace(tzinfo=TAIWAN_TZ)
    else:
        local_now = local_now.astimezone(TAIWAN_TZ)
    latest_expected = expected_daily_price_date(now=local_now)
    if not is_taiwan_trading_day(expected_trade_date):
        return False, None, "requested_date_is_not_trading_session"
    release_at = datetime.combine(
        local_now.date(),
        TAIWAN_DAILY_PRICE_RELEASE_TIME,
        tzinfo=TAIWAN_TZ,
    )
    if expected_trade_date > latest_expected:
        if (
            expected_trade_date == local_now.date()
            and is_taiwan_trading_day(local_now.date())
        ):
            return (
                False,
                release_at.astimezone(timezone.utc),
                "current_trading_session_not_finalized",
            )
        return False, None, "requested_date_is_not_released"
    if not is_taiwan_trading_day(local_now.date()):
        return True, None, "closed_day_latest_bulk_snapshot"
    if expected_trade_date < local_now.date():
        return True, None, "released_historical_session"
    if local_now >= release_at and expected_trade_date == local_now.date():
        return True, None, "post_release_latest_bulk_snapshot"
    return (
        False,
        release_at.astimezone(timezone.utc),
        "current_trading_session_not_finalized",
    )


def _tw_universe(db: Session) -> tuple[UniverseMember, ...]:
    return tuple(
        UniverseMember(symbol=row.stock_id, venue=str(row.market or "").upper())
        for row in list_taiwan_stock_universe(db)
    )


def _tw_ineligible_universe(
    db: Session,
) -> tuple[IneligibleUniverseMember, ...]:
    rows = (
        db.query(StockMaster)
        .filter(StockMaster.is_active.is_(True))
        .filter(func.upper(StockMaster.market).in_(("TWSE", "TPEX")))
        .filter(func.lower(StockMaster.instrument_type) != "stock")
        .order_by(StockMaster.stock_id.asc())
        .all()
    )
    return tuple(
        IneligibleUniverseMember(
            symbol=row.stock_id,
            venue=str(row.market or "").upper(),
            instrument_type=str(row.instrument_type or "unknown"),
            reason="outside_active_ordinary_stock_dataset_scope",
        )
        for row in rows
    )


def build_eod_universe(db: Session, market: str) -> tuple[UniverseMember, ...]:
    if normalize_coverage_market(market) != "TW":
        raise ValueError("US universe ownership is outside Shared EOD lifecycle")
    return _tw_universe(db)


def _universe_hash(members: tuple[UniverseMember, ...]) -> str:
    payload = "\n".join(f"{member.venue}|{member.symbol}" for member in members)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _classify_symbols(
    *,
    members: tuple[UniverseMember, ...],
    latest_by_symbol: dict[str, date],
    usable_expected_symbols: set[str],
    expected_trade_date: date,
) -> tuple[frozenset[str], frozenset[str], frozenset[str], frozenset[str]]:
    current: set[str] = set()
    partial: set[str] = set()
    stale: set[str] = set()
    missing: set[str] = set()
    for member in members:
        latest = latest_by_symbol.get(member.symbol)
        if latest is None:
            missing.add(member.symbol)
        elif latest < expected_trade_date:
            stale.add(member.symbol)
        elif member.symbol in usable_expected_symbols:
            current.add(member.symbol)
        else:
            partial.add(member.symbol)
    return (
        frozenset(current),
        frozenset(partial),
        frozenset(stale),
        frozenset(missing),
    )


def compute_eod_coverage(
    db: Session,
    *,
    market: str,
    expected_trade_date: date | None = None,
    us_port: USFullMarketEodPort | None = None,
) -> CoverageComputation:
    normalized = normalize_coverage_market(market)
    expected = expected_trade_date or expected_eod_trade_date(
        normalized,
        us_port=us_port,
    )
    if normalized == "US":
        if us_port is None:
            raise ValueError("US EOD coverage requires an injected market-owned port")
        return us_port.compute_coverage(db, expected_trade_date=expected)
    members = build_eod_universe(db, normalized)
    symbols = [member.symbol for member in members]

    latest_by_symbol: dict[str, date] = {}
    usable_expected_symbols: set[str] = set()
    if symbols and normalized == "TW":
        latest_by_symbol = {
            str(symbol): latest
            for symbol, latest in (
                db.query(MarketDailyPrice.stock_id, func.max(MarketDailyPrice.trade_date))
                .filter(MarketDailyPrice.stock_id.in_(symbols))
                .filter(MarketDailyPrice.trade_date <= expected)
                .group_by(MarketDailyPrice.stock_id)
                .all()
            )
            if latest is not None
        }
        usable_expected_symbols = {
            str(symbol)
            for (symbol,) in (
                db.query(MarketDailyPrice.stock_id)
                .filter(MarketDailyPrice.stock_id.in_(symbols))
                .filter(MarketDailyPrice.trade_date == expected)
                .filter(MarketDailyPrice.close_price.isnot(None))
                .distinct()
                .all()
            )
        }
    current, partial, stale, missing = _classify_symbols(
        members=members,
        latest_by_symbol=latest_by_symbol,
        usable_expected_symbols=usable_expected_symbols,
        expected_trade_date=expected,
    )
    return CoverageComputation(
        market=normalized,
        dataset_id=TW_DATASET_ID if normalized == "TW" else US_DATASET_ID,
        scope_key=TW_SCOPE_KEY if normalized == "TW" else US_SCOPE_KEY,
        universe_source=(
            "stock_master.active.TWSE_TPEX.ordinary_stock"
            if normalized == "TW"
            else "us_stock_master.active.nasdaq_trader.non_etf_non_test_stock"
        ),
        expected_trade_date=expected,
        latest_data_date=max(latest_by_symbol.values(), default=None),
        universe_hash=_universe_hash(members),
        members=members,
        current_symbols=current,
        partial_symbols=partial,
        stale_symbols=stale,
        missing_symbols=missing,
        ineligible_members=(
            _tw_ineligible_universe(db) if normalized == "TW" else ()
        ),
    )


def evaluate_eod_lifecycle(
    computation: CoverageComputation,
    *,
    checked_at: datetime | None = None,
) -> DatasetLifecycleEvaluation:
    lifecycle = eod_lifecycle_contract(computation.market)
    if lifecycle.dataset_id != computation.dataset_id:
        raise ValueError("coverage computation does not match lifecycle dataset")
    return evaluate_lifecycle(
        lifecycle,
        expected_date=computation.expected_trade_date,
        latest_date=computation.latest_data_date,
        checked_at=checked_at or utc_now(),
        eligible=(True if computation.universe_count else False),
        partial=computation.status == "partial",
    )


def _lifecycle_detail(
    evaluation: DatasetLifecycleEvaluation,
) -> dict[str, Any]:
    return evaluation.model_dump(mode="json")


def _lifecycle_result(
    computation: CoverageComputation,
) -> dict[str, Any]:
    evaluation = evaluate_eod_lifecycle(computation)
    return {
        "dataset_lifecycle": evaluation.lifecycle.model_dump(mode="json"),
        "dataset_health": evaluation.health.model_dump(mode="json"),
    }


def _decode_detail(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {"raw_detail": value}
    return parsed if isinstance(parsed, dict) else {"detail": parsed}


def _encode_detail(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def persist_eod_coverage(
    db: Session,
    computation: CoverageComputation,
    *,
    detail_extra: dict[str, Any] | None = None,
) -> MarketDatasetCoverageCheckpoint:
    row = (
        db.query(MarketDatasetCoverageCheckpoint)
        .filter(MarketDatasetCoverageCheckpoint.dataset_id == computation.dataset_id)
        .filter(MarketDatasetCoverageCheckpoint.scope_key == computation.scope_key)
        .filter(
            MarketDatasetCoverageCheckpoint.expected_trade_date
            == computation.expected_trade_date
        )
        .filter(MarketDatasetCoverageCheckpoint.universe_hash == computation.universe_hash)
        .first()
    )
    if row is None:
        row = MarketDatasetCoverageCheckpoint(
            checkpoint_version=CHECKPOINT_VERSION,
            dataset_id=computation.dataset_id,
            market=computation.market,
            scope_kind=FULL_MARKET_SCOPE_KIND,
            scope_key=computation.scope_key,
            expected_trade_date=computation.expected_trade_date,
            universe_source=computation.universe_source,
            universe_hash=computation.universe_hash,
            status=computation.status,
        )
        db.add(row)

    detail = computation.detail()
    detail["dataset_lifecycle"] = _lifecycle_detail(
        evaluate_eod_lifecycle(computation)
    )
    previous_detail = _decode_detail(row.detail_json)
    for key in ("repair", "last_error", "last_provider_failure"):
        if key in previous_detail:
            detail[key] = previous_detail[key]
    if detail_extra:
        detail.update(detail_extra)

    row.latest_data_date = computation.latest_data_date
    row.universe_count = computation.universe_count
    row.current_count = computation.current_count
    row.partial_count = computation.partial_count
    row.stale_count = computation.stale_count
    row.missing_count = computation.missing_count
    row.status = computation.status
    row.detail_json = _encode_detail(detail)
    row.checked_at = utc_now()
    row.updated_at = utc_now()
    db.commit()
    db.refresh(row)
    return row


def serialize_eod_checkpoint(row: MarketDatasetCoverageCheckpoint) -> dict[str, Any]:
    denominator = max(int(row.universe_count or 0), 1)
    return {
        "checkpoint_version": row.checkpoint_version,
        "id": row.id,
        "dataset_id": row.dataset_id,
        "market": row.market,
        "scope_kind": row.scope_kind,
        "scope_key": row.scope_key,
        "expected_trade_date": row.expected_trade_date,
        "latest_data_date": row.latest_data_date,
        "universe_source": row.universe_source,
        "universe_hash": row.universe_hash,
        "universe_count": row.universe_count,
        "current_count": row.current_count,
        "partial_count": row.partial_count,
        "stale_count": row.stale_count,
        "missing_count": row.missing_count,
        "coverage_ratio": row.current_count / denominator,
        "observed_ratio": (row.current_count + row.partial_count) / denominator,
        "status": row.status,
        "repair_status": row.repair_status,
        "repair_provider": row.repair_provider,
        "cursor_symbol": row.cursor_symbol,
        "attempted_count": row.attempted_count,
        "succeeded_count": row.succeeded_count,
        "failed_count": row.failed_count,
        "consecutive_error_count": row.consecutive_error_count,
        "last_job_id": row.last_job_id,
        "last_attempt_at": row.last_attempt_at,
        "last_success_at": row.last_success_at,
        "next_retry_at": row.next_retry_at,
        "detail": _decode_detail(row.detail_json),
        "checked_at": row.checked_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _result_coverage_counts(row: MarketDatasetCoverageCheckpoint) -> dict[str, int]:
    return {
        "universe_count": row.universe_count,
        "current_count": row.current_count,
        "partial_count": row.partial_count,
        "stale_count": row.stale_count,
        "missing_count": row.missing_count,
    }


def list_cached_eod_checkpoints(
    db: Session,
    *,
    market: str | None = None,
) -> list[dict[str, Any]]:
    normalized = normalize_coverage_market(market) if market else None
    query = db.query(MarketDatasetCoverageCheckpoint)
    if normalized:
        query = query.filter(MarketDatasetCoverageCheckpoint.market == normalized)
    rows = query.order_by(
        MarketDatasetCoverageCheckpoint.expected_trade_date.desc(),
        MarketDatasetCoverageCheckpoint.checked_at.desc(),
        MarketDatasetCoverageCheckpoint.id.desc(),
    ).all()
    latest_by_identity: dict[tuple[str, str], MarketDatasetCoverageCheckpoint] = {}
    for row in rows:
        latest_by_identity.setdefault((row.dataset_id, row.scope_key), row)
    return [
        serialize_eod_checkpoint(row)
        for row in sorted(latest_by_identity.values(), key=lambda item: item.market)
    ]


def cached_eod_coverage_projection(
    db: Session,
    *,
    market: str | None = None,
) -> dict[str, Any]:
    checkpoints = list_cached_eod_checkpoints(db, market=market)
    return {
        "contract_version": CHECKPOINT_VERSION,
        "status": "ready" if checkpoints else "empty",
        "cache_only": True,
        "checkpoint_count": len(checkpoints),
        "checkpoints": checkpoints,
        "limitations": [
            "This GET projection never starts provider I/O or a repair job.",
            "When the computer is off, only reconstructable completed-session EOD data can be repaired after the backend starts again.",
        ],
    }


def _as_aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _release_guard_retry_is_now_eligible(
    row: MarketDatasetCoverageCheckpoint,
    *,
    market: str,
    expected_trade_date: date,
    now: datetime,
) -> bool:
    if market != "TW" or row.repair_status != "deferred":
        return False
    repair = _decode_detail(row.detail_json).get("repair")
    if not isinstance(repair, dict) or repair.get("phase") != "release_guard":
        return False
    eligible, _retry_at, _reason = taiwan_bulk_eod_refresh_window(
        expected_trade_date=expected_trade_date,
        now=now,
    )
    return eligible


def should_enqueue_eod_reconcile(
    db: Session,
    *,
    market: str,
    expected_trade_date: date | None = None,
    now: datetime | None = None,
    us_port: USFullMarketEodPort | None = None,
) -> bool:
    normalized = normalize_coverage_market(market)
    decision_now = now or utc_now()
    expected = expected_trade_date or expected_eod_trade_date(
        normalized,
        now=decision_now,
        us_port=us_port,
    )
    computation = compute_eod_coverage(
        db,
        market=normalized,
        expected_trade_date=expected,
        us_port=us_port,
    )
    dataset_id = eod_lifecycle_contract(normalized).dataset_id
    scope_key = TW_SCOPE_KEY if normalized == "TW" else US_SCOPE_KEY
    row = (
        db.query(MarketDatasetCoverageCheckpoint)
        .filter(MarketDatasetCoverageCheckpoint.dataset_id == dataset_id)
        .filter(MarketDatasetCoverageCheckpoint.scope_key == scope_key)
        .filter(MarketDatasetCoverageCheckpoint.expected_trade_date == expected)
        .filter(
            MarketDatasetCoverageCheckpoint.universe_hash
            == computation.universe_hash
        )
        .order_by(MarketDatasetCoverageCheckpoint.checked_at.desc())
        .first()
    )
    if row is None:
        return True
    next_retry_at = _as_aware_utc(row.next_retry_at)
    decision_now_utc = _as_aware_utc(decision_now) or utc_now()
    if (
        next_retry_at is not None
        and next_retry_at > decision_now_utc
        and not _release_guard_retry_is_now_eligible(
            row,
            market=normalized,
            expected_trade_date=expected,
            now=decision_now,
        )
    ):
        return False
    return row.status != "healthy" or computation.status != "healthy"


def _update_repair_state(
    db: Session,
    row: MarketDatasetCoverageCheckpoint,
    *,
    repair_status: str,
    repair_provider: str | None,
    job_id: int | None,
    cursor_symbol: str | None = None,
    attempted_delta: int = 0,
    succeeded_delta: int = 0,
    failed_delta: int = 0,
    consecutive_error_count: int | None = None,
    next_retry_at: datetime | None = None,
    detail_update: dict[str, Any] | None = None,
    mark_success: bool = False,
) -> None:
    now = utc_now()
    row.repair_status = repair_status
    row.repair_provider = repair_provider
    row.last_job_id = job_id
    if cursor_symbol is not None:
        row.cursor_symbol = cursor_symbol
    row.attempted_count += attempted_delta
    row.succeeded_count += succeeded_delta
    row.failed_count += failed_delta
    if consecutive_error_count is not None:
        row.consecutive_error_count = consecutive_error_count
    row.last_attempt_at = now
    if mark_success:
        row.last_success_at = now
    row.next_retry_at = next_retry_at
    detail = _decode_detail(row.detail_json)
    if detail_update:
        detail.update(detail_update)
    row.detail_json = _encode_detail(detail)
    row.updated_at = now
    db.commit()


def _tw_unresolved_venues(computation: CoverageComputation) -> set[str]:
    unresolved = set(computation.unresolved_symbols)
    return {
        member.venue
        for member in computation.members
        if member.symbol in unresolved
    }


def _tw_venue_coverage(
    computation: CoverageComputation,
    venue: str,
) -> dict[str, Any]:
    return dict(
        computation.detail().get("venue_breakdown", {}).get(
            venue,
            {
                "universe_count": 0,
                "current_count": 0,
                "partial_count": 0,
                "stale_count": 0,
                "missing_count": 0,
                "coverage_ratio": 0.0,
                "status": "unavailable",
            },
        )
    )


def _iso_trade_dates(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple, set)):
        return []
    normalized = []
    for value in values:
        if isinstance(value, (date, datetime)):
            normalized.append(
                value.date().isoformat()
                if isinstance(value, datetime)
                else value.isoformat()
            )
        elif isinstance(value, str) and value.strip():
            normalized.append(value.strip()[:10])
    return list(dict.fromkeys(normalized))


def _iso_temporal(value: Any) -> str | None:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _repair_tw_eod(
    db: Session,
    *,
    row: MarketDatasetCoverageCheckpoint,
    computation: CoverageComputation,
    job_id: int | None,
    progress_callback: ProgressCallback | None,
    error_backoff_seconds: int,
    max_calls: int,
    venue_refresher: TaiwanVenueRefresher | None,
) -> dict[str, Any]:
    source_by_venue = (
        ("TWSE", TWSE_DAILY_TRADING_SOURCE_NAME),
        ("TPEX", TPEX_DAILY_QUOTES_SOURCE_NAME),
    )
    unresolved_venues = _tw_unresolved_venues(computation)
    targets = [
        item for item in source_by_venue if item[0] in unresolved_venues
    ][:max_calls]
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    _update_repair_state(
        db,
        row,
        repair_status="running",
        repair_provider="twse+tpex",
        job_id=job_id,
        detail_update={"repair": {"phase": "provider_refresh", "target_count": len(targets)}},
    )
    for index, (venue, source_name) in enumerate(targets, start=1):
        if progress_callback:
            progress_callback(index - 1, max(len(targets), 1), f"Refreshing {venue} full-market EOD.")
        try:
            before_coverage = _tw_venue_coverage(computation, venue)
            if venue_refresher is None:
                source = get_source_by_name(db, source_name)
                result = refresh_source(
                    db=db,
                    source_id=source.id,
                    trade_date=computation.expected_trade_date,
                )
            else:
                result = venue_refresher(
                    db=db,
                    venue=venue,
                    trade_date=computation.expected_trade_date,
                )
            refreshed_attempt = compute_eod_coverage(
                db,
                market="TW",
                expected_trade_date=computation.expected_trade_date,
            )
            after_coverage = _tw_venue_coverage(refreshed_attempt, venue)
            observed_trade_dates = _iso_trade_dates(
                result.get("replaced_trade_dates")
            )
            expected_trade_date = computation.expected_trade_date.isoformat()
            transport_ok = (
                result.get("fetch_status") == "success"
                and result.get("parse_status") == "success"
            )
            venue_advanced = int(after_coverage["current_count"]) > int(
                before_coverage["current_count"]
            )
            venue_postcondition_met = (
                int(after_coverage["universe_count"]) > 0
                and int(after_coverage["current_count"])
                == int(after_coverage["universe_count"])
            )
            dataset_success = transport_ok and (
                venue_advanced or venue_postcondition_met
            )
            if not transport_ok:
                dataset_status = "transport_error"
            elif venue_postcondition_met:
                dataset_status = "current"
            elif venue_advanced:
                dataset_status = "advanced_partial"
            elif observed_trade_dates and expected_trade_date not in observed_trade_dates:
                dataset_status = "stale_payload"
            elif result.get("is_duplicate") is True:
                dataset_status = "unchanged_duplicate"
            elif observed_trade_dates:
                dataset_status = "expected_payload_without_coverage_advance"
            else:
                dataset_status = "unchanged"
            compact = {
                "venue": venue,
                "source_name": result.get("source_name") or source_name,
                "resource_attempts": result.get("resource_attempts") or [],
                "limitations": result.get("limitations") or [],
                "fetch_status": result.get("fetch_status"),
                "parse_status": result.get("parse_status"),
                "parsed_count": result.get("parsed_count"),
                "data_quality_status": result.get("data_quality_status"),
                "raw_result_id": result.get("raw_result_id"),
                "fetched_at": _iso_temporal(result.get("fetched_at")),
                "is_duplicate": result.get("is_duplicate"),
                "observed_trade_dates": observed_trade_dates,
                "expected_trade_date_observed": (
                    expected_trade_date in observed_trade_dates
                    if observed_trade_dates
                    else None
                ),
                "dataset_status": dataset_status,
                "dataset_advanced": venue_advanced,
                "venue_postcondition_met": venue_postcondition_met,
                "coverage_before": before_coverage,
                "coverage_after": after_coverage,
                "error_message": result.get("error_message"),
            }
            results.append(compact)
            _update_repair_state(
                db,
                row,
                repair_status="running" if transport_ok else "partial",
                repair_provider="twse+tpex",
                job_id=job_id,
                cursor_symbol=venue,
                attempted_delta=1,
                succeeded_delta=1 if dataset_success else 0,
                failed_delta=0 if transport_ok else 1,
                consecutive_error_count=(
                    0 if transport_ok else row.consecutive_error_count + 1
                ),
                mark_success=dataset_success,
            )
            if not transport_ok:
                errors.append({"venue": venue, "message": result.get("error_message") or result.get("message")})
        except Exception as exc:
            db.rollback()
            failure = provider_http_failure(exc)
            error = {"venue": venue, "message": str(exc)}
            if failure is not None:
                error.update(failure.diagnostic_fields())
            errors.append(error)
            _update_repair_state(
                db,
                row,
                repair_status="rate_limited" if failure and failure.rate_limited else "error",
                repair_provider="twse+tpex",
                job_id=job_id,
                cursor_symbol=venue,
                attempted_delta=1,
                failed_delta=1,
                consecutive_error_count=row.consecutive_error_count + 1,
                next_retry_at=utc_now() + timedelta(
                    seconds=max(
                        int(failure.retry_after_seconds or 0) if failure else 0,
                        error_backoff_seconds,
                    )
                ),
                detail_update={"last_error": error},
            )
        if progress_callback:
            progress_callback(index, max(len(targets), 1), f"Refreshed {index}/{len(targets)} Taiwan EOD sources.")

    refreshed = compute_eod_coverage(
        db,
        market="TW",
        expected_trade_date=computation.expected_trade_date,
    )
    refreshed_row = persist_eod_coverage(
        db,
        refreshed,
        detail_extra={"repair": {"provider_results": results, "errors": errors[:10]}},
    )
    final_status = "complete" if refreshed.status == "healthy" else ("error" if errors and not results else "partial")
    _update_repair_state(
        db,
        refreshed_row,
        repair_status=final_status,
        repair_provider="twse+tpex",
        job_id=job_id,
        consecutive_error_count=0 if refreshed.status == "healthy" else refreshed_row.consecutive_error_count,
        next_retry_at=None if refreshed.status == "healthy" else refreshed_row.next_retry_at,
        mark_success=refreshed.status == "healthy",
    )
    return {
        "status": "completed" if refreshed.status == "healthy" else "partial",
        "postcondition_met": refreshed.status == "healthy",
        "market": "TW",
        **_lifecycle_result(refreshed),
        **_result_coverage_counts(refreshed_row),
        "attempted_count": len(targets),
        "success_count": sum(
            1
            for item in results
            if item.get("dataset_advanced") is True
            or item.get("venue_postcondition_met") is True
        ),
        "transport_success_count": sum(
            1
            for item in results
            if item.get("fetch_status") == "success"
            and item.get("parse_status") == "success"
        ),
        "unchanged_count": sum(
            1
            for item in results
            if item.get("dataset_status")
            in {
                "stale_payload",
                "unchanged_duplicate",
                "expected_payload_without_coverage_advance",
                "unchanged",
            }
        ),
        "error_count": len(errors),
        "errors": errors[:10],
        "checkpoint": serialize_eod_checkpoint(refreshed_row),
        "message": "Taiwan full-market EOD coverage reconciled with official bulk sources.",
    }


def _rotate_after_cursor(symbols: tuple[str, ...], cursor: str | None) -> tuple[str, ...]:
    if not symbols or not cursor:
        return symbols
    after = tuple(symbol for symbol in symbols if symbol > cursor)
    before_or_equal = tuple(symbol for symbol in symbols if symbol <= cursor)
    return after + before_or_equal


def _repair_us_eod(
    db: Session,
    *,
    row: MarketDatasetCoverageCheckpoint,
    computation: CoverageComputation,
    job_id: int | None,
    max_symbols: int,
    max_runtime_seconds: int,
    sleep_seconds: float,
    max_consecutive_errors: int,
    error_backoff_seconds: int,
    progress_callback: ProgressCallback | None,
    us_port: USFullMarketEodPort,
) -> dict[str, Any]:
    candidates = _rotate_after_cursor(computation.unresolved_symbols, row.cursor_symbol)
    targets = candidates[:max_symbols]
    started = monotonic()
    errors: list[dict[str, Any]] = []
    attempted = 0
    succeeded = 0
    rate_limited = False
    consecutive_errors = int(row.consecutive_error_count or 0)
    _update_repair_state(
        db,
        row,
        repair_status="running",
        repair_provider="yahoo_chart",
        job_id=job_id,
        detail_update={
            "repair": {
                "phase": "bounded_symbol_shard",
                "candidate_count": len(candidates),
                "bounded_target_count": len(targets),
            }
        },
    )

    for index, symbol in enumerate(targets, start=1):
        if monotonic() - started >= max_runtime_seconds:
            break
        if progress_callback:
            progress_callback(index - 1, max(len(targets), 1), f"Refreshing US EOD {symbol}.")
        attempted += 1
        try:
            us_port.refresh_symbol(
                db,
                symbol=symbol,
                expected_trade_date=computation.expected_trade_date,
            )
            succeeded += 1
            consecutive_errors = 0
            _update_repair_state(
                db,
                row,
                repair_status="running",
                repair_provider="yahoo_chart",
                job_id=job_id,
                cursor_symbol=symbol,
                attempted_delta=1,
                succeeded_delta=1,
                consecutive_error_count=0,
                mark_success=True,
            )
        except Exception as exc:
            failure = provider_http_failure(exc)
            error: dict[str, Any] = {"symbol": symbol, "message": str(exc)}
            if failure is not None:
                error.update(failure.diagnostic_fields())
            errors.append(error)
            consecutive_errors += 1
            rate_limited = bool(failure and failure.rate_limited)
            retry_after = int(failure.retry_after_seconds or 0) if failure else 0
            _update_repair_state(
                db,
                row,
                repair_status="rate_limited" if rate_limited else "running",
                repair_provider="yahoo_chart",
                job_id=job_id,
                cursor_symbol=symbol,
                attempted_delta=1,
                failed_delta=1,
                consecutive_error_count=consecutive_errors,
                next_retry_at=(
                    utc_now() + timedelta(seconds=max(retry_after, error_backoff_seconds))
                    if rate_limited or consecutive_errors >= max_consecutive_errors
                    else None
                ),
                detail_update={
                    "last_error": error,
                    "last_provider_failure": failure.diagnostic_fields() if failure else None,
                },
            )
            if rate_limited or consecutive_errors >= max_consecutive_errors:
                break
        if progress_callback:
            progress_callback(index, max(len(targets), 1), f"Processed {index}/{len(targets)} US EOD symbols.")
        if index < len(targets) and sleep_seconds > 0:
            remaining = max_runtime_seconds - (monotonic() - started)
            if remaining <= 0:
                break
            sleep(min(sleep_seconds, remaining))

    refreshed = compute_eod_coverage(
        db,
        market="US",
        expected_trade_date=computation.expected_trade_date,
        us_port=us_port,
    )
    refreshed_row = persist_eod_coverage(
        db,
        refreshed,
        detail_extra={
            "repair": {
                "attempted_count": attempted,
                "succeeded_count": succeeded,
                "error_count": len(errors),
                "runtime_seconds": round(monotonic() - started, 3),
                "errors": errors[:10],
            }
        },
    )
    if refreshed.status == "healthy":
        repair_status = "complete"
    elif rate_limited:
        repair_status = "rate_limited"
    elif errors and succeeded == 0:
        repair_status = "error"
    else:
        repair_status = "partial"
    next_retry_at = refreshed_row.next_retry_at
    if repair_status == "error" and next_retry_at is None:
        next_retry_at = utc_now() + timedelta(seconds=error_backoff_seconds)
    _update_repair_state(
        db,
        refreshed_row,
        repair_status=repair_status,
        repair_provider="yahoo_chart",
        job_id=job_id,
        consecutive_error_count=0 if refreshed.status == "healthy" else consecutive_errors,
        next_retry_at=None if refreshed.status == "healthy" else next_retry_at,
        mark_success=refreshed.status == "healthy",
    )
    return {
        "status": "completed" if refreshed.status == "healthy" else "partial",
        "postcondition_met": refreshed.status == "healthy",
        "market": "US",
        **_lifecycle_result(refreshed),
        **_result_coverage_counts(refreshed_row),
        "attempted_count": attempted,
        "success_count": succeeded,
        "error_count": len(errors),
        "errors": errors[:10],
        "checkpoint": serialize_eod_checkpoint(refreshed_row),
        "message": "US full-market EOD coverage processed a bounded resumable symbol shard.",
    }


def reconcile_eod_coverage(
    db: Session,
    *,
    market: str,
    repair: bool = True,
    expected_trade_date: date | None = None,
    job_id: int | None = None,
    max_symbols: int = 250,
    max_runtime_seconds: int = 600,
    sleep_seconds: float = 1.0,
    max_consecutive_errors: int = 5,
    error_backoff_seconds: int = 1800,
    progress_callback: ProgressCallback | None = None,
    taiwan_venue_refresher: TaiwanVenueRefresher | None = None,
    us_port: USFullMarketEodPort | None = None,
) -> dict[str, Any]:
    normalized = normalize_coverage_market(market)
    bounds = eod_reconcile_bounds(normalized)
    bounded_max_symbols = min(
        max(int(max_symbols), 1),
        bounds.max_symbols,
        bounds.max_calls,
    )
    bounded_runtime_seconds = min(
        max(int(max_runtime_seconds), 1),
        bounds.timeout_seconds,
    )
    computation = compute_eod_coverage(
        db,
        market=normalized,
        expected_trade_date=expected_trade_date,
        us_port=us_port,
    )
    row = persist_eod_coverage(db, computation)
    if computation.status == "healthy":
        _update_repair_state(
            db,
            row,
            repair_status="complete",
            repair_provider=row.repair_provider,
            job_id=job_id,
            consecutive_error_count=0,
            next_retry_at=None,
            mark_success=True,
        )
        return {
            "status": "completed",
            "postcondition_met": True,
            "market": normalized,
            **_lifecycle_result(computation),
            **_result_coverage_counts(row),
            "attempted_count": 0,
            "success_count": 0,
            "error_count": 0,
            "checkpoint": serialize_eod_checkpoint(row),
            "message": "Full-market EOD coverage is already current.",
        }
    if not repair:
        return {
            "status": "partial",
            "postcondition_met": False,
            "market": normalized,
            **_lifecycle_result(computation),
            **_result_coverage_counts(row),
            "attempted_count": 0,
            "success_count": 0,
            "error_count": 0,
            "checkpoint": serialize_eod_checkpoint(row),
            "message": "Coverage checkpoint recomputed without provider repair.",
        }
    decision_now = utc_now()
    next_retry_at = _as_aware_utc(row.next_retry_at)
    if (
        next_retry_at is not None
        and next_retry_at > decision_now
        and not _release_guard_retry_is_now_eligible(
            row,
            market=normalized,
            expected_trade_date=computation.expected_trade_date,
            now=decision_now,
        )
    ):
        return {
            "status": "partial",
            "postcondition_met": False,
            "market": normalized,
            **_lifecycle_result(computation),
            **_result_coverage_counts(row),
            "attempted_count": 0,
            "success_count": 0,
            "error_count": 0,
            "checkpoint": serialize_eod_checkpoint(row),
            "message": f"Repair deferred until {next_retry_at.isoformat()} after provider backoff.",
        }
    if normalized == "TW":
        eligible, release_retry_at, reason = taiwan_bulk_eod_refresh_window(
            expected_trade_date=computation.expected_trade_date,
            now=decision_now,
        )
        if not eligible:
            _update_repair_state(
                db,
                row,
                repair_status="deferred",
                repair_provider="twse+tpex",
                job_id=job_id,
                next_retry_at=release_retry_at,
                detail_update={
                    "repair": {
                        "phase": "release_guard",
                        "reason": reason,
                    }
                },
            )
            return {
                "status": "partial",
                "postcondition_met": False,
                "market": normalized,
                **_lifecycle_result(computation),
                **_result_coverage_counts(row),
                "attempted_count": 0,
                "success_count": 0,
                "error_count": 0,
                "checkpoint": serialize_eod_checkpoint(row),
                "message": "Taiwan bulk EOD repair deferred until a safe completed-session release window.",
            }
        return _repair_tw_eod(
            db,
            row=row,
            computation=computation,
            job_id=job_id,
            progress_callback=progress_callback,
            error_backoff_seconds=error_backoff_seconds,
            max_calls=min(bounds.max_calls, bounds.max_symbols),
            venue_refresher=taiwan_venue_refresher,
        )
    if us_port is None:
        raise ValueError("US EOD repair requires an injected market-owned port")
    return _repair_us_eod(
        db,
        row=row,
        computation=computation,
        job_id=job_id,
        max_symbols=bounded_max_symbols,
        max_runtime_seconds=bounded_runtime_seconds,
        sleep_seconds=min(max(float(sleep_seconds), 0), 30),
        max_consecutive_errors=min(max(int(max_consecutive_errors), 1), 20),
        error_backoff_seconds=max(int(error_backoff_seconds), 60),
        progress_callback=progress_callback,
        us_port=us_port,
    )


__all__ = [
    "CHECKPOINT_VERSION",
    "FULL_MARKET_SCOPE_KIND",
    "TW_DATASET_ID",
    "US_DATASET_ID",
    "USFullMarketEodPort",
    "build_eod_universe",
    "cached_eod_coverage_projection",
    "compute_eod_coverage",
    "eod_lifecycle_contract",
    "eod_reconcile_bounds",
    "evaluate_eod_lifecycle",
    "expected_eod_trade_date",
    "list_cached_eod_checkpoints",
    "normalize_coverage_market",
    "persist_eod_coverage",
    "reconcile_eod_coverage",
    "serialize_eod_checkpoint",
    "should_enqueue_eod_reconcile",
    "taiwan_bulk_eod_refresh_window",
]
