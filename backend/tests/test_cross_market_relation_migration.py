from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import shutil
import unittest
import uuid

from alembic import command
from sqlalchemy import create_engine, inspect, text

from app.db.migrations import create_alembic_config


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

            command.downgrade(config, "20260731_0049")
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
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
