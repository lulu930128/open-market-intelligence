from __future__ import annotations

import unittest
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import (
    Base,
    MarketIndexDailyStat,
    TaiwanDerivativesLargeTraderDaily,
    TaiwanFuturesTermStructureDaily,
    TaiwanOptionChainDaily,
)
from app.jobs import backfill_tasks
from app.market import tw_derivatives
from app.market.providers import taifex


TRADE_DATE = date(2026, 7, 17)


def option_report_rows() -> list[dict[str, str]]:
    base = {
        "Date": "20260717",
        "Contract": "TXO",
        "ContractMonth(Week)": "202608",
        "Open": "5",
        "High": "6",
        "Low": "4",
        "Close": "5",
        "Volume": "100",
        "SettlementPrice": "5",
        "OpenInterest": "200",
        "BestBid": "4.5",
        "BestAsk": "5.5",
        "HistoricalHigh": "8",
        "HistoricalLow": "1",
        "TradingHalt": "",
        "TradingSession": "一般",
    }
    return [
        {**base, "StrikePrice": "100", "CallPut": "買權"},
        {**base, "StrikePrice": "100", "CallPut": "賣權"},
        {**base, "StrikePrice": "105", "CallPut": "買權", "SettlementPrice": "3"},
        {
            **base,
            "StrikePrice": "100",
            "CallPut": "買權",
            "TradingSession": "盤後",
            "SettlementPrice": "-",
        },
        {**base, "Contract": "TEO", "StrikePrice": "100", "CallPut": "買權"},
    ]


def delta_rows() -> list[dict[str, str]]:
    return [
        {
            "Contract": "TXO",
            "CallPut": "買權",
            "ContractMonth(Week)": "202608",
            "StrikePrice": "100.0",
            "Delta": "0.55",
            "ContractSettlementDay": "20260819",
        },
        {
            "Contract": "TXO",
            "CallPut": "賣權",
            "ContractMonth(Week)": "202608",
            "StrikePrice": "100.0",
            "Delta": "-0.45",
            "ContractSettlementDay": "20260819",
        },
        {
            "Contract": "TXO",
            "CallPut": "買權",
            "ContractMonth(Week)": "202608",
            "StrikePrice": "105.0",
            "Delta": "0.25",
            "ContractSettlementDay": "20260819",
        },
    ]


def futures_report_rows() -> list[dict[str, str]]:
    base = {
        "Date": "20260717",
        "Contract": "TX",
        "Open": "101",
        "High": "103",
        "Low": "99",
        "Last": "102",
        "SettlementPrice": "101",
        "OpenInterest": "1000",
        "TradingSession": "一般",
    }
    return [
        {**base, "ContractMonth(Week)": "202608"},
        {**base, "ContractMonth(Week)": "202609", "SettlementPrice": "103"},
        {**base, "ContractMonth(Week)": "202608/202609"},
        {**base, "ContractMonth(Week)": "202610", "TradingSession": "盤後"},
        {**base, "Contract": "MTX", "ContractMonth(Week)": "202608"},
    ]


def futures_large_trader_rows() -> list[dict[str, str]]:
    base = {
        "Date": "20260717",
        "Contract": "TX",
        "ContractName": "臺股期貨(TX+MTX/4)",
        "Top5Buy": "60",
        "Top5Sell": "55",
        "Top10Buy": "80",
        "Top10Sell": "75",
        "OIOfMarket": "100",
    }
    return [
        {**base, "SettlementMonth": "999912", "TypeOfTraders": "0"},
        {**base, "SettlementMonth": "999912", "TypeOfTraders": "1", "Top5Buy": "40"},
        {**base, "SettlementMonth": "666666", "TypeOfTraders": "0"},
    ]


def options_large_trader_rows() -> list[dict[str, str]]:
    base = {
        "Date": "20260717",
        "Contract": "TXO",
        "ContractName": "臺指",
        "SettlementMonth": "999912",
        "TypeOfTraders": "0",
        "Top5Buy": "50",
        "Top5Sell": "45",
        "Top10Buy": "70",
        "Top10Sell": "65",
        "OIOfMarket": "100",
    }
    return [
        {**base, "CallPut": "買權"},
        {**base, "CallPut": "賣權"},
    ]


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.encoding = None

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self.payload


class TaiwanDerivativesProviderTests(unittest.TestCase):
    def test_openapi_provider_uses_bounded_identity_and_validates_rows(self) -> None:
        calls: list[tuple[str, dict]] = []

        def fake_get(url: str, **kwargs):
            calls.append((url, kwargs))
            return FakeResponse([{"Date": "20260717"}])

        with patch.object(taifex, "get", side_effect=fake_get):
            rows = taifex.fetch_openapi_rows(
                "DailyMarketReportOpt",
                target="TXO",
                timeout_seconds=7,
            )

        self.assertEqual(rows, [{"Date": "20260717"}])
        self.assertEqual(calls[0][1]["provider"], "taifex")
        self.assertEqual(calls[0][1]["resource"], "options_daily_report")
        self.assertEqual(calls[0][1]["target"], "TXO")
        self.assertEqual(calls[0][1]["timeout_seconds"], 7)

        with self.assertRaisesRegex(ValueError, "Unsupported"):
            taifex.fetch_openapi_rows("not-a-dataset", target="TXO")


class TaiwanDerivativesParserTests(unittest.TestCase):
    def test_option_parser_joins_official_delta_and_derives_greeks(self) -> None:
        rows = tw_derivatives.parse_taifex_option_chain_rows(
            option_report_rows(),
            delta_rows(),
            spot_close=100,
        )

        self.assertEqual(len(rows), 4)
        call = next(
            row
            for row in rows
            if row["option_type"] == "call"
            and row["strike_price"] == 100
            and row["session"] == "regular"
        )
        self.assertEqual(call["official_delta"], 0.55)
        self.assertEqual(call["expiry_date"], date(2026, 8, 19))
        self.assertEqual(call["calculation_status"], "ready_derived")
        self.assertGreater(call["implied_volatility_pct"], 0)
        self.assertGreater(call["gamma"], 0)
        self.assertGreater(call["vega_per_vol_pct"], 0)
        self.assertLess(call["theta_per_day"], 0)
        self.assertEqual(call["risk_free_rate"], 0)

    def test_option_parser_keeps_chain_when_spot_is_missing(self) -> None:
        rows = tw_derivatives.parse_taifex_option_chain_rows(
            option_report_rows(),
            delta_rows(),
            spot_close=None,
        )
        self.assertTrue(rows)
        self.assertTrue(all(row["calculation_status"] == "missing_spot" for row in rows))
        self.assertTrue(all(row["implied_volatility_pct"] is None for row in rows))

    def test_large_trader_parser_maps_official_bucket_and_subset_semantics(self) -> None:
        rows = tw_derivatives.parse_taifex_large_trader_rows(
            futures_large_trader_rows(),
            instrument_type="futures",
        )
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["settlement_bucket"], "all_contracts")
        self.assertEqual(rows[0]["trader_type"], "all_traders")
        self.assertEqual(rows[1]["trader_type"], "specific_institution")
        self.assertEqual(rows[2]["settlement_bucket"], "weekly")

    def test_term_structure_parser_uses_regular_monthly_contracts_only(self) -> None:
        rows = tw_derivatives.parse_taifex_term_structure_rows(
            futures_report_rows(),
            spot_close=100,
        )
        self.assertEqual([row["contract_month"] for row in rows], ["202608", "202609"])
        self.assertEqual(rows[0]["basis_points"], 1)
        self.assertEqual(rows[0]["basis_pct"], 1)
        self.assertEqual(rows[0]["calculation_status"], "ready")


class TaiwanDerivativesPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()

    @staticmethod
    def payload_for(dataset: str, *, target: str):
        del target
        return {
            tw_derivatives.OPTION_REPORT_DATASET: option_report_rows(),
            tw_derivatives.OPTION_DELTA_DATASET: delta_rows(),
            tw_derivatives.FUTURES_REPORT_DATASET: futures_report_rows(),
            tw_derivatives.FUTURES_LARGE_TRADER_DATASET: futures_large_trader_rows(),
            tw_derivatives.OPTIONS_LARGE_TRADER_DATASET: options_large_trader_rows(),
        }[dataset]

    def test_refresh_is_bounded_idempotent_and_builds_summary(self) -> None:
        with self.Session() as db:
            db.add(
                MarketIndexDailyStat(
                    index_id="TAIEX",
                    market="tw",
                    trade_date=TRADE_DATE,
                    close_value=100,
                    source="test",
                )
            )
            db.commit()

            calls: list[str] = []

            def fake_fetch(dataset: str, *, target: str):
                calls.append(dataset)
                return self.payload_for(dataset, target=target)

            with (
                patch.object(tw_derivatives, "fetch_openapi_rows", side_effect=fake_fetch),
                patch.object(
                    tw_derivatives,
                    "expected_taiwan_derivatives_date",
                    return_value=TRADE_DATE,
                ),
            ):
                first = tw_derivatives.refresh_taiwan_derivatives(db)
                second = tw_derivatives.refresh_taiwan_derivatives(db)

            self.assertEqual(first["provider_request_count"], 5)
            self.assertEqual(first["failed_request_count"], 0)
            self.assertFalse(first["is_stale"])
            self.assertEqual(first["stale_datasets"], [])
            self.assertEqual(
                first["unverified_date_datasets"],
                [tw_derivatives.OPTION_DELTA_DATASET],
            )
            self.assertEqual(second["status"], "ready")
            self.assertEqual(len(calls), 10)
            self.assertEqual(db.query(TaiwanOptionChainDaily).count(), 4)
            self.assertEqual(db.query(TaiwanDerivativesLargeTraderDaily).count(), 5)
            self.assertEqual(db.query(TaiwanFuturesTermStructureDaily).count(), 2)

            db.add(
                TaiwanOptionChainDaily(
                    provider=tw_derivatives.PROVIDER,
                    trade_date=TRADE_DATE,
                    product_code="TXO",
                    contract_month="202607F3",
                    expiry_date=TRADE_DATE,
                    strike_price=100,
                    option_type="call",
                    session="regular",
                    calculation_status="expiry_reached",
                    source="test",
                )
            )
            db.commit()

            summary = tw_derivatives.build_taiwan_derivatives_summary(
                db,
                option_strike_limit=3,
            )
            self.assertEqual(summary["as_of"], TRADE_DATE)
            self.assertEqual(summary["stale"], [])
            self.assertEqual(summary["options_chain"]["contract_month"], "202608")
            self.assertTrue(summary["options_chain"]["rows"])
            self.assertEqual(summary["large_traders"]["status"], "ready")
            self.assertEqual(summary["term_structure"]["curve_shape"], "contango")

    def test_read_helpers_are_bounded_and_do_not_refresh(self) -> None:
        with self.Session() as db:
            self.assertEqual(tw_derivatives.list_taiwan_option_chain(db), [])
            self.assertEqual(tw_derivatives.list_taiwan_large_traders(db), [])
            self.assertEqual(tw_derivatives.list_taiwan_term_structure(db), [])
            with self.assertRaises(ValueError):
                tw_derivatives.list_taiwan_option_chain(db, limit=501)
            with self.assertRaises(ValueError):
                tw_derivatives.list_taiwan_term_structure(db, limit=13)

    def test_refresh_is_partial_when_one_official_dataset_fails(self) -> None:
        with self.Session() as db:
            db.add(
                MarketIndexDailyStat(
                    index_id="TAIEX",
                    market="tw",
                    trade_date=TRADE_DATE,
                    close_value=100,
                    source="test",
                )
            )
            db.commit()

            def fake_fetch(dataset: str, *, target: str):
                if dataset == tw_derivatives.OPTION_DELTA_DATASET:
                    raise RuntimeError("delta unavailable")
                return self.payload_for(dataset, target=target)

            with (
                patch.object(tw_derivatives, "fetch_openapi_rows", side_effect=fake_fetch),
                patch.object(tw_derivatives, "observe_provider_fallback", return_value=True),
                patch.object(
                    tw_derivatives,
                    "expected_taiwan_derivatives_date",
                    return_value=TRADE_DATE,
                ),
            ):
                result = tw_derivatives.refresh_taiwan_derivatives(db)

            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["failed_request_count"], 1)
            self.assertIn(tw_derivatives.OPTION_DELTA_DATASET, result["errors"])
            self.assertGreater(db.query(TaiwanOptionChainDaily).count(), 0)
            self.assertTrue(
                all(
                    row.official_delta is None
                    for row in db.query(TaiwanOptionChainDaily).all()
                )
            )

    def test_refresh_is_partial_when_one_dataset_has_not_reached_expected_date(self) -> None:
        with self.Session() as db:
            db.add(
                MarketIndexDailyStat(
                    index_id="TAIEX",
                    market="tw",
                    trade_date=TRADE_DATE,
                    close_value=100,
                    source="test",
                )
            )
            db.commit()

            def fake_fetch(dataset: str, *, target: str):
                rows = [dict(row) for row in self.payload_for(dataset, target=target)]
                if dataset == tw_derivatives.FUTURES_REPORT_DATASET:
                    for row in rows:
                        row["Date"] = "20260716"
                return rows

            with (
                patch.object(tw_derivatives, "fetch_openapi_rows", side_effect=fake_fetch),
                patch.object(
                    tw_derivatives,
                    "expected_taiwan_derivatives_date",
                    return_value=TRADE_DATE,
                ),
            ):
                result = tw_derivatives.refresh_taiwan_derivatives(db)

            self.assertEqual(result["status"], "partial")
            self.assertTrue(result["is_stale"])
            self.assertEqual(
                result["stale_datasets"],
                [tw_derivatives.FUTURES_REPORT_DATASET],
            )
            self.assertEqual(
                result["dataset_trade_dates"][tw_derivatives.FUTURES_REPORT_DATASET],
                date(2026, 7, 16),
            )

    def test_scheduled_job_rejects_partial_provider_result(self) -> None:
        result = {
            "status": "partial",
            "as_of": TRADE_DATE,
            "successful_request_count": 4,
            "errors": {tw_derivatives.OPTION_DELTA_DATASET: "delta unavailable"},
        }

        with patch.object(backfill_tasks, "run_tracked_job") as tracked:
            backfill_tasks.run_taiwan_derivatives_refresh_job(61, TRADE_DATE)

        worker = tracked.call_args.args[1]
        with (
            patch.object(
                backfill_tasks,
                "refresh_taiwan_derivatives",
                return_value=result,
            ),
            self.assertRaisesRegex(
                tw_derivatives.TaiwanDerivativesFetchError,
                "incomplete",
            ),
        ):
            worker(SimpleNamespace(), Mock())

    def test_scheduled_job_rejects_stale_provider_result(self) -> None:
        expected_date = TRADE_DATE + timedelta(days=1)
        result = {
            "status": "ready",
            "as_of": TRADE_DATE,
            "successful_request_count": 5,
            "errors": {},
        }

        with patch.object(backfill_tasks, "run_tracked_job") as tracked:
            backfill_tasks.run_taiwan_derivatives_refresh_job(62, expected_date)

        worker = tracked.call_args.args[1]
        with (
            patch.object(
                backfill_tasks,
                "refresh_taiwan_derivatives",
                return_value=result,
            ),
            self.assertRaisesRegex(
                tw_derivatives.TaiwanDerivativesFetchError,
                "expected trade date",
            ),
        ):
            worker(SimpleNamespace(), Mock())


if __name__ == "__main__":
    unittest.main()
