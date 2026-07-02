from __future__ import annotations

from datetime import date
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base
from app.market.market_chips import (
    MarketChipFetchError,
    ensure_market_chip_daily,
    extract_index_futures_position_summary,
    market_chip_daily_to_dict,
    normalize_market_chip_index_ids,
    parse_institutional_amount_summary,
    parse_taifex_futures_institutional_html,
    parse_tpex_margin_summary,
    parse_twse_margin_summary,
    refresh_market_chip_daily,
    upsert_market_chip_daily,
)


TAIFEX_HTML = """
<html>
  <body>
    <div>日期2026/06/09</div>
    <table>
      <tr>
        <th>序號</th><th>商品名稱</th><th>身份別</th>
        <th>口數</th><th>契約金額</th><th>口數</th><th>契約金額</th>
        <th>口數</th><th>契約金額</th><th>口數</th><th>契約金額</th>
        <th>口數</th><th>契約金額</th><th>口數</th><th>契約金額</th>
      </tr>
      <tr>
        <td>1</td><td rowspan="3">臺股期貨</td><td>自營商</td>
        <td>5,988</td><td>52,891,379</td><td>7,276</td><td>64,284,715</td>
        <td>-1,288</td><td>-11,393,336</td><td>8,335</td><td>74,574,655</td>
        <td>4,258</td><td>38,145,962</td><td>4,077</td><td>36,428,693</td>
      </tr>
      <tr>
        <td>投信</td>
        <td>2,415</td><td>21,553,933</td><td>1,036</td><td>9,211,485</td>
        <td>1,379</td><td>12,342,448</td><td>60,730</td><td>542,665,311</td>
        <td>5,477</td><td>48,939,186</td><td>55,253</td><td>493,726,125</td>
      </tr>
      <tr>
        <td>外資</td>
        <td>86,981</td><td>767,160,971</td><td>84,593</td><td>746,194,035</td>
        <td>2,388</td><td>20,966,936</td><td>9,344</td><td>83,501,729</td>
        <td>71,215</td><td>636,459,151</td><td>-61,871</td><td>-552,957,422</td>
      </tr>
      <tr>
        <td>4</td><td rowspan="3">小型臺指期貨</td><td>自營商</td>
        <td>13,207</td><td>29,122,962</td><td>13,694</td><td>30,212,035</td>
        <td>-487</td><td>-1,089,073</td><td>2,281</td><td>5,131,938</td>
        <td>16,291</td><td>36,478,593</td><td>-14,010</td><td>-31,346,655</td>
      </tr>
      <tr>
        <td>投信</td>
        <td>5</td><td>11,181</td><td>0</td><td>0</td>
        <td>5</td><td>11,181</td><td>90</td><td>201,047</td>
        <td>86</td><td>192,111</td><td>4</td><td>8,936</td>
      </tr>
      <tr>
        <td>外資</td>
        <td>178,622</td><td>393,407,139</td><td>174,249</td><td>383,759,461</td>
        <td>4,373</td><td>9,647,678</td><td>4,833</td><td>10,796,667</td>
        <td>1,079</td><td>2,415,613</td><td>3,754</td><td>8,381,054</td>
      </tr>
    </table>
  </body>
</html>
"""


class MarketChipParserTests(unittest.TestCase):
    def test_parse_twse_institutional_amount_summary(self) -> None:
        payload = {
            "date": "115年06月09日",
            "fields": ["單位名稱", "買進金額", "賣出金額", "買賣超金額"],
            "data": [
                ["自營商(自行買賣)", "120", "100", "20"],
                ["自營商(避險)", "40", "80", "-40"],
                ["投信", "700", "500", "200"],
                ["外資及陸資(不含外資自營商)", "2,000", "3,000", "-1,000"],
                ["外資自營商", "90", "70", "20"],
                ["合計", "2,950", "3,750", "-800"],
            ],
        }

        result = parse_institutional_amount_summary(
            payload,
            fallback_trade_date=date(2026, 6, 9),
        )

        self.assertEqual(result["trade_date"], date(2026, 6, 9))
        self.assertEqual(result["foreign_investor_net_value"], -980)
        self.assertEqual(result["investment_trust_net_value"], 200)
        self.assertEqual(result["dealer_net_value"], -20)
        self.assertEqual(result["total_institutional_net_value"], -800)

    def test_parse_taifex_futures_positions(self) -> None:
        payload = parse_taifex_futures_institutional_html(TAIFEX_HTML)
        result = extract_index_futures_position_summary(payload)

        self.assertEqual(payload["trade_date"], date(2026, 6, 9))
        self.assertEqual(result["foreign_futures_net_oi"], -61871)
        self.assertEqual(result["retail_futures_net_oi"], 10252)

    def test_parse_twse_margin_summary(self) -> None:
        payload = {
            "date": "115年06月26日",
            "tables": [
                {
                    "fields": [
                        "項目",
                        "買進",
                        "賣出",
                        "現金(券)償還",
                        "前日餘額",
                        "今日餘額",
                    ],
                    "data": [
                        ["融資(交易單位)", "1", "1", "0", "9,512,446", "9,328,374"],
                        ["融券(交易單位)", "1", "1", "0", "199,161", "203,932"],
                        ["融資金額(仟元)", "1", "1", "0", "611,000,560", "590,925,882"],
                    ],
                }
            ],
        }

        result = parse_twse_margin_summary(
            payload,
            fallback_trade_date=date(2026, 6, 26),
        )

        self.assertEqual(result["trade_date"], date(2026, 6, 26))
        self.assertEqual(result["margin_balance_change_value"], -20_074_678_000)
        self.assertEqual(result["margin_balance_change_shares"], -184_072_000)
        self.assertEqual(result["short_balance_change_shares"], 4_771_000)

    def test_parse_tpex_margin_summary_aggregates_share_rows(self) -> None:
        payload = {
            "date": "115/06/26",
            "tables": [
                {
                    "fields": [
                        "代號",
                        "名稱",
                        "前資餘額(張)",
                        "資買",
                        "資賣",
                        "現償",
                        "資餘額",
                        "限額",
                        "前券限額",
                        "unused",
                        "前券餘額(張)",
                        "券賣",
                        "券買",
                        "券償",
                        "券餘額",
                    ],
                    "data": [
                        ["1111", "A", "10", "0", "0", "0", "15", "", "", "", "5", "0", "0", "0", "6"],
                        ["2222", "B", "20", "0", "0", "0", "18", "", "", "", "7", "0", "0", "0", "5"],
                    ],
                }
            ],
        }

        result = parse_tpex_margin_summary(
            payload,
            fallback_trade_date=date(2026, 6, 26),
        )

        self.assertEqual(result["trade_date"], date(2026, 6, 26))
        self.assertIsNone(result["margin_balance_change_value"])
        self.assertEqual(result["margin_balance_change_shares"], 3_000)
        self.assertEqual(result["short_balance_change_shares"], -1_000)


class MarketChipRefreshTests(unittest.TestCase):
    def test_normalize_market_chip_index_ids_deduplicates_and_validates(self) -> None:
        self.assertEqual(
            normalize_market_chip_index_ids(["taiex", "TPEX", "TAIEX"]),
            ["TAIEX", "TPEX"],
        )

        with self.assertRaises(ValueError):
            normalize_market_chip_index_ids(["SPX"])

    def test_refresh_market_chip_daily_collects_partial_source_errors(self) -> None:
        trade_date = date(2026, 6, 9)
        progress_calls: list[tuple[int | None, int | None, str | None]] = []

        def fake_ensure_market_chip_daily(**kwargs):
            if kwargs["index_id"] == "TPEX":
                raise MarketChipFetchError("TPEx source unavailable")

            return SimpleNamespace(
                index_id="TAIEX",
                market="TWSE",
                trade_date=trade_date,
                updated_at=None,
            )

        with patch(
            "app.market.market_chips.ensure_market_chip_daily",
            side_effect=fake_ensure_market_chip_daily,
        ):
            result = refresh_market_chip_daily(
                db=SimpleNamespace(),
                index_ids=["TAIEX", "TPEX"],
                trade_date=trade_date,
                progress=lambda current, total, message: progress_calls.append(
                    (current, total, message)
                ),
            )

        self.assertEqual(result["status"], "partial_success")
        self.assertEqual(result["trade_date"], "2026-06-09")
        self.assertEqual(result["requested_count"], 2)
        self.assertEqual(result["success_count"], 1)
        self.assertEqual(result["error_count"], 1)
        self.assertEqual(result["results"][0]["index_id"], "TAIEX")
        self.assertEqual(result["errors"][0]["index_id"], "TPEX")
        self.assertGreaterEqual(len(progress_calls), 3)


class MarketChipPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_upsert_computes_change_against_previous_row(self) -> None:
        upsert_market_chip_daily(
            self.db,
            payload={
                "index_id": "TAIEX",
                "market": "TWSE",
                "trade_date": date(2026, 6, 8),
                "foreign_futures_net_oi": -65501,
                "retail_futures_net_oi": 9990,
                "source_details": {"sources": []},
            },
        )

        row = upsert_market_chip_daily(
            self.db,
            payload={
                "index_id": "TAIEX",
                "market": "TWSE",
                "trade_date": date(2026, 6, 9),
                "foreign_futures_net_oi": -61871,
                "retail_futures_net_oi": 10252,
                "source_details": {"sources": []},
            },
        )
        result = market_chip_daily_to_dict(row)

        self.assertEqual(result["foreign_futures_net_oi_change"], 3630)
        self.assertEqual(result["retail_futures_net_oi_change"], 262)
        self.assertEqual(result["source_details"], {"sources": []})

    def test_ensure_refreshes_existing_row_after_margin_release(self) -> None:
        trade_date = date(2026, 6, 26)
        upsert_market_chip_daily(
            self.db,
            payload={
                "index_id": "TAIEX",
                "market": "TWSE",
                "trade_date": trade_date,
                "total_institutional_net_value": 100,
                "source_details": {"sources": []},
            },
        )

        with (
            patch(
                "app.market.market_chips.expected_market_margin_chip_date",
                return_value=trade_date,
            ),
            patch(
                "app.market.market_chips.fetch_market_chip_daily",
                return_value={
                    "index_id": "TAIEX",
                    "market": "TWSE",
                    "trade_date": trade_date,
                    "total_institutional_net_value": 100,
                    "margin_balance_change_value": -20_074_678_000,
                    "margin_balance_change_shares": -184_072_000,
                    "short_balance_change_shares": 4_771_000,
                    "source_details": {"sources": []},
                },
            ) as fetch,
        ):
            row = ensure_market_chip_daily(
                self.db,
                index_id="TAIEX",
                trade_date=trade_date,
            )

        fetch.assert_called_once()
        self.assertEqual(row.margin_balance_change_value, -20_074_678_000)
        self.assertEqual(row.margin_balance_change_shares, -184_072_000)
        self.assertEqual(row.short_balance_change_shares, 4_771_000)

    def test_tpex_margin_value_is_not_required_after_release(self) -> None:
        trade_date = date(2026, 6, 26)
        existing = upsert_market_chip_daily(
            self.db,
            payload={
                "index_id": "TPEX",
                "market": "TPEX",
                "trade_date": trade_date,
                "total_institutional_net_value": 100,
                "margin_balance_change_shares": 3_000,
                "short_balance_change_shares": -1_000,
                "source_details": {"sources": []},
            },
        )

        with (
            patch(
                "app.market.market_chips.expected_market_margin_chip_date",
                return_value=trade_date,
            ),
            patch("app.market.market_chips.fetch_market_chip_daily") as fetch,
        ):
            row = ensure_market_chip_daily(
                self.db,
                index_id="TPEX",
                trade_date=trade_date,
            )

        fetch.assert_not_called()
        self.assertEqual(row.id, existing.id)


if __name__ == "__main__":
    unittest.main()
