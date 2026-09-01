from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, StockMaster
from app.market import intraday


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return Session(engine)


def add_stock(db: Session, stock_id: str = "2330") -> None:
    db.add(
        StockMaster(
            stock_id=stock_id,
            stock_name="TSMC",
            market="TWSE",
            instrument_type="stock",
        )
    )
    db.commit()


def point(
    hour: int,
    minute: int,
    close: float,
    volume: int = 1000,
    *,
    days_ago: int = 0,
) -> dict:
    point_time = (datetime.now(intraday.TAIPEI_TZ) - timedelta(days=days_ago)).replace(
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0,
    )
    return {
        "time": point_time,
        "price": close,
        "volume": volume,
        "open": close - 1,
        "high": close + 2,
        "low": close - 2,
        "close": close,
    }


def bar_series(
    points: list[dict],
    *,
    interval: str = "1m",
) -> SimpleNamespace:
    derived = interval != "1m"
    bars = tuple(
        SimpleNamespace(
            start_at=item["time"],
            end_at=item["time"] + timedelta(
                hours=(4 if interval == "4h" else 1 if interval == "1h" else 0),
                minutes=(0 if interval in {"1h", "4h"} else int(interval[:-1])),
            ),
            open_price=item["open"],
            high_price=item["high"],
            low_price=item["low"],
            close_price=item["close"],
            volume=SimpleNamespace(value=item["volume"]),
            turnover_value=None,
            finalization=SimpleNamespace(value="final"),
            lineage=SimpleNamespace(
                provider=("omi_taiwan_bar_service" if derived else "kgi_superpy"),
                source=("tw.bar.aggregate" if derived else "kgi_superpy_minute_kbars"),
            ),
        )
        for item in points
    )
    return SimpleNamespace(
        bars=bars,
        derived=derived,
        base_interval="1m",
        aggregation_version="tw.bar.aggregate.v1" if derived else None,
        history=SimpleNamespace(
            history_status=SimpleNamespace(value="ready"),
            requested_coverage_satisfied=True,
            requested_session_count=max(
                len({item["time"].date() for item in points}), 1
            ),
            covered_session_count=max(
                len({item["time"].date() for item in points}), 1
            ),
        ),
        identity=SimpleNamespace(
            series_revision="r" * 64,
            series_fingerprint="f" * 64,
            lineage_digest="l" * 64,
            state_digest="s" * 64,
        ),
        session_resolution=(),
        limitations=(),
    )


class MarketIntradayHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = make_session()
        add_stock(self.db)

    def tearDown(self) -> None:
        self.db.close()

    def _read(
        self,
        points: list[dict],
        *,
        interval: str = "1m",
        **metadata,
    ) -> dict:
        del metadata
        with (
            patch.object(intraday, "TaiwanBarService") as service,
            patch.object(
                self.db,
                "commit",
                side_effect=AssertionError("history GET must not commit"),
            ),
        ):
            service.return_value.read_bars.return_value = bar_series(
                points,
                interval=interval,
            )
            return intraday.get_market_intraday_history(
                self.db,
                stock_id="2330",
                interval=interval,
                range_value="5d",
                refresh=True,
            )

    def test_history_get_projects_cache_without_refresh_or_mutation(self) -> None:
        result = self._read([point(9, 0, 101), point(9, 1, 102)])

        self.assertEqual(result["point_count"], 2)
        self.assertEqual(result["points"][-1]["close"], 102)
        self.assertEqual(result["refreshed_count"], 0)
        self.assertEqual(result["cache_status"], "persisted_hit")
        self.assertEqual(result["read_policy"], "cache_only")
        self.assertEqual(result["acquisition_status"], "not_attempted")

    def test_four_hour_projection_preserves_derived_lineage_metadata(self) -> None:
        result = self._read(
            [point(9, 0, 105, 3000), point(13, 0, 103, 3000)],
            interval="4h",
        )

        self.assertEqual(result["interval"], "4h")
        self.assertEqual(result["source_interval"], "1m")
        self.assertEqual(result["calculation_versions"], ["tw.bar.aggregate.v1"])
        self.assertEqual(result["component_raw_result_ids"], [])

    def test_one_minute_cache_keeps_recent_trading_days_across_calendar_gap(self) -> None:
        result = self._read([point(9, 0, 101, days_ago=6)])

        self.assertEqual(result["point_count"], 1)
        self.assertEqual(result["points"][0]["close"], 101)

    def test_history_keeps_multi_day_points_but_scopes_session_metrics(self) -> None:
        result = self._read(
            [
                point(12, 0, 100, 10_000, days_ago=1),
                point(13, 0, 100, 20_000, days_ago=1),
                point(9, 0, 200, 1_000),
                point(9, 1, 200, 2_000),
            ]
        )

        expected_trade_date = datetime.now(intraday.TAIPEI_TZ).date().isoformat()
        self.assertEqual(result["point_count"], 4)
        self.assertEqual(result["window_trade_date_count"], 2)
        self.assertEqual(result["window_volume_sum_shares"], 33_000)
        self.assertEqual(result["bar_volume_trade_date"], expected_trade_date)
        self.assertEqual(result["bar_volume_sum_shares"], 3_000)
        self.assertIsNone(result["cumulative_volume_shares"])
        self.assertEqual(result["cumulative_volume_status"], "partial_coverage")
        self.assertAlmostEqual(result["approx_vwap"], 200.0)

    def test_five_minute_history_uses_resolved_provider_not_local_legacy_overlay(self) -> None:
        result = self._read(
            [point(13, 15, 103, 6000)],
            interval="5m",
        )

        self.assertEqual(result["source"], "tw.bar.aggregate")
        self.assertEqual(result["provider"], "omi_taiwan_bar_service")
        self.assertEqual(result["points"][-1]["close"], 103)
        self.assertEqual(result["points"][-1]["volume"], 6000)

    def test_repeated_cache_reads_never_report_refresh_updates(self) -> None:
        points = [point(9, 0, 101, 1000)]
        with patch.object(intraday, "TaiwanBarService") as service:
            service.return_value.read_bars.return_value = bar_series(points)
            first = intraday.get_market_intraday_history(
                self.db,
                stock_id="2330",
                interval="1m",
                range_value="1d",
                refresh=True,
            )
            second = intraday.get_market_intraday_history(
                self.db,
                stock_id="2330",
                interval="1m",
                range_value="1d",
                refresh=True,
            )

        self.assertEqual(service.return_value.read_bars.call_count, 2)
        self.assertEqual(first["refreshed_count"], 0)
        self.assertEqual(second["refreshed_count"], 0)


if __name__ == "__main__":
    unittest.main()
