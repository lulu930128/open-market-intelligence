from __future__ import annotations

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from typing import Literal


_PRICE_BANDS = (
    (Decimal("0"), Decimal("10"), Decimal("0.01")),
    (Decimal("10"), Decimal("50"), Decimal("0.05")),
    (Decimal("50"), Decimal("100"), Decimal("0.1")),
    (Decimal("100"), Decimal("500"), Decimal("0.5")),
    (Decimal("500"), Decimal("1000"), Decimal("1")),
    (Decimal("1000"), None, Decimal("5")),
)


def taiwan_stock_tick_size(price: float) -> float:
    """Return the regular-board stock tick for a positive TWD price."""

    value = Decimal(str(price))
    if value <= 0:
        raise ValueError("price must be positive")
    for lower, upper, tick in _PRICE_BANDS:
        if value >= lower and (upper is None or value < upper):
            return float(tick)
    raise ValueError("unsupported Taiwan stock price")


def normalize_taiwan_stock_price(
    price: float,
    *,
    direction: Literal["nearest", "up", "down"] = "nearest",
) -> float:
    """Normalize a positive price to a valid Taiwan stock tick.

    Band boundaries are themselves valid prices.  Up/down normalization uses
    the current band anchor so values adjacent to a boundary cannot skip it.
    """

    value = Decimal(str(price))
    if value <= 0:
        raise ValueError("price must be positive")

    lower_price: Decimal | None = None
    upper_price: Decimal | None = None
    for lower, upper, tick in _PRICE_BANDS:
        if value < lower or (upper is not None and value >= upper):
            continue
        units = (value - lower) / tick
        floor_value = lower + units.to_integral_value(rounding=ROUND_FLOOR) * tick
        ceil_value = lower + units.to_integral_value(rounding=ROUND_CEILING) * tick
        lower_price = max(floor_value, lower)
        upper_price = min(ceil_value, upper) if upper is not None else ceil_value
        break

    if lower_price is None or upper_price is None:
        raise ValueError("unsupported Taiwan stock price")
    if direction == "down":
        normalized = lower_price
    elif direction == "up":
        normalized = upper_price
    elif direction == "nearest":
        normalized = (
            lower_price
            if value - lower_price < upper_price - value
            else upper_price
        )
    else:
        raise ValueError(f"unsupported normalization direction: {direction}")

    # Decimal formatting avoids binary artifacts while keeping JSON numeric.
    return float(normalized.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def shift_taiwan_stock_price_by_ticks(price: float, tick_count: int) -> float:
    """Move a valid Taiwan stock price across regular-board tick bands.

    The step is evaluated again after every move so boundaries such as 10, 50,
    100, 500, and 1000 use the correct tick on each side.  Downward movement is
    bounded at the smallest positive regular-board price.
    """

    current = normalize_taiwan_stock_price(price)
    if tick_count == 0:
        return current

    direction = 1 if tick_count > 0 else -1
    for _ in range(abs(tick_count)):
        if direction > 0:
            current = normalize_taiwan_stock_price(
                current + taiwan_stock_tick_size(current),
                direction="up",
            )
            continue
        if current <= 0.01:
            return 0.01
        probe = max(current - 0.000001, 0.000001)
        current = normalize_taiwan_stock_price(
            max(current - taiwan_stock_tick_size(probe), 0.01),
            direction="down",
        )
    return current


__all__ = [
    "normalize_taiwan_stock_price",
    "shift_taiwan_stock_price_by_ticks",
    "taiwan_stock_tick_size",
]
