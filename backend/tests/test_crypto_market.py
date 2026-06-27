from __future__ import annotations

import asyncio
from datetime import datetime
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.crypto_market import sources
from app.crypto_market.auto_refresh import build_crypto_auto_refresh_plans
from app.crypto_market.contract import (
    BINANCE_PROVIDER,
    BITOPRO_PROVIDER,
    OKX_PROVIDER,
    PERPETUAL,
    SPOT,
    list_provider_instruments,
    normalize_symbol,
    provider_contract,
)
from app.crypto_market.realtime import (
    CryptoRealtimeStore,
    CryptoRealtimeStreamSpec,
    OHLCV_RESOURCE,
    ORDER_BOOK_RESOURCE,
    TICKER_RESOURCE,
    apply_realtime_message,
    build_crypto_realtime_stream_specs,
    crypto_realtime_store,
    parse_realtime_message,
)
from app.crypto_market.realtime_persistence import CryptoRealtimePersistenceManager
from app.crypto_market.service import (
    list_crypto_derivatives_history,
    list_crypto_liquidity_history,
    list_crypto_spread_history,
    list_crypto_ticker_history,
    persist_crypto_realtime_updates,
    refresh_crypto_derivatives,
    refresh_crypto_ohlcv,
    refresh_crypto_spreads,
    refresh_crypto_tickers,
)
from app.crypto_market.source_health import build_crypto_source_health
from app.crypto_market.watchlist import (
    CryptoWatchlistAssetNotFoundError,
    CryptoWatchlistDuplicateItemError,
    create_crypto_watchlist_group,
    create_crypto_watchlist_item,
    delete_crypto_watchlist_group,
    get_crypto_watchlist_tree,
    list_crypto_watchlist_items,
)
from app.crypto_market.ws_runtime import CryptoRealtimeCollectorManager
from app.db.models import (
    Base,
    CryptoDerivativesMetricHistory,
    CryptoLiquidityHistory,
    CryptoOrderBookSnapshot,
    CryptoOhlcvBar,
    CryptoSpreadHistory,
    CryptoSpreadSnapshot,
    CryptoTickerHistory,
    CryptoTickerSnapshot,
    ProviderEvent,
    SourceHealthSnapshot,
)
from app.settings.market_data_subscription import (
    get_market_data_subscription_settings,
    update_market_data_subscription_settings,
)
from app.crypto_market.schemas import (
    CryptoRealtimeStatusRead,
    CryptoWatchlistGroupCreate,
    CryptoWatchlistItemCreate,
)
from app.settings.schemas import MarketDataSubscriptionSettingsWrite


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _ticker(
    *,
    provider: str,
    exchange: str,
    symbol: str,
    provider_symbol: str,
    base_asset: str,
    quote_asset: str,
    last_price: float,
) -> sources.CryptoTickerRecord:
    return sources.CryptoTickerRecord(
        provider=provider,
        exchange=exchange,
        symbol=symbol,
        provider_symbol=provider_symbol,
        base_asset=base_asset,
        quote_asset=quote_asset,
        instrument_type=SPOT,
        last_price=last_price,
        bid_price=None,
        bid_size=None,
        ask_price=None,
        ask_size=None,
        high_24h=None,
        low_24h=None,
        price_change_24h=None,
        price_change_pct_24h=None,
        base_volume_24h=None,
        quote_volume_24h=None,
        event_time=None,
        source_url="https://example.test/ticker",
        raw_payload_hash="hash",
        raw_payload={"last": last_price},
        fetched_at=_utc("2026-06-24T00:00:00Z"),
    )


def _derivatives_metric(
    *,
    provider: str,
    exchange: str,
    symbol: str,
    provider_symbol: str,
    mark_price: float,
    funding_rate: float,
    open_interest: float,
) -> sources.CryptoDerivativesMetricRecord:
    return sources.CryptoDerivativesMetricRecord(
        provider=provider,
        exchange=exchange,
        symbol=symbol,
        provider_symbol=provider_symbol,
        base_asset=symbol.split("-", maxsplit=1)[0],
        quote_asset=symbol.split("-", maxsplit=1)[1],
        instrument_type=PERPETUAL,
        mark_price=mark_price,
        index_price=mark_price - 1,
        funding_rate=funding_rate,
        next_funding_time=_utc("2026-06-24T08:00:00Z"),
        open_interest=open_interest,
        open_interest_value=open_interest * mark_price,
        event_time=_utc("2026-06-24T00:00:00Z"),
        source_url="https://example.test/derivatives",
        raw_payload_hash="hash",
        raw_payload={"mark": mark_price},
        fetched_at=_utc("2026-06-24T00:00:00Z"),
    )


class CryptoMarketBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)

    def tearDown(self) -> None:
        crypto_realtime_store.clear()
        self.db.close()
        self.engine.dispose()

    def test_provider_contract_is_read_only_and_crypto_scoped(self) -> None:
        contract = provider_contract()

        self.assertEqual(normalize_symbol("btc/twd"), "BTC-TWD")
        self.assertFalse(contract["execution_enabled"])
        self.assertFalse(contract["ai_execution_enabled"])
        self.assertIn(BITOPRO_PROVIDER, contract["providers"])
        self.assertIn("SOL", contract["coin_ids"])
        self.assertEqual(contract["coin_ids"]["SOL"], "solana")
        self.assertIn(
            "SOL-USDT",
            contract["providers"][BINANCE_PROVIDER]["canonical_symbols"],
        )
        self.assertIn(
            "SOL-USDT",
            contract["providers"][OKX_PROVIDER]["canonical_symbols"],
        )
        self.assertEqual(
            len(
                list_provider_instruments(
                    provider=BITOPRO_PROVIDER,
                    symbol="BTC-TWD",
                    instrument_type=SPOT,
                    resource="ticker",
                )
            ),
            1,
        )
        self.assertEqual(
            len(
                list_provider_instruments(
                    provider=BINANCE_PROVIDER,
                    symbol="SOL-USDT",
                    instrument_type=SPOT,
                    resource="ticker",
                )
            ),
            1,
        )
        self.assertEqual(
            len(
                list_provider_instruments(
                    provider=BINANCE_PROVIDER,
                    symbol="SOL-USDT",
                    instrument_type=PERPETUAL,
                    resource="derivatives",
                )
            ),
            1,
        )
        self.assertEqual(
            len(
                list_provider_instruments(
                    provider=BITOPRO_PROVIDER,
                    symbol="SOL-TWD",
                    instrument_type=SPOT,
                    resource="ticker",
                )
            ),
            0,
        )

    def test_realtime_stream_contract_keeps_okx_unverified(self) -> None:
        specs = build_crypto_realtime_stream_specs()

        providers = {spec.provider for spec in specs}
        okx_specs = [spec for spec in specs if spec.provider == "okx"]
        self.assertIn("bitopro", providers)
        self.assertIn("binance", providers)
        self.assertIn("okx", providers)
        self.assertTrue(okx_specs)
        self.assertTrue(all(not spec.verified for spec in okx_specs))

    def test_realtime_stream_specs_can_be_policy_filtered(self) -> None:
        specs = build_crypto_realtime_stream_specs(
            resource_enabled=lambda instrument, resource: (
                instrument.base_asset == "BTC"
                and resource in {TICKER_RESOURCE, ORDER_BOOK_RESOURCE}
            )
        )

        bitopro_ticker = next(
            spec for spec in specs if spec.provider == BITOPRO_PROVIDER and spec.resource == TICKER_RESOURCE
        )
        binance_combined = next(spec for spec in specs if spec.provider == BINANCE_PROVIDER)
        okx_combined = next(spec for spec in specs if spec.provider == "okx")

        self.assertEqual(bitopro_ticker.symbols, ("BTC-TWD",))
        self.assertIn("BTC_TWD", bitopro_ticker.url)
        self.assertNotIn("ETH_TWD", bitopro_ticker.url)
        self.assertEqual(binance_combined.symbols, ("BTC-USDT",))
        self.assertEqual(binance_combined.covered_resources(), (TICKER_RESOURCE, ORDER_BOOK_RESOURCE))
        self.assertIn("btcusdt@miniTicker", binance_combined.url)
        self.assertIn("btcusdt@depth", binance_combined.url)
        self.assertNotIn("btcusdt@kline_1m", binance_combined.url)
        self.assertNotIn("ethusdt", binance_combined.url)
        self.assertEqual(
            {row["channel"] for row in okx_combined.subscribe_message["args"]},
            {"tickers", "books5"},
        )

    def test_realtime_health_entries_respect_filtered_combined_resources(self) -> None:
        store = CryptoRealtimeStore()
        specs = [
            CryptoRealtimeStreamSpec(
                provider=BINANCE_PROVIDER,
                resource="combined",
                symbols=("BTC-USDT",),
                url="wss://example.test",
                message_resources=(TICKER_RESOURCE,),
            )
        ]

        rows = store.health_entries(
            stream_specs=specs,
            now=_utc("2026-06-24T00:00:00Z"),
            collector_enabled=True,
        )
        resource_names = {row["resource"] for row in rows}

        self.assertIn("crypto_realtime_ticker", resource_names)
        self.assertNotIn("crypto_realtime_order_book", resource_names)
        self.assertNotIn("crypto_realtime_ohlcv", resource_names)

    def test_realtime_collector_reload_tracks_runtime_state_when_disabled(self) -> None:
        manager = CryptoRealtimeCollectorManager()

        with patch(
            "app.crypto_market.ws_runtime.settings.enable_crypto_market_ws_collector",
            False,
        ):
            status = asyncio.run(manager.reload(reason="unit_test"))

        self.assertFalse(status["running"])
        self.assertEqual(status["reload_count"], 1)
        self.assertEqual(status["last_reload_reason"], "unit_test")
        self.assertEqual(status["subscription_policy"], "always_on")
        self.assertIn("enabled_streams", status)
        self.assertIn("persistence", status)
        CryptoRealtimeStatusRead(**status)

    def test_auto_refresh_plan_uses_always_on_subscription_only(self) -> None:
        settings_read = get_market_data_subscription_settings(db=self.db)

        plans = {
            (plan.resource, plan.providers): plan
            for plan in build_crypto_auto_refresh_plans(
                settings_read,
                min_interval_seconds=5.0,
            )
        }

        self.assertEqual(plans[("quote", BITOPRO_PROVIDER)].symbols, ("BTC-TWD",))
        self.assertEqual(plans[("quote", BITOPRO_PROVIDER)].interval_seconds, 5.0)
        self.assertEqual(plans[("quote", BINANCE_PROVIDER)].symbols, ("BTC-USDT",))
        self.assertEqual(plans[("quote", OKX_PROVIDER)].symbols, ("BTC-USDT",))
        self.assertEqual(plans[("order_book", BITOPRO_PROVIDER)].symbols, ("BTC-TWD",))
        self.assertEqual(plans[("order_book", BINANCE_PROVIDER)].symbols, ("BTC-USDT",))
        self.assertEqual(plans[("order_book", OKX_PROVIDER)].symbols, ("BTC-USDT",))
        self.assertEqual(plans[("ohlcv", BITOPRO_PROVIDER)].symbols, ("BTC-TWD",))
        self.assertEqual(plans[("ohlcv", BINANCE_PROVIDER)].symbols, ("BTC-USDT",))
        self.assertEqual(plans[("ohlcv", OKX_PROVIDER)].symbols, ("BTC-USDT",))
        self.assertEqual(plans[("derivatives", BINANCE_PROVIDER)].symbols, ("BTC-USDT",))
        self.assertEqual(plans[("derivatives", OKX_PROVIDER)].symbols, ("BTC-USDT",))
        self.assertEqual(plans[("market_cap", None)].assets, ("BTC",))
        self.assertEqual(plans[("taiwan_spread", "binance,okx")].bases, ("BTC",))

    def test_crypto_watchlist_persists_registered_assets_only(self) -> None:
        default_tree = get_crypto_watchlist_tree(db=self.db)
        self.assertEqual(default_tree[0]["group_name"], "主流幣")
        default_items = list_crypto_watchlist_items(db=self.db, group_id=default_tree[0]["id"])
        self.assertEqual(
            [row["asset"] for row in default_items],
            ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "TON", "LINK"],
        )
        self.assertNotIn("USDT", {row["asset"] for row in default_items})

        group = create_crypto_watchlist_group(
            self.db,
            CryptoWatchlistGroupCreate(group_name="Major coins"),
        )
        item = create_crypto_watchlist_item(
            self.db,
            CryptoWatchlistItemCreate(
                group_id=group["id"],
                asset="SOL",
                note="Layer 1",
                tags="major",
            ),
        )

        tree = get_crypto_watchlist_tree(db=self.db)
        items = list_crypto_watchlist_items(db=self.db)
        created_item = next(row for row in items if row["id"] == item["id"])

        self.assertTrue(any(row["group_name"] == "Major coins" for row in tree))
        self.assertEqual(item["asset"], "SOL")
        self.assertEqual(item["asset_name"], "Solana")
        self.assertEqual(created_item["tags"], "major")

        with self.assertRaises(CryptoWatchlistDuplicateItemError):
            create_crypto_watchlist_item(
                self.db,
                CryptoWatchlistItemCreate(group_id=group["id"], asset="SOL"),
            )

        with self.assertRaises(CryptoWatchlistAssetNotFoundError):
            create_crypto_watchlist_item(
                self.db,
                CryptoWatchlistItemCreate(group_id=group["id"], asset="NOTACOIN"),
            )

    def test_crypto_watchlist_default_group_can_be_deleted(self) -> None:
        tree = get_crypto_watchlist_tree(db=self.db)
        self.assertEqual(len(tree), 1)
        self.assertEqual(tree[0]["group_name"], "主流幣")

        result = delete_crypto_watchlist_group(self.db, tree[0]["id"], recursive=True)

        self.assertEqual(result["deleted_item_count"], 8)
        self.assertEqual(get_crypto_watchlist_tree(db=self.db), [])
        self.assertEqual(list_crypto_watchlist_items(db=self.db), [])

    def test_auto_refresh_plan_respects_disabled_resources_and_min_interval(self) -> None:
        update_market_data_subscription_settings(
            self.db,
            payload=MarketDataSubscriptionSettingsWrite(
                items=[
                    {
                        "key": "crypto:BTC",
                        "mode": "always_on",
                        "resources": {
                            "quote": True,
                            "order_book": False,
                            "ohlcv": False,
                            "derivatives": False,
                            "taiwan_spread": False,
                            "market_cap": False,
                        },
                        "intervals": {"quote_seconds": 2.0},
                    }
                ]
            ),
        )
        settings_read = get_market_data_subscription_settings(db=self.db)

        plans = build_crypto_auto_refresh_plans(
            settings_read,
            min_interval_seconds=5.0,
        )
        plans_by_provider = {plan.providers: plan for plan in plans}

        self.assertEqual(len(plans), 3)
        self.assertEqual(set(plans_by_provider), {BITOPRO_PROVIDER, BINANCE_PROVIDER, OKX_PROVIDER})
        self.assertEqual(plans_by_provider[BITOPRO_PROVIDER].resource, "quote")
        self.assertEqual(plans_by_provider[BITOPRO_PROVIDER].symbols, ("BTC-TWD",))
        self.assertEqual(plans_by_provider[BINANCE_PROVIDER].symbols, ("BTC-USDT",))
        self.assertEqual(plans_by_provider[OKX_PROVIDER].symbols, ("BTC-USDT",))
        self.assertTrue(all(plan.interval_seconds == 5.0 for plan in plans))

    def test_auto_refresh_plan_uses_provider_contract_for_asset_coverage(self) -> None:
        update_market_data_subscription_settings(
            self.db,
            payload=MarketDataSubscriptionSettingsWrite(
                items=[
                    {"key": "crypto:BTC", "mode": "manual"},
                    {
                        "key": "crypto:TON",
                        "mode": "always_on",
                        "resources": {
                            "quote": True,
                            "order_book": False,
                            "ohlcv": False,
                            "derivatives": True,
                            "taiwan_spread": False,
                            "market_cap": False,
                        },
                    },
                ]
            ),
        )
        settings_read = get_market_data_subscription_settings(db=self.db)

        plans = {
            (plan.resource, plan.providers): plan
            for plan in build_crypto_auto_refresh_plans(
                settings_read,
                min_interval_seconds=5.0,
            )
        }

        self.assertEqual(plans[("quote", BINANCE_PROVIDER)].symbols, ("TON-USDT",))
        self.assertEqual(plans[("derivatives", OKX_PROVIDER)].symbols, ("TON-USDT",))
        self.assertNotIn(("quote", OKX_PROVIDER), plans)
        self.assertNotIn(("derivatives", BINANCE_PROVIDER), plans)

    def test_bitopro_realtime_ticker_updates_latest_store(self) -> None:
        store = CryptoRealtimeStore()
        received_at = _utc("2026-06-24T00:00:01Z")
        payload = {
            "event": "TICKER",
            "pair": "BTC_TWD",
            "lastPrice": "2100000",
            "priceChange24hr": "10000",
            "volume24hr": "12.5",
            "high24hr": "2150000",
            "low24hr": "2050000",
            "timestamp": int(_utc("2026-06-24T00:00:00Z").timestamp() * 1000),
        }

        updates = apply_realtime_message(
            BITOPRO_PROVIDER,
            payload,
            received_at=received_at,
            store=store,
        )
        latest = store.latest(provider=BITOPRO_PROVIDER, symbol="BTC-TWD", now=received_at)

        self.assertEqual(len(updates), 1)
        self.assertEqual(latest[0]["resource"], "ticker")
        self.assertEqual(latest[0]["data"]["last_price"], 2100000.0)
        self.assertEqual(latest[0]["feed_lag_ms"], 1000)
        self.assertFalse(latest[0]["stale"])

    def test_binance_realtime_messages_normalize_symbols(self) -> None:
        store = CryptoRealtimeStore()
        received_at = _utc("2026-06-24T00:00:01Z")
        timestamp = int(_utc("2026-06-24T00:00:00Z").timestamp() * 1000)

        apply_realtime_message(
            BINANCE_PROVIDER,
            {
                "stream": "btcusdt@miniTicker",
                "data": {
                    "e": "24hrMiniTicker",
                    "E": timestamp,
                    "s": "BTCUSDT",
                    "c": "100000",
                    "h": "101000",
                    "l": "99000",
                    "v": "10",
                    "q": "1000000",
                },
            },
            received_at=received_at,
            store=store,
        )
        apply_realtime_message(
            BINANCE_PROVIDER,
            {
                "stream": "btcusdt@depth5",
                "data": {
                    "lastUpdateId": 160,
                    "bids": [["99999", "1"]],
                    "asks": [["100001", "2"]],
                },
            },
            received_at=received_at,
            store=store,
        )

        latest = store.latest(provider=BINANCE_PROVIDER, symbol="BTC-USDT", now=received_at)
        resources = {row["resource"] for row in latest}
        self.assertEqual(resources, {"ticker", "order_book"})
        order_book = next(row for row in latest if row["resource"] == "order_book")
        self.assertEqual(order_book["data"]["best_bid_price"], 99999.0)
        self.assertEqual(order_book["sequence"], 160)

    def test_persist_crypto_realtime_updates_writes_existing_cache_tables(self) -> None:
        received_at = _utc("2026-06-24T00:00:01Z")
        timestamp = int(_utc("2026-06-24T00:00:00Z").timestamp() * 1000)
        updates = []
        updates.extend(
            parse_realtime_message(
                BINANCE_PROVIDER,
                {
                    "stream": "btcusdt@miniTicker",
                    "data": {
                        "e": "24hrMiniTicker",
                        "E": timestamp,
                        "s": "BTCUSDT",
                        "c": "100000",
                        "h": "101000",
                        "l": "99000",
                        "v": "10",
                        "q": "1000000",
                    },
                },
                received_at=received_at,
            )
        )
        updates.extend(
            parse_realtime_message(
                BINANCE_PROVIDER,
                {
                    "stream": "btcusdt@depth5",
                    "data": {
                        "lastUpdateId": 160,
                        "bids": [["99999", "1"]],
                        "asks": [["100001", "2"]],
                    },
                },
                received_at=received_at,
            )
        )
        updates.extend(
            parse_realtime_message(
                BINANCE_PROVIDER,
                {
                    "stream": "btcusdt@kline_1m",
                    "data": {
                        "e": "kline",
                        "E": timestamp,
                        "s": "BTCUSDT",
                        "k": {
                            "s": "BTCUSDT",
                            "i": "1m",
                            "t": timestamp,
                            "o": "99800",
                            "h": "100500",
                            "l": "99750",
                            "c": "100100",
                            "v": "3.5",
                            "q": "350000",
                            "x": False,
                            "L": 200,
                        },
                    },
                },
                received_at=received_at,
            )
        )

        result = persist_crypto_realtime_updates(self.db, updates)

        self.assertEqual(result["persisted_count"], 3)
        self.assertEqual(result["persisted_by_resource"][TICKER_RESOURCE], 1)
        self.assertEqual(result["persisted_by_resource"][ORDER_BOOK_RESOURCE], 1)
        self.assertEqual(result["persisted_by_resource"][OHLCV_RESOURCE], 1)
        ticker = self.db.query(CryptoTickerSnapshot).one()
        order_book = self.db.query(CryptoOrderBookSnapshot).one()
        ohlcv = self.db.query(CryptoOhlcvBar).one()
        ticker_history = self.db.query(CryptoTickerHistory).one()
        liquidity_history = self.db.query(CryptoLiquidityHistory).one()
        liquidity_rows = list_crypto_liquidity_history(
            self.db,
            provider="binance",
            symbols="BTC-USDT",
        )
        self.assertEqual(ticker.symbol, "BTC-USDT")
        self.assertEqual(ticker.last_price, 100000.0)
        self.assertEqual(order_book.best_bid_price, 99999.0)
        self.assertEqual(ticker_history.symbol, "BTC-USDT")
        self.assertEqual(ticker_history.last_price, 100000.0)
        self.assertEqual(liquidity_history.best_bid_price, 99999.0)
        self.assertEqual(liquidity_history.sampled_at.replace(tzinfo=None).second, 0)
        self.assertEqual(liquidity_rows[0].spread, 2.0)
        self.assertEqual(ohlcv.interval, "1m")
        self.assertEqual(ohlcv.close_price, 100100.0)
        self.assertEqual(
            ohlcv.bar_time.replace(tzinfo=None),
            _utc("2026-06-24T00:00:00Z").replace(tzinfo=None),
        )

    def test_realtime_persistence_manager_coalesces_pending_updates(self) -> None:
        class DummySession:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return None

        received_at = _utc("2026-06-24T00:00:01Z")
        timestamp = int(_utc("2026-06-24T00:00:00Z").timestamp() * 1000)
        first_update = parse_realtime_message(
            BINANCE_PROVIDER,
            {
                "stream": "btcusdt@miniTicker",
                "data": {
                    "e": "24hrMiniTicker",
                    "E": timestamp,
                    "s": "BTCUSDT",
                    "c": "100000",
                },
            },
            received_at=received_at,
        )[0]
        second_update = parse_realtime_message(
            BINANCE_PROVIDER,
            {
                "stream": "btcusdt@miniTicker",
                "data": {
                    "e": "24hrMiniTicker",
                    "E": timestamp,
                    "s": "BTCUSDT",
                    "c": "100200",
                },
            },
            received_at=received_at,
        )[0]
        persisted_batches = []

        def fake_persist(_db, updates):
            persisted_batches.append(updates)
            return {
                "status": "success",
                "persisted_count": len(updates),
                "skipped_count": 0,
                "error_count": 0,
            }

        manager = CryptoRealtimePersistenceManager(
            session_factory=DummySession,
            persist_func=fake_persist,
            enabled=True,
            flush_interval_seconds=0.01,
            max_pending_keys=10,
        )

        self.assertEqual(manager.enqueue_many([first_update, second_update]), 2)
        self.assertEqual(manager.status()["pending_count"], 1)
        result = asyncio.run(manager.flush_once())

        self.assertEqual(result["persisted_count"], 1)
        self.assertEqual(len(persisted_batches), 1)
        self.assertEqual(persisted_batches[0][0].data["last_price"], 100200.0)
        self.assertEqual(manager.status()["persisted_count"], 1)

    def test_bitopro_ticker_parser_normalizes_local_pair(self) -> None:
        payload = {
            "data": [
                {
                    "pair": "btc_twd",
                    "lastPrice": "2100000",
                    "high24hr": "2150000",
                    "low24hr": "2050000",
                    "priceChange24hr": "10000",
                    "volume24hr": "12.5",
                }
            ]
        }

        with patch.object(sources, "_request_json", return_value=payload):
            record = sources.fetch_bitopro_ticker("btc/twd")

        self.assertEqual(record.provider, BITOPRO_PROVIDER)
        self.assertEqual(record.symbol, "BTC-TWD")
        self.assertEqual(record.provider_symbol, "btc_twd")
        self.assertEqual(record.last_price, 2100000.0)
        self.assertEqual(record.base_volume_24h, 12.5)

    def test_bitopro_ticker_parser_accepts_live_data_object_shape(self) -> None:
        payload = {
            "data": {
                "pair": "usdt_twd",
                "lastPrice": "30.10000000",
                "priceChange24hr": "-0.12",
                "volume24hr": "1000.5",
                "high24hr": "30.3",
                "low24hr": "29.8",
            }
        }

        with patch.object(sources, "_request_json", return_value=payload):
            record = sources.fetch_bitopro_ticker("USDT-TWD")

        self.assertEqual(record.provider, BITOPRO_PROVIDER)
        self.assertEqual(record.symbol, "USDT-TWD")
        self.assertEqual(record.last_price, 30.1)
        self.assertEqual(record.price_change_24h, -0.12)
        self.assertEqual(record.base_volume_24h, 1000.5)

    def test_refresh_tickers_upserts_cache_and_provider_event(self) -> None:
        with patch.object(
            sources,
            "fetch_bitopro_ticker",
            return_value=_ticker(
                provider=BITOPRO_PROVIDER,
                exchange="BitoPro",
                symbol="BTC-TWD",
                provider_symbol="btc_twd",
                base_asset="BTC",
                quote_asset="TWD",
                last_price=2100000,
            ),
        ):
            result = refresh_crypto_tickers(
                self.db,
                providers="bitopro",
                symbols="BTC-TWD",
            )

        row = self.db.query(CryptoTickerSnapshot).one()
        event = self.db.query(ProviderEvent).one()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["refreshed_count"], 1)
        self.assertEqual(row.symbol, "BTC-TWD")
        self.assertEqual(row.last_price, 2100000)
        self.assertEqual(event.market, "crypto")
        self.assertEqual(event.resource, "crypto_ticker")
        self.assertEqual(event.status, "success")
        history = self.db.query(CryptoTickerHistory).one()
        self.assertEqual(history.symbol, "BTC-TWD")
        self.assertEqual(history.last_price, 2100000)
        self.assertEqual(history.sampled_at.replace(tzinfo=None), _utc("2026-06-24T00:00:00Z").replace(tzinfo=None))

    def test_refresh_tickers_coalesces_history_by_sample_bucket(self) -> None:
        first = _ticker(
            provider=BITOPRO_PROVIDER,
            exchange="BitoPro",
            symbol="BTC-TWD",
            provider_symbol="btc_twd",
            base_asset="BTC",
            quote_asset="TWD",
            last_price=2100000,
        )
        second = _ticker(
            provider=BITOPRO_PROVIDER,
            exchange="BitoPro",
            symbol="BTC-TWD",
            provider_symbol="btc_twd",
            base_asset="BTC",
            quote_asset="TWD",
            last_price=2100100,
        )

        with patch.object(sources, "fetch_bitopro_ticker", side_effect=[first, second]):
            refresh_crypto_tickers(self.db, providers="bitopro", symbols="BTC-TWD")
            refresh_crypto_tickers(self.db, providers="bitopro", symbols="BTC-TWD")

        rows = self.db.query(CryptoTickerHistory).all()
        history = list_crypto_ticker_history(
            self.db,
            provider="bitopro",
            symbols="BTC-TWD",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(history[0].last_price, 2100100)

    def test_refresh_tickers_skips_disabled_subscription_item(self) -> None:
        update_market_data_subscription_settings(
            self.db,
            payload=MarketDataSubscriptionSettingsWrite(
                items=[{"key": "crypto:ETH", "mode": "disabled"}]
            ),
        )

        with patch.object(
            sources,
            "fetch_bitopro_ticker",
            return_value=_ticker(
                provider=BITOPRO_PROVIDER,
                exchange="BitoPro",
                symbol="BTC-TWD",
                provider_symbol="btc_twd",
                base_asset="BTC",
                quote_asset="TWD",
                last_price=2100000,
            ),
        ) as fetcher:
            result = refresh_crypto_tickers(
                self.db,
                providers="bitopro",
                symbols="BTC-TWD,ETH-TWD",
            )

        rows = self.db.query(CryptoTickerSnapshot).all()
        self.assertEqual(fetcher.call_count, 1)
        self.assertEqual(fetcher.call_args.args[0], "BTC-TWD")
        self.assertEqual(result["refreshed_count"], 1)
        self.assertEqual(result["skipped_count"], 1)
        self.assertIn("subscription mode disabled", result["skipped"][0]["reason"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].symbol, "BTC-TWD")

    def test_refresh_ohlcv_skips_disabled_subscription_resource(self) -> None:
        update_market_data_subscription_settings(
            self.db,
            payload=MarketDataSubscriptionSettingsWrite(
                items=[
                    {
                        "key": "crypto:BTC",
                        "mode": "manual",
                        "resources": {"ohlcv": False},
                    }
                ]
            ),
        )

        with patch.object(sources, "fetch_binance_ohlcv", return_value=[]) as fetcher:
            result = refresh_crypto_ohlcv(
                self.db,
                providers="binance",
                symbols="BTC-USDT",
                interval="1m",
                limit=10,
            )

        self.assertEqual(fetcher.call_count, 0)
        self.assertEqual(result["status"], "empty")
        self.assertEqual(result["refreshed_count"], 0)
        self.assertEqual(result["skipped_count"], 1)
        self.assertIn("resource ohlcv is disabled", result["skipped"][0]["reason"])
        self.assertEqual(self.db.query(CryptoOhlcvBar).count(), 0)

    def test_refresh_ohlcv_upserts_supported_bars_and_skips_unsupported_pairs(self) -> None:
        bar = sources.CryptoOhlcvBarRecord(
            provider="binance",
            exchange="Binance",
            symbol="BTC-USDT",
            provider_symbol="BTCUSDT",
            base_asset="BTC",
            quote_asset="USDT",
            instrument_type=SPOT,
            interval="1m",
            bar_time=_utc("2026-06-24T00:00:00Z"),
            open_price=100000,
            high_price=100200,
            low_price=99900,
            close_price=100100,
            base_volume=10,
            quote_volume=1001000,
            source_url="https://example.test/klines",
            raw_payload_hash="hash",
            raw_payload=[1, 2, 3],
            fetched_at=_utc("2026-06-24T00:01:00Z"),
        )

        with patch.object(sources, "fetch_binance_ohlcv", return_value=[bar]):
            result = refresh_crypto_ohlcv(
                self.db,
                providers="binance",
                symbols="BTC-USDT,USDT-TWD",
                interval="1m",
                limit=10,
            )

        rows = self.db.query(CryptoOhlcvBar).all()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["refreshed_count"], 1)
        self.assertEqual(result["skipped_count"], 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].symbol, "BTC-USDT")
        self.assertEqual(rows[0].close_price, 100100)

    def test_refresh_bitopro_daily_ohlcv_uses_interval_sized_default_window(self) -> None:
        with patch.object(sources, "fetch_bitopro_ohlcv", return_value=[]) as fetcher:
            result = refresh_crypto_ohlcv(
                self.db,
                providers="bitopro",
                symbols="BTC-TWD",
                interval="1d",
                limit=10,
            )

        kwargs = fetcher.call_args.kwargs
        self.assertEqual(result["status"], "empty")
        self.assertEqual(fetcher.call_args.args[0], "BTC-TWD")
        self.assertEqual(kwargs["interval"], "1d")
        self.assertGreaterEqual((kwargs["end_time"] - kwargs["start_time"]).days, 365)

    def test_refresh_derivatives_records_history(self) -> None:
        with patch.object(
            sources,
            "fetch_binance_derivatives_metric",
            return_value=_derivatives_metric(
                provider=BINANCE_PROVIDER,
                exchange="Binance Futures",
                symbol="BTC-USDT",
                provider_symbol="BTCUSDT",
                mark_price=100000,
                funding_rate=0.0001,
                open_interest=1234,
            ),
        ):
            result = refresh_crypto_derivatives(
                self.db,
                providers="binance",
                symbols="BTC-USDT",
            )

        history = self.db.query(CryptoDerivativesMetricHistory).one()
        queried = list_crypto_derivatives_history(
            self.db,
            provider="binance",
            symbols="BTC-USDT",
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(history.funding_rate, 0.0001)
        self.assertEqual(history.open_interest, 1234)
        self.assertEqual(queried[0].mark_price, 100000)

    def test_refresh_spreads_uses_bitopro_usdt_twd_fx(self) -> None:
        now = _utc("2026-06-24T00:00:00Z")
        self.db.add_all(
            [
                CryptoTickerSnapshot(
                    provider="bitopro",
                    exchange="BitoPro",
                    symbol="USDT-TWD",
                    provider_symbol="usdt_twd",
                    base_asset="USDT",
                    quote_asset="TWD",
                    instrument_type=SPOT,
                    last_price=31.5,
                    fetched_at=now,
                ),
                CryptoTickerSnapshot(
                    provider="bitopro",
                    exchange="BitoPro",
                    symbol="BTC-TWD",
                    provider_symbol="btc_twd",
                    base_asset="BTC",
                    quote_asset="TWD",
                    instrument_type=SPOT,
                    last_price=3151000,
                    fetched_at=now,
                ),
                CryptoTickerSnapshot(
                    provider="binance",
                    exchange="Binance",
                    symbol="BTC-USDT",
                    provider_symbol="BTCUSDT",
                    base_asset="BTC",
                    quote_asset="USDT",
                    instrument_type=SPOT,
                    last_price=100000,
                    fetched_at=now,
                ),
            ]
        )
        self.db.commit()

        result = refresh_crypto_spreads(
            self.db,
            bases="BTC",
            global_providers="binance",
        )

        spread = self.db.query(CryptoSpreadSnapshot).one()
        self.assertEqual(result["status"], "success")
        self.assertEqual(spread.implied_twd_price, 3150000)
        self.assertEqual(spread.spread, 1000)
        self.assertAlmostEqual(spread.spread_pct or 0, 1000 / 3150000 * 100)
        spread_history = self.db.query(CryptoSpreadHistory).one()
        queried_history = list_crypto_spread_history(
            self.db,
            base="BTC",
            global_provider="binance",
        )
        self.assertEqual(spread_history.spread, 1000)
        self.assertEqual(queried_history[0].global_symbol, "BTC-USDT")

    def test_source_health_reports_supported_crypto_resources_only(self) -> None:
        report = build_crypto_source_health(
            self.db,
            provider="bitopro",
            symbol="BTC-USDT",
            now=_utc("2026-06-24T00:00:00Z"),
        )

        bitopro_btc_usdt_entries = [
            entry
            for entry in report["entries"]
            if entry["provider"] == "bitopro" and entry["target"] == "BTC-USDT"
        ]
        self.assertEqual(bitopro_btc_usdt_entries, [])
        self.assertGreaterEqual(report["summary"]["entry_count"], 2)
        self.assertEqual(self.db.query(SourceHealthSnapshot).count(), 0)

    def test_source_health_snapshot_sync_is_explicit(self) -> None:
        report = build_crypto_source_health(
            self.db,
            provider="bitopro",
            symbol="BTC-TWD",
            now=_utc("2026-06-24T00:00:00Z"),
            sync_snapshots=True,
        )

        self.assertGreaterEqual(report["summary"]["entry_count"], 1)
        self.assertGreater(self.db.query(SourceHealthSnapshot).count(), 0)

    def test_source_health_includes_realtime_freshness(self) -> None:
        received_at = _utc("2026-06-24T00:00:01Z")
        payload = {
            "event": "TICKER",
            "pair": "BTC_TWD",
            "lastPrice": "2100000",
            "timestamp": int(_utc("2026-06-24T00:00:00Z").timestamp() * 1000),
        }
        apply_realtime_message(BITOPRO_PROVIDER, payload, received_at=received_at)

        report = build_crypto_source_health(
            self.db,
            provider="bitopro",
            symbol="BTC-TWD",
            now=received_at,
        )

        realtime_entries = [
            entry
            for entry in report["entries"]
            if entry["resource"] == "crypto_realtime_ticker"
            and entry["provider"] == "bitopro"
            and entry["target"] == "BTC-TWD"
        ]
        self.assertEqual(len(realtime_entries), 1)
        self.assertEqual(realtime_entries[0]["status"], "live")
        self.assertEqual(realtime_entries[0]["data_quality"], "ok")

    def test_source_health_expands_binance_combined_realtime_resources(self) -> None:
        received_at = _utc("2026-06-24T00:00:01Z")
        timestamp = int(_utc("2026-06-24T00:00:00Z").timestamp() * 1000)
        apply_realtime_message(
            BINANCE_PROVIDER,
            {
                "stream": "btcusdt@miniTicker",
                "data": {
                    "e": "24hrMiniTicker",
                    "E": timestamp,
                    "s": "BTCUSDT",
                    "c": "100000",
                },
            },
            received_at=received_at,
        )
        apply_realtime_message(
            BINANCE_PROVIDER,
            {
                "stream": "btcusdt@depth5",
                "data": {
                    "lastUpdateId": 160,
                    "bids": [["99999", "1"]],
                    "asks": [["100001", "2"]],
                },
            },
            received_at=received_at,
        )

        report = build_crypto_source_health(
            self.db,
            provider="binance",
            symbol="BTC-USDT",
            now=received_at,
        )

        realtime_status = {
            entry["resource"]: entry["status"]
            for entry in report["entries"]
            if entry["provider"] == "binance" and entry["target"] == "BTC-USDT"
        }
        self.assertEqual(realtime_status["crypto_realtime_ticker"], "live")
        self.assertEqual(realtime_status["crypto_realtime_order_book"], "live")
        self.assertEqual(realtime_status["crypto_realtime_ohlcv"], "empty")
        self.assertNotIn("crypto_realtime_combined", realtime_status)


if __name__ == "__main__":
    unittest.main()
