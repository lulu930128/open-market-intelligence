from __future__ import annotations

import asyncio
from datetime import datetime
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.crypto_market import sources
from app.crypto_market.auto_refresh import (
    CryptoAutoRefreshPlan,
    OHLCV_BUNDLE_INTERVALS,
    OHLCV_FAST_INTERVALS,
    _execute_auto_refresh_plan,
    build_crypto_auto_refresh_plans,
)
from app.crypto_market.contract import (
    BINANCE_PROVIDER,
    BITOPRO_PROVIDER,
    BYBIT_PROVIDER,
    COINGLASS_PROVIDER,
    OKX_PROVIDER,
    OMI_LOCAL_PROVIDER,
    PERPETUAL,
    SPOT,
    list_provider_instruments,
    normalize_symbol,
    provider_contract,
)
from app.crypto_market.realtime import (
    CryptoRealtimeStore,
    CryptoRealtimeStreamSpec,
    LIQUIDATION_RESOURCE,
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
    CryptoMarketUnsupportedError,
    list_crypto_derivatives_history,
    list_crypto_cvd_history,
    list_crypto_liquidation_events,
    list_crypto_liquidation_heatmap_cells,
    list_crypto_liquidity_history,
    list_crypto_long_short_ratio_history,
    list_crypto_ohlcv_coverage,
    list_crypto_spread_history,
    list_crypto_ticker_history,
    persist_crypto_realtime_updates,
    CRYPTO_OHLCV_BUNDLE_INTERVAL_LIMITS,
    refresh_crypto_cvd,
    refresh_crypto_derivatives,
    refresh_crypto_liquidation_heatmap,
    refresh_crypto_long_short_ratios,
    refresh_crypto_ohlcv,
    refresh_crypto_ohlcv_bundle,
    refresh_crypto_spreads,
    refresh_crypto_tickers,
    upsert_crypto_cvd_history,
    upsert_crypto_liquidation_event,
    upsert_crypto_liquidation_heatmap_cell,
    upsert_crypto_long_short_ratio_history,
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
    CryptoCvdHistory,
    CryptoLiquidationEvent,
    CryptoLiquidationHeatmapCell,
    CryptoLiquidityHistory,
    CryptoLongShortRatioHistory,
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
    CryptoCvdHistoryRead,
    CryptoLiquidationEventRead,
    CryptoLiquidationHeatmapCellRead,
    CryptoLiquidityHistoryRead,
    CryptoLongShortRatioHistoryRead,
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
        self.assertIn(COINGLASS_PROVIDER, contract["providers"])
        self.assertIn("liquidation_heatmap", contract["providers"][COINGLASS_PROVIDER]["resources"])
        self.assertEqual(contract["providers"][COINGLASS_PROVIDER]["status"], "api_key_required")
        self.assertIn(OMI_LOCAL_PROVIDER, contract["providers"])
        self.assertIn("liquidation_heatmap", contract["providers"][OMI_LOCAL_PROVIDER]["resources"])
        self.assertIn(BYBIT_PROVIDER, contract["providers"])
        self.assertIn("long_short_ratio", contract["providers"][BYBIT_PROVIDER]["resources"])
        self.assertEqual(
            len(
                list_provider_instruments(
                    provider=BINANCE_PROVIDER,
                    symbol="BTC-USDT",
                    instrument_type=PERPETUAL,
                    resource="long_short_ratio",
                )
            ),
            1,
        )
        self.assertIn("1M", contract["ohlcv_intervals"][OKX_PROVIDER])
        self.assertIn("1M", contract["providers"][OKX_PROVIDER]["ohlcv_intervals"])
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

    def test_advanced_metric_records_round_trip_through_service_layer(self) -> None:
        observed_at = _utc("2026-06-24T00:01:00Z")

        upsert_crypto_liquidation_event(
            self.db,
            sources.CryptoLiquidationEventRecord(
                provider=BINANCE_PROVIDER,
                exchange="Binance Futures",
                symbol="BTC-USDT",
                provider_symbol="BTCUSDT",
                base_asset="BTC",
                quote_asset="USDT",
                instrument_type=PERPETUAL,
                liquidation_side="long",
                order_side="sell",
                price=60000,
                average_price=59980,
                quantity=0.5,
                notional=None,
                event_time=observed_at,
                source_url="wss://fstream.binance.test/ws/!forceOrder@arr",
                raw_payload={"side": "SELL", "price": "60000", "quantity": "0.5"},
                fetched_at=observed_at,
            ),
        )
        upsert_crypto_liquidation_heatmap_cell(
            self.db,
            sources.CryptoLiquidationHeatmapCellRecord(
                provider=OMI_LOCAL_PROVIDER,
                source_kind="estimated",
                method="force_order_bucket",
                exchange="OMI Local",
                symbol="BTC-USDT",
                provider_symbol="BTCUSDT",
                base_asset="BTC",
                quote_asset="USDT",
                instrument_type=PERPETUAL,
                time_bucket=observed_at,
                bucket_seconds=300,
                price_bucket=60000,
                price_bucket_size=100,
                liquidation_side="long",
                liquidation_notional=30000,
                liquidation_quantity=0.5,
                event_count=1,
                intensity=0.8,
                generated_at=observed_at,
                source_url=None,
                raw_payload={"method": "test"},
                fetched_at=observed_at,
            ),
        )
        upsert_crypto_cvd_history(
            self.db,
            sources.CryptoCvdBucketRecord(
                provider=BINANCE_PROVIDER,
                exchange="Binance",
                symbol="BTC-USDT",
                provider_symbol="BTCUSDT",
                base_asset="BTC",
                quote_asset="USDT",
                instrument_type=SPOT,
                bucket_seconds=60,
                sampled_at=observed_at,
                buy_base_volume=12,
                sell_base_volume=8,
                buy_quote_volume=720000,
                sell_quote_volume=480000,
                net_base_volume=4,
                net_quote_volume=240000,
                cumulative_base_delta=4,
                cumulative_quote_delta=240000,
                trade_count=42,
                event_time=observed_at,
                source_url="wss://stream.binance.test/ws/btcusdt@aggTrade",
                raw_payload={"bucket": "test"},
                fetched_at=observed_at,
            ),
        )
        upsert_crypto_long_short_ratio_history(
            self.db,
            sources.CryptoLongShortRatioRecord(
                provider=BINANCE_PROVIDER,
                exchange="Binance Futures",
                symbol="BTC-USDT",
                provider_symbol="BTCUSDT",
                base_asset="BTC",
                quote_asset="USDT",
                instrument_type=PERPETUAL,
                ratio_scope="global_account",
                long_ratio=0.55,
                short_ratio=0.45,
                long_short_ratio=1.22,
                event_time=observed_at,
                sampled_at=observed_at,
                source_url="https://fapi.binance.test/futures/data/globalLongShortAccountRatio",
                raw_payload={"longShortRatio": "1.22"},
                fetched_at=observed_at,
            ),
        )
        self.db.commit()

        events = list_crypto_liquidation_events(self.db, provider=BINANCE_PROVIDER, symbols="BTC-USDT")
        heatmap = list_crypto_liquidation_heatmap_cells(self.db, provider=OMI_LOCAL_PROVIDER, symbols="BTC-USDT")
        cvd = list_crypto_cvd_history(self.db, provider=BINANCE_PROVIDER, symbols="BTC-USDT", instrument_type=SPOT)
        ratios = list_crypto_long_short_ratio_history(self.db, provider=BINANCE_PROVIDER, symbols="BTC-USDT")

        self.assertEqual(self.db.query(CryptoLiquidationEvent).count(), 1)
        self.assertEqual(self.db.query(CryptoLiquidationHeatmapCell).count(), 1)
        self.assertEqual(self.db.query(CryptoCvdHistory).count(), 1)
        self.assertEqual(self.db.query(CryptoLongShortRatioHistory).count(), 1)
        self.assertEqual(events[0].notional, 30000)
        self.assertEqual(heatmap[0].liquidation_notional, 30000)
        self.assertEqual(cvd[0].net_base_volume, 4)
        self.assertEqual(ratios[0].long_short_ratio, 1.22)
        CryptoLiquidationEventRead.model_validate(events[0])
        CryptoLiquidationHeatmapCellRead.model_validate(heatmap[0])
        CryptoCvdHistoryRead.model_validate(cvd[0])
        CryptoLongShortRatioHistoryRead.model_validate(ratios[0])

        health = build_crypto_source_health(self.db, base="BTC", required_only=False, max_entries=200)
        resource_rows = {
            (entry["resource"], entry["provider"], entry["target"]): entry
            for entry in health["entries"]
        }
        self.assertEqual(
            resource_rows[("crypto_cvd_spot", BINANCE_PROVIDER, "BTC-USDT")]["row_count"],
            1,
        )
        self.assertEqual(
            resource_rows[("crypto_liquidation_heatmap", OMI_LOCAL_PROVIDER, "BTC-USDT")]["row_count"],
            1,
        )
        self.assertEqual(
            resource_rows[("crypto_long_short_ratio", BINANCE_PROVIDER, "BTC-USDT")]["row_count"],
            1,
        )

    def test_advanced_metric_refreshes_are_explicitly_pending(self) -> None:
        liquidation = refresh_crypto_liquidation_heatmap(
            self.db,
            providers=COINGLASS_PROVIDER,
            symbols="BTC-USDT",
            allow_local_fallback=False,
        )
        cvd = refresh_crypto_cvd(
            self.db,
            providers=BINANCE_PROVIDER,
            symbols="BTC-USDT",
            instrument_type=PERPETUAL,
        )
        ratios = refresh_crypto_long_short_ratios(
            self.db,
            providers=BYBIT_PROVIDER,
            symbols="BTC-USDT",
        )

        self.assertEqual(liquidation["status"], "skipped")
        self.assertEqual(liquidation["resource"], "liquidation_heatmap")
        self.assertEqual(liquidation["skipped"][0]["reason"], "coinglass_api_key_missing")
        self.assertEqual(cvd["resource"], "cvd")
        self.assertEqual(cvd["skipped"][0]["instrument_type"], PERPETUAL)
        self.assertEqual(ratios["resource"], "long_short_ratio")
        self.assertEqual(ratios["rows"], [])
        with self.assertRaises(CryptoMarketUnsupportedError):
            refresh_crypto_cvd(self.db, providers="unknown", symbols="BTC-USDT")

    def test_binance_long_short_ratio_refresh_persists_history(self) -> None:
        timestamp = int(_utc("2026-06-24T00:05:00Z").timestamp() * 1000)
        payload = [
            {
                "symbol": "BTCUSDT",
                "longShortRatio": "1.50",
                "longAccount": "0.60",
                "shortAccount": "0.40",
                "timestamp": timestamp,
            },
            {
                "symbol": "BTCUSDT",
                "longShortRatio": "1.20",
                "longAccount": "0.5455",
                "shortAccount": "0.4545",
                "timestamp": timestamp + 300000,
            },
        ]

        with patch("app.crypto_market.sources._request_json", return_value=payload) as request_json:
            result = refresh_crypto_long_short_ratios(
                self.db,
                providers=BINANCE_PROVIDER,
                symbols="BTC-USDT",
            )

        rows = list_crypto_long_short_ratio_history(
            self.db,
            provider=BINANCE_PROVIDER,
            symbols="BTC-USDT",
            ascending=True,
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["resource"], "long_short_ratio")
        self.assertEqual(result["refreshed_count"], 2)
        self.assertEqual(result["skipped_count"], 0)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].ratio_scope, "global_account")
        self.assertEqual(rows[0].long_ratio, 0.6)
        self.assertEqual(rows[0].short_ratio, 0.4)
        self.assertEqual(rows[0].long_short_ratio, 1.5)
        self.assertIn("globalLongShortAccountRatio", rows[0].source_url)
        self.assertEqual(request_json.call_args.kwargs["params"]["period"], "5m")

    def test_coinglass_liquidation_heatmap_refresh_persists_cells(self) -> None:
        payload = {
            "code": "0",
            "msg": "success",
            "data": {
                "y_axis": [59900, 60000, 60100],
                "liquidation_leverage_data": [
                    [0, 1, 250000.0],
                    [1, 2, 500000.0],
                ],
                "price_candlesticks": [
                    [1782864000, "60000", "60100", "59900", "60050", "1000000"],
                    [1782864300, "60050", "60200", "60000", "60150", "1200000"],
                ],
            },
        }
        with patch.object(sources.settings, "coinglass_api_key", "test-key"), patch.object(
            sources,
            "_request_json",
            return_value=payload,
        ) as request_json:
            result = refresh_crypto_liquidation_heatmap(
                self.db,
                providers=COINGLASS_PROVIDER,
                symbols="BTC-USDT",
                range_value="24h",
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["refreshed_count"], 2)
        self.assertEqual(self.db.query(CryptoLiquidationHeatmapCell).count(), 2)
        row = result["rows"][0]
        self.assertEqual(row.provider, COINGLASS_PROVIDER)
        self.assertEqual(row.source_kind, "third_party")
        self.assertEqual(row.method, "coinglass_aggregated_heatmap_model1")
        self.assertEqual(row.liquidation_side, "all")
        self.assertEqual(row.bucket_seconds, 300)
        self.assertEqual(request_json.call_args.kwargs["headers"]["CG-API-KEY"], "test-key")
        self.assertEqual(request_json.call_args.kwargs["params"]["range"], "24h")

    def test_coinglass_liquidation_refresh_falls_back_to_local_event_heatmap(self) -> None:
        heatmap_error = sources.CryptoMarketDataFetchError("CoinGlass heatmap plan unavailable")
        order_payload = {
            "code": "0",
            "msg": "success",
            "data": [
                {
                    "exchange_name": "BINANCE",
                    "symbol": "BTCUSDT",
                    "base_asset": "BTC",
                    "price": 60000,
                    "usd_value": 120000,
                    "side": 2,
                    "time": int(_utc("2026-06-24T00:00:00Z").timestamp() * 1000),
                }
            ],
        }

        def fake_request(url, *, params=None, headers=None):
            if "aggregated-heatmap" in url:
                raise heatmap_error
            return order_payload

        with patch("app.crypto_market.service._now", return_value=_utc("2026-06-24T00:05:00Z")), patch.object(
            sources.settings,
            "coinglass_api_key",
            "test-key",
        ), patch.object(
            sources,
            "_request_json",
            side_effect=fake_request,
        ):
            result = refresh_crypto_liquidation_heatmap(
                self.db,
                providers=COINGLASS_PROVIDER,
                symbols="BTC-USDT",
                range_value="24h",
            )

        self.assertEqual(result["status"], "partial_success")
        self.assertEqual(result["refreshed_count"], 1)
        self.assertEqual(self.db.query(CryptoLiquidationEvent).count(), 1)
        self.assertEqual(self.db.query(CryptoLiquidationHeatmapCell).count(), 1)
        row = result["rows"][0]
        self.assertEqual(row.provider, OMI_LOCAL_PROVIDER)
        self.assertEqual(row.source_kind, "estimated")
        self.assertEqual(row.method, "local_liquidation_event_bucket")
        self.assertEqual(row.liquidation_side, "long")
        self.assertEqual(row.liquidation_notional, 120000)

    def test_okx_monthly_ohlcv_interval_maps_to_okx_bar(self) -> None:
        with patch.object(
            sources,
            "_request_json",
            return_value={
                "data": [
                    [
                        "1782864000000",
                        "60000",
                        "61000",
                        "59000",
                        "60500",
                        "123.4",
                        "7465700",
                    ]
                ]
            },
        ) as request_json:
            records = sources.fetch_okx_ohlcv("BTC-USDT", interval="1M", limit=10)

        self.assertEqual(request_json.call_args.kwargs["params"]["bar"], "1M")
        self.assertEqual(records[0].provider, OKX_PROVIDER)
        self.assertEqual(records[0].interval, "1M")
        self.assertEqual(records[0].close_price, 60500)
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

    def test_binance_liquidation_stream_specs_use_futures_force_order(self) -> None:
        specs = build_crypto_realtime_stream_specs(
            resource_enabled=lambda instrument, resource: (
                instrument.base_asset == "BTC"
                and resource == LIQUIDATION_RESOURCE
            )
        )

        binance_futures = next(
            spec
            for spec in specs
            if spec.provider == BINANCE_PROVIDER and spec.instrument_type == PERPETUAL
        )

        self.assertEqual(binance_futures.symbols, ("BTC-USDT",))
        self.assertEqual(binance_futures.covered_resources(), (LIQUIDATION_RESOURCE,))
        self.assertIn("wss://fstream.binance.com/stream", binance_futures.url)
        self.assertIn("btcusdt@forceOrder", binance_futures.url)
        self.assertNotIn("ethusdt@forceOrder", binance_futures.url)

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
            (plan.resource, plan.providers, plan.mode): plan
            for plan in build_crypto_auto_refresh_plans(
                settings_read,
                min_interval_seconds=5.0,
                ohlcv_bundle_interval_seconds=900.0,
            )
        }

        self.assertEqual(plans[("quote", BITOPRO_PROVIDER, "default")].symbols, ("BTC-TWD",))
        self.assertEqual(plans[("quote", BITOPRO_PROVIDER, "default")].interval_seconds, 5.0)
        self.assertEqual(plans[("quote", BINANCE_PROVIDER, "default")].symbols, ("BTC-USDT",))
        self.assertEqual(plans[("quote", OKX_PROVIDER, "default")].symbols, ("BTC-USDT",))
        self.assertEqual(plans[("order_book", BITOPRO_PROVIDER, "default")].symbols, ("BTC-TWD",))
        self.assertEqual(plans[("order_book", BINANCE_PROVIDER, "default")].symbols, ("BTC-USDT",))
        self.assertEqual(plans[("order_book", OKX_PROVIDER, "default")].symbols, ("BTC-USDT",))
        self.assertEqual(plans[("ohlcv", BITOPRO_PROVIDER, "fast")].symbols, ("BTC-TWD",))
        self.assertEqual(plans[("ohlcv", BITOPRO_PROVIDER, "fast")].ohlcv_intervals, OHLCV_FAST_INTERVALS)
        self.assertEqual(plans[("ohlcv", BINANCE_PROVIDER, "fast")].symbols, ("BTC-USDT",))
        self.assertEqual(plans[("ohlcv", OKX_PROVIDER, "fast")].symbols, ("BTC-USDT",))
        self.assertEqual(plans[("ohlcv", BITOPRO_PROVIDER, "coverage")].interval_seconds, 900.0)
        self.assertEqual(plans[("ohlcv", BINANCE_PROVIDER, "coverage")].ohlcv_intervals, OHLCV_BUNDLE_INTERVALS)
        self.assertEqual(plans[("ohlcv", OKX_PROVIDER, "coverage")].symbols, ("BTC-USDT",))
        self.assertEqual(plans[("derivatives", BINANCE_PROVIDER, "default")].symbols, ("BTC-USDT",))
        self.assertEqual(plans[("derivatives", OKX_PROVIDER, "default")].symbols, ("BTC-USDT",))
        self.assertEqual(plans[("market_cap", None, "default")].assets, ("BTC",))
        self.assertEqual(plans[("taiwan_spread", "binance,okx", "default")].bases, ("BTC",))

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

    def test_source_health_can_scope_to_selected_crypto_base_without_events(self) -> None:
        self.db.add(
            CryptoTickerSnapshot(
                provider=BINANCE_PROVIDER,
                exchange="Binance",
                symbol="BTC-USDT",
                provider_symbol="BTCUSDT",
                base_asset="BTC",
                quote_asset="USDT",
                instrument_type=SPOT,
                last_price=100000,
                fetched_at=_utc("2026-06-24T00:00:00Z"),
            )
        )
        self.db.commit()

        result = build_crypto_source_health(
            self.db,
            base="SOL",
            include_events=False,
            now=_utc("2026-06-24T00:01:00Z"),
        )
        targets = {entry["target"] for entry in result["entries"]}

        self.assertEqual(result["filters"]["base"], "SOL")
        self.assertIn("SOL-USDT", targets)
        self.assertNotIn("BTC-USDT", targets)
        self.assertTrue(all("latest_event_id" not in entry for entry in result["entries"]))

    def test_source_health_can_include_provider_events_when_requested(self) -> None:
        self.db.add(
            ProviderEvent(
                market="crypto",
                provider=BINANCE_PROVIDER,
                resource="crypto_ticker",
                target="SOL-USDT",
                status="success",
                severity="info",
                event_type="fetch",
                event_time=_utc("2026-06-24T00:00:00Z"),
                observed_at=_utc("2026-06-24T00:00:00Z"),
                message="ok",
            )
        )
        self.db.commit()

        result = build_crypto_source_health(
            self.db,
            base="SOL",
            include_events=True,
            now=_utc("2026-06-24T00:01:00Z"),
        )
        sol_ticker = next(
            entry
            for entry in result["entries"]
            if entry["resource"] == "crypto_ticker"
            and entry["provider"] == BINANCE_PROVIDER
            and entry["target"] == "SOL-USDT"
        )

        self.assertEqual(sol_ticker["latest_event_status"], "success")
        self.assertIsNotNone(sol_ticker["latest_event_id"])

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

    def test_binance_force_order_updates_liquidation_latest_store(self) -> None:
        store = CryptoRealtimeStore()
        received_at = _utc("2026-06-24T00:00:02Z")
        event_time = int(_utc("2026-06-24T00:00:00Z").timestamp() * 1000)

        updates = apply_realtime_message(
            BINANCE_PROVIDER,
            {
                "stream": "btcusdt@forceOrder",
                "data": {
                    "e": "forceOrder",
                    "E": event_time + 100,
                    "o": {
                        "s": "BTCUSDT",
                        "S": "SELL",
                        "o": "LIMIT",
                        "f": "IOC",
                        "q": "0.5",
                        "p": "60000",
                        "ap": "59980",
                        "X": "FILLED",
                        "l": "0.5",
                        "z": "0.5",
                        "T": event_time,
                    },
                },
            },
            received_at=received_at,
            store=store,
        )
        latest = store.latest(
            provider=BINANCE_PROVIDER,
            resource=LIQUIDATION_RESOURCE,
            symbol="BTC-USDT",
            instrument_type=PERPETUAL,
            now=received_at,
        )

        self.assertEqual(len(updates), 1)
        self.assertEqual(latest[0]["resource"], LIQUIDATION_RESOURCE)
        self.assertEqual(latest[0]["instrument_type"], PERPETUAL)
        self.assertEqual(latest[0]["data"]["liquidation_side"], "long")
        self.assertEqual(latest[0]["data"]["order_side"], "sell")
        self.assertEqual(latest[0]["data"]["notional"], 29990.0)
        self.assertEqual(latest[0]["feed_lag_ms"], 2000)

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
        updates.extend(
            parse_realtime_message(
                BINANCE_PROVIDER,
                {
                    "stream": "btcusdt@forceOrder",
                    "data": {
                        "e": "forceOrder",
                        "E": timestamp,
                        "o": {
                            "s": "BTCUSDT",
                            "S": "SELL",
                            "o": "LIMIT",
                            "f": "IOC",
                            "q": "0.5",
                            "p": "60000",
                            "ap": "59980",
                            "X": "FILLED",
                            "l": "0.5",
                            "z": "0.5",
                            "T": timestamp,
                        },
                    },
                },
                received_at=received_at,
            )
        )

        result = persist_crypto_realtime_updates(self.db, updates)

        self.assertEqual(result["persisted_count"], 4)
        self.assertEqual(result["persisted_by_resource"][TICKER_RESOURCE], 1)
        self.assertEqual(result["persisted_by_resource"][ORDER_BOOK_RESOURCE], 1)
        self.assertEqual(result["persisted_by_resource"][OHLCV_RESOURCE], 1)
        self.assertEqual(result["persisted_by_resource"][LIQUIDATION_RESOURCE], 1)
        ticker = self.db.query(CryptoTickerSnapshot).one()
        order_book = self.db.query(CryptoOrderBookSnapshot).one()
        ohlcv = self.db.query(CryptoOhlcvBar).one()
        liquidation = self.db.query(CryptoLiquidationEvent).one()
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
        liquidity_payload = CryptoLiquidityHistoryRead.model_validate(liquidity_history)
        self.assertEqual(liquidity_payload.bids[0]["price"], 99999.0)
        self.assertEqual(liquidity_payload.asks[0]["price"], 100001.0)
        self.assertEqual(ohlcv.interval, "1m")
        self.assertEqual(ohlcv.close_price, 100100.0)
        self.assertEqual(
            ohlcv.bar_time.replace(tzinfo=None),
            _utc("2026-06-24T00:00:00Z").replace(tzinfo=None),
        )
        self.assertEqual(liquidation.symbol, "BTC-USDT")
        self.assertEqual(liquidation.instrument_type, PERPETUAL)
        self.assertEqual(liquidation.liquidation_side, "long")
        self.assertEqual(liquidation.order_side, "sell")
        self.assertEqual(liquidation.notional, 29990.0)

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

    def test_realtime_persistence_manager_keeps_liquidation_events_distinct(self) -> None:
        class DummySession:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return None

        received_at = _utc("2026-06-24T00:00:03Z")
        first_timestamp = int(_utc("2026-06-24T00:00:00Z").timestamp() * 1000)
        second_timestamp = int(_utc("2026-06-24T00:00:01Z").timestamp() * 1000)
        first_update = parse_realtime_message(
            BINANCE_PROVIDER,
            {
                "stream": "btcusdt@forceOrder",
                "data": {
                    "e": "forceOrder",
                    "E": first_timestamp,
                    "o": {
                        "s": "BTCUSDT",
                        "S": "SELL",
                        "q": "0.5",
                        "p": "60000",
                        "ap": "59980",
                        "z": "0.5",
                        "T": first_timestamp,
                    },
                },
            },
            received_at=received_at,
        )[0]
        second_update = parse_realtime_message(
            BINANCE_PROVIDER,
            {
                "stream": "btcusdt@forceOrder",
                "data": {
                    "e": "forceOrder",
                    "E": second_timestamp,
                    "o": {
                        "s": "BTCUSDT",
                        "S": "BUY",
                        "q": "0.25",
                        "p": "60100",
                        "ap": "60120",
                        "z": "0.25",
                        "T": second_timestamp,
                    },
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
        self.assertEqual(manager.status()["pending_count"], 2)
        result = asyncio.run(manager.flush_once())

        self.assertEqual(result["persisted_count"], 2)
        self.assertEqual(len(persisted_batches), 1)
        self.assertEqual(
            {update.data["liquidation_side"] for update in persisted_batches[0]},
            {"long", "short"},
        )

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

    def test_refresh_ohlcv_skips_provider_unsupported_interval(self) -> None:
        with patch.object(sources, "fetch_okx_ohlcv", return_value=[]) as fetcher:
            result = refresh_crypto_ohlcv(
                self.db,
                providers="okx",
                symbols="BTC-USDT",
                interval="2h",
                limit=10,
            )

        self.assertEqual(fetcher.call_count, 0)
        self.assertEqual(result["status"], "empty")
        self.assertEqual(result["refreshed_count"], 0)
        self.assertEqual(result["skipped_count"], 1)
        self.assertEqual(result["skipped"][0]["interval"], "2h")
        self.assertIn("does not support ohlcv interval", result["skipped"][0]["reason"])

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

    def test_list_ohlcv_coverage_groups_by_provider_symbol_and_interval(self) -> None:
        self.db.add_all(
            [
                CryptoOhlcvBar(
                    provider=BINANCE_PROVIDER,
                    exchange="Binance",
                    symbol="BTC-USDT",
                    provider_symbol="BTCUSDT",
                    base_asset="BTC",
                    quote_asset="USDT",
                    instrument_type=SPOT,
                    interval="1d",
                    bar_time=_utc("2026-06-23T00:00:00Z"),
                    close_price=100000,
                    fetched_at=_utc("2026-06-23T00:01:00Z"),
                ),
                CryptoOhlcvBar(
                    provider=BINANCE_PROVIDER,
                    exchange="Binance",
                    symbol="BTC-USDT",
                    provider_symbol="BTCUSDT",
                    base_asset="BTC",
                    quote_asset="USDT",
                    instrument_type=SPOT,
                    interval="1d",
                    bar_time=_utc("2026-06-24T00:00:00Z"),
                    close_price=101000,
                    fetched_at=_utc("2026-06-24T00:01:00Z"),
                ),
            ]
        )
        self.db.commit()

        coverage = list_crypto_ohlcv_coverage(
            self.db,
            provider=BINANCE_PROVIDER,
            symbols="BTC-USDT",
            interval="1d",
        )

        self.assertEqual(len(coverage), 1)
        self.assertEqual(coverage[0]["row_count"], 2)
        self.assertEqual(
            coverage[0]["first_bar_time"].replace(tzinfo=None),
            _utc("2026-06-23T00:00:00Z").replace(tzinfo=None),
        )
        self.assertEqual(
            coverage[0]["last_bar_time"].replace(tzinfo=None),
            _utc("2026-06-24T00:00:00Z").replace(tzinfo=None),
        )
        self.assertEqual(
            coverage[0]["latest_fetched_at"].replace(tzinfo=None),
            _utc("2026-06-24T00:01:00Z").replace(tzinfo=None),
        )

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

    def test_refresh_ohlcv_bundle_uses_default_intervals_and_bounded_limits(self) -> None:
        def fake_refresh(db, *, providers, symbols, interval, limit, **kwargs):
            return {
                "status": "success" if interval == "1m" else "empty",
                "resource": "ohlcv",
                "requested_count": 2,
                "refreshed_count": 1 if interval == "1m" else 0,
                "error_count": 0,
                "skipped_count": 0,
                "errors": [],
                "skipped": [],
                "rows": [],
            }

        with patch("app.crypto_market.service.refresh_crypto_ohlcv", side_effect=fake_refresh) as refresher:
            result = refresh_crypto_ohlcv_bundle(
                self.db,
                providers="binance,okx",
                symbols="BTC-USDT",
            )

        called_intervals = [call.kwargs["interval"] for call in refresher.call_args_list]
        called_limits = [call.kwargs["limit"] for call in refresher.call_args_list]
        self.assertEqual(called_intervals, list(CRYPTO_OHLCV_BUNDLE_INTERVAL_LIMITS))
        self.assertEqual(called_limits, list(CRYPTO_OHLCV_BUNDLE_INTERVAL_LIMITS.values()))
        self.assertEqual(result["resource"], "ohlcv_bundle")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["requested_count"], len(CRYPTO_OHLCV_BUNDLE_INTERVAL_LIMITS) * 2)
        self.assertEqual(result["refreshed_count"], 1)
        self.assertEqual(len(result["intervals"]), len(CRYPTO_OHLCV_BUNDLE_INTERVAL_LIMITS))
        self.assertEqual(result["intervals"][0]["supported_providers"], [BINANCE_PROVIDER, OKX_PROVIDER])

    def test_refresh_ohlcv_bundle_skips_unknown_intervals_without_fetch(self) -> None:
        with patch("app.crypto_market.service.refresh_crypto_ohlcv") as refresher:
            result = refresh_crypto_ohlcv_bundle(
                self.db,
                providers="binance",
                symbols="BTC-USDT",
                intervals="2h",
            )

        self.assertFalse(refresher.called)
        self.assertEqual(result["status"], "empty")
        self.assertEqual(result["requested_count"], 0)
        self.assertEqual(result["refreshed_count"], 0)
        self.assertEqual(result["skipped_count"], 1)
        self.assertEqual(result["skipped"][0]["interval"], "2h")
        self.assertIn("unsupported ohlcv bundle interval", result["skipped"][0]["reason"])

    def test_auto_refresh_coverage_ohlcv_plan_routes_to_bundle_refresh(self) -> None:
        class DummySession:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return None

        plan = CryptoAutoRefreshPlan(
            resource="ohlcv",
            interval_seconds=900.0,
            providers="binance",
            symbols=("BTC-USDT",),
            mode="coverage",
            ohlcv_intervals=("1m", "1d"),
        )

        with (
            patch("app.crypto_market.auto_refresh.SessionLocal", return_value=DummySession()),
            patch(
                "app.crypto_market.auto_refresh.refresh_crypto_ohlcv_bundle",
                return_value={
                    "status": "success",
                    "resource": "ohlcv_bundle",
                    "requested_count": 4,
                    "refreshed_count": 2,
                    "error_count": 0,
                    "skipped_count": 0,
                    "errors": [],
                    "skipped": [],
                    "intervals": [],
                },
            ) as bundle_refresh,
            patch("app.crypto_market.auto_refresh.refresh_crypto_ohlcv") as single_refresh,
        ):
            result = _execute_auto_refresh_plan(plan)

        self.assertEqual(result["resource"], "ohlcv_bundle")
        self.assertFalse(single_refresh.called)
        self.assertEqual(bundle_refresh.call_args.kwargs["providers"], "binance")
        self.assertEqual(bundle_refresh.call_args.kwargs["symbols"], "BTC-USDT")
        self.assertEqual(bundle_refresh.call_args.kwargs["intervals"], "1m,1d")

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
        self.assertEqual(realtime_status["crypto_realtime_liquidation_event"], "empty")
        self.assertNotIn("crypto_realtime_combined", realtime_status)


if __name__ == "__main__":
    unittest.main()
