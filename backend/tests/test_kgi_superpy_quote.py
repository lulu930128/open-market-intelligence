from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

from app.market.providers.kgi_superpy import KgiSuperPyQuoteManager, _Lease
from app.market.providers import kgi_superpy_bridge
from app.market.providers.kgi_superpy_bridge import (
    _data_get,
    _ensure_login,
    _kbar_payload,
    _on_kbar,
    _on_quote,
    _quote_payload,
    _runtime_compatibility_error,
    _safe_error,
    _select_account,
    _subscribe_symbol,
    _tw_portfolio_records,
    _us_portfolio_records,
)
from app.market.kgi_market_data import backfill_taiwan_kgi_market_data
from app.market.providers.kgi_canonical import KGI_PROVIDER
from app.market.schemas import (
    TaiwanRealtimeMarketStreamRead,
    TaiwanRealtimeQuoteLeaseCreate,
    TaiwanRealtimeQuoteLeaseSummaryRead,
)
from app.market.schemas import TaiwanKgiDataBackfillRequest, TaiwanKgiDataBackfillRead
from app.market.trading_calendar import TAIWAN_TZ
from app.market.tw_realtime_capabilities import KGI_QUOTE_SNAPSHOT_DESCRIPTOR
from app.market.tw_realtime_stream_platform import read_taiwan_realtime_market_stream


class _NoProcessManager(KgiSuperPyQuoteManager):
    def _ensure_subscription_async(self, symbol: str) -> None:
        self._symbol_status[symbol] = "subscribing"

    def _unsubscribe_if_unwatched(self, symbol: str) -> None:
        self._quotes.pop(symbol, None)
        self._symbol_status.pop(symbol, None)


def _config(**overrides):
    values = {
        "enable_kgi_superpy_quote": True,
        "kgi_superpy_person_id": "A123456789",
        "kgi_superpy_password": "secret",
        "kgi_superpy_python": sys.executable,
        "kgi_superpy_quote_stale_seconds": 15,
        "kgi_superpy_lease_ttl_seconds": 60,
        "kgi_superpy_idle_shutdown_seconds": 120,
        "kgi_superpy_start_timeout_seconds": 1,
        "kgi_superpy_command_timeout_seconds": 1,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _read_market_stream(
    manager: KgiSuperPyQuoteManager,
    symbol: str,
    *,
    diagnostic_limit: int = 0,
) -> TaiwanRealtimeMarketStreamRead:
    payload = read_taiwan_realtime_market_stream(
        symbol,
        diagnostic_limit=diagnostic_limit,
        descriptors=(KGI_QUOTE_SNAPSHOT_DESCRIPTOR,),
        ports={KGI_PROVIDER: manager},
    )
    return TaiwanRealtimeMarketStreamRead.model_validate(payload)


class KgiSuperPyQuoteTests(unittest.TestCase):
    def test_bridge_normalizes_taiwan_long_holdings_and_excludes_shorts(self) -> None:
        class _Frame:
            columns = [
                "Symbol",
                "SymbolName",
                "CURRENCY",
                "NETQTY9",
                "NETQTY0",
                "NETQTY3",
                "NETQTY4",
                "AVG_PRICE0",
                "AVG_PRICE3",
            ]

            def to_dict(self, orient):
                self.orient = orient
                return [
                    {
                        "Symbol": "2330",
                        "SymbolName": "台積電",
                        "CURRENCY": "TWD",
                        "NETQTY9": "100",
                        "NETQTY0": "1000",
                        "NETQTY3": "200",
                        "NETQTY4": "50",
                        "AVG_PRICE0": "50",
                        "AVG_PRICE3": "45",
                    }
                ]

        records, warnings = _tw_portfolio_records(_Frame())

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["symbol"], "2330")
        self.assertEqual(records[0]["quantity"], 1200)
        self.assertEqual(records[0]["cost_amount"], 59000)
        self.assertEqual(warnings, ["excluded_short_positions:1"])

    def test_bridge_does_not_double_count_odd_lot_component_in_cash_total(
        self,
    ) -> None:
        class _Frame:
            columns = [
                "Symbol",
                "SymbolName",
                "CURRENCY",
                "NETQTY9",
                "NETQTY0",
                "NETQTY3",
                "NETQTY4",
                "AVG_PRICE0",
                "AVG_PRICE3",
            ]

            def to_dict(self, orient):
                return [
                    {
                        "Symbol": "3711",
                        "SymbolName": "日月光投控",
                        "CURRENCY": "TWD",
                        "NETQTY9": 120,
                        "NETQTY0": 120,
                        "NETQTY3": 0,
                        "NETQTY4": 0,
                        "AVG_PRICE0": 614.29,
                        "AVG_PRICE3": 0,
                    }
                ]

        records, warnings = _tw_portfolio_records(_Frame())

        self.assertEqual(records[0]["quantity"], 120)
        self.assertAlmostEqual(records[0]["cost_amount"], 73_714.8)
        self.assertEqual(warnings, [])

    def test_bridge_portfolio_diagnostics_are_symbol_bounded(self) -> None:
        from app.market.providers.kgi_superpy_bridge import _tw_portfolio_diagnostics

        class _Frame:
            columns = [
                "Symbol",
                "NETQTY9",
                "NETQTY0",
                "NETQTY3",
                "NETQTY4",
                "AVG_PRICE0",
                "AVG_PRICE3",
            ]

            def to_dict(self, orient):
                return [
                    {
                        "Symbol": "3711",
                        "NETQTY9": 120,
                        "NETQTY0": 0,
                        "NETQTY3": 0,
                        "NETQTY4": 0,
                        "AVG_PRICE0": 614.29,
                        "AVG_PRICE3": 0,
                    },
                    {
                        "Symbol": "2330",
                        "NETQTY9": 0,
                        "NETQTY0": 1000,
                        "NETQTY3": 0,
                        "NETQTY4": 0,
                        "AVG_PRICE0": 2000,
                        "AVG_PRICE3": 0,
                    },
                ]

        diagnostics = _tw_portfolio_diagnostics(_Frame(), ["3711"])

        self.assertEqual(diagnostics[0]["symbol"], "3711")
        self.assertEqual(diagnostics[0]["source_row_count"], 1)
        self.assertEqual(diagnostics[0]["source_rows"][0]["NETQTY9"], 120)

    def test_bridge_normalizes_us_holdings_without_inventing_cost(self) -> None:
        class _Frame:
            columns = ["symbol", "symbol_name", "market", "currency", "Qty"]

            def to_dict(self, orient):
                self.orient = orient
                return [
                    {
                        "symbol": "AAPL.O",
                        "symbol_name": "Apple Inc.",
                        "market": "US",
                        "currency": "USD",
                        "Qty": "2",
                    },
                    {
                        "symbol": "AAPL.O",
                        "symbol_name": "Apple Inc.",
                        "market": "US",
                        "currency": "USD",
                        "Qty": 1,
                    },
                ]

        records, warnings = _us_portfolio_records(_Frame())

        self.assertEqual(records[0]["quantity"], 3)
        self.assertIsNone(records[0]["cost_amount"])
        self.assertEqual(warnings, ["missing_cost_basis:1"])

    def test_bridge_account_selection_is_explicit_when_multiple_accounts_exist(self) -> None:
        api = SimpleNamespace(
            show_account=lambda: [
                {"account": "TW-ONE", "account_flag": "證券"},
                {"account": "TW-TWO", "account_flag": "證券"},
                {"account": "US-ONE", "account_flag": "複委託"},
            ]
        )
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "KGI_SUPERPY_TW_ACCOUNT"):
                _select_account(api, "tw")
            self.assertEqual(_select_account(api, "us"), "US-ONE")

        with patch.dict(os.environ, {"KGI_SUPERPY_TW_ACCOUNT": "TW-TWO"}, clear=True):
            self.assertEqual(_select_account(api, "tw"), "TW-TWO")
        self.assertNotIn("TW-TWO", _safe_error(RuntimeError("failed TW-TWO")))

    def test_bridge_data_get_uses_strict_resource_allowlist_and_bounds(self) -> None:
        class _Frame:
            columns = ["股票代號", "成交價"]

            def __len__(self):
                return 2

            def tail(self, limit):
                self.limit = limit
                return self

            def to_dict(self, orient):
                self.orient = orient
                return [
                    {"股票代號": "2330", "成交價": 2400.0},
                    {"股票代號": "2330", "成交價": 2405.0},
                ]

        calls = []

        class _Data:
            def get(self, table, *args):
                calls.append((table, args))
                return _Frame()

        with patch.object(
            kgi_superpy_bridge,
            "_ensure_login",
            return_value=SimpleNamespace(Data=_Data()),
        ):
            result = _data_get(
                {
                    "resource": "market_snapshot",
                    "symbol": "2330",
                    "limit": 10,
                }
            )

        self.assertEqual(
            calls,
            [("批次取得個股盤中行情-含興櫃(tick含試搓)", (["2330"],))],
        )
        self.assertEqual(result["row_count"], 2)
        self.assertEqual(result["returned_count"], 2)
        self.assertEqual(result["records"][0]["成交價"], 2400.0)
        with self.assertRaisesRegex(ValueError, "Unsupported KGI Data resource"):
            _data_get({"resource": "arbitrary_table", "symbol": "2330"})

    def test_bridge_requires_64_bit_python_312_runtime(self) -> None:
        self.assertIsNone(_runtime_compatibility_error((3, 12), 64))
        self.assertIn(
            "Python 3.12",
            _runtime_compatibility_error((3, 13), 64) or "",
        )
        self.assertIn(
            "64-bit",
            _runtime_compatibility_error((3, 12), 32) or "",
        )

    def test_disabled_provider_returns_no_lease_and_no_process_requirement(self) -> None:
        manager = _NoProcessManager(_config(enable_kgi_superpy_quote=False))
        try:
            result = manager.acquire("2330")
        finally:
            manager.close()

        self.assertEqual(result["status"], "disabled")
        self.assertIsNone(result["lease_id"])

    def test_enabled_but_misconfigured_provider_keeps_visible_degraded_lease(self) -> None:
        manager = _NoProcessManager(_config(kgi_superpy_password=""))
        try:
            result = manager.acquire("2330")
            snapshot = manager.snapshot("2330")
            manager.release(result["lease_id"])
        finally:
            manager.close()

        self.assertEqual(result["status"], "unavailable")
        self.assertIsNotNone(result["lease_id"])
        self.assertEqual(snapshot.active_leases, 1)
        self.assertIn("KGI_SUPERPY_PASSWORD", snapshot.error)

    def test_multiple_viewers_share_one_symbol_reference(self) -> None:
        manager = _NoProcessManager(_config())
        try:
            first = manager.acquire("2330")
            second = manager.acquire("2330")
            self.assertNotEqual(first["lease_id"], second["lease_id"])
            self.assertEqual(manager.snapshot("2330").active_leases, 2)

            manager.release(first["lease_id"])
            self.assertEqual(manager.snapshot("2330").active_leases, 1)
            manager.release(second["lease_id"])
            self.assertEqual(manager.snapshot("2330").active_leases, 0)
        finally:
            manager.close()

    def test_lease_summary_is_owner_scoped_and_redacted(self) -> None:
        manager = _NoProcessManager(_config())
        try:
            frontend = manager.acquire("2330", owner_kind="frontend_viewer")
            probe = manager.acquire("2317", owner_kind="acceptance_probe")

            summary = manager.lease_summary()
            parsed = TaiwanRealtimeQuoteLeaseSummaryRead.model_validate(summary)

            self.assertEqual(parsed.total_active_leases, 2)
            self.assertEqual(parsed.active_symbol_count, 2)
            self.assertEqual(
                parsed.leases_by_owner_kind,
                {"acceptance_probe": 1, "frontend_viewer": 1},
            )
            self.assertEqual(parsed.leases_by_symbol, {"2317": 1, "2330": 1})
            self.assertFalse(parsed.bridge_process_running)
            self.assertNotIn(frontend["lease_id"], str(summary))
            self.assertNotIn(probe["lease_id"], str(summary))

            manager.release(frontend["lease_id"])
            manager.release(probe["lease_id"])
            self.assertEqual(manager.lease_summary()["total_active_leases"], 0)
        finally:
            manager.close()

    def test_lease_owner_kind_is_bounded_and_returned_on_heartbeat(self) -> None:
        request = TaiwanRealtimeQuoteLeaseCreate(
            stock_id="2330",
            owner_kind="acceptance_probe",
        )
        manager = _NoProcessManager(_config())
        try:
            lease = manager.acquire(request.stock_id, owner_kind=request.owner_kind)
            heartbeat = manager.heartbeat(lease["lease_id"])
            released = manager.release(lease["lease_id"])
        finally:
            manager.close()

        self.assertEqual(lease["owner_kind"], "acceptance_probe")
        self.assertEqual(heartbeat["owner_kind"], "acceptance_probe")
        self.assertEqual(released["owner_kind"], "acceptance_probe")
        with self.assertRaisesRegex(ValueError, "owner_kind"):
            manager.acquire("2330", owner_kind="unbounded_consumer")

    def test_snapshot_rejects_stale_provider_event(self) -> None:
        manager = _NoProcessManager(_config(kgi_superpy_quote_stale_seconds=5))
        try:
            lease_id = "lease"
            manager._leases[lease_id] = _Lease(
                lease_id=lease_id,
                symbol="2330",
                expires_at=10**12,
            )
            manager._symbol_leases["2330"] = {lease_id}
            manager._quotes["2330"] = {
                "symbol": "2330",
                "datetime": "20200101090000",
            }

            snapshot = manager.snapshot("2330")
        finally:
            manager.close()

        self.assertEqual(snapshot.status, "stale")
        self.assertIsNone(snapshot.quote)

    def test_snapshot_does_not_promote_cached_quote_while_reconnecting(self) -> None:
        manager = _NoProcessManager(_config())
        try:
            lease_id = "lease"
            manager._leases[lease_id] = _Lease(
                lease_id=lease_id,
                symbol="2330",
                expires_at=10**12,
            )
            manager._symbol_leases["2330"] = {lease_id}
            manager._quotes["2330"] = {
                "symbol": "2330",
                "datetime": datetime.now(TAIWAN_TZ).strftime("%Y%m%d%H%M%S"),
            }
            manager._symbol_status["2330"] = "reconnecting"

            snapshot = manager.snapshot("2330")
        finally:
            manager.close()

        self.assertEqual(snapshot.status, "reconnecting")
        self.assertIsNone(snapshot.quote)

    def test_bridge_serializes_only_the_quote_contract(self) -> None:
        quote = SimpleNamespace(
            exchange="TWStock",
            symbol="2330",
            datetime="20260630090512",
            close=2410.0,
            bid_prices=[2410.0],
            bid_volumes=[978],
            simtrade=1,
            private_account="must-not-leak",
        )

        payload = _quote_payload(quote)

        self.assertEqual(payload["symbol"], "2330")
        self.assertEqual(payload["simtrade"], 1)
        self.assertNotIn("private_account", payload)
        datetime.fromisoformat(payload["received_at"]).astimezone(timezone.utc)

    def test_sdk_quote_callback_has_no_annotations(self) -> None:
        # KGI 2.1.0 validates callback annotations and rejects postponed
        # ``-> None`` strings, so the protocol callback must remain unannotated.
        self.assertEqual(_on_quote.__annotations__, {})
        self.assertEqual(_on_kbar.__annotations__, {})

    def test_bridge_serializes_only_the_kbar_contract(self) -> None:
        kbar = SimpleNamespace(
            exchange="TWSE",
            symbol="2330",
            datetime="202606300905",
            timeframe=1,
            open=2400.0,
            high=2410.0,
            low=2395.0,
            close=2405.0,
            volume=310,
            avg_price=2402.5,
            total_amount=744775.0,
            account_id="must-not-leak",
        )

        payload = _kbar_payload(kbar)

        self.assertEqual(payload["timeframe"], 1)
        self.assertEqual(payload["avg_price"], 2402.5)
        self.assertNotIn("account_id", payload)

    def test_kbar_subscription_failure_does_not_cancel_all_quote(self) -> None:
        calls: list[tuple[str, str]] = []

        class _Quote:
            def subscribe_all(self, symbol, odd_lot=False):
                calls.append(("all", symbol))

            def subscribe_kbar(self, symbol, minute=1):
                calls.append(("kbar", symbol))
                raise RuntimeError("KBar permission denied")

        warning = _subscribe_symbol(SimpleNamespace(Quote=_Quote()), "2330")

        self.assertEqual(calls, [("all", "2330"), ("kbar", "2330")])
        self.assertIn("KBar permission denied", warning or "")

    def test_market_stream_separates_trades_and_simtrade_observations(self) -> None:
        manager = _NoProcessManager(_config())
        lease_id = "lease"
        manager._leases[lease_id] = _Lease(
            lease_id=lease_id,
            symbol="2330",
            expires_at=10**12,
        )
        manager._symbol_leases["2330"] = {lease_id}
        event_time = datetime(2026, 8, 21, 10, 0, 0, tzinfo=TAIWAN_TZ)
        try:
            manager._accept_quote(
                {
                    "symbol": "2330",
                    "datetime": event_time.strftime("%Y%m%d%H%M%S"),
                    "received_at": "2026-08-21T02:00:00.100000+00:00",
                    "close": 2400,
                    "volume": 8,
                    "total_volume": 100,
                    "bid_prices": [2395, 2390],
                    "bid_volumes": [20, 30],
                    "ask_prices": [2400, 2405],
                    "ask_volumes": [10, 15],
                    "diff_bid_vol": [2, -1],
                    "diff_ask_vol": [3, 1],
                    "simtrade": 0,
                }
            )
            manager._accept_quote(
                {
                    "symbol": "2330",
                    "datetime": "20260821100001",
                    "received_at": "2026-08-21T02:00:01.100000+00:00",
                    "close": 2405,
                    "volume": 12,
                    "total_volume": 112,
                    "bid_prices": [2400],
                    "bid_volumes": [22],
                    "ask_prices": [2405],
                    "ask_volumes": [18],
                    "diff_bid_vol": [2],
                    "diff_ask_vol": [8],
                    "simtrade": 0,
                }
            )
            manager._accept_quote(
                {
                    "symbol": "2330",
                    "datetime": "20260821100002",
                    "received_at": "2026-08-21T02:00:02.100000+00:00",
                    "close": 2410,
                    "volume": 5,
                    "total_volume": 112,
                    "bid_prices": [2405],
                    "bid_volumes": [22],
                    "ask_prices": [2410],
                    "ask_volumes": [18],
                    "diff_bid_vol": [2],
                    "diff_ask_vol": [8],
                    "simtrade": 1,
                }
            )

            parsed = _read_market_stream(manager, "2330", diagnostic_limit=10)
        finally:
            manager.close()

        self.assertEqual(len(parsed.recent_trades), 1)
        self.assertEqual(parsed.recent_trades[0].price, 2405)
        self.assertEqual(len(parsed.auction_observations), 1)
        self.assertEqual(
            parsed.auction_observations[0].semantics,
            "provider_simtrade_indicative_not_formal_trade",
        )
        self.assertAlmostEqual(parsed.depth_metrics.top5_imbalance, 0.1)
        self.assertEqual(parsed.diagnostic_counters.callback_count, 3)
        self.assertEqual(parsed.diagnostic_counters.baseline_only_count, 1)
        self.assertEqual(parsed.diagnostic_counters.trade_addition_count, 1)
        self.assertEqual(parsed.diagnostic_counters.auction_addition_count, 1)
        self.assertEqual(
            [event.projection_action for event in parsed.diagnostic_events],
            ["baseline_only", "trade_added", "auction_added"],
        )

    def test_market_stream_regular_cold_start_uses_positive_total_as_baseline(self) -> None:
        manager = _NoProcessManager(_config())
        try:
            manager._accept_quote(
                {
                    "symbol": "2330",
                    "datetime": "20260821100000",
                    "received_at": "2026-08-21T02:00:00.100000+00:00",
                    "close": 2400,
                    "volume": 8,
                    "total_volume": 100,
                    "simtrade": 0,
                    "account_id": "must-not-leak",
                }
            )
            parsed = _read_market_stream(manager, "2330", diagnostic_limit=10)
        finally:
            manager.close()

        self.assertEqual(parsed.session_phase, "regular")
        self.assertEqual(parsed.recent_trades, [])
        self.assertEqual(parsed.diagnostic_counters.baseline_only_count, 1)
        self.assertEqual(len(parsed.diagnostic_events), 1)
        diagnostic = parsed.diagnostic_events[0]
        self.assertEqual(diagnostic.cumulative_relation, "baseline")
        self.assertEqual(diagnostic.projection_action, "baseline_only")
        self.assertNotIn("account_id", diagnostic.model_dump())
        self.assertNotIn("must-not-leak", str(diagnostic.model_dump()))

    def test_market_stream_diagnostic_history_is_opt_in(self) -> None:
        manager = _NoProcessManager(_config())
        try:
            manager._accept_quote(
                {
                    "symbol": "2330",
                    "datetime": "20260821100000",
                    "received_at": "2026-08-21T02:00:00.100000+00:00",
                    "close": 2400,
                    "volume": 8,
                    "total_volume": 100,
                    "simtrade": 0,
                }
            )
            outward_default = manager.market_stream_snapshot("2330")
            diagnostics_enabled = manager.market_stream_snapshot(
                "2330",
                diagnostic_limit=1,
            )
        finally:
            manager.close()

        self.assertEqual(outward_default["diagnostic_events"], [])
        self.assertEqual(outward_default["diagnostic_counters"]["callback_count"], 1)
        self.assertEqual(len(diagnostics_enabled["diagnostic_events"]), 1)

    def test_market_stream_post_close_cold_start_requires_cumulative_advance(self) -> None:
        manager = _NoProcessManager(_config())
        try:
            manager._accept_quote(
                {
                    "symbol": "2330",
                    "datetime": "20260821140000",
                    "received_at": "2026-08-21T06:00:00.100000+00:00",
                    "close": 2410,
                    "volume": 4,
                    "total_volume": 12000,
                    "simtrade": 0,
                }
            )
            cold_start = manager.market_stream_snapshot("2330", diagnostic_limit=10)
            manager._accept_quote(
                {
                    "symbol": "2330",
                    "datetime": "20260821140001",
                    "received_at": "2026-08-21T06:00:01.100000+00:00",
                    "close": 2410,
                    "volume": 2,
                    "total_volume": 12002,
                    "simtrade": 0,
                }
            )
            advanced = manager.market_stream_snapshot("2330", diagnostic_limit=10)
        finally:
            manager.close()

        self.assertEqual(cold_start["session_phase"], "post_close")
        self.assertEqual(cold_start["recent_trades"], [])
        self.assertEqual(cold_start["diagnostic_events"][0]["projection_action"], "baseline_only")
        self.assertEqual(len(advanced["recent_trades"]), 1)
        self.assertEqual(advanced["recent_trades"][0]["total_volume_lots"], 12002)

    def test_market_stream_zero_cumulative_quote_is_auction_not_trade(self) -> None:
        manager = _NoProcessManager(_config())
        event_time = datetime(2026, 8, 21, 10, 0, 0, tzinfo=TAIWAN_TZ)
        try:
            manager._accept_quote(
                {
                    "symbol": "2330",
                    "datetime": event_time.strftime("%Y%m%d%H%M%S"),
                    "received_at": datetime.now(timezone.utc).isoformat(),
                    "close": 2405,
                    "volume": 12,
                    "total_volume": 0,
                    "bid_prices": [2400],
                    "bid_volumes": [22],
                    "ask_prices": [2405],
                    "ask_volumes": [18],
                    "simtrade": 0,
                }
            )
            payload = manager.market_stream_snapshot("2330", diagnostic_limit=10)
        finally:
            manager.close()

        self.assertEqual(payload["recent_trades"], [])
        self.assertEqual(payload["capability_status"]["recent_trades"], "empty")
        self.assertEqual(len(payload["auction_observations"]), 1)
        self.assertEqual(
            payload["auction_observations"][0]["semantics"],
            "provider_zero_cumulative_volume_indicative_not_formal_trade",
        )

    def test_market_stream_closing_trial_pair_requires_cumulative_advance(self) -> None:
        manager = _NoProcessManager(_config())
        event_time = datetime(2026, 8, 21, 13, 29, 58, tzinfo=TAIWAN_TZ)
        base_quote = {
            "symbol": "2330",
            "datetime": event_time.strftime("%Y%m%d%H%M%S"),
            "received_at": datetime.now(timezone.utc).isoformat(),
            "close": 2410,
            "volume": 4045,
            "total_volume": 11655,
            "bid_prices": [2405],
            "bid_volumes": [10],
            "ask_prices": [2410],
            "ask_volumes": [12],
        }
        try:
            manager._accept_quote({**base_quote, "simtrade": 1})
            manager._accept_quote({**base_quote, "simtrade": 0})
            before_final_match = manager.market_stream_snapshot("2330")

            manager._accept_quote(
                {
                    **base_quote,
                    "datetime": "20260821133000",
                    "received_at": datetime.now(timezone.utc).isoformat(),
                    "simtrade": 0,
                    "total_volume": 15700,
                }
            )
            after_final_match = manager.market_stream_snapshot("2330")
        finally:
            manager.close()

        self.assertEqual(before_final_match["recent_trades"], [])
        self.assertEqual(len(before_final_match["auction_observations"]), 2)
        self.assertEqual(
            before_final_match["auction_observations"][0]["semantics"],
            "provider_unchanged_cumulative_volume_trial_not_formal_trade",
        )
        self.assertEqual(len(after_final_match["recent_trades"]), 1)
        self.assertEqual(after_final_match["recent_trades"][0]["price"], 2410)
        self.assertEqual(
            after_final_match["recent_trades"][0]["total_volume_lots"],
            15700,
        )

    def test_market_stream_closing_auction_cold_start_fails_closed(self) -> None:
        manager = _NoProcessManager(_config())
        try:
            manager._accept_quote(
                {
                    "exchange": "TWSE",
                    "symbol": "2330",
                    "datetime": "20260821132958",
                    "received_at": "2026-08-21T05:29:58.100000+00:00",
                    "close": 2410,
                    "volume": 4045,
                    "total_volume": 11655,
                    "bid_prices": [2405, 2400],
                    "bid_volumes": [10, 20],
                    "ask_prices": [2410, 2415],
                    "ask_volumes": [12, 18],
                    "delay_time": 25,
                    "simtrade": 0,
                }
            )
            parsed = _read_market_stream(manager, "2330")
        finally:
            manager.close()

        self.assertEqual(parsed.contract_version, "omi.tw.realtime_stream.v2")
        self.assertEqual(parsed.session_phase, "closing_auction")
        self.assertEqual(parsed.recent_trades, [])
        self.assertEqual(len(parsed.auction_observations), 1)
        self.assertEqual(
            parsed.auction_observations[0].semantics,
            "session_closing_auction_indicative_not_formal_trade",
        )
        self.assertIsNotNone(parsed.depth)
        assert parsed.depth is not None
        self.assertEqual(parsed.depth.capability, "level_5")
        self.assertEqual(parsed.depth.bid_levels[0].size_lots, 10)
        self.assertEqual(parsed.depth.bid_levels[0].size_shares, 10000)
        self.assertIsNotNone(parsed.latency)
        assert parsed.latency is not None
        self.assertEqual(parsed.latency.provider_delay_raw, 25)
        self.assertEqual(parsed.latency.provider_delay_unit, "unknown")

    def test_market_stream_closed_day_positive_quote_is_not_a_trade(self) -> None:
        manager = _NoProcessManager(_config())
        try:
            manager._accept_quote(
                {
                    "symbol": "2330",
                    "datetime": "20260822100000",
                    "received_at": "2026-08-22T02:00:00.100000+00:00",
                    "close": 2410,
                    "volume": 5,
                    "total_volume": 12000,
                    "simtrade": 0,
                }
            )
            payload = manager.market_stream_snapshot("2330")
        finally:
            manager.close()

        self.assertEqual(payload["session_phase"], "market_closed")
        self.assertEqual(payload["recent_trades"], [])
        self.assertEqual(payload["auction_observations"], [])

    def test_market_stream_unchanged_cumulative_volume_does_not_create_trade(self) -> None:
        manager = _NoProcessManager(_config())
        event_time = datetime(2026, 8, 21, 10, 0, 0, tzinfo=TAIWAN_TZ)
        try:
            manager._accept_quote(
                {
                    "symbol": "2330",
                    "datetime": event_time.strftime("%Y%m%d%H%M%S"),
                    "received_at": datetime.now(timezone.utc).isoformat(),
                    "close": 2400,
                    "volume": 8,
                    "total_volume": 100,
                    "simtrade": 0,
                }
            )
            manager._accept_quote(
                {
                    "symbol": "2330",
                    "datetime": "20260821100001",
                    "received_at": datetime.now(timezone.utc).isoformat(),
                    "close": 2405,
                    "volume": 12,
                    "total_volume": 100,
                    "simtrade": 0,
                }
            )
            payload = manager.market_stream_snapshot("2330", diagnostic_limit=10)
        finally:
            manager.close()

        self.assertEqual(payload["recent_trades"], [])
        self.assertEqual(payload["diagnostic_counters"]["baseline_only_count"], 1)
        self.assertEqual(payload["diagnostic_counters"]["same_cumulative_count"], 1)
        self.assertEqual(
            [event["projection_action"] for event in payload["diagnostic_events"]],
            ["baseline_only", "same_cumulative_suppressed"],
        )

    def test_market_stream_decreasing_cumulative_volume_is_suppressed(self) -> None:
        manager = _NoProcessManager(_config())
        try:
            manager._accept_quote(
                {
                    "symbol": "2330",
                    "datetime": "20260821100000",
                    "received_at": "2026-08-21T02:00:00.100000+00:00",
                    "close": 2400,
                    "volume": 8,
                    "total_volume": 100,
                    "simtrade": 0,
                }
            )
            manager._accept_quote(
                {
                    "symbol": "2330",
                    "datetime": "20260821100001",
                    "received_at": "2026-08-21T02:00:01.100000+00:00",
                    "close": 2405,
                    "volume": 12,
                    "total_volume": 99,
                    "simtrade": 0,
                }
            )
            payload = manager.market_stream_snapshot("2330", diagnostic_limit=10)
        finally:
            manager.close()

        self.assertEqual(payload["recent_trades"], [])
        self.assertEqual(payload["diagnostic_counters"]["decreasing_cumulative_count"], 1)
        self.assertEqual(
            payload["diagnostic_events"][-1]["projection_action"],
            "decreasing_cumulative_suppressed",
        )

    def test_market_stream_resets_cross_date_buffers_and_rejects_old_kbar(self) -> None:
        manager = _NoProcessManager(_config())
        today = datetime.now(TAIWAN_TZ)
        yesterday = today - timedelta(days=1)
        try:
            manager._accept_quote(
                {
                    "symbol": "2330",
                    "datetime": yesterday.strftime("%Y%m%d%H%M%S"),
                    "received_at": datetime.now(timezone.utc).isoformat(),
                    "close": 2390,
                    "volume": 5,
                    "total_volume": 100,
                    "simtrade": 0,
                }
            )
            manager._accept_quote(
                {
                    "symbol": "2330",
                    "datetime": today.strftime("%Y%m%d%H%M%S"),
                    "received_at": datetime.now(timezone.utc).isoformat(),
                    "close": 2405,
                    "volume": 12,
                    "total_volume": 0,
                    "simtrade": 0,
                }
            )
            manager._accept_quote(
                {
                    "symbol": "2330",
                    "datetime": yesterday.strftime("%Y%m%d%H%M%S"),
                    "received_at": datetime.now(timezone.utc).isoformat(),
                    "close": 2390,
                    "volume": 100,
                    "total_volume": 500,
                    "simtrade": 0,
                }
            )
            manager._accept_kbar(
                {
                    "symbol": "2330",
                    "datetime": yesterday.strftime("%Y%m%d%H%M"),
                    "received_at": datetime.now(timezone.utc).isoformat(),
                    "timeframe": 1,
                    "open": 2390,
                    "high": 2390,
                    "low": 2390,
                    "close": 2390,
                    "volume": 100,
                }
            )
            payload = manager.market_stream_snapshot("2330", diagnostic_limit=10)
        finally:
            manager.close()

        self.assertEqual(payload["recent_trades"], [])
        self.assertEqual(payload["minute_kbars"], [])
        self.assertEqual(len(payload["auction_observations"]), 1)
        self.assertEqual(payload["event_time"][:10], today.date().isoformat())
        self.assertEqual(payload["diagnostic_counters"]["cross_date_rejected_count"], 1)
        self.assertEqual(payload["diagnostic_events"][-1]["projection_action"], "cross_date_rejected")

    def test_market_stream_deduplicates_trade_and_upserts_minute_kbar(self) -> None:
        manager = _NoProcessManager(_config())
        lease_id = "lease"
        manager._leases[lease_id] = _Lease(
            lease_id=lease_id,
            symbol="2330",
            expires_at=10**12,
        )
        manager._symbol_leases["2330"] = {lease_id}
        event_time = datetime(2026, 8, 21, 10, 0, 0, tzinfo=TAIWAN_TZ)
        quote = {
            "symbol": "2330",
            "datetime": event_time.strftime("%Y%m%d%H%M%S"),
            "received_at": datetime.now(timezone.utc).isoformat(),
            "close": 2400,
            "volume": 8,
            "total_volume": 100,
            "simtrade": 0,
        }
        try:
            manager._accept_quote(quote)
            manager._accept_quote(quote)
            manager._accept_quote(
                {
                    **quote,
                    "datetime": (event_time + timedelta(seconds=1)).strftime("%Y%m%d%H%M%S"),
                    "total_volume": 108,
                }
            )
            manager._accept_quote(
                {
                    **quote,
                    "datetime": (event_time + timedelta(seconds=1)).strftime("%Y%m%d%H%M%S"),
                    "total_volume": 108,
                }
            )
            kbar = {
                "symbol": "2330",
                "datetime": event_time.strftime("%Y%m%d%H%M"),
                "received_at": datetime.now(timezone.utc).isoformat(),
                "timeframe": 1,
                "open": 2395,
                "high": 2400,
                "low": 2395,
                "close": 2398,
                "volume": 20,
                "avg_price": 2397,
                "total_amount": 47940,
            }
            manager._accept_kbar(kbar)
            manager._accept_kbar({**kbar, "close": 2400, "volume": 28})
            payload = manager.market_stream_snapshot("2330")
        finally:
            manager.close()

        self.assertEqual(len(payload["recent_trades"]), 1)
        self.assertEqual(len(payload["minute_kbars"]), 1)
        self.assertEqual(payload["minute_kbars"][0]["close"], 2400)
        self.assertEqual(
            payload["minute_kbars"][0]["provider_event_time"],
            event_time.isoformat(),
        )
        self.assertEqual(
            payload["minute_kbars"][0]["canonical_start_at"],
            (event_time - timedelta(minutes=1)).isoformat(),
        )
        self.assertEqual(
            payload["minute_kbars"][0]["timestamp_semantics"],
            "provider_bucket_end_normalized_to_canonical_start",
        )
        self.assertEqual(
            payload["minute_kbars"][0]["total_amount_semantics"],
            "provider_cumulative_not_minute_turnover",
        )
        self.assertEqual(payload["capability_status"]["minute_kbars"], "available")

    def test_released_stream_diagnostics_are_retained_but_not_current(self) -> None:
        manager = _NoProcessManager(_config())
        event_time = datetime(2026, 8, 21, 10, 0, 0, tzinfo=TAIWAN_TZ)
        try:
            manager._accept_kbar(
                {
                    "symbol": "2330",
                    "datetime": event_time.strftime("%Y%m%d%H%M"),
                    "received_at": datetime.now(timezone.utc).isoformat(),
                    "timeframe": 1,
                    "open": 2395,
                    "high": 2400,
                    "low": 2395,
                    "close": 2398,
                    "volume": 20,
                }
            )
            with manager._lock:
                manager._archive_symbol_diagnostics_locked("2330")
                manager._minute_kbars.pop("2330", None)
            payload = manager.market_stream_snapshot("2330")
        finally:
            manager.close()

        self.assertTrue(
            payload["diagnostic_retention"]["retained_after_release"]
        )
        self.assertEqual(
            payload["selection_reason"],
            "retained_diagnostics_after_lease_release",
        )
        self.assertEqual(payload["capability_status"]["minute_kbars"], "retained")
        self.assertEqual(len(payload["minute_kbars"]), 1)

    def test_data_backfill_classifies_provider_permission_failure(self) -> None:
        manager = _NoProcessManager(_config())
        try:
            with patch.object(
                manager,
                "_request",
                return_value={
                    "ok": False,
                    "error": (
                        "StatusCode: D403, Detail: Access denied; "
                        "confirm relevant permissions."
                    ),
                },
            ):
                result = manager.fetch_data_backfill(
                    resource="today_trades",
                    symbol="2330",
                    trade_date="20260818",
                )
        finally:
            manager.close()

        self.assertEqual(result["status"], "plan_restricted")

    def test_data_backfill_service_returns_partial_contract(self) -> None:
        def _result(*, resource, **_kwargs):
            if resource == "market_snapshot":
                return {
                    "resource": resource,
                    "status": "available",
                    "table": "snapshot",
                    "row_count": 1,
                    "returned_count": 1,
                    "columns": ["股票代號"],
                    "records": [{"股票代號": "2330"}],
                }
            return {
                "resource": resource,
                "status": "plan_restricted",
                "error": "D403 permission denied",
            }

        request = TaiwanKgiDataBackfillRequest(
            resources=["market_snapshot", "today_trades"],
        )
        with patch(
            "app.market.kgi_market_data.fetch_kgi_superpy_data_backfill",
            side_effect=_result,
        ):
            payload = backfill_taiwan_kgi_market_data(
                stock_id="2330",
                request=request,
                now=datetime(2026, 8, 18, 12, tzinfo=timezone.utc),
            )
        parsed = TaiwanKgiDataBackfillRead.model_validate(payload)

        self.assertEqual(parsed.status, "partial")
        self.assertEqual(parsed.provider_request_count, 2)
        self.assertEqual(parsed.resources[0].status, "available")
        self.assertEqual(parsed.resources[1].status, "plan_restricted")

    def test_bridge_classifies_missing_quote_facade_as_login_initialization_failure(
        self,
    ) -> None:
        logout_calls: list[bool] = []
        order = SimpleNamespace(
            FIsLogon=False,
            _URL=SimpleNamespace(token=None),
            Logout=lambda: logout_calls.append(True),
        )
        api = SimpleNamespace(_ObjOrder=order)
        fake_sdk = SimpleNamespace(login=lambda *_args: api)
        previous_api = kgi_superpy_bridge._API
        kgi_superpy_bridge._API = None
        try:
            with (
                patch.dict(
                    os.environ,
                    {
                        "KGI_SUPERPY_PERSON_ID": "A123456789",
                        "KGI_SUPERPY_PASSWORD": "secret",
                        "KGI_SUPERPY_SIMULATION": "false",
                    },
                ),
                patch.dict(sys.modules, {"kgisuperpy": fake_sdk}),
            ):
                with self.assertRaisesRegex(RuntimeError, "CA component"):
                    _ensure_login()
        finally:
            kgi_superpy_bridge._API = previous_api

        self.assertEqual(logout_calls, [True])


if __name__ == "__main__":
    unittest.main()
