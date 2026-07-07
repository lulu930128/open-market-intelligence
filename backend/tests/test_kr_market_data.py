from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, KRDailyPrice, KRIndexDailyPrice
from app.kr_market.schemas import (
    KRIndexOhlcChartRead,
    KRIndexIntradayTrendRead,
    KRIndexSummaryRead,
    KRWatchlistGroupCreate,
    KRWatchlistItemCreate,
    KRWatchlistReadinessRead,
)
from app.kr_market.service import (
    create_kr_watchlist_group,
    create_kr_watchlist_item,
    get_kr_index_summary,
    get_kr_index_intraday_trend,
    get_kr_market_breadth,
    get_kr_resource_summary,
    get_kr_watchlist_readiness,
    get_kr_watchlist_ranking,
    list_kr_index_ohlc_chart_data,
    list_kr_ohlc_chart_data,
    refresh_kr_company_fundamental,
    refresh_kr_watchlist_resources,
    sync_kr_index_master,
    upsert_kr_daily_price_records,
    upsert_kr_index_daily_price_records,
    upsert_kr_investor_trade_records,
    upsert_kr_stock_records,
)
from app.kr_market.source_health import build_kr_source_health
from app.kr_market.sources import (
    KRDailyPriceRecord,
    KRInvestorTradeRecord,
    KRMarketDataFetchError,
    normalize_kr_symbol,
    normalize_kr_index_id,
    parse_naver_index_daily_prices,
    parse_naver_index_intraday_points,
    parse_naver_index_realtime_quote,
    parse_krx_daily_price_records,
    parse_krx_investor_trade_records,
    parse_krx_stock_records,
    parse_opendart_company_fundamental_records,
    parse_yahoo_daily_prices,
    parse_yahoo_stock_record,
)
from app.main import app


def _seoul_timestamp(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, 15, 30, tzinfo=timezone(timedelta(hours=9))).timestamp())


YAHOO_KR_CHART_SAMPLE = {
    "chart": {
        "result": [
            {
                "meta": {
                    "symbol": "005930.KS",
                    "longName": "Samsung Electronics Co., Ltd.",
                    "fullExchangeName": "Korea Exchange",
                    "exchangeName": "KSC",
                    "instrumentType": "EQUITY",
                    "currency": "KRW",
                    "exchangeTimezoneName": "Asia/Seoul",
                    "gmtoffset": 32400,
                },
                "timestamp": [
                    _seoul_timestamp(2026, 6, 17),
                    _seoul_timestamp(2026, 6, 18),
                ],
                "indicators": {
                    "quote": [
                        {
                            "open": [71000.0, 72000.0],
                            "high": [73000.0, 73500.0],
                            "low": [70500.0, 71800.0],
                            "close": [72500.0, 73200.0],
                            "volume": [13500000, 14900000],
                        }
                    ],
                    "adjclose": [
                        {
                            "adjclose": [72500.0, 73200.0],
                        }
                    ],
                },
            }
        ],
        "error": None,
    }
}


KRX_STOCK_SAMPLE = {
    "OutBlock_1": [
        {
            "ISU_SRT_CD": "005930",
            "ISU_ABBRV": "Samsung Electronics",
            "ISU_NM": "삼성전자",
            "MKT_TP_NM": "KOSPI",
            "IDX_IND_NM": "Technology",
        },
        {
            "ISU_SRT_CD": "035720",
            "ISU_ABBRV": "Kakao",
            "ISU_NM": "카카오",
            "MKT_TP_NM": "KOSDAQ",
            "IDX_IND_NM": "Communication Services",
        },
    ]
}


KRX_DAILY_SAMPLE = {
    "OutBlock_1": [
        {
            "TRD_DD": "2026/06/18",
            "ISU_SRT_CD": "005930",
            "MKT_NM": "KOSPI",
            "TDD_OPNPRC": "72,000",
            "TDD_HGPRC": "73,500",
            "TDD_LWPRC": "71,800",
            "TDD_CLSPRC": "73,200",
            "CMPPREVDD_PRC": "+700",
            "FLUC_RT": "0.97",
            "ACC_TRDVOL": "14,900,000",
            "ACC_TRDVAL": "1,090,000,000,000",
            "MKTCAP": "437,000,000,000,000",
            "LIST_SHRS": "5,969,782,550",
        }
    ]
}


KRX_MARKET_BREADTH_SAMPLE = {
    "OutBlock_1": [
        {
            "TRD_DD": "2026/07/03",
            "ISU_SRT_CD": "005930",
            "MKT_NM": "KOSPI",
            "TDD_OPNPRC": "72,000",
            "TDD_HGPRC": "73,500",
            "TDD_LWPRC": "71,800",
            "TDD_CLSPRC": "73,200",
            "CMPPREVDD_PRC": "+700",
            "FLUC_RT": "0.97",
            "ACC_TRDVOL": "14,900,000",
            "ACC_TRDVAL": "1,090,000,000,000",
            "MKTCAP": "437,000,000,000,000",
            "LIST_SHRS": "5,969,782,550",
        },
        {
            "TRD_DD": "2026/07/03",
            "ISU_SRT_CD": "000660",
            "MKT_NM": "KOSPI",
            "TDD_OPNPRC": "242,000",
            "TDD_HGPRC": "244,000",
            "TDD_LWPRC": "238,000",
            "TDD_CLSPRC": "239,000",
            "CMPPREVDD_PRC": "-3,000",
            "FLUC_RT": "-1.24",
            "ACC_TRDVOL": "5,500,000",
            "ACC_TRDVAL": "1,300,000,000,000",
            "MKTCAP": "174,000,000,000,000",
            "LIST_SHRS": "728,000,000",
        },
        {
            "TRD_DD": "2026/07/03",
            "ISU_SRT_CD": "035720",
            "MKT_NM": "KOSDAQ",
            "TDD_OPNPRC": "50,000",
            "TDD_HGPRC": "51,000",
            "TDD_LWPRC": "49,500",
            "TDD_CLSPRC": "50,000",
            "CMPPREVDD_PRC": "0",
            "FLUC_RT": "0.00",
            "ACC_TRDVOL": "1,100,000",
            "ACC_TRDVAL": "55,000,000,000",
            "MKTCAP": "22,000,000,000,000",
            "LIST_SHRS": "440,000,000",
        },
    ]
}


OPENDART_FINANCIAL_SAMPLE = {
    "status": "000",
    "message": "정상",
    "list": [
        {
            "corp_code": "00126380",
            "corp_name": "Samsung Electronics",
            "stock_code": "005930",
            "bsns_year": "2025",
            "reprt_code": "11011",
            "reprt_nm": "Annual report",
            "sj_nm": "Statement of financial position",
            "account_id": "ifrs-full_Assets",
            "account_nm": "Assets",
            "thstrm_amount": "455,906,000,000,000",
            "frmtrm_amount": "426,621,000,000,000",
            "currency": "KRW",
            "rcept_no": "20260317000123",
            "rcept_dt": "2026-03-17",
        }
    ],
}


KRX_INVESTOR_SAMPLE = {
    "OutBlock_1": [
        {
            "TRD_DD": "2026/06/18",
            "INVST_TP_NM": "Foreigners",
            "ASK_TRDVAL": "210,000,000,000",
            "BID_TRDVAL": "180,000,000,000",
            "NETBID_TRDVAL": "30,000,000,000",
            "ASK_TRDVOL": "3000000",
            "BID_TRDVOL": "2600000",
            "NETBID_TRDVOL": "400000",
        }
    ]
}


NAVER_KR_INDEX_SAMPLE = """
 [['날짜', '시가', '고가', '저가', '종가', '거래량', '외국인소진율'],

["20260701", 3300.1, 3320.2, 3288.4, 3310.5, 468193, 0.0],
["20260702", 3312.0, 3340.8, 3301.2, 3333.4, 505157, 0.0],
["20260703", 3338.3, 3360.1, 3329.0, 3355.2, 465821, 0.0]
]
"""


NAVER_KR_INDEX_INTRADAY_SAMPLE = """
<html><body>
<table>
  <tr>
    <td class="date">15:32</td>
    <td class="number_1">7,656.31</td>
    <td class="rate_down"><span class="tah p11 nv01">395.02</span></td>
    <td class="number_1">81</td>
    <td class="number_1">512,294</td>
    <td class="number_1">39,659,682</td>
  </tr>
  <tr>
    <td class="date">15:30</td>
    <td class="number_1">7,655.92</td>
    <td class="rate_down"><span class="tah p11 nv01">395.41</span></td>
    <td class="number_1">11,865</td>
    <td class="number_1">512,213</td>
    <td class="number_1">39,654,556</td>
  </tr>
</table>
</body></html>
"""


NAVER_KR_INDEX_REALTIME_SAMPLE = {
    "resultCode": "success",
    "result": {
        "pollingInterval": 70000,
        "areas": [
            {
                "name": "SERVICE_INDEX",
                "datas": [
                    {
                        "ms": "CLOSE",
                        "nv": 765631,
                        "cv": -39502,
                        "cr": -4.91,
                        "rf": "5",
                        "ov": 791920,
                        "hv": 795455,
                        "lv": 738922,
                        "aq": 516366,
                        "aa": 40717403,
                        "bs": 0,
                        "cd": "KOSPI",
                    }
                ],
            }
        ],
        "time": 1783417654003,
    },
}


class KRMarketDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_normalize_kr_symbol_uses_local_code_suffixes(self) -> None:
        self.assertEqual(normalize_kr_symbol("005930"), "005930.KS")
        self.assertEqual(normalize_kr_symbol("5930"), "005930.KS")
        self.assertEqual(normalize_kr_symbol("KRX:005930"), "005930.KS")
        self.assertEqual(normalize_kr_symbol("035720.kq"), "035720.KQ")
        self.assertEqual(normalize_kr_index_id("KPI200"), "KOSPI200")

    def test_parse_krx_stock_records_and_daily_prices(self) -> None:
        stocks = parse_krx_stock_records(KRX_STOCK_SAMPLE)
        daily = parse_krx_daily_price_records(
            KRX_DAILY_SAMPLE,
            symbol="005930",
            source_url="https://data.krx.co.kr/example",
        )

        self.assertEqual(stocks[0].symbol, "005930.KS")
        self.assertEqual(stocks[0].security_name_kr, "삼성전자")
        self.assertEqual(stocks[1].symbol, "035720.KQ")
        self.assertEqual(daily[0].symbol, "005930.KS")
        self.assertEqual(daily[0].trade_date, date(2026, 6, 18))
        self.assertEqual(daily[0].close_price, 73200.0)
        self.assertEqual(daily[0].trade_volume, 14900000)

    def test_parse_yahoo_stock_record_and_daily_prices(self) -> None:
        stock = parse_yahoo_stock_record(YAHOO_KR_CHART_SAMPLE, symbol="005930")
        records = parse_yahoo_daily_prices(
            YAHOO_KR_CHART_SAMPLE,
            symbol="005930",
            source_url="https://query1.finance.yahoo.com/v8/finance/chart/005930.KS",
        )

        self.assertEqual(stock.symbol, "005930.KS")
        self.assertEqual(stock.local_code, "005930")
        self.assertEqual(stock.currency, "KRW")
        self.assertEqual(len(records), 2)
        self.assertEqual(records[-1].close_price, 73200.0)
        self.assertEqual(records[-1].trade_volume, 14900000)

    def test_parse_naver_index_daily_prices(self) -> None:
        records = parse_naver_index_daily_prices(
            NAVER_KR_INDEX_SAMPLE,
            index_id="KOSPI",
            source_url="https://api.finance.naver.com/siseJson.naver?symbol=KOSPI",
        )

        self.assertEqual(len(records), 3)
        self.assertEqual(records[0].index_id, "KOSPI")
        self.assertEqual(records[0].trade_date, date(2026, 7, 1))
        self.assertEqual(records[0].close_value, 3310.5)
        self.assertIsNone(records[0].price_change)
        self.assertAlmostEqual(records[1].price_change or 0, 22.90000000000009)
        self.assertEqual(records[-1].trade_volume, 465821)

    def test_parse_naver_index_intraday_points_and_realtime_quote(self) -> None:
        points = parse_naver_index_intraday_points(
            NAVER_KR_INDEX_INTRADAY_SAMPLE,
            index_id="KOSPI",
            thistime="20260707184700",
        )
        quote = parse_naver_index_realtime_quote(
            NAVER_KR_INDEX_REALTIME_SAMPLE,
            index_id="KOSPI",
        )

        self.assertEqual(len(points), 2)
        self.assertEqual(points[0].time.isoformat(), "2026-07-07T15:30:00+09:00")
        self.assertEqual(points[0].price, 7655.92)
        self.assertEqual(points[0].volume, 11865)
        self.assertEqual(points[-1].price, 7656.31)
        self.assertEqual(quote.price, 7656.31)
        self.assertEqual(quote.change, -395.02)
        self.assertEqual(quote.open_value, 7919.2)
        self.assertEqual(quote.polling_interval_seconds, 70)

    def test_get_kr_index_intraday_trend_uses_naver_points_and_realtime_reference(self) -> None:
        sync_kr_index_master(self.db)

        with (
            patch(
                "app.kr_market.service.fetch_naver_index_intraday_page_payload",
                return_value=(
                    NAVER_KR_INDEX_INTRADAY_SAMPLE,
                    "https://finance.naver.com/sise/sise_index_time.naver?code=KOSPI",
                ),
            ) as intraday_fetch,
            patch(
                "app.kr_market.service.fetch_naver_index_realtime_payload",
                return_value=(
                    NAVER_KR_INDEX_REALTIME_SAMPLE,
                    "https://polling.finance.naver.com/api/realtime?query=SERVICE_INDEX:KOSPI",
                ),
            ),
            patch(
                "app.kr_market.service._kr_index_intraday_thistime",
                return_value="20260707184700",
            ),
        ):
            result = get_kr_index_intraday_trend(
                self.db,
                index_id="KOSPI",
                refresh=True,
                max_pages=1,
            )

        self.assertEqual(result["stock_id"], "KOSPI")
        self.assertEqual(result["source"], "naver_index_time")
        self.assertEqual(result["point_count"], 3)
        self.assertAlmostEqual(result["previous_close"] or 0, 8051.33)
        self.assertEqual(result["polling_interval_seconds"], 70)
        self.assertEqual(intraday_fetch.call_count, 1)
        self.assertEqual(KRIndexIntradayTrendRead.model_validate(result).point_count, 3)

    def test_upsert_index_prices_summary_and_ohlc(self) -> None:
        sync_kr_index_master(self.db)
        records = parse_naver_index_daily_prices(NAVER_KR_INDEX_SAMPLE, index_id="KPI200")
        result = upsert_kr_index_daily_price_records(self.db, records)

        self.assertEqual(result["inserted_count"], 3)
        self.assertEqual(self.db.query(KRIndexDailyPrice).count(), 3)

        summary = get_kr_index_summary(
            self.db,
            expected_daily_date=date(2026, 7, 3),
        )
        chart = list_kr_index_ohlc_chart_data(
            self.db,
            index_id="KPI200",
            bars=5,
            to_date=date(2026, 7, 3),
        )

        kospi200 = next(row for row in summary["indices"] if row["index_id"] == "KOSPI200")
        self.assertEqual(kospi200["status"], "current")
        self.assertEqual(kospi200["close"], 3355.2)
        self.assertEqual(summary["summary"]["index_count"], 3)
        self.assertEqual(chart["index_id"], "KOSPI200")
        self.assertEqual(chart["name"], "KOSPI 200")
        self.assertEqual(chart["point_count"], 3)
        self.assertEqual(chart["points"][-1]["close"], 3355.2)
        self.assertEqual(KRIndexSummaryRead.model_validate(summary).summary.index_count, 3)
        self.assertEqual(KRIndexOhlcChartRead.model_validate(chart).point_count, 3)

    def test_kr_market_breadth_uses_public_daily_rows_by_index_segment(self) -> None:
        sync_kr_index_master(self.db)
        upsert_kr_daily_price_records(
            self.db,
            parse_krx_daily_price_records(
                KRX_MARKET_BREADTH_SAMPLE,
                source_url="https://data.krx.co.kr/example-market",
            ),
        )
        upsert_kr_index_daily_price_records(
            self.db,
            parse_naver_index_daily_prices(NAVER_KR_INDEX_SAMPLE, index_id="KOSPI"),
        )

        kospi = get_kr_market_breadth(self.db, index_id="KOSPI", trade_date=date(2026, 7, 3))
        kosdaq = get_kr_market_breadth(self.db, index_id="KOSDAQ", trade_date=date(2026, 7, 3))
        kospi200 = get_kr_market_breadth(self.db, index_id="KPI200", trade_date=date(2026, 7, 3))
        summary = get_kr_index_summary(
            self.db,
            expected_daily_date=date(2026, 7, 3),
        )
        kospi_summary = next(row for row in summary["indices"] if row["index_id"] == "KOSPI")

        self.assertEqual(kospi["advance_count"], 1)
        self.assertEqual(kospi["decline_count"], 1)
        self.assertEqual(kospi["unchanged_count"], 0)
        self.assertEqual(kospi["total_count"], 2)
        self.assertEqual(kospi["trade_value"], 2_390_000_000_000)
        self.assertEqual(kospi["positive_ratio"], 0.5)
        self.assertEqual(kosdaq["advance_count"], 0)
        self.assertEqual(kosdaq["decline_count"], 0)
        self.assertEqual(kosdaq["unchanged_count"], 1)
        self.assertEqual(kospi200["market_segment"], "KOSPI")
        self.assertIn("KOSPI 200", kospi200["coverage_note"] or "")
        self.assertEqual(kospi_summary["breadth"]["advance_count"], 1)
        self.assertEqual(KRIndexSummaryRead.model_validate(summary).indices[0].breadth.status, "current")

    def test_parse_opendart_and_investor_records(self) -> None:
        fundamentals = parse_opendart_company_fundamental_records(
            OPENDART_FINANCIAL_SAMPLE,
            symbol="005930",
            source_url="https://opendart.example.test",
        )
        investor_rows = parse_krx_investor_trade_records(
            KRX_INVESTOR_SAMPLE,
            symbol="005930",
            source_url="https://data.krx.example.test",
        )

        self.assertEqual(fundamentals[0].corp_code, "00126380")
        self.assertEqual(fundamentals[0].fiscal_year, 2025)
        self.assertEqual(fundamentals[0].current_amount, 455906000000000)
        self.assertEqual(investor_rows[0].investor_type, "Foreigners")
        self.assertEqual(investor_rows[0].net_buy_value, 30000000000)

    def test_upsert_daily_prices_resource_summary_and_ohlc(self) -> None:
        upsert_kr_stock_records(self.db, parse_krx_stock_records(KRX_STOCK_SAMPLE))
        records = parse_krx_daily_price_records(KRX_DAILY_SAMPLE, symbol="005930")
        result = upsert_kr_daily_price_records(self.db, records)

        self.assertEqual(result["inserted_count"], 1)
        self.assertEqual(self.db.query(KRDailyPrice).count(), 1)

        summary = get_kr_resource_summary(self.db, symbol="005930")
        chart = list_kr_ohlc_chart_data(
            self.db,
            symbol="005930",
            bars=5,
            to_date=date(2026, 6, 18),
        )

        self.assertEqual(summary["symbol"], "005930.KS")
        self.assertEqual(summary["slots"][0]["key"], "daily_price")
        self.assertTrue(summary["slots"][0]["available"])
        self.assertEqual(chart["point_count"], 1)
        self.assertEqual(chart["points"][0]["close"], 73200.0)

    def test_kr_source_health_summarizes_provider_freshness(self) -> None:
        upsert_kr_stock_records(self.db, parse_krx_stock_records(KRX_STOCK_SAMPLE))
        upsert_kr_daily_price_records(self.db, parse_krx_daily_price_records(KRX_DAILY_SAMPLE, symbol="005930"))

        health = build_kr_source_health(
            self.db,
            symbol="005930",
            expected_daily_price_date=date(2026, 6, 18),
        )
        daily_by_provider = {
            entry["provider"]: entry
            for entry in health["entries"]
            if entry["resource"] == "daily_price"
        }

        self.assertEqual(health["kind"], "kr_source_health")
        self.assertEqual(daily_by_provider["krx_data"]["status"], "current")
        self.assertEqual(daily_by_provider["yahoo_chart"]["status"], "empty")
        self.assertGreaterEqual(health["summary"]["entry_count"], 4)

    def test_refresh_fundamentals_skips_without_opendart_key(self) -> None:
        with patch("app.kr_market.service.settings.opendart_api_key", None):
            result = refresh_kr_company_fundamental(self.db, symbol="005930", corp_code="00126380")

        self.assertEqual(result["status"], "skipped")
        self.assertIn("OpenDART API key", result["message"])

    def test_watchlist_refresh_isolates_symbol_failures(self) -> None:
        upsert_kr_stock_records(self.db, parse_krx_stock_records(KRX_STOCK_SAMPLE))
        group = create_kr_watchlist_group(
            self.db,
            KRWatchlistGroupCreate(group_name="Korea"),
        )
        create_kr_watchlist_item(
            self.db,
            KRWatchlistItemCreate(group_id=group.id, symbol="005930"),
        )
        create_kr_watchlist_item(
            self.db,
            KRWatchlistItemCreate(group_id=group.id, symbol="035720.KQ"),
        )

        def fake_refresh(*, db, symbol, outputsize, provider, trade_date=None):
            if symbol == "035720.KQ":
                raise KRMarketDataFetchError("provider failed")
            return {
                "status": "success",
                "provider": provider,
                "symbol": symbol,
                "fetched_count": 1,
                "inserted_count": 1,
                "updated_count": 0,
                "message": "ok",
            }

        with patch("app.kr_market.service.refresh_kr_daily_prices", side_effect=fake_refresh):
            result = refresh_kr_watchlist_resources(
                self.db,
                group_id=group.id,
                include_investors=False,
                sleep_seconds=0,
            )

        self.assertEqual(result["status"], "partial_success")
        self.assertEqual(result["requested_symbol_count"], 2)
        self.assertEqual(result["refreshed_symbol_count"], 1)
        self.assertEqual(result["complete_symbol_count"], 1)
        self.assertEqual(result["failed_symbol_count"], 1)
        self.assertEqual(result["error_count"], 1)
        self.assertEqual(result["resource_attempt_count"], 2)
        self.assertEqual(result["resource_success_count"], 1)
        self.assertEqual(result["resource_error_count"], 1)

    def test_watchlist_refresh_includes_investors_and_respects_limit(self) -> None:
        upsert_kr_stock_records(self.db, parse_krx_stock_records(KRX_STOCK_SAMPLE))
        group = create_kr_watchlist_group(self.db, KRWatchlistGroupCreate(group_name="Korea"))
        create_kr_watchlist_item(self.db, KRWatchlistItemCreate(group_id=group.id, symbol="005930"))
        create_kr_watchlist_item(self.db, KRWatchlistItemCreate(group_id=group.id, symbol="035720.KQ"))

        daily_result = {
            "status": "success",
            "provider": "auto",
            "symbol": "005930.KS",
            "fetched_count": 1,
            "inserted_count": 1,
            "updated_count": 0,
            "message": "daily ok",
        }
        investor_result = {
            "status": "success",
            "provider": "krx_data",
            "symbol": "005930.KS",
            "fetched_count": 1,
            "inserted_count": 1,
            "updated_count": 0,
            "message": "investors ok",
        }

        with (
            patch("app.kr_market.service.refresh_kr_daily_prices", return_value=daily_result) as daily_refresh,
            patch("app.kr_market.service.refresh_kr_investor_trades_from_krx", return_value=investor_result) as investor_refresh,
        ):
            result = refresh_kr_watchlist_resources(
                self.db,
                group_id=group.id,
                include_investors=True,
                sleep_seconds=0,
                max_symbols=1,
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["total_symbol_count"], 2)
        self.assertEqual(result["requested_symbol_count"], 1)
        self.assertEqual(result["complete_symbol_count"], 1)
        self.assertEqual(result["partial_symbol_count"], 0)
        self.assertEqual(result["failed_symbol_count"], 0)
        self.assertEqual(result["resource_attempt_count"], 2)
        self.assertEqual(result["resource_success_count"], 2)
        self.assertTrue(result["include_investors"])
        self.assertEqual(result["results"][0]["daily"]["status"], "success")
        self.assertEqual(result["results"][0]["investors"]["status"], "success")
        self.assertEqual(daily_refresh.call_count, 1)
        self.assertEqual(investor_refresh.call_count, 1)

    def test_watchlist_readiness_summarizes_daily_and_investor_coverage(self) -> None:
        upsert_kr_stock_records(self.db, parse_krx_stock_records(KRX_STOCK_SAMPLE))
        group = create_kr_watchlist_group(self.db, KRWatchlistGroupCreate(group_name="Korea"))
        create_kr_watchlist_item(self.db, KRWatchlistItemCreate(group_id=group.id, symbol="005930"))
        upsert_kr_daily_price_records(self.db, parse_krx_daily_price_records(KRX_DAILY_SAMPLE, symbol="005930"))
        upsert_kr_investor_trade_records(
            self.db,
            [
                KRInvestorTradeRecord(
                    provider="krx_data",
                    symbol="005930.KS",
                    trade_date=date(2026, 6, 18),
                    investor_type="Foreigners",
                    buy_value=180000000000,
                    sell_value=210000000000,
                    net_buy_value=30000000000,
                    buy_volume=2600000,
                    sell_volume=3000000,
                    net_buy_volume=400000,
                    source_url="https://data.krx.example.test",
                    raw_payload_hash="investor-a",
                )
            ],
        )

        readiness = get_kr_watchlist_readiness(
            self.db,
            group_id=group.id,
            expected_daily_date=date(2026, 6, 18),
        )

        self.assertEqual(readiness["kind"], "kr_watchlist_readiness")
        self.assertEqual(readiness["summary"]["requested_symbol_count"], 1)
        self.assertEqual(readiness["summary"]["ready_count"], 1)
        self.assertEqual(readiness["summary"]["daily_current_count"], 1)
        self.assertEqual(readiness["summary"]["investor_available_count"], 1)
        self.assertEqual(readiness["results"][0]["readiness_status"], "ready")
        self.assertIn("financials", readiness["results"][0]["missing_resources"])
        validated = KRWatchlistReadinessRead.model_validate(readiness)
        self.assertEqual(validated.summary.ready_count, 1)

    def test_watchlist_ranking_uses_latest_two_daily_rows(self) -> None:
        upsert_kr_stock_records(self.db, parse_krx_stock_records(KRX_STOCK_SAMPLE))
        group = create_kr_watchlist_group(self.db, KRWatchlistGroupCreate(group_name="Korea"))
        create_kr_watchlist_item(self.db, KRWatchlistItemCreate(group_id=group.id, symbol="005930"))
        upsert_kr_daily_price_records(
            self.db,
            [
                KRDailyPriceRecord(
                    provider="krx_data",
                    symbol="005930.KS",
                    trade_date=date(2026, 6, 17),
                    currency="KRW",
                    open_price=71000.0,
                    high_price=73000.0,
                    low_price=70500.0,
                    close_price=72500.0,
                    adjusted_close=None,
                    price_change=None,
                    change_pct=None,
                    trade_volume=13500000,
                    trade_value=None,
                    market_cap=None,
                    listed_shares=None,
                    source_url=None,
                    raw_payload_hash="a",
                ),
                KRDailyPriceRecord(
                    provider="krx_data",
                    symbol="005930.KS",
                    trade_date=date(2026, 6, 18),
                    currency="KRW",
                    open_price=72000.0,
                    high_price=73500.0,
                    low_price=71800.0,
                    close_price=73200.0,
                    adjusted_close=None,
                    price_change=None,
                    change_pct=None,
                    trade_volume=14900000,
                    trade_value=None,
                    market_cap=None,
                    listed_shares=None,
                    source_url=None,
                    raw_payload_hash="b",
                ),
            ],
        )

        ranking = get_kr_watchlist_ranking(self.db, group_id=group.id, rank_by="change_pct", sort_order="desc")

        self.assertEqual(ranking["ranked_count"], 1)
        self.assertEqual(ranking["results"][0]["symbol"], "005930.KS")
        self.assertAlmostEqual(ranking["results"][0]["change_pct"], 0.9655172413793104)

    def test_kr_routes_are_registered(self) -> None:
        matching_paths = {getattr(route, "path", None) for route in app.routes}

        self.assertIn("/api/kr-market/source-health", matching_paths)
        self.assertIn("/api/kr-market/market-breadth/refresh", matching_paths)
        self.assertIn("/api/kr-market/indices/summary", matching_paths)
        self.assertIn("/api/kr-market/indices/{index_id}/breadth", matching_paths)
        self.assertIn("/api/kr-market/indices/{index_id}/intraday", matching_paths)
        self.assertIn("/api/kr-market/indices/{index_id}/ohlc", matching_paths)
        self.assertIn("/api/kr-market/indices/{index_id}/refresh", matching_paths)
        self.assertIn("/api/kr-market/daily/{symbol}/refresh", matching_paths)
        self.assertIn("/api/kr-market/watchlists/readiness", matching_paths)
        self.assertIn("/api/kr-market/watchlists/resources/refresh", matching_paths)


if __name__ == "__main__":
    unittest.main()
