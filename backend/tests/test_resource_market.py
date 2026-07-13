from __future__ import annotations

import json
import unittest
import warnings
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db.models import Base, ProviderEvent, ResourceOhlcvBar, ResourceQuoteSnapshot, utc_now
from app.resource_market import service as resource_service
from app.resource_market.contract import list_resource_instruments, resource_provider_contract
from app.resource_market.maintenance import compact_resource_ohlcv_raw_payloads
from app.resource_market.service import (
    list_latest_resource_quotes,
    list_resource_ohlcv_bars,
    refresh_resource_market_snapshot,
)
from app.resource_market.source_health import build_resource_source_health
from app.resource_market.sources import (
    YAHOO_RANGE_BY_INTERVAL,
    normalize_resource_interval,
    parse_yahoo_ohlcv_records,
)


class ResourceMarketTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_resource_contract_is_watch_only_with_default_commodities(self) -> None:
        contract = resource_provider_contract()
        symbols = {instrument["symbol"] for instrument in contract["instruments"]}

        self.assertFalse(contract["execution_enabled"])
        self.assertFalse(contract["ai_execution_enabled"])
        self.assertEqual(contract["trade_candidate_symbols"], [])
        self.assertIn("crypto", {folder["key"] for folder in contract["root_folders"]})
        self.assertIn("commodity", {folder["key"] for folder in contract["root_folders"]})
        self.assertTrue({"GC", "SI", "HG", "CL"}.issubset(symbols))
        self.assertTrue(all(not row["tradable"] for row in contract["instruments"]))
        self.assertTrue(all(row["provider"] == "yahoo_chart" for row in contract["instruments"]))
        self.assertTrue(all(row["quote_asset"] == "USD" for row in contract["instruments"]))
        self.assertEqual(
            contract["chart_profiles"]["overview"]["intervals"],
            ["1m", "1d", "1w", "1M"],
        )
        self.assertIn("5m", contract["chart_profiles"]["professional"]["intervals"])
        self.assertIn("30m", contract["ohlcv_intervals"]["yahoo_chart"])

    def test_resource_instrument_filters_normalize_symbols(self) -> None:
        matches = list_resource_instruments(group="metals", symbol="hg")

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].display_name, "銅")
        self.assertEqual(matches[0].symbol, "HG")

    def test_resource_interval_supports_overview_and_professional_modes(self) -> None:
        self.assertEqual(normalize_resource_interval("1m"), "1m")
        self.assertEqual(normalize_resource_interval("5m"), "5m")
        self.assertEqual(normalize_resource_interval("15m"), "15m")
        self.assertEqual(normalize_resource_interval("30m"), "30m")
        self.assertEqual(normalize_resource_interval("1h"), "1h")
        self.assertEqual(normalize_resource_interval("1d"), "1d")
        self.assertEqual(normalize_resource_interval("1w"), "1w")
        self.assertEqual(normalize_resource_interval("1M"), "1M")

    def test_resource_yahoo_ranges_cover_crypto_like_chart_depth(self) -> None:
        self.assertEqual(YAHOO_RANGE_BY_INTERVAL["5m"], "1mo")
        self.assertEqual(YAHOO_RANGE_BY_INTERVAL["30m"], "60d")
        self.assertEqual(YAHOO_RANGE_BY_INTERVAL["1d"], "10y")
        self.assertEqual(YAHOO_RANGE_BY_INTERVAL["1w"], "max")
        self.assertEqual(YAHOO_RANGE_BY_INTERVAL["1M"], "max")

    def test_resource_quote_and_ohlcv_read_queries_are_cache_only(self) -> None:
        fetched_at = utc_now()
        self.db.add(
            ResourceQuoteSnapshot(
                provider="yahoo_chart",
                exchange="COMEX",
                symbol="GC",
                provider_symbol="GC=F",
                name="Gold Futures",
                root_folder="commodity",
                group="metals",
                asset_class="commodity_futures",
                base_asset="GOLD",
                quote_asset="USD",
                instrument_type="futures",
                contract_key="front_month",
                last_price=2400.0,
                fetched_at=fetched_at,
            )
        )
        self.db.add(
            ResourceOhlcvBar(
                provider="yahoo_chart",
                exchange="COMEX",
                symbol="GC",
                provider_symbol="GC=F",
                name="Gold Futures",
                root_folder="commodity",
                group="metals",
                asset_class="commodity_futures",
                base_asset="GOLD",
                quote_asset="USD",
                instrument_type="futures",
                contract_key="front_month",
                interval="1d",
                bar_time=fetched_at,
                close_price=2400.0,
                fetched_at=fetched_at,
            )
        )
        self.db.commit()

        quotes = list_latest_resource_quotes(self.db, symbols="gc", group="metals")
        bars = list_resource_ohlcv_bars(self.db, symbols="GC", interval="1d")

        self.assertEqual(len(quotes), 1)
        self.assertEqual(quotes[0].last_price, 2400.0)
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].close_price, 2400.0)

    def test_resource_read_queries_scope_supported_symbol_to_contract(self) -> None:
        fetched_at = utc_now()
        self.db.add(
            ResourceOhlcvBar(
                provider="other_provider",
                exchange="COMEX",
                symbol="GC",
                provider_symbol="GC-X",
                name="Other Gold",
                root_folder="commodity",
                group="metals",
                asset_class="commodity_futures",
                base_asset="GOLD",
                quote_asset="USD",
                instrument_type="futures",
                contract_key="front_month",
                interval="1m",
                bar_time=fetched_at,
                close_price=1.0,
                fetched_at=fetched_at,
            )
        )
        self.db.add(
            ResourceOhlcvBar(
                provider="yahoo_chart",
                exchange="COMEX",
                symbol="GC",
                provider_symbol="GC=F",
                name="Gold Futures",
                root_folder="commodity",
                group="metals",
                asset_class="commodity_futures",
                base_asset="GOLD",
                quote_asset="USD",
                instrument_type="futures",
                contract_key="front_month",
                interval="1m",
                bar_time=fetched_at,
                close_price=2400.0,
                fetched_at=fetched_at,
            )
        )
        self.db.commit()

        bars = list_resource_ohlcv_bars(self.db, symbols="GC", interval="1m")

        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].provider, "yahoo_chart")
        self.assertEqual(bars[0].close_price, 2400.0)

    def test_compact_resource_ohlcv_raw_payloads_replaces_legacy_large_payload(self) -> None:
        fetched_at = utc_now()
        self.db.add(
            ResourceOhlcvBar(
                provider="yahoo_chart",
                exchange="COMEX",
                symbol="GC",
                provider_symbol="GC=F",
                name="Gold Futures",
                root_folder="commodity",
                group="metals",
                asset_class="commodity_futures",
                base_asset="GOLD",
                quote_asset="USD",
                instrument_type="futures",
                contract_key="front_month",
                interval="1m",
                bar_time=fetched_at,
                close_price=2400.0,
                raw_payload_json=json.dumps({"chart": "x" * 2000}),
                fetched_at=fetched_at,
            )
        )
        self.db.commit()

        dry_run = compact_resource_ohlcv_raw_payloads(
            self.db,
            apply=False,
            min_raw_chars=1000,
        )
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            applied = compact_resource_ohlcv_raw_payloads(
                self.db,
                apply=True,
                min_raw_chars=1000,
                batch_size=1,
            )
        row = self.db.query(ResourceOhlcvBar).one()
        compact_payload = json.loads(row.raw_payload_json or "{}")

        self.assertEqual(dry_run["candidate_count"], 1)
        self.assertEqual(applied["compacted_count"], 1)
        self.assertNotIn("chart", compact_payload)
        self.assertEqual(compact_payload["compacted_from"], "legacy_resource_ohlcv_full_payload")

    def test_resource_source_health_summarizes_cache_without_refreshing(self) -> None:
        fetched_at = utc_now()
        self.db.add(
            ResourceQuoteSnapshot(
                provider="yahoo_chart",
                exchange="COMEX",
                symbol="GC",
                provider_symbol="GC=F",
                name="Gold Futures",
                root_folder="commodity",
                group="metals",
                asset_class="commodity_futures",
                base_asset="GOLD",
                quote_asset="USD",
                instrument_type="futures",
                contract_key="front_month",
                last_price=2400.0,
                fetched_at=fetched_at,
            )
        )
        self.db.add(
            ResourceOhlcvBar(
                provider="yahoo_chart",
                exchange="COMEX",
                symbol="GC",
                provider_symbol="GC=F",
                name="Gold Futures",
                root_folder="commodity",
                group="metals",
                asset_class="commodity_futures",
                base_asset="GOLD",
                quote_asset="USD",
                instrument_type="futures",
                contract_key="front_month",
                interval="1m",
                bar_time=fetched_at,
                close_price=2400.0,
                fetched_at=fetched_at,
            )
        )
        self.db.commit()

        health = build_resource_source_health(
            self.db,
            symbols="GC",
            intervals="1m",
            include_events=False,
        )

        self.assertEqual(health["kind"], "resource_source_health")
        self.assertEqual(health["summary"]["entry_count"], 2)
        self.assertEqual(health["summary"]["ok_count"], 2)
        self.assertEqual(health["summary"]["delayed_count"], 2)
        self.assertEqual(
            {(entry["resource"], entry["target"], entry["status"]) for entry in health["entries"]},
            {("quote", "GC", "delayed"), ("ohlcv", "GC:1m", "delayed")},
        )

    def test_resource_quote_health_uses_best_effort_session_window(self) -> None:
        now = datetime(2026, 7, 7, 15, 0, tzinfo=timezone.utc)
        fetched_at = now - timedelta(hours=2)
        self.db.add(
            ResourceQuoteSnapshot(
                provider="yahoo_chart",
                exchange="COMEX",
                symbol="GC",
                provider_symbol="GC=F",
                name="Gold Futures",
                root_folder="commodity",
                group="metals",
                asset_class="commodity_futures",
                base_asset="GOLD",
                quote_asset="USD",
                instrument_type="futures",
                contract_key="front_month",
                last_price=2400.0,
                fetched_at=fetched_at,
            )
        )
        self.db.commit()

        with patch("app.resource_market.source_health._now", return_value=now):
            health = build_resource_source_health(
                self.db,
                symbols="GC",
                intervals="1d",
                include_events=False,
            )

        quote_entry = next(entry for entry in health["entries"] if entry["resource"] == "quote")
        self.assertEqual(quote_entry["status"], "delayed")
        self.assertEqual(quote_entry["age_seconds"], 7200)
        self.assertEqual(quote_entry["stale_seconds"], 4 * 60 * 60)
        self.assertEqual(quote_entry["session_status"], "open")

    def test_refresh_resource_market_snapshot_writes_yahoo_quote_and_ohlcv(self) -> None:
        payload = {
            "chart": {
                "result": [
                    {
                        "meta": {
                            "symbol": "GC=F",
                            "regularMarketPrice": 2405.5,
                            "previousClose": 2390.0,
                            "regularMarketTime": 1782991050,
                            "regularMarketOpen": 2398.0,
                            "regularMarketDayHigh": 2410.0,
                            "regularMarketDayLow": 2388.0,
                            "regularMarketVolume": 1200,
                        },
                        "timestamp": [1782990900, 1782991050],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [2398.0, 2400.0],
                                    "high": [2402.0, 2406.0],
                                    "low": [2397.0, 2399.5],
                                    "close": [2401.0, 2405.5],
                                    "volume": [500, 700],
                                }
                            ]
                        },
                    }
                ],
                "error": None,
            }
        }

        with patch(
            "app.resource_market.service.fetch_yahoo_chart_payload_for_interval",
            return_value=(payload, "https://query1.finance.yahoo.com/v8/finance/chart/GC%3DF"),
        ):
            result = refresh_resource_market_snapshot(
                self.db,
                symbols="GC",
                intervals="1m",
                limit=5,
            )

        quotes = list_latest_resource_quotes(self.db, symbols="GC")
        bars = list_resource_ohlcv_bars(self.db, symbols="GC", interval="1m")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["provider"], "yahoo_chart")
        self.assertEqual(len(quotes), 1)
        self.assertEqual(quotes[0].provider_symbol, "GC=F")
        self.assertEqual(quotes[0].quote_asset, "USD")
        self.assertEqual(quotes[0].last_price, 2405.5)
        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[0].close_price, 2405.5)
        raw_bar_payload = json.loads(bars[0].raw_payload_json or "{}")
        self.assertNotIn("chart", raw_bar_payload)
        self.assertEqual(raw_bar_payload["source"], "yahoo_chart")
        self.assertEqual(raw_bar_payload["symbol"], "GC=F")
        self.assertEqual(raw_bar_payload["interval"], "1m")
        self.assertEqual(raw_bar_payload["timestamp_count"], 2)
        events = (
            self.db.query(ProviderEvent)
            .filter(ProviderEvent.market == "resource")
            .order_by(ProviderEvent.resource.asc(), ProviderEvent.target.asc())
            .all()
        )
        self.assertEqual(
            [(event.resource, event.target, event.status) for event in events],
            [("ohlcv", "GC:1m", "success"), ("quote", "GC", "success")],
        )

    def test_resource_refresh_keeps_successful_symbol_when_later_symbol_fails(self) -> None:
        payload = {
            "chart": {
                "result": [
                    {
                        "meta": {
                            "symbol": "GC=F",
                            "regularMarketPrice": 2405.5,
                            "previousClose": 2390.0,
                        },
                        "timestamp": [1782990900, 1782991050],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [2398.0, 2400.0],
                                    "high": [2402.0, 2406.0],
                                    "low": [2397.0, 2399.5],
                                    "close": [2401.0, 2405.5],
                                    "volume": [500, 700],
                                }
                            ]
                        },
                    }
                ],
                "error": None,
            }
        }

        def fake_fetch(*, instrument, interval):
            if instrument.symbol == "SI":
                raise RuntimeError("simulated SI provider failure")
            return payload, "https://query1.finance.yahoo.com/v8/finance/chart/GC%3DF"

        with patch(
            "app.resource_market.service.fetch_yahoo_chart_payload_for_interval",
            side_effect=fake_fetch,
        ):
            result = refresh_resource_market_snapshot(
                self.db,
                symbols="GC,SI",
                intervals="1m",
                limit=5,
            )

        quotes = list_latest_resource_quotes(self.db, symbols="GC")
        bars = list_resource_ohlcv_bars(self.db, symbols="GC", interval="1m")
        si_quotes = list_latest_resource_quotes(self.db, symbols="SI")

        self.assertEqual(result["status"], "partial_success")
        self.assertGreater(result["refreshed_count"], 0)
        self.assertEqual(result["error_count"], 2)
        self.assertEqual(len(quotes), 1)
        self.assertEqual(len(bars), 2)
        self.assertEqual(si_quotes, [])

    def test_resource_refresh_retries_transient_sqlite_lock(self) -> None:
        payload = {
            "chart": {
                "result": [
                    {
                        "meta": {
                            "symbol": "GC=F",
                            "regularMarketPrice": 2405.5,
                            "previousClose": 2390.0,
                        },
                        "timestamp": [1782990900, 1782991050],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [2398.0, 2400.0],
                                    "high": [2402.0, 2406.0],
                                    "low": [2397.0, 2399.5],
                                    "close": [2401.0, 2405.5],
                                    "volume": [500, 700],
                                }
                            ]
                        },
                    }
                ],
                "error": None,
            }
        }
        original_upsert = resource_service._upsert_resource_quote
        attempts = {"count": 0}

        def flaky_quote_upsert(db, record):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise OperationalError("INSERT", {}, Exception("database is locked"))
            return original_upsert(db, record)

        with patch(
            "app.resource_market.service.fetch_yahoo_chart_payload_for_interval",
            return_value=(payload, "https://query1.finance.yahoo.com/v8/finance/chart/GC%3DF"),
        ), patch(
            "app.resource_market.service._upsert_resource_quote",
            side_effect=flaky_quote_upsert,
        ), patch("app.resource_market.service.time.sleep"):
            result = refresh_resource_market_snapshot(
                self.db,
                symbols="GC",
                intervals="1m",
                limit=5,
            )

        quotes = list_latest_resource_quotes(self.db, symbols="GC")
        self.assertEqual(result["status"], "success")
        self.assertEqual(attempts["count"], 2)
        self.assertEqual(len(quotes), 1)
        self.assertEqual(quotes[0].last_price, 2405.5)

    def test_monthly_yahoo_current_bars_are_normalized_and_deduped(self) -> None:
        instrument = list_resource_instruments(group="metals", symbol="GC")[0]
        july_open = int(datetime(2026, 7, 1, 4, 0, tzinfo=timezone.utc).timestamp())
        july_refresh = int(datetime(2026, 7, 2, 12, 30, tzinfo=timezone.utc).timestamp())
        payload = {
            "chart": {
                "result": [
                    {
                        "meta": {"symbol": "GC=F"},
                        "timestamp": [july_open, july_refresh],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [4049.0, 4050.0],
                                    "high": [4092.0, 4094.0],
                                    "low": [4042.0, 4043.0],
                                    "close": [4075.0, 4079.0],
                                    "volume": [45000, 46000],
                                }
                            ]
                        },
                    }
                ],
                "error": None,
            }
        }

        records = parse_yahoo_ohlcv_records(
            payload,
            instrument=instrument,
            interval="1M",
            source_url="https://query1.finance.yahoo.com/v8/finance/chart/GC%3DF",
            limit=10,
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].bar_time, datetime(2026, 7, 1, tzinfo=timezone.utc))
        self.assertEqual(records[0].close_price, 4079.0)


if __name__ == "__main__":
    unittest.main()
