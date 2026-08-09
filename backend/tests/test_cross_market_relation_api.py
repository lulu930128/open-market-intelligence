from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import (
    Base,
    CrossMarketRelation,
    CrossMarketRelationEvidence,
)
from app.main import app
from app.routers.cross_market import get_cross_market_relations


class CrossMarketRelationAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:",
        )
        Base.metadata.create_all(bind=self.engine)
        self.db = Session(self.engine)
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
            valid_from=date(2026, 7, 22),
            verified_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
            review_status="approved",
            is_active=True,
            version=1,
            created_by="test",
            change_reason="test fixture",
        )
        relation.evidence = [
            CrossMarketRelationEvidence(
                source_type="sec_filing",
                source_grade="A",
                source_label="TSMC 2025 Form 20-F",
                source_url="https://example.test/tsm-20f",
                statement="One ADR represents five common shares.",
                verified_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
                content_hash="b" * 64,
                is_primary=True,
                review_status="approved",
                created_by="test",
            )
        ]
        self.db.add(relation)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_read_only_relation_route_returns_structured_registry(self) -> None:
        payload = get_cross_market_relations(
            "2330",
            as_of=date(2026, 8, 9),
            db=self.db,
        )

        self.assertEqual(payload.schema_version, "cross_market.relations.v1")
        self.assertEqual(payload.status, "ready")
        self.assertEqual(payload.relation_count, 1)
        self.assertEqual(
            payload.relations[0].source.canonical_symbol,
            "US:TSM",
        )
        self.assertEqual(payload.relations[0].ratio_denominator, 5.0)
        self.assertFalse(payload.freshness["market_data_included"])

    def test_route_returns_not_applicable_without_false_missing(self) -> None:
        payload = get_cross_market_relations(
            "1101",
            as_of=date(2026, 8, 9),
            db=self.db,
        )

        self.assertEqual(payload.status, "not_applicable")
        self.assertEqual(payload.relations, [])
        self.assertEqual(payload.missing, [])

    def test_route_rejects_malformed_target_identity(self) -> None:
        with self.assertRaises(HTTPException) as context:
            get_cross_market_relations(
                "bad!",
                as_of=date(2026, 8, 9),
                db=self.db,
            )

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("stock_id", context.exception.detail)

    def test_openapi_exposes_read_only_relation_contract(self) -> None:
        operation = app.openapi()["paths"][
            "/api/market/cross-market/relations/{stock_id}"
        ]["get"]

        self.assertNotIn(
            "post",
            app.openapi()["paths"][
                "/api/market/cross-market/relations/{stock_id}"
            ],
        )
        response_schema = operation["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        self.assertEqual(
            response_schema["$ref"],
            "#/components/schemas/CrossMarketRelationRegistryRead",
        )


if __name__ == "__main__":
    unittest.main()
