from __future__ import annotations

from datetime import date
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    MacroSeriesObservation,
    MarketDailyPrice,
    StockMaster,
    USDailyPrice,
    USCompanyProfile,
    USCorporateAction,
    USSecCompanyFact,
    USShortVolumeDaily,
    USStockMaster,
    USWatchlistGroup,
    USWatchlistItem,
    WatchlistGroup,
    WatchlistItem,
)
from app.us_market.schemas import USWatchlistGroupCreate, USWatchlistItemCreate
from app.us_market.service import (
    create_us_watchlist_group,
    create_us_watchlist_item,
    get_us_sec_fundamental_summary,
    get_us_watchlist_ranking,
    get_us_intraday_trend,
    list_us_ohlc_chart_data,
    list_us_watchlist_items,
    list_us_watchlist_symbols,
    refresh_us_daily_prices_from_yahoo_chart,
    refresh_us_sec_companyfacts,
    refresh_us_watchlist_resources,
    repair_us_daily_price_quality,
    search_us_stocks,
    upsert_macro_series_observation_records,
    upsert_us_company_profile_records,
    upsert_us_corporate_action_records,
    upsert_us_daily_price_records,
    upsert_us_sec_fact_records,
    upsert_us_short_volume_records,
    upsert_us_symbol_records,
)
from app.us_market.sources import (
    USDailyPriceRecord,
    USMarketDataFetchError,
    USShortVolumeRecord,
    normalize_us_symbol,
    parse_alphavantage_company_profile,
    parse_alphavantage_daily_prices,
    parse_alphavantage_dividends,
    parse_alphavantage_splits,
    parse_finra_short_volume,
    parse_fred_series_observations,
    parse_sec_companyfacts,
    parse_symbol_directories,
    parse_yahoo_daily_prices,
    parse_yahoo_intraday_prices,
)


NASDAQ_LISTED_SAMPLE = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N
QQQ|Invesco QQQ Trust, Series 1|G|N|N|100|Y|N
File Creation Time: 0531202621:30|||||||
"""


OTHER_LISTED_SAMPLE = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
IBM|International Business Machines Corporation|N|IBM|N|100|N|IBM
BRK.B|Berkshire Hathaway Inc. Class B|N|BRK.B|N|100|N|BRK.B
File Creation Time: 0531202621:30|||||||
"""


SEC_TICKERS_SAMPLE = {
    "fields": ["cik", "name", "ticker", "exchange"],
    "data": [
        [320193, "Apple Inc.", "AAPL", "Nasdaq"],
        [51143, "International Business Machines Corp", "IBM", "NYSE"],
    ],
}


SEC_TICKERS_MU_SAMPLE = {
    "fields": ["cik", "name", "ticker", "exchange"],
    "data": [
        [723125, "MICRON TECHNOLOGY INC", "MU", "Nasdaq"],
    ],
}


ALPHAVANTAGE_DAILY_SAMPLE = {
    "Meta Data": {
        "1. Information": "Daily Prices (open, high, low, close) and Volumes",
        "2. Symbol": "IBM",
    },
    "Time Series (Daily)": {
        "2026-05-29": {
            "1. open": "100.0000",
            "2. high": "105.0000",
            "3. low": "99.0000",
            "4. close": "104.5000",
            "5. volume": "1234567",
        },
    },
}


YAHOO_CHART_DAILY_SAMPLE = {
    "chart": {
        "result": [
            {
                "meta": {"gmtoffset": -14400},
                "timestamp": [1782748800],
                "indicators": {
                    "quote": [
                        {
                            "open": [120.0],
                            "high": [125.0],
                            "low": [119.5],
                            "close": [124.25],
                            "volume": [12345],
                        }
                    ],
                    "adjclose": [
                        {
                            "adjclose": [124.0],
                        }
                    ],
                },
            }
        ],
        "error": None,
    }
}


YAHOO_CHART_INTRADAY_SAMPLE = {
    "chart": {
        "result": [
            {
                "meta": {
                    "symbol": "MU",
                    "gmtoffset": -14400,
                    "chartPreviousClose": 90.0,
                },
                "timestamp": [1780407000, 1780407060],
                "indicators": {
                    "quote": [
                        {
                            "open": [91.0, 91.2],
                            "high": [91.5, 91.4],
                            "low": [90.8, 91.1],
                            "close": [91.25, 91.35],
                            "volume": [1000, 1500],
                        }
                    ],
                },
            }
        ],
        "error": None,
    }
}


SEC_COMPANYFACTS_SAMPLE = {
    "cik": 320193,
    "entityName": "Apple Inc.",
    "facts": {
        "us-gaap": {
            "Revenues": {
                "label": "Revenues",
                "description": "Revenue from contracts with customers.",
                "units": {
                    "USD": [
                        {
                            "fy": 2025,
                            "fp": "FY",
                            "form": "10-K",
                            "filed": "2025-10-31",
                            "start": "2024-09-29",
                            "end": "2025-09-27",
                            "val": 1000000,
                            "accn": "0000320193-25-000001",
                            "frame": "CY2025",
                        }
                    ]
                },
            }
        }
    },
}


SEC_COMPANYFACTS_MU_SAMPLE = {
    "cik": 723125,
    "entityName": "MICRON TECHNOLOGY INC",
    "facts": {
        "us-gaap": {
            "Revenues": {
                "label": "Revenues",
                "description": "Revenue from contracts with customers.",
                "units": {
                    "USD": [
                        {
                            "fy": 2025,
                            "fp": "FY",
                            "form": "10-K",
                            "filed": "2025-10-17",
                            "start": "2024-08-30",
                            "end": "2025-08-28",
                            "val": 37100000000,
                            "accn": "0000723125-25-000001",
                            "frame": "CY2025",
                        }
                    ]
                },
            }
        }
    },
}


ALPHAVANTAGE_OVERVIEW_SAMPLE = {
    "Symbol": "IBM",
    "Name": "International Business Machines Corporation",
    "Description": "Hybrid cloud and AI company.",
    "Exchange": "NYSE",
    "Currency": "USD",
    "Country": "USA",
    "Sector": "TECHNOLOGY",
    "Industry": "Information Technology Services",
    "MarketCapitalization": "240000000000",
    "EBITDA": "16000000000",
    "PERatio": "24.5",
    "PEGRatio": "1.8",
    "Beta": "0.72",
    "DividendYield": "0.031",
    "EPS": "9.25",
    "RevenueTTM": "63000000000",
    "ProfitMargin": "0.14",
    "FiscalYearEnd": "December",
    "LatestQuarter": "2026-03-31",
}


ALPHAVANTAGE_DIVIDENDS_SAMPLE = {
    "symbol": "IBM",
    "data": [
        {
            "ex_dividend_date": "2026-05-08",
            "declaration_date": "2026-04-29",
            "record_date": "2026-05-11",
            "payment_date": "2026-06-10",
            "amount": "1.68",
        }
    ],
}


ALPHAVANTAGE_SPLITS_SAMPLE = {
    "symbol": "IBM",
    "data": [
        {
            "effective_date": "1999-05-27",
            "split_factor": "2:1",
        }
    ],
}


FINRA_SHORT_VOLUME_SAMPLE = """Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market
20260529|AAPL|250|0|1000|Q,N
20260529|IBM|100|5|400|N
20260529|BF||0||B,Q,N
"""


FRED_OBSERVATIONS_SAMPLE = {
    "observations": [
        {
            "realtime_start": "2026-05-31",
            "realtime_end": "2026-05-31",
            "date": "2026-05-29",
            "value": "4.50",
        },
        {
            "realtime_start": "2026-05-31",
            "realtime_end": "2026-05-31",
            "date": "2026-05-30",
            "value": ".",
        },
    ],
}


class USMarketSourceParsingTests(unittest.TestCase):
    def test_normalize_us_symbol_accepts_ui_labels(self) -> None:
        self.assertEqual(normalize_us_symbol("AAPL / Apple"), "AAPL")
        self.assertEqual(normalize_us_symbol("nasdaq:mu"), "MU")
        self.assertEqual(normalize_us_symbol("brk.b - Berkshire"), "BRK.B")

    def test_parse_symbol_directories_merges_sec_cik_without_taiwan_fields(self) -> None:
        records = parse_symbol_directories(
            nasdaq_listed_text=NASDAQ_LISTED_SAMPLE,
            other_listed_text=OTHER_LISTED_SAMPLE,
            sec_company_payload=SEC_TICKERS_SAMPLE,
        )
        by_symbol = {record.symbol: record for record in records}

        self.assertEqual(by_symbol["AAPL"].exchange, "NASDAQ")
        self.assertEqual(by_symbol["AAPL"].cik, "0000320193")
        self.assertEqual(by_symbol["AAPL"].asset_type, "stock")
        self.assertEqual(by_symbol["IBM"].exchange, "NYSE")
        self.assertTrue(by_symbol["QQQ"].is_etf)
        self.assertEqual(by_symbol["QQQ"].asset_type, "ETF")

    def test_parse_alphavantage_daily_prices(self) -> None:
        records = parse_alphavantage_daily_prices(
            ALPHAVANTAGE_DAILY_SAMPLE,
            symbol="ibm",
            source_url="https://example.test/query",
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].symbol, "IBM")
        self.assertEqual(records[0].trade_date, date(2026, 5, 29))
        self.assertEqual(records[0].close_price, 104.5)
        self.assertEqual(records[0].trade_volume, 1234567)

    def test_parse_yahoo_daily_prices(self) -> None:
        records = parse_yahoo_daily_prices(
            YAHOO_CHART_DAILY_SAMPLE,
            symbol="mu",
            source_url="https://example.test/chart/MU",
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].symbol, "MU")
        self.assertEqual(records[0].trade_date, date(2026, 6, 29))
        self.assertEqual(records[0].close_price, 124.25)
        self.assertEqual(records[0].adjusted_close, 124.0)
        self.assertEqual(records[0].trade_volume, 12345)

    def test_parse_yahoo_intraday_prices(self) -> None:
        trend = parse_yahoo_intraday_prices(
            YAHOO_CHART_INTRADAY_SAMPLE,
            symbol="mu",
            source_url="https://example.test/chart/MU",
        )

        self.assertEqual(trend["stock_id"], "MU")
        self.assertEqual(trend["symbol"], "MU")
        self.assertEqual(trend["source"], "yahoo_finance_chart")
        self.assertEqual(trend["previous_close"], 90.0)
        self.assertEqual(trend["point_count"], 2)
        self.assertEqual(trend["points"][0]["time"], "2026-06-02T09:30:00-04:00")
        self.assertEqual(trend["points"][0]["price"], 91.25)
        self.assertEqual(trend["points"][1]["volume"], 1500)

    @patch("app.us_market.service.fetch_yahoo_chart_payload")
    def test_get_us_intraday_trend_uses_yahoo_chart_payload(self, mock_fetch) -> None:
        mock_fetch.return_value = (
            YAHOO_CHART_INTRADAY_SAMPLE,
            "https://example.test/chart/MU",
        )

        trend = get_us_intraday_trend(symbol="mu")

        mock_fetch.assert_called_once()
        self.assertEqual(trend["stock_id"], "MU")
        self.assertEqual(trend["point_count"], 2)
        self.assertEqual(trend["points"][-1]["price"], 91.35)

    def test_parse_sec_companyfacts(self) -> None:
        records = parse_sec_companyfacts(
            SEC_COMPANYFACTS_SAMPLE,
            symbol="aapl",
            source_url="https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].symbol, "AAPL")
        self.assertEqual(records[0].cik, "0000320193")
        self.assertEqual(records[0].taxonomy, "us-gaap")
        self.assertEqual(records[0].tag, "Revenues")
        self.assertEqual(records[0].value_numeric, 1000000)

    def test_parse_alphavantage_company_profile(self) -> None:
        record = parse_alphavantage_company_profile(
            ALPHAVANTAGE_OVERVIEW_SAMPLE,
            symbol="ibm",
            source_url="https://example.test/query?apikey=REDACTED",
        )

        self.assertEqual(record.symbol, "IBM")
        self.assertEqual(record.company_name, "International Business Machines Corporation")
        self.assertEqual(record.market_cap, 240000000000)
        self.assertEqual(record.pe_ratio, 24.5)
        self.assertEqual(record.latest_quarter, date(2026, 3, 31))

    def test_parse_alphavantage_corporate_actions(self) -> None:
        dividends = parse_alphavantage_dividends(
            ALPHAVANTAGE_DIVIDENDS_SAMPLE,
            symbol="ibm",
            source_url="https://example.test/dividends",
        )
        splits = parse_alphavantage_splits(
            ALPHAVANTAGE_SPLITS_SAMPLE,
            symbol="ibm",
            source_url="https://example.test/splits",
        )

        self.assertEqual(dividends[0].action_type, "dividend")
        self.assertEqual(dividends[0].event_date, date(2026, 5, 8))
        self.assertEqual(dividends[0].amount, 1.68)
        self.assertEqual(splits[0].action_type, "split")
        self.assertEqual(splits[0].split_from, 1.0)
        self.assertEqual(splits[0].split_to, 2.0)
        self.assertEqual(splits[0].split_ratio, 2.0)

    def test_parse_finra_short_volume(self) -> None:
        records = parse_finra_short_volume(
            FINRA_SHORT_VOLUME_SAMPLE,
            source_url="https://cdn.finra.org/equity/regsho/daily/CNMSshvol20260529.txt",
        )

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].symbol, "AAPL")
        self.assertEqual(records[0].trade_date, date(2026, 5, 29))
        self.assertEqual(records[0].short_volume, 250)
        self.assertEqual(records[0].short_ratio, 0.25)

    def test_parse_fred_series_observations(self) -> None:
        records = parse_fred_series_observations(
            FRED_OBSERVATIONS_SAMPLE,
            series_id="dgs10",
            series_name="10-Year Treasury Constant Maturity Rate",
            unit="percent",
            frequency="daily",
            source_url="https://example.test/fred?api_key=REDACTED",
        )

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].series_id, "DGS10")
        self.assertEqual(records[0].value, 4.5)
        self.assertIsNone(records[1].value)


class USMarketStorageIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_upserts_write_only_us_tables(self) -> None:
        symbol_records = parse_symbol_directories(
            nasdaq_listed_text=NASDAQ_LISTED_SAMPLE,
            other_listed_text=OTHER_LISTED_SAMPLE,
            sec_company_payload=SEC_TICKERS_SAMPLE,
        )

        symbol_result = upsert_us_symbol_records(self.db, symbol_records)
        self.assertEqual(symbol_result["created_count"], 4)
        self.assertEqual(self.db.query(USStockMaster).count(), 4)
        self.assertEqual(self.db.query(StockMaster).count(), 0)

        daily_records = parse_alphavantage_daily_prices(
            ALPHAVANTAGE_DAILY_SAMPLE,
            symbol="IBM",
            source_url="https://example.test/query",
        )
        daily_result = upsert_us_daily_price_records(self.db, daily_records)
        self.assertEqual(daily_result["inserted_count"], 1)
        self.assertEqual(self.db.query(USDailyPrice).count(), 1)
        self.assertEqual(self.db.query(MarketDailyPrice).count(), 0)

        fact_records = parse_sec_companyfacts(SEC_COMPANYFACTS_SAMPLE, symbol="AAPL")
        fact_result = upsert_us_sec_fact_records(self.db, fact_records)
        self.assertEqual(fact_result["inserted_count"], 1)
        self.assertEqual(self.db.query(USSecCompanyFact).count(), 1)

        profile_record = parse_alphavantage_company_profile(
            ALPHAVANTAGE_OVERVIEW_SAMPLE,
            symbol="IBM",
        )
        profile_result = upsert_us_company_profile_records(self.db, [profile_record])
        self.assertEqual(profile_result["inserted_count"], 1)
        self.assertEqual(self.db.query(USCompanyProfile).count(), 1)

        action_records = [
            *parse_alphavantage_dividends(ALPHAVANTAGE_DIVIDENDS_SAMPLE, symbol="IBM"),
            *parse_alphavantage_splits(ALPHAVANTAGE_SPLITS_SAMPLE, symbol="IBM"),
        ]
        action_result = upsert_us_corporate_action_records(self.db, action_records)
        self.assertEqual(action_result["inserted_count"], 2)
        self.assertEqual(self.db.query(USCorporateAction).count(), 2)

        short_volume_records = parse_finra_short_volume(FINRA_SHORT_VOLUME_SAMPLE)
        short_volume_result = upsert_us_short_volume_records(self.db, short_volume_records)
        self.assertEqual(short_volume_result["inserted_count"], 2)
        self.assertEqual(self.db.query(USShortVolumeDaily).count(), 2)

        macro_records = parse_fred_series_observations(
            FRED_OBSERVATIONS_SAMPLE,
            series_id="DGS10",
        )
        macro_result = upsert_macro_series_observation_records(self.db, macro_records)
        self.assertEqual(macro_result["inserted_count"], 2)
        self.assertEqual(self.db.query(MacroSeriesObservation).count(), 2)

    @patch("app.us_market.service.fetch_sec_companyfacts_payload")
    @patch("app.us_market.service.fetch_sec_company_tickers_exchange_payload")
    def test_sec_fact_refresh_resolves_missing_cik_from_sec_mapping(
        self,
        mock_fetch_sec_tickers,
        mock_fetch_companyfacts,
    ) -> None:
        self.db.add(
            USStockMaster(
                symbol="MU",
                security_name="Micron Technology, Inc. - Common Stock",
                exchange="NASDAQ",
                asset_type="stock",
                listing_source="nasdaq_trader",
                is_active=True,
            )
        )
        self.db.commit()
        mock_fetch_sec_tickers.return_value = (
            SEC_TICKERS_MU_SAMPLE,
            "https://www.sec.gov/files/company_tickers_exchange.json",
        )
        mock_fetch_companyfacts.return_value = (
            SEC_COMPANYFACTS_MU_SAMPLE,
            "https://data.sec.gov/api/xbrl/companyfacts/CIK0000723125.json",
        )

        with patch(
            "app.us_market.service.settings.us_sec_user_agent",
            "Open Market Intelligence tests contact=test@example.com",
        ):
            result = refresh_us_sec_companyfacts(self.db, symbol="MU")

        stock = self.db.query(USStockMaster).filter(USStockMaster.symbol == "MU").one()
        self.assertEqual(stock.cik, "0000723125")
        self.assertEqual(stock.sec_company_name, "MICRON TECHNOLOGY INC")
        self.assertEqual(result["cik"], "0000723125")
        self.assertEqual(result["fetched_count"], 1)
        self.assertEqual(self.db.query(USSecCompanyFact).count(), 1)
        mock_fetch_sec_tickers.assert_called_once()
        mock_fetch_companyfacts.assert_called_once()

    def test_sec_fundamental_summary_uses_latest_sec_fact_metrics(self) -> None:
        self.db.add(
            USStockMaster(
                symbol="MU",
                security_name="Micron Technology, Inc. - Common Stock",
                exchange="NASDAQ",
                asset_type="stock",
                listing_source="nasdaq_trader",
                cik="0000723125",
                sec_company_name="MICRON TECHNOLOGY INC",
                is_active=True,
            )
        )
        self.db.commit()
        fact_records = parse_sec_companyfacts(SEC_COMPANYFACTS_MU_SAMPLE, symbol="MU")
        upsert_us_sec_fact_records(self.db, fact_records)

        summary = get_us_sec_fundamental_summary(self.db, symbol="MU")

        self.assertEqual(summary["symbol"], "MU")
        self.assertEqual(summary["cik"], "0000723125")
        self.assertEqual(summary["metric_count"], 1)
        self.assertEqual(summary["metrics"][0]["metric"], "revenue")
        self.assertEqual(summary["metrics"][0]["value_numeric"], 37100000000)

    def test_upsert_us_short_volume_records_deduplicates_input_batch(self) -> None:
        records = [
            USShortVolumeRecord(
                provider="finra",
                symbol="BF",
                trade_date=date(2026, 6, 1),
                market_center="B,Q,N",
                short_volume=100,
                short_exempt_volume=0,
                total_volume=1000,
                short_ratio=0.1,
                source_url="https://example.test/finra",
                raw_payload_hash="old",
            ),
            USShortVolumeRecord(
                provider="finra",
                symbol="BF",
                trade_date=date(2026, 6, 1),
                market_center="B,Q,N",
                short_volume=250,
                short_exempt_volume=0,
                total_volume=1000,
                short_ratio=0.25,
                source_url="https://example.test/finra",
                raw_payload_hash="new",
            ),
        ]

        result = upsert_us_short_volume_records(self.db, records)

        row = self.db.query(USShortVolumeDaily).one()
        self.assertEqual(result["inserted_count"], 1)
        self.assertEqual(result["updated_count"], 0)
        self.assertEqual(row.short_volume, 250)
        self.assertEqual(row.raw_payload_hash, "new")

    def test_us_watchlists_write_only_us_tables(self) -> None:
        symbol_records = parse_symbol_directories(
            nasdaq_listed_text=NASDAQ_LISTED_SAMPLE,
            other_listed_text=OTHER_LISTED_SAMPLE,
            sec_company_payload=SEC_TICKERS_SAMPLE,
        )
        upsert_us_symbol_records(self.db, symbol_records)

        group = create_us_watchlist_group(
            self.db,
            USWatchlistGroupCreate(group_name="Mega Cap"),
        )
        item = create_us_watchlist_item(
            self.db,
            USWatchlistItemCreate(group_id=group.id, symbol="aapl", note="core"),
        )
        listed_items = list_us_watchlist_items(self.db, group_id=group.id)

        self.assertEqual(item["symbol"], "AAPL")
        self.assertEqual(item["security_name"], "Apple Inc. - Common Stock")
        self.assertEqual(listed_items[0]["symbol"], "AAPL")
        self.assertEqual(list_us_watchlist_symbols(self.db, group_id=group.id), ["AAPL"])
        self.assertEqual(self.db.query(USWatchlistGroup).count(), 1)
        self.assertEqual(self.db.query(USWatchlistItem).count(), 1)
        self.assertEqual(self.db.query(WatchlistGroup).count(), 0)
        self.assertEqual(self.db.query(WatchlistItem).count(), 0)

    def test_us_watchlist_ranking_uses_only_us_daily_prices(self) -> None:
        symbol_records = parse_symbol_directories(
            nasdaq_listed_text=NASDAQ_LISTED_SAMPLE,
            other_listed_text=OTHER_LISTED_SAMPLE,
            sec_company_payload=SEC_TICKERS_SAMPLE,
        )
        upsert_us_symbol_records(self.db, symbol_records)
        group = create_us_watchlist_group(
            self.db,
            USWatchlistGroupCreate(group_name="Mega Cap"),
        )
        create_us_watchlist_item(
            self.db,
            USWatchlistItemCreate(group_id=group.id, symbol="AAPL"),
        )
        create_us_watchlist_item(
            self.db,
            USWatchlistItemCreate(group_id=group.id, symbol="IBM"),
        )
        upsert_us_daily_price_records(
            self.db,
            [
                USDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="AAPL",
                    trade_date=date(2026, 5, 28),
                    open_price=100.0,
                    high_price=102.0,
                    low_price=99.0,
                    close_price=100.0,
                    adjusted_close=None,
                    trade_volume=1000,
                    dividend_amount=None,
                    split_coefficient=None,
                    source_url=None,
                    raw_payload_hash="aapl-1",
                ),
                USDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="AAPL",
                    trade_date=date(2026, 5, 29),
                    open_price=100.0,
                    high_price=112.0,
                    low_price=98.0,
                    close_price=110.0,
                    adjusted_close=None,
                    trade_volume=2000,
                    dividend_amount=None,
                    split_coefficient=None,
                    source_url=None,
                    raw_payload_hash="aapl-2",
                ),
                USDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="IBM",
                    trade_date=date(2026, 5, 28),
                    open_price=200.0,
                    high_price=202.0,
                    low_price=198.0,
                    close_price=200.0,
                    adjusted_close=None,
                    trade_volume=3000,
                    dividend_amount=None,
                    split_coefficient=None,
                    source_url=None,
                    raw_payload_hash="ibm-1",
                ),
                USDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="IBM",
                    trade_date=date(2026, 5, 29),
                    open_price=200.0,
                    high_price=205.0,
                    low_price=180.0,
                    close_price=190.0,
                    adjusted_close=None,
                    trade_volume=4000,
                    dividend_amount=None,
                    split_coefficient=None,
                    source_url=None,
                    raw_payload_hash="ibm-2",
                ),
            ],
        )

        ranking = get_us_watchlist_ranking(
            self.db,
            group_id=group.id,
            rank_by="change_pct",
            sort_order="desc",
        )

        self.assertEqual(ranking["requested_symbol_count"], 2)
        self.assertEqual(ranking["ranked_count"], 2)
        self.assertEqual(ranking["results"][0]["symbol"], "AAPL")
        self.assertEqual(ranking["results"][0]["change_pct"], 10.0)
        self.assertEqual(ranking["results"][1]["symbol"], "IBM")
        self.assertEqual(self.db.query(MarketDailyPrice).count(), 0)

    def test_us_watchlist_ranking_limits_intraday_overlay_attempts(self) -> None:
        symbol_records = parse_symbol_directories(
            nasdaq_listed_text=NASDAQ_LISTED_SAMPLE,
            other_listed_text=OTHER_LISTED_SAMPLE,
            sec_company_payload=SEC_TICKERS_SAMPLE,
        )
        upsert_us_symbol_records(self.db, symbol_records)
        group = create_us_watchlist_group(
            self.db,
            USWatchlistGroupCreate(group_name="Mega Cap"),
        )
        create_us_watchlist_item(
            self.db,
            USWatchlistItemCreate(group_id=group.id, symbol="AAPL"),
        )
        create_us_watchlist_item(
            self.db,
            USWatchlistItemCreate(group_id=group.id, symbol="IBM"),
        )
        self.db.add_all(
            [
                USDailyPrice(
                    provider="yahoo_chart",
                    symbol="AAPL",
                    trade_date=date(2026, 5, 29),
                    close_price=100.0,
                    trade_volume=1000,
                    raw_payload_hash="aapl-1",
                ),
                USDailyPrice(
                    provider="yahoo_chart",
                    symbol="IBM",
                    trade_date=date(2026, 5, 29),
                    close_price=190.0,
                    trade_volume=4000,
                    raw_payload_hash="ibm-1",
                ),
            ],
        )
        self.db.commit()

        with patch("app.us_market.service._get_us_intraday_overlay") as mock_overlay:
            mock_overlay.return_value = {
                "time": "2026-06-05T13:45:00-04:00",
                "close": 111.0,
                "previous_close": 100.0,
                "change": 11.0,
                "change_pct": 11.0,
                "volume": 2000,
                "source": "test_intraday",
                "points": [{"time": "2026-06-05T13:45:00-04:00", "price": 111.0}],
            }

            ranking = get_us_watchlist_ranking(
                self.db,
                group_id=group.id,
                use_intraday=True,
                intraday_limit=1,
            )

        mock_overlay.assert_called_once_with(symbol="AAPL")
        self.assertEqual(ranking["results"][0]["symbol"], "AAPL")
        self.assertEqual(ranking["results"][0]["status"], "intraday")
        self.assertEqual(ranking["results"][0]["close"], 111.0)
        self.assertEqual(ranking["results"][1]["symbol"], "IBM")
        self.assertEqual(ranking["results"][1]["status"], "ready")
        self.assertEqual(ranking["results"][1]["close"], 190.0)

    def test_us_watchlist_resource_refresh_continues_after_resource_error(self) -> None:
        symbol_records = parse_symbol_directories(
            nasdaq_listed_text=NASDAQ_LISTED_SAMPLE,
            other_listed_text=OTHER_LISTED_SAMPLE,
            sec_company_payload=SEC_TICKERS_SAMPLE,
        )
        upsert_us_symbol_records(self.db, symbol_records)
        group = create_us_watchlist_group(
            self.db,
            USWatchlistGroupCreate(group_name="Mega Cap"),
        )
        create_us_watchlist_item(
            self.db,
            USWatchlistItemCreate(group_id=group.id, symbol="AAPL"),
        )
        create_us_watchlist_item(
            self.db,
            USWatchlistItemCreate(group_id=group.id, symbol="IBM"),
        )
        progress_updates: list[tuple[int | None, int | None, str | None]] = []

        def daily_result(*, db: Session, symbol: str, outputsize: str, adjusted: bool):
            return {
                "status": "success",
                "provider": "yahoo_chart",
                "symbol": symbol,
                "fetched_count": 2,
                "inserted_count": 1,
                "updated_count": 1,
                "message": "daily ok",
            }

        def profile_result(*, db: Session, symbol: str):
            if symbol == "IBM":
                raise RuntimeError("profile unavailable")

            return {
                "status": "success",
                "provider": "alphavantage",
                "symbol": symbol,
                "fetched_count": 1,
                "inserted_count": 1,
                "updated_count": 0,
                "message": "profile ok",
            }

        def facts_result(*, db: Session, symbol: str):
            return {
                "status": "success",
                "symbol": symbol,
                "cik": "0000320193",
                "fetched_count": 3,
                "inserted_count": 3,
                "updated_count": 0,
                "message": "facts ok",
            }

        with (
            patch("app.us_market.service.refresh_us_daily_prices", side_effect=daily_result) as daily_mock,
            patch(
                "app.us_market.service.refresh_us_company_profile_from_alphavantage",
                side_effect=profile_result,
            ) as profile_mock,
            patch("app.us_market.service.refresh_us_sec_companyfacts", side_effect=facts_result) as facts_mock,
        ):
            result = refresh_us_watchlist_resources(
                self.db,
                group_id=group.id,
                include_actions=False,
                sleep_seconds=0,
                progress_callback=lambda current, total, message: progress_updates.append(
                    (current, total, message)
                ),
            )

        self.assertEqual(result["status"], "partial_success")
        self.assertEqual(result["symbol_count"], 2)
        self.assertEqual(result["success_count"], 1)
        self.assertEqual(result["partial_success_count"], 1)
        self.assertEqual(result["error_count"], 1)
        self.assertEqual(result["errors"][0]["symbol"], "IBM")
        self.assertEqual(result["errors"][0]["resource"], "profile")
        self.assertEqual(daily_mock.call_count, 2)
        self.assertEqual(profile_mock.call_count, 2)
        self.assertEqual(facts_mock.call_count, 2)
        self.assertEqual(progress_updates[0][0], 0)
        self.assertEqual(progress_updates[-1][0], 2)

    def test_us_stock_search_prioritizes_exact_symbol(self) -> None:
        self.db.add_all(
            [
                USStockMaster(
                    symbol="ABR$D",
                    security_name=(
                        "Arbor Realty Trust 6.375% Series D Cumulative "
                        "Redeemable Preferred Stock"
                    ),
                    exchange="NYSE",
                    asset_type="stock",
                ),
                USStockMaster(
                    symbol="MU",
                    security_name="Micron Technology, Inc. - Common Stock",
                    exchange="NASDAQ",
                    asset_type="stock",
                ),
            ]
        )
        self.db.commit()

        results = search_us_stocks(self.db, keyword="MU", limit=5)

        self.assertGreaterEqual(len(results), 2)
        self.assertEqual(results[0].symbol, "MU")

        labeled_results = search_us_stocks(self.db, keyword="MU / Micron", limit=5)
        self.assertEqual(labeled_results[0].symbol, "MU")

    def test_us_ohlc_chart_data_aggregates_monthly(self) -> None:
        records = [
            USDailyPriceRecord(
                provider="alphavantage",
                symbol="MU",
                trade_date=date(2026, 1, 2),
                open_price=10.0,
                high_price=12.0,
                low_price=9.0,
                close_price=11.0,
                adjusted_close=10.5,
                trade_volume=100,
                dividend_amount=None,
                split_coefficient=None,
                source_url="https://example.test/query",
                raw_payload_hash="hash-1",
            ),
            USDailyPriceRecord(
                provider="alphavantage",
                symbol="MU",
                trade_date=date(2026, 1, 5),
                open_price=11.0,
                high_price=16.0,
                low_price=10.0,
                close_price=15.0,
                adjusted_close=14.0,
                trade_volume=200,
                dividend_amount=None,
                split_coefficient=None,
                source_url="https://example.test/query",
                raw_payload_hash="hash-2",
            ),
            USDailyPriceRecord(
                provider="alphavantage",
                symbol="MU",
                trade_date=date(2026, 2, 2),
                open_price=18.0,
                high_price=21.0,
                low_price=17.0,
                close_price=20.0,
                adjusted_close=19.0,
                trade_volume=300,
                dividend_amount=None,
                split_coefficient=None,
                source_url="https://example.test/query",
                raw_payload_hash="hash-3",
            ),
        ]
        upsert_us_daily_price_records(self.db, records)

        chart = list_us_ohlc_chart_data(
            self.db,
            symbol="MU / Micron",
            timeframe="monthly",
            bars=3,
            to_date=date(2026, 2, 28),
        )

        self.assertEqual(chart["symbol"], "MU")
        self.assertEqual(chart["point_count"], 2)
        self.assertEqual(chart["points"][0]["time"], date(2026, 1, 1))
        self.assertEqual(chart["points"][0]["open"], 10.0)
        self.assertEqual(chart["points"][0]["high"], 16.0)
        self.assertEqual(chart["points"][0]["low"], 9.0)
        self.assertEqual(chart["points"][0]["close"], 15.0)
        self.assertEqual(chart["points"][0]["volume"], 300)

    def test_us_ohlc_chart_data_keeps_raw_daily_close(self) -> None:
        records = [
            USDailyPriceRecord(
                provider="yahoo_chart",
                symbol="MU",
                trade_date=date(2026, 3, 25),
                open_price=383.0,
                high_price=388.92,
                low_price=371.38,
                close_price=382.09,
                adjusted_close=381.93,
                trade_volume=55328700,
                dividend_amount=None,
                split_coefficient=None,
                source_url="https://example.test/chart",
                raw_payload_hash="raw-close-1",
            ),
            USDailyPriceRecord(
                provider="yahoo_chart",
                symbol="MU",
                trade_date=date(2026, 3, 26),
                open_price=370.02,
                high_price=374.25,
                low_price=350.0,
                close_price=355.46,
                adjusted_close=355.31,
                trade_volume=54515900,
                dividend_amount=None,
                split_coefficient=None,
                source_url="https://example.test/chart",
                raw_payload_hash="raw-close-2",
            ),
        ]
        upsert_us_daily_price_records(self.db, records)

        chart = list_us_ohlc_chart_data(
            self.db,
            symbol="MU",
            timeframe="daily",
            bars=2,
            to_date=date(2026, 3, 26),
        )

        self.assertEqual(chart["point_count"], 2)
        self.assertEqual(chart["points"][0]["close"], 382.09)
        self.assertEqual(chart["points"][1]["close"], 355.46)

    def test_us_daily_ohlc_skips_refresh_when_local_points_are_enough(self) -> None:
        records = [
            USDailyPriceRecord(
                provider="yahoo_chart",
                symbol="MU",
                trade_date=date(2026, 3, 25),
                open_price=381.0,
                high_price=386.0,
                low_price=378.0,
                close_price=382.09,
                adjusted_close=None,
                trade_volume=55328700,
                dividend_amount=None,
                split_coefficient=None,
                source_url=None,
                raw_payload_hash="raw-skip-refresh-1",
            ),
            USDailyPriceRecord(
                provider="yahoo_chart",
                symbol="MU",
                trade_date=date(2026, 3, 26),
                open_price=370.02,
                high_price=374.25,
                low_price=350.0,
                close_price=355.46,
                adjusted_close=None,
                trade_volume=54515900,
                dividend_amount=None,
                split_coefficient=None,
                source_url=None,
                raw_payload_hash="raw-skip-refresh-2",
            ),
        ]
        upsert_us_daily_price_records(self.db, records)

        with patch("app.us_market.service.refresh_us_daily_prices") as refresh_mock:
            chart = list_us_ohlc_chart_data(
                self.db,
                symbol="MU",
                timeframe="daily",
                bars=2,
                ensure_history=True,
                to_date=date(2026, 3, 26),
            )

        refresh_mock.assert_not_called()
        self.assertEqual(chart["point_count"], 2)
        self.assertIsNone(chart["backfill"])

    def test_us_daily_ohlc_refreshes_when_local_points_are_monthly_sparse(self) -> None:
        records = [
            USDailyPriceRecord(
                provider="yahoo_chart",
                symbol="AMZN",
                trade_date=date(year, month, 1),
                open_price=100.0,
                high_price=110.0,
                low_price=90.0,
                close_price=105.0,
                adjusted_close=None,
                trade_volume=1000,
                dividend_amount=None,
                split_coefficient=None,
                source_url=None,
                raw_payload_hash=f"monthly-sparse-{year}-{month}",
            )
            for year, month in [
                (2025, 7),
                (2025, 8),
                (2025, 9),
                (2025, 10),
                (2025, 11),
                (2025, 12),
                (2026, 1),
                (2026, 2),
                (2026, 3),
                (2026, 4),
                (2026, 5),
                (2026, 6),
            ]
        ]
        upsert_us_daily_price_records(self.db, records)

        with patch("app.us_market.service.refresh_us_daily_prices") as refresh_mock:
            refresh_mock.return_value = {
                "status": "success",
                "provider": "yahoo_chart",
                "symbol": "AMZN",
                "fetched_count": 0,
                "inserted_count": 0,
                "updated_count": 0,
                "message": "mocked",
            }
            chart = list_us_ohlc_chart_data(
                self.db,
                symbol="AMZN",
                timeframe="daily",
                bars=180,
                ensure_history=True,
                outputsize="compact",
                provider="yahoo_chart",
                to_date=date(2026, 6, 30),
            )

        refresh_mock.assert_called_once_with(
            db=self.db,
            symbol="AMZN",
            outputsize="compact",
            adjusted=False,
            provider="yahoo_chart",
        )
        self.assertEqual(chart["backfill"]["message"], "mocked")

    def test_us_daily_ohlc_ignores_yahoo_range_max_rows(self) -> None:
        records = [
            USDailyPriceRecord(
                provider="yahoo_chart",
                symbol="MU",
                trade_date=trade_date,
                open_price=100.0 + index,
                high_price=105.0 + index,
                low_price=95.0 + index,
                close_price=102.0 + index,
                adjusted_close=None,
                trade_volume=1000 + index,
                dividend_amount=None,
                split_coefficient=None,
                source_url="https://query1.finance.yahoo.com/v8/finance/chart/MU?range=1y&interval=1d",
                raw_payload_hash=f"clean-{index}",
            )
            for index, trade_date in enumerate(
                [
                    date(2026, 2, 27),
                    date(2026, 3, 2),
                    date(2026, 3, 3),
                    date(2026, 3, 4),
                    date(2026, 3, 5),
                    date(2026, 3, 6),
                ],
                start=1,
            )
        ]
        records.append(
            USDailyPriceRecord(
                provider="yahoo_chart",
                symbol="MU",
                trade_date=date(2026, 3, 1),
                open_price=401.47,
                high_price=981.0,
                low_price=311.49,
                close_price=971.0,
                adjusted_close=None,
                trade_volume=3_012_061_200,
                dividend_amount=None,
                split_coefficient=None,
                source_url="https://query1.finance.yahoo.com/v8/finance/chart/MU?range=max&interval=1d",
                raw_payload_hash="range-max-month-row",
            )
        )
        upsert_us_daily_price_records(self.db, records)

        chart = list_us_ohlc_chart_data(
            self.db,
            symbol="MU",
            timeframe="daily",
            bars=10,
            to_date=date(2026, 3, 7),
        )

        self.assertEqual(chart["point_count"], 6)
        self.assertNotIn(date(2026, 3, 1), [point["time"] for point in chart["points"]])
        self.assertNotIn(981.0, [point["high"] for point in chart["points"]])

    def test_us_daily_ohlc_refreshes_when_newer_yahoo_range_max_row_exists(self) -> None:
        records = [
            USDailyPriceRecord(
                provider="yahoo_chart",
                symbol="MU",
                trade_date=trade_date,
                open_price=100.0 + index,
                high_price=105.0 + index,
                low_price=95.0 + index,
                close_price=102.0 + index,
                adjusted_close=None,
                trade_volume=1000 + index,
                dividend_amount=None,
                split_coefficient=None,
                source_url="https://query1.finance.yahoo.com/v8/finance/chart/MU?range=1y&interval=1d",
                raw_payload_hash=f"clean-latest-{index}",
            )
            for index, trade_date in enumerate(
                [
                    date(2026, 5, 26),
                    date(2026, 5, 27),
                    date(2026, 5, 28),
                    date(2026, 5, 29),
                ],
                start=1,
            )
        ]
        records.append(
            USDailyPriceRecord(
                provider="yahoo_chart",
                symbol="MU",
                trade_date=date(2026, 6, 1),
                open_price=1009.72,
                high_price=1046.97,
                low_price=1009.5,
                close_price=1035.5,
                adjusted_close=None,
                trade_volume=46_305_400,
                dividend_amount=None,
                split_coefficient=None,
                source_url="https://query1.finance.yahoo.com/v8/finance/chart/MU?range=max&interval=1d",
                raw_payload_hash="range-max-latest-row",
            )
        )
        upsert_us_daily_price_records(self.db, records)

        with patch("app.us_market.service.refresh_us_daily_prices") as refresh_mock:
            refresh_mock.return_value = {
                "status": "success",
                "provider": "yahoo_chart",
                "symbol": "MU",
                "fetched_count": 0,
                "inserted_count": 0,
                "updated_count": 0,
                "message": "mocked",
            }
            chart = list_us_ohlc_chart_data(
                self.db,
                symbol="MU",
                timeframe="daily",
                bars=3,
                ensure_history=True,
                outputsize="compact",
                provider="yahoo_chart",
                to_date=date(2026, 6, 1),
            )

        refresh_mock.assert_called_once_with(
            db=self.db,
            symbol="MU",
            outputsize="compact",
            adjusted=False,
            provider="yahoo_chart",
        )
        self.assertEqual(chart["backfill"]["message"], "mocked")

    def test_us_daily_ohlc_uses_clean_cache_when_quality_refresh_fails(self) -> None:
        records = [
            USDailyPriceRecord(
                provider="yahoo_chart",
                symbol="MU",
                trade_date=trade_date,
                open_price=100.0 + index,
                high_price=105.0 + index,
                low_price=95.0 + index,
                close_price=102.0 + index,
                adjusted_close=None,
                trade_volume=1000 + index,
                dividend_amount=None,
                split_coefficient=None,
                source_url="https://query1.finance.yahoo.com/v8/finance/chart/MU?range=1y&interval=1d",
                raw_payload_hash=f"clean-fallback-{index}",
            )
            for index, trade_date in enumerate(
                [
                    date(2026, 5, 26),
                    date(2026, 5, 27),
                    date(2026, 5, 28),
                    date(2026, 5, 29),
                ],
                start=1,
            )
        ]
        records.append(
            USDailyPriceRecord(
                provider="yahoo_chart",
                symbol="MU",
                trade_date=date(2026, 6, 1),
                open_price=1009.72,
                high_price=1046.97,
                low_price=1009.5,
                close_price=1035.5,
                adjusted_close=None,
                trade_volume=46_305_400,
                dividend_amount=None,
                split_coefficient=None,
                source_url="https://query1.finance.yahoo.com/v8/finance/chart/MU?range=max&interval=1d",
                raw_payload_hash="range-max-fallback-row",
            )
        )
        upsert_us_daily_price_records(self.db, records)

        with patch("app.us_market.service.refresh_us_daily_prices") as refresh_mock:
            refresh_mock.side_effect = USMarketDataFetchError("proxy down")
            chart = list_us_ohlc_chart_data(
                self.db,
                symbol="MU",
                timeframe="daily",
                bars=3,
                ensure_history=True,
                outputsize="compact",
                provider="yahoo_chart",
                to_date=date(2026, 6, 1),
            )

        self.assertEqual(chart["point_count"], 3)
        self.assertEqual(chart["backfill"]["status"], "error")
        self.assertIn("using cached clean rows", chart["backfill"]["message"])
        self.assertNotIn(date(2026, 6, 1), [point["time"] for point in chart["points"]])

    def test_us_daily_upsert_does_not_replace_clean_yahoo_row_with_range_max(self) -> None:
        upsert_us_daily_price_records(
            self.db,
            [
                USDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="MU",
                    trade_date=date(2026, 3, 2),
                    open_price=100.0,
                    high_price=110.0,
                    low_price=90.0,
                    close_price=105.0,
                    adjusted_close=None,
                    trade_volume=1000,
                    dividend_amount=None,
                    split_coefficient=None,
                    source_url="https://query1.finance.yahoo.com/v8/finance/chart/MU?range=1y&interval=1d",
                    raw_payload_hash="clean-row",
                )
            ],
        )

        result = upsert_us_daily_price_records(
            self.db,
            [
                USDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="MU",
                    trade_date=date(2026, 3, 2),
                    open_price=400.0,
                    high_price=981.0,
                    low_price=300.0,
                    close_price=971.0,
                    adjusted_close=None,
                    trade_volume=3_012_061_200,
                    dividend_amount=None,
                    split_coefficient=None,
                    source_url="https://query1.finance.yahoo.com/v8/finance/chart/MU?range=max&interval=1d",
                    raw_payload_hash="range-max-row",
                )
            ],
        )

        row = self.db.query(USDailyPrice).filter(USDailyPrice.symbol == "MU").one()
        self.assertEqual(result["updated_count"], 0)
        self.assertEqual(row.close_price, 105.0)
        self.assertEqual(row.raw_payload_hash, "clean-row")

    def test_us_daily_upsert_replaces_range_max_row_with_clean_yahoo_row(self) -> None:
        upsert_us_daily_price_records(
            self.db,
            [
                USDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="MU",
                    trade_date=date(2026, 3, 2),
                    open_price=400.0,
                    high_price=981.0,
                    low_price=300.0,
                    close_price=971.0,
                    adjusted_close=None,
                    trade_volume=3_012_061_200,
                    dividend_amount=None,
                    split_coefficient=None,
                    source_url="https://query1.finance.yahoo.com/v8/finance/chart/MU?range=max&interval=1d",
                    raw_payload_hash="range-max-row",
                )
            ],
        )

        result = upsert_us_daily_price_records(
            self.db,
            [
                USDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="MU",
                    trade_date=date(2026, 3, 2),
                    open_price=100.0,
                    high_price=110.0,
                    low_price=90.0,
                    close_price=105.0,
                    adjusted_close=None,
                    trade_volume=1000,
                    dividend_amount=None,
                    split_coefficient=None,
                    source_url="https://query1.finance.yahoo.com/v8/finance/chart/MU?range=1y&interval=1d",
                    raw_payload_hash="clean-row",
                )
            ],
        )

        row = self.db.query(USDailyPrice).filter(USDailyPrice.symbol == "MU").one()
        self.assertEqual(result["updated_count"], 1)
        self.assertEqual(row.close_price, 105.0)
        self.assertEqual(row.raw_payload_hash, "clean-row")

    def test_us_daily_quality_repair_dry_run_reports_range_max_rows(self) -> None:
        upsert_us_daily_price_records(
            self.db,
            [
                USDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="MU",
                    trade_date=date(2026, 3, 1),
                    open_price=401.47,
                    high_price=981.0,
                    low_price=311.49,
                    close_price=971.0,
                    adjusted_close=None,
                    trade_volume=3_012_061_200,
                    dividend_amount=None,
                    split_coefficient=None,
                    source_url="https://query1.finance.yahoo.com/v8/finance/chart/MU?range=max&interval=1d",
                    raw_payload_hash="range-max-mu",
                ),
                USDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="AAPL",
                    trade_date=date(2026, 3, 1),
                    open_price=200.0,
                    high_price=250.0,
                    low_price=180.0,
                    close_price=240.0,
                    adjusted_close=None,
                    trade_volume=1000,
                    dividend_amount=None,
                    split_coefficient=None,
                    source_url="https://query1.finance.yahoo.com/v8/finance/chart/AAPL?range=max&interval=1d",
                    raw_payload_hash="range-max-aapl",
                ),
                USDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="MU",
                    trade_date=date(2026, 3, 2),
                    open_price=100.0,
                    high_price=110.0,
                    low_price=90.0,
                    close_price=105.0,
                    adjusted_close=None,
                    trade_volume=1000,
                    dividend_amount=None,
                    split_coefficient=None,
                    source_url="https://query1.finance.yahoo.com/v8/finance/chart/MU?range=1y&interval=1d",
                    raw_payload_hash="clean-mu",
                ),
            ],
        )

        result = repair_us_daily_price_quality(self.db, dry_run=True)

        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["total_dirty_count"], 2)
        self.assertEqual(result["candidate_count"], 2)
        self.assertEqual(result["remaining_dirty_count"], 2)
        self.assertEqual(result["deleted_count"], 0)
        self.assertEqual(result["affected_symbols"], ["AAPL", "MU"])
        self.assertEqual(self.db.query(USDailyPrice).count(), 3)

    def test_us_daily_quality_repair_deletes_only_matching_symbol_range_max_rows(self) -> None:
        upsert_us_daily_price_records(
            self.db,
            [
                USDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="MU",
                    trade_date=date(2026, 3, 1),
                    open_price=401.47,
                    high_price=981.0,
                    low_price=311.49,
                    close_price=971.0,
                    adjusted_close=None,
                    trade_volume=3_012_061_200,
                    dividend_amount=None,
                    split_coefficient=None,
                    source_url="https://query1.finance.yahoo.com/v8/finance/chart/MU?range=max&interval=1d",
                    raw_payload_hash="range-max-mu",
                ),
                USDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="AAPL",
                    trade_date=date(2026, 3, 1),
                    open_price=200.0,
                    high_price=250.0,
                    low_price=180.0,
                    close_price=240.0,
                    adjusted_close=None,
                    trade_volume=1000,
                    dividend_amount=None,
                    split_coefficient=None,
                    source_url="https://query1.finance.yahoo.com/v8/finance/chart/AAPL?range=max&interval=1d",
                    raw_payload_hash="range-max-aapl",
                ),
                USDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="MU",
                    trade_date=date(2026, 3, 2),
                    open_price=100.0,
                    high_price=110.0,
                    low_price=90.0,
                    close_price=105.0,
                    adjusted_close=None,
                    trade_volume=1000,
                    dividend_amount=None,
                    split_coefficient=None,
                    source_url="https://query1.finance.yahoo.com/v8/finance/chart/MU?range=1y&interval=1d",
                    raw_payload_hash="clean-mu",
                ),
            ],
        )

        result = repair_us_daily_price_quality(self.db, symbol="MU", dry_run=False)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["deleted_count"], 1)
        self.assertEqual(result["remaining_dirty_count"], 0)
        self.assertEqual(result["affected_symbols"], ["MU"])
        rows = self.db.query(USDailyPrice).order_by(USDailyPrice.symbol.asc()).all()
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            self.db.query(USDailyPrice)
            .filter(USDailyPrice.symbol == "MU")
            .filter(USDailyPrice.source_url.ilike("%range=max%"))
            .count(),
            0,
        )
        self.assertEqual(
            self.db.query(USDailyPrice)
            .filter(USDailyPrice.symbol == "AAPL")
            .filter(USDailyPrice.source_url.ilike("%range=max%"))
            .count(),
            1,
        )

    def test_us_daily_quality_repair_refreshes_affected_symbols_after_delete(self) -> None:
        upsert_us_daily_price_records(
            self.db,
            [
                USDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol=symbol,
                    trade_date=date(2026, 3, 1),
                    open_price=401.47,
                    high_price=981.0,
                    low_price=311.49,
                    close_price=971.0,
                    adjusted_close=None,
                    trade_volume=3_012_061_200,
                    dividend_amount=None,
                    split_coefficient=None,
                    source_url=f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=max&interval=1d",
                    raw_payload_hash=f"range-max-{symbol}",
                )
                for symbol in ["MU", "AAPL"]
            ],
        )

        with patch("app.us_market.service.refresh_us_daily_prices") as refresh_mock:
            refresh_mock.side_effect = lambda **kwargs: {
                "status": "success",
                "provider": kwargs["provider"],
                "symbol": kwargs["symbol"],
                "fetched_count": 1,
                "inserted_count": 1,
                "updated_count": 0,
                "message": "mocked",
            }
            result = repair_us_daily_price_quality(
                self.db,
                dry_run=False,
                refresh=True,
                outputsize="compact",
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["deleted_count"], 2)
        self.assertEqual(result["remaining_dirty_count"], 0)
        self.assertEqual(result["refreshed_symbol_count"], 2)
        self.assertEqual(self.db.query(USDailyPrice).count(), 0)
        self.assertEqual(
            [call.kwargs["symbol"] for call in refresh_mock.call_args_list],
            ["AAPL", "MU"],
        )
        for call in refresh_mock.call_args_list:
            self.assertEqual(call.kwargs["provider"], "yahoo_chart")
            self.assertEqual(call.kwargs["outputsize"], "compact")

    @patch("app.us_market.service.fetch_yahoo_chart_payload")
    def test_us_yahoo_full_refresh_uses_ten_year_range_for_stocks(self, mock_fetch) -> None:
        mock_fetch.return_value = (
            {"chart": {"result": [{"timestamp": [], "indicators": {"quote": [{}]}}]}},
            "https://example.test/chart/MU",
        )

        result = refresh_us_daily_prices_from_yahoo_chart(
            self.db,
            symbol="MU",
            outputsize="full",
        )

        self.assertEqual(result["symbol"], "MU")
        self.assertEqual(result["fetched_count"], 0)
        self.assertEqual(mock_fetch.call_args.kwargs["range_value"], "10y")

    @patch("app.us_market.service.fetch_yahoo_chart_payload")
    def test_us_yahoo_full_refresh_uses_ten_year_range_for_indices(self, mock_fetch) -> None:
        mock_fetch.return_value = (
            {"chart": {"result": [{"timestamp": [], "indicators": {"quote": [{}]}}]}},
            "https://example.test/chart/%5EIXIC",
        )

        result = refresh_us_daily_prices_from_yahoo_chart(
            self.db,
            symbol="^IXIC",
            outputsize="full",
        )

        self.assertEqual(result["symbol"], "^IXIC")
        self.assertEqual(result["fetched_count"], 0)
        self.assertEqual(mock_fetch.call_args.kwargs["range_value"], "10y")

    def test_us_monthly_ohlc_refreshes_full_history_when_local_points_are_short(self) -> None:
        records = [
            USDailyPriceRecord(
                provider="yahoo_chart",
                symbol="MU",
                trade_date=date(year, month, 1),
                open_price=100.0,
                high_price=110.0,
                low_price=90.0,
                close_price=105.0,
                adjusted_close=None,
                trade_volume=1000,
                dividend_amount=None,
                split_coefficient=None,
                source_url=None,
                raw_payload_hash=f"hash-{year}-{month}",
            )
            for year, month in [
                (2025, 5),
                (2025, 6),
                (2025, 7),
                (2025, 8),
                (2025, 9),
                (2025, 10),
                (2025, 11),
                (2025, 12),
                (2026, 1),
                (2026, 2),
                (2026, 3),
                (2026, 4),
                (2026, 5),
            ]
        ]
        upsert_us_daily_price_records(self.db, records)

        with patch("app.us_market.service.refresh_us_daily_prices") as refresh_mock:
            refresh_mock.return_value = {
                "status": "success",
                "provider": "yahoo_chart",
                "symbol": "MU",
                "fetched_count": 0,
                "inserted_count": 0,
                "updated_count": 0,
                "message": "mocked",
            }
            chart = list_us_ohlc_chart_data(
                self.db,
                symbol="MU",
                timeframe="monthly",
                bars=72,
                ensure_history=True,
                outputsize="compact",
                to_date=date(2026, 5, 31),
            )

        refresh_mock.assert_called_once_with(
            db=self.db,
            symbol="MU",
            outputsize="full",
            adjusted=False,
            provider="auto",
        )
        self.assertEqual(chart["point_count"], 13)
        self.assertEqual(chart["backfill"]["message"], "mocked")

    def test_us_ohlc_refresh_uses_requested_provider(self) -> None:
        with patch("app.us_market.service.refresh_us_daily_prices") as refresh_mock:
            refresh_mock.return_value = {
                "status": "success",
                "provider": "yahoo_chart",
                "symbol": "^GSPC",
                "fetched_count": 0,
                "inserted_count": 0,
                "updated_count": 0,
                "message": "mocked",
            }
            chart = list_us_ohlc_chart_data(
                self.db,
                symbol="^GSPC",
                timeframe="daily",
                bars=5,
                ensure_history=True,
                outputsize="compact",
                provider="yahoo_chart",
                to_date=date(2026, 5, 31),
            )

        refresh_mock.assert_called_once_with(
            db=self.db,
            symbol="^GSPC",
            outputsize="compact",
            adjusted=False,
            provider="yahoo_chart",
        )
        self.assertEqual(chart["symbol"], "^GSPC")
        self.assertEqual(chart["backfill"]["provider"], "yahoo_chart")

    def test_us_monthly_ohlc_skips_refresh_when_local_points_are_enough(self) -> None:
        records = [
            USDailyPriceRecord(
                provider="yahoo_chart",
                symbol="MU",
                trade_date=date(2025, month, 1),
                open_price=100.0,
                high_price=110.0,
                low_price=90.0,
                close_price=105.0,
                adjusted_close=None,
                trade_volume=1000,
                dividend_amount=None,
                split_coefficient=None,
                source_url=None,
                raw_payload_hash=f"hash-2025-{month}",
            )
            for month in range(1, 7)
        ]
        upsert_us_daily_price_records(self.db, records)

        with patch("app.us_market.service.refresh_us_daily_prices") as refresh_mock:
            chart = list_us_ohlc_chart_data(
                self.db,
                symbol="MU",
                timeframe="monthly",
                bars=3,
                ensure_history=True,
                outputsize="compact",
                to_date=date(2025, 6, 30),
            )

        refresh_mock.assert_not_called()
        self.assertEqual(chart["point_count"], 3)
        self.assertIsNone(chart["backfill"])


if __name__ == "__main__":
    unittest.main()
