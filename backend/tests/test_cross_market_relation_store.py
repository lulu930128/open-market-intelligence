from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    CrossMarketRelation,
    CrossMarketRelationEvidence,
)
from app.market.cross_market.maintenance import (
    approve_relation,
    create_relation_candidate,
    disable_relation,
    reject_relation,
    validate_registry,
)
from app.market.cross_market.relation_store import (
    build_relation_registry_read,
    validate_candidate,
)
from app.market.cross_market.schemas import (
    CrossMarketRelationCandidate,
    CrossMarketRelationEvidenceCandidate,
    InstrumentRefRead,
)
from app.market.cross_market.types import InstrumentRef, taiwan_stock_ref


VERIFIED_AT = datetime(2026, 7, 22, tzinfo=timezone.utc)


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return Session(engine)


def direct_candidate(
    *,
    valid_from: date = date(2026, 7, 22),
    valid_to: date | None = None,
) -> CrossMarketRelationCandidate:
    return CrossMarketRelationCandidate(
        source=InstrumentRefRead(
            market="US",
            instrument_type="adr",
            canonical_symbol="US:TSM",
            provider_symbol="TSM",
            exchange="NYSE",
            currency="USD",
        ),
        target=InstrumentRefRead(
            market="TW",
            instrument_type="stock",
            canonical_symbol="TW:2330",
            provider_symbol="2330",
            exchange="TWSE",
            currency="TWD",
        ),
        relation_type="same_equity_dr",
        relation_subtype="verified_adr",
        bucket="direct_equivalent",
        directionality="equivalent",
        base_weight=1.0,
        confidence_tier="A",
        evidence_grade="official_primary",
        ratio_numerator=1,
        ratio_denominator=5,
        listing_tier="primary",
        valid_from=valid_from,
        valid_to=valid_to,
        verified_at=VERIFIED_AT,
        evidence=[
            CrossMarketRelationEvidenceCandidate(
                source_type="sec_filing",
                source_grade="A",
                source_label="TSMC 2025 Form 20-F",
                source_url="https://example.test/tsm-20f",
                statement="One ADR represents five common shares.",
                verified_at=VERIFIED_AT,
                is_primary=True,
            )
        ],
    )


def add_approved_relation(
    db: Session,
    *,
    include_evidence: bool = True,
    valid_from: date = date(2026, 7, 22),
    version: int = 1,
) -> CrossMarketRelation:
    relation = CrossMarketRelation(
        source_market="US",
        source_instrument_type="adr",
        source_canonical_symbol="US:TSM",
        source_provider_symbol="TSM",
        source_exchange="NYSE",
        source_currency="USD",
        target_market="TW",
        target_instrument_type="stock",
        target_canonical_symbol="TW:2330",
        target_provider_symbol="2330",
        target_exchange="TWSE",
        target_currency="TWD",
        relation_type="same_equity_dr",
        relation_subtype="verified_adr",
        bucket="direct_equivalent",
        directionality="equivalent",
        base_weight=Decimal("1"),
        confidence_tier="A",
        evidence_grade="official_primary",
        ratio_numerator=Decimal("1"),
        ratio_denominator=Decimal("5"),
        listing_tier="primary",
        valid_from=valid_from,
        verified_at=VERIFIED_AT,
        review_status="approved",
        is_active=True,
        version=version,
        created_by="test",
        change_reason="test fixture",
    )
    if include_evidence:
        relation.evidence = [
            CrossMarketRelationEvidence(
                source_type="sec_filing",
                source_grade="A",
                source_label="TSMC 2025 Form 20-F",
                source_url="https://example.test/tsm-20f",
                statement="One ADR represents five common shares.",
                verified_at=VERIFIED_AT,
                content_hash="a" * 64,
                is_primary=True,
                review_status="approved",
                created_by="test",
            )
        ]
    db.add(relation)
    db.commit()
    db.refresh(relation)
    return relation


class CrossMarketRelationStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = make_session()

    def tearDown(self) -> None:
        engine = self.db.get_bind()
        self.db.close()
        engine.dispose()

    def test_instrument_identity_separates_market_type_and_provider_symbol(self) -> None:
        ref = InstrumentRef.create(
            market="us",
            instrument_type="adr",
            symbol="TSM",
            provider_symbol="TSM",
            exchange="nyse",
            currency="usd",
        )

        self.assertEqual(ref.market, "US")
        self.assertEqual(ref.instrument_type, "adr")
        self.assertEqual(ref.canonical_symbol, "US:TSM")
        self.assertEqual(ref.provider_symbol, "TSM")
        self.assertEqual(taiwan_stock_ref(" 2330 ").canonical_symbol, "TW:2330")
        with self.assertRaises(ValueError):
            InstrumentRef.create(
                market="US",
                instrument_type="adr",
                symbol="TW:2330",
            )

    def test_registry_read_returns_governed_direct_relation(self) -> None:
        relation = add_approved_relation(self.db)

        result = build_relation_registry_read(
            self.db,
            "2330",
            as_of=date(2026, 8, 9),
            generated_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
        )

        self.assertEqual(result.status, "ready")
        self.assertTrue(result.decision_usable)
        self.assertEqual(result.relation_count, 1)
        self.assertEqual(result.relations[0].relation_id, relation.id)
        self.assertEqual(result.relations[0].source.canonical_symbol, "US:TSM")
        self.assertEqual(result.relations[0].ratio_denominator, 5.0)
        self.assertEqual(result.relations[0].evidence[0].source_grade, "A")
        self.assertIn(
            "historical_validity_before_verification_not_asserted",
            result.relations[0].limitations,
        )
        self.assertFalse(result.freshness["market_data_included"])

    def test_registry_read_distinguishes_not_applicable_and_blocked(self) -> None:
        not_applicable = build_relation_registry_read(
            self.db,
            "1101",
            as_of=date(2026, 8, 9),
        )
        self.assertEqual(not_applicable.status, "not_applicable")
        self.assertEqual(not_applicable.relation_count, 0)
        self.assertEqual(not_applicable.missing, [])

        add_approved_relation(self.db, include_evidence=False)
        blocked = build_relation_registry_read(
            self.db,
            "2330",
            as_of=date(2026, 8, 9),
        )
        self.assertEqual(blocked.status, "blocked")
        self.assertFalse(blocked.decision_usable)
        self.assertIn("relation_evidence_missing", blocked.missing)
        self.assertIn("relation_primary_evidence_missing", blocked.missing)

    def test_registry_read_enforces_relation_and_evidence_availability_dates(self) -> None:
        relation = add_approved_relation(self.db)
        relation.valid_from = date(2026, 7, 1)
        relation.verified_at = datetime(2026, 7, 22, tzinfo=timezone.utc)
        relation.evidence[0].verified_at = datetime(
            2026,
            7,
            25,
            tzinfo=timezone.utc,
        )
        self.db.commit()

        before_relation_verification = build_relation_registry_read(
            self.db,
            "2330",
            as_of=date(2026, 7, 21),
        )
        self.assertEqual(before_relation_verification.status, "not_applicable")

        before_evidence_verification = build_relation_registry_read(
            self.db,
            "2330",
            as_of=date(2026, 7, 23),
        )
        self.assertEqual(before_evidence_verification.status, "blocked")
        self.assertEqual(before_evidence_verification.relations[0].evidence, [])
        self.assertIn(
            "relation_evidence_missing",
            before_evidence_verification.missing,
        )

        after_evidence_verification = build_relation_registry_read(
            self.db,
            "2330",
            as_of=date(2026, 7, 25),
        )
        self.assertEqual(after_evidence_verification.status, "ready")

    def test_candidate_validation_enforces_bucket_ratio_and_primary_evidence(self) -> None:
        candidate = direct_candidate()
        validate_candidate(candidate, require_approvable_evidence=True)

        with self.assertRaisesRegex(ValueError, "positive ratio"):
            validate_candidate(
                candidate.model_copy(update={"ratio_denominator": None})
            )
        with self.assertRaisesRegex(ValueError, "bucket must be"):
            validate_candidate(candidate.model_copy(update={"bucket": "industry_peer"}))
        with self.assertRaisesRegex(ValueError, "requires primary"):
            validate_candidate(
                candidate.model_copy(
                    update={
                        "evidence": [
                            candidate.evidence[0].model_copy(
                                update={"is_primary": False}
                            )
                        ]
                    }
                ),
                require_approvable_evidence=True,
            )

    def test_approval_rejects_validity_overlap(self) -> None:
        add_approved_relation(self.db)
        candidate = create_relation_candidate(
            self.db,
            direct_candidate(valid_from=date(2026, 8, 1)),
            actor="reviewer",
            reason="candidate overlap test",
        )

        with self.assertRaisesRegex(ValueError, "validity overlaps"):
            approve_relation(
                self.db,
                candidate.id,
                actor="reviewer",
                reason="must fail",
            )

        self.assertEqual(
            self.db.get(CrossMarketRelation, candidate.id).review_status,
            "candidate",
        )

    def test_approved_superseding_version_closes_prior_validity(self) -> None:
        prior = add_approved_relation(self.db)
        candidate = create_relation_candidate(
            self.db,
            direct_candidate(valid_from=date(2026, 8, 10)),
            actor="reviewer",
            reason="ratio review candidate",
        )

        approved = approve_relation(
            self.db,
            candidate.id,
            actor="approver",
            reason="verified new effective version",
            supersedes_relation_id=prior.id,
        )

        self.db.refresh(prior)
        self.assertEqual(approved.review_status, "approved")
        self.assertTrue(approved.is_active)
        self.assertEqual(approved.version, 2)
        self.assertEqual(approved.created_by, "reviewer")
        self.assertEqual(approved.reviewed_by, "approver")
        self.assertIsNotNone(approved.reviewed_at)
        self.assertEqual(prior.valid_to, date(2026, 8, 9))
        self.assertEqual(prior.reviewed_by, "approver")
        self.assertEqual(validate_registry(self.db)["status"], "ready")

    def test_reject_and_disable_require_audited_actor_and_reason(self) -> None:
        candidate = create_relation_candidate(
            self.db,
            direct_candidate(valid_from=date(2026, 7, 1)),
            actor="reviewer",
            reason="candidate lifecycle test",
        )
        with self.assertRaisesRegex(ValueError, "actor and reason"):
            reject_relation(
                self.db,
                candidate.id,
                actor=" ",
                reason="invalid audit",
            )
        rejected = reject_relation(
            self.db,
            candidate.id,
            actor="reviewer",
            reason="evidence superseded before approval",
        )
        self.assertEqual(rejected.review_status, "rejected")
        self.assertFalse(rejected.is_active)
        self.assertEqual(rejected.created_by, "reviewer")
        self.assertEqual(rejected.reviewed_by, "reviewer")
        self.assertIsNotNone(rejected.reviewed_at)

        approved = add_approved_relation(
            self.db,
            valid_from=date(2026, 7, 22),
            version=2,
        )
        with self.assertRaisesRegex(ValueError, "actor and reason"):
            disable_relation(
                self.db,
                approved.id,
                actor="reviewer",
                reason=" ",
            )
        disabled = disable_relation(
            self.db,
            approved.id,
            actor="reviewer",
            reason="ratio requires reverification",
        )
        self.assertEqual(disabled.review_status, "revoked")
        self.assertFalse(disabled.is_active)
        self.assertEqual(disabled.created_by, "test")
        self.assertEqual(disabled.reviewed_by, "reviewer")
        self.assertIsNotNone(disabled.reviewed_at)


if __name__ == "__main__":
    unittest.main()
