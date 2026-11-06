"""A successful revision receipt must distinguish changed rows from inserts."""
from datetime import date
import json

from app.db.models import MarketDailyPrice, MarketDailyPriceRevision
from app.market.providers.tw_official_daily import TWSE_DAILY_RESOURCE_ID
from test_tw_official_daily_platform import db, _platform, _refresh, _raw_payload, FakeResponse  # noqa: F401


def test_official_volume_revision_retains_old_value_and_reports_update(db):
    payload = json.loads(_raw_payload("twse_stock_day_all_excerpt_20260825.json"))
    requirement = _refresh(symbol="2330", venue="TWSE", trade_date=date(2026, 8, 24))
    def refresh():
        return _platform(db, resource_id=TWSE_DAILY_RESOURCE_ID,
            response=FakeResponse(text=json.dumps(payload))).refresh_instrument(requirement)
    first = refresh()
    assert first.persistence.observations_inserted == 1
    row = db.query(MarketDailyPrice).filter_by(stock_id="2330").one()
    old_volume, old_receipt = row.trade_volume, row.raw_result_id
    for item in payload:
        if item["Code"] == "2330":
            item["TradeVolume"] = str(old_volume + 100)
    corrected = refresh()
    assert corrected.persistence.observations_written == 1
    assert corrected.persistence.observations_updated == 1
    assert corrected.persistence.observations_inserted == 0
    assert corrected.persistence.observations_unchanged == 0
    assert row.trade_volume == old_volume + 100
    prior = db.get(MarketDailyPriceRevision, (row.id, old_receipt))
    assert prior.trade_volume == old_volume
    repeated = refresh()
    assert repeated.persistence.observations_written == 0
    assert repeated.persistence.observations_updated == 0
    assert repeated.persistence.observations_unchanged == 1
