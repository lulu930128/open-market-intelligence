from __future__ import annotations

from datetime import datetime
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, TaiwanIndexContractSnapshot
from app.jobs.taiwan_index_contract_scheduler import (
    add_taiwan_index_contract_snapshot_jobs,
)
from app.market.index_contract_snapshot import (
    TAIWAN_INDEX_CONTRACT_SLOTS,
    capture_taiwan_index_contract_snapshot,
    get_taiwan_index_contract_replay,
)
from app.market.trading_calendar import TAIWAN_TZ


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return Session(engine)


class TaiwanIndexContractSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = make_session()

    def tearDown(self) -> None:
        self.db.close()

    @staticmethod
    def _intraday(_index_id: str) -> dict:
        return {
            "source": "twse_index_5s",
            "previous_close": 43_000.0,
            "points": [
                {
                    "time": "2026-07-27T13:30:00+08:00",
                    "price": 43_634.19,
                    "open": 43_100.0,
                    "high": 43_686.15,
                    "low": 43_050.0,
                }
            ],
        }

    @staticmethod
    def _summary(_db: Session, _force_refresh: bool) -> dict:
        return {
            "indices": [
                {
                    "index_id": "TAIEX",
                    "time": "2026-07-27",
                    "as_of": "2026-07-27T13:30:05+08:00",
                    "close": 43_634.19,
                    "high": 43_686.15,
                    "source": (
                        "yahoo_finance_chart+twse_index_5s_snapshot"
                    ),
                }
            ]
        }

    def test_capture_is_idempotent_and_replay_is_read_only(self) -> None:
        now = datetime(2026, 7, 27, 13, 34, tzinfo=TAIWAN_TZ)

        first = capture_taiwan_index_contract_snapshot(
            self.db,
            index_id="TAIEX",
            capture_slot="13:34",
            now=now,
            intraday_reader=self._intraday,
            summary_reader=self._summary,
        )
        repeated = capture_taiwan_index_contract_snapshot(
            self.db,
            index_id="TAIEX",
            capture_slot="13:34",
            now=now,
            intraday_reader=self._intraday,
            summary_reader=self._summary,
        )

        before_replay = self.db.query(TaiwanIndexContractSnapshot).count()
        replay = get_taiwan_index_contract_replay(
            self.db,
            index_id="TAIEX",
            trade_date=now.date(),
        )
        after_replay = self.db.query(TaiwanIndexContractSnapshot).count()

        self.assertEqual(first["capture_status"], "captured")
        self.assertEqual(repeated["capture_status"], "captured")
        self.assertEqual(before_replay, 1)
        self.assertEqual(after_replay, before_replay)
        self.assertEqual(
            replay["required_slots"],
            list(TAIWAN_INDEX_CONTRACT_SLOTS),
        )
        self.assertEqual(replay["captured_count"], 1)
        self.assertFalse(replay["complete"])
        self.assertFalse(replay["read_path_side_effects"])
        snapshot = next(
            item
            for item in replay["snapshots"]
            if item["capture_slot"] == "13:34"
        )
        self.assertEqual(snapshot["status"], "captured")
        self.assertEqual(
            snapshot["selected_candidate"],
            "official_close",
        )
        self.assertEqual(
            snapshot["official_close_status"],
            "confirmed",
        )
        self.assertNotEqual(
            snapshot["payload"]["quote"]["official_close_price"],
            snapshot["payload"]["quote"]["high_price"],
        )

    def test_scheduler_registers_every_index_acceptance_slot(self) -> None:
        class FakeScheduler:
            def __init__(self) -> None:
                self.jobs: list[dict] = []

            def add_job(self, function, **kwargs) -> None:
                self.jobs.append({"function": function, **kwargs})

        scheduler = FakeScheduler()

        enabled = add_taiwan_index_contract_snapshot_jobs(scheduler)

        self.assertTrue(enabled)
        self.assertEqual(
            len(scheduler.jobs),
            len(TAIWAN_INDEX_CONTRACT_SLOTS),
        )
        self.assertEqual(
            [job["kwargs"]["capture_slot"] for job in scheduler.jobs],
            list(TAIWAN_INDEX_CONTRACT_SLOTS),
        )
        self.assertTrue(
            all(job["max_instances"] == 1 for job in scheduler.jobs)
        )

    def test_replay_rejects_unknown_index(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported Taiwan index"):
            get_taiwan_index_contract_replay(
                self.db,
                index_id="DJI",
            )


if __name__ == "__main__":
    unittest.main()
