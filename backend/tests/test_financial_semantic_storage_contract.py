from __future__ import annotations

import json
from pathlib import Path
import shutil
import unittest
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.migrations import create_alembic_config, get_database_revision
from app.db.models import (
    Base,
    RawFetchResult,
    SourceRegistry,
    TaiwanFinancialCorporateAction,
    TaiwanFinancialFiling,
    TaiwanFinancialNormalizedFact,
    TaiwanFinancialParseRun,
    TaiwanFinancialParseRunReview,
    TaiwanFinancialStatementFact,
)


class FinancialSemanticStorageContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        source = SourceRegistry(
            source_name="financial-semantic-test",
            source_type="official",
            category="financial",
            enabled=True,
            priority=100,
            auth_type="none",
            reliability_level="official",
        )
        self.db.add(source)
        self.db.flush()
        raw = RawFetchResult(
            source_id=source.id,
            fetched_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
            method="GET",
            content_hash="raw-2327-2026q1",
            parser_version="financial-semantic-test-v1",
        )
        self.db.add(raw)
        self.db.flush()
        self.source_id = source.id
        self.raw_result_id = raw.id

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _add_filing(self) -> TaiwanFinancialFiling:
        filing = TaiwanFinancialFiling(
            source_id=self.source_id,
            raw_result_id=self.raw_result_id,
            stock_id="2327",
            source_document_id="2327-2026Q1-consolidated",
            source_document_url="https://example.test/2327/2026Q1",
            content_hash="filing-2327-2026q1-v1",
            filing_kind="quarterly_report",
            fiscal_year=2026,
            fiscal_quarter=1,
            period_end=date(2026, 3, 31),
            announced_at=datetime(2026, 4, 15, tzinfo=timezone.utc),
            filed_at=datetime(2026, 4, 15, tzinfo=timezone.utc),
            provider_generated_at=None,
            fetched_at=datetime(2026, 7, 27, tzinfo=timezone.utc),
            known_at=datetime(2026, 4, 15, tzinfo=timezone.utc),
            parser_version="financial-semantic-test-v1",
        )
        self.db.add(filing)
        self.db.flush()
        return filing

    def _add_parse_run(
        self,
        filing: TaiwanFinancialFiling,
    ) -> TaiwanFinancialParseRun:
        parse_run = TaiwanFinancialParseRun(
            filing_id=filing.id,
            raw_result_id=filing.raw_result_id,
            parser_version=filing.parser_version,
            parsed_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
            parse_status="succeeded",
            review_status="approved",
            output_hash=f"output-{filing.id}",
            fact_count=1,
            diagnostics_json="{}",
            reviewed_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
            reviewed_by="test-reviewer",
        )
        self.db.add(parse_run)
        self.db.flush()
        return parse_run

    def test_metadata_exposes_versioned_financial_tables_and_constraints(self) -> None:
        table_names = set(inspect(self.engine).get_table_names())
        self.assertTrue(
            {
                "tw_financial_filing",
                "tw_financial_parse_run",
                "tw_financial_statement_fact",
                "tw_financial_corporate_action",
                "tw_financial_normalized_fact",
            }.issubset(table_names)
        )

        filing_columns = {
            column["name"]
            for column in inspect(self.engine).get_columns("tw_financial_filing")
        }
        self.assertTrue(
            {
                "announced_at",
                "filed_at",
                "provider_generated_at",
                "fetched_at",
                "known_at",
                "content_hash",
                "supersedes_filing_id",
            }.issubset(filing_columns)
        )

    def test_filing_versions_and_fact_lineage_are_persisted_without_redefining_legacy_eps(
        self,
    ) -> None:
        filing = self._add_filing()
        parse_run = self._add_parse_run(filing)
        fact = TaiwanFinancialStatementFact(
            filing_id=filing.id,
            parse_run_id=parse_run.id,
            stock_id="2327",
            fact_key="basic_eps|current|2026Q1",
            metric_code="basic_eps",
            source_label="基本每股盈餘",
            source_value=Decimal("3.90"),
            source_value_text="3.90",
            source_unit="TWD_per_share",
            currency="TWD",
            statement_type="per_share",
            period_kind="duration",
            period_scope="ytd_3m",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 3, 31),
            months_covered=3,
            fiscal_year=2026,
            fiscal_quarter=1,
            consolidation_scope="consolidated",
            attribution_scope="parent",
            eps_kind="basic",
            presentation_role="current_period",
            source_share_basis_id="2327-post-2025-split",
            source_restated=True,
            source_restated_status="confirmed",
        )
        self.db.add(fact)
        self.db.flush()
        normalized = TaiwanFinancialNormalizedFact(
            source_fact_id=fact.id,
            comparison_basis_id="2327-current-share-basis-2025-08-22",
            normalization_mode="current_comparable",
            normalized_value=Decimal("3.90"),
            normalized_unit="TWD_per_share",
            adjustment_factor=Decimal("1"),
            normalization_status="unchanged",
            normalization_version="tw-financial-normalization-v1",
            derived_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
            decision_usable=True,
            issue_codes_json="[]",
            lineage_json=json.dumps(
                {"source_fact_ids": [fact.id], "corporate_action_ids": []}
            ),
        )
        self.db.add(normalized)
        self.db.commit()

        self.assertEqual(fact.source_value, Decimal("3.9000000000"))
        self.assertEqual(normalized.normalized_value, Decimal("3.9000000000"))
        self.assertEqual(
            json.loads(normalized.lineage_json)["source_fact_ids"],
            [fact.id],
        )

    def test_duplicate_filing_version_is_rejected(self) -> None:
        filing = self._add_filing()
        duplicate = TaiwanFinancialFiling(
            source_id=filing.source_id,
            raw_result_id=filing.raw_result_id,
            stock_id=filing.stock_id,
            source_document_id=filing.source_document_id,
            source_document_url=filing.source_document_url,
            content_hash=filing.content_hash,
            filing_kind=filing.filing_kind,
            fiscal_year=filing.fiscal_year,
            fiscal_quarter=filing.fiscal_quarter,
            period_end=filing.period_end,
            fetched_at=filing.fetched_at,
            parser_version=filing.parser_version,
        )
        self.db.add(duplicate)

        with self.assertRaises(IntegrityError):
            self.db.flush()

    def test_corporate_action_purpose_separates_per_share_adjustment(self) -> None:
        action = TaiwanFinancialCorporateAction(
            source_id=self.source_id,
            raw_result_id=self.raw_result_id,
            stock_id="2327",
            action_type="share_split",
            announced_at=datetime(2025, 5, 27, tzinfo=timezone.utc),
            record_date=date(2025, 8, 22),
            effective_date=date(2025, 8, 22),
            old_share_basis=Decimal("10"),
            new_share_basis=Decimal("2.5"),
            adjustment_ratio=Decimal("4"),
            adjustment_purpose="per_share_financials",
            source_document_id="2327-par-value-change-2025",
            source_document_url="https://example.test/2327/par-value-change",
            content_hash="action-2327-par-value-change-v1",
            status="confirmed",
        )
        self.db.add(action)
        self.db.commit()

        self.assertEqual(action.adjustment_ratio, Decimal("4.0000000000"))
        self.assertEqual(action.adjustment_purpose, "per_share_financials")

    def test_migration_0045_creates_and_downgrades_only_semantic_tables(self) -> None:
        root = Path(__file__).resolve().parents[2] / ".tmp" / "financial_semantic_migration"
        root.mkdir(parents=True, exist_ok=True)
        directory = root / uuid.uuid4().hex
        directory.mkdir()
        database_path = directory / "semantic.db"
        database_url = f"sqlite:///{database_path.as_posix()}"
        config = create_alembic_config(database_url)
        semantic_tables = {
            "tw_financial_filing",
            "tw_financial_statement_fact",
            "tw_financial_corporate_action",
            "tw_financial_normalized_fact",
        }

        try:
            command.upgrade(config, "20260730_0044")
            engine = create_engine(database_url)
            try:
                Base.metadata.tables["tw_financial_normalized_fact"].drop(engine)
                Base.metadata.tables["tw_financial_corporate_action"].drop(engine)
                Base.metadata.tables["tw_financial_statement_fact"].drop(engine)
                Base.metadata.tables["tw_financial_filing"].drop(engine)
            finally:
                engine.dispose()

            command.upgrade(config, "20260730_0045")
            engine = create_engine(database_url)
            try:
                table_names = set(inspect(engine).get_table_names())
            finally:
                engine.dispose()
            self.assertTrue(semantic_tables.issubset(table_names))
            self.assertEqual(get_database_revision(database_url), "20260730_0045")

            command.downgrade(config, "20260730_0044")
            engine = create_engine(database_url)
            try:
                table_names = set(inspect(engine).get_table_names())
            finally:
                engine.dispose()
            self.assertTrue(semantic_tables.isdisjoint(table_names))
            self.assertEqual(get_database_revision(database_url), "20260730_0044")
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_migration_0047_adopts_legacy_facts_into_approved_parse_run(
        self,
    ) -> None:
        root = (
            Path(__file__).resolve().parents[2]
            / ".tmp"
            / "financial_parse_run_migration"
        )
        root.mkdir(parents=True, exist_ok=True)
        directory = root / uuid.uuid4().hex
        directory.mkdir()
        database_path = directory / "parse-runs.db"
        database_url = f"sqlite:///{database_path.as_posix()}"
        config = create_alembic_config(database_url)

        try:
            command.upgrade(config, "20260730_0046")
            engine = create_engine(database_url)
            try:
                with engine.begin() as connection:
                    connection.exec_driver_sql(
                        "DROP TABLE tw_financial_normalized_fact"
                    )
                    connection.exec_driver_sql(
                        "DROP TABLE tw_financial_statement_fact"
                    )
                    connection.exec_driver_sql(
                        "DROP TABLE tw_financial_parse_run"
                    )
                    connection.exec_driver_sql(
                        """
                        CREATE TABLE tw_financial_statement_fact (
                            id INTEGER NOT NULL,
                            filing_id INTEGER NOT NULL,
                            stock_id VARCHAR(20) NOT NULL,
                            fact_key VARCHAR(180) NOT NULL,
                            metric_code VARCHAR(100) NOT NULL,
                            source_label VARCHAR(240) NOT NULL,
                            source_value NUMERIC(30, 10) NOT NULL,
                            source_value_text VARCHAR(120),
                            source_unit VARCHAR(40) NOT NULL,
                            unit_inference_source TEXT,
                            currency VARCHAR(10),
                            statement_type VARCHAR(30) NOT NULL,
                            period_kind VARCHAR(20) NOT NULL,
                            period_scope VARCHAR(40) NOT NULL,
                            period_start DATE,
                            period_end DATE NOT NULL,
                            months_covered INTEGER,
                            fiscal_year INTEGER NOT NULL,
                            fiscal_quarter INTEGER,
                            consolidation_scope VARCHAR(40) NOT NULL,
                            attribution_scope VARCHAR(60) NOT NULL,
                            eps_kind VARCHAR(20) NOT NULL,
                            presentation_role VARCHAR(30) NOT NULL,
                            source_share_basis_id VARCHAR(160),
                            source_restated BOOLEAN,
                            source_restated_status VARCHAR(30) NOT NULL,
                            created_at DATETIME NOT NULL,
                            updated_at DATETIME NOT NULL,
                            PRIMARY KEY (id),
                            CONSTRAINT uq_tw_financial_statement_fact_filing_key
                                UNIQUE (filing_id, fact_key),
                            CONSTRAINT ck_tw_financial_statement_fact_period_kind
                                CHECK (period_kind IN ('duration', 'instant')),
                            CONSTRAINT ck_tw_financial_statement_fact_presentation_role
                                CHECK (presentation_role IN (
                                    'current_period',
                                    'comparative_period'
                                )),
                            CONSTRAINT ck_tw_financial_statement_fact_eps_kind
                                CHECK (eps_kind IN (
                                    'basic',
                                    'diluted',
                                    'not_applicable'
                                )),
                            CONSTRAINT ck_tw_financial_statement_fact_restatement
                                CHECK (source_restated_status IN (
                                    'confirmed',
                                    'not_restated',
                                    'unknown'
                                )),
                            FOREIGN KEY(filing_id)
                                REFERENCES tw_financial_filing (id)
                        )
                        """
                    )
                    connection.execute(
                        text(
                            "INSERT INTO source_registry "
                            "(id, source_name, source_type, category, enabled, "
                            "priority, auth_type, reliability_level, created_at, "
                            "updated_at) VALUES "
                            "(1, 'parse-run-test', 'official', 'financial', 1, "
                            "1, 'none', 'official', :now, :now)"
                        ),
                        {"now": "2026-07-30 00:00:00"},
                    )
                    connection.execute(
                        text(
                            "INSERT INTO raw_fetch_result "
                            "(id, source_id, fetched_at, method, parser_version) "
                            "VALUES (1, 1, :now, 'GET', 'mops-ixbrl-v1')"
                        ),
                        {"now": "2026-07-30 00:00:00"},
                    )
                    connection.execute(
                        text(
                            "INSERT INTO tw_financial_filing "
                            "(id, source_id, raw_result_id, stock_id, "
                            "source_document_id, content_hash, filing_kind, "
                            "fiscal_year, fiscal_quarter, period_end, fetched_at, "
                            "parser_version, created_at, updated_at) VALUES "
                            "(1, 1, 1, '2327', '2327-2026Q1', 'filing-hash', "
                            "'quarterly_report', 2026, 1, '2026-03-31', :now, "
                            "'mops-ixbrl-v1', :now, :now)"
                        ),
                        {"now": "2026-07-30 00:00:00"},
                    )
                    connection.execute(
                        text(
                            "INSERT INTO tw_financial_statement_fact "
                            "(id, filing_id, stock_id, fact_key, metric_code, "
                            "source_label, source_value, source_value_text, "
                            "source_unit, currency, statement_type, period_kind, "
                            "period_scope, period_start, period_end, months_covered, "
                            "fiscal_year, fiscal_quarter, consolidation_scope, "
                            "attribution_scope, eps_kind, presentation_role, "
                            "source_restated_status, created_at, updated_at) VALUES "
                            "(1, 1, '2327', 'eps|current|2026Q1', 'basic_eps', "
                            "'Basic EPS', 3.90, '3.90', 'TWD_per_share', 'TWD', "
                            "'per_share', 'duration', 'ytd_3m', '2026-01-01', "
                            "'2026-03-31', 3, 2026, 1, 'consolidated', 'parent', "
                            "'basic', 'current_period', 'not_restated', :now, :now)"
                        ),
                        {"now": "2026-07-30 00:00:00"},
                    )
            finally:
                engine.dispose()

            command.upgrade(config, "20260730_0047")
            engine = create_engine(database_url)
            try:
                with engine.connect() as connection:
                    parse_run = connection.execute(
                        text(
                            "SELECT id, filing_id, parser_version, parse_status, "
                            "review_status, output_hash, fact_count "
                            "FROM tw_financial_parse_run"
                        )
                    ).mappings().one()
                    fact_row = connection.execute(
                        text(
                            "SELECT filing_id, parse_run_id "
                            "FROM tw_financial_statement_fact"
                        )
                    ).mappings().one()
                unique_constraints = {
                    item["name"]
                    for item in inspect(engine).get_unique_constraints(
                        "tw_financial_statement_fact"
                    )
                }
                foreign_keys = {
                    (
                        tuple(item["constrained_columns"]),
                        item["referred_table"],
                    )
                    for item in inspect(engine).get_foreign_keys(
                        "tw_financial_statement_fact"
                    )
                }
            finally:
                engine.dispose()

            self.assertEqual(parse_run["filing_id"], 1)
            self.assertEqual(parse_run["parser_version"], "mops-ixbrl-v1")
            self.assertEqual(parse_run["parse_status"], "succeeded")
            self.assertEqual(parse_run["review_status"], "approved")
            self.assertEqual(len(parse_run["output_hash"]), 64)
            self.assertEqual(parse_run["fact_count"], 1)
            self.assertEqual(fact_row["filing_id"], 1)
            self.assertEqual(fact_row["parse_run_id"], parse_run["id"])
            self.assertIn(
                "uq_tw_financial_statement_fact_parse_run_key",
                unique_constraints,
            )
            self.assertEqual(
                foreign_keys,
                {
                    (("filing_id",), "tw_financial_filing"),
                    (("parse_run_id",), "tw_financial_parse_run"),
                },
            )

            command.downgrade(config, "20260730_0046")
            engine = create_engine(database_url)
            try:
                columns = {
                    item["name"]
                    for item in inspect(engine).get_columns(
                        "tw_financial_statement_fact"
                    )
                }
                fact_count = engine.connect().execute(
                    text("SELECT COUNT(*) FROM tw_financial_statement_fact")
                ).scalar_one()
            finally:
                engine.dispose()
            self.assertNotIn("parse_run_id", columns)
            self.assertEqual(fact_count, 1)
            self.assertEqual(get_database_revision(database_url), "20260730_0046")
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_migration_0049_adopts_review_snapshots_as_immutable_events(
        self,
    ) -> None:
        root = (
            Path(__file__).resolve().parents[2]
            / ".tmp"
            / "financial_parse_review_migration"
        )
        root.mkdir(parents=True, exist_ok=True)
        directory = root / uuid.uuid4().hex
        directory.mkdir()
        database_path = directory / "parse-reviews.db"
        database_url = f"sqlite:///{database_path.as_posix()}"
        config = create_alembic_config(database_url)

        try:
            command.upgrade(config, "20260731_0048")
            engine = create_engine(database_url)
            db = Session(engine)
            try:
                source = SourceRegistry(
                    source_name="parse-review-migration-test",
                    source_type="official",
                    category="financial",
                    enabled=True,
                    priority=1,
                    auth_type="none",
                    reliability_level="official",
                )
                db.add(source)
                db.flush()
                reviewed_at = datetime(2026, 7, 31, tzinfo=timezone.utc)
                raw = RawFetchResult(
                    source_id=source.id,
                    fetched_at=reviewed_at,
                    method="GET",
                    content_hash="parse-review-migration-raw",
                    parser_version="parse-review-migration-v1",
                )
                db.add(raw)
                db.flush()
                filing = TaiwanFinancialFiling(
                    source_id=source.id,
                    raw_result_id=raw.id,
                    stock_id="2327",
                    source_document_id="parse-review-migration-filing",
                    content_hash="parse-review-migration-filing",
                    filing_kind="quarterly_report",
                    fiscal_year=2026,
                    fiscal_quarter=1,
                    period_end=date(2026, 3, 31),
                    fetched_at=reviewed_at,
                    known_at=reviewed_at,
                    parser_version="parse-review-migration-v1",
                )
                db.add(filing)
                db.flush()
                db.add(
                    TaiwanFinancialParseRun(
                        filing_id=filing.id,
                        raw_result_id=raw.id,
                        parser_version="parse-review-migration-v1",
                        parsed_at=reviewed_at,
                        parse_status="succeeded",
                        review_status="approved",
                        output_hash="a" * 64,
                        fact_count=0,
                        diagnostics_json="{}",
                        reviewed_at=reviewed_at,
                        reviewed_by="migration-test-reviewer",
                    )
                )
                db.commit()
                self.assertEqual(
                    db.query(TaiwanFinancialParseRun).filter(
                        TaiwanFinancialParseRun.review_status == "approved"
                    ).count(),
                    1,
                )
            finally:
                db.close()
                engine.dispose()

            engine = create_engine(database_url)
            try:
                self.assertIn(
                    "tw_financial_parse_run_review",
                    set(inspect(engine).get_table_names()),
                )
                with engine.connect() as connection:
                    review_count = connection.execute(
                        text(
                            "SELECT COUNT(*) "
                            "FROM tw_financial_parse_run_review"
                        )
                    ).scalar_one()
                self.assertEqual(review_count, 0)
            finally:
                engine.dispose()
            command.upgrade(config, "20260731_0049")
            engine = create_engine(database_url)
            try:
                with Session(engine) as migrated_db:
                    parse_run_count = migrated_db.query(
                        TaiwanFinancialParseRun
                    ).count()
                    review_count = migrated_db.query(
                        TaiwanFinancialParseRunReview
                    ).count()
                    self.assertEqual(
                        (parse_run_count, review_count),
                        (1, 1),
                    )
                    review = migrated_db.query(
                        TaiwanFinancialParseRunReview
                    ).one()
                    self.assertEqual(review.decision, "approved")
                    self.assertEqual(
                        review.decided_by,
                        "migration-test-reviewer",
                    )
                    self.assertEqual(review.output_hash_snapshot, "a" * 64)
                self.assertEqual(
                    get_database_revision(database_url),
                    "20260731_0049",
                )
            finally:
                engine.dispose()

            command.downgrade(config, "20260731_0048")
            engine = create_engine(database_url)
            try:
                self.assertNotIn(
                    "tw_financial_parse_run_review",
                    set(inspect(engine).get_table_names()),
                )
                with engine.connect() as connection:
                    current_status = connection.execute(
                        text(
                            "SELECT review_status FROM tw_financial_parse_run"
                        )
                    ).scalar_one()
                self.assertEqual(current_status, "approved")
                self.assertEqual(
                    get_database_revision(database_url),
                    "20260731_0048",
                )
            finally:
                engine.dispose()
            command.upgrade(config, "20260731_0049")
            engine = create_engine(database_url)
            try:
                with Session(engine) as migrated_db:
                    self.assertEqual(
                        migrated_db.query(
                            TaiwanFinancialParseRunReview
                        ).count(),
                        1,
                    )
                self.assertEqual(
                    get_database_revision(database_url),
                    "20260731_0049",
                )
            finally:
                engine.dispose()
        finally:
            shutil.rmtree(directory, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
