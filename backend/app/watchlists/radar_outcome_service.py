from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import json
from numbers import Real
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import (
    MarketDailyPrice,
    MarketIntradayBar,
    WatchlistRadarOutcome,
    WatchlistRadarSnapshotItem,
    WatchlistRadarSnapshotRun,
    utc_now,
)
from app.market.trading_calendar import next_taiwan_trading_day
from app.watchlists import service as watchlist_service


RADAR_RULE_VERSION = "radar_v1.0"

MOMENTUM_BUCKETS = {
    "limit_up_lock",
    "surge_up",
    "breakout_high",
    "trend_reclaim",
    "volume_up",
    "momentum",
    "pullback",
    "breakout",
    "limit_up_move",
}
RISK_BUCKETS = {
    "limit_down_liquidity",
    "selloff_risk",
    "support_break",
    "volume_down",
    "bearish_momentum",
    "risk",
    "limit_down_move",
}
OVERHEAT_BUCKETS = {"overheated", "volatility_risk"}
STRUCTURE_WATCH_BUCKETS = {"compression_watch", "volume", "watch"}
NON_SCORING_BUCKETS = {"quiet", "no_data", "error"}


class WatchlistRadarSnapshotNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class WatchlistRadarSnapshotSaveResult:
    snapshot: dict[str, Any]
    created: bool


@dataclass(frozen=True)
class WatchlistRadarOutcomeBar:
    trade_date: date
    open_price: float | None
    high_price: float | None
    low_price: float | None
    close_price: float
    trade_volume: int | None
    source: str


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("/", "-")
    try:
        return datetime.fromisoformat(normalized[:10]).date()
    except ValueError:
        return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, Real) and value == value:
        return float(value)
    return None


def _pct_change(current: float | None, base: float | None) -> float | None:
    if current is None or base is None or base == 0:
        return None
    return round(((current - base) / base) * 100, 4)


def _avg(values: list[float | None]) -> float | None:
    valid = [value for value in values if value is not None]
    if not valid:
        return None
    return round(sum(valid) / len(valid), 4)


def watchlist_radar_snapshot_date(radar: dict[str, Any]) -> date:
    return (
        _as_date(radar.get("trade_date"))
        or _as_date(radar.get("target_trade_date"))
        or date.today()
    )


def _snapshot_to_read(run: WatchlistRadarSnapshotRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "group_id": run.group_id,
        "include_children": run.include_children,
        "enabled_only": run.enabled_only,
        "mode": run.mode,
        "max_results": run.max_results,
        "calculation_limit": run.calculation_limit,
        "radar_rule_version": run.radar_rule_version,
        "snapshot_date": run.snapshot_date,
        "trade_date": run.trade_date,
        "target_trade_date": run.target_trade_date,
        "is_current": run.is_current,
        "current_stock_count": run.current_stock_count,
        "stale_stock_count": run.stale_stock_count,
        "requested_stock_count": run.requested_stock_count,
        "ranked_count": run.ranked_count,
        "matched_count": run.matched_count,
        "radar_count": run.radar_count,
        "no_data_count": run.no_data_count,
        "error_count": run.error_count,
        "buckets": _json_loads(run.buckets_json, []),
        "data_limitations": _json_loads(run.data_limitations_json, []),
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }


def _item_to_read(
    item: WatchlistRadarSnapshotItem,
    outcome: WatchlistRadarOutcome,
) -> dict[str, Any]:
    return {
        "id": outcome.id,
        "snapshot_item_id": item.id,
        "rank": item.rank,
        "stock_id": item.stock_id,
        "stock_name": item.stock_name,
        "bucket": item.bucket,
        "bucket_label": item.bucket_label,
        "status": outcome.status,
        "reason": outcome.reason,
        "snapshot_date": outcome.snapshot_date,
        "outcome_trade_date": outcome.outcome_trade_date,
        "signal_close_price": outcome.signal_close_price,
        "outcome_open_price": outcome.outcome_open_price,
        "outcome_high_price": outcome.outcome_high_price,
        "outcome_low_price": outcome.outcome_low_price,
        "outcome_close_price": outcome.outcome_close_price,
        "outcome_volume": outcome.outcome_volume,
        "open_gap_pct": outcome.open_gap_pct,
        "close_return_pct": outcome.close_return_pct,
        "max_favorable_pct": outcome.max_favorable_pct,
        "max_adverse_pct": outcome.max_adverse_pct,
        "intraday_range_pct": outcome.intraday_range_pct,
        "volume_change_pct": outcome.volume_change_pct,
    }


def _latest_snapshot(
    *,
    db: Session,
    group_id: int,
    mode: str,
    snapshot_date: date | None = None,
    radar_rule_version: str = RADAR_RULE_VERSION,
) -> WatchlistRadarSnapshotRun | None:
    query = (
        db.query(WatchlistRadarSnapshotRun)
        .filter(WatchlistRadarSnapshotRun.group_id == group_id)
        .filter(WatchlistRadarSnapshotRun.mode == mode)
        .filter(WatchlistRadarSnapshotRun.radar_rule_version == radar_rule_version)
    )
    if snapshot_date is not None:
        query = query.filter(WatchlistRadarSnapshotRun.snapshot_date == snapshot_date)
    return (
        query.order_by(
            WatchlistRadarSnapshotRun.snapshot_date.desc(),
            WatchlistRadarSnapshotRun.id.desc(),
        )
        .first()
    )


def _snapshot_for_scope(
    *,
    db: Session,
    group_id: int,
    mode: str,
    snapshot_date: date,
    include_children: bool,
    enabled_only: bool,
    radar_rule_version: str,
) -> WatchlistRadarSnapshotRun | None:
    return (
        db.query(WatchlistRadarSnapshotRun)
        .filter(WatchlistRadarSnapshotRun.group_id == group_id)
        .filter(WatchlistRadarSnapshotRun.mode == mode)
        .filter(WatchlistRadarSnapshotRun.snapshot_date == snapshot_date)
        .filter(WatchlistRadarSnapshotRun.include_children.is_(include_children))
        .filter(WatchlistRadarSnapshotRun.enabled_only.is_(enabled_only))
        .filter(WatchlistRadarSnapshotRun.radar_rule_version == radar_rule_version)
        .first()
    )


def _snapshot_by_id(
    *,
    db: Session,
    snapshot_run_id: int,
    group_id: int,
    mode: str,
    radar_rule_version: str,
) -> WatchlistRadarSnapshotRun | None:
    return (
        db.query(WatchlistRadarSnapshotRun)
        .filter(WatchlistRadarSnapshotRun.id == snapshot_run_id)
        .filter(WatchlistRadarSnapshotRun.group_id == group_id)
        .filter(WatchlistRadarSnapshotRun.mode == mode)
        .filter(WatchlistRadarSnapshotRun.radar_rule_version == radar_rule_version)
        .first()
    )


def _snapshot_items(
    db: Session,
    snapshot_run_id: int,
) -> list[WatchlistRadarSnapshotItem]:
    return (
        db.query(WatchlistRadarSnapshotItem)
        .filter(WatchlistRadarSnapshotItem.snapshot_run_id == snapshot_run_id)
        .order_by(WatchlistRadarSnapshotItem.rank.asc(), WatchlistRadarSnapshotItem.id.asc())
        .all()
    )


def save_watchlist_radar_snapshot_with_status(
    *,
    db: Session,
    radar: dict[str, Any],
    request: dict[str, Any],
    enabled_only: bool = True,
    radar_rule_version: str = RADAR_RULE_VERSION,
) -> WatchlistRadarSnapshotSaveResult:
    group_id = int(radar["group_id"])
    watchlist_service.get_group(db=db, group_id=group_id)
    mode = str(radar.get("mode") or request.get("mode") or "action")
    snapshot_date = watchlist_radar_snapshot_date(radar)
    include_children = bool(radar.get("include_children", True))

    existing = _snapshot_for_scope(
        db=db,
        group_id=group_id,
        mode=mode,
        snapshot_date=snapshot_date,
        include_children=include_children,
        enabled_only=enabled_only,
        radar_rule_version=radar_rule_version,
    )
    if existing is not None:
        return WatchlistRadarSnapshotSaveResult(
            snapshot=_snapshot_to_read(existing),
            created=False,
        )

    run = WatchlistRadarSnapshotRun(
        group_id=group_id,
        include_children=include_children,
        enabled_only=enabled_only,
        mode=mode,
        max_results=int(radar.get("max_results") or request.get("max_results") or 30),
        calculation_limit=int(request.get("calculation_limit") or 100),
        radar_rule_version=radar_rule_version,
        snapshot_date=snapshot_date,
        trade_date=_as_date(radar.get("trade_date")),
        target_trade_date=_as_date(radar.get("target_trade_date")),
        is_current=bool(radar.get("is_current", True)),
        current_stock_count=int(radar.get("current_stock_count") or 0),
        stale_stock_count=int(radar.get("stale_stock_count") or 0),
        requested_stock_count=int(radar.get("requested_stock_count") or 0),
        ranked_count=int(radar.get("ranked_count") or 0),
        matched_count=int(radar.get("matched_count") or 0),
        radar_count=int(radar.get("radar_count") or 0),
        no_data_count=int(radar.get("no_data_count") or 0),
        error_count=int(radar.get("error_count") or 0),
        buckets_json=_json_dumps(radar.get("buckets") or []),
        data_limitations_json=_json_dumps(radar.get("data_limitations") or []),
        request_json=_json_dumps(request),
    )
    db.add(run)
    db.flush()

    for item in radar.get("results") or []:
        if not isinstance(item, dict):
            continue
        signal_trade_date = _as_date(item.get("trade_date") or item.get("time"))
        snapshot_item = WatchlistRadarSnapshotItem(
            snapshot_run_id=run.id,
            rank=int(item.get("rank") or 0),
            source_rank=int(item["source_rank"]) if item.get("source_rank") is not None else None,
            stock_id=str(item.get("stock_id") or ""),
            stock_name=item.get("stock_name"),
            bucket=str(item.get("bucket") or "watch"),
            bucket_label=str(item.get("bucket_label") or item.get("bucket") or "watch"),
            urgency=str(item.get("urgency") or "low"),
            priority_score=float(item.get("priority_score") or 0),
            technical_evidence_score=float(item.get("technical_evidence_score") or 0),
            technical_score=float(item.get("technical_score") or 0),
            technical_grade=str(item.get("technical_grade") or "watch"),
            direction=str(item.get("direction") or "neutral"),
            signal_trade_date=signal_trade_date,
            close_price=_number(item.get("close")),
            volume=int(item["volume"]) if _number(item.get("volume")) is not None else None,
            change_pct=_number(item.get("change_pct")),
            previous_close=_number(item.get("previous_close")),
            limit_status=item.get("limit_status"),
            action_label=item.get("action_label"),
            reason=item.get("reason"),
            signal_keys_json=_json_dumps(item.get("signal_keys") or []),
            matched_signal_keys_json=_json_dumps(item.get("matched_signal_keys") or []),
            context_signals_json=_json_dumps(item.get("context_signals") or []),
            factor_scores_json=_json_dumps(item.get("factor_scores") or {}),
            price_levels_json=_json_dumps(item.get("price_levels") or {}),
            raw_item_json=_json_dumps(item),
        )
        db.add(snapshot_item)

    db.commit()
    db.refresh(run)
    return WatchlistRadarSnapshotSaveResult(
        snapshot=_snapshot_to_read(run),
        created=True,
    )


def save_watchlist_radar_snapshot(
    *,
    db: Session,
    radar: dict[str, Any],
    request: dict[str, Any],
    enabled_only: bool = True,
    radar_rule_version: str = RADAR_RULE_VERSION,
) -> dict[str, Any]:
    return save_watchlist_radar_snapshot_with_status(
        db=db,
        radar=radar,
        request=request,
        enabled_only=enabled_only,
        radar_rule_version=radar_rule_version,
    ).snapshot


def get_latest_watchlist_radar_snapshot(
    *,
    db: Session,
    group_id: int,
    mode: str = "action",
    snapshot_date: date | None = None,
    radar_rule_version: str = RADAR_RULE_VERSION,
) -> dict[str, Any] | None:
    run = _latest_snapshot(
        db=db,
        group_id=group_id,
        mode=mode,
        snapshot_date=snapshot_date,
        radar_rule_version=radar_rule_version,
    )
    return _snapshot_to_read(run) if run is not None else None


def _next_intraday_outcome_bar(
    *,
    db: Session,
    stock_id: str,
    after_date: date,
) -> WatchlistRadarOutcomeBar | None:
    trade_date = next_taiwan_trading_day(after_date, include_value=False)
    day_start = datetime.combine(trade_date, time.min)
    day_end = day_start + timedelta(days=1)
    rows = (
        db.query(MarketIntradayBar)
        .filter(MarketIntradayBar.stock_id == stock_id)
        .filter(MarketIntradayBar.interval == "1m")
        .filter(MarketIntradayBar.bar_time >= day_start)
        .filter(MarketIntradayBar.bar_time < day_end)
        .filter(MarketIntradayBar.close_price.isnot(None))
        .order_by(MarketIntradayBar.bar_time.asc(), MarketIntradayBar.id.asc())
        .all()
    )
    if not rows or rows[-1].bar_time.time() < time(13, 25):
        return None

    open_price = next(
        (
            row.open_price if row.open_price is not None else row.close_price
            for row in rows
            if row.close_price is not None
        ),
        None,
    )
    high_prices = [
        row.high_price if row.high_price is not None else row.close_price
        for row in rows
        if row.close_price is not None
    ]
    low_prices = [
        row.low_price if row.low_price is not None else row.close_price
        for row in rows
        if row.close_price is not None
    ]
    sources = sorted({str(row.source) for row in rows if row.source})

    return WatchlistRadarOutcomeBar(
        trade_date=trade_date,
        open_price=open_price,
        high_price=max(high_prices) if high_prices else None,
        low_price=min(low_prices) if low_prices else None,
        close_price=float(rows[-1].close_price),
        trade_volume=None,
        source=f"market_intraday_bar:{','.join(sources) or 'unknown'}",
    )


def _next_outcome_bar(
    *,
    db: Session,
    stock_id: str,
    after_date: date,
) -> WatchlistRadarOutcomeBar | None:
    expected_trade_date = next_taiwan_trading_day(after_date, include_value=False)
    daily = (
        db.query(MarketDailyPrice)
        .filter(MarketDailyPrice.stock_id == stock_id)
        .filter(MarketDailyPrice.trade_date == expected_trade_date)
        .filter(MarketDailyPrice.close_price.isnot(None))
        .order_by(
            MarketDailyPrice.trade_date.asc(),
            MarketDailyPrice.updated_at.desc(),
            MarketDailyPrice.id.desc(),
        )
        .first()
    )
    if daily is not None:
        return WatchlistRadarOutcomeBar(
            trade_date=daily.trade_date,
            open_price=daily.open_price,
            high_price=daily.high_price,
            low_price=daily.low_price,
            close_price=float(daily.close_price),
            trade_volume=daily.trade_volume,
            source="market_daily_price",
        )

    return _next_intraday_outcome_bar(
        db=db,
        stock_id=stock_id,
        after_date=after_date,
    )


def _outcome_status(
    *,
    bucket: str,
    close_return_pct: float | None,
    max_favorable_pct: float | None,
    max_adverse_pct: float | None,
    intraday_range_pct: float | None,
) -> tuple[str, str]:
    if bucket in NON_SCORING_BUCKETS:
        return "unevaluable", "此 bucket 不作 T+1 命中判定。"
    if close_return_pct is None:
        return "unevaluable", "缺少可比較的收盤價。"

    favorable = max_favorable_pct or 0
    adverse = max_adverse_pct or 0

    if bucket in MOMENTUM_BUCKETS:
        if close_return_pct >= 0 or favorable >= 2:
            return "hit", "續強/突破類 bucket 在 T+1 維持正向或出現有利延伸。"
        if close_return_pct <= -2 or adverse <= -4:
            return "miss", "續強/突破類 bucket 在 T+1 明顯反向或不利走勢擴大。"
        return "neutral", "T+1 未明顯延續也未明顯失效。"

    if bucket in RISK_BUCKETS:
        if close_return_pct <= 0 or adverse <= -2:
            return "hit", "風控/轉弱類 bucket 在 T+1 延續弱勢或出現不利走勢。"
        if close_return_pct >= 2 and adverse > -1:
            return "miss", "風控/轉弱類 bucket 在 T+1 快速修復。"
        return "neutral", "T+1 風險未擴大但也未完全修復。"

    if bucket in OVERHEAT_BUCKETS:
        if close_return_pct < 0 or adverse <= -2:
            return "hit", "過熱/波動 bucket 在 T+1 出現降溫、回落或不利波動。"
        if close_return_pct >= 2 and adverse > -1:
            return "miss", "過熱/波動 bucket 在 T+1 仍強勢且回撤有限。"
        return "neutral", "T+1 波動或降溫訊號不明顯。"

    if bucket in STRUCTURE_WATCH_BUCKETS:
        if abs(close_return_pct) >= 2 or (intraday_range_pct is not None and intraday_range_pct >= 3):
            return "hit", "觀察/壓縮 bucket 在 T+1 出現可驗證波動展開。"
        return "neutral", "觀察/壓縮 bucket 在 T+1 尚未展開。"

    return "neutral", "此 bucket 使用保守 T+1 觀察判定。"


def _evaluate_item(
    *,
    db: Session,
    run: WatchlistRadarSnapshotRun,
    item: WatchlistRadarSnapshotItem,
) -> WatchlistRadarOutcome:
    base_date = item.signal_trade_date or run.trade_date or run.snapshot_date
    outcome_bar = _next_outcome_bar(db=db, stock_id=item.stock_id, after_date=base_date)
    signal_close = item.close_price

    values: dict[str, Any] = {
        "snapshot_run_id": run.id,
        "snapshot_item_id": item.id,
        "group_id": run.group_id,
        "stock_id": item.stock_id,
        "bucket": item.bucket,
        "snapshot_date": run.snapshot_date,
        "signal_close_price": signal_close,
        "evaluated_at": utc_now(),
    }

    if outcome_bar is None:
        values.update(
            {
                "outcome_trade_date": None,
                "status": "pending",
                "reason": "尚無 snapshot 後的日線或完整收盤分時資料可評估。",
            }
        )
    elif signal_close is None or signal_close <= 0:
        values.update(
            {
                "outcome_trade_date": outcome_bar.trade_date,
                "status": "unevaluable",
                "reason": "snapshot 缺少有效收盤價，無法計算 T+1 報酬。",
                "outcome_open_price": outcome_bar.open_price,
                "outcome_high_price": outcome_bar.high_price,
                "outcome_low_price": outcome_bar.low_price,
                "outcome_close_price": outcome_bar.close_price,
                "outcome_volume": outcome_bar.trade_volume,
            }
        )
    else:
        open_gap_pct = _pct_change(outcome_bar.open_price, signal_close)
        close_return_pct = _pct_change(outcome_bar.close_price, signal_close)
        max_favorable_pct = _pct_change(outcome_bar.high_price, signal_close)
        max_adverse_pct = _pct_change(outcome_bar.low_price, signal_close)
        intraday_range_pct = None
        if (
            outcome_bar.high_price is not None
            and outcome_bar.low_price is not None
            and signal_close
        ):
            intraday_range_pct = round(
                ((outcome_bar.high_price - outcome_bar.low_price) / signal_close)
                * 100,
                4,
            )
        volume_change_pct = _pct_change(
            float(outcome_bar.trade_volume)
            if outcome_bar.trade_volume is not None
            else None,
            float(item.volume) if item.volume is not None else None,
        )
        status_value, reason = _outcome_status(
            bucket=item.bucket,
            close_return_pct=close_return_pct,
            max_favorable_pct=max_favorable_pct,
            max_adverse_pct=max_adverse_pct,
            intraday_range_pct=intraday_range_pct,
        )
        if outcome_bar.source.startswith("market_intraday_bar:"):
            reason = f"{reason}；結果使用收盤後分時資料彙整。"
        values.update(
            {
                "outcome_trade_date": outcome_bar.trade_date,
                "status": status_value,
                "reason": reason,
                "outcome_open_price": outcome_bar.open_price,
                "outcome_high_price": outcome_bar.high_price,
                "outcome_low_price": outcome_bar.low_price,
                "outcome_close_price": outcome_bar.close_price,
                "outcome_volume": outcome_bar.trade_volume,
                "open_gap_pct": open_gap_pct,
                "close_return_pct": close_return_pct,
                "max_favorable_pct": max_favorable_pct,
                "max_adverse_pct": max_adverse_pct,
                "intraday_range_pct": intraday_range_pct,
                "volume_change_pct": volume_change_pct,
            }
        )

    outcome = (
        db.query(WatchlistRadarOutcome)
        .filter(WatchlistRadarOutcome.snapshot_item_id == item.id)
        .first()
    )
    if outcome is None:
        outcome = WatchlistRadarOutcome(**values)
        db.add(outcome)
    else:
        for key, value in values.items():
            setattr(outcome, key, value)
    return outcome


def evaluate_watchlist_radar_outcome(
    *,
    db: Session,
    group_id: int,
    mode: str = "action",
    snapshot_run_id: int | None = None,
    snapshot_date: date | None = None,
    radar_rule_version: str = RADAR_RULE_VERSION,
) -> dict[str, Any]:
    if snapshot_run_id is not None:
        run = _snapshot_by_id(
            db=db,
            snapshot_run_id=snapshot_run_id,
            group_id=group_id,
            mode=mode,
            radar_rule_version=radar_rule_version,
        )
    else:
        run = _latest_snapshot(
            db=db,
            group_id=group_id,
            mode=mode,
            snapshot_date=snapshot_date,
            radar_rule_version=radar_rule_version,
        )
    if run is None:
        raise WatchlistRadarSnapshotNotFoundError(
            f"Watchlist radar snapshot not found for group_id={group_id}, mode={mode}."
        )

    items = _snapshot_items(db=db, snapshot_run_id=run.id)
    for item in items:
        _evaluate_item(db=db, run=run, item=item)
    db.commit()
    return get_watchlist_radar_outcome_summary(db=db, snapshot_run_id=run.id)


def _summary_from_run(
    *,
    db: Session,
    run: WatchlistRadarSnapshotRun,
    item_limit: int = 12,
) -> dict[str, Any]:
    rows = (
        db.query(WatchlistRadarSnapshotItem, WatchlistRadarOutcome)
        .join(
            WatchlistRadarOutcome,
            WatchlistRadarOutcome.snapshot_item_id == WatchlistRadarSnapshotItem.id,
        )
        .filter(WatchlistRadarSnapshotItem.snapshot_run_id == run.id)
        .order_by(WatchlistRadarSnapshotItem.rank.asc(), WatchlistRadarSnapshotItem.id.asc())
        .all()
    )
    outcomes = [outcome for _item, outcome in rows]
    counts = Counter(outcome.status for outcome in outcomes)
    bucket_rows: dict[str, list[tuple[WatchlistRadarSnapshotItem, WatchlistRadarOutcome]]] = defaultdict(list)
    for item, outcome in rows:
        bucket_rows[item.bucket].append((item, outcome))

    bucket_summaries: list[dict[str, Any]] = []
    for bucket, values in bucket_rows.items():
        bucket_counts = Counter(outcome.status for _item, outcome in values)
        bucket_summaries.append(
            {
                "bucket": bucket,
                "bucket_label": values[0][0].bucket_label,
                "total_count": len(values),
                "hit_count": bucket_counts.get("hit", 0),
                "miss_count": bucket_counts.get("miss", 0),
                "neutral_count": bucket_counts.get("neutral", 0),
                "unevaluable_count": bucket_counts.get("unevaluable", 0),
                "pending_count": bucket_counts.get("pending", 0),
                "avg_close_return_pct": _avg([outcome.close_return_pct for _item, outcome in values]),
                "avg_max_adverse_pct": _avg([outcome.max_adverse_pct for _item, outcome in values]),
            }
        )

    evaluated_at = max((outcome.evaluated_at for outcome in outcomes), default=None)
    status = "not_evaluated"
    if outcomes:
        status = "pending" if counts.get("pending", 0) == len(outcomes) else "evaluated"

    data_limitations = list(_json_loads(run.data_limitations_json, []))
    if counts.get("pending", 0):
        data_limitations.append("部分雷達項目尚無 snapshot 後的日線或完整收盤分時資料。")
    if counts.get("unevaluable", 0):
        data_limitations.append("部分雷達項目缺少必要價格或屬於不評分 bucket。")

    return {
        "status": status,
        "snapshot": _snapshot_to_read(run),
        "evaluated_at": evaluated_at,
        "total_count": len(outcomes),
        "hit_count": counts.get("hit", 0),
        "miss_count": counts.get("miss", 0),
        "neutral_count": counts.get("neutral", 0),
        "unevaluable_count": counts.get("unevaluable", 0),
        "pending_count": counts.get("pending", 0),
        "avg_close_return_pct": _avg([outcome.close_return_pct for outcome in outcomes]),
        "avg_max_favorable_pct": _avg([outcome.max_favorable_pct for outcome in outcomes]),
        "avg_max_adverse_pct": _avg([outcome.max_adverse_pct for outcome in outcomes]),
        "bucket_summaries": bucket_summaries,
        "items": [
            _item_to_read(item, outcome)
            for item, outcome in rows[: max(1, min(item_limit, 50))]
        ],
        "data_limitations": data_limitations,
    }


def get_watchlist_radar_outcome_summary(
    *,
    db: Session,
    snapshot_run_id: int,
    item_limit: int = 12,
) -> dict[str, Any]:
    run = (
        db.query(WatchlistRadarSnapshotRun)
        .filter(WatchlistRadarSnapshotRun.id == snapshot_run_id)
        .first()
    )
    if run is None:
        raise WatchlistRadarSnapshotNotFoundError(
            f"Watchlist radar snapshot id={snapshot_run_id} not found."
        )
    return _summary_from_run(db=db, run=run, item_limit=item_limit)


def get_latest_watchlist_radar_outcome_summary(
    *,
    db: Session,
    group_id: int,
    mode: str = "action",
    snapshot_date: date | None = None,
    item_limit: int = 12,
    radar_rule_version: str = RADAR_RULE_VERSION,
) -> dict[str, Any]:
    run = _latest_snapshot(
        db=db,
        group_id=group_id,
        mode=mode,
        snapshot_date=snapshot_date,
        radar_rule_version=radar_rule_version,
    )
    if run is None:
        return {
            "status": "no_snapshot",
            "snapshot": None,
            "evaluated_at": None,
            "total_count": 0,
            "hit_count": 0,
            "miss_count": 0,
            "neutral_count": 0,
            "unevaluable_count": 0,
            "pending_count": 0,
            "avg_close_return_pct": None,
            "avg_max_favorable_pct": None,
            "avg_max_adverse_pct": None,
            "bucket_summaries": [],
            "items": [],
            "data_limitations": ["尚未保存雷達快照。"],
        }
    return _summary_from_run(db=db, run=run, item_limit=item_limit)


def list_watchlist_radar_outcome_summaries(
    *,
    db: Session,
    group_id: int,
    mode: str = "action",
    limit: int = 30,
    item_limit: int = 8,
    radar_rule_version: str = RADAR_RULE_VERSION,
) -> list[dict[str, Any]]:
    watchlist_service.get_group(db=db, group_id=group_id)
    runs = (
        db.query(WatchlistRadarSnapshotRun)
        .filter(WatchlistRadarSnapshotRun.group_id == group_id)
        .filter(WatchlistRadarSnapshotRun.mode == mode)
        .filter(WatchlistRadarSnapshotRun.radar_rule_version == radar_rule_version)
        .order_by(
            WatchlistRadarSnapshotRun.snapshot_date.desc(),
            WatchlistRadarSnapshotRun.id.desc(),
        )
        .limit(max(1, min(limit, 120)))
        .all()
    )
    return [
        _summary_from_run(db=db, run=run, item_limit=item_limit)
        for run in runs
    ]
