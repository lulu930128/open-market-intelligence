from __future__ import annotations

import asyncio
from contextlib import contextmanager
import json
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import AppSetting, Base
from app.main import app
from app.routers.settings import (
    get_market_data_subscription_settings_endpoint,
    update_market_data_subscription_settings_endpoint,
)
from app.settings.market_data_subscription import (
    get_market_data_subscription_settings,
    update_market_data_subscription_settings,
)
from app.settings.schemas import MarketDataSubscriptionSettingsWrite
from app.settings.store import MARKET_DATA_SUBSCRIPTION_SETTING_KEY


@contextmanager
def settings_db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    try:
        with Session(engine) as db:
            yield db
    finally:
        engine.dispose()


def _settings_payload() -> MarketDataSubscriptionSettingsWrite:
    return MarketDataSubscriptionSettingsWrite(
        items=[
            {
                "key": "crypto:BTC",
                "mode": "manual",
                "resources": {
                    "quote": True,
                    "order_book": False,
                    "ohlcv": True,
                    "derivatives": True,
                    "taiwan_spread": True,
                    "market_cap": True,
                },
                "intervals": {
                    "quote_seconds": 10.0,
                    "order_book_seconds": 15.0,
                    "ohlcv_seconds": 60.0,
                    "derivatives_seconds": 180.0,
                    "market_cap_seconds": 1200.0,
                },
            },
            {
                "key": "commodity:energy:CL",
                "mode": "on_select",
                "resources": {"quote": True, "ohlcv": False},
                "intervals": {"quote_seconds": 120.0, "ohlcv_seconds": 600.0},
            },
        ]
    )


class MarketDataSubscriptionSettingsTests(unittest.TestCase):
    def test_market_data_subscription_defaults_include_crypto_and_resources(self) -> None:
        with settings_db_session() as db:
            response = get_market_data_subscription_settings(db=db)

        by_key = {item.key: item for item in response.items}

        self.assertEqual(response.kind, "market_data_subscription_settings")
        self.assertEqual(response.version, "market_data_subscription_settings.v1")
        self.assertEqual(response.source, "backend_config")
        self.assertEqual(by_key["crypto:BTC"].mode, "always_on")
        self.assertTrue(by_key["crypto:BTC"].resources["order_book"])
        self.assertEqual(by_key["crypto:SOL"].mode, "on_select")
        self.assertTrue(by_key["crypto:SOL"].resources["derivatives"])
        self.assertNotIn("taiwan_spread", by_key["crypto:SOL"].resources)
        self.assertEqual(by_key["crypto:USDT"].mode, "on_select")
        self.assertTrue(by_key["crypto:USDT"].resources["twd_reference"])
        self.assertNotIn("derivatives", by_key["crypto:USDT"].resources)
        self.assertEqual(by_key["commodity:metals:GC"].mode, "manual")
        self.assertEqual(by_key["commodity:metals:GC"].provider_status, "provider_pending")

    def test_update_market_data_subscription_settings_persists_database_override(self) -> None:
        with settings_db_session() as db:
            response = update_market_data_subscription_settings(
                db=db,
                payload=_settings_payload(),
            )
            row = db.query(AppSetting).filter(
                AppSetting.setting_key == MARKET_DATA_SUBSCRIPTION_SETTING_KEY
            ).one()
            stored_payload = json.loads(row.value_json)
            reread = get_market_data_subscription_settings(db=db)

        by_key = {item.key: item for item in response.items}
        reread_by_key = {item.key: item for item in reread.items}

        self.assertEqual(response.source, "database")
        self.assertEqual(stored_payload["items"][0]["key"], "crypto:BTC")
        self.assertEqual(by_key["crypto:BTC"].mode, "manual")
        self.assertFalse(by_key["crypto:BTC"].resources["order_book"])
        self.assertEqual(by_key["crypto:BTC"].intervals["quote_seconds"], 10.0)
        self.assertEqual(reread.source, "database")
        self.assertEqual(reread_by_key["commodity:energy:CL"].mode, "on_select")
        self.assertFalse(reread_by_key["commodity:energy:CL"].resources["ohlcv"])

    def test_market_data_subscription_endpoint_uses_service_schema(self) -> None:
        with settings_db_session() as db:
            response = get_market_data_subscription_settings_endpoint(db=db)

        self.assertEqual(response.kind, "market_data_subscription_settings")
        self.assertGreaterEqual(len(response.items), 9)

    def test_update_market_data_subscription_endpoint_persists(self) -> None:
        with settings_db_session() as db:
            with patch(
                "app.routers.settings.reload_crypto_realtime_collectors",
                new=AsyncMock(return_value={"enabled": False, "running": False, "enabled_streams": []}),
            ), patch(
                "app.routers.settings.reload_crypto_auto_refresh",
                new=AsyncMock(return_value={"enabled": True, "running": False, "active_resource_count": 0}),
            ):
                response = asyncio.run(
                    update_market_data_subscription_settings_endpoint(
                        payload=_settings_payload(),
                        db=db,
                    )
                )

        by_key = {item.key: item for item in response.items}
        self.assertEqual(response.source, "database")
        self.assertEqual(by_key["crypto:BTC"].mode, "manual")
        self.assertEqual(by_key["commodity:energy:CL"].mode, "on_select")
        self.assertEqual(response.runtime["crypto_realtime_reload"]["status"], "success")
        self.assertEqual(response.runtime["crypto_auto_refresh_reload"]["status"], "success")

    def test_update_market_data_subscription_endpoint_reloads_crypto_realtime_runtime(self) -> None:
        with settings_db_session() as db:
            with patch(
                "app.routers.settings.reload_crypto_realtime_collectors",
                new=AsyncMock(
                    return_value={
                        "enabled": False,
                        "running": False,
                        "enabled_streams": [{"provider": "bitopro"}],
                        "reload_count": 3,
                        "last_reload_at": "2026-06-26T00:00:00+00:00",
                    }
                ),
            ) as realtime_reloader, patch(
                "app.routers.settings.reload_crypto_auto_refresh",
                new=AsyncMock(
                    return_value={
                        "enabled": True,
                        "running": True,
                        "active_resource_count": 6,
                        "reload_count": 4,
                        "last_reload_at": "2026-06-26T00:00:01+00:00",
                    }
                ),
            ) as auto_reloader:
                response = asyncio.run(
                    update_market_data_subscription_settings_endpoint(
                        payload=_settings_payload(),
                        db=db,
                    )
                )

        realtime_reloader.assert_awaited_once_with(
            reason="market_data_subscription_settings_updated"
        )
        auto_reloader.assert_awaited_once_with(
            reason="market_data_subscription_settings_updated"
        )
        self.assertEqual(response.runtime["crypto_realtime_reload"]["status"], "success")
        self.assertEqual(response.runtime["crypto_realtime_reload"]["enabled_stream_count"], 1)
        self.assertEqual(response.runtime["crypto_realtime_reload"]["reload_count"], 3)
        self.assertEqual(response.runtime["crypto_auto_refresh_reload"]["status"], "success")
        self.assertEqual(response.runtime["crypto_auto_refresh_reload"]["active_resource_count"], 6)
        self.assertEqual(response.runtime["crypto_auto_refresh_reload"]["reload_count"], 4)

    def test_market_data_subscription_route_is_registered(self) -> None:
        matching_routes = [
            route
            for route in app.routes
            if getattr(route, "path", None)
            == "/api/settings/market-data-subscriptions"
        ]
        registered_methods = set().union(
            *(getattr(route, "methods", set()) for route in matching_routes)
        )

        self.assertIn("GET", registered_methods)
        self.assertIn("PUT", registered_methods)


if __name__ == "__main__":
    unittest.main()
