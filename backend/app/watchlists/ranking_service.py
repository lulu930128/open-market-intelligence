from datetime import date, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    FinancialMetricQuarterly,
    InstitutionalTradeDaily,
    MarginTradingDaily,
    MonthlyRevenue,
)
from app.market.calendar_status import expected_taiwan_trade_date
from app.market.intraday import get_intraday_trend
from app.market.signal_service import calculate_latest_stock_signals
from app.market.taiwan_rules import TAIWAN_DATASET_DAILY_PRICE
from app.watchlists import service as watchlist_service


_ALLOWED_RANK_FIELDS = {"watchlist", "score", "change_pct", "volume"}
_ALLOWED_SORT_ORDERS = {"asc", "desc"}
ESTIMATED_LIMIT_PCT_THRESHOLD = 9.5


def _date_text(value) -> str | None:
    if isinstance(value, (date, datetime)):
        return value.isoformat()

    return str(value) if value is not None else None


def _numeric_or_none(value) -> float | int | None:
    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)) and value == value:
        return value

    return None


def expected_daily_price_date() -> date | None:
    return expected_taiwan_trade_date(TAIWAN_DATASET_DAILY_PRICE)


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
    if target_trade_date is None:
        target_trade_date = date.today()
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


def _get_unique_watchlist_items(
    db: Session,
    group_id: int,
    include_children: bool,
    enabled_only: bool,
) -> list[dict]:
    watchlist_service.get_group(db=db, group_id=group_id)

    def find_group_node(nodes: list[dict]) -> dict | None:
        for node in nodes:
            if node["id"] == group_id:
                return node

            child_node = find_group_node(node.get("children", []))
            if child_node is not None:
                return child_node

        return None

    def ordered_group_ids(node: dict) -> list[int]:
        result = [node["id"]]

        for child in node.get("children", []):
            result.extend(ordered_group_ids(child))

        return result

    group_ids = [group_id]

    if include_children:
        tree_node = find_group_node(watchlist_service.get_group_tree(db=db))
        if tree_node is not None:
            group_ids = ordered_group_ids(tree_node)

    items: list[dict] = []

    for current_group_id in group_ids:
        items.extend(
            watchlist_service.list_items(
                db=db,
                group_id=current_group_id,
                enabled=True if enabled_only else None,
                include_children=False,
                limit=10000,
                offset=0,
            )
        )

    seen_stock_ids: set[str] = set()
    unique_items: list[dict] = []

    for item in items:
        stock_id = item["stock_id"]

        if stock_id in seen_stock_ids:
            continue

        seen_stock_ids.add(stock_id)
        unique_items.append(item)

    return unique_items


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


def _latest_rows_by_stock(
    db: Session,
    model,
    stock_ids: list[str],
    order_columns: list,
) -> dict[str, object]:
    if not stock_ids or not hasattr(db, "query"):
        return {}

    ranked_rows = (
        db.query(
            model.id.label("row_id"),
            func.row_number()
            .over(
                partition_by=model.stock_id,
                order_by=[column.desc() for column in order_columns],
            )
            .label("row_number"),
        )
        .filter(model.stock_id.in_(stock_ids))
        .subquery()
    )

    rows = (
        db.query(model)
        .join(ranked_rows, model.id == ranked_rows.c.row_id)
        .filter(ranked_rows.c.row_number == 1)
        .all()
    )
    return {row.stock_id: row for row in rows}


def _margin_balance_change(row: MarginTradingDaily | None) -> int | None:
    if row is None:
        return None

    current = getattr(row, "margin_today_balance", None)
    previous = getattr(row, "margin_previous_balance", None)
    if current is None or previous is None:
        return None

    return current - previous


def _short_balance_change(row: MarginTradingDaily | None) -> int | None:
    if row is None:
        return None

    current = getattr(row, "short_today_balance", None)
    previous = getattr(row, "short_previous_balance", None)
    if current is None or previous is None:
        return None

    return current - previous


def _stock_context_snapshot(
    *,
    institutional: InstitutionalTradeDaily | None = None,
    margin: MarginTradingDaily | None = None,
    revenue: MonthlyRevenue | None = None,
    financial: FinancialMetricQuarterly | None = None,
) -> dict[str, dict[str, object]]:
    snapshot: dict[str, dict[str, object]] = {}

    if institutional is not None:
        snapshot["institutional"] = {
            "trade_date": _date_text(institutional.trade_date),
            "total_net": _numeric_or_none(institutional.total_institutional_net),
            "foreign_net": _numeric_or_none(institutional.foreign_investor_net),
            "investment_trust_net": _numeric_or_none(institutional.investment_trust_net),
            "dealer_net": _numeric_or_none(institutional.dealer_net),
        }

    if margin is not None:
        snapshot["margin"] = {
            "trade_date": _date_text(margin.trade_date),
            "margin_balance_change": _margin_balance_change(margin),
            "margin_today_balance": _numeric_or_none(margin.margin_today_balance),
            "short_balance_change": _short_balance_change(margin),
            "short_today_balance": _numeric_or_none(margin.short_today_balance),
            "offset": _numeric_or_none(margin.offset),
        }

    if revenue is not None:
        snapshot["revenue"] = {
            "period": _date_text(revenue.period),
            "month_over_month_pct": _numeric_or_none(revenue.month_over_month_pct),
            "year_over_year_pct": _numeric_or_none(revenue.year_over_year_pct),
            "cumulative_year_over_year_pct": _numeric_or_none(
                revenue.cumulative_year_over_year_pct
            ),
        }

    if financial is not None:
        snapshot["financial"] = {
            "period": financial.period,
            "fiscal_year": _numeric_or_none(financial.fiscal_year),
            "quarter": _numeric_or_none(financial.quarter),
            "eps": _numeric_or_none(financial.eps),
            "roe": _numeric_or_none(financial.roe),
            "roa": _numeric_or_none(financial.roa),
        }

    return snapshot


def _market_context_by_stock(db: Session, stock_ids: list[str]) -> dict[str, dict[str, dict[str, object]]]:
    stock_ids = list(dict.fromkeys(stock_ids))
    if not stock_ids:
        return {}

    institutional_by_stock = _latest_rows_by_stock(
        db=db,
        model=InstitutionalTradeDaily,
        stock_ids=stock_ids,
        order_columns=[InstitutionalTradeDaily.trade_date, InstitutionalTradeDaily.id],
    )
    margin_by_stock = _latest_rows_by_stock(
        db=db,
        model=MarginTradingDaily,
        stock_ids=stock_ids,
        order_columns=[MarginTradingDaily.trade_date, MarginTradingDaily.id],
    )
    revenue_by_stock = _latest_rows_by_stock(
        db=db,
        model=MonthlyRevenue,
        stock_ids=stock_ids,
        order_columns=[MonthlyRevenue.period, MonthlyRevenue.id],
    )
    financial_by_stock = _latest_rows_by_stock(
        db=db,
        model=FinancialMetricQuarterly,
        stock_ids=stock_ids,
        order_columns=[
            FinancialMetricQuarterly.fiscal_year,
            FinancialMetricQuarterly.quarter,
            FinancialMetricQuarterly.id,
        ],
    )

    context_by_stock: dict[str, dict[str, dict[str, object]]] = {}
    for stock_id in stock_ids:
        snapshot = _stock_context_snapshot(
            institutional=institutional_by_stock.get(stock_id),
            margin=margin_by_stock.get(stock_id),
            revenue=revenue_by_stock.get(stock_id),
            financial=financial_by_stock.get(stock_id),
        )
        if snapshot:
            context_by_stock[stock_id] = snapshot

    return context_by_stock


def _with_intraday_context(
    context_snapshot: dict[str, dict[str, object]],
    overlay: dict,
) -> dict[str, dict[str, object]]:
    next_snapshot = {key: dict(value) for key, value in context_snapshot.items()}
    points = overlay.get("points") or []
    first_price = points[0]["price"] if points else None
    last_price = points[-1]["price"] if points else None
    session_change_pct = None

    if _valid_number(first_price) and _valid_number(last_price) and float(first_price) != 0:
        session_change_pct = ((float(last_price) - float(first_price)) / float(first_price)) * 100

    next_snapshot["intraday"] = {
        "time": overlay.get("time"),
        "source": overlay.get("source"),
        "previous_close": _numeric_or_none(overlay.get("previous_close")),
        "change_pct": _numeric_or_none(overlay.get("change_pct")),
        "session_change_pct": round(session_change_pct, 4)
        if session_change_pct is not None
        else None,
        "point_count": len(points),
    }
    return next_snapshot


def _build_watchlist_ranking_rows(
    db: Session,
    items: list[dict],
    ma_windows: str | None,
    volume_ma_windows: str | None,
    limit: int,
    volume_ratio_threshold: float | None,
    use_intraday: bool,
    intraday_limit: int,
    intraday_overlay_cache: dict[str, dict | None] | None = None,
) -> list[dict]:
    rows: list[dict] = []
    intraday_overlay_attempts = 0
    context_by_stock = _market_context_by_stock(
        db=db,
        stock_ids=[item["stock_id"] for item in items],
    )

    for item in items:
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
                "signal_keys": [
                    signal.get("key") for signal in signals if signal.get("key")
                ],
                "primary_signal_key": primary_signal.get("key") if primary_signal else None,
                "primary_signal_label": primary_signal.get("label") if primary_signal else None,
                "indicator_snapshot": signal_result.get("indicator_snapshot") or {},
                "context_snapshot": context_by_stock.get(stock_id, {}),
                "intraday_previous_close": None,
                "intraday_points": [],
                "error_message": None,
            }

            if use_intraday and intraday_overlay_attempts < intraday_limit:
                intraday_overlay_attempts += 1
                if intraday_overlay_cache is None:
                    overlay = _get_intraday_overlay(db=db, stock_id=stock_id)
                else:
                    if stock_id not in intraday_overlay_cache:
                        intraday_overlay_cache[stock_id] = _get_intraday_overlay(
                            db=db,
                            stock_id=stock_id,
                        )
                    overlay = intraday_overlay_cache[stock_id]

                if overlay is not None:
                    row["time"] = overlay["time"]
                    row["close"] = overlay["close"]
                    row["change"] = overlay["change"]
                    row["change_pct"] = overlay["change_pct"]
                    row["previous_close"] = overlay["previous_close"]
                    row["limit_status"] = overlay["limit_status"]
                    row["intraday_previous_close"] = overlay["previous_close"]
                    row["intraday_points"] = overlay["points"]
                    row["context_snapshot"] = _with_intraday_context(
                        context_snapshot=row["context_snapshot"],
                        overlay=overlay,
                    )

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
                    "indicator_snapshot": {},
                    "context_snapshot": context_by_stock.get(stock_id, {}),
                    "intraday_previous_close": None,
                    "intraday_points": [],
                    "error_message": str(exc),
                }
            )

    return rows


def get_watchlist_group_latest_ranking(
    db: Session,
    group_id: int,
    include_children: bool = True,
    enabled_only: bool = True,
    rank_by: str = "watchlist",
    sort_order: str = "asc",
    ma_windows: str | None = None,
    volume_ma_windows: str | None = None,
    limit: int = 100,
    volume_ratio_threshold: float | None = None,
    use_intraday: bool = False,
    intraday_limit: int = 30,
    intraday_overlay_cache: dict[str, dict | None] | None = None,
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

    unique_items = _get_unique_watchlist_items(
        db=db,
        group_id=group_id,
        include_children=include_children,
        enabled_only=enabled_only,
    )
    rows = _build_watchlist_ranking_rows(
        db=db,
        items=unique_items,
        ma_windows=ma_windows,
        volume_ma_windows=volume_ma_windows,
        limit=limit,
        volume_ratio_threshold=volume_ratio_threshold,
        use_intraday=use_intraday,
        intraday_limit=intraday_limit,
        intraday_overlay_cache=intraday_overlay_cache,
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


def get_watchlist_group_latest_ranking_batch(
    db: Session,
    group_id: int,
    include_children: bool = True,
    enabled_only: bool = True,
    rank_by: str = "watchlist",
    sort_order: str = "asc",
    ma_windows: str | None = None,
    volume_ma_windows: str | None = None,
    limit: int = 100,
    volume_ratio_threshold: float | None = None,
    use_intraday: bool = False,
    intraday_limit: int = 30,
    offset: int = 0,
    batch_size: int = 20,
) -> dict:
    rank_by = rank_by.lower()
    sort_order = sort_order.lower()

    if rank_by != "watchlist":
        raise ValueError("Progressive ranking batches only support rank_by='watchlist'.")

    if sort_order not in _ALLOWED_SORT_ORDERS:
        raise ValueError(
            f"Unsupported sort_order='{sort_order}'. "
            f"Allowed values: {', '.join(sorted(_ALLOWED_SORT_ORDERS))}."
        )

    offset = max(0, int(offset))
    batch_size = max(1, min(int(batch_size), 100))
    unique_items = _get_unique_watchlist_items(
        db=db,
        group_id=group_id,
        include_children=include_children,
        enabled_only=enabled_only,
    )
    total_stock_count = len(unique_items)
    batch_items = unique_items[offset : offset + batch_size]
    batch_intraday_limit = max(0, int(intraday_limit) - offset)
    rows = _build_watchlist_ranking_rows(
        db=db,
        items=batch_items,
        ma_windows=ma_windows,
        volume_ma_windows=volume_ma_windows,
        limit=limit,
        volume_ratio_threshold=volume_ratio_threshold,
        use_intraday=use_intraday,
        intraday_limit=batch_intraday_limit,
    )

    for index, row in enumerate(rows, start=offset + 1):
        row["rank"] = index

    no_data_count = sum(1 for row in rows if row["status"] == "no_data")
    error_count = sum(1 for row in rows if row["status"] == "error")
    freshness = _ranking_freshness(
        rows=rows,
        requested_stock_count=len(batch_items),
    )

    return {
        "group_id": group_id,
        "include_children": include_children,
        "rank_by": rank_by,
        "sort_order": sort_order,
        "offset": offset,
        "batch_size": batch_size,
        "total_stock_count": total_stock_count,
        "requested_stock_count": len(batch_items),
        "ranked_count": len(rows),
        "no_data_count": no_data_count,
        "error_count": error_count,
        **freshness,
        "has_more": offset + len(batch_items) < total_stock_count,
        "results": rows,
    }
