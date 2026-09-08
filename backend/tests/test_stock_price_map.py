from __future__ import annotations

from datetime import date, datetime
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, MarketDailyPrice, RawFetchResult, SourceRegistry, StockMaster
from app.main import app
from app.market.stock_price_map import (
    _resolve_price_map_status,
    build_tw_stock_price_map,
    cluster_price_levels,
)
from app.market.stock_price_map_schemas import StockPriceMapRead
from app.market.technical_evidence import build_tw_stock_price_map_evidence
from app.market.trading_calendar import TAIWAN_TZ, previous_taiwan_trading_day
from app.sources.defaults import TWSE_RWD_DAILY_TRADING_SOURCE_NAME


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return Session(engine)


def add_daily_fixture(db: Session) -> None:
    db.add(StockMaster(stock_id="2330", stock_name="台積電", market="TWSE", instrument_type="stock"))
    source = SourceRegistry(
        source_name=TWSE_RWD_DAILY_TRADING_SOURCE_NAME,
        source_type="official",
        category="market_daily_price",
        reliability_level="official",
    )
    db.add(source)
    db.flush()
    raw = RawFetchResult(
        source_id=source.id,
        method="GET",
        url="https://example.test/2330/daily",
        status_code=200,
        content_hash="price-map-fixture",
        raw_text="{}",
    )
    db.add(raw)
    db.flush()
    cursor = date(2026, 8, 7)
    dates = [cursor]
    while len(dates) < 90:
        dates.append(previous_taiwan_trading_day(dates[-1], include_value=False))
    for index, trade_date in enumerate(reversed(dates)):
        close = 100.0 + index
        db.add(MarketDailyPrice(
            source_id=source.id,
            raw_result_id=raw.id,
            trade_date=trade_date,
            stock_id="2330",
            stock_name="台積電",
            open_price=close - 1,
            high_price=close + 2,
            low_price=close - 2,
            close_price=close,
            trade_volume=1_000_000 + index,
        ))
    db.commit()


def level(evidence_id: str, price: float, source_type: str = "swing") -> dict:
    return {
        "evidence_id": evidence_id,
        "label": evidence_id,
        "source_type": source_type,
        "price": price,
        "confidence": "medium",
        "strength": "medium",
        "evidence_state": "derived",
        "source_ref": {"type": "derived", "name": source_type},
        "limitations": [],
    }


class StockPriceMapPureTests(unittest.TestCase):
    def test_missing_plan_with_price_evidence_is_partial_not_missing(self) -> None:
        self.assertEqual(
            _resolve_price_map_status(
                plan_status="missing",
                reference_available=True,
                levels_available=True,
                evidence_status="partial",
                corporate_complete=False,
            ),
            "partial",
        )
        self.assertEqual(
            _resolve_price_map_status(
                plan_status="missing",
                reference_available=False,
                levels_available=False,
                evidence_status="missing",
                corporate_complete=False,
            ),
            "missing",
        )

    def test_cluster_is_deterministic_and_does_not_chain_across_wide_span(self) -> None:
        inputs = [level("c", 104), level("a", 100), level("b", 102)]
        first = cluster_price_levels(inputs, reference=100, threshold_pct=2)
        second = cluster_price_levels(reversed(inputs), reference=100, threshold_pct=2)

        self.assertEqual(first, second)
        self.assertEqual(len(first), 2)
        self.assertEqual(first[0]["evidence_ids"], ["a", "b"])
        self.assertEqual(first[1]["evidence_ids"], ["c"])

    def test_single_exact_level_becomes_auditable_band(self) -> None:
        zones = cluster_price_levels(
            [level("single", 105)],
            reference=100,
            threshold_pct=0,
        )

        self.assertEqual(len(zones), 1)
        zone = zones[0]
        self.assertEqual(zone["evidence_lower_bound"], 105)
        self.assertEqual(zone["evidence_upper_bound"], 105)
        self.assertLess(zone["lower_bound"], 105)
        self.assertGreater(zone["upper_bound"], 105)
        self.assertEqual(zone["tier_label"], "R1")
        self.assertEqual(zone["evidence_ids"], ["single"])

    def test_padding_does_not_turn_upside_evidence_into_pivot(self) -> None:
        zone = cluster_price_levels(
            [level("near", 100.5)],
            reference=100,
            threshold_pct=0,
            zone_padding_pct=2,
        )[0]

        self.assertEqual(zone["side"], "upside")
        self.assertEqual(zone["tier_label"], "R1")
        self.assertGreater(zone["lower_bound"], 100)
        self.assertTrue(any("clipped above" in item for item in zone["limitations"]))

    def test_display_overlap_alone_does_not_merge_distinct_tiers(self) -> None:
        zones = cluster_price_levels(
            [level("near", 102), level("far", 105)],
            reference=100,
            threshold_pct=0,
            zone_padding_pct=2,
            zone_merge_gap_ticks=0,
        )

        self.assertEqual([zone["tier_label"] for zone in zones], ["R1", "R2"])

    def test_same_side_raw_gap_can_merge_within_tick_policy(self) -> None:
        zones = cluster_price_levels(
            [level("a", 102), level("b", 103)],
            reference=100,
            threshold_pct=0,
            zone_merge_gap_ticks=2,
        )

        self.assertEqual(len(zones), 1)
        self.assertEqual(zones[0]["evidence_ids"], ["a", "b"])

    def test_confidence_is_not_promoted_by_one_high_among_low_estimates(self) -> None:
        inputs = []
        for index, confidence in enumerate(["high", "low", "low", "low", "low"]):
            item = level(str(index), 100 + index * 0.1, f"family_{index}")
            item["confidence"] = confidence
            if confidence == "low":
                item["evidence_state"] = "estimated"
            inputs.append(item)

        zone = cluster_price_levels(inputs, reference=100, threshold_pct=2)[0]

        self.assertEqual(zone["confidence"], "medium")
        self.assertEqual(zone["strength_components"]["estimated_evidence_count"], 4)


class StockPriceMapServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = make_session()
        add_daily_fixture(self.db)

    def tearDown(self) -> None:
        engine = self.db.get_bind()
        self.db.close()
        engine.dispose()

    def test_focused_evidence_loads_daily_price_map_capabilities_only(self) -> None:
        evidence = build_tw_stock_price_map_evidence(
            db=self.db,
            stock_id="2330",
            corporate_event_history=None,
        )

        self.assertEqual(evidence["version"], "tw.stock.price_map.evidence.v1")
        self.assertEqual(
            list(evidence["indicators"]["timeframes"]),
            ["daily"],
        )
        self.assertTrue(
            {"swings", "fibonacci", "breakout", "volume_profile", "anchored_vwap"}
            <= evidence.keys()
        )
        self.assertNotIn("divergence", evidence)
        self.assertNotIn("relative_strength", evidence)

    @patch("app.market.stock_price_map.get_taiwan_stock_event_history")
    @patch("app.market.stock_price_map.build_tw_stock_price_map_evidence")
    @patch("app.market.stock_price_map.build_stock_technical_report")
    def test_candidate_reuses_recent_completed_daily_basis(
        self,
        report_mock,
        evidence_mock,
        corporate_mock,
    ) -> None:
        report_mock.return_value = {
            "title": "短線偏多",
            "summary": "完成日線",
            "score": 1,
            "confidence": "medium",
            "rows": [],
            "warnings": [],
            "missing": [],
        }
        corporate_mock.return_value = None
        evidence_mock.return_value = {
            "status": "partial",
            "price_basis": "raw_unadjusted",
            "warnings": [],
            "missing": [],
            "source_refs": [],
            "indicators": {
                "corporate_action": {"coverage_status": "missing"},
                "timeframes": {"daily": {"completed": {}}},
            },
            "swings": {"pivots": []},
            "fibonacci": {"levels": []},
            "anchored_vwap": {},
            "breakout": {},
            "volume_profile": {},
        }

        first = build_tw_stock_price_map(db=self.db, stock_id="2330")
        second = build_tw_stock_price_map(
            db=self.db,
            stock_id="2330",
            candidate_close=191.2,
        )

        self.assertEqual(first["reference"], second["reference"])
        self.assertEqual(second["candidate"]["candidate_close"], 191.0)
        self.assertEqual(report_mock.call_count, 1)
        self.assertEqual(evidence_mock.call_count, 1)
        self.assertEqual(corporate_mock.call_count, 1)

    @patch("app.market.stock_price_map.get_taiwan_stock_event_history")
    @patch("app.market.stock_price_map.build_tw_stock_price_map_evidence")
    @patch("app.market.stock_price_map.build_stock_technical_report")
    def test_projection_keeps_lineage_candidate_semantics_and_low_confidence_profile(
        self,
        report_mock,
        evidence_mock,
        corporate_mock,
    ) -> None:
        report_mock.return_value = {
            "title": "短線偏多",
            "summary": "完成日線結構偏多",
            "score": 4,
            "value": 2.5,
            "value_label": "vs MA20",
            "confidence": "high",
            "rows": [{"key": "trend_structure", "label": "趨勢結構", "display_value": "偏多", "tone": "positive", "description": "test"}],
            "data": {
                "decision_state": {
                    "next_conditions": [
                        {
                            "key": "first_reclaim",
                            "label": "站回 MA5 190，並確認不再破低",
                            "tone": "neutral",
                            "level_key": "ma5",
                            "price": 190,
                        },
                        {
                            "key": "risk_break",
                            "label": "跌破 20 日低點 170，弱勢延續",
                            "tone": "negative",
                            "level_key": "support20",
                            "price": 170,
                        },
                    ]
                }
            },
            "warnings": [],
            "missing": [],
        }
        corporate_mock.return_value = {"cache_status": "current"}
        evidence_mock.return_value = {
            "status": "ready",
            "price_basis": "raw_unadjusted",
            "warnings": [],
            "missing": [],
            "source_refs": [{"type": "resolved_market_data", "name": "tw.daily.ohlcv"}],
            "indicators": {
                "corporate_action": {"coverage_status": "complete", "adjustment_applied": False},
                "timeframes": {"daily": {"completed": {"donchian": {"lower20": 170, "upper20": 200}, "bollinger": {}, "support_resistance": {}}}},
            },
            "swings": {"pivots": []},
            "fibonacci": {"levels": []},
            "anchored_vwap": {},
            "breakout": {},
            "volume_profile": {"status": "ready", "source_granularity": "daily_ohlcv", "confidence": "low", "poc": 185, "val": 180, "vah": 190},
        }

        result = build_tw_stock_price_map(
            db=self.db,
            stock_id="2330",
            candidate_close=191.2,
            now=datetime(2026, 8, 9, 10, tzinfo=TAIWAN_TZ),
        )
        validated = StockPriceMapRead.model_validate(result)

        self.assertEqual(validated.version, "tw.stock.price_map.v3")
        self.assertTrue(validated.decision_usable)
        self.assertTrue(validated.basis_revision.startswith("price-map:"))
        self.assertEqual(validated.evidence_timeframes, ["daily"])
        self.assertEqual(validated.axis.range_kind, "display_range")
        self.assertFalse(validated.axis.is_legal_limit)
        self.assertEqual(
            [tick.percent for tick in validated.axis.ticks],
            [10, 8, 6, 4, 2, 0, -2, -4, -6, -8, -10],
        )
        self.assertEqual(
            [item.kind for item in validated.markers],
            ["completed_reference"],
        )
        self.assertEqual(
            [item.key for item in validated.decision_changes],
            ["first_reclaim", "risk_break"],
        )
        self.assertEqual(validated.decision_changes[0].relation, "at_or_above")
        self.assertEqual(validated.decision_changes[1].relation, "below")
        self.assertEqual(validated.decision_changes[0].threshold_price, 190)
        self.assertEqual(validated.decision_changes[1].threshold_price, 170)
        self.assertTrue(all(item.link_status == "linked" for item in validated.decision_changes))
        self.assertTrue(all(item.zone_id for item in validated.decision_changes))
        linked_trigger_ids = {
            trigger_id
            for zone in validated.zones
            for trigger_id in zone.trigger_ids
        }
        self.assertEqual(linked_trigger_ids, {"first_reclaim", "risk_break"})
        self.assertTrue(all(zone.timeframes == ["daily"] for zone in validated.zones))
        self.assertTrue(all(zone.lower_bound < zone.upper_bound for zone in validated.zones))
        self.assertTrue(
            all(
                zone.evidence_lower_bound <= zone.anchor_price <= zone.evidence_upper_bound
                for zone in validated.zones
            )
        )
        self.assertEqual(validated.candidate.candidate_close, 191.0)
        self.assertEqual([item.period for item in validated.candidate.projections], [5, 20, 60])
        profile_levels = [item for item in validated.levels if item.source_type == "volume_profile_estimate"]
        self.assertTrue(profile_levels)
        self.assertTrue(all(item.confidence == "low" for item in profile_levels))
        self.assertTrue(all("not execution-grade" in " ".join(item.limitations) for item in profile_levels))


class StockPriceMapApiContractTests(unittest.TestCase):
    def test_openapi_exposes_named_price_map_response(self) -> None:
        operation = app.openapi()["paths"]["/api/market/technical/{stock_id}/price-map"]["get"]
        schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
        self.assertEqual(schema["$ref"], "#/components/schemas/StockPriceMapRead")


if __name__ == "__main__":
    unittest.main()
