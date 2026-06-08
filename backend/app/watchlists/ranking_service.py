from datetime import date, datetime

from sqlalchemy.orm import Session

from app.market.intraday import get_intraday_trend
from app.market.signal_service import calculate_latest_stock_signals
from app.market.taiwan_rules import expected_daily_price_date
from app.watchlists import service as watchlist_service


_ALLOWED_RANK_FIELDS = {"watchlist", "score", "change_pct", "volume"}
_ALLOWED_SORT_ORDERS = {"asc", "desc"}
ESTIMATED_LIMIT_PCT_THRESHOLD = 9.5


def _pick_primary_signal(signals: list[dict]) -> dict | None:
    if not signals:
        return None

    for signal in signals:
        if signal.get("level") == "strong":
            return signal

    return signals[0]


def _get_rank_value(row: dict, rank_by: str):
    value = row.get(rank_by)

    if value is None:
        return None

    return value


def _valid_number(value) -> bool:
    return isinstance(value, (int, float)) and value == value


def _limit_status_from_change_pct(change_pct) -> str | None:
    if not _valid_number(change_pct):
        return None

    if float(change_pct) >= ESTIMATED_LIMIT_PCT_THRESHOLD:
        return "limit_up"

    if float(change_pct) <= -ESTIMATED_LIMIT_PCT_THRESHOLD:
        return "limit_down"

    return None


def _previous_close_from_change(
    close,
    change,
    change_pct,
) -> float | None:
    if _valid_number(close) and _valid_number(change):
        previous_close = float(close) - float(change)
        return previous_close if previous_close > 0 else None

    if _valid_number(close) and _valid_number(change_pct):
        denominator = 1 + (float(change_pct) / 100)
        if denominator > 0:
            return float(close) / denominator

    return None


def _sum_intraday_volume(points: list[dict]) -> int | None:
    volumes = [
        int(point["volume"])
        for point in points
        if _valid_number(point.get("volume")) and int(point["volume"]) > 0
    ]

    if not volumes:
        return None

    return sum(volumes)


def _compact_intraday_points(points: list[dict], max_points: int = 72) -> list[dict]:
    valid_points = [
        {
            "time": point.get("time"),
            "price": float(point["price"]),
        }
        for point in points
        if point.get("time") and _valid_number(point.get("price"))
    ]

    if len(valid_points) <= max_points:
        return valid_points

    last_index = len(valid_points) - 1
    indexes = {
        round(index * last_index / (max_points - 1))
        for index in range(max_points)
    }

    return [valid_points[index] for index in sorted(indexes)]


def _parse_row_trade_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    text = str(value or "").strip()

    if not text:
        return None

    normalized = text.replace("/", "-")

    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"

    try:
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        pass

    try:
        return date.fromisoformat(normalized[:10])
    except ValueError:
        return None


def _ranking_freshness(rows: list[dict], requested_stock_count: int) -> dict:
    target_trade_date = expected_daily_price_date()
    row_dates = [_parse_row_trade_date(row.get("time")) for row in rows]
    latest_trade_date = max(
        (row_date for row_date in row_dates if row_date is not None),
        default=None,
    )
    current_stock_count = sum(
        1
        for row_date in row_dates
        if row_date is not None and row_date >= target_trade_date
    )
    stale_stock_count = max(requested_stock_count - current_stock_count, 0)

    return {
        "trade_date": latest_trade_date,
        "target_trade_date": target_trade_date,
        "is_current": requested_stock_count == 0 or stale_stock_count == 0,
        "current_stock_count": current_stock_count,
        "stale_stock_count": stale_stock_count,
    }


def _get_intraday_overlay(db: Session, stock_id: str) -> dict | None:
    intraday = get_intraday_trend(db=db, stock_id=stock_id)
    points = intraday.get("points") or []

    if not points:
        return None

    latest = points[-1]
    latest_price = latest.get("price")
    previous_close = intraday.get("previous_close")

    if not _valid_number(latest_price):
        return None

    change_pct = None
    change = None

    if _valid_number(previous_close) and previous_close != 0:
        change = float(latest_price) - float(previous_close)
        change_pct = ((float(latest_price) - float(previous_close)) / float(previous_close)) * 100

    volume = _sum_intraday_volume(points)

    if volume is None and _valid_number(latest.get("volume")):
        volume = int(latest["volume"])

    return {
        "time": latest.get("time"),
        "close": float(latest_price),
        "volume": volume,
        "change": change,
        "change_pct": change_pct,
        "previous_close": float(previous_close) if _valid_number(previous_close) else None,
        "limit_status": _limit_status_from_change_pct(change_pct),
        "points": _compact_intraday_points(points),
        "source": intraday.get("source"),
    }


def get_watchlist_group_latest_ranking(
    db: Session,
    group_id: int,
    include_children: bool = True,
    enabled_only: bool = True,
    rank_by: str = "watchlist",
    sort_order: str = "asc",
    ma_windows: str = "5,20,60",
    volume_ma_windows: str = "5,20",
    limit: int = 100,
    volume_ratio_threshold: float = 1.5,
    use_intraday: bool = False,
    intraday_limit: int = 30,
) -> dict:
    rank_by = rank_by.lower()
    sort_order = sort_order.lower()

    if rank_by not in _ALLOWED_RANK_FIELDS:
        raise ValueError(
            f"Unsupported rank_by='{rank_by}'. "
            f"Allowed values: {', '.join(sorted(_ALLOWED_RANK_FIELDS))}."
        )

    if sort_order not in _ALLOWED_SORT_ORDERS:
        raise ValueError(
            f"Unsupported sort_order='{sort_order}'. "
            f"Allowed values: {', '.join(sorted(_ALLOWED_SORT_ORDERS))}."
        )

    watchlist_service.get_group(db=db, group_id=group_id)

    items = watchlist_service.list_items(
        db=db,
        group_id=group_id,
        enabled=True if enabled_only else None,
        include_children=include_children,
        limit=10000,
        offset=0,
    )

    seen_stock_ids: set[str] = set()
    unique_items: list[dict] = []

    for item in items:
        stock_id = item["stock_id"]

        if stock_id in seen_stock_ids:
            continue

        seen_stock_ids.add(stock_id)
        unique_items.append(item)

    rows: list[dict] = []

    intraday_overlay_attempts = 0

    for item in unique_items:
        stock_id = item["stock_id"]
        stock_name = item.get("stock_name")

        try:
            signal_result = calculate_latest_stock_signals(
                db=db,
                stock_id=stock_id,
                ma_windows=ma_windows,
                volume_ma_windows=volume_ma_windows,
                limit=limit,
                volume_ratio_threshold=volume_ratio_threshold,
            )

            signals = signal_result.get("signals", []) or []
            primary_signal = _pick_primary_signal(signals)

            status = signal_result.get("status", "unknown")
            change = signal_result.get("change")
            close = signal_result.get("close")
            change_pct = signal_result.get("change_pct")
            previous_close = _previous_close_from_change(
                close=close,
                change=change,
                change_pct=change_pct,
            )
            row = {
                "rank": 0,
                "stock_id": stock_id,
                "stock_name": stock_name,
                "time": signal_result.get("time"),
                "close": close,
                "volume": signal_result.get("volume"),
                "change": change,
                "previous_close": previous_close,
                "change_pct": change_pct,
                "limit_status": _limit_status_from_change_pct(change_pct),
                "score": int(signal_result.get("score", 0) or 0),
                "status": status,
                "signal_count": len(signals),
                "signal_keys": [signal.get("key") for signal in signals if signal.get("key")],
                "primary_signal_key": primary_signal.get("key") if primary_signal else None,
                "primary_signal_label": primary_signal.get("label") if primary_signal else None,
                "intraday_previous_close": None,
                "intraday_points": [],
                "error_message": None,
            }

            if use_intraday and intraday_overlay_attempts < intraday_limit:
                intraday_overlay_attempts += 1
                overlay = _get_intraday_overlay(db=db, stock_id=stock_id)

                if overlay is not None:
                    row["time"] = overlay["time"]
                    row["close"] = overlay["close"]
                    row["change"] = overlay["change"]
                    row["change_pct"] = overlay["change_pct"]
                    row["previous_close"] = overlay["previous_close"]
                    row["limit_status"] = overlay["limit_status"]
                    row["intraday_previous_close"] = overlay["previous_close"]
                    row["intraday_points"] = overlay["points"]

                    if overlay["volume"] is not None:
                        row["volume"] = overlay["volume"]

                    if row["status"] == "no_data":
                        row["status"] = "intraday"

            rows.append(row)

        except Exception as exc:
            rows.append(
                {
                    "rank": 0,
                    "stock_id": stock_id,
                    "stock_name": stock_name,
                    "time": None,
                    "close": None,
                    "volume": None,
                    "change": None,
                    "previous_close": None,
                    "change_pct": None,
                    "limit_status": None,
                    "score": 0,
                    "status": "error",
                    "signal_count": 0,
                    "signal_keys": [],
                    "primary_signal_key": None,
                    "primary_signal_label": None,
                    "intraday_previous_close": None,
                    "intraday_points": [],
                    "error_message": str(exc),
                }
            )

    no_data_count = sum(1 for row in rows if row["status"] == "no_data")
    error_count = sum(1 for row in rows if row["status"] == "error")

    if rank_by == "watchlist":
        sortable_rows = rows
        ranked_results = rows
    else:
        sortable_rows: list[dict] = []
        unsortable_rows: list[dict] = []

        for row in rows:
            rank_value = _get_rank_value(row, rank_by)

            if row["status"] in {"error", "no_data"} or rank_value is None:
                unsortable_rows.append(row)
            else:
                sortable_rows.append(row)

        sortable_rows.sort(
            key=lambda row: _get_rank_value(row, rank_by),
            reverse=sort_order == "desc",
        )

        ranked_results = sortable_rows + unsortable_rows

    for index, row in enumerate(ranked_results, start=1):
        row["rank"] = index

    freshness = _ranking_freshness(
        rows=ranked_results,
        requested_stock_count=len(unique_items),
    )

    return {
        "group_id": group_id,
        "include_children": include_children,
        "rank_by": rank_by,
        "sort_order": sort_order,
        "requested_stock_count": len(unique_items),
        "ranked_count": len(sortable_rows),
        "no_data_count": no_data_count,
        "error_count": error_count,
        **freshness,
        "results": ranked_results,
    }
