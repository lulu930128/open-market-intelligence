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
            db.add(
                StockMaster(
                    stock_id="0050",
                    stock_name="元大台灣50",
                    market="TWSE",
                    instrument_type="ETF",
                )
            )
            db.commit()

    def tearDown(self) -> None:
        self.engine.dispose()

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
