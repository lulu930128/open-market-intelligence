from __future__ import annotations

from typing import Any

from app.market.kgi_market_data import backfill_taiwan_kgi_market_data
from app.market.schemas import TaiwanKgiDataBackfillRequest


def run_taiwan_kgi_data_backfill(
    *,
    stock_id: str,
    request: TaiwanKgiDataBackfillRequest,
) -> dict[str, Any]:
    """Run the explicit KGI maintenance operation behind a market-owned seam."""

    return backfill_taiwan_kgi_market_data(
        stock_id=stock_id,
        request=request,
    )


__all__ = ["run_taiwan_kgi_data_backfill"]
