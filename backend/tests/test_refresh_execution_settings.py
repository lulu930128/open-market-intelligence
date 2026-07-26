from __future__ import annotations

from contextlib import contextmanager
import json
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import AppSetting, Base
from app.main import app
from app.routers.settings import (
    get_refresh_execution_settings_endpoint,
    update_refresh_execution_settings_endpoint,
)
from app.settings import refresh_execution
from app.settings.refresh_execution import (
    get_refresh_execution_settings,
    resolve_market_refresh_interval_seconds,
    resolve_observed_stock_refresh_interval_seconds,
    resolve_subresource_refresh_interval_seconds,
    update_refresh_execution_settings,
)
from app.settings.schemas import RefreshExecutionSettingsWrite
from app.settings.store import REFRESH_EXECUTION_SETTING_KEY


@contextmanager
def settings_db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    try:
        with Session(engine) as db:
            yield db
    finally:
        engine.dispose()


def _market_policy(
    *,
    observed: float,
    subresource: float,
    market: float,
) -> dict[str, float]:
    return {
        "observed_stock_refresh_interval_seconds": observed,
        "subresource_refresh_interval_seconds": subresource,
        "market_refresh_interval_seconds": market,
    }


def _settings_payload() -> RefreshExecutionSettingsWrite:
    return RefreshExecutionSettingsWrite(
        markets={
            "tw": _market_policy(observed=1.2, subresource=0.4, market=0.6),
            "us": _market_policy(observed=20.0, subresource=30.0, market=40.0),
            "jp": _market_policy(observed=2.0, subresource=15.0, market=25.0),
            "kr": _market_policy(observed=2.5, subresource=16.0, market=26.0),
        }
    )


class RefreshExecutionSettingsTests(unittest.TestCase):
    def test_refresh_execution_defaults_reflect_backend_config(self) -> None:
        with (
            settings_db_session() as db,
            patch.object(refresh_execution.settings, "scheduler_market_refresh_sleep_seconds", 0.7),
            patch.object(refresh_execution.settings, "scheduler_us_market_refresh_sleep_seconds", 21.0),
            patch.object(refresh_execution.settings, "scheduler_jp_market_refresh_sleep_seconds", 31.0),
            patch.object(refresh_execution.settings, "scheduler_kr_market_refresh_sleep_seconds", 32.0),
        ):
            response = get_refresh_execution_settings(db=db)

        self.assertEqual(response.kind, "refresh_execution_settings")
        self.assertEqual(response.version, "refresh_execution_settings.v1")
        self.assertEqual(response.source, "backend_config")
        self.assertEqual(response.markets.tw.observed_stock_refresh_interval_seconds, 0.8)
        self.assertEqual(response.markets.tw.subresource_refresh_interval_seconds, 0.2)
        self.assertEqual(response.markets.tw.market_refresh_interval_seconds, 0.7)
        self.assertEqual(response.markets.us.market_refresh_interval_seconds, 21.0)
        self.assertEqual(response.markets.jp.market_refresh_interval_seconds, 31.0)
        self.assertEqual(response.markets.kr.market_refresh_interval_seconds, 32.0)

    def test_update_refresh_execution_settings_persists_database_override(self) -> None:
        with settings_db_session() as db:
            payload = _settings_payload()

            response = update_refresh_execution_settings(db=db, payload=payload)
            row = db.query(AppSetting).filter(
                AppSetting.setting_key == REFRESH_EXECUTION_SETTING_KEY
            ).one()
            stored_payload = json.loads(row.value_json)
            reread = get_refresh_execution_settings(db=db)

        self.assertEqual(response.source, "database")
        self.assertEqual(stored_payload["markets"]["tw"]["subresource_refresh_interval_seconds"], 0.4)
        self.assertEqual(stored_payload["markets"]["us"]["observed_stock_refresh_interval_seconds"], 20.0)
        self.assertEqual(reread.source, "database")
        self.assertEqual(reread.markets.jp.market_refresh_interval_seconds, 25.0)
        self.assertEqual(reread.markets.kr.market_refresh_interval_seconds, 26.0)

    def test_refresh_execution_resolvers_use_explicit_value_first(self) -> None:
        with settings_db_session() as db:
            update_refresh_execution_settings(db=db, payload=_settings_payload())

            observed = resolve_observed_stock_refresh_interval_seconds(
                db=db,
                market="tw",
                explicit_sleep_seconds=None,
            )
            subresource = resolve_subresource_refresh_interval_seconds(
                db=db,
                market="tw",
                explicit_sleep_seconds=None,
            )
            market = resolve_market_refresh_interval_seconds(
                db=db,
                market="tw",
                explicit_sleep_seconds=None,
            )
            explicit = resolve_subresource_refresh_interval_seconds(
                db=db,
                market="tw",
                explicit_sleep_seconds=0.05,
            )

        self.assertEqual(observed, 1.2)
        self.assertEqual(subresource, 0.4)
        self.assertEqual(market, 0.6)
        self.assertEqual(explicit, 0.05)

    def test_refresh_execution_settings_endpoint_uses_service_schema(self) -> None:
        with settings_db_session() as db:
            response = get_refresh_execution_settings_endpoint(db=db)

        self.assertEqual(response.kind, "refresh_execution_settings")
        self.assertEqual(response.markets.tw.observed_stock_refresh_interval_seconds, 0.8)

    def test_update_refresh_execution_settings_endpoint_persists(self) -> None:
        with settings_db_session() as db:
            response = update_refresh_execution_settings_endpoint(
                payload=_settings_payload(),
                db=db,
            )

        self.assertEqual(response.source, "database")
        self.assertEqual(response.markets.us.subresource_refresh_interval_seconds, 30.0)

    def test_refresh_execution_settings_route_is_registered(self) -> None:
        matching_routes = [
            route
            for route in app.routes
            if getattr(route, "path", None) == "/api/settings/refresh-execution"
        ]
        registered_methods = set().union(
            *(getattr(route, "methods", set()) for route in matching_routes)
        )

        self.assertIn("GET", registered_methods)
        self.assertIn("PUT", registered_methods)


if __name__ == "__main__":
    unittest.main()
