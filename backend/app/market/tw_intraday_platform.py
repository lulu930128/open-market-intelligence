"""Taiwan intraday bar application platform over Shared Market Data Core."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import json
from typing import Any, Callable, Iterable, Literal

from pydantic import Field

from sqlalchemy.orm import Session

from app.db.models import StockMaster
from app.market.intraday_repository import TaiwanIntradayBarRepository
from app.market.intraday_transaction import TaiwanIntradayBarTransaction
from app.market.trading_calendar import taiwan_presentation_session
from app.market.tw_instrument import (
    normalize_taiwan_instrument_id,
    resolve_taiwan_instrument,
)
from app.market.tw_intraday_acquisition import TaiwanIntradayAcquisitionExecutor
from app.market.tw_intraday_capabilities import (
    TW_INTRADAY_BARS_CAPABILITY_ID,
    TW_INTRADAY_DESCRIPTORS,
)
from app.market_data.contracts import (
    BarObservation,
    CanonicalModel,
    InstrumentKey,
    InstrumentType,
    MarketSession,
    QuantityUnit,
)
from app.market_data.gateway import MarketDataGateway
from app.market_data.integration_contracts import (
    BarCapabilityRequest,
    DataRequirementV2,
    FreshnessRequirement,
    InstrumentTarget,
    MarketDataResultV1,
    QualityRequirement,
    RequestBounds,
)
from app.market_data.policies import DataPurpose, RealtimePolicy
from app.market_data.provider_catalog import ProviderCapabilityDescriptorV2


TAIPEI_TZ = timezone(timedelta(hours=8))
# RequestBounds count both endpoints, so a four-day delta is the bounded
# five-calendar-day Yahoo ``range=5d`` window.
INTRADAY_HISTORY_FIVE_TRADING_DAY_QUERY_DAYS = 4
INTRADAY_HISTORY_INTERVAL_CONFIGS = {
    "1m": {"range": "5d", "days": INTRADAY_HISTORY_FIVE_TRADING_DAY_QUERY_DAYS},
    "5m": {"range": "1mo", "days": 31},
    "15m": {"range": "1mo", "days": 31},
    "30m": {"range": "1mo", "days": 31},
    "1h": {"range": "3mo", "days": 93},
    "4h": {"range": "3mo", "days": 93},
}
INTRADAY_HISTORY_RANGE_DAYS = {
    "1d": 1,
    "5d": INTRADAY_HISTORY_FIVE_TRADING_DAY_QUERY_DAYS,
    "1mo": 31,
    "3mo": 93,
}


class TaiwanIntradayBootstrapSymbolResult(CanonicalModel):
    symbol: str
    status: Literal["success", "partial", "failed", "skipped"]
    requested_from: datetime | None = None
    requested_to: datetime | None = None
    bar_count: int = Field(default=0, ge=0)
    receipts_written: int = Field(default=0, ge=0)
    bars_written: int = Field(default=0, ge=0)
    bars_unchanged: int = Field(default=0, ge=0)
    raw_result_ids: tuple[int, ...] = ()
    warnings: tuple[str, ...] = ()
    failure_reason: str | None = None


class TaiwanIntradayBootstrapResult(CanonicalModel):
    contract_version: str = "tw.intraday.bootstrap.v1"
    status: Literal["success", "partial", "failed", "skipped"]
    requested_symbols: tuple[str, ...]
    planned_symbols: tuple[str, ...]
    processed_symbols: tuple[str, ...]
    skipped_symbols: tuple[str, ...]
    failed_symbols: tuple[str, ...]
    requested_trade_dates: tuple[date, ...]
    provider: str = "canonical_planner"
    source: str = "tw_intraday_base_1m_bootstrap"
    receipts_written: int = Field(default=0, ge=0)
    bars_written: int = Field(default=0, ge=0)
    bars_unchanged: int = Field(default=0, ge=0)
    rejected_bar_count: int = Field(default=0, ge=0)
    earliest_bar: datetime | None = None
    latest_bar: datetime | None = None
    per_symbol: tuple[TaiwanIntradayBootstrapSymbolResult, ...] = ()
    target_plan: dict[str, Any]


IntradayBootstrapRefresher = Callable[..., MarketDataResultV1]


def bootstrap_taiwan_intraday_bars(
    db: Session,
    *,
    symbols: Iterable[object] | None = None,
    max_symbols: int = 10,
    requested_at: datetime | None = None,
    refresher: IntradayBootstrapRefresher | None = None,
) -> TaiwanIntradayBootstrapResult:
    """Explicit bounded Base-1m bootstrap over the canonical Tier-A planner."""

    if max_symbols < 1 or max_symbols > 10:
        raise ValueError("Taiwan intraday bootstrap max_symbols must be between 1 and 10")
    # Lazy import avoids the realtime-runtime -> intraday-platform cycle while
    # keeping the canonical Tier-A planner as the only universe owner.
    from app.market.tw_intraday_universe import resolve_taiwan_tier_a_target_plan

    now = requested_at or datetime.now(TAIPEI_TZ)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("requested_at must be timezone-aware")
    requested_symbols = tuple(
        dict.fromkeys(
            str(value or "").strip().upper()
            for value in symbols or ()
            if str(value or "").strip()
        )
    )
    plan = resolve_taiwan_tier_a_target_plan(
        db,
        operation_profile="production_intraday",
        max_symbols=max_symbols,
        configured_symbols=(requested_symbols if requested_symbols else None),
    )
    planned_symbols = tuple(str(value) for value in plan.get("symbols") or ())
    effective_refresher = refresher or refresh_taiwan_intraday_bars
    results: list[TaiwanIntradayBootstrapSymbolResult] = []
    rejected_count = 0
    observed_dates: set[date] = set()
    observed_times: list[datetime] = []
    for symbol in planned_symbols:
        try:
            result = effective_refresher(
                db,
                stock_id=symbol,
                interval="1m",
                range_value="5d",
                requested_at=now,
            )
            persistence = result.persistence
            rejected_count += len(result.candidate_rejections)
            bars = tuple(result.resolved.bars)
            observed_times.extend(bar.start_at for bar in bars)
            observed_dates.update(
                bar.start_at.astimezone(TAIPEI_TZ).date() for bar in bars
            )
            warnings = tuple(
                dict.fromkeys(
                    (
                        *result.limitations,
                        *persistence.limitations,
                        *(
                            rejection.reason_code
                            for rejection in result.candidate_rejections
                        ),
                    )
                )
            )
            status: Literal["success", "partial", "failed", "skipped"] = (
                "success"
                if bars and not result.candidate_rejections
                else "partial"
                if bars or persistence.committed
                else "failed"
            )
            results.append(
                TaiwanIntradayBootstrapSymbolResult(
                    symbol=symbol,
                    status=status,
                    requested_from=result.requirement.request.start_at,
                    requested_to=result.requirement.request.end_at,
                    bar_count=len(bars),
                    receipts_written=persistence.receipts_written,
                    bars_written=persistence.observations_written,
                    bars_unchanged=persistence.observations_unchanged,
                    raw_result_ids=persistence.raw_result_ids,
                    warnings=warnings,
                    failure_reason=(
                        None if status != "failed" else "no_canonical_bar_persisted"
                    ),
                )
            )
        except Exception as exc:
            db.rollback()
            results.append(
                TaiwanIntradayBootstrapSymbolResult(
                    symbol=symbol,
                    status="failed",
                    failure_reason=f"{type(exc).__name__}: {exc}",
                )
            )
    failed = tuple(item.symbol for item in results if item.status == "failed")
    skipped = tuple(
        str(item.get("stock_id") or "")
        for item in plan.get("skipped_targets") or ()
        if item.get("stock_id")
    )
    processed = tuple(item.symbol for item in results if item.status != "failed")
    overall: Literal["success", "partial", "failed", "skipped"] = (
        "skipped"
        if not results
        else "success"
        if not failed and all(item.status == "success" for item in results)
        else "failed"
        if len(failed) == len(results)
        else "partial"
    )
    return TaiwanIntradayBootstrapResult(
        status=overall,
        requested_symbols=requested_symbols,
        planned_symbols=planned_symbols,
        processed_symbols=processed,
        skipped_symbols=skipped,
        failed_symbols=failed,
        requested_trade_dates=tuple(sorted(observed_dates)),
        receipts_written=sum(item.receipts_written for item in results),
        bars_written=sum(item.bars_written for item in results),
        bars_unchanged=sum(item.bars_unchanged for item in results),
        rejected_bar_count=rejected_count,
        earliest_bar=min(observed_times, default=None),
        latest_bar=max(observed_times, default=None),
        per_symbol=tuple(results),
        target_plan=plan,
    )


def intraday_history_config(interval: str, range_value: str) -> dict[str, object]:
    config = INTRADAY_HISTORY_INTERVAL_CONFIGS.get(interval)
    if config is None:
        raise ValueError("interval must be one of: 1m, 5m, 15m, 30m, 1h, 4h.")
    if range_value == "auto":
        return dict(config)
    days = INTRADAY_HISTORY_RANGE_DAYS.get(range_value)
    if days is None:
        raise ValueError("range must be one of: auto, 1d, 5d, 1mo, 3mo.")
    return {"range": range_value, "days": days}


def _instrument(db: Session, stock_id: str) -> tuple[StockMaster, InstrumentKey]:
    normalized = normalize_taiwan_instrument_id(stock_id)
    instrument = resolve_taiwan_instrument(db, normalized)
    if instrument.instrument_type is InstrumentType.INDEX:
        raise ValueError(
            "Stock/ETF intraday acquisition does not materialize index events"
        )
    stock = (
        db.query(StockMaster)
        .filter(StockMaster.stock_id == normalized)
        .first()
    )
    if stock is None:
        raise RuntimeError("Resolved StockMaster row disappeared during request")
    return stock, instrument


def build_taiwan_intraday_requirement(
    *,
    instrument: InstrumentKey,
    interval: str,
    range_value: str,
    policy: RealtimePolicy,
    requested_at: datetime,
    acquiring: bool,
) -> DataRequirementV2:
    if requested_at.tzinfo is None or requested_at.utcoffset() is None:
        raise ValueError("requested_at must be timezone-aware")
    config = intraday_history_config(interval, range_value)
    days = int(config["days"])
    local_requested_at = requested_at.astimezone(TAIPEI_TZ)
    if days == 1:
        presentation_trade_date = taiwan_presentation_session(
            local_requested_at
        )["trade_date"]
        if not isinstance(presentation_trade_date, date):
            raise RuntimeError("Taiwan presentation session returned an invalid trade date")
        start_at = datetime.combine(
            presentation_trade_date,
            time.min,
            tzinfo=TAIPEI_TZ,
        )
    else:
        start_at = local_requested_at - timedelta(days=days)
    if start_at >= local_requested_at:
        start_at = local_requested_at - timedelta(days=1)
    bounds = RequestBounds(
        max_provider_attempts=2 if acquiring else 0,
        max_external_calls=2 if acquiring else 0,
        max_subscriptions=0,
        timeout_seconds=40 if acquiring else 30,
        max_candidates=3,
        max_rows=5000,
    )
    return DataRequirementV2(
        target=InstrumentTarget(instrument=instrument),
        request=BarCapabilityRequest(
            capability_id=TW_INTRADAY_BARS_CAPABILITY_ID,
            interval=interval,
            start_at=start_at,
            end_at=local_requested_at,
            max_bars=5000,
            completed_only=False,
            price_basis="provider_default",
        ),
        purpose=DataPurpose.REPAIR if acquiring else DataPurpose.VIEWER,
        realtime_policy=policy,
        session=MarketSession.UNKNOWN,
        requested_at=requested_at,
        freshness=FreshnessRequirement(max_age_seconds=300 if not acquiring else 1),
        quality=QualityRequirement(
            require_canonical_lineage=True,
            allow_partial=False,
        ),
        bounds=bounds,
    )


def read_taiwan_intraday_bars(
    db: Session,
    *,
    stock_id: str,
    interval: str = "1m",
    range_value: str = "auto",
    requested_at: datetime | None = None,
) -> MarketDataResultV1:
    _, instrument = _instrument(db, stock_id)
    now = requested_at or datetime.now(TAIPEI_TZ)
    requirement = build_taiwan_intraday_requirement(
        instrument=instrument,
        interval=interval,
        range_value=range_value,
        policy=RealtimePolicy.CACHE_ONLY,
        requested_at=now,
        acquiring=False,
    )
    return MarketDataGateway().resolve_bars(
        requirement,
        reader=TaiwanIntradayBarRepository(db),
    )


def refresh_taiwan_intraday_bars(
    db: Session,
    *,
    stock_id: str,
    interval: str = "1m",
    range_value: str = "auto",
    policy: RealtimePolicy = RealtimePolicy.PREFER_LIVE,
    requested_at: datetime | None = None,
    descriptors: Iterable[ProviderCapabilityDescriptorV2] = TW_INTRADAY_DESCRIPTORS,
    acquisition: TaiwanIntradayAcquisitionExecutor | None = None,
) -> MarketDataResultV1:
    if policy not in {RealtimePolicy.PREFER_LIVE, RealtimePolicy.REQUIRE_LIVE}:
        raise ValueError("intraday refresh requires prefer_live or require_live")
    _, instrument = _instrument(db, stock_id)
    now = requested_at or datetime.now(TAIPEI_TZ)
    requirement = build_taiwan_intraday_requirement(
        instrument=instrument,
        interval=interval,
        range_value=range_value,
        policy=policy,
        requested_at=now,
        acquiring=True,
    )
    catalog = tuple(descriptors)
    executor = acquisition or TaiwanIntradayAcquisitionExecutor(
        clock=lambda: datetime.now(TAIPEI_TZ)
    )
    return MarketDataGateway().resolve_bars(
        requirement,
        reader=TaiwanIntradayBarRepository(db),
        descriptors=catalog,
        acquisition_port=executor,
        transaction_port=TaiwanIntradayBarTransaction(db),
    )


def _quantity_shares(bar: BarObservation) -> int | None:
    if bar.volume is None:
        return None
    if bar.volume.unit is QuantityUnit.SHARE:
        return int(bar.volume.value)
    return None


def project_taiwan_intraday_bars(
    db: Session,
    result: MarketDataResultV1,
) -> tuple[list[dict[str, object | None]], dict[str, object | None]]:
    bars = tuple(result.resolved.bars)
    observation_ids = tuple(
        bar.lineage.observation_id
        for bar in bars
        if bar.lineage.observation_id is not None
    )
    metadata = TaiwanIntradayBarRepository(db).lineage_metadata(observation_ids)
    points: list[dict[str, object | None]] = []
    component_raw_ids: set[str] = set()
    calculation_versions: set[str] = set()
    source_intervals: set[str] = set()
    for bar in bars:
        observation_id = bar.lineage.observation_id or ""
        item_metadata = metadata.get(observation_id, {})
        raw_component_json = item_metadata.get("component_raw_result_ids")
        raw_components = []
        if isinstance(raw_component_json, str) and raw_component_json:
            try:
                raw_components = json.loads(raw_component_json)
            except (TypeError, ValueError):
                raw_components = []
        component_raw_ids.update(f"raw_fetch_result:{item}" for item in raw_components)
        calculation_version = item_metadata.get("calculation_version")
        source_interval = item_metadata.get("source_interval")
        if isinstance(calculation_version, str) and calculation_version:
            calculation_versions.add(calculation_version)
        if isinstance(source_interval, str) and source_interval:
            source_intervals.add(source_interval)
        points.append(
            {
                "time": bar.start_at,
                "price": float(bar.close_price),
                "open": float(bar.open_price),
                "high": float(bar.high_price),
                "low": float(bar.low_price),
                "close": float(bar.close_price),
                "volume": _quantity_shares(bar),
                "trade_value": (
                    int(bar.turnover_value)
                    if bar.turnover_value is not None
                    else None
                ),
                "provider": bar.lineage.provider,
                "source": bar.lineage.source,
                "raw_result_id": bar.lineage.raw_receipt_id,
                "source_interval": source_interval or bar.interval,
                "calculation_version": calculation_version,
                "component_raw_result_ids": raw_components,
                "finalization": bar.finalization.value,
            }
        )
    selected = bars[-1] if bars else None
    latest_trade_date = (
        selected.start_at.astimezone(TAIPEI_TZ).date()
        if selected is not None
        else None
    )
    session_bars = [
        bar
        for bar in bars
        if latest_trade_date is not None
        and bar.start_at.astimezone(TAIPEI_TZ).date() == latest_trade_date
    ]
    continuous_bars = [
        bar
        for bar in session_bars
        if time(9, 0)
        <= bar.start_at.astimezone(TAIPEI_TZ).time()
        < time(13, 25)
    ]
    first_bar_at = continuous_bars[0].start_at if continuous_bars else None
    last_bar_at = continuous_bars[-1].start_at if continuous_bars else None
    observed_minutes_all = {
        bar.start_at.astimezone(TAIPEI_TZ).replace(second=0, microsecond=0)
        for bar in continuous_bars
    }
    requested_local = result.requirement.requested_at.astimezone(TAIPEI_TZ)
    expected_session_start = (
        datetime.combine(latest_trade_date, time(9, 0), tzinfo=TAIPEI_TZ)
        if latest_trade_date is not None
        else None
    )
    expected_full_session_last = (
        datetime.combine(latest_trade_date, time(13, 24), tzinfo=TAIPEI_TZ)
        if latest_trade_date is not None
        else None
    )
    active_same_session = bool(
        latest_trade_date == requested_local.date()
        and time(9, 0) <= requested_local.time() < time(13, 25)
    )
    expected_observed_end = expected_full_session_last
    if active_same_session and expected_session_start is not None:
        expected_observed_end = min(
            requested_local.replace(second=0, microsecond=0)
            - timedelta(minutes=1),
            expected_full_session_last,
        )
    expected_minutes = (
        {
            expected_session_start + timedelta(minutes=offset)
            for offset in range(
                max(
                    int(
                        (expected_observed_end - expected_session_start)
                        .total_seconds()
                        // 60
                    )
                    + 1,
                    0,
                )
            )
        }
        if expected_session_start is not None
        and expected_observed_end is not None
        and expected_observed_end >= expected_session_start
        else set()
    )
    observed_minutes = {
        value for value in observed_minutes_all if value in expected_minutes
    }
    expected_point_count = len(expected_minutes)
    gap_count = len(expected_minutes - observed_minutes)
    session_start_covered = bool(
        first_bar_at is not None
        and first_bar_at.astimezone(TAIPEI_TZ).time() <= time(9, 1)
    )
    expected_window_end_covered = bool(
        last_bar_at is not None
        and expected_observed_end is not None
        and last_bar_at.astimezone(TAIPEI_TZ) >= expected_observed_end
    )
    full_session_end_covered = bool(
        last_bar_at is not None
        and last_bar_at.astimezone(TAIPEI_TZ).time() >= time(13, 24)
    )
    expected_window_complete = bool(
        session_start_covered and expected_window_end_covered and gap_count == 0
    )
    coverage_status = (
        "missing"
        if not continuous_bars
        else "complete_session"
        if expected_window_complete and full_session_end_covered
        else "complete_prefix"
        if expected_window_complete
        else "sparse"
        if session_start_covered and expected_window_end_covered
        else "trailing_window"
        if not session_start_covered and expected_window_end_covered
        else "partial_prefix"
        if session_start_covered
        else "partial_window"
    )
    gap_reason = (
        None
        if gap_count == 0
        else "provider_trailing_window"
        if coverage_status == "trailing_window"
        else "missing_expected_minutes"
    )
    series_coverage = {
        "status": coverage_status,
        "trade_date": latest_trade_date,
        "observed_bar_count": len(session_bars),
        "observed_regular_minute_count": len(observed_minutes_all),
        "expected_point_count_approx": expected_point_count,
        "expected_full_session_point_count_approx": 265,
        "first_bar_at": first_bar_at,
        "last_bar_at": last_bar_at,
        "observed_start": first_bar_at,
        "observed_end": last_bar_at,
        "expected_session_start": expected_session_start,
        "expected_observed_end": expected_observed_end,
        "expected_continuous_end": (
            datetime.combine(latest_trade_date, time(13, 25), tzinfo=TAIPEI_TZ)
            if latest_trade_date is not None
            else None
        ),
        "expected_close_time": (
            datetime.combine(latest_trade_date, time(13, 30), tzinfo=TAIPEI_TZ)
            if latest_trade_date is not None
            else None
        ),
        "session_start_covered": session_start_covered,
        "session_end_covered": full_session_end_covered,
        "expected_window_end_covered": expected_window_end_covered,
        "opening_covered": session_start_covered,
        "current_window_complete": expected_window_complete,
        "continuous_session_covered": coverage_status == "complete_session",
        "session_volume_complete": coverage_status == "complete_session",
        "current_cumulative_volume_complete": expected_window_complete,
        "gap_count": gap_count,
        "gap_reason": gap_reason,
        "coverage_semantics": "observed_regular_minute_window_with_expected_session_bounds",
        "provider_session_total_volume_shares": None,
        "provider_session_total_volume_semantics": "not_projected_from_raw_receipt",
    }
    return points, {
        "provider": selected.lineage.provider if selected is not None else None,
        "source": selected.lineage.source if selected is not None else None,
        "source_interval": (
            next(iter(source_intervals))
            if len(source_intervals) == 1
            else result.requirement.request.interval
        ),
        "calculation_versions": sorted(calculation_versions),
        "component_raw_result_ids": sorted(component_raw_ids),
        "resolved_health": result.resolved.health.model_dump(mode="json"),
        "candidate_rejections": [
            item.model_dump(mode="json") for item in result.candidate_rejections
        ],
        "limitations": list(result.limitations),
        "series_coverage": series_coverage,
    }


__all__ = [
    "INTRADAY_HISTORY_FIVE_TRADING_DAY_QUERY_DAYS",
    "INTRADAY_HISTORY_INTERVAL_CONFIGS",
    "INTRADAY_HISTORY_RANGE_DAYS",
    "TaiwanIntradayBootstrapResult",
    "TaiwanIntradayBootstrapSymbolResult",
    "bootstrap_taiwan_intraday_bars",
    "build_taiwan_intraday_requirement",
    "intraday_history_config",
    "project_taiwan_intraday_bars",
    "read_taiwan_intraday_bars",
    "refresh_taiwan_intraday_bars",
]
