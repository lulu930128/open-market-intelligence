from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import shutil
import unittest
import uuid

from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.db.migrations import create_alembic_config
from app.market.cross_market.schemas import CrossMarketTargetContextRead
from app.market.cross_market.snapshot_store import (
    load_latest_cross_market_context_snapshots,
    materialize_cross_market_context_snapshot,
)
from backend.tests.test_cross_market_context import (
    ADR_TRADE_DATE,
    DECISION_AT,
    MATERIALIZED_AT,
    add_adr_close,
    add_fx,
    add_tw_daily,
)


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


@contextmanager
def migration_directory():
    root = Path(__file__).resolve().parents[2] / ".tmp" / "cross_market_point_in_time"
    directory = root / uuid.uuid4().hex
    directory.mkdir(parents=True, exist_ok=False)
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


class CrossMarketPointInTimeTests(unittest.TestCase):
    def test_snapshot_lifecycle_migration_round_trips_legacy_payload(self) -> None:
        with migration_directory() as directory:
            database_url = sqlite_url(directory / "snapshot-lifecycle.db")
            config = create_alembic_config(database_url)
            command.upgrade(config, "head")

            engine = create_engine(database_url)
            try:
                with Session(engine) as db:
                    add_adr_close(db)
                    add_tw_daily(db)
                    add_fx(db)
                    snapshot = materialize_cross_market_context_snapshot(
                        db,
                        "2330",
                        decision_at=DECISION_AT,
                        expected_adr_trade_date=ADR_TRADE_DATE,
                        materialized_by="migration-roundtrip",
                        materialized_at=MATERIALIZED_AT,
                    )
                    snapshot_id = snapshot.snapshot_id
                    db.commit()
            finally:
                engine.dispose()

            command.downgrade(config, "20260809_0056")
            legacy_engine = create_engine(database_url)
            try:
                legacy_columns = {
                    item["name"]
                    for item in inspect(legacy_engine).get_columns(
                        "cross_market_signal_snapshot"
                    )
                }
                with legacy_engine.connect() as connection:
                    legacy_row = connection.execute(
                        text(
                            "SELECT payload_hash, payload_json "
                            "FROM cross_market_signal_snapshot"
                        )
                    ).mappings().one()
                legacy_payload = json.loads(legacy_row["payload_json"])
                self.assertNotIn("projection_source", legacy_columns)
                self.assertNotIn("projection_source", legacy_payload)
                self.assertIn(
                    "latest_local_cache_projection_not_materialized_snapshot",
                    legacy_payload["limitations"],
                )
                self.assertEqual(
                    legacy_row["payload_hash"],
                    hashlib.sha256(
                        legacy_row["payload_json"].encode("utf-8")
                    ).hexdigest(),
                )
            finally:
                legacy_engine.dispose()

            command.upgrade(config, "head")
            migrated_engine = create_engine(database_url)
            try:
                inspector = inspect(migrated_engine)
                migrated_columns = {
                    item["name"]
                    for item in inspector.get_columns(
                        "cross_market_signal_snapshot"
                    )
                }
                check_names = {
                    item["name"]
                    for item in inspector.get_check_constraints(
                        "cross_market_signal_snapshot"
                    )
                }
                index_names = {
                    item["name"]
                    for item in inspector.get_indexes(
                        "cross_market_signal_snapshot"
                    )
                }
                self.assertTrue(
                    {
                        "projection_source",
                        "source_cutoff_at",
                        "materialized_at",
                    }.issubset(migrated_columns)
                )
                self.assertIn(
                    "ck_cross_market_signal_snapshot_projection_source",
                    check_names,
                )
                self.assertIn(
                    "ix_cross_market_signal_snapshot_source_cutoff_at",
                    index_names,
                )
                with Session(migrated_engine) as db:
                    loaded = load_latest_cross_market_context_snapshots(
                        db,
                        ["2330"],
                        as_of_at=MATERIALIZED_AT,
                    )
                    context = loaded["2330"]
                    self.assertIsInstance(context, CrossMarketTargetContextRead)
                    self.assertEqual(context.snapshot_id, snapshot_id)
                    self.assertEqual(
                        context.projection_source,
                        "materialized_snapshot",
                    )
                    self.assertEqual(
                        context.payload_hash,
                        context.evidence_passport["payload_hash"],
                    )
                    self.assertNotIn(
                        "latest_local_cache_projection_not_materialized_snapshot",
                        context.limitations,
                    )
            finally:
                migrated_engine.dispose()

    def test_snapshot_lifecycle_migration_rejects_corrupt_legacy_payload(self) -> None:
        with migration_directory() as directory:
            database_url = sqlite_url(directory / "corrupt-legacy.db")
            config = create_alembic_config(database_url)
            command.upgrade(config, "head")
            command.downgrade(config, "20260809_0056")
            engine = create_engine(database_url)
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            """
                            INSERT INTO cross_market_signal_snapshot (
                                id, snapshot_id, schema_version,
                                methodology_version, relation_snapshot_version,
                                target_market, target_canonical_symbol,
                                target_provider_symbol, decision_at, as_of,
                                status, decision_usable, coverage_ratio,
                                payload_hash, payload_json, materialized_by,
                                created_at
                            ) VALUES (
                                1, 'cmctx:corrupt', 'cross_market.context.v1',
                                'cross_market.relation_context.v2',
                                'relation_registry:none', 'TW', 'TW:2330',
                                '2330', :decision_at, '2026-08-07',
                                'partial', 0, 0,
                                :payload_hash, '{}', 'corrupt-test',
                                :created_at
                            )
                            """
                        ),
                        {
                            "decision_at": DECISION_AT.isoformat(),
                            "created_at": MATERIALIZED_AT.isoformat(),
                            "payload_hash": "0" * 64,
                        },
                    )
            finally:
                engine.dispose()

            with self.assertRaisesRegex(RuntimeError, "payload identity is invalid"):
                command.upgrade(config, "head")


if __name__ == "__main__":
    unittest.main()
