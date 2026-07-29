from __future__ import annotations

from datetime import date, datetime
import unittest
from unittest.mock import patch
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
    TaiwanFuturesFetchError,
    build_taiwan_futures_market_status,
    build_taiwan_futures_quote_freshness,
    fetch_taiwan_futures_quotes,
    get_latest_taiwan_futures_quotes,
    list_taiwan_futures_intraday_bars,
    list_taiwan_futures_daily_bars,
    normalize_taiwan_futures_symbols,
    parse_taifex_daily_market_html,
    parse_taifex_mis_intraday_payload,
    parse_taifex_mis_quote_payload,
    refresh_taiwan_futures_daily_bars,
    refresh_taiwan_futures_intraday_bars,
    refresh_taiwan_futures_quotes,
    resolve_taiwan_futures_daily_refresh_window,
    select_active_taiwan_futures_quote,
    taiwan_futures_quote_to_dict,
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


def sample_mxf_after_hours_payload() -> dict:
    return {
        "RtCode": "0",
        "RtMsg": "",
        "RtData": {
            "QuoteCount": "3",
            "QuoteList": [
                {
                    "SymbolID": "MXF-P",
                    "DispEName": "MXF",
                    "CDate": "20260717",
                    "CTime": "",
                    "CLastPrice": "",
                },
                {
                    "SymbolID": "MX4H6-M",
                    "DispEName": "MX4W4086",
                    "CDate": "20260717",
                    "CTime": "191401",
                    "CLastPrice": "42898.00",
                    "CTotalVolume": "29",
                },
                {
                    "SymbolID": "MXFH6-M",
                    "DispEName": "MTX086",
                    "COpenPrice": "42700.00",
                    "CHighPrice": "43045.00",
                    "CLowPrice": "42173.00",
                    "CLastPrice": "42901.00",
                    "CRefPrice": "42604.00",
                    "CTotalVolume": "76688",
                    "CDate": "20260717",
                    "CTime": "191441",
                    "CDiff": "297.00",
                    "CDiffRate": "0.70",
                    "CBestBidPrice": "42900.00",
                    "CBestBidSize": "3",
                    "CBestAskPrice": "42901.00",
                    "CBestAskSize": "5",
                },
            ],
        },
    }


def sample_txf_after_hours_chart_payload() -> dict:
    return {
        "RtCode": "0",
        "RtMsg": "",
        "RtData": {
            "SymbolID": "TXFH6-M",
            "Info": {
                "Status": "0",
                "Sessions": [{"Start": "1500", "End": "0500"}],
            },
            "Quote": {
                "CDate": "20260717",
                "CRefPrice": "42604.00",
                "CTotalVolume": "27364",
            },
            "Ticks": [
                ["150100", "42700.00", "42857.00", "42700.00", "42780.00", "607"],
                ["235900", "42800.00", "42820.00", "42790.00", "42810.00", "25"],
                ["000100", "42810.00", "42830.00", "42805.00", "42825.00", "18"],
                ["bad", "1", "1", "1", "1", "1"],
                ["060000", "42825.00", "42825.00", "42825.00", "42825.00", "1"],
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
    def test_normalize_symbols_accepts_common_aliases(self) -> None:
        self.assertEqual(
            normalize_taiwan_futures_symbols(["TX", "大台", "小台", "微台"]),
            ["TXF", "MXF", "TMF"],
        )

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

    def test_parse_payload_accepts_after_hours_monthly_contract_suffix(self) -> None:
        quotes = parse_taifex_mis_quote_payload(
            symbol="MXF",
            session="after_hours",
            payload=sample_mxf_after_hours_payload(),
            fetched_at=datetime(2026, 7, 17, 19, 15, tzinfo=TAIWAN_TZ),
        )

        self.assertEqual(len(quotes), 1)
        quote = quotes[0]
        self.assertEqual(quote["contract_symbol"], "MXFH6-M")
        self.assertEqual(quote["contract_month"], "202608")
        self.assertEqual(quote["session"], "after_hours")
        self.assertEqual(quote["last_price"], 42901.0)
        self.assertEqual(quote["total_volume"], 76688)

    def test_parse_after_hours_quote_advances_calendar_date_after_midnight(self) -> None:
        payload = sample_mxf_after_hours_payload()
        payload["RtData"]["QuoteList"][2]["CTime"] = "045958"

        quotes = parse_taifex_mis_quote_payload(
            symbol="MXF",
            session="after_hours",
            payload=payload,
            fetched_at=datetime(2026, 7, 18, 5, 0, tzinfo=TAIWAN_TZ),
        )

        self.assertEqual(len(quotes), 1)
        self.assertEqual(quotes[0]["trade_date"], date(2026, 7, 17))
        self.assertEqual(
            quotes[0]["quote_time"],
            datetime(2026, 7, 18, 4, 59, 58, tzinfo=TAIWAN_TZ),
        )

    def test_fetch_rejects_empty_after_hours_projection(self) -> None:
        with patch(
            "app.market.tw_futures.fetch_taifex_mis_quote_payload",
            return_value=sample_mxf_payload(),
        ):
            with self.assertRaisesRegex(
                TaiwanFuturesFetchError,
                "no usable after_hours monthly quote",
            ):
                fetch_taiwan_futures_quotes(
                    symbols=["MXF"],
                    session="after_hours",
                    provider="taifex_mis",
                )

    def test_parse_intraday_payload_keeps_minute_ohlc_and_crosses_midnight(self) -> None:
        bars = parse_taifex_mis_intraday_payload(
            symbol="TXF",
            session="after_hours",
            contract_symbol="TXFH6-M",
            contract_month="202608",
            payload=sample_txf_after_hours_chart_payload(),
            fetched_at=datetime(2026, 7, 17, 20, 34, tzinfo=TAIWAN_TZ),
        )

        self.assertEqual(len(bars), 3)
        self.assertEqual(bars[0]["bar_time"], datetime(2026, 7, 17, 15, 1, tzinfo=TAIWAN_TZ))
        self.assertEqual(bars[-1]["bar_time"], datetime(2026, 7, 18, 0, 1, tzinfo=TAIWAN_TZ))
        self.assertEqual(bars[0]["open_price"], 42700.0)
        self.assertEqual(bars[0]["high_price"], 42857.0)
        self.assertEqual(bars[0]["total_volume"], 607)
        self.assertEqual(bars[0]["source"], "TAIFEX MIS 1-minute chart")

    def test_parse_intraday_payload_rejects_wrong_session_contract(self) -> None:
        with self.assertRaisesRegex(TaiwanFuturesFetchError, "does not match"):
            parse_taifex_mis_intraday_payload(
                symbol="TXF",
                session="after_hours",
                contract_symbol="TXFH6-F",
                contract_month="202608",
                payload=sample_txf_after_hours_chart_payload(),
            )

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


class TaiwanFuturesMarketStatusTests(unittest.TestCase):
    def test_weekend_status_reports_last_session_and_next_regular_open(self) -> None:
        status = build_taiwan_futures_market_status(
            now=datetime(2026, 7, 18, 17, 3, tzinfo=TAIWAN_TZ)
        )

        self.assertFalse(status["is_open"])
        self.assertEqual(status["status"], "closed")
        self.assertEqual(status["reason"], "weekend")
        self.assertEqual(status["last_session"], "after_hours")
        self.assertEqual(
            status["last_session_end_at"],
            datetime(2026, 7, 18, 5, 0, tzinfo=TAIWAN_TZ),
        )
        self.assertEqual(status["next_session"], "regular")
        self.assertEqual(
            status["next_session_start_at"],
            datetime(2026, 7, 20, 8, 45, tzinfo=TAIWAN_TZ),
        )

    def test_after_hours_session_remains_open_after_midnight(self) -> None:
        status = build_taiwan_futures_market_status(
            now=datetime(2026, 7, 18, 4, 0, tzinfo=TAIWAN_TZ)
        )

        self.assertTrue(status["is_open"])
        self.assertEqual(status["current_session"], "after_hours")
        self.assertEqual(
            status["current_session_start_at"],
            datetime(2026, 7, 17, 15, 0, tzinfo=TAIWAN_TZ),
        )
        self.assertEqual(
            status["current_session_end_at"],
            datetime(2026, 7, 18, 5, 0, tzinfo=TAIWAN_TZ),
        )

    def test_weekday_between_sessions_reports_next_after_hours_open(self) -> None:
        status = build_taiwan_futures_market_status(
            now=datetime(2026, 7, 20, 14, 15, tzinfo=TAIWAN_TZ)
        )

        self.assertFalse(status["is_open"])
        self.assertEqual(status["phase"], "between_sessions")
        self.assertEqual(status["next_session"], "after_hours")
        self.assertEqual(
            status["next_session_start_at"],
            datetime(2026, 7, 20, 15, 0, tzinfo=TAIWAN_TZ),
        )

    def test_latest_completed_session_quote_is_closed_not_stale(self) -> None:
        row = TaiwanFuturesQuoteSnapshot(
            provider="taifex_mis",
            market="TAIFEX",
            symbol="TXF",
            product_code="TX",
            product_name="大台 台指期",
            contract_symbol="TXFH6-M",
            contract_month="202608",
            session="after_hours",
            trade_date=date(2026, 7, 17),
            quote_time=datetime(2026, 7, 17, 4, 59, 58, tzinfo=TAIWAN_TZ),
            last_price=43481,
            source="test",
        )

        freshness = build_taiwan_futures_quote_freshness(
            row,
            expected_session="auto",
            now=datetime(2026, 7, 18, 17, 3, tzinfo=TAIWAN_TZ),
        )

        self.assertEqual(freshness["status"], "closed")
        self.assertFalse(freshness["is_live"])
        self.assertFalse(freshness["is_stale"])
        self.assertEqual(freshness["last_session_quote_lag_seconds"], 2)
        self.assertFalse(freshness["market_status"]["is_open"])
        self.assertIn("週末休市", freshness["message"])
        self.assertIn("07/20 08:45", freshness["message"])

    def test_older_quote_remains_stale_while_market_is_closed(self) -> None:
        row = TaiwanFuturesQuoteSnapshot(
            provider="taifex_mis",
            market="TAIFEX",
            symbol="TXF",
            product_code="TX",
            product_name="大台 台指期",
            contract_symbol="TXFH6-M",
            contract_month="202608",
            session="after_hours",
            trade_date=date(2026, 7, 16),
            quote_time=datetime(2026, 7, 16, 23, 59, 30, tzinfo=TAIWAN_TZ),
            last_price=42604,
            source="test",
        )

        freshness = build_taiwan_futures_quote_freshness(
            row,
            expected_session="auto",
            now=datetime(2026, 7, 18, 17, 3, tzinfo=TAIWAN_TZ),
        )

        self.assertEqual(freshness["status"], "stale")
        self.assertTrue(freshness["is_stale"])


class TaiwanFuturesPersistenceTests(unittest.TestCase):
    def test_latest_quote_recovers_legacy_after_midnight_taifex_timestamp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        try:
            with Session(engine) as db:
                db.add_all(
                    [
                        TaiwanFuturesQuoteSnapshot(
                            provider="taifex_mis",
                            market="TAIFEX",
                            symbol="TXF",
                            product_code="TX",
                            product_name="大台 台指期",
                            contract_symbol="TXFH6-M",
                            contract_month="202608",
                            session="after_hours",
                            trade_date=date(2026, 7, 17),
                            quote_time=datetime(2026, 7, 17, 23, 59, 30),
                            last_price=43576,
                            source="test",
                            fetched_at=datetime(2026, 7, 17, 23, 59, 34),
                        ),
                        TaiwanFuturesQuoteSnapshot(
                            provider="taifex_mis",
                            market="TAIFEX",
                            symbol="TXF",
                            product_code="TX",
                            product_name="大台 台指期",
                            contract_symbol="TXFH6-M",
                            contract_month="202608",
                            session="after_hours",
                            trade_date=date(2026, 7, 17),
                            quote_time=datetime(2026, 7, 17, 4, 59, 58),
                            last_price=43481,
                            source="test",
                            fetched_at=datetime(2026, 7, 18, 5, 0, 4),
                        ),
                    ]
                )
                db.commit()

                rows = get_latest_taiwan_futures_quotes(db=db, symbols=["TXF"])

                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].last_price, 43481)
                payload = taiwan_futures_quote_to_dict(rows[0])
                self.assertEqual(
                    payload["quote_time"],
                    datetime(2026, 7, 18, 4, 59, 58, tzinfo=TAIWAN_TZ),
                )
        finally:
            engine.dispose()

    def test_quote_dict_marks_session_mismatch_cache(self) -> None:
        row = TaiwanFuturesQuoteSnapshot(
            id=1,
            provider="taifex_mis",
            market="TAIFEX",
            symbol="TXF",
            product_code="TX",
            product_name="大台 台指期",
            contract_symbol="TXFF6-F",
            contract_month="202606",
            session="regular",
            trade_date=date(2026, 6, 15),
            quote_time=datetime(2026, 6, 15, 13, 44, tzinfo=TAIWAN_TZ),
            last_price=45580,
            source="test",
            fetched_at=datetime(2026, 6, 15, 21, 30, tzinfo=TAIWAN_TZ),
            created_at=datetime(2026, 6, 15, 21, 30, tzinfo=TAIWAN_TZ),
            updated_at=datetime(2026, 6, 15, 21, 30, tzinfo=TAIWAN_TZ),
        )

        payload = taiwan_futures_quote_to_dict(
            row,
            expected_session="after_hours",
        )

        self.assertEqual(payload["freshness"]["status"], "session_mismatch")
        self.assertTrue(payload["freshness"]["is_session_mismatch"])
        self.assertEqual(payload["freshness"]["expected_session"], "after_hours")
        self.assertIn("預期夜盤", payload["freshness"]["message"])

    def test_kgi_provider_slot_reports_clear_error_before_adapter_is_wired(self) -> None:
        from app.market import tw_futures

        original_configured_settings = tw_futures._configured_kgi_settings
        try:
            tw_futures._configured_kgi_settings = lambda: []
            with self.assertRaises(TaiwanFuturesFetchError) as context:
                fetch_taiwan_futures_quotes(
                    symbols=["TXF"],
                    provider="kgi",
                )
        finally:
            tw_futures._configured_kgi_settings = original_configured_settings

        self.assertIn("KGI Taiwan futures provider is selected", str(context.exception))

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
                self.assertIsNone(bar.total_volume)
        finally:
            engine.dispose()

    def test_refresh_intraday_bars_upserts_full_chart_idempotently(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        try:
            with Session(engine) as db:
                db.add(
                    TaiwanFuturesQuoteSnapshot(
                        provider="taifex_mis",
                        market="TAIFEX",
                        symbol="TXF",
                        product_code="TX",
                        product_name="Taiwan Index Futures",
                        contract_symbol="TXFH6-M",
                        contract_month="202608",
                        session="after_hours",
                        trade_date=date(2026, 7, 17),
                        quote_time=datetime(2026, 7, 17, 20, 34, tzinfo=TAIWAN_TZ),
                        last_price=42879,
                        source="test",
                    )
                )
                db.commit()

                with patch(
                    "app.market.tw_futures.fetch_taifex_mis_intraday_payload",
                    return_value=sample_txf_after_hours_chart_payload(),
                ):
                    first_rows = refresh_taiwan_futures_intraday_bars(
                        db=db,
                        symbol="TXF",
                        session="after_hours",
                    )
                    second_rows = refresh_taiwan_futures_intraday_bars(
                        db=db,
                        symbol="TXF",
                        session="after_hours",
                    )

                self.assertEqual(len(first_rows), 3)
                self.assertEqual(len(second_rows), 3)
                self.assertEqual(db.query(TaiwanFuturesIntradayBar).count(), 3)
                first_bar = (
                    db.query(TaiwanFuturesIntradayBar)
                    .order_by(TaiwanFuturesIntradayBar.bar_time.asc())
                    .first()
                )
                self.assertIsNotNone(first_bar)
                self.assertEqual(first_bar.total_volume, 607)
                self.assertEqual(first_bar.source, "TAIFEX MIS 1-minute chart")
        finally:
            engine.dispose()

    def test_latest_quotes_can_filter_by_provider(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        try:
            with Session(engine) as db:
                db.add_all(
                    [
                        TaiwanFuturesQuoteSnapshot(
                            provider="taifex_mis",
                            market="TAIFEX",
                            symbol="TXF",
                            product_code="TX",
                            product_name="大台 台指期",
                            contract_symbol="TXFF6-F",
                            contract_month="202606",
                            session="regular",
                            trade_date=date(2026, 6, 15),
                            quote_time=datetime(2026, 6, 15, 13, 44, tzinfo=TAIWAN_TZ),
                            last_price=45580,
                            source="test",
                        ),
                        TaiwanFuturesQuoteSnapshot(
                            provider="kgi",
                            market="TAIFEX",
                            symbol="TXF",
                            product_code="TX",
                            product_name="大台 台指期",
                            contract_symbol="TXFR1",
                            contract_month="202606",
                            session="after_hours",
                            trade_date=date(2026, 6, 15),
                            quote_time=datetime(2026, 6, 15, 21, 30, tzinfo=TAIWAN_TZ),
                            last_price=45620,
                            source="test",
                        ),
                    ]
                )
                db.commit()

                taifex_rows = get_latest_taiwan_futures_quotes(
                    db=db,
                    symbols=["TXF"],
                    provider="taifex_mis",
                )
                kgi_rows = get_latest_taiwan_futures_quotes(
                    db=db,
                    symbols=["TXF"],
                    provider="kgi",
                )
                auto_rows = get_latest_taiwan_futures_quotes(
                    db=db,
                    symbols=["TXF"],
                    provider="auto",
                )

                self.assertEqual(taifex_rows[0].provider, "taifex_mis")
                self.assertEqual(taifex_rows[0].last_price, 45580)
                self.assertEqual(kgi_rows[0].provider, "kgi")
                self.assertEqual(kgi_rows[0].last_price, 45620)
                self.assertEqual(auto_rows[0].provider, "kgi")
        finally:
            engine.dispose()

    def test_intraday_bars_default_to_latest_trade_date(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        try:
            with Session(engine) as db:
                db.add_all(
                    [
                        TaiwanFuturesIntradayBar(
                            provider="taifex_mis",
                            market="TAIFEX",
                            symbol="MXF",
                            product_code="MTX",
                            product_name="小台 台指期",
                            contract_symbol="MXFF6-F",
                            contract_month="202606",
                            session="regular",
                            interval="1m",
                            bar_time=datetime(2026, 6, 12, 13, 45, tzinfo=TAIWAN_TZ),
                            open_price=44199,
                            high_price=44199,
                            low_price=44199,
                            close_price=44199,
                            total_volume=408801,
                            source="test",
                        ),
                        TaiwanFuturesIntradayBar(
                            provider="taifex_mis",
                            market="TAIFEX",
                            symbol="MXF",
                            product_code="MTX",
                            product_name="小台 台指期",
                            contract_symbol="MXFF6-F",
                            contract_month="202606",
                            session="regular",
                            interval="1m",
                            bar_time=datetime(2026, 6, 15, 9, 0, tzinfo=TAIWAN_TZ),
                            open_price=45000,
                            high_price=45000,
                            low_price=45000,
                            close_price=45000,
                            total_volume=100,
                            source="test",
                        ),
                        TaiwanFuturesIntradayBar(
                            provider="taifex_mis",
                            market="TAIFEX",
                            symbol="MXF",
                            product_code="MTX",
                            product_name="小台 台指期",
                            contract_symbol="MXFF6-F",
                            contract_month="202606",
                            session="regular",
                            interval="1m",
                            bar_time=datetime(2026, 6, 15, 9, 1, tzinfo=TAIWAN_TZ),
                            open_price=45010,
                            high_price=45010,
                            low_price=45010,
                            close_price=45010,
                            total_volume=120,
                            source="test",
                        ),
                    ]
                )
                db.commit()

                rows = list_taiwan_futures_intraday_bars(
                    db=db,
                    symbol="MXF",
                    limit=10,
                    session="regular",
                )

                self.assertEqual(len(rows), 2)
                self.assertEqual([row.bar_time.date() for row in rows], [date(2026, 6, 15), date(2026, 6, 15)])
        finally:
            engine.dispose()

    def test_intraday_bars_keep_night_session_together_across_midnight(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        try:
            with Session(engine) as db:
                common = {
                    "provider": "taifex_mis",
                    "market": "TAIFEX",
                    "symbol": "TXF",
                    "product_code": "TX",
                    "product_name": "Taiwan Index Futures",
                    "contract_symbol": "TXFH6-M",
                    "contract_month": "202608",
                    "interval": "1m",
                    "open_price": 42800,
                    "high_price": 42810,
                    "low_price": 42790,
                    "close_price": 42805,
                    "total_volume": 10,
                    "source": "test",
                }
                db.add_all(
                    [
                        TaiwanFuturesIntradayBar(
                            **common,
                            session="after_hours",
                            bar_time=datetime(2026, 7, 17, 23, 59, tzinfo=TAIWAN_TZ),
                        ),
                        TaiwanFuturesIntradayBar(
                            **common,
                            session="after_hours",
                            bar_time=datetime(2026, 7, 18, 0, 1, tzinfo=TAIWAN_TZ),
                        ),
                        TaiwanFuturesIntradayBar(
                            **{**common, "contract_symbol": "TXFH6-F"},
                            session="regular",
                            bar_time=datetime(2026, 7, 18, 9, 0, tzinfo=TAIWAN_TZ),
                        ),
                    ]
                )
                db.commit()

                rows = list_taiwan_futures_intraday_bars(
                    db=db,
                    symbol="TXF",
                    limit=10,
                    session="after_hours",
                )

                self.assertEqual(len(rows), 2)
                self.assertEqual(
                    [row.bar_time.hour for row in rows],
                    [23, 0],
                )
                self.assertTrue(all(row.session == "after_hours" for row in rows))
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

    def test_daily_refresh_window_excludes_current_trade_date_before_release(self) -> None:
        window = resolve_taiwan_futures_daily_refresh_window(
            start_date=date(2026, 7, 17),
            end_date=date(2026, 7, 20),
            now=datetime(2026, 7, 20, 13, 50, tzinfo=TAIWAN_TZ),
        )

        self.assertEqual(window["latest_released_trade_date"], date(2026, 7, 17))
        self.assertEqual(window["effective_end_date"], date(2026, 7, 17))
        self.assertTrue(window["skipped_unreleased_end_date"])

    def test_daily_refresh_window_allows_current_trade_date_after_release(self) -> None:
        window = resolve_taiwan_futures_daily_refresh_window(
            start_date=date(2026, 7, 17),
            end_date=date(2026, 7, 20),
            now=datetime(2026, 7, 20, 14, 31, tzinfo=TAIWAN_TZ),
        )

        self.assertEqual(window["latest_released_trade_date"], date(2026, 7, 20))
        self.assertEqual(window["effective_end_date"], date(2026, 7, 20))
        self.assertFalse(window["skipped_unreleased_end_date"])

    def test_daily_refresh_rejects_only_unreleased_trade_date(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        try:
            with Session(engine) as db:
                with self.assertRaisesRegex(ValueError, "official release window"):
                    refresh_taiwan_futures_daily_bars(
                        db=db,
                        symbols=["TXF"],
                        start_date=date(2026, 7, 20),
                        end_date=date(2026, 7, 20),
                        now=datetime(2026, 7, 20, 13, 50, tzinfo=TAIWAN_TZ),
                    )
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
