from datetime import date

import pytest

from app.ai.market_context.taiwan_projection import _index_freshness_by_domain
from app.market.market_chips import project_market_chip_freshness


@pytest.mark.parametrize(
    "latest,expected,status",
    [
        ("2026-09-08", "2026-09-09", "stale"),
        ("2026-09-09", "2026-09-09", "current"),
        ("2026-09-09", "2026-09-10", "stale"),
        ("2026-09-09", None, "available"),
        (None, "2026-09-09", "empty"),
    ],
)
def test_index_chips_preserve_release_window_assessment(latest, expected, status):
    calendar = {"release_windows": {"market_chip_daily": {"expected_trade_date": expected}}}
    chip = {"trade_date": latest} if latest else None
    canonical = project_market_chip_freshness(
        latest_data_date=date.fromisoformat(latest) if latest else None,
        row_count=int(bool(chip)), calendar_status=calendar,
    )
    projected = _index_freshness_by_domain(
        quote={}, intraday_bars={}, market_chip=chip, missing=[], calendar_status=calendar,
    )["chips"]
    assert canonical["status"] == status
    assert projected["resources"] == [canonical]
    assert projected["is_current"] == (status == "current")
    assert projected["expected"] == expected
