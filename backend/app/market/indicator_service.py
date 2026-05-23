from datetime import date

from sqlalchemy.orm import Session

from app.market.service import list_stock_daily_history


def _parse_windows(value: str, default: list[int]) -> list[int]:
    if not value or value.strip() == "":
        return default

    windows: list[int] = []

    for item in value.split(","):
        item = item.strip()

        if not item:
            continue

        try:
            window = int(item)
        except ValueError as exc:
            raise ValueError(f"Invalid window value: '{item}'.") from exc

        if window <= 0:
            raise ValueError("Window value must be greater than 0.")

        if window > 1000:
            raise ValueError("Window value must be less than or equal to 1000.")

        windows.append(window)

    return sorted(set(windows))


def _moving_average(
    values: list[float | None],
    index: int,
    window: int,
    dates: list[date] | None = None,
    max_gap_days: int = 10,
) -> float | None:
    start = index - window + 1

    if start < 0:
        return None

    if dates is not None:
        window_dates = dates[start : index + 1]

        if any(
            (right - left).days > max_gap_days
            for left, right in zip(window_dates, window_dates[1:])
        ):
            return None

    window_values = values[start : index + 1]

    if any(value is None for value in window_values):
        return None

    total = sum(value for value in window_values if value is not None)

    return round(total / window, 4)


def _calculate_change(
    current: float | None,
    previous: float | None,
) -> tuple[float | None, float | None]:
    if current is None or previous is None:
        return None, None

    if previous == 0:
        return None, None

    change = current - previous
    change_pct = change / previous * 100

    return round(change, 4), round(change_pct, 4)


def _calculate_change_from_price_change(
    current: float | None,
    price_change: float | None,
) -> tuple[float | None, float | None]:
    if current is None or price_change is None:
        return None, None

    previous = current - price_change

    if previous == 0:
        return round(price_change, 4), None

    change_pct = price_change / previous * 100
    return round(price_change, 4), round(change_pct, 4)


def calculate_daily_indicators(
    db: Session,
    stock_id: str,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 250,
    ma_windows: str = "5,20,60",
    volume_ma_windows: str = "5,20",
) -> list[dict]:
    ma_window_list = _parse_windows(ma_windows, default=[5, 20, 60])
    volume_ma_window_list = _parse_windows(volume_ma_windows, default=[5, 20])

    rows = list_stock_daily_history(
        db=db,
        stock_id=stock_id,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        ascending=True,
    )

    closes: list[float | None] = [row.close_price for row in rows]
    row_dates: list[date] = [row.trade_date for row in rows]
    volumes: list[float | None] = [
        float(row.trade_volume) if row.trade_volume is not None else None
        for row in rows
    ]

    results: list[dict] = []

    for index, row in enumerate(rows):
        previous_close = closes[index - 1] if index > 0 else None
        change, change_pct = _calculate_change_from_price_change(
            row.close_price,
            row.price_change,
        )

        if change is None and change_pct is None:
            change, change_pct = _calculate_change(row.close_price, previous_close)

        ma_values = {
            f"ma{window}": _moving_average(closes, index, window, row_dates)
            for window in ma_window_list
        }

        volume_ma_values = {
            f"volume_ma{window}": _moving_average(volumes, index, window, row_dates)
            for window in volume_ma_window_list
        }

        results.append(
            {
                "time": row.trade_date,
                "close": row.close_price,
                "volume": row.trade_volume,
                "change": change,
                "change_pct": change_pct,
                "ma": ma_values,
                "volume_ma": volume_ma_values,
            }
        )

    return results


def calculate_latest_daily_indicator(
    db: Session,
    stock_id: str,
    ma_windows: str = "5,20,60",
    volume_ma_windows: str = "5,20",
) -> dict | None:
    ma_window_list = _parse_windows(ma_windows, default=[5, 20, 60])
    volume_ma_window_list = _parse_windows(volume_ma_windows, default=[5, 20])

    required_lookback = max(ma_window_list + volume_ma_window_list + [2])

    results = calculate_daily_indicators(
        db=db,
        stock_id=stock_id,
        limit=max(required_lookback, 250),
        ma_windows=ma_windows,
        volume_ma_windows=volume_ma_windows,
    )

    if not results:
        return None

    return results[-1]
