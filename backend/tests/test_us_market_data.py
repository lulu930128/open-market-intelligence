from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai import agentic_tools
from app.us_market import service as us_market_service
from app.db.models import (
    Base,
    MacroSeriesObservation,
    MarketDailyPrice,
    StockMaster,
    SourceHealthSnapshot,
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
from app.us_market.schemas import (
    USWatchlistGroupCreate,
    USWatchlistItemCreate,
    USWatchlistRankingItemRead,
    USSourceHealthRead,
)
from app.us_market.price_store import list_us_daily_prices
from app.us_market.service import (
    USStockNotFoundError,
    build_us_source_health,
    create_us_watchlist_group,
    create_us_watchlist_item,
    get_us_sec_fundamental_summary,
    get_us_watchlist_ranking,
    get_us_watchlist_technical_radar,
    get_us_intraday_trend,
    list_us_ohlc_chart_data,
    list_us_watchlist_items,
    list_us_watchlist_symbols,
    refresh_us_daily_prices,
    refresh_us_daily_prices_from_yahoo_chart,
    refresh_us_sec_companyfacts,
    refresh_us_watchlist_resources,
    repair_us_daily_price_quality,
    search_us_stocks,
    snapshot_us_source_health,
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
from us_daily_test_support import upsert_canonical_us_daily_price_records
from app.us_market.trading_calendar import (
    expected_us_daily_price_date,
    is_us_daily_price_finalized,
    us_daily_price_finalization_time,
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


YAHOO_CHART_DISCOVERY_SAMPLE = {
    "chart": {
        "result": [
            {
                "meta": {
                    "symbol": "SPCX",
                    "exchangeName": "NMS",
                    "instrumentType": "EQUITY",
                    "longName": "SpaceX Corp.",
                },
                "timestamp": [],
                "indicators": {"quote": [{}]},
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


def _ny_timestamp(year: int, month: int, day: int, hour: int, minute: int) -> int:
    return int(
        datetime(
            year,
            month,
            day,
            hour,
            minute,
            tzinfo=ZoneInfo("America/New_York"),
        ).timestamp()
    )


YAHOO_CHART_INTRADAY_EXTENDED_SAMPLE = {
    "chart": {
        "result": [
            {
                "meta": {
                    "symbol": "MU",
                    "gmtoffset": -14400,
                    "chartPreviousClose": 90.0,
                },
                "timestamp": [
                    _ny_timestamp(2026, 6, 2, 8, 0),
                    _ny_timestamp(2026, 6, 2, 9, 30),
                    _ny_timestamp(2026, 6, 2, 16, 30),
                ],
                "indicators": {
                    "quote": [
                        {
                            "open": [90.5, 91.0, 92.1],
                            "high": [90.8, 91.5, 92.4],
                            "low": [90.1, 90.8, 91.8],
                            "close": [90.6, 91.25, 92.0],
                            "volume": [300, 1000, 450],
                        }
                    ],
                },
            }
        ],
        "error": None,
    }
}


YAHOO_CHART_INTRADAY_PREMARKET_SAMPLE = {
    "chart": {
        "result": [
            {
                "meta": {
                    "symbol": "IBM",
                    "gmtoffset": -14400,
                    "chartPreviousClose": 90.0,
                },
                "timestamp": [
                    _ny_timestamp(2026, 6, 2, 8, 0),
                ],
                "indicators": {
                    "quote": [
                        {
                            "open": [90.5],
                            "high": [90.8],
                            "low": [90.1],
                            "close": [90.6],
                            "volume": [300],
                        }
                    ],
                },
            }
        ],
        "error": None,
    }
}


YAHOO_CHART_INTRADAY_PREVIOUS_REGULAR_SAMPLE = {
    "chart": {
        "result": [
            {
                "meta": {
                    "symbol": "IBM",
                    "gmtoffset": -14400,
                    "chartPreviousClose": 87.0,
                },
                "timestamp": [
                    _ny_timestamp(2026, 6, 1, 15, 59),
                    _ny_timestamp(2026, 6, 1, 16, 0),
                ],
                "indicators": {
                    "quote": [
                        {
                            "open": [88.2, 88.4],
                            "high": [88.6, 88.7],
                            "low": [88.1, 88.3],
                            "close": [88.4, 88.5],
                            "volume": [900, 1200],
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


SEC_SUBMISSIONS_MU_SAMPLE = {
    "cik": "723125",
    "filings": {
        "recent": {
            "accessionNumber": ["0000723125-25-000001"],
            "filingDate": ["2025-10-17"],
            "reportDate": ["2025-08-28"],
            "acceptanceDateTime": ["20251017160000"],
            "form": ["10-K"],
            "primaryDocument": ["mu-20250828.htm"],
            "isXBRL": [1],
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
    def setUp(self) -> None:
        us_market_service._US_INTRADAY_CACHE.clear()
        us_market_service._US_INTRADAY_LAST_GOOD.clear()

    def test_us_intraday_read_cache_survives_five_second_poll_cycles(self) -> None:
        key = (1, "TSM", "regular", "1m", "regular")
        payload = {
            "current_observation": {
                "observed_at": datetime.now(timezone.utc).isoformat(),
            },
            "points": [{"time": datetime.now(timezone.utc).isoformat()}],
        }
        with patch("app.us_market.service.time.monotonic", side_effect=(100.0, 115.0)):
            us_market_service._set_us_intraday_cache(key, payload)
            cached = us_market_service._get_us_intraday_cache(key)

        self.assertEqual(cached, payload)

    def test_us_intraday_read_cache_never_outlives_current_evidence_boundary(self) -> None:
        key = (1, "TSM", "regular", "1m", "regular")
        payload = {
            "current_observation": {"observed_at": "2020-01-01T00:00:00+00:00"},
            "current_source_status": {"freshness_status": "current"},
            "points": [{"time": "2020-01-01T00:00:00+00:00"}],
        }
        with patch("app.us_market.service.time.monotonic", side_effect=(100.0, 101.0)):
            us_market_service._set_us_intraday_cache(key, payload)
            cached = us_market_service._get_us_intraday_cache(key)

        self.assertIsNone(cached)

    def test_normalize_us_symbol_accepts_ui_labels(self) -> None:
        self.assertEqual(normalize_us_symbol("AAPL / Apple"), "AAPL")
        self.assertEqual(normalize_us_symbol("nasdaq:mu"), "MU")
        self.assertEqual(normalize_us_symbol("brk.b - Berkshire"), "BRK.B")
        self.assertEqual(normalize_us_symbol("SOX"), "^SOX")
        self.assertEqual(normalize_us_symbol("SPX"), "^GSPC")
        self.assertEqual(normalize_us_symbol("DJI"), "^DJI")
        self.assertEqual(normalize_us_symbol("^SOX"), "^SOX")

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
        self.assertEqual(trend["session_scope"], "regular")
        self.assertEqual(trend["session_phase"], "regular")
        self.assertFalse(trend["has_extended_hours"])
        self.assertEqual(trend["regular_point_count"], 2)
        self.assertEqual(trend["extended_point_count"], 0)
        self.assertEqual(trend["points"][0]["time"], "2026-06-02T09:30:00-04:00")
        self.assertEqual(trend["points"][0]["session"], "regular")
        self.assertEqual(trend["points"][0]["price"], 91.25)
        self.assertEqual(trend["points"][1]["volume"], 1500)

    def test_parse_yahoo_intraday_prices_can_return_extended_hours(self) -> None:
        all_trend = parse_yahoo_intraday_prices(
            YAHOO_CHART_INTRADAY_EXTENDED_SAMPLE,
            symbol="mu",
            source_url="https://example.test/chart/MU?includePrePost=true",
            session_scope="all",
        )
        extended_trend = parse_yahoo_intraday_prices(
            YAHOO_CHART_INTRADAY_EXTENDED_SAMPLE,
            symbol="mu",
            source_url="https://example.test/chart/MU?includePrePost=true",
            session_scope="extended",
        )

        self.assertEqual(all_trend["point_count"], 3)
        self.assertEqual(all_trend["regular_point_count"], 1)
        self.assertEqual(all_trend["extended_point_count"], 2)
        self.assertTrue(all_trend["has_extended_hours"])
        self.assertEqual(all_trend["regular_session_close"], 91.25)
        self.assertEqual(
            all_trend["regular_session_close_time"],
            "2026-06-02T09:30:00-04:00",
        )
        self.assertEqual(
            [point["session"] for point in all_trend["points"]],
            ["pre_market", "regular", "after_hours"],
        )
        self.assertEqual(extended_trend["point_count"], 2)
        self.assertEqual(
            [point["session"] for point in extended_trend["points"]],
            ["pre_market", "after_hours"],
        )

    def test_parse_yahoo_intraday_zero_filled_extended_volume_is_unknown(self) -> None:
        payload = deepcopy(YAHOO_CHART_INTRADAY_EXTENDED_SAMPLE)
        payload["chart"]["result"][0]["indicators"]["quote"][0]["volume"] = [
            0,
            1000,
            0,
        ]

        trend = parse_yahoo_intraday_prices(
            payload,
            symbol="mu",
            source_url="https://example.test/chart/MU?includePrePost=true",
            session_scope="all",
        )

        self.assertIsNone(trend["points"][0]["volume"])
        self.assertEqual(trend["points"][0]["volume_status"], "provider_unavailable")
        self.assertEqual(trend["points"][1]["volume"], 1000)
        self.assertIsNone(trend["points"][2]["volume"])
        self.assertEqual(trend["volume_status"], "partial")
        self.assertEqual(trend["volume_semantics"], "partial_interval_shares")
        self.assertEqual(trend["volume_coverage"]["extended_unavailable_point_count"], 2)
        self.assertTrue(any("zero-filled" in warning for warning in trend["warnings"]))

    @patch("app.us_market.service.fetch_yahoo_chart_payload")
    def test_get_us_intraday_trend_without_db_is_truthful_cache_miss(self, mock_fetch) -> None:
        mock_fetch.return_value = (
            YAHOO_CHART_INTRADAY_SAMPLE,
            "https://example.test/chart/MU",
        )

        trend = get_us_intraday_trend(symbol="mu")

        mock_fetch.assert_not_called()
        self.assertEqual(trend["stock_id"], "MU")
        self.assertEqual(trend["point_count"], 0)
        self.assertEqual(trend["source_status"]["freshness_status"], "missing")
        self.assertFalse(trend["source_status"]["has_usable_data"])

    @patch("app.us_market.service.fetch_yahoo_chart_payload")
    def test_get_us_intraday_trend_can_read_with_db_without_persisting_history(
        self,
        mock_fetch,
    ) -> None:
        mock_fetch.return_value = (
            YAHOO_CHART_INTRADAY_SAMPLE,
            "https://example.test/chart/MU",
        )
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        db = Session(engine)
        try:
            db.add(
                USStockMaster(
                    symbol="MU",
                    exchange="NASDAQ",
                    asset_type="stock",
                    is_active=True,
                )
            )
            db.commit()
            with patch.object(
                us_market_service,
                "_persist_us_intraday_history",
            ) as persist_history:
                trend = get_us_intraday_trend(
                    symbol="mu",
                    db=db,
                    persist_history=False,
                )
        finally:
            db.close()
            engine.dispose()

        persist_history.assert_not_called()
        mock_fetch.assert_not_called()
        self.assertEqual(trend["point_count"], 0)
        self.assertIsNone(trend["volume_pace"])

    def test_us_intraday_source_status_detects_stopped_live_data(self) -> None:
        payload = {
            "points": [
                {
                    "time": "2026-07-24T10:29:42-04:00",
                    "session": "regular",
                    "price": 406.75,
                }
            ]
        }

        status = us_market_service._build_us_intraday_source_status(
            payload,
            session_scope="regular",
            now=datetime(2026, 7, 24, 15, 6, tzinfo=timezone.utc),
        )

        self.assertEqual(status["status"], "degraded")
        self.assertEqual(status["freshness_status"], "stale")
        self.assertTrue(status["is_live_window"])
        self.assertEqual(status["lag_seconds"], 2178.0)

    def test_us_intraday_source_status_accepts_current_live_data(self) -> None:
        payload = {
            "points": [
                {
                    "time": "2026-07-24T11:05:00-04:00",
                    "session": "regular",
                    "price": 407.0,
                }
            ]
        }

        status = us_market_service._build_us_intraday_source_status(
            payload,
            session_scope="regular",
            now=datetime(2026, 7, 24, 15, 6, tzinfo=timezone.utc),
        )

        self.assertEqual(status["status"], "ok")
        self.assertEqual(status["freshness_status"], "current")
        self.assertEqual(status["lag_seconds"], 60.0)

    def test_us_intraday_last_good_cache_is_bounded(self) -> None:
        with patch.object(
            us_market_service,
            "US_INTRADAY_LAST_GOOD_MAX_ENTRIES",
            2,
        ):
            for index, symbol in enumerate(("AAPL", "MSFT", "TSM"), start=1):
                us_market_service._remember_us_intraday_last_good(
                    f"US:{symbol}:regular",
                    {
                        "points": [
                            {
                                "time": f"2026-07-24T10:0{index}:00-04:00",
                                "price": 100 + index,
                            }
                        ]
                    },
                )

        self.assertEqual(
            list(us_market_service._US_INTRADAY_LAST_GOOD),
            ["US:MSFT:regular", "US:TSM:regular"],
        )

    @patch("app.us_market.service.fetch_yahoo_chart_payload")
    def test_us_intraday_read_does_not_use_provider_or_legacy_last_good_memory(
        self,
        mock_fetch,
    ) -> None:
        mock_fetch.return_value = (
            YAHOO_CHART_INTRADAY_SAMPLE,
            "https://example.test/chart/MU",
        )
        initial = get_us_intraday_trend(symbol="mu")
        us_market_service._US_INTRADAY_CACHE.clear()
        mock_fetch.side_effect = RuntimeError("upstream unavailable")

        fallback = get_us_intraday_trend(symbol="mu")

        mock_fetch.assert_not_called()
        self.assertEqual(fallback["points"], initial["points"])
        self.assertEqual(fallback["source_status"]["status"], "unavailable")
        self.assertEqual(fallback["source_status"]["freshness_status"], "missing")
        self.assertIn(
            "US_INTRADAY_CANONICAL_CACHE_MISSING",
            fallback["source_status"]["limitations"],
        )
        self.assertEqual(fallback["source_status"]["freshness_status"], "missing")
        self.assertFalse(fallback["source_status"]["is_fallback"])
        self.assertFalse(fallback["source_status"]["has_usable_data"])

    @patch("app.us_market.service.fetch_yahoo_chart_payload")
    def test_get_us_intraday_trend_preserves_all_scope_on_cache_miss(self, mock_fetch) -> None:
        mock_fetch.return_value = (
            YAHOO_CHART_INTRADAY_EXTENDED_SAMPLE,
            "https://example.test/chart/MU?includePrePost=true",
        )

        trend = get_us_intraday_trend(symbol="mu", session_scope="all")

        mock_fetch.assert_not_called()
        self.assertEqual(trend["session_scope"], "all")
        self.assertEqual(trend["point_count"], 0)

    @patch("app.us_market.service.fetch_yahoo_chart_payload")
    def test_us_stock_intraday_read_does_not_bootstrap_or_derive_volume_pace(
        self,
        mock_fetch,
    ) -> None:
        mock_fetch.return_value = (
            YAHOO_CHART_INTRADAY_SAMPLE,
            "https://example.test/chart/MU?range=5d&interval=1m",
        )

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        db = Session(engine)
        try:
            db.add(
                USStockMaster(
                    symbol="MU",
                    exchange="NASDAQ",
                    asset_type="stock",
                    is_active=True,
                )
            )
            db.commit()
            trend = get_us_intraday_trend(symbol="mu", db=db)
        finally:
            db.close()
            engine.dispose()

        mock_fetch.assert_not_called()
        self.assertEqual(trend["point_count"], 0)
        self.assertIsNone(trend["volume_pace"])

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
        us_market_service._US_INTRADAY_CACHE.clear()
        us_market_service._US_INTRADAY_LAST_GOOD.clear()
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _add_market_identity(self, symbol: str, exchange: str = "NASDAQ") -> None:
        self.db.add(
            USStockMaster(
                symbol=symbol,
                exchange=exchange,
                asset_type="stock",
                is_active=True,
            )
        )
        self.db.commit()

    def test_us_daily_prices_read_legacy_index_alias_rows(self) -> None:
        self.db.add(
            USDailyPrice(
                provider="yahoo_chart",
                symbol="SOX",
                trade_date=date(2026, 7, 14),
                close_price=102.0,
                raw_payload_hash="legacy-sox",
            )
        )
        self.db.commit()

        rows = list_us_daily_prices(
            self.db,
            symbol="^SOX",
            provider="yahoo_chart",
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].symbol, "SOX")

    @patch("app.ai.agentic_tools.us_market_service.get_us_intraday_trend")
    def test_read_us_stock_context_fetches_intraday_when_requested(self, mock_intraday) -> None:
        self._add_market_identity("MU")
        upsert_us_daily_price_records(
            self.db,
            [
                USDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="MU",
                    trade_date=date(2026, 6, 1),
                    open_price=89.0,
                    high_price=91.0,
                    low_price=88.0,
                    close_price=90.0,
                    adjusted_close=None,
                    trade_volume=1000,
                    dividend_amount=None,
                    split_coefficient=None,
                    source_url="https://example.test/chart/MU?range=1y&interval=1d",
                    raw_payload_hash="daily-mu",
                )
            ],
        )
        mock_intraday.return_value = {
            "stock_id": "MU",
            "symbol": "MU",
            "source": "yahoo_finance_chart",
            "session_scope": "all",
            "session_phase": "regular",
            "has_extended_hours": True,
            "previous_close": 90.0,
            "point_count": 2,
            "points": [
                {
                    "time": "2026-06-02T09:30:00-04:00",
                    "session": "regular",
                    "price": 91.25,
                    "volume": 1000,
                },
                {
                    "time": "2026-06-02T09:31:00-04:00",
                    "session": "regular",
                    "price": 91.35,
                    "volume": 1500,
                },
            ],
            "source_url": "https://example.test/chart/MU?range=1d&interval=1m",
            "_resolved_market_data": {
                "quote_snapshot": {
                    "schema_version": "omi.market.quote.snapshot.v1",
                    "selected_provider": "yahoo_chart",
                },
                "intraday_bars": {
                    "schema_version": "omi.market.bars.v1",
                    "returned_bar_count": 2,
                },
            },
        }

        with patch(
            "app.ai.market_context.us_context.build_us_calendar_status",
            return_value={
                "checked_at": "2026-06-06T12:00:00-04:00",
                "date": "2026-06-06",
                "is_trading_day": False,
                "phase": "closed",
                "previous_trading_day": "2026-06-05",
            },
        ):
            context = agentic_tools.read_us_stock_context(
                db=self.db,
                symbol="mu",
                market_data_params={
                    "include_intraday": True,
                    "payload_level": "summary",
                    "intraday_limit": 1,
                    "session_scope": "all",
                },
            )

        mock_intraday.assert_called_once_with(
            symbol="MU",
            session_scope="all",
            interval="1m",
            db=self.db,
            persist_history=False,
        )
        compact = context["data"]["compact"]
        self.assertEqual(context["as_of"], "2026-06-02T09:31:00-04:00")
        self.assertEqual(compact["quote"]["price"], 91.35)
        self.assertTrue(compact["quote"]["source_is_intraday"])
        self.assertFalse(compact["quote"]["is_realtime"])
        self.assertFalse(compact["quote"]["is_latest_session_quote"])
        self.assertEqual(compact["quote"]["market_status"], "closed")
        self.assertEqual(compact["slots"]["intraday"]["status"], "ready")
        self.assertTrue(compact["resources"]["include_intraday"])
        self.assertEqual(
            compact["intraday_bars"]["series"]["1m"]["returned_point_count"],
            1,
        )
        self.assertNotIn("us_intraday_trend", context["missing"])
        self.assertEqual(
            context["data"]["resolved_market_data"]["quote_snapshot"][
                "schema_version"
            ],
            "omi.market.us_truth_quote_compat.v1",
        )
        self.assertNotIn("_resolved_market_data", context["summary"]["intraday"])

    @patch("app.ai.agentic_tools.us_market_service.get_us_intraday_trend")
    def test_read_us_stock_context_selects_exact_historical_close(
        self,
        mock_intraday,
    ) -> None:
        self._add_market_identity("AAPL")
        upsert_canonical_us_daily_price_records(
            self.db,
            [
                USDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="AAPL",
                    trade_date=date(2026, 7, 20),
                    open_price=320.0,
                    high_price=330.0,
                    low_price=319.0,
                    close_price=326.59,
                    adjusted_close=None,
                    trade_volume=10_000,
                    dividend_amount=None,
                    split_coefficient=None,
                    source_url="https://example.test/chart/AAPL",
                    raw_payload_hash="aapl-20260720",
                ),
                USDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="AAPL",
                    trade_date=date(2026, 7, 24),
                    open_price=328.0,
                    high_price=332.0,
                    low_price=327.0,
                    close_price=329.0,
                    adjusted_close=None,
                    trade_volume=12_000,
                    dividend_amount=None,
                    split_coefficient=None,
                    source_url="https://example.test/chart/AAPL",
                    raw_payload_hash="aapl-20260724",
                ),
            ],
        )

        with patch(
            "app.ai.market_context.us_context.build_us_calendar_status",
            return_value={
                "checked_at": "2026-07-26T10:00:00-04:00",
                "phase": "closed",
                "previous_trading_day": "2026-07-24",
            },
        ):
            context = agentic_tools.read_us_stock_context(
                db=self.db,
                symbol="AAPL",
                market_data_params={
                    "trade_date": "2026-07-20",
                    "include_intraday": True,
                    "session_scope": "all",
                },
            )

        mock_intraday.assert_not_called()
        quote = context["data"]["compact"]["quote"]
        self.assertEqual(context["as_of"], "2026-07-20T16:00:00-04:00")
        self.assertEqual(quote["status"], "historical")
        self.assertEqual(quote["price"], 326.59)
        self.assertEqual(quote["currency"], "USD")
        self.assertEqual(quote["volume_unit"], "shares")
        self.assertEqual(quote["volume_semantics"], "daily_shares")
        self.assertEqual(quote["trade_date"], "2026-07-20")
        self.assertEqual(
            quote["quote_semantics"],
            "historical_regular_session_close",
        )
        self.assertTrue(quote["is_historical"])
        self.assertFalse(quote["is_realtime"])
        self.assertFalse(quote["is_latest_session_quote"])
        self.assertEqual(quote["timezone"], "America/New_York")
        self.assertEqual(
            [row["trade_date"] for row in context["data"]["daily_prices"]],
            ["2026-07-20"],
        )
        self.assertFalse(context["data"]["compact"]["resources"]["include_intraday"])

    def test_read_us_stock_context_does_not_fallback_when_trade_date_is_missing(
        self,
    ) -> None:
        self._add_market_identity("AAPL")
        upsert_us_daily_price_records(
            self.db,
            [
                USDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="AAPL",
                    trade_date=date(2026, 7, 24),
                    open_price=328.0,
                    high_price=332.0,
                    low_price=327.0,
                    close_price=329.0,
                    adjusted_close=None,
                    trade_volume=12_000,
                    dividend_amount=None,
                    split_coefficient=None,
                    source_url="https://example.test/chart/AAPL",
                    raw_payload_hash="aapl-latest-only",
                )
            ],
        )

        context = agentic_tools.read_us_stock_context(
            db=self.db,
            symbol="AAPL",
            market_data_params={"trade_date": "2026-07-19"},
        )

        quote = context["data"]["compact"]["quote"]
        self.assertEqual(quote["status"], "missing")
        self.assertIsNone(quote["price"])
        self.assertEqual(quote["requested_trade_date"], "2026-07-19")
        self.assertEqual(context["data"]["daily_prices"], [])
        self.assertIn(
            "us_daily_price_requested_trade_date",
            context["missing"],
        )
        self.assertTrue(
            any(
                "did not fall back to another date" in warning
                for warning in context["warnings"]
            )
        )

    def _set_daily_fetched_at(
        self,
        *,
        provider: str,
        symbol: str,
        trade_date: date,
        fetched_at: datetime,
    ) -> None:
        row = (
            self.db.query(USDailyPrice)
            .filter(USDailyPrice.provider == provider)
            .filter(USDailyPrice.symbol == symbol)
            .filter(USDailyPrice.trade_date == trade_date)
            .one()
        )
        row.fetched_at = fetched_at
        self.db.commit()

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

    @patch("app.us_market.service.fetch_sec_submissions_payload")
    @patch("app.us_market.service.fetch_sec_companyfacts_payload")
    @patch("app.us_market.service.fetch_sec_company_tickers_exchange_payload")
    def test_sec_fact_refresh_resolves_missing_cik_from_sec_mapping(
        self,
        mock_fetch_sec_tickers,
        mock_fetch_companyfacts,
        mock_fetch_submissions,
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
        mock_fetch_submissions.return_value = (
            SEC_SUBMISSIONS_MU_SAMPLE,
            "https://data.sec.gov/submissions/CIK0000723125.json",
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
        self.assertEqual(result["latest_remote_accession_number"], "0000723125-25-000001")
        self.assertEqual(result["freshness"]["status"], "current")
        self.assertEqual(self.db.query(USSecCompanyFact).count(), 1)
        mock_fetch_sec_tickers.assert_called_once()
        mock_fetch_companyfacts.assert_called_once()
        mock_fetch_submissions.assert_called_once()

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

    def test_us_source_health_summarizes_provider_freshness(self) -> None:
        self.db.add(
            USStockMaster(
                symbol="IBM",
                security_name="International Business Machines Corporation",
                exchange="NYSE",
                asset_type="stock",
                listing_source="nasdaq_trader",
                cik="0000051143",
                sec_company_name="International Business Machines Corp",
                is_active=True,
            )
        )
        self.db.commit()
        upsert_us_daily_price_records(
            self.db,
            [
                USDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="IBM",
                    trade_date=date(2026, 5, 29),
                    open_price=100.0,
                    high_price=105.0,
                    low_price=99.0,
                    close_price=104.5,
                    adjusted_close=None,
                    trade_volume=1234567,
                    dividend_amount=None,
                    split_coefficient=None,
                    source_url="https://query1.finance.yahoo.com/v8/finance/chart/IBM",
                    raw_payload_hash="ibm-yahoo",
                )
            ],
        )
        upsert_us_company_profile_records(
            self.db,
            [
                parse_alphavantage_company_profile(
                    ALPHAVANTAGE_OVERVIEW_SAMPLE,
                    symbol="IBM",
                    source_url="https://www.alphavantage.co/query?function=OVERVIEW&symbol=IBM&apikey=REDACTED",
                )
            ],
        )

        health = build_us_source_health(
            self.db,
            symbol="ibm",
            expected_daily_price_date=date(2026, 6, 2),
        )
        entries = {
            (entry["resource"], entry["provider"]): entry
            for entry in health["entries"]
        }

        self.assertEqual(health["filters"]["symbol"], "IBM")
        self.assertEqual(entries[("daily_price", "yahoo_chart")]["status"], "stale")
        self.assertEqual(entries[("daily_price", "yahoo_chart")]["freshness_lag_days"], 4)
        self.assertNotIn(("daily_price", "alphavantage"), entries)
        self.assertEqual(entries[("profile", "alphavantage")]["status"], "available")
        self.assertEqual(entries[("sec_facts", "sec_edgar")]["status"], "empty")
        self.assertEqual(health["summary"]["stale_count"], 1)
        self.assertGreaterEqual(health["summary"]["empty_count"], 1)
        self.assertEqual(self.db.query(SourceHealthSnapshot).count(), 0)

        realtime = {
            (entry["resource"], entry["provider"]): entry
            for entry in health["entries"]
            if entry["resource"] in {"quote_snapshot", "intraday_bars"}
        }
        self.assertEqual(
            realtime[("quote_snapshot", "yahoo_chart")]["freshness_basis"],
            "fetched_time",
        )
        USSourceHealthRead.model_validate(health)
        self.assertEqual(
            realtime[("intraday_bars", "yahoo_chart")]["freshness_basis"],
            "event_time",
        )

        snapshot_us_source_health(
            self.db,
            symbol="IBM",
            expected_daily_price_date=date(2026, 6, 2),
        )
        self.assertGreater(self.db.query(SourceHealthSnapshot).count(), 0)

    def test_us_source_health_marks_preclose_daily_row_as_partial(self) -> None:
        upsert_canonical_us_daily_price_records(
            self.db,
            [
                USDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="IBM",
                    trade_date=date(2026, 6, 1),
                    open_price=87.0,
                    high_price=89.0,
                    low_price=86.5,
                    close_price=88.5,
                    adjusted_close=None,
                    trade_volume=1200,
                    dividend_amount=None,
                    split_coefficient=None,
                    source_url=None,
                    raw_payload_hash="ibm-finalized",
                )
            ],
        )
        self.db.add(
            USDailyPrice(
                provider="yahoo_chart",
                symbol="IBM",
                trade_date=date(2026, 6, 2),
                close_price=90.6,
                trade_volume=300,
                fetched_at=datetime(2026, 6, 2, 14, 0, tzinfo=timezone.utc),
                raw_payload_hash="ibm-preclose",
            )
        )
        self.db.commit()

        health = build_us_source_health(
            self.db,
            symbol="IBM",
            expected_daily_price_date=date(2026, 6, 2),
        )
        yahoo_entry = next(
            entry
            for entry in health["entries"]
            if entry["resource"] == "daily_price"
            and entry["provider"] == "yahoo_chart"
        )

        self.assertEqual(yahoo_entry["status"], "partial")
        self.assertFalse(yahoo_entry["ok"])
        self.assertFalse(yahoo_entry["latest_row_finalized"])
        self.assertEqual(
            yahoo_entry["latest_finalized_data_date"],
            "2026-06-01",
        )
        self.assertIn("excluded from completed daily data", yahoo_entry["reason"])
        self.assertEqual(health["summary"]["partial_count"], 1)

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

    @patch("app.us_market.service.fetch_yahoo_chart_payload")
    def test_create_us_watchlist_item_discovers_missing_stock_from_yahoo(self, mock_fetch) -> None:
        mock_fetch.return_value = (
            YAHOO_CHART_DISCOVERY_SAMPLE,
            "https://query1.finance.yahoo.com/v8/finance/chart/SPCX?range=5d&interval=1d",
        )
        group = create_us_watchlist_group(
            self.db,
            USWatchlistGroupCreate(group_name="New Listings"),
        )

        item = create_us_watchlist_item(
            self.db,
            USWatchlistItemCreate(group_id=group.id, symbol="spcx"),
        )
        stock = self.db.query(USStockMaster).filter(USStockMaster.symbol == "SPCX").one()

        self.assertEqual(item["symbol"], "SPCX")
        self.assertEqual(item["security_name"], "SpaceX Corp.")
        self.assertEqual(stock.security_name, "SpaceX Corp.")
        self.assertEqual(stock.exchange, "NASDAQ")
        self.assertEqual(stock.asset_type, "stock")
        self.assertEqual(stock.listing_source, "discovered_yahoo_chart")
        self.assertTrue(stock.is_active)
        self.assertEqual(self.db.query(USWatchlistItem).count(), 1)
        self.assertEqual(mock_fetch.call_args.kwargs["symbol"], "SPCX")
        self.assertEqual(mock_fetch.call_args.kwargs["range_value"], "5d")
        self.assertEqual(mock_fetch.call_args.kwargs["interval"], "1d")

    @patch("app.us_market.service.fetch_yahoo_chart_payload")
    def test_create_us_watchlist_item_does_not_write_unknown_symbol(self, mock_fetch) -> None:
        mock_fetch.side_effect = USMarketDataFetchError("No data found for this symbol.")
        group = create_us_watchlist_group(
            self.db,
            USWatchlistGroupCreate(group_name="New Listings"),
        )

        with self.assertRaisesRegex(USStockNotFoundError, "Yahoo discovery failed"):
            create_us_watchlist_item(
                self.db,
                USWatchlistItemCreate(group_id=group.id, symbol="notreal"),
            )

        self.assertEqual(self.db.query(USStockMaster).count(), 0)
        self.assertEqual(self.db.query(USWatchlistItem).count(), 0)

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
        upsert_canonical_us_daily_price_records(
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

        with patch(
            "app.us_market.service.expected_us_daily_price_date",
            return_value=date(2026, 5, 29),
        ):
            ranking = get_us_watchlist_ranking(
                self.db,
                group_id=group.id,
                rank_by="change_pct",
                sort_order="desc",
            )

        self.assertEqual(ranking["requested_symbol_count"], 2)
        self.assertEqual(ranking["ranked_count"], 2)
        self.assertEqual(ranking["coverage_ratio"], 1.0)
        self.assertFalse(ranking["is_live"])
        self.assertTrue(ranking["is_full"])
        self.assertEqual(
            ranking["ranking_semantics"],
            "resolved_completed_daily_bars",
        )
        self.assertEqual(ranking["results"][0]["symbol"], "AAPL")
        self.assertEqual(ranking["results"][0]["change_pct"], 10.0)
        self.assertEqual(ranking["results"][0]["selected_provider"], "yahoo_chart")
        self.assertEqual(
            ranking["results"][0]["selected_source"],
            "yahoo.chart.1d",
        )
        self.assertEqual(ranking["results"][0]["selected_session"], "closed")
        self.assertEqual(ranking["results"][0]["price_basis"], "raw")
        self.assertEqual(ranking["results"][1]["symbol"], "IBM")
        self.assertEqual(self.db.query(MarketDailyPrice).count(), 0)

    def test_us_watchlist_ranking_contract_preserves_unknown_price_basis(self) -> None:
        row = USWatchlistRankingItemRead.model_validate(
            {
                "rank": 1,
                "symbol": "LYV",
                "group_id": 36,
                "status": "ready",
                "price_basis": None,
            }
        )

        self.assertIsNone(row.price_basis)

    def test_us_watchlist_ranking_uses_resolver_priority_and_raw_price_basis(self) -> None:
        upsert_us_symbol_records(
            self.db,
            parse_symbol_directories(
                nasdaq_listed_text=NASDAQ_LISTED_SAMPLE,
                other_listed_text=OTHER_LISTED_SAMPLE,
                sec_company_payload=SEC_TICKERS_SAMPLE,
            ),
        )
        group = create_us_watchlist_group(
            self.db,
            USWatchlistGroupCreate(group_name="Resolver Ownership"),
        )
        create_us_watchlist_item(
            self.db,
            USWatchlistItemCreate(group_id=group.id, symbol="AAPL"),
        )
        records: list[USDailyPriceRecord] = []
        for provider, closes, adjusted_closes in (
            ("yahoo_chart", (100.0, 110.0), (90.0, 99.0)),
            ("alphavantage", (101.0, 120.0), (80.0, 85.0)),
        ):
            for trade_date, close, adjusted_close in zip(
                (date(2026, 5, 28), date(2026, 5, 29)),
                closes,
                adjusted_closes,
                strict=True,
            ):
                records.append(
                    USDailyPriceRecord(
                        provider=provider,
                        symbol="AAPL",
                        trade_date=trade_date,
                        open_price=close - 1,
                        high_price=close + 1,
                        low_price=close - 2,
                        close_price=close,
                        adjusted_close=adjusted_close,
                        trade_volume=1000,
                        dividend_amount=None,
                        split_coefficient=None,
                        source_url=None,
                        raw_payload_hash=f"{provider}-{trade_date.isoformat()}",
                    )
                )
        upsert_canonical_us_daily_price_records(self.db, records)

        with patch(
            "app.us_market.service.expected_us_daily_price_date",
            return_value=date(2026, 5, 29),
        ):
            ranking = get_us_watchlist_ranking(self.db, group_id=group.id)

        row = ranking["results"][0]
        self.assertEqual(row["selected_provider"], "yahoo_chart")
        self.assertEqual(row["close"], 110.0)
        self.assertEqual(row["previous_close"], 100.0)
        self.assertEqual(row["change_pct"], 10.0)
        self.assertEqual(row["price_basis"], "raw")
        self.assertFalse(row["fallback_used"])

    def test_us_watchlist_technical_radar_flags_ohlcv_breakout(self) -> None:
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
        records: list[USDailyPriceRecord] = []
        for index in range(21):
            close = 100.0 + index
            records.append(
                USDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="AAPL",
                    trade_date=date(2026, 5, 1 + index),
                    open_price=close - 0.5,
                    high_price=close + 1.0,
                    low_price=close - 1.0,
                    close_price=close,
                    adjusted_close=None,
                    trade_volume=1000,
                    dividend_amount=None,
                    split_coefficient=None,
                    source_url=None,
                    raw_payload_hash=f"aapl-{index}",
                )
            )
        records.append(
            USDailyPriceRecord(
                provider="yahoo_chart",
                symbol="AAPL",
                trade_date=date(2026, 5, 22),
                open_price=121.0,
                high_price=132.0,
                low_price=120.0,
                close_price=130.0,
                adjusted_close=None,
                trade_volume=4000,
                dividend_amount=None,
                split_coefficient=None,
                source_url=None,
                raw_payload_hash="aapl-breakout",
            )
        )
        upsert_canonical_us_daily_price_records(self.db, records)

        with patch(
            "app.us_market.service._latest_distinct_us_daily_rows",
            side_effect=AssertionError("Radar must not read legacy provider rows."),
        ):
            radar = get_us_watchlist_technical_radar(
                self.db,
                group_id=group.id,
                mode="breakout",
                max_results=5,
                calculation_limit=80,
            )

        self.assertEqual(radar["market"], "US")
        self.assertEqual(radar["radar_count"], 1)
        self.assertEqual(radar["results"][0]["stock_id"], "AAPL")
        self.assertEqual(radar["results"][0]["bucket"], "breakout_high")
        self.assertIn("donchian_breakout", radar["results"][0]["signal_keys"])
        self.assertIn("OHLCV technical radar only", radar["data_limitations"][0])

    def test_us_watchlist_ranking_marks_old_rows_stale_after_daily_release(self) -> None:
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
        upsert_canonical_us_daily_price_records(
            self.db,
            [USDailyPriceRecord(
                provider="yahoo_chart",
                symbol="AAPL",
                trade_date=date(2026, 6, 5),
                open_price=99.0,
                high_price=101.0,
                low_price=98.0,
                close_price=100.0,
                trade_volume=1000,
                adjusted_close=None,
                dividend_amount=None,
                split_coefficient=None,
                source_url=None,
                raw_payload_hash="aapl-1",
            )],
        )

        with patch(
            "app.us_market.service.expected_us_daily_price_date",
            return_value=date(2026, 6, 8),
        ):
            ranking = get_us_watchlist_ranking(
                self.db,
                group_id=group.id,
            )

        self.assertFalse(ranking["is_current"])
        self.assertEqual(ranking["target_trade_date"], date(2026, 6, 8))
        self.assertEqual(ranking["trade_date"], date(2026, 6, 5))
        self.assertEqual(ranking["current_symbol_count"], 0)
        self.assertEqual(ranking["stale_symbol_count"], 1)

    def test_us_watchlist_ranking_accepts_previous_session_before_daily_release(self) -> None:
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
        upsert_canonical_us_daily_price_records(
            self.db,
            [USDailyPriceRecord(
                provider="yahoo_chart",
                symbol="AAPL",
                trade_date=date(2026, 6, 5),
                open_price=99.0,
                high_price=101.0,
                low_price=98.0,
                close_price=100.0,
                trade_volume=1000,
                adjusted_close=None,
                dividend_amount=None,
                split_coefficient=None,
                source_url=None,
                raw_payload_hash="aapl-1",
            )],
        )

        with patch(
            "app.us_market.service.expected_us_daily_price_date",
            return_value=date(2026, 6, 5),
        ):
            ranking = get_us_watchlist_ranking(
                self.db,
                group_id=group.id,
            )

        self.assertTrue(ranking["is_current"])
        self.assertEqual(ranking["target_trade_date"], date(2026, 6, 5))
        self.assertEqual(ranking["current_symbol_count"], 1)
        self.assertEqual(ranking["stale_symbol_count"], 0)

    def test_us_watchlist_ranking_excludes_preclose_daily_row(self) -> None:
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
        upsert_canonical_us_daily_price_records(
            self.db,
            [
                USDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="AAPL",
                    trade_date=date(2026, 6, 5),
                    open_price=99.0,
                    high_price=101.0,
                    low_price=98.0,
                    close_price=100.0,
                    trade_volume=1000,
                    adjusted_close=None,
                    dividend_amount=None,
                    split_coefficient=None,
                    source_url=None,
                    raw_payload_hash="aapl-finalized",
                ),
            ],
        )
        self.db.add(
                USDailyPrice(
                    provider="yahoo_chart",
                    symbol="AAPL",
                    trade_date=date(2026, 6, 8),
                    open_price=100.0,
                    high_price=102.0,
                    low_price=99.0,
                    close_price=101.0,
                    trade_volume=50,
                    fetched_at=datetime(2026, 6, 8, 14, 0, tzinfo=timezone.utc),
                    raw_payload_hash="aapl-preclose",
                )
        )
        self.db.commit()

        with patch(
            "app.us_market.service.expected_us_daily_price_date",
            return_value=date(2026, 6, 8),
        ):
            ranking = get_us_watchlist_ranking(
                self.db,
                group_id=group.id,
            )

        self.assertFalse(ranking["is_current"])
        self.assertEqual(ranking["trade_date"], date(2026, 6, 5))
        self.assertEqual(ranking["results"][0]["close"], 100.0)
        self.assertEqual(ranking["stale_symbol_count"], 1)

    @patch("app.us_market.service.fetch_yahoo_chart_payload")
    def test_us_intraday_cache_miss_does_not_select_raw_daily_close(self, mock_fetch) -> None:
        self._add_market_identity("IBM")
        upsert_canonical_us_daily_price_records(
            self.db,
            [
                USDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="IBM",
                    trade_date=date(2026, 5, 29),
                    open_price=86.0,
                    high_price=88.0,
                    low_price=85.0,
                    close_price=87.0,
                    adjusted_close=None,
                    trade_volume=900,
                    dividend_amount=None,
                    split_coefficient=None,
                    source_url=None,
                    raw_payload_hash="ibm-older",
                ),
                USDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="IBM",
                    trade_date=date(2026, 6, 1),
                    open_price=87.5,
                    high_price=89.0,
                    low_price=87.0,
                    close_price=88.5,
                    adjusted_close=None,
                    trade_volume=1200,
                    dividend_amount=None,
                    split_coefficient=None,
                    source_url=None,
                    raw_payload_hash="ibm-reference",
                ),
            ],
        )
        mock_fetch.return_value = (
            YAHOO_CHART_INTRADAY_PREMARKET_SAMPLE,
            "https://example.test/chart/IBM?includePrePost=true",
        )

        trend = get_us_intraday_trend(
            symbol="ibm",
            session_scope="all",
            db=self.db,
        )

        mock_fetch.assert_not_called()
        self.assertEqual(trend["point_count"], 0)
        self.assertIsNone(trend["previous_close"])

    @patch("app.us_market.service.fetch_yahoo_chart_payload")
    def test_us_intraday_cache_miss_does_not_fetch_previous_regular_session(
        self,
        mock_fetch,
    ) -> None:
        self._add_market_identity("IBM")
        self.db.add(
            USDailyPrice(
                provider="yahoo_chart",
                symbol="IBM",
                trade_date=date(2026, 5, 29),
                close_price=87.0,
                trade_volume=900,
                raw_payload_hash="ibm-stale",
            )
        )
        self.db.commit()
        mock_fetch.side_effect = [
            (
                YAHOO_CHART_INTRADAY_PREMARKET_SAMPLE,
                "https://example.test/chart/IBM?includePrePost=true",
            ),
            (
                YAHOO_CHART_INTRADAY_PREVIOUS_REGULAR_SAMPLE,
                "https://example.test/chart/IBM?includePrePost=false",
            ),
        ]

        trend = get_us_intraday_trend(
            symbol="ibm",
            session_scope="all",
            db=self.db,
        )

        mock_fetch.assert_not_called()
        self.assertEqual(trend["point_count"], 0)
        self.assertIsNone(trend["previous_close"])

    @patch("app.us_market.service.fetch_yahoo_chart_payload")
    def test_us_intraday_cache_miss_does_not_use_preclose_raw_daily_reference(
        self,
        mock_fetch,
    ) -> None:
        self._add_market_identity("IBM")
        upsert_canonical_us_daily_price_records(
            self.db,
            [
                USDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="IBM",
                    trade_date=date(2026, 5, 29),
                    open_price=86.0,
                    high_price=88.0,
                    low_price=85.0,
                    close_price=87.0,
                    adjusted_close=None,
                    trade_volume=900,
                    dividend_amount=None,
                    split_coefficient=None,
                    source_url=None,
                    raw_payload_hash="ibm-finalized",
                )
            ],
        )
        self.db.add(
            USDailyPrice(
                provider="yahoo_chart",
                symbol="IBM",
                trade_date=date(2026, 6, 1),
                close_price=85.0,
                trade_volume=200,
                fetched_at=datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc),
                raw_payload_hash="ibm-preclose",
            )
        )
        self.db.commit()
        mock_fetch.side_effect = [
            (
                YAHOO_CHART_INTRADAY_PREMARKET_SAMPLE,
                "https://example.test/chart/IBM?includePrePost=true",
            ),
            (
                YAHOO_CHART_INTRADAY_PREVIOUS_REGULAR_SAMPLE,
                "https://example.test/chart/IBM?includePrePost=false",
            ),
        ]

        trend = get_us_intraday_trend(
            symbol="ibm",
            session_scope="all",
            db=self.db,
        )

        mock_fetch.assert_not_called()
        self.assertEqual(trend["point_count"], 0)
        self.assertIsNone(trend["previous_close"])

    @patch("app.us_market.service.fetch_yahoo_chart_payload")
    def test_us_intraday_cache_miss_does_not_read_unresolved_daily_rows(
        self,
        mock_fetch,
    ) -> None:
        self._add_market_identity("IBM")
        self.db.add_all(
            [
                USDailyPrice(
                    provider="yahoo_chart",
                    symbol="IBM",
                    trade_date=date(2026, 6, 1),
                    close_price=88.5,
                    trade_volume=1200,
                    raw_payload_hash="ibm-reference",
                ),
                USDailyPrice(
                    provider="yahoo_chart",
                    symbol="IBM",
                    trade_date=date(2026, 6, 2),
                    close_price=91.25,
                    trade_volume=2000,
                    raw_payload_hash="ibm-same-day",
                ),
            ]
        )
        self.db.commit()
        mock_fetch.return_value = (
            YAHOO_CHART_INTRADAY_SAMPLE,
            "https://example.test/chart/IBM?includePrePost=false",
        )

        trend = get_us_intraday_trend(
            symbol="ibm",
            session_scope="regular",
            db=self.db,
        )

        mock_fetch.assert_not_called()
        self.assertEqual(trend["point_count"], 0)
        self.assertIsNone(trend["previous_close"])

    def test_us_watchlist_ranking_limits_current_quote_overlay_without_intraday(self) -> None:
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
            USStockMaster(
                symbol=f"TEST{index:02d}",
                security_name=f"Synthetic test symbol {index:02d}",
                exchange="NASDAQ",
                asset_type="stock",
                listing_source="test_fixture",
            )
            for index in range(28)
        )
        self.db.flush()
        self.db.add_all(
            USWatchlistItem(
                group_id=group.id,
                symbol=f"TEST{index:02d}",
                priority=100 + index,
                enabled=True,
            )
            for index in range(28)
        )
        self.db.commit()
        upsert_canonical_us_daily_price_records(
            self.db,
            [
                USDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="AAPL",
                    trade_date=date(2026, 5, 29),
                    open_price=99.0,
                    high_price=101.0,
                    low_price=98.0,
                    close_price=100.0,
                    trade_volume=1000,
                    adjusted_close=None,
                    dividend_amount=None,
                    split_coefficient=None,
                    source_url=None,
                    raw_payload_hash="aapl-1",
                ),
                USDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="IBM",
                    trade_date=date(2026, 5, 29),
                    open_price=189.0,
                    high_price=191.0,
                    low_price=188.0,
                    close_price=190.0,
                    trade_volume=4000,
                    adjusted_close=None,
                    dividend_amount=None,
                    split_coefficient=None,
                    source_url=None,
                    raw_payload_hash="ibm-1",
                ),
            ],
        )

        with patch(
            "app.us_market.service.expected_us_daily_price_date",
            return_value=date(2026, 5, 29),
        ), patch(
            "app.us_market.service.get_us_intraday_trend",
            side_effect=AssertionError("ranking called full intraday trend"),
        ) as full_intraday, patch(
            "app.us_market.service._get_us_current_quote_overlay"
        ) as mock_overlay:
            mock_overlay.return_value = {
                "time": "2026-06-05T13:45:00-04:00",
                "session": "regular",
                "close": 111.0,
                "previous_close": 100.0,
                "change": 11.0,
                "change_pct": 11.0,
                "volume": 2000,
                "source": "test_intraday",
                "provider": "test_quote",
                "selection_reason": "TEST_CURRENT_QUOTE_SELECTED",
                "fallback_used": False,
                "is_live": True,
                "limitations": [],
                "has_extended_hours": False,
            }

            ranking = get_us_watchlist_ranking(
                self.db,
                group_id=group.id,
                use_current_quote=True,
                intraday_limit=30,
            )

        self.assertEqual(mock_overlay.call_count, 30)
        full_intraday.assert_not_called()
        first_quote_call = mock_overlay.call_args_list[0]
        self.assertEqual(first_quote_call.kwargs["symbol"], "AAPL")
        self.assertIs(first_quote_call.kwargs["db"], self.db)
        self.assertIn("now", first_quote_call.kwargs)
        self.assertEqual(len(ranking["results"]), 30)
        self.assertEqual(ranking["results"][0]["symbol"], "AAPL")
        self.assertEqual(ranking["results"][0]["status"], "current_quote")
        self.assertEqual(ranking["results"][0]["close"], 111.0)
        self.assertEqual(ranking["results"][0]["intraday_points"], [])
        self.assertEqual(ranking["ranking_semantics"], "current_quote_overlay")
        self.assertEqual(ranking["results"][1]["symbol"], "IBM")
        self.assertEqual(ranking["results"][1]["status"], "current_quote")
        self.assertEqual(ranking["results"][1]["close"], 111.0)

    def test_expected_us_daily_price_date_uses_new_york_release_time(self) -> None:
        self.assertEqual(
            expected_us_daily_price_date(
                now=datetime(2026, 6, 8, 19, 59, tzinfo=timezone.utc),
            ),
            date(2026, 6, 5),
        )
        self.assertEqual(
            expected_us_daily_price_date(
                now=datetime(2026, 6, 8, 20, 4, tzinfo=timezone.utc),
            ),
            date(2026, 6, 5),
        )
        self.assertEqual(
            expected_us_daily_price_date(
                now=datetime(2026, 6, 8, 20, 6, tzinfo=timezone.utc),
            ),
            date(2026, 6, 8),
        )
        self.assertEqual(
            expected_us_daily_price_date(
                now=datetime(2026, 6, 19, 20, 6, tzinfo=timezone.utc),
            ),
            date(2026, 6, 18),
        )

    def test_us_daily_price_finalization_uses_fetch_time_and_settlement_buffer(
        self,
    ) -> None:
        trade_date = date(2026, 6, 8)

        self.assertEqual(
            us_daily_price_finalization_time(trade_date),
            datetime(2026, 6, 8, 20, 5, tzinfo=timezone.utc),
        )
        self.assertFalse(
            is_us_daily_price_finalized(
                trade_date=trade_date,
                fetched_at=datetime(2026, 6, 8, 14, 0, tzinfo=timezone.utc),
            )
        )
        self.assertTrue(
            is_us_daily_price_finalized(
                trade_date=trade_date,
                fetched_at=datetime(2026, 6, 8, 20, 5, tzinfo=timezone.utc),
            )
        )

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
            patch(
                "app.us_market.service._refresh_us_watchlist_daily_through_platform",
                side_effect=daily_result,
            ) as daily_mock,
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

    @patch("app.us_market.service.fetch_yahoo_chart_payload")
    def test_us_stock_search_discovers_exact_missing_symbol(self, mock_fetch) -> None:
        mock_fetch.return_value = (
            YAHOO_CHART_DISCOVERY_SAMPLE,
            "https://query1.finance.yahoo.com/v8/finance/chart/SPCX?range=5d&interval=1d",
        )

        results = search_us_stocks(
            self.db,
            keyword="spcx",
            limit=5,
            discover_missing_exact_symbol=True,
        )
        stock = self.db.query(USStockMaster).filter(USStockMaster.symbol == "SPCX").one()

        self.assertEqual(results[0].symbol, "SPCX")
        self.assertEqual(results[0].security_name, "SpaceX Corp.")
        self.assertEqual(stock.listing_source, "discovered_yahoo_chart")
        self.assertEqual(mock_fetch.call_args.kwargs["symbol"], "SPCX")

    @patch("app.us_market.service.fetch_yahoo_chart_payload")
    def test_us_stock_search_keeps_empty_result_when_discovery_fails(self, mock_fetch) -> None:
        mock_fetch.side_effect = USMarketDataFetchError("No data found for this symbol.")

        results = search_us_stocks(
            self.db,
            keyword="notreal",
            limit=5,
            discover_missing_exact_symbol=True,
        )

        self.assertEqual(results, [])
        self.assertEqual(self.db.query(USStockMaster).count(), 0)

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
        self.assertEqual(chart["volume_unit"], "shares")
        self.assertEqual(chart["volume_semantics"], "monthly_traded_shares")
        self.assertEqual(chart["volume_status"], "available")

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

    def test_us_daily_ohlc_uses_one_canonical_row_per_trade_date(self) -> None:
        records = [
            USDailyPriceRecord(
                provider="yahoo_chart",
                symbol="MU",
                trade_date=date(2026, 3, 25),
                open_price=100.0,
                high_price=110.0,
                low_price=95.0,
                close_price=105.0,
                adjusted_close=None,
                trade_volume=1000,
                dividend_amount=None,
                split_coefficient=None,
                source_url="https://query1.finance.yahoo.com/v8/finance/chart/MU?range=1y&interval=1d",
                raw_payload_hash="yahoo-duplicate-date",
            ),
            USDailyPriceRecord(
                provider="alphavantage",
                symbol="MU",
                trade_date=date(2026, 3, 25),
                open_price=101.0,
                high_price=112.0,
                low_price=96.0,
                close_price=111.0,
                adjusted_close=None,
                trade_volume=2000,
                dividend_amount=None,
                split_coefficient=None,
                source_url="https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol=MU&apikey=REDACTED",
                raw_payload_hash="alphavantage-duplicate-date",
            ),
        ]
        upsert_us_daily_price_records(self.db, records)
        self._set_daily_fetched_at(
            provider="yahoo_chart",
            symbol="MU",
            trade_date=date(2026, 3, 25),
            fetched_at=datetime(2026, 3, 25, 20, 0, tzinfo=timezone.utc),
        )
        self._set_daily_fetched_at(
            provider="alphavantage",
            symbol="MU",
            trade_date=date(2026, 3, 25),
            fetched_at=datetime(2026, 3, 25, 22, 0, tzinfo=timezone.utc),
        )

        chart = list_us_ohlc_chart_data(
            self.db,
            symbol="MU",
            timeframe="daily",
            bars=5,
            to_date=date(2026, 3, 25),
        )

        self.assertEqual(chart["point_count"], 1)
        self.assertEqual(chart["points"][0]["time"], date(2026, 3, 25))
        self.assertEqual(chart["points"][0]["close"], 111.0)
        self.assertEqual(chart["points"][0]["volume"], 2000)

    def test_us_weekly_ohlc_does_not_double_count_duplicate_providers(self) -> None:
        records = [
            USDailyPriceRecord(
                provider="yahoo_chart",
                symbol="MU",
                trade_date=date(2026, 3, 23),
                open_price=100.0,
                high_price=105.0,
                low_price=98.0,
                close_price=104.0,
                adjusted_close=None,
                trade_volume=100,
                dividend_amount=None,
                split_coefficient=None,
                source_url="https://query1.finance.yahoo.com/v8/finance/chart/MU?range=1y&interval=1d",
                raw_payload_hash="weekly-yahoo-1",
            ),
            USDailyPriceRecord(
                provider="alphavantage",
                symbol="MU",
                trade_date=date(2026, 3, 23),
                open_price=101.0,
                high_price=106.0,
                low_price=99.0,
                close_price=105.0,
                adjusted_close=None,
                trade_volume=200,
                dividend_amount=None,
                split_coefficient=None,
                source_url="https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol=MU&apikey=REDACTED",
                raw_payload_hash="weekly-alpha-1",
            ),
            USDailyPriceRecord(
                provider="yahoo_chart",
                symbol="MU",
                trade_date=date(2026, 3, 24),
                open_price=106.0,
                high_price=112.0,
                low_price=104.0,
                close_price=110.0,
                adjusted_close=None,
                trade_volume=300,
                dividend_amount=None,
                split_coefficient=None,
                source_url="https://query1.finance.yahoo.com/v8/finance/chart/MU?range=1y&interval=1d",
                raw_payload_hash="weekly-yahoo-2",
            ),
            USDailyPriceRecord(
                provider="alphavantage",
                symbol="MU",
                trade_date=date(2026, 3, 24),
                open_price=107.0,
                high_price=113.0,
                low_price=105.0,
                close_price=111.0,
                adjusted_close=None,
                trade_volume=400,
                dividend_amount=None,
                split_coefficient=None,
                source_url="https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol=MU&apikey=REDACTED",
                raw_payload_hash="weekly-alpha-2",
            ),
        ]
        upsert_us_daily_price_records(self.db, records)
        for trade_date in (date(2026, 3, 23), date(2026, 3, 24)):
            self._set_daily_fetched_at(
                provider="yahoo_chart",
                symbol="MU",
                trade_date=trade_date,
                fetched_at=datetime(2026, 3, 25, 20, 0, tzinfo=timezone.utc),
            )
            self._set_daily_fetched_at(
                provider="alphavantage",
                symbol="MU",
                trade_date=trade_date,
                fetched_at=datetime(2026, 3, 25, 22, 0, tzinfo=timezone.utc),
            )

        chart = list_us_ohlc_chart_data(
            self.db,
            symbol="MU",
            timeframe="weekly",
            bars=5,
            to_date=date(2026, 3, 27),
        )

        self.assertEqual(chart["point_count"], 1)
        self.assertEqual(chart["points"][0]["time"], date(2026, 3, 23))
        self.assertEqual(chart["points"][0]["open"], 101.0)
        self.assertEqual(chart["points"][0]["high"], 113.0)
        self.assertEqual(chart["points"][0]["low"], 99.0)
        self.assertEqual(chart["points"][0]["close"], 111.0)
        self.assertEqual(chart["points"][0]["volume"], 600)

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

    def test_us_daily_ohlc_uses_partial_cache_when_refresh_fails(self) -> None:
        records = [
            USDailyPriceRecord(
                provider="yahoo_chart",
                symbol="MU",
                trade_date=date(2026, 5, 29),
                open_price=100.0,
                high_price=105.0,
                low_price=95.0,
                close_price=102.0,
                adjusted_close=None,
                trade_volume=1000,
                dividend_amount=None,
                split_coefficient=None,
                source_url="https://query1.finance.yahoo.com/v8/finance/chart/MU?range=1y&interval=1d",
                raw_payload_hash="partial-cache-row",
            )
        ]
        upsert_us_daily_price_records(self.db, records)

        with patch("app.us_market.service.refresh_us_daily_prices") as refresh_mock:
            refresh_mock.side_effect = USMarketDataFetchError("provider down")
            chart = list_us_ohlc_chart_data(
                self.db,
                symbol="MU",
                timeframe="daily",
                bars=5,
                ensure_history=True,
                outputsize="compact",
                provider="auto",
                to_date=date(2026, 5, 31),
            )

        self.assertEqual(chart["point_count"], 1)
        self.assertEqual(chart["points"][0]["time"], date(2026, 5, 29))
        self.assertEqual(chart["backfill"]["status"], "error")
        self.assertIn("using cached clean rows", chart["backfill"]["message"])

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

        with patch("app.us_market.service.refresh_us_daily_ohlcv") as refresh_mock:
            refresh_mock.side_effect = lambda **kwargs: {
                "status": "success",
                "provider": "canonical",
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
            self.assertEqual(call.kwargs["outputsize"], "compact")

    @patch("app.us_market.service.parse_yahoo_daily_prices")
    @patch("app.us_market.service.fetch_yahoo_chart_payload")
    def test_us_yahoo_refresh_skips_unfinalized_daily_row(
        self,
        mock_fetch,
        mock_parse,
    ) -> None:
        mock_fetch.return_value = (
            {"chart": {"result": []}},
            "https://example.test/chart/IBM",
        )
        mock_parse.return_value = [
            USDailyPriceRecord(
                provider="yahoo_chart",
                symbol="IBM",
                trade_date=date(2026, 6, 5),
                open_price=87.0,
                high_price=89.0,
                low_price=86.0,
                close_price=88.5,
                adjusted_close=88.5,
                trade_volume=1200,
                dividend_amount=None,
                split_coefficient=None,
                source_url="https://example.test/chart/IBM",
                raw_payload_hash="ibm-finalized",
            ),
            USDailyPriceRecord(
                provider="yahoo_chart",
                symbol="IBM",
                trade_date=date(2026, 6, 8),
                open_price=90.0,
                high_price=91.0,
                low_price=89.5,
                close_price=90.6,
                adjusted_close=90.6,
                trade_volume=300,
                dividend_amount=None,
                split_coefficient=None,
                source_url="https://example.test/chart/IBM",
                raw_payload_hash="ibm-preclose",
            ),
        ]

        with patch(
            "app.us_market.service.expected_us_daily_price_date",
            return_value=date(2026, 6, 5),
        ):
            result = refresh_us_daily_prices_from_yahoo_chart(
                self.db,
                symbol="IBM",
            )

        rows = list_us_daily_prices(self.db, symbol="IBM")
        self.assertEqual(result["status"], "partial_success")
        self.assertEqual(result["fetched_count"], 2)
        self.assertEqual(result["eligible_count"], 1)
        self.assertEqual(result["skipped_count"], 1)
        self.assertEqual(result["expected_trade_date"], date(2026, 6, 5))
        self.assertEqual(result["latest_eligible_trade_date"], date(2026, 6, 5))
        self.assertEqual([row.trade_date for row in rows], [date(2026, 6, 5)])
        self.assertIn("2026-06-08", result["warnings"][0])

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

    def test_auto_daily_refresh_uses_yahoo_for_full_history(self) -> None:
        yahoo_result = {
            "status": "success",
            "provider": "yahoo_chart",
            "symbol": "MU",
            "fetched_count": 2,
            "inserted_count": 1,
            "updated_count": 1,
            "message": "US daily prices refreshed from Yahoo chart.",
        }

        with (
            patch("app.us_market.service.settings.alphavantage_api_key", "demo"),
            patch("app.us_market.service.refresh_us_daily_prices_from_alphavantage") as alpha_mock,
            patch(
                "app.us_market.service.refresh_us_daily_prices_from_yahoo_chart",
                return_value=yahoo_result,
            ) as yahoo_mock,
        ):
            result = refresh_us_daily_prices(
                self.db,
                symbol="MU",
                outputsize="full",
                provider="auto",
            )

        alpha_mock.assert_not_called()
        yahoo_mock.assert_called_once_with(db=self.db, symbol="MU", outputsize="full")
        self.assertEqual(result["provider"], "yahoo_chart")

    def test_auto_daily_refresh_falls_back_to_alphavantage_after_yahoo_error(self) -> None:
        alpha_result = {
            "status": "success",
            "provider": "alphavantage",
            "symbol": "MU",
            "fetched_count": 2,
            "inserted_count": 1,
            "updated_count": 1,
            "message": "US daily prices refreshed from Alpha Vantage.",
        }

        with (
            patch("app.us_market.service.settings.alphavantage_api_key", "demo"),
            patch(
                "app.us_market.service.refresh_us_daily_prices_from_alphavantage",
                return_value=alpha_result,
            ) as alpha_mock,
            patch(
                "app.us_market.service.refresh_us_daily_prices_from_yahoo_chart",
                side_effect=USMarketDataFetchError("Yahoo unavailable"),
            ) as yahoo_mock,
        ):
            result = refresh_us_daily_prices(
                self.db,
                symbol="MU",
                outputsize="compact",
                provider="auto",
            )

        alpha_mock.assert_called_once_with(
            db=self.db,
            symbol="MU",
            outputsize="compact",
            adjusted=False,
        )
        yahoo_mock.assert_called_once_with(db=self.db, symbol="MU", outputsize="compact")
        self.assertEqual(result["provider"], "alphavantage")
        self.assertIn("Yahoo chart auto refresh failed first", result["message"])

    def test_us_monthly_ohlc_skips_refresh_when_local_points_are_enough(self) -> None:
        records = [
            USDailyPriceRecord(
                provider="yahoo_chart",
                symbol="MU",
                trade_date=date(2025, month, 30 if month == 6 else 1),
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

    def test_us_daily_ohlc_refreshes_when_full_window_is_stale(self) -> None:
        records = [
            USDailyPriceRecord(
                provider="yahoo_chart",
                symbol="SOX",
                trade_date=trade_date,
                open_price=100.0 + index,
                high_price=105.0 + index,
                low_price=95.0 + index,
                close_price=102.0 + index,
                adjusted_close=None,
                trade_volume=1000 + index,
                dividend_amount=None,
                split_coefficient=None,
                source_url="https://query1.finance.yahoo.com/v8/finance/chart/%5ESOX",
                raw_payload_hash=f"stale-sox-{index}",
            )
            for index, trade_date in enumerate(
                [date(2026, 7, 13), date(2026, 7, 14)],
                start=1,
            )
        ]
        upsert_us_daily_price_records(self.db, records)

        with patch(
            "app.us_market.service.refresh_us_daily_prices",
            return_value={
                "status": "success",
                "provider": "yahoo_chart",
                "symbol": "SOX",
                "fetched_count": 0,
                "inserted_count": 0,
                "updated_count": 0,
                "message": "mocked",
            },
        ) as refresh_mock:
            chart = list_us_ohlc_chart_data(
                self.db,
                symbol="SOX",
                timeframe="daily",
                bars=2,
                ensure_history=True,
                provider="yahoo_chart",
                to_date=date(2026, 7, 16),
            )

        refresh_mock.assert_called_once()
        self.assertEqual(chart["latest_data_date"], date(2026, 7, 14))
        self.assertEqual(chart["expected_data_date"], date(2026, 7, 16))
        self.assertEqual(chart["freshness_status"], "stale")
        self.assertIn("stale_latest_date", chart["backfill"]["refresh_reasons"])


if __name__ == "__main__":
    unittest.main()
