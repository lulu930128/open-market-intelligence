from __future__ import annotations

from datetime import date, datetime
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    MarketDailyPrice,
    MarketIntradayBar,
    RawFetchResult,
    SourceRegistry,
    WatchlistGroup,
    WatchlistRadarOutcome,
    WatchlistRadarSnapshotRun,
)
from app.watchlists import radar_automation, radar_outcome_service


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return Session(engine)


class WatchlistRadarAutomationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = make_session()
        self.addCleanup(self.db.close)

    def add_group(
        self,
        group_name: str = "Radar Test",
        *,
        parent_id: int | None = None,
        is_active: bool = True,
    ) -> WatchlistGroup:
        group = WatchlistGroup(
            parent_id=parent_id,
            group_name=group_name,
            is_active=is_active,
        )
        self.db.add(group)
        self.db.commit()
        return group

    def add_source(self) -> tuple[int, int]:
        source = SourceRegistry(
            source_name="test-market-daily-price",
            source_type="test",
            category="market_daily_price",
        )
        self.db.add(source)
        self.db.flush()
        raw = RawFetchResult(
            source_id=source.id,
            method="GET",
            url="https://example.test/daily",
            status_code=200,
            content_hash="test-daily",
            raw_text="{}",
        )
        self.db.add(raw)
        self.db.flush()
        return source.id, raw.id

    def add_daily_bar(
        self,
        *,
        source_id: int,
        raw_result_id: int,
        stock_id: str,
        trade_date: date,
        close_price: float,
        open_price: float | None = None,
        high_price: float | None = None,
        low_price: float | None = None,
        trade_volume: int | None = None,
    ) -> None:
        self.db.add(
            MarketDailyPrice(
                source_id=source_id,
                raw_result_id=raw_result_id,
                trade_date=trade_date,
                stock_id=stock_id,
                stock_name=stock_id,
                trade_volume=trade_volume,
                open_price=open_price,
                high_price=high_price,
                low_price=low_price,
                close_price=close_price,
            )
        )
        self.db.commit()

    def radar_item(
        self,
        *,
        rank: int,
        stock_id: str,
        bucket: str,
        close: float,
        trade_date: str,
    ) -> dict[str, object]:
        return {
            "rank": rank,
            "source_rank": rank,
            "bucket": bucket,
            "bucket_label": bucket,
            "urgency": "high",
            "priority_score": 85.0,
            "technical_evidence_score": 70.0,
            "technical_score": 72.0,
            "technical_grade": "strong",
            "direction": "bullish",
            "stock_id": stock_id,
            "stock_name": stock_id,
            "trade_date": trade_date,
            "close": close,
            "volume": 1000,
            "change_pct": 1.5,
            "previous_close": close - 1,
            "signal_keys": [bucket],
            "matched_signal_keys": [bucket],
            "context_signals": [],
            "factor_scores": {},
            "price_levels": {},
            "action_label": "Watch",
            "reason": "Test radar item",
        }

    def radar_payload(
        self,
        *,
        group_id: int,
        trade_date: str,
        results: list[dict[str, object]],
    ) -> dict[str, object]:
        return {
            "group_id": group_id,
            "include_children": True,
            "mode": "action",
            "max_results": 30,
            "trade_date": trade_date,
            "target_trade_date": trade_date,
            "is_current": True,
            "current_stock_count": len(results),
            "stale_stock_count": 0,
            "requested_stock_count": len(results),
            "ranked_count": len(results),
            "matched_count": len(results),
            "radar_count": len(results),
            "no_data_count": 0,
            "error_count": 0,
            "buckets": [],
            "data_limitations": [],
            "results": results,
        }

    def save_snapshot(
        self,
        *,
        group_id: int,
        trade_date: str,
        results: list[dict[str, object]],
    ) -> dict[str, object]:
        return radar_outcome_service.save_watchlist_radar_snapshot(
            db=self.db,
            radar=self.radar_payload(
                group_id=group_id,
                trade_date=trade_date,
                results=results,
            ),
            request={
                "group_id": group_id,
                "mode": "action",
                "max_results": 30,
                "calculation_limit": 100,
            },
        )

    def test_automation_evaluates_previous_snapshot_and_saves_today(self) -> None:
        group = self.add_group()
        source_id, raw_result_id = self.add_source()
        self.save_snapshot(
            group_id=group.id,
            trade_date="2026-07-06",
            results=[
                self.radar_item(
                    rank=1,
                    stock_id="2330",
                    bucket="volume_up",
                    close=100,
                    trade_date="2026-07-06",
                )
            ],
        )
        self.add_daily_bar(
            source_id=source_id,
            raw_result_id=raw_result_id,
            stock_id="2330",
            trade_date=date(2026, 7, 7),
            open_price=101,
            high_price=104,
            low_price=99,
            close_price=102,
            trade_volume=2000,
        )
        today_radar = self.radar_payload(
            group_id=group.id,
            trade_date="2026-07-07",
            results=[
                self.radar_item(
                    rank=1,
                    stock_id="2368",
                    bucket="support_break",
                    close=50,
                    trade_date="2026-07-07",
                )
            ],
        )

        with patch.object(
            radar_automation.radar_service,
            "get_watchlist_group_radar",
            return_value=today_radar,
        ) as get_radar:
            result = radar_automation.run_watchlist_radar_automation(
                db=self.db,
                group_ids=[group.id],
                modes=["action"],
                evaluate_before_date=date(2026, 7, 7),
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["saved_count"], 1)
        self.assertEqual(result["evaluated_count"], 1)
        self.assertEqual(self.db.query(WatchlistRadarOutcome).count(), 1)
        self.assertEqual(self.db.query(WatchlistRadarSnapshotRun).count(), 2)
        get_radar.assert_called_once()

    def test_automation_defaults_to_all_active_groups(self) -> None:
        root = self.add_group("Root")
        child = self.add_group("Child", parent_id=root.id)
        self.add_group("Inactive", is_active=False)
        called_group_ids: list[int] = []

        def fake_radar(**kwargs):
            group_id = int(kwargs["group_id"])
            called_group_ids.append(group_id)
            return self.radar_payload(group_id=group_id, trade_date="2026-07-07", results=[])

        with patch.object(
            radar_automation.radar_service,
            "get_watchlist_group_radar",
            side_effect=fake_radar,
        ):
            result = radar_automation.run_watchlist_radar_automation(
                db=self.db,
                group_ids=None,
                modes="action",
                evaluate_before_date=date(2026, 7, 7),
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(called_group_ids, [root.id, child.id])
        self.assertEqual(result["group_ids"], [root.id, child.id])
        self.assertEqual(result["coverage"]["status"], "complete")

    def test_automation_rejects_stale_snapshot_date(self) -> None:
        group = self.add_group()
        stale_radar = self.radar_payload(
            group_id=group.id,
            trade_date="2026-07-06",
            results=[],
        )

        with patch.object(
            radar_automation.radar_service,
            "get_watchlist_group_radar",
            return_value=stale_radar,
        ):
            result = radar_automation.run_watchlist_radar_automation(
                db=self.db,
                group_ids=[group.id],
                evaluate_before_date=date(2026, 7, 7),
            )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["saved_count"], 0)
        self.assertEqual(result["invalid_count"], 1)
        self.assertEqual(result["coverage"]["missing_count"], 1)
        self.assertEqual(result["results"][0]["snapshot_status"], "stale")
        self.assertEqual(self.db.query(WatchlistRadarSnapshotRun).count(), 0)

    def test_automation_reports_existing_snapshot_without_false_save(self) -> None:
        group = self.add_group()
        radar = self.radar_payload(
            group_id=group.id,
            trade_date="2026-07-07",
            results=[],
        )
        self.save_snapshot(
            group_id=group.id,
            trade_date="2026-07-07",
            results=[],
        )

        with patch.object(
            radar_automation.radar_service,
            "get_watchlist_group_radar",
            return_value=radar,
        ):
            result = radar_automation.run_watchlist_radar_automation(
                db=self.db,
                group_ids=[group.id],
                evaluate_before_date=date(2026, 7, 7),
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["saved_count"], 0)
        self.assertEqual(result["existing_count"], 1)
        self.assertEqual(result["coverage"]["status"], "complete")
        self.assertEqual(result["results"][0]["snapshot_status"], "existing")
        self.assertEqual(self.db.query(WatchlistRadarSnapshotRun).count(), 1)

    def test_partial_outcome_rows_still_require_evaluation(self) -> None:
        group = self.add_group()
        snapshot = self.save_snapshot(
            group_id=group.id,
            trade_date="2026-07-06",
            results=[
                self.radar_item(
                    rank=1,
                    stock_id="2330",
                    bucket="volume_up",
                    close=100,
                    trade_date="2026-07-06",
                ),
                self.radar_item(
                    rank=2,
                    stock_id="2303",
                    bucket="volume_up",
                    close=50,
                    trade_date="2026-07-06",
                ),
            ],
        )
        radar_outcome_service.evaluate_watchlist_radar_outcome(
            db=self.db,
            group_id=group.id,
            mode="action",
            snapshot_run_id=int(snapshot["id"]),
        )
        outcome = self.db.query(WatchlistRadarOutcome).first()
        self.db.delete(outcome)
        self.db.commit()

        self.assertTrue(
            radar_automation._run_needs_evaluation(
                self.db,
                int(snapshot["id"]),
            )
        )

    def test_automation_fetches_current_intraday_before_outcome_evaluation(self) -> None:
        group = self.add_group()
        self.save_snapshot(
            group_id=group.id,
            trade_date="2026-07-06",
            results=[
                self.radar_item(
                    rank=1,
                    stock_id="2330",
                    bucket="volume_up",
                    close=100,
                    trade_date="2026-07-06",
                )
            ],
        )
        today_radar = self.radar_payload(
            group_id=group.id,
            trade_date="2026-07-07",
            results=[],
        )

        def fake_radar(**_: object):
            for bar_time, close_price in (
                (datetime(2026, 7, 7, 9, 0), 101.0),
                (datetime(2026, 7, 7, 13, 30), 103.0),
            ):
                self.db.add(
                    MarketIntradayBar(
                        provider="test",
                        stock_id="2330",
                        market="TWSE",
                        symbol="TWSE_2330.tw",
                        interval="1m",
                        bar_time=bar_time,
                        open_price=101.0,
                        high_price=max(103.0, close_price),
                        low_price=99.0,
                        close_price=close_price,
                        trade_volume=100,
                        source="test_intraday",
                    )
                )
            self.db.commit()
            return today_radar

        with patch.object(
            radar_automation.radar_service,
            "get_watchlist_group_radar",
            side_effect=fake_radar,
        ):
            result = radar_automation.run_watchlist_radar_automation(
                db=self.db,
                group_ids=[group.id],
                use_intraday=True,
                evaluate_before_date=date(2026, 7, 7),
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["evaluated_count"], 1)
        self.assertEqual(result["results"][0]["evaluated_snapshots"][0]["hit_count"], 1)
        outcome = self.db.query(WatchlistRadarOutcome).one()
        self.assertEqual(outcome.outcome_trade_date, date(2026, 7, 7))
        self.assertEqual(outcome.outcome_close_price, 103.0)

    def test_automation_reports_pending_outcomes_as_partial_success(self) -> None:
        group = self.add_group()
        self.save_snapshot(
            group_id=group.id,
            trade_date="2026-07-06",
            results=[
                self.radar_item(
                    rank=1,
                    stock_id="2330",
                    bucket="volume_up",
                    close=100,
                    trade_date="2026-07-06",
                )
            ],
        )
        today_radar = self.radar_payload(
            group_id=group.id,
            trade_date="2026-07-07",
            results=[],
        )

        with patch.object(
            radar_automation.radar_service,
            "get_watchlist_group_radar",
            return_value=today_radar,
        ):
            result = radar_automation.run_watchlist_radar_automation(
                db=self.db,
                group_ids=[group.id],
                evaluate_before_date=date(2026, 7, 7),
            )

        self.assertEqual(result["status"], "partial_success")
        self.assertEqual(result["coverage"]["pending_evaluation_count"], 1)
        self.assertFalse(result["coverage"]["reconciliation_complete"])


if __name__ == "__main__":
    unittest.main()
