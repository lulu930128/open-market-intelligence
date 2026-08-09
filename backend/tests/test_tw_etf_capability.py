from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    Base,
    MarketDailyPrice,
    RawFetchResult,
    SourceRegistry,
    StockMaster,
    TaiwanEtfInavSnapshot,
    TaiwanEtfNavDaily,
    TaiwanEtfPcfComponent,
    TaiwanEtfPcfSnapshot,
    TaiwanEtfProfile,
    WatchlistGroup,
    WatchlistItem,
)
from app.market.providers.tw_etf import (
    TaiwanEtfNavRecord,
    TaiwanEtfProfileRecord,
    TaiwanEtfProviderError,
    parse_mops_etf_nav_html,
    parse_twse_etf_profiles,
)
from app.market.providers.tw_etf_contracts import (
    TaiwanEtfInstrumentIdentity,
    TaiwanEtfPcfProviderResource,
    TaiwanEtfProviderBinding,
)
from app.market.providers.tw_etf_capital import (
    CAPITAL_PROVIDER,
    TaiwanEtfCapitalProviderError,
    fetch_capital_etf_inav,
    parse_capital_etf_inav_payload,
)
from app.market.providers.tw_etf_cathay import (
    CATHAY_PROVIDER,
    TaiwanEtfCathayProviderError,
    fetch_cathay_etf_inav,
    fetch_cathay_etf_pcf,
    parse_cathay_etf_inav_payload,
    parse_cathay_etf_list_payload,
    parse_cathay_etf_pcf_html,
)
from app.market.providers.tw_etf_fubon import (
    FUBON_INAV_URL,
    FUBON_PROVIDER,
    TaiwanEtfFubonProviderError,
    fetch_fubon_etf_inav,
    fetch_fubon_etf_pcf,
    parse_fubon_etf_inav_html,
    parse_fubon_etf_pcf_html,
)
from app.market.providers.tw_etf_fuh_hwa import (
    FUH_HWA_PROVIDER,
    TaiwanEtfFuhHwaProviderError,
    fetch_fuh_hwa_etf_inav,
    parse_fuh_hwa_etf_inav_html,
)
from app.market.providers.tw_etf_issuers import (
    DEFAULT_TAIWAN_ETF_ISSUER_CATALOG,
    canonicalize_taiwan_etf_identity,
)
from app.market.providers.tw_etf_registry import (
    DEFAULT_TAIWAN_ETF_PROVIDER_REGISTRY,
    TaiwanEtfProviderRegistry,
)
from app.market.providers.tw_etf_nomura import (
    NOMURA_PROVIDER,
    TaiwanEtfNomuraProviderError,
    fetch_nomura_etf_inav,
    parse_nomura_etf_inav_payload,
)
from app.market.providers.tw_etf_upamc import (
    UPAMC_PROVIDER,
    TaiwanEtfUpamcProviderError,
    fetch_upamc_etf_pcf,
    parse_upamc_etf_pcf_payload,
    parse_upamc_pcf_page,
)
from app.market.providers.tw_etf_yuanta import (
    TaiwanEtfInavRecord,
    TaiwanEtfPcfComponentRecord,
    TaiwanEtfPcfRecord,
    TaiwanEtfYuantaProviderError,
    fetch_yuanta_etf_inav,
    parse_yuanta_etf_inav_payload,
    parse_yuanta_etf_pcf_payload,
)
import app.market.tw_etf as tw_etf_service
from app.market.tw_etf import get_taiwan_etf_overview, refresh_taiwan_etf
from app.market.tw_etf_schemas import TaiwanEtfOverviewRead
from app.watchlists.service import _item_to_dict


TAIWAN_TZ = ZoneInfo("Asia/Taipei")


class TaiwanEtfProviderParserTests(unittest.TestCase):
    CATHAY_PCF_HTML = """
        <html>
          <head><title>00878 國泰永續高股息－申購買回清單｜國泰投信</title></head>
          <body>
            <input value="2026-08-10" />
            <div class="li"><h3 class="table-subtitle">基金淨資產價值(元)</h3><p>NT$ 606,661,506,476</p></div>
            <div class="li"><h3 class="table-subtitle">預收申購總價金(元)</h3><p>NT$ 18,041,000</p></div>
            <div class="li"><h3 class="table-subtitle">已發行受益權單位總數</h3><p>18,520,790,000</p></div>
            <div class="li"><h3 class="table-subtitle">與前日已發行單位差異數</h3><p>16,000,000</p></div>
            <div class="li"><h3 class="table-subtitle">2026/08/07 每受益權單位淨資產價值(元)</h3><p>NT$ 32.76</p></div>
            <div class="li"><h3 class="table-subtitle">每現金申購/買回基數之受益權單位數</h3><p>500,000</p></div>
            <div class="li"><h3 class="table-subtitle">2026/08/07 每現金申購/買回基數估計現金差額(元)</h3><p>NT$ 503,050</p></div>
          </body>
        </html>
    """
    FUBON_PCF_HTML = """
        <input id="mainContent_subMainContent_hidStkId" value="006208" />
        <input id="mainContent_subMainContent_sDate" value="2026/08/09" />
        <h6 class="top blue3 mb25">006208 FB TW50</h6>
        <ul class="w3-row mb20">
          <li><h6>Portfolio Composition File</h6></li>
          <li>2026/08/10</li>
        </ul>
        <div class="fund_box_2">
          <li><p>Net Asset Value(NAV)</p><p>NT$437,906,638,802</p></li>
          <li><p>Total Units Outstanding</p><p>1,860,040,000</p></li>
          <li><p>Net Unit Change</p><p>0</p></li>
          <li><p>NAV Per Unit</p><p>NT$235.43</p></li>
          <li><p>Creation/Redemption Unit</p><p>500,000</p></li>
          <li><p>Cash Component Per Basket</p><p>NT$-9,772,979</p></li>
          <li><p>Price per creation basket</p><p>NT$117,837,021</p></li>
        </div>
    """
    FUBON_INAV_HTML = """
        <div class="con_c1_cardbox1">
          <div class="card_name">006208&nbsp;富邦台50<br />(收益平準金揭露)</div>
          <div class="card_time">資料時間：2026/08/07 17:05:00</div>
          <table class="w674">
            <tr>
              <td class="card_price">市價</td>
              <td class="card_price3"><span class="spacer12">235.35</span></td>
              <td class="card_price4"><span>漲跌</span><span>-1.20</span><span>(-0.51%)</span></td>
            </tr>
            <tr>
              <td class="card_price">淨值</td>
              <td class="card_price3"><span class="spacer12">235.43</span></td>
              <td class="card_price4"><span>漲跌</span><span>-0.65</span><span>(-0.28%)</span></td>
            </tr>
          </table>
          <div class="card_price5"><span>-0.03%</span></div>
        </div>
    """

    def test_parse_twse_profile_uses_official_fields(self) -> None:
        records = parse_twse_etf_profiles(
            [
                {
                    "出表日期": "1150808",
                    "基金代號": "0050",
                    "基金簡稱": "元大台灣50",
                    "基金類型": "國內成分證券指數股票型基金",
                    "基金中文名稱": "元大台灣卓越50證券投資信託基金",
                    "基金英文名稱": "Yuanta Taiwan Top 50 ETF",
                    "標的指數/追蹤指數名稱": "臺灣50指數",
                    "標的指數是否為客製化或需揭露相關資訊之指數": "否",
                    "股票及債券投資比例說明": "股票投資",
                    "是否設有績效指標": "是",
                    "績效指標中文名稱": "臺灣50指數",
                    "是否包含國外成分股": "否",
                    "基金統一編號": "00938563",
                    "成立日期": "0920625",
                    "上市日期": "0920630",
                    "基金經理人": "測試經理人",
                    "發行單位數/轉換數": "1,234,000",
                    "保管機構": "測試銀行",
                }
            ]
        )

        record = records[0]
        self.assertEqual(record.stock_id, "0050")
        self.assertEqual(record.report_date, date(2026, 8, 8))
        self.assertEqual(record.listed_date, date(2003, 6, 30))
        self.assertEqual(record.issued_units, 1_234_000)
        self.assertFalse(record.has_foreign_components)

    def test_parse_mops_nav_and_benchmark_rows(self) -> None:
        html = """
        <table class="hasBorder">
          <tr><th>投信公司</th><th>代號</th><th>名稱</th><th>日期</th></tr>
          <tr>
            <td rowspan="2">元大證券投資信託股份有限公司</td>
            <td>0050</td><td>元大台灣50</td><td>115/08/07</td>
            <td>102.76000</td><td>103.04000</td><td>-0.28000</td>
            <td>-0.27%</td><td>102.85</td><td>0.09%</td>
          </tr>
          <tr>
            <td>臺灣50指數</td><td>115/08/07</td><td>41098.32</td>
            <td>41212.45</td><td>-114.13</td><td>-0.28%</td>
          </tr>
        </table>
        """

        record = parse_mops_etf_nav_html(html)[0]
        self.assertEqual(record.stock_id, "0050")
        self.assertEqual(record.nav_date, date(2026, 8, 7))
        self.assertEqual(record.nav, Decimal("102.76000"))
        self.assertEqual(record.premium_discount_pct, Decimal("0.09"))
        self.assertEqual(record.benchmark_name, "臺灣50指數")
        self.assertEqual(record.benchmark_close, Decimal("41098.32"))

    def test_mops_schema_drift_is_explicit(self) -> None:
        with self.assertRaises(TaiwanEtfProviderError):
            parse_mops_etf_nav_html("<html><body>unexpected response</body></html>")

    def test_mops_malformed_issuer_rows_preserve_all_fund_codes(self) -> None:
        html = """
        <table class="hasBorder">
          <tr class="odd">
            <td rowspan="8">元大證券投資信託股份有限公司</td>
            <td rowspan="4">0050</td>
            <th>基金名稱</th><th>淨值日期</th><th>淨值</th>
            <th>前一日淨值</th><th>淨值漲跌</th><th>淨值漲跌%</th>
            <th>市價</th><th>折溢價%</th>
          </tr>
          <tr class="odd">
            <td>元大台灣50</td><td>2026/08/07</td>
            <td>102.76000</td><td>103.04000</td><td>-0.28000</td>
            <td>-0.27</td><td>102.85</td><td>0.09</td>
          </tr>
          <tr><th>指數名稱</th><th>指數日期</th><th>指數</th><th>前一日指數</th><th>漲跌</th><th>漲跌%</th></tr>
          <tr><td>臺灣50指數</td><td>2026/08/07</td><td>41098.32</td><td>41212.45</td><td>-114.13</td><td>-0.28</td></tr>
          <td rowspan="4">0056</td>
          <th>基金名稱</th><th>淨值日期</th><th>淨值</th>
          <th>前一日淨值</th><th>淨值漲跌</th><th>淨值漲跌%</th>
          <th>市價</th><th>折溢價%</th>
          </tr>
          <tr class="odd">
            <td>元大高股息</td><td>2026/08/07</td>
            <td>36.12000</td><td>36.30000</td><td>-0.18000</td>
            <td>-0.50</td><td>36.15</td><td>0.08</td>
          </tr>
          <tr><th>指數名稱</th><th>指數日期</th><th>指數</th><th>前一日指數</th><th>漲跌</th><th>漲跌%</th></tr>
          <tr><td>臺灣高股息指數</td><td>2026/08/07</td><td>9123.45</td><td>9168.90</td><td>-45.45</td><td>-0.50</td></tr>
        </table>
        """

        records = parse_mops_etf_nav_html(html)

        self.assertEqual([record.stock_id for record in records], ["0050", "0056"])
        self.assertEqual(records[1].issuer_name, "元大證券投資信託股份有限公司")
        self.assertEqual(records[1].nav, Decimal("36.12000"))
        self.assertEqual(records[1].benchmark_name, "臺灣高股息指數")

    def test_parse_yuanta_pcf_preserves_in_kind_basket_semantics(self) -> None:
        record = parse_yuanta_etf_pcf_payload(
            {
                "PCF": {
                    "fundid": "1066",
                    "fundname": "元大台灣卓越50基金",
                    "fullname": "元大台灣卓越50證券投資信託基金",
                    "ename": "Yuanta/P-shares Taiwan Top 50 ETF",
                    "markcd": "0050",
                    "trandate": "20260807",
                    "anndate": "20260810",
                    "totalav": 2305206923456,
                    "osunit": 22433000000,
                    "nav": 102.76,
                    "baseunit": 500000,
                    "estcvalue": 51379818,
                    "estdvalue": 51496,
                    "issuesdiff": 0,
                    "cashdiff": 52052,
                    "upddate": "2026-08-07 15:47:38",
                },
                "InKind": {
                    "FundComposition": [
                        {
                            "stkcd": "1216",
                            "name": "統一",
                            "ename": "UNI-PRESIDENT ENTERPRISES CORP.",
                            "qty": 2581,
                            "cashinlieu": "N",
                            "minimum": "Y",
                        }
                    ]
                },
                "FundWeights": {
                    "StockWeights": [
                        {"code": "1216", "name": "統一", "weights": 1.2, "qty": 2581}
                    ],
                    "FutureWeights": [],
                    "ETFWeights": [],
                    "BondWeights": [],
                },
            },
            "0050",
        )

        self.assertEqual(record.effective_date, date(2026, 8, 10))
        self.assertEqual(record.reference_date, date(2026, 8, 7))
        self.assertEqual(record.redemption_method, "in_kind")
        self.assertEqual(record.creation_unit, 500_000)
        self.assertEqual(len(record.components), 1)
        self.assertEqual(record.components[0].asset_type, "stock")
        self.assertEqual(record.components[0].quantity, Decimal("2581"))
        self.assertTrue(record.components[0].minimum_creation)

    def test_parse_yuanta_pcf_preserves_cash_and_derivative_exposure(self) -> None:
        record = parse_yuanta_etf_pcf_payload(
            {
                "PCF": {
                    "markcd": "00940",
                    "trandate": "20260807",
                    "anndate": "20260810",
                    "upddate": "2026-08-07 16:37:31",
                },
                "InKind": {"FundComposition": []},
                "FundWeights": {
                    "StockWeights": [
                        {"code": "2357", "name": "華碩", "weights": 5.13, "qty": 4182000}
                    ],
                    "FutureWeights": [
                        {
                            "code": "TX",
                            "ym": "202608",
                            "name": "臺股期貨",
                            "weights": 1.36,
                            "qty": 102,
                        }
                    ],
                    "ETFWeights": [],
                    "BondWeights": [],
                },
            },
            "00940",
        )

        self.assertEqual(record.redemption_method, "cash")
        self.assertEqual([item.asset_type for item in record.components], ["stock", "future"])
        self.assertEqual(record.components[1].contract_month, "202608")
        self.assertEqual(record.components[1].weight_pct, Decimal("1.36"))

    def test_parse_yuanta_inav_uses_source_timestamp_and_computes_premium(self) -> None:
        record = parse_yuanta_etf_inav_payload(
            {
                "M": [
                    {
                        "H": "CompareHub",
                        "M": "CompareData",
                        "A": [
                            [
                                {
                                    "etfId": "0050",
                                    "FUND_SH_NAME": "元大台灣卓越50基金",
                                    "ETFSet": {
                                        "invArea": "D",
                                        "nowNav": 102.76,
                                        "navFluct": -0.28,
                                        "nowPrice": 102.85,
                                        "priceFluct": -0.45,
                                        "updateT": "2026-08-10 09:29:30",
                                    },
                                }
                            ]
                        ],
                    }
                ]
            },
            "0050",
        )

        self.assertEqual(record.estimated_nav, Decimal("102.76"))
        self.assertEqual(record.market_price, Decimal("102.85"))
        self.assertEqual(record.observed_at.astimezone(TAIWAN_TZ).hour, 9)
        self.assertEqual(
            record.premium_discount_pct.quantize(Decimal("0.000001")),
            Decimal("0.087583"),
        )

    def test_yuanta_inav_signalr_fetch_is_bounded_to_five_requests(self) -> None:
        inav_payload = {
            "M": [
                {
                    "H": "CompareHub",
                    "M": "CompareData",
                    "A": [
                        [
                            {
                                "etfId": "0050",
                                "ETFSet": {
                                    "nowNav": 102.76,
                                    "nowPrice": 102.85,
                                    "updateT": "2026-08-10 09:29:30",
                                },
                            }
                        ]
                    ],
                }
            ]
        }

        class FakeResponse:
            status_code = 200
            headers: dict[str, str] = {"Content-Type": "application/json"}

            def __init__(self, payload: dict) -> None:
                self.payload = payload

            def json(self) -> dict:
                return self.payload

        class FakeSession:
            def __init__(self) -> None:
                self.calls: list[tuple[str, str, int]] = []
                self.closed = False

            def request(self, method: str, url: str, *, timeout: int, **_: object) -> FakeResponse:
                self.calls.append((method, url, timeout))
                if url.endswith("/negotiate"):
                    return FakeResponse({"ConnectionToken": "token"})
                if url.endswith("/connect"):
                    return FakeResponse({"C": "message-id", "M": []})
                if url.endswith("/start"):
                    return FakeResponse({"Response": "started"})
                if url.endswith("/send"):
                    return FakeResponse({"I": "0"})
                if url.endswith("/poll"):
                    return FakeResponse(inav_payload)
                raise AssertionError(url)

            def close(self) -> None:
                self.closed = True

        session = FakeSession()
        record = fetch_yuanta_etf_inav("0050", session_factory=lambda: session)

        self.assertEqual(record.stock_id, "0050")
        self.assertEqual(len(session.calls), 5)
        self.assertTrue(all(timeout == 10 for _, _, timeout in session.calls))
        self.assertTrue(session.closed)

    def test_yuanta_schema_drift_is_explicit(self) -> None:
        with self.assertRaises(TaiwanEtfYuantaProviderError):
            parse_yuanta_etf_pcf_payload({}, "0050")
        with self.assertRaises(TaiwanEtfYuantaProviderError):
            parse_yuanta_etf_inav_payload({"M": []}, "0050")

    def test_parse_fubon_pcf_preserves_summary_without_claiming_components(self) -> None:
        record = parse_fubon_etf_pcf_html(self.FUBON_PCF_HTML, "006208")

        self.assertEqual(record.effective_date, date(2026, 8, 10))
        self.assertEqual(record.reference_date, date(2026, 8, 9))
        self.assertEqual(record.unit_nav, Decimal("235.43"))
        self.assertEqual(record.creation_unit, 500_000)
        self.assertEqual(record.estimated_creation_value, Decimal("117837021"))
        self.assertEqual(record.estimated_cash_component, Decimal("-9772979"))
        self.assertEqual(record.redemption_method, "unknown")
        self.assertEqual(record.components, ())

    def test_parse_fubon_inav_uses_source_timestamp_and_premium(self) -> None:
        record = parse_fubon_etf_inav_html(self.FUBON_INAV_HTML, "006208")

        self.assertEqual(record.fund_short_name, "富邦台50")
        self.assertEqual(record.estimated_nav, Decimal("235.43"))
        self.assertEqual(record.market_price, Decimal("235.35"))
        self.assertEqual(record.premium_discount_pct, Decimal("-0.03"))
        self.assertEqual(record.observed_at.isoformat(), "2026-08-07T17:05:00+08:00")

    def test_fubon_html_fetchers_are_bounded_to_one_request_each(self) -> None:
        calls: list[tuple[str, str]] = []

        class Response:
            def __init__(self, html: str) -> None:
                self.content = html.encode("utf-8")

            @staticmethod
            def raise_for_status() -> None:
                return None

        def request_get(url: str, **kwargs):
            calls.append((url, kwargs["resource"]))
            html = (
                self.FUBON_PCF_HTML
                if kwargs["resource"] == "etf_pcf"
                else self.FUBON_INAV_HTML
            )
            return Response(html)

        pcf = fetch_fubon_etf_pcf("006208", request_get=request_get)
        inav = fetch_fubon_etf_inav("006208", request_get=request_get)

        self.assertEqual(pcf.stock_id, "006208")
        self.assertEqual(inav.stock_id, "006208")
        self.assertEqual(
            [resource for _, resource in calls],
            ["etf_pcf", "etf_intraday_estimated_nav"],
        )

    def test_fubon_schema_drift_is_explicit(self) -> None:
        with self.assertRaises(TaiwanEtfFubonProviderError):
            parse_fubon_etf_pcf_html("<html></html>", "006208")
        with self.assertRaises(TaiwanEtfFubonProviderError):
            parse_fubon_etf_inav_html("<html></html>", "006208")

    def test_parse_cathay_inav_resolves_internal_fund_code_first(self) -> None:
        fund_code, short_name = parse_cathay_etf_list_payload(
            {
                "success": True,
                "returnCode": "2000",
                "result": [
                    {
                        "fundCode": "CN",
                        "stockCode": "00878",
                        "stockShortNameFix": "國泰永續高股息",
                    }
                ],
            },
            "00878",
        )
        record = parse_cathay_etf_inav_payload(
            {
                "success": True,
                "returnCode": "2000",
                "result": {
                    "預估淨值": "32.76",
                    "最新市價": "32.81",
                    "淨值漲跌": "0.02",
                    "市價漲跌": "-0.03",
                    "時間": "2026/08/07 16:59:47",
                },
            },
            "00878",
            fund_short_name=short_name,
        )

        self.assertEqual(fund_code, "CN")
        self.assertEqual(record.estimated_nav, Decimal("32.76"))
        self.assertEqual(record.fund_short_name, "國泰永續高股息")
        self.assertEqual(record.observed_at.isoformat(), "2026-08-07T16:59:47+08:00")

    def test_parse_cathay_pcf_preserves_cash_subscription_semantics(self) -> None:
        record = parse_cathay_etf_pcf_html(
            self.CATHAY_PCF_HTML,
            "00878",
            fund_code="CN",
            fund_short_name="國泰永續高股息",
        )

        self.assertEqual(record.fund_id, "CN")
        self.assertEqual(record.reference_date, date(2026, 8, 7))
        self.assertEqual(record.effective_date, date(2026, 8, 10))
        self.assertEqual(record.total_net_assets, Decimal("606661506476"))
        self.assertEqual(record.issued_units, 18_520_790_000)
        self.assertEqual(record.unit_nav, Decimal("32.76"))
        self.assertEqual(record.creation_unit, 500_000)
        self.assertEqual(record.estimated_creation_value, Decimal("18041000"))
        self.assertEqual(record.estimated_cash_component, Decimal("503050"))
        self.assertEqual(record.redemption_method, "cash")
        self.assertEqual(record.components, ())

    def test_parse_capital_inav_preserves_official_diff_ratio(self) -> None:
        record = parse_capital_etf_inav_payload(
            {
                "code": 200,
                "data": [
                    {
                        "fundId": "195",
                        "stocNo": "00919",
                        "stocSname": "群益台灣精選高息",
                        "date1": "2026/08/07",
                        "time1": "15:00:00",
                        "nav": 29.76,
                        "navChange": "0.250000",
                        "price": "29.740000",
                        "priceChange": "0.140000",
                        "diffRatio": "-0.067204",
                    }
                ],
            },
            "00919",
        )

        self.assertEqual(record.estimated_nav, Decimal("29.76"))
        self.assertEqual(record.market_price, Decimal("29.740000"))
        self.assertEqual(record.premium_discount_pct, Decimal("-0.067204"))

    def test_parse_fuh_hwa_inav_uses_only_estimate_cards(self) -> None:
        html = """
        <div class="fundCard" data-type="etf">
          <p class="fundCard-code">00929</p>
        </div>
        <div class="fundCard" data-type="etfnet">
          <p class="fundCard-code">00929</p>
          <a class="fundCard-fundName">復華台灣科技優息ETF基金</a>
          <div class="fundCard-date">2026/08/07 15:00:30</div>
          <div class="fundCard-state">
            <div class="row">
              <div class="fundCard-stateName">預估淨值/漲跌幅</div>
              <span class="fundFluctuate">28.54</span><span class="fundFluctuate">-1.31%</span>
            </div>
            <div class="row">
              <div class="fundCard-stateName">最新市價/漲跌幅</div>
              <span class="fundFluctuate">28.58</span><span class="fundFluctuate">-1.21%</span>
            </div>
            <div class="row">
              <div class="fundCard-stateName">折溢價率</div>
              <span class="fundFluctuate">0.14%</span>
            </div>
          </div>
        </div>
        """

        record = parse_fuh_hwa_etf_inav_html(html, "00929")

        self.assertEqual(record.estimated_nav, Decimal("28.54"))
        self.assertEqual(record.market_price, Decimal("28.58"))
        self.assertEqual(record.premium_discount_pct, Decimal("0.14"))
        self.assertEqual(record.nav_change, None)

    def test_parse_nomura_inav_computes_absolute_changes(self) -> None:
        record = parse_nomura_etf_inav_payload(
            {
                "StatusCode": 0,
                "Entries": [
                    {
                        "CDataDt": "2026/08/07 17:20:50",
                        "CStockNo": "00980A",
                        "CFundShortName": "主動野村臺灣優選",
                        "CLastDayNav": 23.76,
                        "CEstimateNav": 23.55,
                        "CLastDayMarketPrice": 23.73,
                        "CLatestMarketPrice": 23.57,
                        "CDiffPct": 0.0849,
                    }
                ],
            },
            "00980A",
        )

        self.assertEqual(record.nav_change, Decimal("-0.21"))
        self.assertEqual(record.price_change, Decimal("-0.16"))
        self.assertEqual(record.premium_discount_pct, Decimal("0.0849"))

    def test_parse_upamc_pcf_keeps_summary_separate_from_asset_holdings(self) -> None:
        fund_code, default_date = parse_upamc_pcf_page(
            """
            <a href="/ETF/Fund/Info?fundCode=36YTW">00757 統一FANG+</a>
            <input id="ED" value="115/08/10" />
            """,
            "00757",
        )
        record = parse_upamc_etf_pcf_payload(
            {
                "fund": {
                    "sFundCode": "36YTW",
                    "sFundName": "統一NYSE FANG+ETF基金",
                    "sStockNo": "00757 ",
                },
                "pcf": [
                    {
                        "PCFCode": "PRE_AMT",
                        "Amount": 76850000,
                        "TranDate": "2026-08-06T00:00:00",
                        "PostDate": "2026-08-10T00:00:00",
                        "EditDate": "2026-08-07T15:34:25",
                    },
                    {"PCFCode": "NAV", "Amount": 40378493173},
                    {"PCFCode": "OUT_UNIT", "Amount": 288994000},
                    {"PCFCode": "DIFF_UNIT", "Amount": 0},
                    {"PCFCode": "P_UNIT", "Amount": 139.72},
                    {"PCFCode": "FUND_BASEUNIT", "Amount": 500000},
                    {"PCFCode": "DIFF_ACT_AMT", "Amount": -8060100},
                ],
                "asset": [{"AssetCode": "ST", "Details": [{"DetailCode": "MSFT US"}]}],
            },
            "00757",
        )

        self.assertEqual(fund_code, "36YTW")
        self.assertEqual(default_date, "115/08/10")
        self.assertEqual(record.effective_date, date(2026, 8, 10))
        self.assertEqual(record.creation_unit, 500_000)
        self.assertEqual(record.estimated_creation_value, Decimal("76850000"))
        self.assertIsNone(record.estimated_cash_component)
        self.assertEqual(record.components, ())

    def test_major_issuer_fetchers_keep_bounded_request_counts(self) -> None:
        cathay_calls: list[str] = []

        class JsonResponse:
            def __init__(self, payload: dict) -> None:
                self.payload = payload

            @staticmethod
            def raise_for_status() -> None:
                return None

            def json(self) -> dict:
                return self.payload

        class CathayHtmlResponse:
            encoding = "utf-8"
            text = self.CATHAY_PCF_HTML

            @staticmethod
            def raise_for_status() -> None:
                return None

        def cathay_get(url: str, **kwargs: object):
            cathay_calls.append(url)
            if "GetETFList" in url:
                return JsonResponse(
                    {
                        "success": True,
                        "returnCode": "2000",
                        "result": [
                            {
                                "fundCode": "CN",
                                "stockCode": "00878",
                                "stockShortNameFix": "國泰永續高股息",
                            }
                        ],
                    }
                )
            if kwargs.get("resource") == "etf_pcf":
                return CathayHtmlResponse()
            return JsonResponse(
                {
                    "success": True,
                    "returnCode": "2000",
                    "result": {"預估淨值": 32.76, "時間": "2026/08/07 16:59:47"},
                }
            )

        fetch_cathay_etf_pcf("00878", request_get=cathay_get)
        fetch_cathay_etf_inav("00878", request_get=cathay_get)
        self.assertEqual(len(cathay_calls), 4)

        capital_calls: list[str] = []

        def capital_post(url: str, **_: object) -> JsonResponse:
            capital_calls.append(url)
            return JsonResponse(
                {
                    "code": 200,
                    "data": [
                        {
                            "stocNo": "00919",
                            "date1": "2026/08/07",
                            "time1": "15:00:00",
                            "nav": 29.76,
                        }
                    ],
                }
            )

        fetch_capital_etf_inav("00919", request_post=capital_post)
        self.assertEqual(len(capital_calls), 1)

        fuh_hwa_calls: list[str] = []

        class HtmlResponse:
            encoding = "utf-8"

            def __init__(self, html: str) -> None:
                self.text = html

            @staticmethod
            def raise_for_status() -> None:
                return None

        def fuh_hwa_get(url: str, **_: object) -> HtmlResponse:
            fuh_hwa_calls.append(url)
            return HtmlResponse(
                """
                <div class="fundCard" data-type="etfnet">
                  <p class="fundCard-code">00929</p>
                  <div class="fundCard-date">2026/08/07 15:00:30</div>
                  <div class="fundCard-state"><div class="row">
                    <div class="fundCard-stateName">預估淨值/漲跌幅</div>
                    <span class="fundFluctuate">28.54</span>
                  </div></div>
                </div>
                """
            )

        fetch_fuh_hwa_etf_inav("00929", request_get=fuh_hwa_get)
        self.assertEqual(len(fuh_hwa_calls), 1)

        class FakeSession:
            def __init__(self, responses: list[object]) -> None:
                self.responses = responses
                self.calls: list[tuple[str, str]] = []
                self.closed = False

            def request(self, method: str, url: str, **_: object):
                self.calls.append((method, url))
                return self.responses.pop(0)

            def close(self) -> None:
                self.closed = True

        nomura_session = FakeSession(
            [
                JsonResponse(
                    {
                        "StatusCode": 0,
                        "Entries": [
                            {
                                "CStockNo": "00980A",
                                "CDataDt": "2026/08/07 17:20:50",
                                "CEstimateNav": 23.55,
                            }
                        ],
                    }
                )
            ]
        )
        fetch_nomura_etf_inav("00980A", session_factory=lambda: nomura_session)
        self.assertEqual(len(nomura_session.calls), 1)
        self.assertTrue(nomura_session.closed)

        upamc_session = FakeSession(
            [
                HtmlResponse(
                    '<a href="/ETF/Fund/Info?fundCode=36YTW">00757 統一FANG+</a>'
                    '<input id="ED" value="115/08/10" />'
                ),
                JsonResponse(
                    {
                        "fund": {"sFundCode": "36YTW", "sStockNo": "00757"},
                        "pcf": [
                            {
                                "PCFCode": "PRE_AMT",
                                "Amount": 76850000,
                                "TranDate": "2026-08-06T00:00:00",
                                "PostDate": "2026-08-10T00:00:00",
                                "EditDate": "2026-08-07T15:34:25",
                            },
                            {"PCFCode": "NAV", "Amount": 40378493173},
                            {"PCFCode": "OUT_UNIT", "Amount": 288994000},
                            {"PCFCode": "P_UNIT", "Amount": 139.72},
                            {"PCFCode": "FUND_BASEUNIT", "Amount": 500000},
                        ],
                    }
                ),
            ]
        )
        fetch_upamc_etf_pcf("00757", session_factory=lambda: upamc_session)
        self.assertEqual(len(upamc_session.calls), 2)
        self.assertTrue(upamc_session.closed)

    def test_major_issuer_schema_drift_is_explicit(self) -> None:
        with self.assertRaises(TaiwanEtfCathayProviderError):
            parse_cathay_etf_inav_payload({}, "00878")
        with self.assertRaises(TaiwanEtfCathayProviderError):
            parse_cathay_etf_pcf_html("<html></html>", "00878", fund_code="CN")
        with self.assertRaises(TaiwanEtfCapitalProviderError):
            parse_capital_etf_inav_payload({}, "00919")
        with self.assertRaises(TaiwanEtfFuhHwaProviderError):
            parse_fuh_hwa_etf_inav_html("<html></html>", "00929")
        with self.assertRaises(TaiwanEtfNomuraProviderError):
            parse_nomura_etf_inav_payload({}, "00980A")
        with self.assertRaises(TaiwanEtfUpamcProviderError):
            parse_upamc_etf_pcf_payload({}, "00757")


class TaiwanEtfProviderRegistryTests(unittest.TestCase):
    def test_official_issuer_catalog_canonicalizes_recognized_issuers(self) -> None:
        identity = canonicalize_taiwan_etf_identity(
            TaiwanEtfInstrumentIdentity(
                stock_id="00878",
                market="TWSE",
                issuer_name="國泰證券投資信託股份有限公司",
                stock_name="永續高股息",
            )
        )

        self.assertEqual(identity.issuer_code, "A0037")
        self.assertEqual(
            len(DEFAULT_TAIWAN_ETF_ISSUER_CATALOG.issuers),
            22,
        )

    def test_default_registry_resolves_yuanta_from_canonical_issuer_name(self) -> None:
        binding = DEFAULT_TAIWAN_ETF_PROVIDER_REGISTRY.resolve(
            TaiwanEtfInstrumentIdentity(
                stock_id="0050",
                market="TWSE",
                issuer_name="元大證券投資信託股份有限公司",
                stock_name="台灣50",
            )
        )

        self.assertIsNotNone(binding)
        assert binding is not None
        self.assertEqual(binding.provider, "yuanta_etfs")
        self.assertEqual(binding.pcf.request_count if binding.pcf else None, 1)
        self.assertEqual(
            binding.intraday_nav.request_count if binding.intraday_nav else None,
            5,
        )

    def test_default_registry_resolves_cathay_resources(self) -> None:
        binding = DEFAULT_TAIWAN_ETF_PROVIDER_REGISTRY.resolve(
            TaiwanEtfInstrumentIdentity(
                stock_id="00878",
                market="TWSE",
                issuer_name="國泰證券投資信託股份有限公司",
                stock_name="國泰永續高股息",
            )
        )

        self.assertIsNotNone(binding)
        assert binding is not None
        self.assertEqual(binding.provider, CATHAY_PROVIDER)
        self.assertEqual(binding.pcf.request_count if binding.pcf else None, 2)
        self.assertTrue(binding.pcf.unit_nav_is_daily_nav if binding.pcf else False)
        self.assertEqual(
            binding.intraday_nav.request_count if binding.intraday_nav else None,
            2,
        )

    def test_default_registry_resolves_fubon_by_official_issuer_code(self) -> None:
        binding = DEFAULT_TAIWAN_ETF_PROVIDER_REGISTRY.resolve(
            TaiwanEtfInstrumentIdentity(
                stock_id="006208",
                market="TWSE",
                issuer_code="A0010",
                stock_name="台灣50",
            )
        )

        self.assertIsNotNone(binding)
        assert binding is not None
        self.assertEqual(binding.provider, FUBON_PROVIDER)
        self.assertEqual(binding.pcf.request_count if binding.pcf else None, 1)
        self.assertFalse(
            binding.pcf.includes_component_exposure if binding.pcf else True
        )
        self.assertEqual(
            binding.intraday_nav.request_count if binding.intraday_nav else None,
            1,
        )

    def test_default_registry_connects_each_major_issuer_at_resource_level(self) -> None:
        expected = {
            "A0009": (UPAMC_PROVIDER, True, False),
            "A0016": (CAPITAL_PROVIDER, False, True),
            "A0022": (FUH_HWA_PROVIDER, False, True),
            "A0032": (NOMURA_PROVIDER, False, True),
            "A0037": (CATHAY_PROVIDER, True, True),
        }

        for issuer_code, (provider, has_pcf, has_inav) in expected.items():
            with self.subTest(issuer_code=issuer_code):
                binding = DEFAULT_TAIWAN_ETF_PROVIDER_REGISTRY.resolve(
                    TaiwanEtfInstrumentIdentity(
                        stock_id="TEST",
                        market="TWSE",
                        issuer_code=issuer_code,
                    )
                )
                self.assertIsNotNone(binding)
                assert binding is not None
                self.assertEqual(binding.provider, provider)
                self.assertEqual(binding.pcf is not None, has_pcf)
                self.assertEqual(binding.intraday_nav is not None, has_inav)


class TaiwanEtfServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        with self.Session() as db:
            db.add_all(
                [
                    StockMaster(
                        stock_id="0050",
                        stock_name="元大台灣50",
                        market="TWSE",
                        instrument_type="ETF",
                    ),
                    StockMaster(
                        stock_id="006208",
                        stock_name="富邦台50",
                        market="TWSE",
                        instrument_type="ETF",
                    ),
                    StockMaster(
                        stock_id="00878",
                        stock_name="國泰永續高股息",
                        market="TWSE",
                        instrument_type="ETF",
                    ),
                    StockMaster(
                        stock_id="00981A",
                        stock_name="統一台股增長",
                        market="TWSE",
                        instrument_type="ETF",
                    ),
                    StockMaster(
                        stock_id="00999X",
                        stock_name="未接入投信測試ETF",
                        market="TWSE",
                        instrument_type="ETF",
                    ),
                ]
            )
            db.commit()

    def tearDown(self) -> None:
        self.engine.dispose()

    @staticmethod
    def _add_daily_close(
        db: Session,
        *,
        stock_id: str,
        trade_date: date,
        close_price: float,
    ) -> None:
        source = SourceRegistry(
            source_name=f"etf-daily-close-{stock_id}",
            source_type="official",
            category="daily_price",
            endpoint_url="https://openapi.twse.com.tw/",
            enabled=True,
            priority=10,
            auth_type="none",
            reliability_level="official",
        )
        db.add(source)
        db.flush()
        raw = RawFetchResult(
            source_id=source.id,
            fetched_at=datetime(2026, 8, 7, 14, 30, tzinfo=TAIWAN_TZ),
            method="GET",
            content_hash=f"etf-daily-close-{stock_id}-{trade_date.isoformat()}",
            parser_version="etf-valuation-test-v1",
        )
        db.add(raw)
        db.flush()
        db.add(
            MarketDailyPrice(
                source_id=source.id,
                raw_result_id=raw.id,
                trade_date=trade_date,
                stock_id=stock_id,
                close_price=close_price,
            )
        )
        db.flush()

    @staticmethod
    def _profile(_: str) -> TaiwanEtfProfileRecord:
        return TaiwanEtfProfileRecord(
            stock_id="0050",
            report_date=date(2026, 8, 8),
            fund_short_name="元大台灣50",
            fund_name="元大台灣卓越50證券投資信託基金",
            fund_name_en="Yuanta Taiwan Top 50 ETF",
            fund_type="國內成分證券指數股票型基金",
            benchmark_name="臺灣50指數",
            is_customized_index=False,
            investment_scope="股票投資",
            has_performance_benchmark=True,
            performance_benchmark_name="臺灣50指數",
            has_foreign_components=False,
            tax_id="00938563",
            established_date=date(2003, 6, 25),
            listed_date=date(2003, 6, 30),
            fund_manager="測試經理人",
            issued_units=1_234_000,
            custodian="測試銀行",
        )

    @staticmethod
    def _nav(target_date: date) -> tuple[TaiwanEtfNavRecord, ...]:
        return (
            TaiwanEtfNavRecord(
                stock_id="0050",
                nav_date=target_date,
                issuer_name="元大投信",
                fund_name="元大台灣50",
                nav=Decimal("102.76"),
                previous_nav=Decimal("103.04"),
                nav_change=Decimal("-0.28"),
                nav_change_pct=Decimal("-0.27"),
                close_price=Decimal("102.85"),
                premium_discount_pct=Decimal("0.09"),
            ),
        )

    @staticmethod
    def _pcf(
        stock_id: str,
        *,
        target_date: date | None = None,
    ) -> TaiwanEtfPcfRecord:
        return TaiwanEtfPcfRecord(
            stock_id=stock_id,
            fund_id="1066",
            fund_name="元大台灣卓越50基金",
            full_name="元大台灣卓越50證券投資信託基金",
            name_en="Yuanta/P-shares Taiwan Top 50 ETF",
            reference_date=date(2026, 8, 7),
            effective_date=target_date or date(2026, 8, 10),
            total_net_assets=Decimal("2305206923456"),
            issued_units=22_433_000_000,
            unit_nav=Decimal("102.76"),
            creation_unit=500_000,
            estimated_creation_value=Decimal("51379818"),
            estimated_cash_component=Decimal("51496"),
            unit_change=0,
            actual_cash_component=Decimal("52052"),
            redemption_method="in_kind",
            source_updated_at=datetime(2026, 8, 7, 7, 47, 38, tzinfo=ZoneInfo("UTC")),
            components=(
                TaiwanEtfPcfComponentRecord(
                    source_section="in_kind",
                    asset_type="stock",
                    symbol="1216",
                    name="統一",
                    name_en="UNI-PRESIDENT ENTERPRISES CORP.",
                    contract_month=None,
                    quantity=Decimal("2581"),
                    weight_pct=None,
                    cash_in_lieu="N",
                    minimum_creation=True,
                    order_index=0,
                ),
                TaiwanEtfPcfComponentRecord(
                    source_section="in_kind",
                    asset_type="stock",
                    symbol="2330",
                    name="台積電",
                    name_en="Taiwan Semiconductor Manufacturing Co.",
                    contract_month=None,
                    quantity=Decimal("18000"),
                    weight_pct=None,
                    cash_in_lieu="N",
                    minimum_creation=True,
                    order_index=1,
                ),
            ),
        )

    @staticmethod
    def _inav(stock_id: str) -> TaiwanEtfInavRecord:
        return TaiwanEtfInavRecord(
            stock_id=stock_id,
            fund_short_name="元大台灣卓越50基金",
            investment_area="D",
            estimated_nav=Decimal("102.76"),
            nav_change=Decimal("-0.28"),
            market_price=Decimal("102.85"),
            price_change=Decimal("-0.45"),
            premium_discount_pct=Decimal("0.087583"),
            observed_at=datetime(2026, 8, 10, 9, 29, 30, tzinfo=TAIWAN_TZ),
        )

    def test_get_is_cache_only_and_refresh_is_bounded_idempotent(self) -> None:
        now = datetime(2026, 8, 9, 12, 0, tzinfo=TAIWAN_TZ)
        calls = {"profile": 0, "nav": 0}

        def fetch_profile(stock_id: str) -> TaiwanEtfProfileRecord:
            calls["profile"] += 1
            return self._profile(stock_id)

        def fetch_nav(target_date: date) -> tuple[TaiwanEtfNavRecord, ...]:
            calls["nav"] += 1
            return self._nav(target_date)

        with self.Session() as db:
            cached = get_taiwan_etf_overview(db, "0050", now=now)
            self.assertEqual(cached["status"], "missing")
            self.assertEqual(calls, {"profile": 0, "nav": 0})

            first = refresh_taiwan_etf(
                db,
                "0050",
                now=now,
                fetch_profile=fetch_profile,
                fetch_nav=fetch_nav,
            )
            second = refresh_taiwan_etf(
                db,
                "0050",
                now=now,
                fetch_profile=fetch_profile,
                fetch_nav=fetch_nav,
            )

            self.assertEqual(first["status"], "current")
            self.assertEqual(first["refresh"]["request_count"], 2)
            self.assertEqual(second["status"], "current")
            self.assertEqual(calls, {"profile": 2, "nav": 2})
            self.assertEqual(db.query(TaiwanEtfProfile).count(), 1)
            self.assertEqual(db.query(TaiwanEtfNavDaily).count(), 1)
            self.assertEqual(
                db.query(StockMaster)
                .filter(StockMaster.stock_id == "0050")
                .one()
                .instrument_type,
                "ETF",
            )

    def test_partial_provider_failure_preserves_successful_profile(self) -> None:
        now = datetime(2026, 8, 9, 12, 0, tzinfo=TAIWAN_TZ)

        def fail_nav(_: date) -> tuple[TaiwanEtfNavRecord, ...]:
            raise TaiwanEtfProviderError("NAV provider unavailable")

        with self.Session() as db:
            result = refresh_taiwan_etf(
                db,
                "0050",
                now=now,
                fetch_profile=self._profile,
                fetch_nav=fail_nav,
            )

            self.assertEqual(result["status"], "partial")
            self.assertIsNotNone(result["profile"])
            self.assertIsNone(result["daily_nav"])
            self.assertIn("daily_close_nav", result["refresh"]["errors"])

    def test_canonical_valuation_keeps_market_close_when_daily_nav_is_missing(self) -> None:
        now = datetime(2026, 8, 9, 12, 0, tzinfo=TAIWAN_TZ)
        with self.Session() as db:
            self._add_daily_close(
                db,
                stock_id="00981A",
                trade_date=date(2026, 8, 7),
                close_price=28.21,
            )
            result = get_taiwan_etf_overview(db, "00981A", now=now)

        valuation = result["valuation"]
        self.assertIsNone(result["daily_nav"])
        self.assertEqual(valuation["status"], "partial")
        self.assertEqual(valuation["basis"], "daily_close")
        self.assertEqual(valuation["market_price"]["value"], Decimal("28.21"))
        self.assertEqual(
            valuation["market_price"]["as_of_date"],
            date(2026, 8, 7),
        )
        self.assertEqual(valuation["market_price"]["status"], "current")
        self.assertIsNone(valuation["nav"]["value"])
        self.assertIsNone(valuation["premium_discount_pct"])
        self.assertEqual(
            valuation["premium_discount_status"],
            "input_missing",
        )

    def test_verified_pcf_unit_nav_can_fill_canonical_daily_nav(self) -> None:
        now = datetime(2026, 8, 9, 12, 0, tzinfo=TAIWAN_TZ)

        def fetch_pcf(
            stock_id: str,
            *,
            target_date: date | None = None,
        ) -> TaiwanEtfPcfRecord:
            return replace(
                self._pcf(stock_id, target_date=target_date),
                reference_date=date(2026, 8, 7),
                unit_nav=Decimal("28.15"),
                redemption_method="cash",
                components=(),
            )

        with self.Session() as db:
            self._add_daily_close(
                db,
                stock_id="00981A",
                trade_date=date(2026, 8, 7),
                close_price=28.21,
            )
            result = refresh_taiwan_etf(
                db,
                "00981A",
                refresh_profile=False,
                refresh_nav=False,
                refresh_pcf=True,
                now=now,
                fetch_pcf=fetch_pcf,
            )

        valuation = result["valuation"]
        self.assertEqual(result["refresh"]["request_count"], 2)
        self.assertEqual(valuation["status"], "current")
        self.assertTrue(valuation["aligned"])
        self.assertEqual(valuation["nav"]["value"], Decimal("28.15"))
        self.assertEqual(valuation["nav"]["basis"], "pcf_unit_nav")
        self.assertEqual(valuation["nav"]["source"], UPAMC_PROVIDER)
        self.assertEqual(valuation["premium_discount_status"], "ready")
        self.assertAlmostEqual(
            float(valuation["premium_discount_pct"]),
            ((28.21 / 28.15) - 1) * 100,
            places=8,
        )

    def test_unverified_pcf_unit_nav_is_not_promoted_to_daily_nav(self) -> None:
        now = datetime(2026, 8, 9, 12, 0, tzinfo=TAIWAN_TZ)

        def fetch_pcf(
            stock_id: str,
            *,
            target_date: date | None = None,
        ) -> TaiwanEtfPcfRecord:
            return replace(
                self._pcf(stock_id, target_date=target_date),
                reference_date=date(2026, 8, 7),
                unit_nav=Decimal("28.15"),
                components=(),
            )

        registry = TaiwanEtfProviderRegistry(
            (
                TaiwanEtfProviderBinding(
                    provider="upamc_unverified_test",
                    issuer_codes=frozenset({"A0009"}),
                    issuer_aliases=("統一",),
                    markets=frozenset({"TWSE"}),
                    pcf=TaiwanEtfPcfProviderResource(
                        source_url="https://provider.test/upamc/pcf",
                        request_count=1,
                        fetch=fetch_pcf,
                        unit_nav_is_daily_nav=False,
                    ),
                ),
            )
        )

        with self.Session() as db:
            self._add_daily_close(
                db,
                stock_id="00981A",
                trade_date=date(2026, 8, 7),
                close_price=28.21,
            )
            result = refresh_taiwan_etf(
                db,
                "00981A",
                refresh_profile=False,
                refresh_nav=False,
                refresh_pcf=True,
                now=now,
                provider_registry=registry,
            )

        valuation = result["valuation"]
        self.assertIsNone(valuation["nav"]["value"])
        self.assertIn(
            "valuation_pcf_unit_nav_not_eligible",
            valuation["issue_codes"],
        )
        self.assertIsNone(valuation["premium_discount_pct"])

    def test_canonical_valuation_does_not_mix_price_and_nav_dates(self) -> None:
        now = datetime(2026, 8, 9, 12, 0, tzinfo=TAIWAN_TZ)

        def fetch_pcf(
            stock_id: str,
            *,
            target_date: date | None = None,
        ) -> TaiwanEtfPcfRecord:
            return replace(
                self._pcf(stock_id, target_date=target_date),
                reference_date=date(2026, 8, 6),
                unit_nav=Decimal("28.00"),
                components=(),
            )

        with self.Session() as db:
            self._add_daily_close(
                db,
                stock_id="00981A",
                trade_date=date(2026, 8, 7),
                close_price=28.21,
            )
            result = refresh_taiwan_etf(
                db,
                "00981A",
                refresh_profile=False,
                refresh_nav=False,
                refresh_pcf=True,
                now=now,
                fetch_pcf=fetch_pcf,
            )

        valuation = result["valuation"]
        self.assertEqual(valuation["status"], "partial")
        self.assertFalse(valuation["aligned"])
        self.assertIsNone(valuation["premium_discount_pct"])
        self.assertEqual(
            valuation["premium_discount_status"],
            "date_mismatch",
        )
        self.assertIn(
            "valuation_price_nav_date_mismatch",
            valuation["issue_codes"],
        )

    def test_active_etf_resource_states_distinguish_not_applicable(self) -> None:
        now = datetime(2026, 8, 9, 12, 0, tzinfo=TAIWAN_TZ)

        def fetch_profile(stock_id: str) -> TaiwanEtfProfileRecord:
            return replace(
                self._profile(stock_id),
                stock_id=stock_id,
                fund_short_name="主動統一台股增長",
                fund_name="統一台股增長主動式ETF基金",
                fund_name_en="UPAMC Taiwan Growth Active ETF",
                fund_type="國內成分證券主動式交易所交易基金(股票)",
                benchmark_name=None,
                has_performance_benchmark=True,
                performance_benchmark_name="臺灣證券交易所發行量加權股價報酬指數",
            )

        def fetch_pcf(
            stock_id: str,
            *,
            target_date: date | None = None,
        ) -> TaiwanEtfPcfRecord:
            return replace(
                self._pcf(stock_id, target_date=target_date),
                reference_date=date(2026, 8, 7),
                unit_nav=Decimal("28.15"),
                redemption_method="cash",
                components=(),
            )

        with self.Session() as db:
            result = refresh_taiwan_etf(
                db,
                "00981A",
                refresh_profile=True,
                refresh_nav=False,
                refresh_pcf=True,
                now=now,
                fetch_profile=fetch_profile,
                fetch_pcf=fetch_pcf,
            )

        states = result["resource_states"]
        self.assertEqual(result["strategy"]["management_style"], "active")
        self.assertEqual(
            result["strategy"]["benchmark_role"],
            "performance_benchmark",
        )
        self.assertFalse(states["tracked_index"]["applicable"])
        self.assertEqual(states["tracked_index"]["status"], "not_applicable")
        self.assertEqual(states["performance_benchmark"]["status"], "current")
        self.assertFalse(states["pcf_component_basket"]["applicable"])
        self.assertEqual(
            states["pcf_component_basket"]["reason_code"],
            "cash_redemption_has_no_in_kind_basket",
        )
        self.assertEqual(
            states["fund_holdings"]["status"],
            "provider_not_connected",
        )

    def test_passive_etf_keeps_optional_resources_out_of_core_status(self) -> None:
        now = datetime(2026, 8, 9, 12, 0, tzinfo=TAIWAN_TZ)

        def fetch_profile(stock_id: str) -> TaiwanEtfProfileRecord:
            return replace(
                self._profile(stock_id),
                stock_id=stock_id,
                fund_short_name="國泰永續高股息",
                fund_name="國泰台灣ESG永續高股息ETF基金",
                fund_name_en="Cathay MSCI Taiwan ESG Sustainability High Dividend Yield ETF",
                fund_type="國內成分證券指數股票型基金",
                benchmark_name="MSCI臺灣ESG永續高股息精選30指數",
                has_performance_benchmark=True,
                performance_benchmark_name="MSCI臺灣ESG永續高股息精選30指數",
            )

        with self.Session() as db:
            result = refresh_taiwan_etf(
                db,
                "00878",
                refresh_profile=True,
                refresh_nav=False,
                now=now,
                fetch_profile=fetch_profile,
            )

        states = result["resource_states"]
        self.assertEqual(result["strategy"]["management_style"], "passive")
        self.assertEqual(result["strategy"]["benchmark_role"], "tracked_index")
        self.assertEqual(states["tracked_index"]["status"], "current")
        self.assertEqual(
            states["performance_benchmark"]["status"],
            "not_applicable",
        )
        self.assertEqual(
            states["pcf_summary"]["status"],
            "missing",
        )
        self.assertEqual(
            states["fund_holdings"]["status"],
            "provider_not_connected",
        )

    def test_pcf_and_inav_refresh_are_bounded_idempotent_and_freshness_aware(self) -> None:
        now = datetime(2026, 8, 10, 9, 30, tzinfo=TAIWAN_TZ)
        calls = {"pcf": 0, "inav": 0}

        def fetch_pcf(stock_id: str, *, target_date: date | None = None) -> TaiwanEtfPcfRecord:
            calls["pcf"] += 1
            return self._pcf(stock_id, target_date=target_date)

        def fetch_inav(stock_id: str) -> TaiwanEtfInavRecord:
            calls["inav"] += 1
            return self._inav(stock_id)

        with self.Session() as db:
            first = refresh_taiwan_etf(
                db,
                "0050",
                refresh_profile=False,
                refresh_nav=False,
                refresh_pcf=True,
                refresh_inav=True,
                now=now,
                fetch_pcf=fetch_pcf,
                fetch_inav=fetch_inav,
            )
            second = refresh_taiwan_etf(
                db,
                "0050",
                refresh_profile=False,
                refresh_nav=False,
                refresh_pcf=True,
                refresh_inav=True,
                now=now,
                fetch_pcf=fetch_pcf,
                fetch_inav=fetch_inav,
            )

            self.assertEqual(first["refresh"]["request_count"], 6)
            self.assertEqual(first["freshness"]["pcf_status"], "current")
            self.assertEqual(first["freshness"]["inav_status"], "current")
            self.assertEqual(first["pcf"]["component_count"], 2)
            self.assertEqual(first["intraday_nav"]["estimated_nav"], Decimal("102.76"))
            self.assertEqual(second["pcf"]["component_count"], 2)
            self.assertEqual(calls, {"pcf": 2, "inav": 2})
            self.assertEqual(db.query(TaiwanEtfPcfSnapshot).count(), 1)
            self.assertEqual(db.query(TaiwanEtfPcfComponent).count(), 2)
            self.assertEqual(db.query(TaiwanEtfInavSnapshot).count(), 1)

    def test_resource_level_registry_drives_provider_source_and_capability(self) -> None:
        registry = TaiwanEtfProviderRegistry(
            (
                TaiwanEtfProviderBinding(
                    provider="fubon_test",
                    issuer_codes=frozenset(),
                    issuer_aliases=("富邦",),
                    markets=frozenset({"TWSE"}),
                    pcf=TaiwanEtfPcfProviderResource(
                        source_url="https://provider.test/fubon/pcf",
                        request_count=2,
                        fetch=self._pcf,
                    ),
                ),
            )
        )

        with self.Session() as db:
            result = refresh_taiwan_etf(
                db,
                "006208",
                refresh_profile=False,
                refresh_nav=False,
                refresh_pcf=True,
                now=datetime(2026, 8, 10, 9, 30, tzinfo=TAIWAN_TZ),
                provider_registry=registry,
            )
            snapshot = db.query(TaiwanEtfPcfSnapshot).one()

        pcf_source = next(
            source for source in result["sources"] if source["resource"] == "pcf"
        )
        self.assertEqual(result["refresh"]["request_count"], 2)
        self.assertTrue(result["capabilities"]["pcf"])
        self.assertFalse(result["capabilities"]["intraday_estimated_nav"])
        self.assertEqual(pcf_source["provider"], "fubon_test")
        self.assertEqual(pcf_source["source_url"], "https://provider.test/fubon/pcf")
        self.assertEqual(snapshot.source, "fubon_test")

    def test_default_fubon_binding_refreshes_both_resources_in_two_requests(self) -> None:
        with self.Session() as db:
            result = refresh_taiwan_etf(
                db,
                "006208",
                refresh_profile=False,
                refresh_nav=False,
                refresh_pcf=True,
                refresh_inav=True,
                now=datetime(2026, 8, 10, 9, 30, tzinfo=TAIWAN_TZ),
                fetch_pcf=self._pcf,
                fetch_inav=self._inav,
            )

        sources = {source["resource"]: source for source in result["sources"]}
        self.assertEqual(result["refresh"]["request_count"], 2)
        self.assertTrue(result["capabilities"]["pcf"])
        self.assertTrue(result["capabilities"]["intraday_estimated_nav"])
        self.assertFalse(result["capabilities"]["component_exposure"])
        self.assertEqual(sources["pcf"]["provider"], FUBON_PROVIDER)
        self.assertIn("stkId=006208", sources["pcf"]["source_url"])
        self.assertEqual(sources["intraday_estimated_nav"]["source_url"], FUBON_INAV_URL)

    def test_unconnected_issuer_is_explicit_and_does_not_call_injected_fetchers(self) -> None:
        def unexpected_pcf(*_args, **_kwargs) -> TaiwanEtfPcfRecord:
            raise AssertionError("unconnected PCF fetcher must not be called")

        def unexpected_inav(*_args, **_kwargs) -> TaiwanEtfInavRecord:
            raise AssertionError("unconnected iNAV fetcher must not be called")

        with self.Session() as db:
            result = refresh_taiwan_etf(
                db,
                "00999X",
                refresh_profile=False,
                refresh_nav=False,
                refresh_pcf=True,
                refresh_inav=True,
                now=datetime(2026, 8, 10, 9, 30, tzinfo=TAIWAN_TZ),
                fetch_pcf=unexpected_pcf,
                fetch_inav=unexpected_inav,
            )

        sources = {source["resource"]: source for source in result["sources"]}
        self.assertEqual(result["refresh"]["request_count"], 0)
        self.assertIn("provider_not_connected", result["refresh"]["errors"]["pcf"])
        self.assertIn(
            "provider_not_connected",
            result["refresh"]["errors"]["intraday_estimated_nav"],
        )
        self.assertFalse(result["capabilities"]["pcf"])
        self.assertFalse(result["capabilities"]["intraday_estimated_nav"])
        self.assertEqual(sources["pcf"]["provider"], "not_connected")
        self.assertEqual(sources["intraday_estimated_nav"]["provider"], "not_connected")

    def test_off_session_inav_is_closed_not_falsely_current(self) -> None:
        with self.Session() as db:
            refresh_taiwan_etf(
                db,
                "0050",
                refresh_profile=False,
                refresh_nav=False,
                refresh_inav=True,
                now=datetime(2026, 8, 10, 9, 30, tzinfo=TAIWAN_TZ),
                fetch_inav=self._inav,
            )
            result = get_taiwan_etf_overview(
                db,
                "0050",
                now=datetime(2026, 8, 10, 15, 0, tzinfo=TAIWAN_TZ),
            )

        self.assertEqual(result["freshness"]["session_phase"], "post_close")
        self.assertEqual(result["freshness"]["inav_status"], "closed")

    def test_inav_retention_keeps_only_the_newest_bounded_history(self) -> None:
        call_count = 0

        def fetch_inav(stock_id: str) -> TaiwanEtfInavRecord:
            nonlocal call_count
            call_count += 1
            return replace(
                self._inav(stock_id),
                observed_at=self._inav(stock_id).observed_at
                + timedelta(seconds=call_count),
            )

        with patch.object(tw_etf_service, "ETF_INAV_RETENTION_PER_STOCK", 2):
            with self.Session() as db:
                for _ in range(4):
                    refresh_taiwan_etf(
                        db,
                        "0050",
                        refresh_profile=False,
                        refresh_nav=False,
                        refresh_inav=True,
                        now=datetime(2026, 8, 10, 9, 30, tzinfo=TAIWAN_TZ),
                        fetch_inav=fetch_inav,
                    )

                observed_at = [
                    row.observed_at
                    for row in db.query(TaiwanEtfInavSnapshot)
                    .order_by(TaiwanEtfInavSnapshot.observed_at.asc())
                    .all()
                ]

        self.assertEqual(call_count, 4)
        self.assertEqual(len(observed_at), 2)
        self.assertEqual(observed_at[-1].second, 34)

    def test_watchlist_contract_carries_canonical_instrument(self) -> None:
        with self.Session() as db:
            group = WatchlistGroup(group_name="ETF", sort_order=100, is_active=True)
            db.add(group)
            db.flush()
            item = WatchlistItem(
                group_id=group.id,
                stock_id="0050",
                priority=100,
                enabled=True,
            )
            db.add(item)
            db.commit()
            db.refresh(item)

            payload = _item_to_dict(db, item)

            self.assertEqual(payload["market"], "TWSE")
            self.assertEqual(payload["instrument_type"], "etf")

    def test_cache_only_overview_matches_public_response_schema(self) -> None:
        with self.Session() as db:
            payload = TaiwanEtfOverviewRead.model_validate(
                get_taiwan_etf_overview(
                    db,
                    "0050",
                    now=datetime(2026, 8, 9, 12, 0, tzinfo=TAIWAN_TZ),
                )
            )

        self.assertEqual(payload.instrument_type, "etf")
        self.assertEqual(payload.status, "missing")
        self.assertFalse(payload.capabilities["company_financials"])
        self.assertTrue(payload.capabilities["intraday_estimated_nav"])
        self.assertTrue(payload.capabilities["pcf"])
        self.assertFalse(payload.capabilities["holdings"])


if __name__ == "__main__":
    unittest.main()
