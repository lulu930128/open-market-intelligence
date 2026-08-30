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
            }
        )
    selected = bars[-1] if bars else None
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
