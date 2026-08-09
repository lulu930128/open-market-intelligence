from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import unittest
import uuid

from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.db.migrations import create_alembic_config
from app.market.cross_market.relation_store import build_relation_registry_read


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


@contextmanager
def migration_directory():
    root = Path(__file__).resolve().parents[2] / ".tmp" / "cross_market_migration"
    root.mkdir(parents=True, exist_ok=True)
    directory = root / uuid.uuid4().hex
    directory.mkdir()
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


class CrossMarketRelationMigrationTests(unittest.TestCase):
    def test_upgrade_seeds_verified_adr_relations_and_downgrade_is_scoped(self) -> None:
        with migration_directory() as directory:
            database_url = sqlite_url(directory / "cross-market.db")
            config = create_alembic_config(database_url)

            command.upgrade(config, "20260809_0053")

            engine = create_engine(database_url)
            try:
                inspector = inspect(engine)
                self.assertTrue(inspector.has_table("cross_market_relation"))
                self.assertTrue(
                    inspector.has_table("cross_market_relation_evidence")
                )
                self.assertTrue(
                    inspector.has_table("cross_market_signal_snapshot")
                )
                relation_unique_constraints = {
                    item["name"]
                    for item in inspector.get_unique_constraints(
                        "cross_market_relation"
                    )
                }
                with engine.connect() as connection:
                    relations = connection.execute(
                        text(
                            """
                            SELECT
                                target_provider_symbol,
                                source_provider_symbol,
                                relation_type,
                                relation_subtype,
                                bucket,
                                base_weight,
                                ratio_numerator,
                                ratio_denominator,
                                confidence_tier,
                                review_status,
                                is_active,
                                valid_from,
                                created_by,
                                reviewed_by,
                                reviewed_at
                            FROM cross_market_relation
                            ORDER BY target_provider_symbol
                            """
                        )
                    ).mappings().all()
                    evidence_count = connection.execute(
                        text(
                            "SELECT COUNT(*) "
                            "FROM cross_market_relation_evidence "
                            "WHERE is_primary = 1 AND review_status = 'approved'"
                        )
                    ).scalar_one()
            finally:
                engine.dispose()

            direct_relations = [
                row for row in relations if row["relation_type"] == "same_equity_dr"
            ]
            self.assertEqual(
                [
                    (
                        row["target_provider_symbol"],
                        row["source_provider_symbol"],
                        float(row["ratio_numerator"]),
                        float(row["ratio_denominator"]),
                    )
                    for row in direct_relations
                ],
                [
                    ("2303", "UMC", 1.0, 5.0),
                    ("2330", "TSM", 1.0, 5.0),
                    ("3711", "ASX", 1.0, 2.0),
                    ("8150", "IMOS", 1.0, 20.0),
                ],
            )
            self.assertTrue(
                all(
                    row["confidence_tier"] == "A"
                    and row["review_status"] == "approved"
                    and bool(row["is_active"])
                    and str(row["valid_from"]) == "2026-07-22"
                    and row["created_by"] == "migration:20260809_0052"
                    and row["reviewed_by"] == "migration:20260809_0052"
                    and row["reviewed_at"] is not None
                    for row in direct_relations
                )
            )
            proxy = next(
                row for row in relations if row["relation_type"] == "industry_peer"
            )
            self.assertEqual(proxy["target_provider_symbol"], "2408")
            self.assertEqual(proxy["source_provider_symbol"], "MU")
            self.assertEqual(proxy["relation_subtype"], "dram_memory_cycle_proxy")
            self.assertEqual(proxy["bucket"], "industry_peer")
            self.assertEqual(float(proxy["base_weight"]), 0.4)
            self.assertEqual(proxy["confidence_tier"], "C")
            self.assertIsNone(proxy["ratio_numerator"])
            self.assertIsNone(proxy["ratio_denominator"])
            self.assertEqual(evidence_count, 4)
            self.assertIn(
                "uq_cross_market_relation_identity_valid_from",
                relation_unique_constraints,
            )
            self.assertIn(
                "uq_cross_market_relation_identity_version",
                relation_unique_constraints,
            )

            command.downgrade(config, "20260804_0051")
            engine = create_engine(database_url)
            try:
                inspector = inspect(engine)
                self.assertFalse(inspector.has_table("cross_market_relation"))
                self.assertFalse(
                    inspector.has_table("cross_market_relation_evidence")
                )
                self.assertFalse(
                    inspector.has_table("cross_market_signal_snapshot")
                )
                self.assertTrue(inspector.has_table("dispatch_schedule_run"))
            finally:
                engine.dispose()

    def test_proxy_temporal_revalidation_is_forward_only_and_replay_safe(self) -> None:
        with migration_directory() as directory:
            database_url = sqlite_url(directory / "cross-market-revalidated.db")
            config = create_alembic_config(database_url)
            command.upgrade(config, "20260809_0056")

            engine = create_engine(database_url)
            try:
                with engine.connect() as connection:
                    relations = connection.execute(
                        text(
                            """
                            SELECT id, version, valid_from, verified_at,
                                   review_status, is_active, created_by,
                                   reviewed_by, reviewed_at, change_reason
                            FROM cross_market_relation
                            WHERE source_canonical_symbol = 'US:MU'
                              AND target_canonical_symbol = 'TW:2408'
                              AND relation_type = 'industry_peer'
                            ORDER BY version
                            """
                        )
                    ).mappings().all()
                    evidence = connection.execute(
                        text(
                            """
                            SELECT relation_id, verified_at, content_hash,
                                   review_status, created_by, reviewed_by
                            FROM cross_market_relation_evidence
                            WHERE relation_id IN (:old_id, :new_id)
                            ORDER BY relation_id, content_hash
                            """
                        ),
                        {
                            "old_id": int(relations[0]["id"]),
                            "new_id": int(relations[1]["id"]),
                        },
                    ).mappings().all()

                self.assertEqual([int(row["version"]) for row in relations], [1, 2])
                old, new = relations
                self.assertEqual(old["review_status"], "revoked")
                self.assertFalse(bool(old["is_active"]))
                self.assertEqual(old["created_by"], "migration:20260809_0052")
                self.assertEqual(old["reviewed_by"], "migration:20260809_0056")
                self.assertIn("future verification timestamp", old["change_reason"])

                self.assertEqual(new["review_status"], "approved")
                self.assertTrue(bool(new["is_active"]))
                self.assertEqual(new["created_by"], "migration:20260809_0056")
                self.assertEqual(new["reviewed_by"], "migration:20260809_0056")
                verified_at = datetime.fromisoformat(str(new["verified_at"]))
                if verified_at.tzinfo is None:
                    verified_at = verified_at.replace(tzinfo=timezone.utc)
                self.assertEqual(
                    str(new["valid_from"]),
                    (verified_at.date() + timedelta(days=1)).isoformat(),
                )
                self.assertEqual(len(evidence), 4)
                self.assertEqual(
                    {row["created_by"] for row in evidence},
                    {"migration:20260809_0052", "migration:20260809_0056"},
                )
                self.assertTrue(
                    all(row["review_status"] == "approved" for row in evidence)
                )

                session = sessionmaker(bind=engine)()
                try:
                    unavailable = build_relation_registry_read(
                        session,
                        "2408",
                        as_of=verified_at.date(),
                        generated_at=verified_at + timedelta(minutes=1),
                    )
                    available = build_relation_registry_read(
                        session,
                        "2408",
                        as_of=verified_at.date() + timedelta(days=1),
                        generated_at=verified_at + timedelta(days=1, minutes=1),
                    )
                finally:
                    session.close()
                self.assertEqual(unavailable.status, "not_applicable")
                self.assertEqual(unavailable.relation_count, 0)
                self.assertEqual(available.status, "ready")
                self.assertEqual(available.relation_count, 1)
                self.assertEqual(available.relations[0].relation_version, 2)

                command.downgrade(config, "20260809_0055")
                command.upgrade(config, "20260809_0056")
                with engine.connect() as connection:
                    count = connection.execute(
                        text(
                            """
                            SELECT COUNT(*)
                            FROM cross_market_relation
                            WHERE source_canonical_symbol = 'US:MU'
                              AND target_canonical_symbol = 'TW:2408'
                              AND relation_type = 'industry_peer'
                            """
                        )
                    ).scalar_one()
                self.assertEqual(count, 2)
            finally:
                engine.dispose()

    def test_proxy_temporal_revalidation_fails_closed_on_seed_drift(self) -> None:
        with migration_directory() as directory:
            database_url = sqlite_url(directory / "cross-market-conflict.db")
            config = create_alembic_config(database_url)
            command.upgrade(config, "20260809_0055")

            engine = create_engine(database_url)
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            """
                            UPDATE cross_market_relation
                            SET base_weight = 0.5
                            WHERE source_canonical_symbol = 'US:MU'
                              AND target_canonical_symbol = 'TW:2408'
                              AND relation_type = 'industry_peer'
                            """
                        )
                    )
                with self.assertRaisesRegex(
                    RuntimeError,
                    "relation seed fingerprint mismatch",
                ):
                    command.upgrade(config, "20260809_0056")
                with engine.connect() as connection:
                    current_revision = connection.execute(
                        text("SELECT version_num FROM alembic_version")
                    ).scalar_one()
                self.assertEqual(current_revision, "20260809_0055")
            finally:
                engine.dispose()

    def test_proxy_temporal_revalidation_can_seed_an_absent_proxy(self) -> None:
        with migration_directory() as directory:
            database_url = sqlite_url(directory / "cross-market-absent.db")
            config = create_alembic_config(database_url)
            command.upgrade(config, "20260809_0055")

            engine = create_engine(database_url)
            try:
                with engine.begin() as connection:
                    relation_id = connection.execute(
                        text(
                            """
                            SELECT id
                            FROM cross_market_relation
                            WHERE source_canonical_symbol = 'US:MU'
                              AND target_canonical_symbol = 'TW:2408'
                              AND relation_type = 'industry_peer'
                            """
                        )
                    ).scalar_one()
                    connection.execute(
                        text(
                            "DELETE FROM cross_market_relation_evidence "
                            "WHERE relation_id = :relation_id"
                        ),
                        {"relation_id": relation_id},
                    )
                    connection.execute(
                        text(
                            "DELETE FROM cross_market_relation "
                            "WHERE id = :relation_id"
                        ),
                        {"relation_id": relation_id},
                    )

                command.upgrade(config, "20260809_0056")
                with engine.connect() as connection:
                    relation = connection.execute(
                        text(
                            """
                            SELECT id, version, valid_from, verified_at,
                                   review_status, is_active, created_by
                            FROM cross_market_relation
                            WHERE source_canonical_symbol = 'US:MU'
                              AND target_canonical_symbol = 'TW:2408'
                              AND relation_type = 'industry_peer'
                            """
                        )
                    ).mappings().one()
                    evidence_count = connection.execute(
                        text(
                            "SELECT COUNT(*) "
                            "FROM cross_market_relation_evidence "
                            "WHERE relation_id = :relation_id"
                        ),
                        {"relation_id": int(relation["id"])},
                    ).scalar_one()
                verified_at = datetime.fromisoformat(str(relation["verified_at"]))
                self.assertEqual(int(relation["version"]), 1)
                self.assertEqual(relation["review_status"], "approved")
                self.assertTrue(bool(relation["is_active"]))
                self.assertEqual(relation["created_by"], "migration:20260809_0056")
                self.assertEqual(
                    str(relation["valid_from"]),
                    (verified_at.date() + timedelta(days=1)).isoformat(),
                )
                self.assertEqual(evidence_count, 2)
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
