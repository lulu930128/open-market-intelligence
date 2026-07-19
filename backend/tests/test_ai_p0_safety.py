from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai import ask as ai_ask
from app.ai import ask_stages, decision_core, pipeline_progress, scope_resolution, technical_analysis
from app.ai.schemas import AiAskRequest
from app.ai.schemas import AiAskResponse
from app.db.models import Base, StockMaster


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return Session(engine)


def add_tw_stocks(db: Session) -> None:
    db.add_all(
        [
            StockMaster(
                stock_id="2330",
                stock_name="台積電",
                market="TWSE",
                instrument_type="stock",
                is_active=True,
            ),
            StockMaster(
                stock_id="2380",
                stock_name="虹光",
                market="TWSE",
                instrument_type="stock",
                is_active=True,
            ),
            StockMaster(
                stock_id="2454",
                stock_name="聯發科",
                market="TWSE",
                instrument_type="stock",
                is_active=True,
            ),
        ]
    )
    db.commit()


class AiP0ScopeSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = make_session()
        add_tw_stocks(self.db)

    def tearDown(self) -> None:
        self.db.close()

    def resolve(self, question: str, **updates: object) -> scope_resolution.ScopeResolution:
        payload = AiAskRequest(
            question=question,
            target={"type": "auto"},
            **updates,
        )
        return scope_resolution._resolve_scope(self.db, payload)

    def test_position_cost_is_not_treated_as_stock_id_when_name_is_explicit(self) -> None:
        question = "台積電現在怎麼看？我手上成本 2380，短線要不要先減碼"

        resolution = self.resolve(question)
        position = decision_core.infer_position_context(question)

        self.assertEqual(resolution.selected_scope_id, "2330")
        self.assertEqual(resolution.display_name, "台積電")
        self.assertEqual(position.entry_price, 2380)

    def test_unqualified_numeric_stock_id_still_resolves_normally(self) -> None:
        resolution = self.resolve("2380 最近怎麼樣？")

        self.assertEqual(resolution.selected_scope_id, "2380")
        self.assertEqual(resolution.display_name, "虹光")

    def test_name_and_different_unqualified_stock_id_require_clarification(self) -> None:
        resolution = self.resolve("台積電 2380")

        self.assertTrue(resolution.clarification_required)
        self.assertEqual(resolution.source, "target_conflict")
        self.assertEqual(
            {(candidate.get("target") or {}).get("id") for candidate in resolution.candidates},
            {"2330", "2380"},
        )

    def test_cost_equal_to_another_stock_id_does_not_override_named_stock(self) -> None:
        resolution = self.resolve("成本 2330 的聯發科，短線怎麼看？")

        self.assertEqual(resolution.selected_scope_id, "2454")
        self.assertEqual(resolution.display_name, "聯發科")

    def test_unknown_tw_stock_stops_before_analysis(self) -> None:
        response = ai_ask.ask(
            db=self.db,
            payload=AiAskRequest(
                question="9999 現在可以買嗎？",
                target={"type": "tw_stock", "id": "9999"},
                mode="brief",
            ),
        )

        self.assertFalse(response["ok"])
        self.assertFalse(response["answer_ready"])
        self.assertEqual(response["action"], "omi.ask.reject")
        self.assertEqual(response["error"]["code"], "TARGET_NOT_FOUND")
        self.assertEqual(response["analysis"], {})
        self.assertEqual(response["next_actions"], [])
        self.assertEqual(response["tool_runs"], [])
        validated = AiAskResponse.model_validate(response).model_dump()
        self.assertFalse(validated["ok"])
        self.assertEqual(validated["error"]["code"], "TARGET_NOT_FOUND")

    def test_unknown_auto_target_also_stops_before_analysis(self) -> None:
        response = ai_ask.ask(
            db=self.db,
            payload=AiAskRequest(
                question="查詢不存在的台股 9999 最新價格",
                target={"type": "auto"},
                mode="brief",
            ),
        )

        self.assertFalse(response["ok"])
        self.assertEqual(response["target"]["id"], "9999")
        self.assertEqual(response["error"]["code"], "TARGET_NOT_FOUND")
        self.assertFalse(response["answer_ready"])

    def test_follow_up_inherits_canonical_last_target(self) -> None:
        resolution = self.resolve(
            "那近 5 天分點主要買賣方呢？",
            conversation_context={
                "last_target": {
                    "type": "tw_stock",
                    "id": "2330",
                    "label": "台積電",
                    "market": "TW",
                }
            },
        )

        self.assertEqual(resolution.selected_scope_id, "2330")
        self.assertEqual(resolution.source, "conversation_target")

    def test_follow_up_accepts_legacy_last_resolution_shape(self) -> None:
        resolution = self.resolve(
            "那分點呢？",
            conversation_context={
                "last_resolution": {
                    "target": {
                        "type": "tw_stock",
                        "id": "2330",
                        "label": "台積電",
                        "market": "TW",
                    }
                }
            },
        )

        self.assertEqual(resolution.selected_scope_id, "2330")
        self.assertEqual(resolution.source, "conversation_target")

    def test_explicit_new_name_overrides_last_target(self) -> None:
        resolution = self.resolve(
            "換聯發科呢？",
            conversation_context={
                "last_target": {"type": "tw_stock", "id": "2330", "label": "台積電"}
            },
        )

        self.assertEqual(resolution.selected_scope_id, "2454")
        self.assertEqual(resolution.source, "stock_master_name")

    def test_stock_follow_up_without_context_requests_target(self) -> None:
        resolution = self.resolve("那分點呢？")

        self.assertTrue(resolution.clarification_required)
        self.assertEqual(resolution.selected_scope_type, "stock")

    def test_successful_resolution_exposes_canonical_next_context(self) -> None:
        resolution = self.resolve("台積電最近怎麼樣？")

        next_context = scope_resolution._next_conversation_context(resolution)

        self.assertEqual(next_context["last_target"]["id"], "2330")
        self.assertEqual(next_context["last_target"]["type"], "tw_stock")
        self.assertEqual(next_context["last_resolution"]["target"]["id"], "2330")


class AiP0TechnicalSafetyTests(unittest.TestCase):
    @staticmethod
    def build_levels(*, latest: float, ma5: float, ma20: float, ma60: float, atr: float, upper: float, lower: float) -> dict[str, object]:
        return technical_analysis._technical_price_levels(
            technical_reports={
                "daily": {
                    "score": -3,
                    "title": "短線偏弱",
                    "data": {
                        "daily_indicator": {
                            "close": latest,
                            "ma": {"ma5": ma5, "ma20": ma20, "ma60": ma60},
                            "atr": {"atr14": atr},
                            "donchian": {"upper20": upper, "lower20": lower},
                            "rsi": {"rsi14": 35},
                        }
                    },
                },
                "weekly": {"score": -2, "data": {"daily_indicator": {}}},
            },
            latest_daily={"trade_date": "2026-07-17", "close_price": latest},
        )

    def test_long_levels_never_expose_entry_or_risk_levels_on_wrong_side(self) -> None:
        levels = self.build_levels(
            latest=100,
            ma5=120,
            ma20=115,
            ma60=110,
            atr=10,
            upper=130,
            lower=100,
        )

        for zone in levels["entry"].values():
            if isinstance(zone, dict) and "high" in zone:
                self.assertLessEqual(zone["high"], levels["latest_price"])
        for field in ("short_stop", "technical_invalidation"):
            level = levels["risk"].get(field)
            if isinstance(level, dict):
                self.assertLess(level["price"], levels["latest_price"])
        self.assertGreater(
            levels["entry"]["breakout_confirm_above"]["price"],
            levels["latest_price"],
        )
        self.assertIn("preferred_zone", levels["resistance"])
        self.assertEqual(levels["validation"]["status"], "unavailable")
        self.assertFalse(levels["validation"]["decision_ready"])

    def test_valid_long_levels_remain_decision_ready(self) -> None:
        levels = self.build_levels(
            latest=100,
            ma5=98,
            ma20=95,
            ma60=90,
            atr=4,
            upper=105,
            lower=88,
        )

        self.assertTrue(levels["validation"]["decision_ready"])
        self.assertEqual(levels["validation"]["status"], "ready")
        self.assertLess(levels["risk"]["short_stop"]["price"], levels["latest_price"])
        self.assertLess(levels["risk"]["technical_invalidation"]["price"], levels["latest_price"])

    def test_unavailable_price_levels_block_action_plan_and_answer_readiness(self) -> None:
        levels = self.build_levels(
            latest=100,
            ma5=120,
            ma20=115,
            ma60=110,
            atr=10,
            upper=130,
            lower=100,
        )
        position_builder = Mock(return_value={"action_plan": [{"label": "減碼", "text": "test"}]})
        understanding = SimpleNamespace(as_policy_payload=lambda: {"intent": "position_risk_decision"})

        assembled = ask_stages.assemble_response_analysis(
            result={"warnings": [], "missing": [], "source_refs": []},
            freshness_result={"is_current": True},
            warnings=[],
            resolution=SimpleNamespace(),
            effective_mode="brief",
            policy={},
            requested_mode="brief",
            question_understanding=understanding,
            question_intent="position_risk_decision",
            position_context={"has_position_context": True, "entry_price": 120},
            scope_type="stock",
            response_target={"type": "tw_stock", "id": "2330", "label": "台積電"},
            progress=pipeline_progress.OmiPipelineProgress(lambda event: None),
            extract_list=lambda source, key: source.get(key, []),
            extract_analysis_digest=lambda result, policy: {
                "kind": "stock_analysis_digest",
                "technical_levels": levels,
            },
            clarification_dict=lambda resolution: {},
            build_next_actions=lambda **kwargs: [],
            build_position_decision=position_builder,
            try_attach_position_decision_llm=lambda **kwargs: kwargs["position_decision"],
            build_consumer_human_answer=lambda **kwargs: {"action_plan": [{"label": "進場"}]},
            build_reasoning_steps=lambda **kwargs: [],
            payload=AiAskRequest(question="台積電成本 120，要不要減碼？"),
        )

        self.assertFalse(assembled.answer_ready)
        self.assertIn("technical_price_level_safety", assembled.combined_missing)
        self.assertEqual(assembled.consumer_human_answer["action_plan"], [])
        self.assertEqual(
            assembled.consumer_human_answer["source"],
            "backend_price_level_validator",
        )
        position_builder.assert_not_called()

    def test_long_only_level_model_blocks_short_position_actions(self) -> None:
        levels = self.build_levels(
            latest=100,
            ma5=98,
            ma20=95,
            ma60=90,
            atr=4,
            upper=105,
            lower=88,
        )
        understanding = SimpleNamespace(as_policy_payload=lambda: {"intent": "position_risk_decision"})

        assembled = ask_stages.assemble_response_analysis(
            result={"warnings": [], "missing": [], "source_refs": []},
            freshness_result={"is_current": True},
            warnings=[],
            resolution=SimpleNamespace(),
            effective_mode="brief",
            policy={},
            requested_mode="brief",
            question_understanding=understanding,
            question_intent="position_risk_decision",
            position_context={
                "has_position_context": True,
                "entry_price": 105,
                "position_side": "short",
            },
            scope_type="stock",
            response_target={"type": "tw_stock", "id": "2330", "label": "台積電"},
            progress=pipeline_progress.OmiPipelineProgress(lambda event: None),
            extract_list=lambda source, key: source.get(key, []),
            extract_analysis_digest=lambda result, policy: {
                "kind": "stock_analysis_digest",
                "technical_levels": levels,
            },
            clarification_dict=lambda resolution: {},
            build_next_actions=lambda **kwargs: [],
            build_position_decision=lambda **kwargs: {"action_plan": [{"label": "停損"}]},
            try_attach_position_decision_llm=lambda **kwargs: kwargs["position_decision"],
            build_consumer_human_answer=lambda **kwargs: {"action_plan": [{"label": "停損"}]},
            build_reasoning_steps=lambda **kwargs: [],
            payload=AiAskRequest(question="空單停損怎麼設？"),
        )

        self.assertFalse(assembled.answer_ready)
        self.assertEqual(assembled.consumer_human_answer["action_plan"], [])
        self.assertTrue(any("position side" in warning for warning in assembled.combined_warnings))


if __name__ == "__main__":
    unittest.main()
