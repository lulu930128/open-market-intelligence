from sqlalchemy.orm import Session

from app.market.signal_service import calculate_latest_stock_signals
from app.watchlists import service as watchlist_service


_ALLOWED_RANK_FIELDS = {"score", "change_pct", "volume", "close"}
_ALLOWED_SORT_ORDERS = {"asc", "desc"}


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


def get_watchlist_group_latest_ranking(
    db: Session,
    group_id: int,
    include_children: bool = True,
    enabled_only: bool = True,
    rank_by: str = "score",
    sort_order: str = "desc",
    ma_windows: str = "5,20,60",
    volume_ma_windows: str = "5,20",
    limit: int = 100,
    volume_ratio_threshold: float = 1.5,
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
        limit=1000,
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

    no_data_count = 0
    error_count = 0

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

            if status == "no_data":
                no_data_count += 1

            rows.append(
                {
                    "rank": 0,
                    "stock_id": stock_id,
                    "stock_name": stock_name,
                    "time": signal_result.get("time"),
                    "close": signal_result.get("close"),
                    "volume": signal_result.get("volume"),
                    "change_pct": signal_result.get("change_pct"),
                    "score": int(signal_result.get("score", 0) or 0),
                    "status": status,
                    "signal_count": len(signals),
                    "signal_keys": [signal.get("key") for signal in signals if signal.get("key")],
                    "primary_signal_key": primary_signal.get("key") if primary_signal else None,
                    "primary_signal_label": primary_signal.get("label") if primary_signal else None,
                    "error_message": None,
                }
            )

        except Exception as exc:
            error_count += 1

            rows.append(
                {
                    "rank": 0,
                    "stock_id": stock_id,
                    "stock_name": stock_name,
                    "time": None,
                    "close": None,
                    "volume": None,
                    "change_pct": None,
                    "score": 0,
                    "status": "error",
                    "signal_count": 0,
                    "signal_keys": [],
                    "primary_signal_key": None,
                    "primary_signal_label": None,
                    "error_message": str(exc),
                }
            )

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

    return {
        "group_id": group_id,
        "include_children": include_children,
        "rank_by": rank_by,
        "sort_order": sort_order,
        "requested_stock_count": len(unique_items),
        "ranked_count": len(sortable_rows),
        "no_data_count": no_data_count,
        "error_count": error_count,
        "results": ranked_results,
    }