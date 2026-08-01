from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    RawFetchResult,
    SourceRegistry,
    TaiwanFinancialCorporateAction,
    TaiwanFinancialFiling,
    TaiwanFinancialNormalizedFact,
    TaiwanFinancialParseRun,
    TaiwanFinancialStatementFact,
)
from app.market.financial_evidence_package import (
    TaiwanFinancialEvidencePackage,
    apply_financial_evidence_package,
)


class FinancialEvidencePackageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.reviewed_at = datetime(
            2026,
            7,
            30,
            10,
            0,
            tzinfo=timezone.utc,
        )
        source = SourceRegistry(
            source_name="TWSE Financial Metrics",
            source_type="api_bundle",
            category="financial_metrics",
            enabled=True,
            priority=70,
            parser_type="financial_metrics",
            auth_type="none",
            reliability_level="official",
        )
        self.db.add(source)
        self.db.flush()
        raw = RawFetchResult(
            source_id=source.id,
            fetched_at=self.reviewed_at,
            method="GET",
            status_code=200,
            content_hash="source-content",
            parser_version="source-v1",
        )
        self.db.add(raw)
        self.db.flush()
        filing = TaiwanFinancialFiling(
            source_id=source.id,
            raw_result_id=raw.id,
            stock_id="2327",
            source_document_id="legacy-2327-2025q1",
            content_hash="source-content",
            filing_kind="provider_financial_snapshot",
            fiscal_year=2025,
            fiscal_quarter=1,
            period_end=date(2025, 3, 31),
            announced_at=None,
            filed_at=None,
            fetched_at=self.reviewed_at,
            known_at=None,
            parser_version="source-v1",
        )
        self.db.add(filing)
        self.db.flush()
        parse_run = TaiwanFinancialParseRun(
            filing_id=filing.id,
            raw_result_id=raw.id,
            parser_version="source-v1",
            parsed_at=self.reviewed_at,
            parse_status="succeeded",
            review_status="approved",
            output_hash="evidence-source-output",
            fact_count=1,
            diagnostics_json="{}",
            reviewed_at=self.reviewed_at,
            reviewed_by="test-reviewer",
        )
        self.db.add(parse_run)
        self.db.flush()
        self.db.add(
            TaiwanFinancialStatementFact(
                filing_id=filing.id,
                parse_run_id=parse_run.id,
                stock_id="2327",
                fact_key="eps|current|2025Q1",
                metric_code="basic_eps",
                source_label="基本每股盈餘",
                source_value=Decimal("10"),
                source_value_text="10",
                source_unit="TWD_per_share",
                currency="TWD",
                statement_type="per_share",
                period_kind="duration",
                period_scope="ytd_3m",
                period_start=date(2025, 1, 1),
                period_end=date(2025, 3, 31),
                months_covered=3,
                fiscal_year=2025,
                fiscal_quarter=1,
                consolidation_scope="unknown",
                attribution_scope="parent",
                eps_kind="basic",
                presentation_role="current_period",
                source_share_basis_id=None,
                source_restated=None,
                source_restated_status="unknown",
            )
        )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _package(self, *, expected_source_value: str = "10"):
        return TaiwanFinancialEvidencePackage.model_validate(
            {
                "package_version": "omi.tw-financial-evidence.v1",
                "package_id": "2327-test-v1",
                "approval_scope": "clone_only",
                "review_status": "approved",
                "reviewer": "test-reviewer",
                "reviewed_at": self.reviewed_at,
                "stock_id": "2327",
                "mode": "current_comparable",
                "comparison_basis_id": "2327-current-basis",
                "target_basis_date": "2025-08-22",
                "normalization_version": "test-normalization-v1",
                "evidence_source_name": "Yageo filing mirror",
                "sources": [
                    {
                        "source_name": "TWSE Financial Metrics",
                        "source_type": "api_bundle",
                        "category": "financial_metrics",
                        "priority": 70,
                        "reliability_level": "official",
                    },
                    {
                        "source_name": "Yageo filing mirror",
                        "source_type": "filing_mirror",
                        "category": "financial_filing_evidence",
                        "endpoint_url": "https://example.test/yageo-filing",
                        "priority": 20,
                        "reliability_level": "verified_official_mirror",
                    },
                ],
                "documents": [
                    {
                        "document_id": "yageo-action-document",
                        "url": "https://example.test/yageo-filing",
                        "description": "Reviewed filing mirror",
                        "content_hash": None,
                        "content_hash_status": "package_assertion_only",
                    }
                ],
                "actions": [
                    {
                        "source_name": "Yageo filing mirror",
                        "action_key": "2327-share-change-2025-08-22",
                        "action_type": "share_split_equivalent",
                        "announced_at": None,
                        "record_date": "2025-08-22",
                        "effective_date": "2025-08-22",
                        "old_share_basis": "10",
                        "new_share_basis": "2.5",
                        "adjustment_ratio": "4",
                        "adjustment_purpose": "per_share_financials",
                        "source_document_id": "yageo-action-document",
                        "source_document_url": "https://example.test/yageo-filing",
                        "status": "confirmed",
                    }
                ],
                "facts": [
                    {
                        "source_name": "TWSE Financial Metrics",
                        "fiscal_year": 2025,
                        "fiscal_quarter": 1,
                        "metric_code": "basic_eps",
                        "expected_source_value": expected_source_value,
                        "source_share_basis_id": "2327-old-basis",
                        "source_restated_status": "not_restated",
                        "expected_normalized_value": "2.5",
                        "evidence_document_ids": ["yageo-action-document"],
                    }
                ],
            }
        )

    def test_dry_run_validates_without_mutation(self) -> None:
        summary = apply_financial_evidence_package(
            self.db,
            package=self._package(),
            apply=False,
        )

        self.assertEqual(summary["normalized_facts_created"], 1)
        self.assertEqual(summary["results"][0]["normalized_value"], "2.5000000000")
        self.assertEqual(
            self.db.query(TaiwanFinancialNormalizedFact).count(),
            0,
        )
        self.assertEqual(
            self.db.query(TaiwanFinancialCorporateAction).count(),
            0,
        )
        self.assertEqual(self.db.query(SourceRegistry).count(), 1)

    def test_apply_is_idempotent_and_preserves_lineage(self) -> None:
        first = apply_financial_evidence_package(
            self.db,
            package=self._package(),
            apply=True,
        )
        self.db.commit()
        second = apply_financial_evidence_package(
            self.db,
            package=self._package(),
            apply=True,
        )
        self.db.commit()

        self.assertEqual(first["normalized_facts_created"], 1)
        self.assertEqual(second["normalized_facts_created"], 0)
        self.assertEqual(second["normalized_facts_reused"], 1)
        self.assertEqual(
            self.db.query(TaiwanFinancialNormalizedFact).count(),
            1,
        )
        self.assertEqual(
            self.db.query(TaiwanFinancialCorporateAction).count(),
            1,
        )
        normalized = self.db.query(TaiwanFinancialNormalizedFact).one()
        self.assertEqual(normalized.normalized_value, Decimal("2.5"))
        self.assertIn('"package_hash"', normalized.lineage_json)
        self.assertIn(
            "2327-share-change-2025-08-22",
            normalized.lineage_json,
        )

    def test_changed_source_value_requires_re_review(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "source value changed",
        ):
            apply_financial_evidence_package(
                self.db,
                package=self._package(expected_source_value="9.99"),
                apply=False,
            )

    def test_action_free_package_requires_explicit_share_basis_assessment(
        self,
    ) -> None:
        payload = self._package().model_dump(mode="json")
        payload["actions"] = []
        payload["facts"][0]["expected_normalized_value"] = "10"

        with self.assertRaisesRegex(
            ValidationError,
            "share_basis_assessment is required",
        ):
            TaiwanFinancialEvidencePackage.model_validate(payload)

        payload["share_basis_assessment"] = {
            "status": "verified_unchanged",
            "verification_method": "cross_filing_comparative_reconciliation",
            "rationale": (
                "The later official filing repeats the earlier comparative "
                "EPS without a basis change."
            ),
            "evidence_document_ids": ["yageo-action-document"],
        }
        package = TaiwanFinancialEvidencePackage.model_validate(payload)
        summary = apply_financial_evidence_package(
            self.db,
            package=package,
            apply=False,
        )

        self.assertEqual(
            summary["share_basis_assessment"]["status"],
            "verified_unchanged",
        )
        self.assertEqual(
            summary["results"][0]["adjustment_factor"],
            "1",
        )

    def test_same_quarter_allows_distinct_explicit_period_scopes(self) -> None:
        payload = self._package().model_dump(mode="json")
        first = payload["facts"][0]
        first["fiscal_quarter"] = 2
        first["period_scope"] = "ytd_6m"
        first["fact_key"] = "eps|current|2025Q2-ytd"
        second = {
            **first,
            "period_scope": "discrete_3m",
            "fact_key": "eps|current|2025Q2-discrete",
        }
        payload["facts"] = [first, second]

        package = TaiwanFinancialEvidencePackage.model_validate(payload)
        self.assertEqual(
            [fact.period_scope for fact in package.facts],
            ["ytd_6m", "discrete_3m"],
        )

        payload["facts"][1]["period_scope"] = "ytd_6m"
        with self.assertRaisesRegex(
            ValidationError,
            "duplicate fact adjudication",
        ):
            TaiwanFinancialEvidencePackage.model_validate(payload)

    def test_official_restated_treatment_requires_confirmed_action_evidence(
        self,
    ) -> None:
        payload = self._package().model_dump(mode="json")
        fact = payload["facts"][0]
        fact["source_restated_status"] = "confirmed"
        fact["normalization_treatment"] = "official_restated"

        package = TaiwanFinancialEvidencePackage.model_validate(payload)
        self.assertEqual(
            package.facts[0].normalization_treatment,
            "official_restated",
        )

        payload["facts"][0]["source_restated_status"] = "not_restated"
        with self.assertRaisesRegex(
            ValidationError,
            "confirmed source restatement status",
        ):
            TaiwanFinancialEvidencePackage.model_validate(payload)

    def test_restatement_status_mismatch_without_official_adjudication_fails(
        self,
    ) -> None:
        source_fact = self.db.query(TaiwanFinancialStatementFact).one()
        source_fact.source_restated_status = "not_restated"
        self.db.commit()
        payload = self._package().model_dump(mode="json")
        payload["facts"][0]["source_restated_status"] = "confirmed"
        package = TaiwanFinancialEvidencePackage.model_validate(payload)

        with self.assertRaisesRegex(
            ValueError,
            "source restatement status changed",
        ):
            apply_financial_evidence_package(
                self.db,
                package=package,
                apply=False,
            )

    def test_reviewed_official_restatement_can_override_parser_status(
        self,
    ) -> None:
        source_fact = self.db.query(TaiwanFinancialStatementFact).one()
        source_fact.source_restated_status = "not_restated"
        self.db.commit()
        payload = self._package().model_dump(mode="json")
        payload["facts"][0].update(
            {
                "source_restated_status": "confirmed",
                "expected_normalized_value": "10",
                "normalization_treatment": "official_restated",
            }
        )
        package = TaiwanFinancialEvidencePackage.model_validate(payload)

        summary = apply_financial_evidence_package(
            self.db,
            package=package,
            apply=False,
        )

        self.assertEqual(
            summary["results"][0]["normalized_value"],
            "10.0000000000",
        )
        self.assertEqual(summary["results"][0]["adjustment_factor"], "1")
        self.assertEqual(
            summary["results"][0]["adjustment_treatment"],
            "official_restated",
        )


if __name__ == "__main__":
    unittest.main()
