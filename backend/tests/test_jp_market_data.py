from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    JPDailyPrice,
    JPStockMaster,
    JPWatchlistGroup,
    JPWatchlistItem,
    USWatchlistGroup,
    USWatchlistItem,
    WatchlistGroup,
    WatchlistItem,
)
from app.jp_market.schemas import JPWatchlistGroupCreate, JPWatchlistItemCreate
from app.jp_market.service import (
    JPWatchlistDuplicateItemError,
    create_jp_watchlist_group,
    create_jp_watchlist_item,
    get_jp_resource_summary,
    list_jp_ohlc_chart_data,
    list_jp_watchlist_items,
    list_jp_watchlist_symbols,
    refresh_jp_daily_prices_from_yahoo_chart,
    search_jp_stocks,
    sync_jp_symbol_master,
    upsert_jp_daily_price_records,
)
from app.jp_market.sources import (
    JPDailyPriceRecord,
    normalize_jp_symbol,
    parse_jpx_listed_issue_rows,
    parse_yahoo_daily_prices,
    parse_yahoo_stock_record,
)


def _tokyo_timestamp(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, 15, 0, tzinfo=timezone(timedelta(hours=9))).timestamp())


YAHOO_JP_CHART_SAMPLE = {
    "chart": {
        "result": [
            {
                "meta": {
                    "symbol": "7203.T",
                    "longName": "Toyota Motor Corporation",
                    "fullExchangeName": "Tokyo Stock Exchange",
                    "instrumentType": "EQUITY",
                    "currency": "JPY",
                    "exchangeTimezoneName": "Asia/Tokyo",
                    "gmtoffset": 32400,
                },
                "timestamp": [
                    _tokyo_timestamp(2026, 6, 17),
                    _tokyo_timestamp(2026, 6, 18),
                ],
                "indicators": {
                    "quote": [
                        {
                            "open": [3000.0, 3040.0],
                            "high": [3060.0, 3090.0],
                            "low": [2990.0, 3030.0],
                            "close": [3050.0, 3080.0],
                            "volume": [12000000, 15000000],
                        }
                    ],
                    "adjclose": [
                        {
                            "adjclose": [3050.0, 3080.0],
                        }
                    ],
                },
            }
        ],
        "error": None,
    }
}


JPX_LISTED_ROWS_SAMPLE = [
    {
        "Effective Date": "20260530",
        "Local Code": 7203.0,
        "Name (English)": "Toyota Motor Corporation",
        "Section/Products": "Prime Market (Domestic)",
        "33 Sector(Code)": 3700.0,
        "33 Sector(name)": "Transportation Equipment",
        "17 Sector(Code)": 8.0,
        "17 Sector(name)": "Automobiles & Transportation Equipment",
        "Size Code (New Index Series)": 1.0,
        "Size (New Index Series)": "TOPIX Large70",
    },
    {
        "Effective Date": "20260530",
        "Local Code": "1343",
        "Name (English)": "NEXT FUNDS REIT INDEX ETF",
        "Section/Products": "ETFs/ ETNs",
        "33 Sector(Code)": "-",
        "33 Sector(name)": "-",
        "17 Sector(Code)": "-",
        "17 Sector(name)": "-",
        "Size Code": "-",
        "Size": "-",
    },
]


class JPMarketDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_normalize_jp_symbol_adds_tokyo_suffix_for_local_codes(self) -> None:
        self.assertEqual(normalize_jp_symbol("7203"), "7203.T")
        self.assertEqual(normalize_jp_symbol("130A"), "130A.T")
        self.assertEqual(normalize_jp_symbol("7203.t"), "7203.T")
        self.assertEqual(normalize_jp_symbol("TYO:7203.T"), "7203.T")

    def test_parse_yahoo_stock_record_and_daily_prices(self) -> None:
        stock = parse_yahoo_stock_record(YAHOO_JP_CHART_SAMPLE, symbol="7203")
        records = parse_yahoo_daily_prices(
            YAHOO_JP_CHART_SAMPLE,
            symbol="7203",
            source_url="https://query1.finance.yahoo.com/v8/finance/chart/7203.T",
        )

        self.assertEqual(stock.symbol, "7203.T")
        self.assertEqual(stock.local_code, "7203")
        self.assertEqual(stock.asset_type, "stock")
        self.assertEqual(stock.currency, "JPY")
        self.assertEqual(len(records), 2)
        self.assertEqual(records[-1].symbol, "7203.T")
        self.assertEqual(records[-1].close_price, 3080.0)
        self.assertEqual(records[-1].trade_volume, 15000000)

    def test_parse_jpx_listed_issue_rows_maps_master_fields(self) -> None:
        records = parse_jpx_listed_issue_rows(JPX_LISTED_ROWS_SAMPLE)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].symbol, "7203.T")
        self.assertEqual(records[0].local_code, "7203")
        self.assertEqual(records[0].market_segment, "Prime Market (Domestic)")
        self.assertEqual(records[0].sector_33_name, "Transportation Equipment")
        self.assertEqual(records[0].size_name, "TOPIX Large70")
        self.assertEqual(records[0].asset_type, "stock")
        self.assertEqual(records[1].asset_type, "ETF")

    def test_sync_jp_symbol_master_from_jpx_records(self) -> None:
        with (
            patch(
                "app.jp_market.service.fetch_jpx_listed_issues_workbook",
                return_value=(b"workbook", "https://www.jpx.co.jp/data_e.xls"),
            ),
            patch(
                "app.jp_market.service.parse_jpx_listed_issues_workbook",
                return_value=parse_jpx_listed_issue_rows(JPX_LISTED_ROWS_SAMPLE),
            ),
        ):
            result = sync_jp_symbol_master(db=self.db)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["provider"], "jpx_listed_issues")
        self.assertEqual(result["scanned_count"], 2)
        self.assertEqual(result["created_count"], 2)
        self.assertEqual(self.db.query(JPStockMaster).count(), 2)

        toyota = self.db.query(JPStockMaster).filter(JPStockMaster.symbol == "7203.T").one()
        self.assertEqual(toyota.security_name, "Toyota Motor Corporation")
        self.assertEqual(toyota.market_segment, "Prime Market (Domestic)")
        self.assertEqual(toyota.sector_17_name, "Automobiles & Transportation Equipment")

    def test_search_jp_stocks_matches_code_name_and_sector(self) -> None:
        with (
            patch(
                "app.jp_market.service.fetch_jpx_listed_issues_workbook",
                return_value=(b"workbook", "https://www.jpx.co.jp/data_e.xls"),
            ),
            patch(
                "app.jp_market.service.parse_jpx_listed_issues_workbook",
                return_value=parse_jpx_listed_issue_rows(JPX_LISTED_ROWS_SAMPLE),
            ),
        ):
            sync_jp_symbol_master(db=self.db)

        self.assertEqual(search_jp_stocks(self.db, keyword="7203")[0].symbol, "7203.T")
        self.assertEqual(search_jp_stocks(self.db, keyword="Toyota")[0].symbol, "7203.T")
        self.assertEqual(search_jp_stocks(self.db, keyword="Transportation")[0].symbol, "7203.T")

    def test_jp_watchlists_write_only_jp_tables(self) -> None:
        with (
            patch(
                "app.jp_market.service.fetch_jpx_listed_issues_workbook",
                return_value=(b"workbook", "https://www.jpx.co.jp/data_e.xls"),
            ),
            patch(
                "app.jp_market.service.parse_jpx_listed_issues_workbook",
                return_value=parse_jpx_listed_issue_rows(JPX_LISTED_ROWS_SAMPLE),
            ),
        ):
            sync_jp_symbol_master(db=self.db)

        group = create_jp_watchlist_group(
            self.db,
            JPWatchlistGroupCreate(group_name="Japan Core"),
        )
        item = create_jp_watchlist_item(
            self.db,
            JPWatchlistItemCreate(group_id=group.id, symbol="7203", note="core"),
        )
        listed_items = list_jp_watchlist_items(self.db, group_id=group.id)

        self.assertEqual(item["symbol"], "7203.T")
        self.assertEqual(item["security_name"], "Toyota Motor Corporation")
        self.assertEqual(item["market_segment"], "Prime Market (Domestic)")
        self.assertEqual(listed_items[0]["note"], "core")
        self.assertEqual(list_jp_watchlist_symbols(self.db, group_id=group.id), ["7203.T"])
        self.assertEqual(self.db.query(JPWatchlistGroup).count(), 1)
        self.assertEqual(self.db.query(JPWatchlistItem).count(), 1)
        self.assertEqual(self.db.query(WatchlistGroup).count(), 0)
        self.assertEqual(self.db.query(WatchlistItem).count(), 0)
        self.assertEqual(self.db.query(USWatchlistGroup).count(), 0)
        self.assertEqual(self.db.query(USWatchlistItem).count(), 0)

    def test_jp_watchlist_rejects_duplicate_symbol_in_group(self) -> None:
        with (
            patch(
                "app.jp_market.service.fetch_jpx_listed_issues_workbook",
                return_value=(b"workbook", "https://www.jpx.co.jp/data_e.xls"),
            ),
            patch(
                "app.jp_market.service.parse_jpx_listed_issues_workbook",
                return_value=parse_jpx_listed_issue_rows(JPX_LISTED_ROWS_SAMPLE),
            ),
        ):
            sync_jp_symbol_master(db=self.db)

        group = create_jp_watchlist_group(
            self.db,
            JPWatchlistGroupCreate(group_name="Japan Core"),
        )
        create_jp_watchlist_item(
            self.db,
            JPWatchlistItemCreate(group_id=group.id, symbol="7203"),
        )

        with self.assertRaises(JPWatchlistDuplicateItemError):
            create_jp_watchlist_item(
                self.db,
                JPWatchlistItemCreate(group_id=group.id, symbol="7203.T"),
            )

    def test_refresh_jp_daily_prices_from_yahoo_chart_upserts_stock_and_prices(self) -> None:
        with patch(
            "app.jp_market.service.fetch_yahoo_chart_payload",
            return_value=(
                YAHOO_JP_CHART_SAMPLE,
                "https://query1.finance.yahoo.com/v8/finance/chart/7203.T?range=1y&interval=1d",
            ),
        ) as fetch_mock:
            result = refresh_jp_daily_prices_from_yahoo_chart(
                db=self.db,
                symbol="7203",
                outputsize="compact",
            )

        fetch_mock.assert_called_once()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["symbol"], "7203.T")
        self.assertEqual(result["fetched_count"], 2)
        self.assertEqual(result["inserted_count"], 2)
        self.assertEqual(self.db.query(JPStockMaster).count(), 1)
        self.assertEqual(self.db.query(JPDailyPrice).count(), 2)

        stock = self.db.query(JPStockMaster).first()
        self.assertIsNotNone(stock)
        self.assertEqual(stock.local_code, "7203")

    def test_upsert_jp_daily_price_records_updates_existing_row(self) -> None:
        first = JPDailyPriceRecord(
            provider="yahoo_chart",
            symbol="7203.T",
            trade_date=datetime(2026, 6, 18).date(),
            currency="JPY",
            open_price=3000.0,
            high_price=3060.0,
            low_price=2990.0,
            close_price=3050.0,
            adjusted_close=3050.0,
            trade_volume=12000000,
            source_url="first",
            raw_payload_hash="hash-1",
        )
        second = JPDailyPriceRecord(
            provider="yahoo_chart",
            symbol="7203.T",
            trade_date=datetime(2026, 6, 18).date(),
            currency="JPY",
            open_price=3010.0,
            high_price=3070.0,
            low_price=3000.0,
            close_price=3060.0,
            adjusted_close=3060.0,
            trade_volume=13000000,
            source_url="second",
            raw_payload_hash="hash-2",
        )

        first_result = upsert_jp_daily_price_records(self.db, [first])
        second_result = upsert_jp_daily_price_records(self.db, [second])

        self.assertEqual(first_result["inserted_count"], 1)
        self.assertEqual(second_result["updated_count"], 1)
        row = self.db.query(JPDailyPrice).one()
        self.assertEqual(row.close_price, 3060.0)
        self.assertEqual(row.raw_payload_hash, "hash-2")

    def test_jp_ohlc_chart_uses_lazy_backfill_when_requested(self) -> None:
        with patch(
            "app.jp_market.service.refresh_jp_daily_prices",
            return_value={
                "status": "success",
                "provider": "yahoo_chart",
                "symbol": "7203.T",
                "fetched_count": 0,
                "inserted_count": 0,
                "updated_count": 0,
                "message": "mocked",
            },
        ) as refresh_mock:
            result = list_jp_ohlc_chart_data(
                db=self.db,
                symbol="7203",
                bars=20,
                ensure_history=True,
                to_date=datetime(2026, 6, 18).date(),
            )

        refresh_mock.assert_called_once()
        self.assertEqual(result["symbol"], "7203.T")
        self.assertEqual(result["point_count"], 0)
        self.assertEqual(result["backfill"]["status"], "success")

    def test_jp_resource_summary_reports_daily_price_and_planned_slots(self) -> None:
        upsert_jp_daily_price_records(
            self.db,
            [
                JPDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="7203.T",
                    trade_date=datetime(2026, 6, 18).date(),
                    currency="JPY",
                    open_price=3000.0,
                    high_price=3060.0,
                    low_price=2990.0,
                    close_price=3050.0,
                    adjusted_close=3050.0,
                    trade_volume=12000000,
                    source_url="source",
                    raw_payload_hash="hash",
                ),
            ],
        )

        summary = get_jp_resource_summary(db=self.db, symbol="7203")
        slots = {slot["key"]: slot for slot in summary["slots"]}

        self.assertEqual(summary["symbol"], "7203.T")
        self.assertEqual(slots["daily_price"]["status"], "available")
        self.assertTrue(slots["daily_price"]["available"])
        self.assertEqual(slots["daily_price"]["latest_date"], datetime(2026, 6, 18).date())
        self.assertEqual(slots["daily_price"]["row_count"], 1)
        self.assertEqual(slots["chips"]["status"], "planned")
        self.assertFalse(slots["chips"]["available"])
        self.assertEqual(slots["earnings"]["row_count"], 0)


if __name__ == "__main__":
    unittest.main()
