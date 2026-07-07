from __future__ import annotations

from datetime import date
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    MarketDailyPrice,
    RawFetchResult,
    SourceRegistry,
    WatchlistGroup,
    WatchlistRadarOutcome,
    WatchlistRadarSnapshotItem,
    WatchlistRadarSnapshotRun,
)
from app.watchlists import radar_outcome_service


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return Session(engine)


class WatchlistRadarOutcomeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = make_session()
        self.addCleanup(self.db.close)

    def add_group(self, group_name: str = "Radar Test") -> WatchlistGroup:
        group = WatchlistGroup(group_name=group_name, is_active=True)
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

    def radar_payload(
        self,
        group_id: int,
        results: list[dict[str, object]],
        trade_date: str = "2026-07-06",
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
            "buckets": [
                {"key": "volume_up", "label": "Volume up", "description": "", "count": 1},
                {"key": "support_break", "label": "Support break", "description": "", "count": 1},
            ],
            "data_limitations": [],
            "results": results,
        }

    def radar_item(
        self,
        *,
        rank: int,
        stock_id: str,
        bucket: str,
        close: float,
        trade_date: str = "2026-07-06",
        volume: int = 1000,
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
            "volume": volume,
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

    def save_snapshot(
        self,
        group_id: int,
        results: list[dict[str, object]],
        trade_date: str = "2026-07-06",
    ) -> dict[str, object]:
        return radar_outcome_service.save_watchlist_radar_snapshot(
            db=self.db,
            radar=self.radar_payload(group_id, results, trade_date=trade_date),
            request={
                "group_id": group_id,
                "mode": "action",
                "max_results": 30,
                "calculation_limit": 100,
            },
        )

    def test_save_snapshot_is_idempotent_for_same_scope(self) -> None:
        group = self.add_group()
        item = self.radar_item(rank=1, stock_id="2330", bucket="volume_up", close=100)

        first = self.save_snapshot(group.id, [item])
        second = self.save_snapshot(group.id, [item])

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(self.db.query(WatchlistRadarSnapshotRun).count(), 1)
        self.assertEqual(self.db.query(WatchlistRadarSnapshotItem).count(), 1)

    def test_evaluate_snapshot_scores_bucket_aware_hits(self) -> None:
        group = self.add_group()
        source_id, raw_result_id = self.add_source()
        self.save_snapshot(
            group.id,
            [
                self.radar_item(rank=1, stock_id="2330", bucket="volume_up", close=100),
                self.radar_item(rank=2, stock_id="6257", bucket="support_break", close=50),
            ],
        )
        self.add_daily_bar(
            source_id=source_id,
            raw_result_id=raw_result_id,
            stock_id="2330",
            trade_date=date(2026, 7, 7),
            open_price=101,
            high_price=105,
            low_price=99,
            close_price=103,
            trade_volume=2000,
        )
        self.add_daily_bar(
            source_id=source_id,
            raw_result_id=raw_result_id,
            stock_id="6257",
            trade_date=date(2026, 7, 7),
            open_price=49,
            high_price=50,
            low_price=47,
            close_price=48,
            trade_volume=2200,
        )

        summary = radar_outcome_service.evaluate_watchlist_radar_outcome(
            db=self.db,
            group_id=group.id,
            mode="action",
        )

        self.assertEqual(summary["status"], "evaluated")
        self.assertEqual(summary["total_count"], 2)
        self.assertEqual(summary["hit_count"], 2)
        self.assertEqual(summary["miss_count"], 0)
        self.assertEqual(self.db.query(WatchlistRadarOutcome).count(), 2)

    def test_evaluate_snapshot_keeps_missing_t_plus_one_pending(self) -> None:
        group = self.add_group()
        self.save_snapshot(
            group.id,
            [self.radar_item(rank=1, stock_id="9999", bucket="volume_up", close=100)],
        )

        summary = radar_outcome_service.evaluate_watchlist_radar_outcome(
            db=self.db,
            group_id=group.id,
            mode="action",
        )

        self.assertEqual(summary["status"], "pending")
        self.assertEqual(summary["total_count"], 1)
        self.assertEqual(summary["pending_count"], 1)
        self.assertEqual(summary["hit_count"], 0)

    def test_history_lists_multiple_snapshot_dates(self) -> None:
        group = self.add_group()
        self.save_snapshot(
            group.id,
            [self.radar_item(rank=1, stock_id="2330", bucket="volume_up", close=100)],
            trade_date="2026-07-06",
        )
        self.save_snapshot(
            group.id,
            [
                self.radar_item(
                    rank=1,
                    stock_id="2368",
                    bucket="support_break",
                    close=50,
                    trade_date="2026-07-07",
                )
            ],
            trade_date="2026-07-07",
        )

        history = radar_outcome_service.list_watchlist_radar_outcome_summaries(
            db=self.db,
            group_id=group.id,
            mode="action",
        )

        self.assertEqual([row["snapshot"]["snapshot_date"] for row in history], [
            date(2026, 7, 7),
            date(2026, 7, 6),
        ])
        self.assertEqual([row["status"] for row in history], ["not_evaluated", "not_evaluated"])

    def test_evaluate_can_target_non_latest_snapshot(self) -> None:
        group = self.add_group()
        source_id, raw_result_id = self.add_source()
        old_snapshot = self.save_snapshot(
            group.id,
            [self.radar_item(rank=1, stock_id="2330", bucket="volume_up", close=100)],
            trade_date="2026-07-06",
        )
        new_snapshot = self.save_snapshot(
            group.id,
            [
                self.radar_item(
                    rank=1,
                    stock_id="2368",
                    bucket="support_break",
                    close=50,
                    trade_date="2026-07-07",
                )
            ],
            trade_date="2026-07-07",
        )
        self.add_daily_bar(
            source_id=source_id,
            raw_result_id=raw_result_id,
            stock_id="2330",
            trade_date=date(2026, 7, 7),
            open_price=101,
            high_price=103,
            low_price=99,
            close_price=102,
            trade_volume=2000,
        )

        summary = radar_outcome_service.evaluate_watchlist_radar_outcome(
            db=self.db,
            group_id=group.id,
            mode="action",
            snapshot_run_id=old_snapshot["id"],
        )

        self.assertEqual(summary["snapshot"]["id"], old_snapshot["id"])
        self.assertEqual(summary["hit_count"], 1)
        latest = radar_outcome_service.get_latest_watchlist_radar_outcome_summary(
            db=self.db,
            group_id=group.id,
            mode="action",
        )
        self.assertEqual(latest["snapshot"]["id"], new_snapshot["id"])
        self.assertEqual(latest["status"], "not_evaluated")


if __name__ == "__main__":
    unittest.main()
