from sqlalchemy.orm import Session

from app.market.signal_service import calculate_latest_stock_signals
from app.watchlists import service as watchlist_service


def get_watchlist_group_latest_signals(
    db: Session,
    group_id: int,
    include_children: bool = True,
    enabled_only: bool = True,
    ma_windows: str = "5,20,60",
    volume_ma_windows: str = "5,20",
    limit: int = 100,
    volume_ratio_threshold: float = 1.5,
) -> dict:
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

    results: list[dict] = []

    bullish_count = 0
    bearish_count = 0
    neutral_count = 0
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

            status = signal_result.get("status", "unknown")

            if status in {"bullish", "strong_bullish"}:
                bullish_count += 1
            elif status in {"bearish", "strong_bearish"}:
                bearish_count += 1
            elif status == "no_data":
                no_data_count += 1
            else:
                neutral_count += 1

            results.append(
                {
                    "stock_id": stock_id,
                    "stock_name": stock_name,
                    "time": signal_result.get("time"),
                    "close": signal_result.get("close"),
                    "volume": signal_result.get("volume"),
                    "change_pct": signal_result.get("change_pct"),
                    "score": signal_result.get("score", 0),
                    "status": status,
                    "signals": signal_result.get("signals", []),
                    "error_message": None,
                }
            )

        except Exception as exc:
            error_count += 1

            results.append(
                {
                    "stock_id": stock_id,
                    "stock_name": stock_name,
                    "time": None,
                    "close": None,
                    "volume": None,
                    "change_pct": None,
                    "score": 0,
                    "status": "error",
                    "signals": [],
                    "error_message": str(exc),
                }
            )

    return {
        "group_id": group_id,
        "include_children": include_children,
        "requested_stock_count": len(unique_items),
        "bullish_count": bullish_count,
        "bearish_count": bearish_count,
        "neutral_count": neutral_count,
        "no_data_count": no_data_count,
        "error_count": error_count,
        "results": results,
    }