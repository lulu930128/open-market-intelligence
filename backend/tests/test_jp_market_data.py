from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai.agentic_tools import read_jp_stock_context
from app.db.models import (
    Base,
    JPCompanyFundamental,
    JPDailyPrice,
    JPInvestorType,
    JPMarginInterest,
    JPStockMaster,
    JPWatchlistGroup,
    JPWatchlistItem,
    USWatchlistGroup,
    USWatchlistItem,
    WatchlistGroup,
    WatchlistItem,
    SourceHealthSnapshot,
)
from app.jp_market import service as jp_market_service
from app.jp_market.schemas import (
    JPMarketOverviewRead,
    JPSourceHealthRead,
    JPWatchlistGroupCreate,
    JPWatchlistItemCreate,
)
from app.jp_market.source_health import build_jp_source_health
from app.jp_market.service import (
    JPWatchlistDuplicateItemError,
    create_jp_watchlist_group,
    create_jp_watchlist_item,
    get_jp_company_fundamental,
    get_jp_intraday_trend,
    get_jp_market_overview,
    get_jp_resource_summary,
    get_jp_watchlist_ranking,
    get_jp_watchlist_technical_radar,
    list_jp_ohlc_chart_data,
    list_jp_watchlist_items,
    list_jp_watchlist_symbols,
    refresh_jp_company_fundamental,
    refresh_jp_company_fundamental_from_yahoo_quote_summary,
    refresh_jp_daily_prices_from_yahoo_chart,
    refresh_jp_market_resource,
    refresh_jp_watchlist_resources,
    search_jp_stocks,
    sync_jp_symbol_master,
    upsert_jp_company_fundamental_records,
    upsert_jp_daily_price_records,
    upsert_jp_investor_type_records,
    upsert_jp_margin_interest_records,
)
from app.jp_market.sources import (
    JPCompanyFundamentalRecord,
    JPDailyPriceRecord,
    JPInvestorTypeRecord,
    JPMarginInterestRecord,
    JPMarketDataFetchError,
    normalize_jp_symbol,
    parse_jquants_company_fundamental,
    parse_jquants_investor_type_records,
    parse_jquants_margin_interest_records,
    parse_yahoo_company_fundamental,
    parse_jpx_listed_issue_rows,
    parse_yahoo_daily_prices,
    parse_yahoo_intraday_prices,
    parse_yahoo_stock_record,
)


def _tokyo_timestamp(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, 15, 0, tzinfo=timezone(timedelta(hours=9))).timestamp())


def _tokyo_intraday_timestamp(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
) -> int:
    return int(
        datetime(
            year,
            month,
            day,
            hour,
            minute,
            tzinfo=timezone(timedelta(hours=9)),
        ).timestamp()
    )


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


YAHOO_JP_INTRADAY_SAMPLE = {
    "chart": {
        "result": [
            {
                "meta": {
                    "symbol": "^N225",
                    "fullExchangeName": "Nikkei",
                    "instrumentType": "INDEX",
                    "currency": "JPY",
                    "exchangeTimezoneName": "Asia/Tokyo",
                    "gmtoffset": 32400,
                    "chartPreviousClose": 39800.0,
                },
                "timestamp": [
                    _tokyo_intraday_timestamp(2026, 6, 19, 9, 0),
                    _tokyo_intraday_timestamp(2026, 6, 19, 9, 1),
                    _tokyo_intraday_timestamp(2026, 6, 19, 11, 45),
                    _tokyo_intraday_timestamp(2026, 6, 19, 12, 30),
                    _tokyo_intraday_timestamp(2026, 6, 19, 15, 30),
                ],
                "indicators": {
                    "quote": [
                        {
                            "open": [39900.0, 39920.0, 39940.0, 40010.0, 40120.0],
                            "high": [39940.0, 39950.0, 39950.0, 40080.0, 40180.0],
                            "low": [39890.0, 39910.0, 39930.0, 39990.0, 40100.0],
                            "close": [39920.0, 39940.0, 39945.0, 40060.0, 40150.0],
                            "volume": [100000, 120000, 0, 150000, 180000],
                        }
                    ],
                },
            }
        ],
        "error": None,
    }
}


YAHOO_JP_QUOTE_SUMMARY_SAMPLE = {
    "quoteSummary": {
        "result": [
            {
                "price": {
                    "symbol": "7203.T",
                    "longName": "Toyota Motor Corporation",
                    "fullExchangeName": "Tokyo Stock Exchange",
                    "currency": "JPY",
                    "marketCap": {"raw": 41000000000000, "fmt": "41T"},
                },
                "assetProfile": {
                    "sector": "Consumer Cyclical",
                    "industry": "Auto Manufacturers",
                },
                "summaryDetail": {
                    "trailingPE": {"raw": 9.8, "fmt": "9.80"},
                    "forwardPE": {"raw": 8.9, "fmt": "8.90"},
                    "dividendYield": {"raw": 0.026, "fmt": "2.60%"},
                    "beta": {"raw": 1.05, "fmt": "1.05"},
                },
                "defaultKeyStatistics": {
                    "enterpriseValue": {"raw": 52000000000000, "fmt": "52T"},
                    "trailingEps": {"raw": 320.12, "fmt": "320.12"},
                    "forwardEps": {"raw": 345.67, "fmt": "345.67"},
                    "priceToBook": {"raw": 1.15, "fmt": "1.15"},
                    "bookValue": {"raw": 2300.5, "fmt": "2,300.5"},
                    "sharesOutstanding": {"raw": 13200000000, "fmt": "13.2B"},
                },
                "financialData": {
                    "financialCurrency": "JPY",
                    "totalRevenue": {"raw": 48000000000000, "fmt": "48T"},
                    "grossMargins": {"raw": 0.205, "fmt": "20.50%"},
                    "operatingMargins": {"raw": 0.112, "fmt": "11.20%"},
                    "profitMargins": {"raw": 0.092, "fmt": "9.20%"},
                    "returnOnEquity": {"raw": 0.138, "fmt": "13.80%"},
                    "returnOnAssets": {"raw": 0.053, "fmt": "5.30%"},
                    "revenueGrowth": {"raw": 0.061, "fmt": "6.10%"},
                    "earningsGrowth": {"raw": 0.074, "fmt": "7.40%"},
                    "totalCash": {"raw": 9000000000000, "fmt": "9T"},
                    "totalDebt": {"raw": 33000000000000, "fmt": "33T"},
                    "debtToEquity": {"raw": 98.2, "fmt": "98.2"},
                    "currentRatio": {"raw": 1.12, "fmt": "1.12"},
                    "quickRatio": {"raw": 0.91, "fmt": "0.91"},
                },
                "calendarEvents": {
                    "earnings": {
                        "earningsDate": [{"raw": 1788480000, "fmt": "2026-09-04"}],
                    },
                    "exDividendDate": {"raw": 1777334400, "fmt": "2026-04-28"},
                },
            }
        ],
        "error": None,
    }
}


JQUANTS_STATEMENTS_SAMPLE = {
    "statements": [
        {
            "DisclosedDate": "2025-05-08",
            "DisclosedTime": "15:00:00",
            "LocalCode": "7203",
            "DisclosureNumber": "20250508555555",
            "TypeOfDocument": "FYFinancialStatements_Consolidated_IFRS",
            "TypeOfCurrentPeriod": "FY",
            "CurrentFiscalYearStartDate": "2024-04-01",
            "CurrentFiscalYearEndDate": "2025-03-31",
            "NetSales": "45000000000000",
            "OperatingProfit": "5100000000000",
            "OrdinaryProfit": "5600000000000",
            "Profit": "4900000000000",
            "EarningsPerShare": "300.12",
            "TotalAssets": "89000000000000",
            "Equity": "35000000000000",
            "EquityToAssetRatio": "0.393",
            "BookValuePerShare": "2200.5",
            "CashFlowsFromOperatingActivities": "4200000000000",
            "CashFlowsFromInvestingActivities": "-2100000000000",
            "CashFlowsFromFinancingActivities": "-1300000000000",
            "CashAndEquivalents": "8200000000000",
            "ForecastNetSales": "47000000000000",
            "ForecastOperatingProfit": "5300000000000",
            "ForecastOrdinaryProfit": "5700000000000",
            "ForecastProfit": "5000000000000",
            "ForecastEarningsPerShare": "320.30",
            "NumberOfIssuedAndOutstandingSharesAtTheEndOfFiscalYearIncludingTreasuryStock": "13200000000",
        },
        {
            "DisclosedDate": "2026-05-08",
            "DisclosedTime": "15:00:00",
            "LocalCode": "7203",
            "DisclosureNumber": "20260508123456",
            "TypeOfDocument": "FYFinancialStatements_Consolidated_IFRS",
            "TypeOfCurrentPeriod": "FY",
            "CurrentFiscalYearStartDate": "2025-04-01",
            "CurrentFiscalYearEndDate": "2026-03-31",
            "NetSales": "48000000000000",
            "OperatingProfit": "5400000000000",
            "OrdinaryProfit": "5900000000000",
            "Profit": "5300000000000",
            "EarningsPerShare": "320.12",
            "TotalAssets": "91000000000000",
            "Equity": "37000000000000",
            "EquityToAssetRatio": "0.407",
            "BookValuePerShare": "2300.5",
            "CashFlowsFromOperatingActivities": "4500000000000",
            "CashFlowsFromInvestingActivities": "-2300000000000",
            "CashFlowsFromFinancingActivities": "-1500000000000",
            "CashAndEquivalents": "9000000000000",
            "ForecastNetSales": "50000000000000",
            "ForecastOperatingProfit": "5600000000000",
            "ForecastOrdinaryProfit": "6000000000000",
            "ForecastProfit": "5500000000000",
            "ForecastEarningsPerShare": "345.67",
            "NumberOfIssuedAndOutstandingSharesAtTheEndOfFiscalYearIncludingTreasuryStock": "13200000000",
        },
    ]
}


JQUANTS_SUMMARY_SAMPLE = {
    "data": [
        {
            "DiscDate": "2025-05-08",
            "DiscTime": "15:00:00",
            "Code": "72030",
            "DiscNo": "20250508555555",
            "DocType": "FYFinancialStatements_Consolidated_IFRS",
            "CurPerType": "FY",
            "CurPerSt": "2024-04-01",
            "CurPerEn": "2025-03-31",
            "CurFYEn": "2025-03-31",
            "Sales": "45000000000000",
            "OP": "5100000000000",
            "OdP": "5600000000000",
            "NP": "4900000000000",
            "EPS": "300.12",
            "TA": "89000000000000",
            "Eq": "35000000000000",
            "EqAR": "0.393",
            "BPS": "2200.5",
            "CFO": "4200000000000",
            "CFI": "-2100000000000",
            "CFF": "-1300000000000",
            "CashEq": "8200000000000",
            "FSales": "47000000000000",
            "FOP": "5300000000000",
            "FOdP": "5700000000000",
            "FNP": "5000000000000",
            "FEPS": "320.30",
            "ShOutFY": "13200000000",
        },
        {
            "DiscDate": "2026-05-08",
            "DiscTime": "15:00:00",
            "Code": "72030",
            "DiscNo": "20260508123456",
            "DocType": "FYFinancialStatements_Consolidated_IFRS",
            "CurPerType": "FY",
            "CurPerSt": "2025-04-01",
            "CurPerEn": "2026-03-31",
            "CurFYEn": "2026-03-31",
            "Sales": "48000000000000",
            "OP": "5400000000000",
            "OdP": "5900000000000",
            "NP": "5300000000000",
            "EPS": "320.12",
            "TA": "91000000000000",
            "Eq": "37000000000000",
            "EqAR": "0.407",
            "BPS": "2300.5",
            "CFO": "4500000000000",
            "CFI": "-2300000000000",
            "CFF": "-1500000000000",
            "CashEq": "9000000000000",
            "FSales": "50000000000000",
            "FOP": "5600000000000",
            "FOdP": "6000000000000",
            "FNP": "5500000000000",
            "FEPS": "345.67",
            "ShOutFY": "13200000000",
        },
    ]
}


JQUANTS_MARGIN_INTEREST_SAMPLE = {
    "data": [
        {
            "Date": "2026-06-12",
            "Code": "72030",
            "ShrtVol": "100000",
            "LongVol": "3400000",
            "ShrtNegVol": "30000",
            "LongNegVol": "1200000",
            "ShrtStdVol": "70000",
            "LongStdVol": "2200000",
            "IssType": "2",
        }
    ]
}


JQUANTS_INVESTOR_TYPES_SAMPLE = {
    "data": [
        {
            "PubDate": "2026-06-19",
            "StDate": "2026-06-08",
            "EnDate": "2026-06-12",
            "Section": "TSEPrime",
            "PropSell": "1000",
            "PropBuy": "1250",
            "PropTot": "2250",
            "PropBal": "250",
            "BrkSell": "9000",
            "BrkBuy": "8500",
            "BrkTot": "17500",
            "BrkBal": "-500",
            "TotSell": "10000",
            "TotBuy": "9750",
            "TotTot": "19750",
            "TotBal": "-250",
            "IndSell": "3200",
            "IndBuy": "2800",
            "IndTot": "6000",
            "IndBal": "-400",
            "FrgnSell": "4200",
            "FrgnBuy": "5000",
            "FrgnTot": "9200",
            "FrgnBal": "800",
            "InvTrSell": "700",
            "InvTrBuy": "650",
            "InvTrTot": "1350",
            "InvTrBal": "-50",
            "TrstBnkSell": "1100",
            "TrstBnkBuy": "900",
            "TrstBnkTot": "2000",
            "TrstBnkBal": "-200",
        }
    ]
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

    def test_parse_yahoo_intraday_prices_classifies_japan_sessions(self) -> None:
        trend = parse_yahoo_intraday_prices(
            YAHOO_JP_INTRADAY_SAMPLE,
            symbol="^N225",
            source_url="https://query1.finance.yahoo.com/v8/finance/chart/%5EN225",
        )

        self.assertEqual(trend["stock_id"], "^N225")
        self.assertEqual(trend["symbol"], "^N225")
        self.assertEqual(trend["source"], "yahoo_finance_chart")
        self.assertEqual(trend["previous_close"], 39800.0)
        self.assertEqual(trend["previous_close_source"], "yahoo_finance_chart")
        self.assertEqual(trend["point_count"], 5)
        self.assertEqual(trend["regular_point_count"], 4)
        self.assertEqual(trend["session_phase"], "regular")
        self.assertEqual(trend["regular_session_close"], 40150.0)
        self.assertEqual(trend["points"][0]["time"], "2026-06-19T09:00:00+09:00")
        self.assertEqual(trend["points"][2]["session"], "lunch_break")
        self.assertTrue(all(point["volume"] is None for point in trend["points"]))
        self.assertEqual(trend["volume_status"], "not_provided")
        self.assertEqual(
            trend["volume_semantics"],
            "not_provided_for_cash_index",
        )

    def test_parse_yahoo_company_fundamental(self) -> None:
        record = parse_yahoo_company_fundamental(
            YAHOO_JP_QUOTE_SUMMARY_SAMPLE,
            symbol="7203",
            source_url="https://query1.finance.yahoo.com/v10/finance/quoteSummary/7203.T",
        )

        self.assertEqual(record.provider, "yahoo_quote_summary")
        self.assertEqual(record.symbol, "7203.T")
        self.assertEqual(record.company_name, "Toyota Motor Corporation")
        self.assertEqual(record.sector, "Consumer Cyclical")
        self.assertEqual(record.industry, "Auto Manufacturers")
        self.assertEqual(record.currency, "JPY")
        self.assertEqual(record.market_cap, 41000000000000)
        self.assertEqual(record.revenue_ttm, 48000000000000)
        self.assertEqual(record.eps_ttm, 320.12)
        self.assertEqual(record.profit_margin, 0.092)
        self.assertEqual(record.earnings_date, datetime(2026, 9, 4).date())

    def test_parse_jquants_company_fundamental(self) -> None:
        record = parse_jquants_company_fundamental(
            JQUANTS_STATEMENTS_SAMPLE,
            symbol="7203",
            source_url="https://api.jquants.com/v1/fins/statements?code=7203",
            company_name="Toyota Motor Corporation",
            sector="Transportation Equipment",
            industry="Automobiles & Transportation Equipment",
        )

        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.provider, "jquants_statements")
        self.assertEqual(record.symbol, "7203.T")
        self.assertEqual(record.disclosed_date, datetime(2026, 5, 8).date())
        self.assertEqual(record.fiscal_period, "FY")
        self.assertEqual(record.fiscal_year_end, datetime(2026, 3, 31).date())
        self.assertEqual(record.net_sales, 48000000000000)
        self.assertEqual(record.operating_profit, 5400000000000)
        self.assertEqual(record.profit, 5300000000000)
        self.assertEqual(record.forward_eps, 345.67)
        self.assertAlmostEqual(record.operating_margin or 0, 0.1125)
        self.assertAlmostEqual(record.profit_margin or 0, 0.11041666666666666)
        self.assertAlmostEqual(record.revenue_growth or 0, 0.06666666666666667)
        self.assertAlmostEqual(record.earnings_growth or 0, 0.08163265306122448)
        self.assertEqual(record.equity_to_asset_ratio, 0.407)

    def test_parse_jquants_company_fundamental_v2_summary(self) -> None:
        record = parse_jquants_company_fundamental(
            JQUANTS_SUMMARY_SAMPLE,
            symbol="7203",
            source_url="https://api.jquants.com/v2/fins/summary?code=7203",
            company_name="Toyota Motor Corporation",
        )

        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.provider, "jquants_statements")
        self.assertEqual(record.symbol, "7203.T")
        self.assertEqual(record.disclosed_date, datetime(2026, 5, 8).date())
        self.assertEqual(record.fiscal_period, "FY")
        self.assertEqual(record.fiscal_year_end, datetime(2026, 3, 31).date())
        self.assertEqual(record.net_sales, 48000000000000)
        self.assertEqual(record.operating_profit, 5400000000000)
        self.assertEqual(record.profit, 5300000000000)
        self.assertEqual(record.forward_eps, 345.67)
        self.assertEqual(record.shares_outstanding, 13200000000)
        self.assertAlmostEqual(record.revenue_growth or 0, 0.06666666666666667)
        self.assertEqual(record.equity_to_asset_ratio, 0.407)

    def test_parse_jquants_margin_interest_records(self) -> None:
        records = parse_jquants_margin_interest_records(
            JQUANTS_MARGIN_INTEREST_SAMPLE,
            symbol="7203",
            source_url="https://api.jquants.com/v2/markets/margin-interest?code=7203",
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].provider, "jquants_margin_interest")
        self.assertEqual(records[0].symbol, "7203.T")
        self.assertEqual(records[0].report_date, datetime(2026, 6, 12).date())
        self.assertEqual(records[0].long_volume, 3400000)
        self.assertEqual(records[0].short_volume, 100000)
        self.assertEqual(records[0].issue_type, "2")

    def test_parse_jquants_investor_type_records(self) -> None:
        records = parse_jquants_investor_type_records(
            JQUANTS_INVESTOR_TYPES_SAMPLE,
            source_url="https://api.jquants.com/v2/equities/investor-types?section=TSEPrime",
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].provider, "jquants_investor_types")
        self.assertEqual(records[0].section, "TSEPrime")
        self.assertEqual(records[0].published_date, datetime(2026, 6, 19).date())
        self.assertEqual(records[0].foreign_balance, 800)
        self.assertEqual(records[0].trust_bank_balance, -200)
        self.assertEqual(records[0].individual_balance, -400)

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

    def test_get_jp_watchlist_ranking_uses_latest_daily_prices(self) -> None:
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
        create_jp_watchlist_item(
            self.db,
            JPWatchlistItemCreate(group_id=group.id, symbol="1343"),
        )
        upsert_jp_daily_price_records(
            self.db,
            [
                JPDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="7203.T",
                    trade_date=datetime(2026, 6, 17).date(),
                    currency="JPY",
                    open_price=3000.0,
                    high_price=3060.0,
                    low_price=2990.0,
                    close_price=3000.0,
                    adjusted_close=3000.0,
                    trade_volume=12000000,
                    source_url="source",
                    raw_payload_hash="hash-1",
                ),
                JPDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="7203.T",
                    trade_date=datetime(2026, 6, 18).date(),
                    currency="JPY",
                    open_price=3010.0,
                    high_price=3120.0,
                    low_price=3000.0,
                    close_price=3060.0,
                    adjusted_close=3060.0,
                    trade_volume=15000000,
                    source_url="source",
                    raw_payload_hash="hash-2",
                ),
                JPDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="1343.T",
                    trade_date=datetime(2026, 6, 17).date(),
                    currency="JPY",
                    open_price=2000.0,
                    high_price=2040.0,
                    low_price=1980.0,
                    close_price=2000.0,
                    adjusted_close=2000.0,
                    trade_volume=900000,
                    source_url="source",
                    raw_payload_hash="hash-3",
                ),
                JPDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="1343.T",
                    trade_date=datetime(2026, 6, 18).date(),
                    currency="JPY",
                    open_price=2010.0,
                    high_price=2030.0,
                    low_price=1940.0,
                    close_price=1960.0,
                    adjusted_close=1960.0,
                    trade_volume=1100000,
                    source_url="source",
                    raw_payload_hash="hash-4",
                ),
            ],
        )

        ranking = get_jp_watchlist_ranking(
            self.db,
            group_id=group.id,
            rank_by="change_pct",
            sort_order="desc",
            expected_trade_date=date(2026, 6, 18),
        )

        self.assertEqual(ranking["group_id"], group.id)
        self.assertEqual(ranking["requested_symbol_count"], 2)
        self.assertEqual(ranking["ranked_count"], 2)
        self.assertEqual(ranking["no_data_count"], 0)
        self.assertTrue(ranking["is_current"])
        self.assertEqual(ranking["trade_date"], datetime(2026, 6, 18).date())
        self.assertEqual(ranking["target_trade_date"], datetime(2026, 6, 18).date())
        self.assertEqual(ranking["coverage_status"], "current")
        self.assertFalse(ranking["refresh_recommended"])
        self.assertEqual(
            ranking["underlying_trade_date"],
            datetime(2026, 6, 18).date(),
        )
        self.assertEqual(ranking["coverage_ratio"], 1.0)
        self.assertFalse(ranking["is_live"])
        self.assertTrue(ranking["is_full"])
        self.assertEqual(
            ranking["ranking_semantics"],
            "latest_completed_daily_rows",
        )
        self.assertEqual(ranking["results"][0]["symbol"], "7203.T")
        self.assertEqual(ranking["results"][0]["close"], 3060.0)
        self.assertEqual(ranking["results"][0]["change"], 60.0)
        self.assertAlmostEqual(ranking["results"][0]["change_pct"], 2.0)
        self.assertEqual(ranking["results"][1]["symbol"], "1343.T")
        self.assertAlmostEqual(ranking["results"][1]["change_pct"], -2.0)

        stale_ranking = get_jp_watchlist_ranking(
            self.db,
            group_id=group.id,
            expected_trade_date=date(2026, 6, 19),
        )
        self.assertFalse(stale_ranking["is_current"])
        self.assertEqual(stale_ranking["target_trade_date"], date(2026, 6, 19))
        self.assertEqual(stale_ranking["stale_symbol_count"], 2)
        self.assertEqual(stale_ranking["missing_symbol_count"], 0)
        self.assertEqual(stale_ranking["coverage_status"], "stale")
        self.assertTrue(stale_ranking["refresh_recommended"])
        self.assertTrue(
            all(row["freshness_status"] == "stale" for row in stale_ranking["results"])
        )

    def test_jp_watchlist_technical_radar_flags_support_break(self) -> None:
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
        records: list[JPDailyPriceRecord] = []
        for index in range(21):
            close = 3000.0 + index
            records.append(
                JPDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="7203.T",
                    trade_date=datetime(2026, 5, 1 + index).date(),
                    currency="JPY",
                    open_price=close + 5.0,
                    high_price=close + 20.0,
                    low_price=close - 20.0,
                    close_price=close,
                    adjusted_close=close,
                    trade_volume=1000000,
                    source_url="source",
                    raw_payload_hash=f"jp-7203-{index}",
                )
            )
        records.append(
            JPDailyPriceRecord(
                provider="yahoo_chart",
                symbol="7203.T",
                trade_date=datetime(2026, 5, 22).date(),
                currency="JPY",
                open_price=2980.0,
                high_price=2990.0,
                low_price=2760.0,
                close_price=2800.0,
                adjusted_close=2800.0,
                trade_volume=3500000,
                source_url="source",
                raw_payload_hash="jp-7203-break",
            )
        )
        upsert_jp_daily_price_records(self.db, records)

        radar = get_jp_watchlist_technical_radar(
            self.db,
            group_id=group.id,
            mode="risk",
            max_results=5,
            calculation_limit=80,
        )

        self.assertEqual(radar["market"], "JP")
        self.assertEqual(radar["radar_count"], 1)
        self.assertEqual(radar["results"][0]["stock_id"], "7203.T")
        self.assertEqual(radar["results"][0]["bucket"], "support_break")
        self.assertIn("structure_support_break", radar["results"][0]["signal_keys"])
        self.assertIn("OHLCV technical radar only", radar["data_limitations"][0])

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

    def test_jp_source_health_exposes_explicit_freshness_policy(self) -> None:
        with patch(
            "app.jp_market.service.fetch_yahoo_chart_payload",
            return_value=(
                YAHOO_JP_CHART_SAMPLE,
                "https://query1.finance.yahoo.com/v8/finance/chart/7203.T",
            ),
        ):
            refresh_jp_daily_prices_from_yahoo_chart(
                db=self.db,
                symbol="7203",
                outputsize="compact",
            )

        availability = build_jp_source_health(
            self.db,
            symbol="7203.T",
            use_expected_date=False,
        )
        automatic = build_jp_source_health(
            self.db,
            symbol="7203.T",
            now=datetime(2026, 6, 18, 17, 0, tzinfo=timezone(timedelta(hours=9))),
        )
        exact = build_jp_source_health(
            self.db,
            symbol="7203.T",
            expected_daily_price_date=date(2026, 6, 18),
        )
        entries = {
            (entry["resource"], entry["provider"]): entry
            for entry in exact["entries"]
        }

        self.assertEqual(availability["freshness_policy"]["mode"], "availability_only")
        self.assertIsNotNone(availability["freshness_policy"]["calendar_limit"])
        self.assertEqual(automatic["freshness_policy"]["mode"], "expected_date")
        self.assertEqual(automatic["expected_daily_price_date"], "2026-06-18")
        self.assertEqual(exact["freshness_policy"]["mode"], "expected_date")
        self.assertEqual(entries[("daily_price", "yahoo_chart")]["status"], "current")
        self.assertGreater(self.db.query(SourceHealthSnapshot).count(), 0)
        self.assertEqual(JPSourceHealthRead.model_validate(exact).kind, "jp_source_health")

        self.db.add(
            JPInvestorType(
                provider="jquants_investor_types",
                section="TSEPrime",
                published_date=date(2026, 6, 18),
            )
        )
        self.db.commit()
        unknown_symbol = build_jp_source_health(self.db, symbol="9999.T")
        investor_entry = next(
            entry
            for entry in unknown_symbol["entries"]
            if entry["resource"] == "investor_types"
        )
        self.assertEqual(investor_entry["status"], "empty")
        self.assertEqual(investor_entry["target"], "9999.T")

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

    def test_refresh_jp_company_fundamental_from_yahoo_quote_summary_upserts_row(self) -> None:
        with patch(
            "app.jp_market.service.fetch_yahoo_quote_summary_payload",
            return_value=(
                YAHOO_JP_QUOTE_SUMMARY_SAMPLE,
                "https://query1.finance.yahoo.com/v10/finance/quoteSummary/7203.T",
            ),
        ) as fetch_mock:
            result = refresh_jp_company_fundamental_from_yahoo_quote_summary(
                db=self.db,
                symbol="7203",
            )

        fetch_mock.assert_called_once()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["provider"], "yahoo_quote_summary")
        self.assertEqual(result["symbol"], "7203.T")
        self.assertEqual(result["fetched_count"], 1)
        self.assertEqual(result["inserted_count"], 1)
        self.assertEqual(self.db.query(JPCompanyFundamental).count(), 1)

        row = self.db.query(JPCompanyFundamental).one()
        self.assertEqual(row.company_name, "Toyota Motor Corporation")
        self.assertEqual(row.market_cap, 41000000000000)
        self.assertEqual(row.revenue_ttm, 48000000000000)

    def test_refresh_jp_company_fundamental_auto_uses_jquants_statements(self) -> None:
        with (
            patch("app.jp_market.service.settings.jquants_api_key", "test-api-key"),
            patch(
                "app.jp_market.service.fetch_jquants_summary_payload",
                return_value=(
                    JQUANTS_SUMMARY_SAMPLE,
                    "https://api.jquants.com/v2/fins/summary?code=7203",
                ),
            ) as fetch_mock,
        ):
            result = refresh_jp_company_fundamental(
                db=self.db,
                symbol="7203",
                provider="auto",
            )

        fetch_mock.assert_called_once()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["provider"], "jquants_statements")
        self.assertEqual(result["symbol"], "7203.T")
        self.assertEqual(result["fetched_count"], 2)
        self.assertEqual(result["inserted_count"], 1)

        row = (
            self.db.query(JPCompanyFundamental)
            .filter(JPCompanyFundamental.provider == "jquants_statements")
            .one()
        )
        self.assertEqual(row.provider, "jquants_statements")
        self.assertEqual(row.net_sales, 48000000000000)
        self.assertEqual(row.operating_profit, 5400000000000)
        self.assertEqual(row.profit, 5300000000000)
        self.assertEqual(row.fiscal_period, "FY")

    def test_refresh_jp_company_fundamental_reuses_refresh_token_id_token(self) -> None:
        with (
            patch("app.jp_market.service.settings.jquants_api_base_url", "https://api.jquants.com/v1"),
            patch("app.jp_market.service.settings.jquants_api_key", None),
            patch("app.jp_market.service.settings.jquants_id_token", None),
            patch("app.jp_market.service.settings.jquants_refresh_token", "test-refresh-token"),
            patch("app.jp_market.service.settings.jquants_mail_address", None),
            patch("app.jp_market.service.settings.jquants_password", None),
            patch("app.jp_market.service.settings.jquants_id_token_cache_seconds", 3600),
            patch("app.jp_market.service._jquants_id_token_cache", None),
            patch(
                "app.jp_market.service.fetch_jquants_id_token",
                return_value="test-id-token",
            ) as id_token_mock,
            patch(
                "app.jp_market.service.fetch_jquants_statements_payload",
                return_value=(
                    JQUANTS_STATEMENTS_SAMPLE,
                    "https://api.jquants.com/v1/fins/statements?code=7203",
                ),
            ) as statements_mock,
        ):
            first_result = refresh_jp_company_fundamental(
                db=self.db,
                symbol="7203",
                provider="jquants_statements",
            )
            second_result = refresh_jp_company_fundamental(
                db=self.db,
                symbol="7203",
                provider="jquants_statements",
            )

        id_token_mock.assert_called_once()
        self.assertEqual(statements_mock.call_count, 2)
        self.assertEqual(first_result["status"], "success")
        self.assertEqual(second_result["status"], "success")
        self.assertEqual(self.db.query(JPCompanyFundamental).count(), 1)

    def test_refresh_jp_company_fundamental_auto_falls_back_to_yahoo(self) -> None:
        with (
            patch("app.jp_market.service.settings.jquants_api_key", None),
            patch("app.jp_market.service.settings.jquants_id_token", None),
            patch("app.jp_market.service.settings.jquants_refresh_token", None),
            patch("app.jp_market.service.settings.jquants_mail_address", None),
            patch("app.jp_market.service.settings.jquants_password", None),
            patch(
                "app.jp_market.service.fetch_yahoo_quote_summary_payload",
                return_value=(
                    YAHOO_JP_QUOTE_SUMMARY_SAMPLE,
                    "https://query1.finance.yahoo.com/v10/finance/quoteSummary/7203.T",
                ),
            ) as yahoo_fetch_mock,
        ):
            result = refresh_jp_company_fundamental(
                db=self.db,
                symbol="7203",
                provider="auto",
            )

        yahoo_fetch_mock.assert_called_once()
        self.assertEqual(result["status"], "partial_success")
        self.assertEqual(result["provider"], "yahoo_quote_summary")
        self.assertEqual(result["symbol"], "7203.T")
        self.assertEqual(result["fetched_count"], 1)
        self.assertEqual(result["inserted_count"], 1)

        row = self.db.query(JPCompanyFundamental).one()
        self.assertEqual(row.provider, "yahoo_quote_summary")
        self.assertEqual(row.market_cap, 41000000000000)

    def test_get_jp_company_fundamental_merges_primary_and_supplemental_rows(self) -> None:
        jquants_record = parse_jquants_company_fundamental(
            JQUANTS_STATEMENTS_SAMPLE,
            symbol="7203",
            source_url="https://api.jquants.com/v1/fins/statements?code=7203",
            company_name="Toyota Motor Corporation",
        )
        yahoo_record = parse_yahoo_company_fundamental(
            YAHOO_JP_QUOTE_SUMMARY_SAMPLE,
            symbol="7203.T",
            source_url="https://query1.finance.yahoo.com/v10/finance/quoteSummary/7203.T",
        )
        assert jquants_record is not None
        upsert_jp_company_fundamental_records(self.db, [jquants_record, yahoo_record])

        row = get_jp_company_fundamental(db=self.db, symbol="7203")

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row.provider, "jquants_statements+yahoo_quote_summary")
        self.assertEqual(row.net_sales, 48000000000000)
        self.assertEqual(row.operating_profit, 5400000000000)
        self.assertEqual(row.total_assets, 91000000000000)
        self.assertEqual(row.market_cap, 41000000000000)
        self.assertEqual(row.trailing_pe, 9.8)

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
        self.assertIn("insufficient_history", result["backfill"]["refresh_reasons"])
        self.assertEqual(result["freshness_status"], "missing")
        self.assertTrue(result["refresh_recommended"])

    def test_jp_ohlc_chart_refreshes_when_full_window_is_stale(self) -> None:
        records = [
            JPDailyPriceRecord(
                provider="yahoo_chart",
                symbol="9984.T",
                trade_date=date(2026, 6, day),
                currency="JPY",
                open_price=1000.0 + day,
                high_price=1010.0 + day,
                low_price=990.0 + day,
                close_price=1005.0 + day,
                adjusted_close=1005.0 + day,
                trade_volume=1000000,
                source_url="source",
                raw_payload_hash=f"hash-{day}",
            )
            for day in range(15, 19)
        ]
        upsert_jp_daily_price_records(self.db, records)

        with patch(
            "app.jp_market.service.refresh_jp_daily_prices",
            return_value={
                "status": "success",
                "provider": "yahoo_chart",
                "symbol": "9984.T",
                "fetched_count": 0,
                "inserted_count": 0,
                "updated_count": 0,
                "message": "mocked",
            },
        ) as refresh_mock:
            result = list_jp_ohlc_chart_data(
                db=self.db,
                symbol="9984.T",
                bars=4,
                ensure_history=True,
                to_date=date(2026, 6, 22),
                expected_data_date=date(2026, 6, 22),
            )

        refresh_mock.assert_called_once()
        self.assertEqual(result["point_count"], 4)
        self.assertEqual(result["latest_data_date"], date(2026, 6, 18))
        self.assertEqual(result["expected_data_date"], date(2026, 6, 22))
        self.assertEqual(result["freshness_status"], "stale")
        self.assertIn("stale_latest_date", result["backfill"]["refresh_reasons"])

    def test_get_jp_intraday_trend_uses_yahoo_chart_payload(self) -> None:
        with patch(
            "app.jp_market.service.fetch_yahoo_chart_payload",
            return_value=(
                YAHOO_JP_INTRADAY_SAMPLE,
                "https://query1.finance.yahoo.com/v8/finance/chart/%5EN225",
            ),
        ) as fetch_mock:
            result = get_jp_intraday_trend(
                db=self.db,
                symbol="^N225",
                refresh=True,
            )

        fetch_mock.assert_called_once()
        call_kwargs = fetch_mock.call_args.kwargs
        self.assertEqual(call_kwargs["symbol"], "^N225")
        self.assertEqual(call_kwargs["range_value"], "1d")
        self.assertEqual(call_kwargs["interval"], "1m")
        self.assertEqual(result["symbol"], "^N225")
        self.assertEqual(result["point_count"], 5)
        self.assertEqual(result["regular_point_count"], 4)
        self.assertEqual(result["previous_close"], 39800.0)
        self.assertEqual(result["previous_close_trade_date"], "2026-06-18")
        self.assertEqual(result["volume_status"], "not_provided")

    def test_get_jp_intraday_trend_falls_back_to_daily_previous_close(self) -> None:
        upsert_jp_daily_price_records(
            self.db,
            [
                JPDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="^N225",
                    trade_date=datetime(2026, 6, 18).date(),
                    currency="JPY",
                    open_price=39700.0,
                    high_price=39950.0,
                    low_price=39650.0,
                    close_price=39780.0,
                    adjusted_close=39780.0,
                    trade_volume=200000000,
                    source_url="source",
                    raw_payload_hash="hash",
                ),
            ],
        )
        payload = deepcopy(YAHOO_JP_INTRADAY_SAMPLE)
        meta = payload["chart"]["result"][0]["meta"]
        meta.pop("chartPreviousClose", None)

        with patch(
            "app.jp_market.service.fetch_yahoo_chart_payload",
            return_value=(
                payload,
                "https://query1.finance.yahoo.com/v8/finance/chart/%5EN225",
            ),
        ):
            result = get_jp_intraday_trend(
                db=self.db,
                symbol="^N225",
                refresh=True,
            )

        self.assertEqual(result["previous_close"], 39780.0)
        self.assertEqual(result["previous_close_source"], "jp_daily_price")
        self.assertEqual(result["previous_close_trade_date"], "2026-06-18")
        self.assertEqual(result["previous_close_provider"], "yahoo_chart")

    def test_jp_stock_intraday_bootstraps_bounded_history_and_exposes_volume_pace(self) -> None:
        with patch(
            "app.jp_market.service.fetch_yahoo_chart_payload",
            return_value=(
                YAHOO_JP_INTRADAY_SAMPLE,
                "https://query1.finance.yahoo.com/v8/finance/chart/7203.T?range=5d&interval=1m",
            ),
        ) as fetch_mock:
            result = get_jp_intraday_trend(
                db=self.db,
                symbol="7203.T",
                refresh=True,
            )

        self.assertEqual(fetch_mock.call_args.kwargs["range_value"], "5d")
        self.assertEqual(result["point_count"], 5)
        self.assertEqual(result["volume_pace"]["market"], "JP")
        self.assertEqual(result["volume_pace"]["status"], "partial")

        jp_market_service._jp_intraday_cache.clear()
        with patch(
            "app.jp_market.service.fetch_yahoo_chart_payload",
            side_effect=AssertionError(
                "cache-only replay must not call the provider"
            ),
        ) as fetch_again:
            replay = get_jp_intraday_trend(
                db=self.db,
                symbol="7203.T",
                refresh=False,
                external_fetch_allowed=False,
            )

        fetch_again.assert_not_called()
        self.assertEqual(replay["point_count"], 4)
        self.assertEqual(replay["cache_status"], "persisted_hit")
        self.assertTrue(replay["cache_hit"])

    def test_refresh_jp_watchlist_resources_refreshes_group_symbols(self) -> None:
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
        create_jp_watchlist_item(
            self.db,
            JPWatchlistItemCreate(group_id=group.id, symbol="1343"),
        )

        def fake_refresh(**kwargs):
            return {
                "status": "success",
                "provider": "yahoo_chart",
                "symbol": kwargs["symbol"],
                "fetched_count": 2,
                "inserted_count": 1,
                "updated_count": 1,
                "message": "mocked",
            }

        with patch("app.jp_market.service.refresh_jp_daily_prices", side_effect=fake_refresh):
            result = refresh_jp_watchlist_resources(
                db=self.db,
                group_id=group.id,
                sleep_seconds=0,
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["symbol_count"], 2)
        self.assertEqual(result["success_count"], 2)
        self.assertEqual(result["error_count"], 0)
        self.assertEqual(result["fetched_count"], 4)
        self.assertEqual(result["inserted_count"], 2)
        self.assertEqual(result["updated_count"], 2)

    def test_refresh_jp_watchlist_resources_isolates_symbol_failures(self) -> None:
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
        create_jp_watchlist_item(
            self.db,
            JPWatchlistItemCreate(group_id=group.id, symbol="1343"),
        )

        def fake_refresh(**kwargs):
            if kwargs["symbol"] == "1343.T":
                raise RuntimeError("provider failed")

            return {
                "status": "success",
                "provider": "yahoo_chart",
                "symbol": kwargs["symbol"],
                "fetched_count": 2,
                "inserted_count": 1,
                "updated_count": 1,
                "message": "mocked",
            }

        with patch("app.jp_market.service.refresh_jp_daily_prices", side_effect=fake_refresh):
            result = refresh_jp_watchlist_resources(
                db=self.db,
                group_id=group.id,
                include_fundamentals=False,
                sleep_seconds=0,
            )

        self.assertEqual(result["status"], "partial_success")
        self.assertEqual(result["symbol_count"], 2)
        self.assertEqual(result["success_count"], 1)
        self.assertEqual(result["symbol_error_count"], 1)
        self.assertEqual(result["error_count"], 1)
        self.assertEqual(result["errors"][0]["symbol"], "1343.T")
        self.assertEqual(result["errors"][0]["resource"], "daily")

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
        self.assertEqual(slots["demand"]["status"], "empty")
        self.assertFalse(slots["demand"]["available"])
        self.assertEqual(slots["investors"]["status"], "empty")
        self.assertFalse(slots["investors"]["available"])
        self.assertEqual(slots["disclosures"]["status"], "empty")
        self.assertEqual(slots["performance"]["status"], "empty")
        self.assertEqual(slots["financials"]["row_count"], 0)

    def test_jp_market_overview_reports_partial_local_coverage(self) -> None:
        for symbol, name, sector in (
            ("1111.T", "Alpha", "Services"),
            ("2222.T", "Beta", "Banks"),
            ("3333.T", "Gamma", "Services"),
            ("4444.T", "Delta", "Banks"),
        ):
            self.db.add(
                JPStockMaster(
                    symbol=symbol,
                    local_code=symbol.split(".")[0],
                    security_name=name,
                    exchange="Tokyo Stock Exchange",
                    market_segment="Prime Market (Domestic)",
                    sector_33_name=sector,
                    asset_type="stock",
                    listing_source="test",
                    currency="JPY",
                    is_active=True,
                )
            )
        self.db.commit()
        records = []
        for symbol, previous_close, current_close in (
            ("1111.T", 100.0, 110.0),
            ("2222.T", 100.0, 95.0),
        ):
            records.extend(
                [
                    JPDailyPriceRecord(
                        provider="yahoo_chart",
                        symbol=symbol,
                        trade_date=date(2026, 7, 14),
                        currency="JPY",
                        open_price=previous_close,
                        high_price=previous_close,
                        low_price=previous_close,
                        close_price=previous_close,
                        adjusted_close=previous_close,
                        trade_volume=1000,
                        source_url="source",
                        raw_payload_hash=f"{symbol}-previous",
                    ),
                    JPDailyPriceRecord(
                        provider="yahoo_chart",
                        symbol=symbol,
                        trade_date=date(2026, 7, 15),
                        currency="JPY",
                        open_price=previous_close,
                        high_price=max(previous_close, current_close),
                        low_price=min(previous_close, current_close),
                        close_price=current_close,
                        adjusted_close=current_close,
                        trade_volume=2000,
                        source_url="source",
                        raw_payload_hash=f"{symbol}-current",
                    ),
                ]
            )
        records.append(
            JPDailyPriceRecord(
                provider="yahoo_chart",
                symbol="3333.T",
                trade_date=date(2026, 7, 14),
                currency="JPY",
                open_price=50.0,
                high_price=51.0,
                low_price=49.0,
                close_price=50.0,
                adjusted_close=50.0,
                trade_volume=500,
                source_url="source",
                raw_payload_hash="3333-stale",
            )
        )
        upsert_jp_daily_price_records(self.db, records)

        overview = get_jp_market_overview(
            self.db,
            now=datetime.fromisoformat("2026-07-15T16:20:00+09:00"),
        )
        validated_overview = JPMarketOverviewRead.model_validate(overview)

        self.assertEqual(overview["kind"], "jp_market_overview")
        self.assertEqual(validated_overview.kind, "jp_market_overview")
        self.assertEqual(overview["expected_trade_date"], date(2026, 7, 15))
        self.assertEqual(overview["coverage"]["active_stock_count"], 4)
        self.assertEqual(overview["coverage"]["observed_symbol_count"], 3)
        self.assertEqual(overview["coverage"]["current_symbol_count"], 2)
        self.assertEqual(overview["coverage"]["stale_symbol_count"], 1)
        self.assertEqual(overview["coverage"]["missing_symbol_count"], 1)
        self.assertEqual(overview["coverage"]["status"], "partial")
        self.assertTrue(overview["coverage"]["is_partial"])
        self.assertEqual(overview["breadth"]["advance_count"], 1)
        self.assertEqual(overview["breadth"]["decline_count"], 1)
        self.assertEqual(overview["breadth"]["total_count"], 2)
        self.assertEqual(overview["breadth"]["universe_count"], 4)
        self.assertEqual(overview["breadth"]["coverage_count"], 2)
        self.assertEqual(overview["breadth"]["coverage_ratio"], 0.5)
        self.assertEqual(overview["breadth"]["classified_count"], 2)
        self.assertEqual(overview["breadth"]["unknown_count"], 2)
        self.assertEqual(overview["breadth"]["reconciliation_status"], "partial")
        self.assertTrue(overview["breadth"]["direct_market_breadth"])
        self.assertFalse(overview["breadth"]["proxy_used"])
        self.assertFalse(overview["coverage"]["is_full_market"])
        self.assertFalse(overview["breadth"]["is_full_market"])
        self.assertEqual(
            overview["breadth"]["universe_type"],
            "active_local_stock_master",
        )
        self.assertIn(
            "not_official_full_exchange_breadth",
            overview["breadth"]["coverage_limitation"],
        )
        self.assertEqual(overview["top_gainers"][0]["symbol"], "1111.T")
        self.assertEqual(overview["top_losers"][0]["symbol"], "2222.T")
        self.assertEqual(len(overview["indices"]), 2)
        self.assertTrue(all(not item["is_current"] for item in overview["indices"]))
        self.assertTrue(overview["refresh_recommended"])

    def test_read_jp_stock_context_returns_local_evidence_pack(self) -> None:
        self.db.add(
            JPStockMaster(
                symbol="7203.T",
                local_code="7203",
                security_name="Toyota Motor Corporation",
                exchange="Tokyo Stock Exchange",
                market_segment="Prime Market (Domestic)",
                sector_33_name="Transportation Equipment",
                asset_type="stock",
                listing_source="test",
                currency="JPY",
                is_active=True,
            )
        )
        self.db.commit()
        upsert_jp_daily_price_records(
            self.db,
            [
                JPDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="7203.T",
                    trade_date=datetime(2026, 6, 17).date(),
                    currency="JPY",
                    open_price=3000.0,
                    high_price=3060.0,
                    low_price=2990.0,
                    close_price=3050.0,
                    adjusted_close=3050.0,
                    trade_volume=12000000,
                    source_url="source-1",
                    raw_payload_hash="hash-1",
                ),
                JPDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="7203.T",
                    trade_date=datetime(2026, 6, 18).date(),
                    currency="JPY",
                    open_price=3060.0,
                    high_price=3090.0,
                    low_price=3030.0,
                    close_price=3080.0,
                    adjusted_close=3080.0,
                    trade_volume=15000000,
                    source_url="source-2",
                    raw_payload_hash="hash-2",
                ),
            ],
        )

        context = read_jp_stock_context(db=self.db, symbol="7203")

        self.assertEqual(context["kind"], "jp_stock_context")
        self.assertEqual(context["scope"]["target"]["type"], "jp_stock")
        self.assertEqual(context["scope"]["target"]["id"], "7203.T")
        self.assertEqual(context["summary"]["latest_close"], 3080.0)
        self.assertEqual(context["summary"]["latest_trade_date"], "2026-06-18")
        self.assertEqual(context["data"]["stock"]["security_name"], "Toyota Motor Corporation")
        self.assertEqual(context["data"]["daily_prices"][0]["trade_date"], "2026-06-18")
        self.assertEqual(context["data"]["chart"]["point_count"], 2)
        self.assertIn("jp_company_fundamental", context["missing"])
        self.assertTrue(
            any(ref.get("kind") == "jp_daily_price" for ref in context["source_refs"])
        )
        self.assertEqual(context["evidence_passport"]["target_kind"], "jp_stock_context")

    def test_read_jp_stock_context_includes_bounded_intraday_evidence(self) -> None:
        self.db.add(
            JPStockMaster(
                symbol="7203.T",
                local_code="7203",
                security_name="Toyota Motor Corporation",
                exchange="Tokyo Stock Exchange",
                market_segment="Prime Market (Domestic)",
                sector_33_name="Transportation Equipment",
                asset_type="stock",
                listing_source="test",
                currency="JPY",
                is_active=True,
            )
        )
        self.db.commit()
        upsert_jp_daily_price_records(
            self.db,
            [
                JPDailyPriceRecord(
                    provider="yahoo_chart",
                    symbol="7203.T",
                    trade_date=datetime(2026, 7, 14).date(),
                    currency="JPY",
                    open_price=3000.0,
                    high_price=3060.0,
                    low_price=2990.0,
                    close_price=3050.0,
                    adjusted_close=3050.0,
                    trade_volume=12000000,
                    source_url="daily-source",
                    raw_payload_hash="daily-hash",
                )
            ],
        )
        intraday = {
            "symbol": "7203.T",
            "source": "yahoo_finance_chart",
            "session_scope": "regular",
            "session_phase": "regular",
            "previous_close": 3050.0,
            "previous_close_source": "jp_daily_price",
            "previous_close_trade_date": "2026-07-14",
            "point_count": 2,
            "points": [
                {
                    "time": "2026-07-15T09:00:00+09:00",
                    "price": 3060.0,
                    "volume": 1000,
                },
                {
                    "time": "2026-07-15T10:00:00+09:00",
                    "price": 3080.0,
                    "volume": 1500,
                },
            ],
            "source_url": "intraday-source",
            "warnings": [],
        }

        with (
            patch(
                "app.ai.agentic_tools._now",
                return_value=datetime.fromisoformat("2026-07-15T10:05:00+09:00"),
            ),
            patch(
                "app.ai.agentic_tools.jp_market_service.get_jp_intraday_trend",
                return_value=intraday,
            ) as intraday_reader,
        ):
            context = read_jp_stock_context(
                db=self.db,
                symbol="7203",
                market_data_params={
                    "include_intraday": True,
                    "intraday_limit": 1,
                    "payload_level": "decision",
                },
            )

        intraday_reader.assert_called_once_with(
            symbol="7203.T",
            db=self.db,
            refresh=True,
            external_fetch_allowed=True,
        )
        compact = context["data"]["compact"]
        self.assertEqual(context["as_of"], "2026-07-15T10:00:00+09:00")
        self.assertFalse(compact["quote"]["is_realtime"])
        self.assertEqual(compact["quote"]["freshness"]["status"], "delayed")
        self.assertEqual(compact["quote"]["freshness"]["age_seconds"], 300)
        self.assertEqual(compact["quote"]["price"], 3080.0)
        self.assertTrue(compact["resources"]["include_intraday"])
        self.assertTrue(compact["resources"]["intraday_available"])
        self.assertEqual(compact["intraday_readiness"]["status"], "limited")
        self.assertFalse(
            compact["intraday_readiness"]["usable_for_intraday"]
        )
        self.assertTrue(
            compact["intraday_readiness"]["independent_of_daily"]
        )
        self.assertEqual(
            compact["intraday_readiness"]["daily_dependency"],
            "none",
        )
        self.assertEqual(
            compact["freshness_by_domain"]["intraday"],
            "delayed",
        )
        intraday_bars = compact["intraday_bars"]
        self.assertTrue(intraday_bars["enabled"])
        self.assertEqual(intraday_bars["series"]["1m"]["returned_point_count"], 1)
        self.assertEqual(
            intraday_bars["series"]["1m"]["points"][0]["price"],
            3080.0,
        )

    def test_read_jp_stock_context_treats_null_chart_points_as_empty(self) -> None:
        with patch(
            "app.ai.agentic_tools.jp_market_service.list_jp_ohlc_chart_data",
            return_value={
                "symbol": "7203.T",
                "timeframe": "daily",
                "point_count": 0,
                "points": None,
                "is_current": False,
                "latest_data_date": None,
                "expected_data_date": "2026-07-27",
            },
        ):
            context = read_jp_stock_context(db=self.db, symbol="7203")

        self.assertEqual(context["data"]["compact"]["resources"]["chart_points"], 0)
        self.assertIn("jp_daily_price", context["missing"])

    def test_jp_resource_summary_reports_fundamental_slots(self) -> None:
        upsert_jp_company_fundamental_records(
            self.db,
            [
                JPCompanyFundamentalRecord(
                    provider="yahoo_quote_summary",
                    symbol="7203.T",
                    company_name="Toyota Motor Corporation",
                    exchange="Tokyo Stock Exchange",
                    sector="Consumer Cyclical",
                    industry="Auto Manufacturers",
                    currency="JPY",
                    market_cap=41000000000000,
                    enterprise_value=52000000000000,
                    trailing_pe=9.8,
                    forward_pe=8.9,
                    price_to_book=1.15,
                    dividend_yield=0.026,
                    beta=1.05,
                    disclosed_date=datetime(2026, 5, 8).date(),
                    fiscal_period="FY",
                    fiscal_year_end=datetime(2026, 3, 31).date(),
                    document_type="FYFinancialStatements_Consolidated_IFRS",
                    eps_ttm=320.12,
                    forward_eps=345.67,
                    revenue_ttm=48000000000000,
                    net_sales=48000000000000,
                    operating_profit=5400000000000,
                    ordinary_profit=5900000000000,
                    profit=5300000000000,
                    forecast_net_sales=50000000000000,
                    forecast_operating_profit=5600000000000,
                    forecast_ordinary_profit=6000000000000,
                    forecast_profit=5500000000000,
                    gross_margin=0.205,
                    operating_margin=0.112,
                    profit_margin=0.092,
                    return_on_equity=0.138,
                    return_on_assets=0.053,
                    revenue_growth=0.061,
                    earnings_growth=0.074,
                    total_assets=91000000000000,
                    equity=37000000000000,
                    equity_to_asset_ratio=0.407,
                    total_cash=9000000000000,
                    total_debt=33000000000000,
                    operating_cash_flow=4500000000000,
                    investing_cash_flow=-2300000000000,
                    financing_cash_flow=-1500000000000,
                    debt_to_equity=98.2,
                    current_ratio=1.12,
                    quick_ratio=0.91,
                    shares_outstanding=13200000000,
                    book_value=2300.5,
                    earnings_date=datetime(2026, 9, 4).date(),
                    ex_dividend_date=datetime(2026, 4, 28).date(),
                    source_url="source",
                    raw_payload_hash="hash",
                ),
            ],
        )

        summary = get_jp_resource_summary(db=self.db, symbol="7203")
        slots = {slot["key"]: slot for slot in summary["slots"]}

        self.assertEqual(slots["performance"]["status"], "available")
        self.assertTrue(slots["performance"]["available"])
        self.assertEqual(slots["performance"]["source"], "yahoo_quote_summary")
        self.assertEqual(slots["performance"]["row_count"], 1)
        self.assertEqual(slots["financials"]["status"], "available")
        self.assertTrue(slots["financials"]["available"])
        self.assertEqual(slots["disclosures"]["status"], "partial")
        self.assertTrue(slots["disclosures"]["available"])
        self.assertEqual(slots["disclosures"]["latest_date"], date(2026, 5, 8))
        self.assertEqual(
            slots["disclosures"]["metrics"]["coverage"],
            "company_statement_metadata_only",
        )

    def test_jp_resource_summary_reports_market_resource_metrics(self) -> None:
        self.db.add(
            JPStockMaster(
                symbol="7203.T",
                local_code="7203",
                security_name="Toyota Motor Corporation",
                exchange="Tokyo Stock Exchange",
                market_segment="Prime Market (Domestic)",
                sector_33_name="Transportation Equipment",
                asset_type="stock",
                listing_source="jpx_listed_issues",
                currency="JPY",
                is_active=True,
            )
        )
        self.db.commit()

        upsert_jp_margin_interest_records(
            self.db,
            [
                JPMarginInterestRecord(
                    provider="jquants_margin_interest",
                    symbol="7203.T",
                    report_date=datetime(2026, 6, 12).date(),
                    short_volume=100000,
                    long_volume=3400000,
                    short_negotiable_volume=30000,
                    long_negotiable_volume=1200000,
                    short_standardized_volume=70000,
                    long_standardized_volume=2200000,
                    issue_type="2",
                    source_url="source",
                    raw_payload_hash="hash",
                )
            ],
        )
        upsert_jp_investor_type_records(
            self.db,
            [
                JPInvestorTypeRecord(
                    provider="jquants_investor_types",
                    section="TSEPrime",
                    published_date=datetime(2026, 6, 19).date(),
                    start_date=datetime(2026, 6, 8).date(),
                    end_date=datetime(2026, 6, 12).date(),
                    proprietary_sell=1000,
                    proprietary_buy=1250,
                    proprietary_total=2250,
                    proprietary_balance=250,
                    broker_sell=9000,
                    broker_buy=8500,
                    broker_total=17500,
                    broker_balance=-500,
                    total_sell=10000,
                    total_buy=9750,
                    total_traded=19750,
                    total_balance=-250,
                    individual_sell=3200,
                    individual_buy=2800,
                    individual_total=6000,
                    individual_balance=-400,
                    foreign_sell=4200,
                    foreign_buy=5000,
                    foreign_total=9200,
                    foreign_balance=800,
                    investment_trust_sell=700,
                    investment_trust_buy=650,
                    investment_trust_total=1350,
                    investment_trust_balance=-50,
                    trust_bank_sell=1100,
                    trust_bank_buy=900,
                    trust_bank_total=2000,
                    trust_bank_balance=-200,
                    source_url="source",
                    raw_payload_hash="hash",
                )
            ],
        )

        summary = get_jp_resource_summary(db=self.db, symbol="7203")
        slots = {slot["key"]: slot for slot in summary["slots"]}

        self.assertEqual(slots["demand"]["status"], "available")
        self.assertEqual(slots["demand"]["latest_date"], datetime(2026, 6, 12).date())
        self.assertEqual(slots["demand"]["metrics"]["margin_long_balance"], 3400000)
        self.assertEqual(slots["demand"]["metrics"]["margin_net_balance"], 3300000)
        self.assertEqual(slots["investors"]["status"], "available")
        self.assertEqual(slots["investors"]["latest_date"], datetime(2026, 6, 19).date())
        self.assertEqual(slots["investors"]["metrics"]["investor_section"], "TSEPrime")
        self.assertEqual(slots["investors"]["metrics"]["foreign_balance"], 800)
        self.assertEqual(slots["investors"]["metrics"]["trust_bank_balance"], -200)

    def test_refresh_jp_company_fundamental_jquants_is_skipped_without_credentials(self) -> None:
        with (
            patch("app.jp_market.service.settings.jquants_api_key", None),
            patch("app.jp_market.service.settings.jquants_id_token", None),
            patch("app.jp_market.service.settings.jquants_refresh_token", None),
            patch("app.jp_market.service.settings.jquants_mail_address", None),
            patch("app.jp_market.service.settings.jquants_password", None),
        ):
            result = refresh_jp_company_fundamental(
                db=self.db,
                symbol="7203",
                provider="jquants_statements",
            )

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["provider"], "jquants_statements")
        self.assertEqual(result["symbol"], "7203.T")
        self.assertEqual(result["fetched_count"], 0)

    def test_refresh_jp_market_resource_returns_structured_provider_limit(self) -> None:
        with (
            patch("app.jp_market.service.settings.jquants_api_key", "test-api-key"),
            patch(
                "app.jp_market.service.fetch_jquants_margin_interest_payload",
                side_effect=JPMarketDataFetchError("J-Quants margin-interest failed: HTTP 403."),
            ),
        ):
            result = refresh_jp_market_resource(
                db=self.db,
                symbol="7203",
                resource="demand",
            )

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["provider"], "jquants_margin_interest")
        self.assertIn("does not allow", result["message"])

    def test_refresh_jp_market_resource_returns_structured_rate_limit(self) -> None:
        with (
            patch("app.jp_market.service.settings.jquants_api_key", "test-api-key"),
            patch(
                "app.jp_market.service.fetch_jquants_margin_interest_payload",
                side_effect=JPMarketDataFetchError("J-Quants margin-interest failed: HTTP 429."),
            ),
        ):
            result = refresh_jp_market_resource(
                db=self.db,
                symbol="7203",
                resource="demand",
            )

        self.assertEqual(result["status"], "rate_limited")
        self.assertEqual(result["provider"], "jquants_margin_interest")
        self.assertIn("rate limit", result["message"])

    def test_jp_watchlist_daily_refresh_routes_are_registered(self) -> None:
        from app.main import app

        routes = {
            getattr(route, "path", ""): set(getattr(route, "methods", set()) or set())
            for route in app.routes
        }

        self.assertIn("POST", routes["/api/jp-market/watchlists/daily/refresh"])
        self.assertIn("POST", routes["/api/jp-market/resources/{symbol}/refresh"])
        self.assertIn("GET", routes["/api/jp-market/intraday/{symbol}"])
        self.assertIn("GET", routes["/api/jp-market/source-health"])
        self.assertIn("GET", routes["/api/jp-market/overview"])
        self.assertIn(
            "POST",
            routes["/api/jp-market/watchlists/groups/{group_id}/refresh-daily"],
        )


if __name__ == "__main__":
    unittest.main()
