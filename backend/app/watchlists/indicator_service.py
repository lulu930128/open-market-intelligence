from sqlalchemy.orm import Session

from app.market.technical_indicator_gateway import (
    active_engine_contract,
    calculate_active_latest_daily_indicator,
)
from app.market.technical_parameters import get_technical_analysis_parameters
from app.watchlists import service as watchlist_service


def _get_result_field(result, field_name: str, default=None):
    if result is None:
        return default

    if isinstance(result, dict):
        return result.get(field_name, default)

    if hasattr(result, "model_dump"):
        data = result.model_dump()
        return data.get(field_name, default)

    return getattr(result, field_name, default)


def _normalize_indicator_status(point) -> str:
    if point is None:
        return "no_data"

    close = _get_result_field(point, "close")
    ma = _get_result_field(point, "ma", {}) or {}
    change_pct = _get_result_field(point, "change_pct")

    ma20 = ma.get("ma20")

    if close is None:
        return "no_data"

    if ma20 is not None:
        if close > ma20:
            return "above_ma20"
        if close < ma20:
            return "below_ma20"

    if change_pct is not None:
        if change_pct > 0:
            return "up"
        if change_pct < 0:
            return "down"

    return "normal"


def get_watchlist_group_latest_indicators(
    db: Session,
    group_id: int,
    include_children: bool = True,
    enabled_only: bool = True,
    ma_windows: str | None = None,
    volume_ma_windows: str | None = None,
) -> dict:
    technical_parameters = get_technical_analysis_parameters(
        ma_windows=ma_windows,
        volume_ma_windows=volume_ma_windows,
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

    results: list[dict] = []

    success_count = 0
    no_data_count = 0
    error_count = 0

    for item in unique_items:
        stock_id = item["stock_id"]
        stock_name = item.get("stock_name")

        try:
            point = calculate_active_latest_daily_indicator(
                db=db,
                stock_id=stock_id,
                parameters=technical_parameters,
            )

            status = _normalize_indicator_status(point)

            if status == "no_data":
                no_data_count += 1
            else:
                success_count += 1

            results.append(
                {
                    "stock_id": stock_id,
                    "stock_name": stock_name,
                    "time": _get_result_field(point, "time"),
                    "close": _get_result_field(point, "close"),
                    "volume": _get_result_field(point, "volume"),
                    "change": _get_result_field(point, "change"),
                    "change_pct": _get_result_field(point, "change_pct"),
                    "ma": _get_result_field(point, "ma", {}) or {},
                    "volume_ma": _get_result_field(point, "volume_ma", {}) or {},
                    "status": status,
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
                    "change": None,
                    "change_pct": None,
                    "ma": {},
                    "volume_ma": {},
                    "status": "error",
                    "error_message": str(exc),
                }
            )

    return {
        "group_id": group_id,
        "include_children": include_children,
        "requested_stock_count": len(unique_items),
        "success_count": success_count,
        "no_data_count": no_data_count,
        "error_count": error_count,
        "indicator_engine": active_engine_contract(),
        "results": results,
    }
