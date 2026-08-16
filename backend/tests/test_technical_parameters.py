from __future__ import annotations

from contextlib import contextmanager
from datetime import date, timedelta
import json
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import AppSetting, Base
from app.market import technical_parameters
from app.market import indicator_service
from app.market.indicator_service import calculate_indicator_points_from_ohlc_points
from app.main import app
from app.routers.settings import (
    get_technical_analysis_settings_endpoint,
    update_technical_analysis_settings_endpoint,
)
from app.settings.schemas import TechnicalAnalysisSettingsWrite
from app.settings.service import get_technical_analysis_settings, update_technical_analysis_settings
from app.settings.store import TECHNICAL_ANALYSIS_SETTING_KEY


def _points(count: int) -> list[dict]:
    start = date(2026, 1, 1)
    return [
        {
            "time": start + timedelta(days=index),
            "open": 100.0 + index,
            "high": 102.0 + index,
            "low": 98.0 + index,
            "close": 100.0 + index,
            "volume": 1_000 + (index * 10),
            "price_change": 1.0 if index else None,
        }
        for index in range(count)
    ]


@contextmanager
def settings_db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    try:
        with Session(engine) as db:
            yield db
    finally:
        engine.dispose()


def _write_payload_from_defaults(db: Session) -> TechnicalAnalysisSettingsWrite:
    current = get_technical_analysis_settings(db=db).model_dump()
    return TechnicalAnalysisSettingsWrite(
        windows=current["windows"],
        periods=current["periods"],
        thresholds=current["thresholds"],
    )


class TechnicalParametersTests(unittest.TestCase):
    def test_query_overrides_use_same_parameter_resolver(self) -> None:
        params = technical_parameters.get_technical_analysis_parameters(
            ma_windows="7,3,7",
            volume_ma_windows="2",
            volume_ratio_threshold=2.25,
            persisted_settings=None,
        )

        self.assertEqual(params.ma_windows, (3, 7))
        self.assertEqual(params.volume_ma_windows, (2,))
        self.assertEqual(params.ma_windows_text, "3,7")
        self.assertEqual(params.volume_ma_windows_text, "2")
        self.assertEqual(params.volume_ratio_threshold, 2.25)

    def test_invalid_window_override_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            technical_parameters.get_technical_analysis_parameters(
                ma_windows="5,bad",
                persisted_settings=None,
            )

    def test_indicator_calculation_uses_configured_windows(self) -> None:
        params = technical_parameters.get_technical_analysis_parameters(
            ma_windows="3,7",
            volume_ma_windows="2",
            persisted_settings=None,
        )

        latest = calculate_indicator_points_from_ohlc_points(
            _points(30),
            parameters=params,
        )[-1]

        self.assertEqual(set(latest["ma"]), {"ma3", "ma7"})
        self.assertEqual(set(latest["volume_ma"]), {"volume_ma2"})
        self.assertIsNotNone(latest["ma"]["ma3"])
        self.assertIsNotNone(latest["volume_ma"]["volume_ma2"])

    def test_indicator_calculation_keeps_legacy_aliases_for_changed_periods(self) -> None:
        with patch.object(technical_parameters.settings, "technical_rsi_period", 10):
            params = technical_parameters.get_technical_analysis_parameters(persisted_settings=None)
            latest = calculate_indicator_points_from_ohlc_points(
                _points(30),
                parameters=params,
            )[-1]

        self.assertIn("rsi10", latest["rsi"])
        self.assertIn("rsi14", latest["rsi"])
        self.assertEqual(latest["rsi"]["rsi10"], latest["rsi"]["rsi14"])

    def test_legal_lunar_new_year_gap_does_not_clear_moving_averages(self) -> None:
        points = _points(5)
        trading_dates = [
            date(2026, 2, 9),
            date(2026, 2, 10),
            date(2026, 2, 11),
            date(2026, 2, 23),
            date(2026, 2, 24),
        ]
        for point, trade_date in zip(points, trading_dates):
            point["time"] = trade_date
        params = technical_parameters.get_technical_analysis_parameters(
            ma_windows="5",
            volume_ma_windows="5",
            persisted_settings=None,
        )

        latest = calculate_indicator_points_from_ohlc_points(
            points,
            parameters=params,
        )[-1]

        self.assertIsNotNone(latest["ma"]["ma5"])
        self.assertIsNotNone(latest["volume_ma"]["volume_ma5"])

    def test_missing_expected_trading_day_clears_moving_averages(self) -> None:
        points = _points(5)
        trading_dates = [
            date(2026, 3, 2),
            date(2026, 3, 3),
            date(2026, 3, 5),
            date(2026, 3, 6),
            date(2026, 3, 9),
        ]
        for point, trade_date in zip(points, trading_dates):
            point["time"] = trade_date
        params = technical_parameters.get_technical_analysis_parameters(
            ma_windows="5",
            volume_ma_windows="5",
            persisted_settings=None,
        )

        latest = calculate_indicator_points_from_ohlc_points(
            points,
            parameters=params,
        )[-1]

        self.assertIsNone(latest["ma"]["ma5"])
        self.assertIsNone(latest["volume_ma"]["volume_ma5"])

    def test_moving_average_gap_checks_are_precomputed_once_per_edge(self) -> None:
        points = _points(1_000)
        params = technical_parameters.get_technical_analysis_parameters(
            ma_windows="5,20,60",
            volume_ma_windows="5,20",
            persisted_settings=None,
        )

        with patch.object(
            indicator_service,
            "_has_unexpected_taiwan_gap",
            return_value=False,
        ) as gap_check:
            result = calculate_indicator_points_from_ohlc_points(
                points,
                parameters=params,
            )

        self.assertEqual(len(result), len(points))
        self.assertEqual(gap_check.call_count, len(points) - 1)
        self.assertIsNotNone(result[-1]["ma"]["ma60"])
        self.assertIsNotNone(result[-1]["volume_ma"]["volume_ma20"])

    def test_persisted_settings_override_backend_defaults(self) -> None:
        params = technical_parameters.get_technical_analysis_parameters(
            persisted_settings={
                "ma_windows": [4, 8, 16],
                "volume_ma_windows": [3, 9],
                "rsi_period": 10,
                "volume_ratio_threshold": 1.8,
            },
        )

        self.assertEqual(params.ma_windows, (4, 8, 16))
        self.assertEqual(params.volume_ma_windows, (3, 9))
        self.assertEqual(params.rsi_period, 10)
        self.assertEqual(params.volume_ratio_threshold, 1.8)

    def test_technical_settings_response_exposes_effective_defaults(self) -> None:
        with settings_db_session() as db:
            response = get_technical_analysis_settings(db=db)
        payload = response.model_dump()

        self.assertEqual(payload["kind"], "technical_analysis_settings")
        self.assertEqual(payload["version"], "technical_analysis_settings.v1")
        self.assertEqual(payload["source"], "backend_config")
        self.assertEqual(payload["windows"]["ma"], [5, 20, 60])
        self.assertEqual(payload["windows"]["volume_ma"], [5, 20])
        self.assertEqual(payload["query_defaults"]["ma_windows"], "5,20,60")
        self.assertEqual(payload["query_defaults"]["volume_ma_windows"], "5,20")
        self.assertEqual(payload["periods"]["macd"], {"fast": 12, "slow": 26, "signal": 9})
        self.assertEqual(payload["periods"]["pvo"], {"fast": 12, "slow": 26, "signal": 9})
        self.assertEqual(payload["periods"]["bollinger"], {"period": 20, "std_dev": 2.0})
        self.assertEqual(payload["indicator_keys"]["ma_medium"], "ma20")
        self.assertEqual(payload["indicator_keys"]["kd_j"], "j9")
        self.assertEqual(payload["thresholds"]["breakout_volume_ratio"], 1.2)

    def test_technical_settings_endpoint_uses_service_schema(self) -> None:
        with settings_db_session() as db:
            response = get_technical_analysis_settings_endpoint(db=db)

        self.assertEqual(response.kind, "technical_analysis_settings")
        self.assertEqual(response.thresholds.volume_ratio, 1.5)

    def test_technical_settings_endpoint_reports_invalid_backend_config(self) -> None:
        with settings_db_session() as db:
            with patch.object(technical_parameters.settings, "technical_macd_fast_period", 30):
                with self.assertRaises(HTTPException) as raised:
                    get_technical_analysis_settings_endpoint(db=db)

        self.assertEqual(getattr(raised.exception, "status_code", None), 500)

    def test_update_technical_settings_persists_database_override(self) -> None:
        with settings_db_session() as db:
            payload = _write_payload_from_defaults(db)
            payload.windows.ma = [4, 8, 16]
            payload.windows.volume_ma = [3, 9]
            payload.periods.rsi = 10
            payload.periods.pvo.fast = 5
            payload.periods.pvo.slow = 10
            payload.periods.pvo.signal = 4
            payload.thresholds.volume_ratio = 1.8
            payload.thresholds.breakout_volume_ratio = 1.3

            response = update_technical_analysis_settings(db=db, payload=payload)

            row = db.query(AppSetting).filter(
                AppSetting.setting_key == TECHNICAL_ANALYSIS_SETTING_KEY
            ).one()
            stored_payload = json.loads(row.value_json)
            reread = get_technical_analysis_settings(db=db)

        self.assertEqual(response.source, "database")
        self.assertEqual(stored_payload["ma_windows"], [4, 8, 16])
        self.assertEqual(stored_payload["volume_ma_windows"], [3, 9])
        self.assertEqual(stored_payload["rsi_period"], 10)
        self.assertEqual(stored_payload["pvo_fast_period"], 5)
        self.assertEqual(stored_payload["pvo_slow_period"], 10)
        self.assertEqual(stored_payload["pvo_signal_period"], 4)
        self.assertEqual(stored_payload["volume_ratio_threshold"], 1.8)
        self.assertEqual(stored_payload["breakout_volume_ratio_threshold"], 1.3)
        self.assertEqual(reread.source, "database")
        self.assertEqual(reread.windows.ma, [4, 8, 16])
        self.assertEqual(reread.periods.rsi, 10)

    def test_update_technical_settings_endpoint_rejects_invalid_macd(self) -> None:
        with settings_db_session() as db:
            payload = _write_payload_from_defaults(db)
            payload.periods.macd.fast = 30

            with self.assertRaises(HTTPException) as raised:
                update_technical_analysis_settings_endpoint(payload=payload, db=db)

        self.assertEqual(getattr(raised.exception, "status_code", None), 400)

    def test_technical_settings_route_is_registered(self) -> None:
        matching_routes = [
            route
            for route in app.routes
            if getattr(route, "path", None) == "/api/settings/technical-analysis"
        ]
        registered_methods = set().union(
            *(getattr(route, "methods", set()) for route in matching_routes)
        )

        self.assertIn("GET", registered_methods)
        self.assertIn("PUT", registered_methods)


if __name__ == "__main__":
    unittest.main()
