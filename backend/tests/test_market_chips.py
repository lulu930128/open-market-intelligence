from __future__ import annotations

from datetime import date
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base
from app.market.market_chips import (
    extract_index_futures_position_summary,
    market_chip_daily_to_dict,
    parse_institutional_amount_summary,
    parse_taifex_futures_institutional_html,
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


if __name__ == "__main__":
    unittest.main()
