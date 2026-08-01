from __future__ import annotations

import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    RawFetchResult,
    SourceRegistry,
    TaiwanFinancialBasisAssessment,
)
from app.market.financial_basis_assessment import (
    TaiwanFinancialBasisAssessmentPackage,
    apply_financial_basis_assessment,
)


class FinancialBasisAssessmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.db.add(
            SourceRegistry(
                source_name="MOPS Official Filing iXBRL",
                source_type="official_filing",
                category="financial_filing",
                enabled=True,
                priority=5,
                parser_type="mops_ixbrl",
                auth_type="none",
                reliability_level="official",
            )
        )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _package(self) -> TaiwanFinancialBasisAssessmentPackage:
        return TaiwanFinancialBasisAssessmentPackage.model_validate(
            {
                "package_version": "omi.tw-financial-basis-assessment.v1",
                "package_id": "2881-ifrs17-transition-clone-20260731",
                "approval_scope": "clone_only",
                "review_status": "approved",
                "reviewer": "test-reviewer",
                "reviewed_at": "2026-07-31T02:40:00+08:00",
                "known_at": "2026-05-29T12:01:13+08:00",
                "stock_id": "2881",
                "normalization_mode": "current_comparable",
                "assessment_type": "accounting_basis_transition",
                "outcome": "blocked",
                "effective_date": "2026-01-01",
                "issue_code": (
                    "accounting_basis_transition_incomplete_comparatives"
                ),
                "rationale": (
                    "IFRS 17 restated 2025Q1, but restated 2025Q2-Q4 EPS "
                    "are not yet available."
                ),
                "resolution_requirements": [
                    "restated_2025Q2_discrete_eps",
                    "restated_2025Q3_discrete_and_ytd_eps",
                    "restated_2025_annual_eps",
                ],
                "evidence_source_name": "MOPS Official Filing iXBRL",
                "documents": [
                    {
                        "document_id": "202601_2881_AI1.pdf-binary",
                        "url": "https://example.test/2881.pdf",
                        "description": "Official filing",
                        "content_hash": "a" * 64,
                        "content_hash_status": "verified_source_bytes",
                    }
                ],
                "observations": [
                    {
                        "observation_code": "ifrs17_q1_restatement",
                        "description": "2025Q1 EPS changed from 3.00 to -2.09.",
                        "document_ids": ["202601_2881_AI1.pdf-binary"],
                    }
                ],
            }
        )

    def test_dry_run_does_not_mutate(self) -> None:
        summary = apply_financial_basis_assessment(
            self.db,
            package=self._package(),
            apply=False,
        )

        self.assertEqual(summary["assessment_created"], 1)
        self.assertEqual(
            self.db.query(TaiwanFinancialBasisAssessment).count(),
            0,
        )
        self.assertEqual(self.db.query(RawFetchResult).count(), 0)

    def test_apply_is_idempotent(self) -> None:
        first = apply_financial_basis_assessment(
            self.db,
            package=self._package(),
            apply=True,
        )
        self.db.commit()
        second = apply_financial_basis_assessment(
            self.db,
            package=self._package(),
            apply=True,
        )
        self.db.commit()

        self.assertEqual(first["assessment_created"], 1)
        self.assertEqual(second["assessment_created"], 0)
        self.assertEqual(second["assessment_reused"], 1)
        assessment = self.db.query(TaiwanFinancialBasisAssessment).one()
        self.assertEqual(assessment.outcome, "blocked")
        self.assertEqual(
            assessment.issue_code,
            "accounting_basis_transition_incomplete_comparatives",
        )
        self.assertEqual(
            assessment.reviewed_at.replace(tzinfo=timezone.utc),
            datetime(2026, 7, 30, 18, 40, tzinfo=timezone.utc),
        )


if __name__ == "__main__":
    unittest.main()
