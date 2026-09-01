"""Taiwan intraday bar application platform over Shared Market Data Core."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import json
from typing import Iterable

from sqlalchemy.orm import Session

from app.db.models import StockMaster
from app.market.intraday_repository import TaiwanIntradayBarRepository
from app.market.intraday_transaction import TaiwanIntradayBarTransaction
from app.market.trading_calendar import taiwan_presentation_session
from app.market.tw_intraday_acquisition import TaiwanIntradayAcquisitionExecutor
from app.market.tw_intraday_capabilities import (
    TW_INTRADAY_BARS_CAPABILITY_ID,
    TW_INTRADAY_DESCRIPTORS,
)
from app.market_data.contracts import (
    BarObservation,
    InstrumentKey,
    InstrumentType,
    Market,
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
INTRADAY_HISTORY_FIVE_TRADING_DAY_QUERY_DAYS = 21
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
    normalized = str(stock_id or "").strip().upper()
    stock = (
        db.query(StockMaster)
        .filter(StockMaster.stock_id == normalized)
        .first()
    )
    if stock is None:
        raise ValueError(f"Unknown Taiwan stock id: {normalized}")
    venue = str(stock.market or "").strip().upper()
    if venue not in {"TWSE", "TPEX"}:
        raise ValueError("Taiwan intraday bars require TWSE/TPEX venue")
    instrument_type = (
        InstrumentType.ETF
        if "etf" in str(stock.instrument_type or "").strip().lower()
        else InstrumentType.STOCK
    )
    return stock, InstrumentKey(
        market=Market.TW,
        symbol=normalized,
        instrument_type=instrument_type,
        venue=venue,
    )


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
    "build_taiwan_intraday_requirement",
    "intraday_history_config",
    "project_taiwan_intraday_bars",
    "read_taiwan_intraday_bars",
    "refresh_taiwan_intraday_bars",
]
