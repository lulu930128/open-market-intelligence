from __future__ import annotations

from datetime import date, datetime
import unittest
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    TaiwanFuturesDailyBar,
    TaiwanFuturesIntradayBar,
    TaiwanFuturesQuoteSnapshot,
)
from app.market.tw_futures import (
    list_taiwan_futures_daily_bars,
    parse_taifex_daily_market_html,
    parse_taifex_mis_quote_payload,
    refresh_taiwan_futures_daily_bars,
    refresh_taiwan_futures_quotes,
    select_active_taiwan_futures_quote,
)


TAIWAN_TZ = ZoneInfo("Asia/Taipei")


def sample_mxf_payload() -> dict:
    return {
        "RtCode": "0",
        "RtMsg": "",
        "RtData": {
            "QuoteCount": "3",
            "QuoteList": [
                {
                    "SymbolID": "MXF-S",
                    "DispCName": "小臺指現貨",
                    "DispEName": "MXF",
                    "COpenPrice": "43587.63",
                    "CHighPrice": "44798.88",
                    "CLowPrice": "43587.63",
                    "CLastPrice": "44169.04",
                    "CRefPrice": "43149.46",
                    "CDate": "20260612",
                    "CTime": "133315",
                },
                {
                    "SymbolID": "MX4F6-F",
                    "DispCName": "小臺指期W4066",
                    "DispEName": "MX4W4066",
                    "CTotalVolume": "5",
                    "COpenPrice": "44389.00",
                    "CHighPrice": "44389.00",
                    "CLowPrice": "44178.00",
                    "CLastPrice": "44311.00",
                    "CRefPrice": "43268.00",
                    "SettlementPrice": "44229.00",
                    "OpenInterest": "1",
                    "CDate": "20260612",
                    "CTime": "133003",
                    "CDiff": "1043.00",
                    "CDiffRate": "2.41",
                },
                {
                    "SymbolID": "MXFF6-F",
                    "DispCName": "小臺指期066",
                    "DispEName": "MTX066",
                    "CTotalVolume": "408801",
                    "COpenPrice": "44938.00",
                    "CHighPrice": "44939.00",
                    "CLowPrice": "44044.00",
                    "CLastPrice": "44199.00",
                    "CRefPrice": "43219.00",
                    "SettlementPrice": "44217.00",
                    "OpenInterest": "25847",
                    "CDate": "20260612",
                    "CTime": "134500",
                    "CDiff": "980.00",
                    "CDiffRate": "2.27",
                    "CAmpRate": "2.07",
                    "CBestBidPrice": "44199.00",
                    "CBestBidSize": "7",
                    "CBestAskPrice": "44207.00",
                    "CBestAskSize": "2",
                },
            ],
        },
    }


def sample_daily_html() -> str:
    return """
    <table>
      <tr>
        <th>契約</th><th>到期月份</th><th>開盤價</th><th>最高價</th><th>最低價</th>
        <th>最後成交價</th><th>漲跌價</th><th>漲跌%</th><th>盤後交易時段成交量</th>
        <th>一般交易時段成交量</th><th>合計成交量</th><th>結算價</th><th>未沖銷契約量</th>
        <th>最後最佳買價</th><th>最後最佳賣價</th><th>歷史最高價</th><th>歷史最低價</th>
      </tr>
      <tr>
        <td>MTX</td><td>202606</td><td>44,938</td><td>44,939</td><td>44,044</td>
        <td>44,199</td><td>▲980</td><td>▲2.27%</td><td>256,020</td>
        <td>153,072</td><td>409,092</td><td>44,217</td><td>25,847</td>
        <td>44,199</td><td>44,207</td><td>46,995</td><td>20,740</td>
      </tr>
      <tr>
        <td>MTX</td><td>202606W4</td><td>44,389</td><td>44,389</td><td>44,178</td>
        <td>44,311</td><td>▲1,043</td><td>▲2.41%</td><td>1</td>
        <td>4</td><td>5</td><td>44,229</td><td>1</td>
        <td>44,221</td><td>44,238</td><td>44,389</td><td>42,388</td>
      </tr>
      <tr>
        <td>TX</td><td>202606</td><td>44,929</td><td>44,931</td><td>44,045</td>
        <td>44,188</td><td>▲969</td><td>▲2.24%</td><td>88,271</td>
        <td>80,412</td><td>168,683</td><td>44,217</td><td>71,366</td>
        <td>44,189</td><td>44,200</td><td>46,994</td><td>20,819</td>
      </tr>
    </table>
    """


class TaiwanFuturesParserTests(unittest.TestCase):
    def test_parse_payload_keeps_monthly_contracts_only(self) -> None:
        quotes = parse_taifex_mis_quote_payload(
            symbol="MXF",
            session="regular",
            payload=sample_mxf_payload(),
            fetched_at=datetime(2026, 6, 12, 13, 45, tzinfo=TAIWAN_TZ),
        )

        self.assertEqual(len(quotes), 1)
        quote = quotes[0]
        self.assertEqual(quote["symbol"], "MXF")
        self.assertEqual(quote["product_code"], "MTX")
        self.assertEqual(quote["contract_symbol"], "MXFF6-F")
        self.assertEqual(quote["contract_month"], "202606")
        self.assertEqual(quote["session"], "regular")
        self.assertEqual(quote["last_price"], 44199.0)
        self.assertEqual(quote["total_volume"], 408801)

    def test_select_active_quote_prefers_liquid_contract(self) -> None:
        payload = sample_mxf_payload()
        payload["RtData"]["QuoteList"].append(
            {
                "SymbolID": "MXFG6-F",
                "DispCName": "小臺指期076",
                "DispEName": "MTX076",
                "CTotalVolume": "23357",
                "CLastPrice": "44316.00",
                "CDate": "20260612",
                "CTime": "134453",
            }
        )
        quotes = parse_taifex_mis_quote_payload(
            symbol="MXF",
            session="regular",
            payload=payload,
        )

        active = select_active_taiwan_futures_quote(quotes)

        self.assertIsNotNone(active)
        self.assertEqual(active["contract_symbol"], "MXFF6-F")

    def test_parse_daily_market_html_keeps_monthly_contracts_only(self) -> None:
        rows = parse_taifex_daily_market_html(
            symbol="MXF",
            trade_date=date(2026, 6, 12),
            html_text=sample_daily_html(),
            source_url="https://example.test/daily",
            fetched_at=datetime(2026, 6, 12, 14, 0, tzinfo=TAIWAN_TZ),
        )

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["symbol"], "MXF")
        self.assertEqual(row["product_code"], "MTX")
        self.assertEqual(row["contract_symbol"], "MTX202606")
        self.assertEqual(row["contract_month"], "202606")
        self.assertEqual(row["close_price"], 44199.0)
        self.assertEqual(row["change"], 980.0)
        self.assertEqual(row["change_pct"], 2.27)
        self.assertEqual(row["after_hours_volume"], 256020)
        self.assertEqual(row["regular_volume"], 153072)
        self.assertEqual(row["total_volume"], 409092)
        self.assertEqual(row["open_interest"], 25847)


class TaiwanFuturesPersistenceTests(unittest.TestCase):
    def test_refresh_upserts_quote_and_one_minute_bar(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        try:
            with Session(engine) as db:
                from app.market import tw_futures

                original_fetch = tw_futures.fetch_taifex_mis_quote_payload
                try:
                    tw_futures.fetch_taifex_mis_quote_payload = lambda **kwargs: sample_mxf_payload()
                    rows = refresh_taiwan_futures_quotes(
                        db=db,
                        symbols=["MXF"],
                        session="regular",
                    )
                finally:
                    tw_futures.fetch_taifex_mis_quote_payload = original_fetch

                self.assertEqual(len(rows), 1)
                self.assertEqual(db.query(TaiwanFuturesQuoteSnapshot).count(), 1)
                self.assertEqual(db.query(TaiwanFuturesIntradayBar).count(), 1)
                bar = db.query(TaiwanFuturesIntradayBar).one()
                self.assertEqual(bar.symbol, "MXF")
                self.assertEqual(bar.contract_month, "202606")
                self.assertEqual(bar.close_price, 44199.0)
        finally:
            engine.dispose()

    def test_refresh_daily_bars_upserts_and_lists_active_monthly_contract(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        try:
            with Session(engine) as db:
                from app.market import tw_futures

                original_fetch = tw_futures.fetch_taifex_daily_market_html
                try:
                    tw_futures.fetch_taifex_daily_market_html = lambda **kwargs: (
                        sample_daily_html(),
                        "https://example.test/daily",
                    )
                    rows = refresh_taiwan_futures_daily_bars(
                        db=db,
                        symbols=["MXF"],
                        start_date=date(2026, 6, 12),
                        end_date=date(2026, 6, 12),
                    )
                finally:
                    tw_futures.fetch_taifex_daily_market_html = original_fetch

                self.assertEqual(len(rows), 1)
                self.assertEqual(db.query(TaiwanFuturesDailyBar).count(), 1)

                listed_rows = list_taiwan_futures_daily_bars(
                    db=db,
                    symbol="MXF",
                    limit=10,
                )
                self.assertEqual(len(listed_rows), 1)
                self.assertEqual(listed_rows[0].contract_month, "202606")
                self.assertEqual(listed_rows[0].close_price, 44199.0)
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
