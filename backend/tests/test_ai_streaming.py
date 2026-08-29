from __future__ import annotations

import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai import ask as ai_ask
from app.ai import streaming as ai_streaming
from app.ai.schemas import AiAskRequest, AiAskV4Request
from app.db.models import Base
from app.market_data.errors import MarketDataContractError
from app.routers import ai as ai_router


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return Session(engine)


def parse_sse_events(payload: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in payload.strip().split("\n\n"):
        event_name = "message"
        data = "{}"
        for line in block.splitlines():
            if line.startswith("event: "):
                event_name = line.removeprefix("event: ").strip()
            elif line.startswith("data: "):
                data = line.removeprefix("data: ")
        events.append((event_name, json.loads(data)))
    return events


class AiStreamingTests(unittest.TestCase):
    def test_stream_emits_status_evidence_delta_final_and_done(self) -> None:
        db = make_session()
        try:
            payload = AiAskRequest(
                question="2330 近況",
                target={"type": "tw_stock", "id": "2330"},
                mode="brief",
            )
            fake_response = {
                "kind": "ai_ask",
                "contract_version": "omi.ai.ask.v2",
                "question": payload.question,
                "target": {"type": "tw_stock", "id": "2330", "label": "2330 台積電"},
                "mode": {"requested": "brief", "effective": "brief"},
                "action": "omi.generate_stock_brief",
                "strategy_profile": "short_term_momentum",
                "caller_profile": "kuro_readonly",
                "answer_ready": True,
                "report_level": "brief",
                "analysis": {
                    "human_answer": {
                        "text": "結論：短線偏多\n追蹤：2330 台積電",
                    }
                },
                "reasoning_steps": [
                    {"stage": "question_understanding", "message": "已解析為持倉/停損問題。"},
                    {"stage": "position_math", "message": "已計算成本距離與浮動損益。"},
                ],
                "tool_runs": [{"tool": "tw.refresh_stock_evidence", "status": "success"}],
                "result": {},
                "freshness": {"is_current": True},
                "missing": [],
                "warnings": [],
                "source_refs": [{"type": "table", "name": "market_daily_price"}],
                "evidence_passport": {
                    "kind": "evidence_passport",
                    "trust_level": "high",
                    "trust_score": 92,
                },
            }

            with patch.object(ai_streaming.ai_ask, "ask", return_value=fake_response):
                payload_text = "".join(
                    ai_streaming.iter_ask_sse_events(
                        db=db,
                        payload=payload,
                        server_policy=ai_ask.AiAskServerPolicy(),
                    )
                )

            events = parse_sse_events(payload_text)
            event_names = [event_name for event_name, _ in events]
            self.assertEqual(event_names[:2], ["status", "status"])
            self.assertIn("evidence", event_names)
            self.assertIn("tool_run", event_names)
            self.assertIn("delta", event_names)
            self.assertEqual(event_names[-2:], ["final", "done"])
            first_status = events[0][1]
            self.assertEqual(first_status["stage"], "accepted")
            self.assertEqual(first_status["stage_label"], "收到問題")
            self.assertEqual(first_status["sequence"], 1)
            self.assertEqual(events[event_names.index("evidence")][1]["trust_level"], "high")
            tool_event = events[event_names.index("tool_run")][1]
            self.assertEqual(tool_event["tool_label"], "台股資料刷新")
            self.assertEqual(tool_event["signal_key"], "tool:tw.refresh_stock_evidence:default")
            self.assertIn("已完成", tool_event["message"])
            status_stages = [data.get("stage") for name, data in events if name == "status"]
            self.assertIn("evidence_passport", status_stages)
            self.assertIn("tool_execution", status_stages)
            self.assertIn("position_math", status_stages)
            self.assertTrue(
                all(data.get("stage_label") for name, data in events if name == "status")
            )
            self.assertIn("短線偏多", "".join(data["text"] for name, data in events if name == "delta"))
            self.assertEqual(events[-2][1]["action"], "omi.generate_stock_brief")
            self.assertTrue(events[-1][1]["ok"])
        finally:
            engine = db.get_bind()
            db.close()
            engine.dispose()

    def test_stream_converts_ask_errors_to_error_event(self) -> None:
        db = make_session()
        try:
            payload = AiAskRequest(question="watchlist ranking", mode="auto")

            with patch.object(ai_streaming.ai_ask, "ask", side_effect=ValueError("bad target")):
                payload_text = "".join(
                    ai_streaming.iter_ask_sse_events(
                        db=db,
                        payload=payload,
                        server_policy=ai_ask.AiAskServerPolicy(),
                    )
                )

            events = parse_sse_events(payload_text)
            self.assertEqual(events[-2][0], "error")
            self.assertEqual(events[-2][1]["status_code"], 400)
            self.assertEqual(events[-2][1]["kind"], "bad_request")
            self.assertEqual(
                events[-1],
                (
                    "done",
                    {
                        "ok": False,
                        "transport_ok": False,
                        "request_status": "transport_error",
                    },
                ),
            )
        finally:
            engine = db.get_bind()
            db.close()
            engine.dispose()

    def test_market_data_contract_error_is_internal_and_sanitized_across_transports(
        self,
    ) -> None:
        db = make_session()
        raw_message = "candidate bars must share one provider lineage"
        payload = AiAskV4Request(question="2330 近況", mode="auto")
        try:
            with patch.object(
                ai_streaming.ai_ask,
                "ask",
                side_effect=MarketDataContractError(raw_message),
            ):
                payload_text = "".join(
                    ai_streaming.iter_ask_sse_events(
                        db=db,
                        payload=payload,
                        server_policy=ai_ask.AiAskServerPolicy(),
                    )
                )

            events = parse_sse_events(payload_text)
            stream_error = events[-2][1]
            self.assertEqual(stream_error["status_code"], 500)
            self.assertEqual(stream_error["kind"], "market_data_contract_error")
            self.assertEqual(stream_error["code"], "MARKET_DATA_CONTRACT_VIOLATION")
            self.assertTrue(stream_error["request_valid"])
            self.assertNotIn(raw_message, json.dumps(stream_error))

            request = SimpleNamespace(headers={}, client=None)
            with patch.object(
                ai_router.ai_ask,
                "ask",
                side_effect=MarketDataContractError(raw_message),
            ):
                with self.assertRaises(HTTPException) as caught:
                    ai_router.ask_omi(request=request, payload=payload, db=db)

            self.assertEqual(caught.exception.status_code, 500)
            self.assertEqual(
                caught.exception.detail["code"],
                "MARKET_DATA_CONTRACT_VIOLATION",
            )
            self.assertTrue(caught.exception.detail["request_valid"])
            self.assertNotIn(raw_message, json.dumps(caught.exception.detail))
        finally:
            engine = db.get_bind()
            db.close()
            engine.dispose()

    def test_stream_emits_ask_progress_callback_statuses(self) -> None:
        db = make_session()
        try:
            payload = AiAskRequest(
                question="2330 可以買嗎",
                target={"type": "tw_stock", "id": "2330"},
                mode="brief",
            )
            fake_response = {
                "kind": "ai_ask",
                "contract_version": "omi.ai.ask.v2",
                "question": payload.question,
                "target": {"type": "tw_stock", "id": "2330", "label": "2330 台積電"},
                "mode": {"requested": "brief", "effective": "brief"},
                "action": "omi.generate_stock_brief",
                "strategy_profile": "short_term_momentum",
                "caller_profile": "kuro_readonly",
                "answer_ready": True,
                "report_level": "brief",
                "analysis": {"human_answer": {"text": "結論：等待回檔確認。"}},
                "reasoning_steps": [],
                "tool_runs": [],
                "result": {},
                "freshness": {"is_current": True},
                "missing": [],
                "warnings": [],
                "source_refs": [],
                "evidence_passport": {},
            }

            def fake_ask(**kwargs):
                progress_callback = kwargs["progress_callback"]
                progress_callback(
                    {
                        "stage": "score_model",
                        "message": "已完成五因子評分。",
                        "question_intent": "entry_decision",
                    }
                )
                return fake_response

            with patch.object(ai_streaming.ai_ask, "ask", side_effect=fake_ask):
                payload_text = "".join(
                    ai_streaming.iter_ask_sse_events(
                        db=db,
                        payload=payload,
                        server_policy=ai_ask.AiAskServerPolicy(),
                    )
                )

            events = parse_sse_events(payload_text)
            event_names = [event_name for event_name, _ in events]
            score_status_index = next(
                index
                for index, (event_name, data) in enumerate(events)
                if event_name == "status" and data.get("stage") == "score_model"
            )
            self.assertLess(score_status_index, event_names.index("final"))
            score_status = events[score_status_index][1]
            self.assertEqual(score_status["sequence"], 3)
            self.assertEqual(score_status["stage_label"], "五因子評分")
            self.assertEqual(score_status["question_intent"], "entry_decision")
        finally:
            engine = db.get_bind()
            db.close()
            engine.dispose()

    def test_stream_dedupes_statuses_by_dedupe_key_not_stage_only(self) -> None:
        db = make_session()
        try:
            payload = AiAskRequest(
                question="2330 可以買嗎",
                target={"type": "tw_stock", "id": "2330"},
                mode="brief",
            )
            fake_response = {
                "kind": "ai_ask",
                "contract_version": "omi.ai.ask.v2",
                "question": payload.question,
                "target": {"type": "tw_stock", "id": "2330", "label": "2330 台積電"},
                "mode": {"requested": "brief", "effective": "brief"},
                "action": "omi.generate_stock_brief",
                "strategy_profile": "short_term_momentum",
                "caller_profile": "kuro_readonly",
                "answer_ready": True,
                "report_level": "brief",
                "analysis": {"human_answer": {"text": "結論：等待回檔確認。"}},
                "reasoning_steps": [],
                "tool_runs": [],
                "result": {},
                "freshness": {"is_current": True},
                "missing": [],
                "warnings": [],
                "source_refs": [],
                "evidence_passport": {},
            }

            def fake_ask(**kwargs):
                progress_callback = kwargs["progress_callback"]
                progress_callback(
                    {
                        "stage": "evidence_read",
                        "message": "已完成台股資料檢查，資料可用。",
                        "phase": "completed",
                        "dedupe_key": "evidence_read:freshness",
                    }
                )
                progress_callback(
                    {
                        "stage": "evidence_read",
                        "message": "正在讀取摘要所需的市場與技術資料。",
                        "phase": "running",
                        "dedupe_key": "evidence_read:mode:brief",
                    }
                )
                progress_callback(
                    {
                        "stage": "evidence_read",
                        "message": "已完成台股資料檢查，資料可用。",
                        "phase": "completed",
                        "dedupe_key": "evidence_read:freshness",
                    }
                )
                return fake_response

            with patch.object(ai_streaming.ai_ask, "ask", side_effect=fake_ask):
                payload_text = "".join(
                    ai_streaming.iter_ask_sse_events(
                        db=db,
                        payload=payload,
                        server_policy=ai_ask.AiAskServerPolicy(),
                    )
                )

            events = parse_sse_events(payload_text)
            evidence_statuses = [
                data
                for event_name, data in events
                if event_name == "status" and data.get("stage") == "evidence_read"
            ]
            self.assertEqual(
                [status["dedupe_key"] for status in evidence_statuses],
                ["evidence_read:freshness", "evidence_read:mode:brief"],
            )
            self.assertEqual([status["sequence"] for status in evidence_statuses], [3, 4])
        finally:
            engine = db.get_bind()
            db.close()
            engine.dispose()

    def test_extract_answer_text_prefers_llm_report_when_present(self) -> None:
        text = ai_streaming.extract_answer_text(
            {
                "result": {
                    "llm": {
                        "report": {
                            "headline": "資料可信但需留意量能",
                            "key_observations": ["價格站上 MA20"],
                            "interpretation": ["短線結構偏多"],
                            "risks": ["若量縮回落需降評"],
                            "missing_data": [],
                            "next_checks": ["追蹤法人與成交量"],
                            "disclaimer": "僅根據 OMI 證據包。",
                        }
                    }
                }
            }
        )

        self.assertIn("資料可信但需留意量能", text)
        self.assertIn("追蹤法人與成交量", text)

    def test_extract_answer_text_uses_bounded_failure_copy_for_rejection(
        self,
    ) -> None:
        text = ai_streaming.extract_answer_text(
            {
                "ok": False,
                "request_status": "rejected",
                "action": "omi.ask",
                "target": {"label": "世界"},
                "error": {
                    "code": "RESPONSE_BUDGET_TOO_SMALL",
                    "message": "x" * 1_000,
                },
            }
        )

        self.assertIn("OMI 無法完成這次請求", text)
        self.assertNotIn("OMI 已完成", text)
        self.assertLessEqual(len(text), ai_streaming.MAX_FAILURE_DELTA_CHARS)

    def test_extract_answer_text_keeps_completion_fallback_for_success(
        self,
    ) -> None:
        text = ai_streaming.extract_answer_text(
            {
                "ok": True,
                "request_status": "completed",
                "action": "omi.ask",
                "target": {"label": "世界"},
            }
        )

        self.assertEqual(text, "OMI 已完成 omi.ask：世界。")

    def test_stream_preserves_rejected_business_status_without_completion_delta(
        self,
    ) -> None:
        db = make_session()
        rejected = {
            "kind": "omi_decision",
            "contract_version": "omi.decision.v4",
            "ok": False,
            "request_status": "rejected",
            "action": "omi.ask",
            "target": {"type": "tw_stock", "id": "5347", "label": "世界"},
            "answer": {},
            "evidence": {},
            "execution": {},
            "error": {
                "code": "RESPONSE_BUDGET_TOO_SMALL",
                "message": "max_response_bytes is too small.",
            },
        }
        try:
            with patch.object(
                ai_streaming.ai_ask,
                "ask",
                return_value=rejected,
            ):
                payload_text = "".join(
                    ai_streaming.iter_ask_sse_events(
                        db=db,
                        payload=AiAskV4Request(
                            question="用當沖和盤中角度分析目前標的。",
                            target={"type": "tw_stock", "id": "5347"},
                        ),
                        server_policy=ai_ask.AiAskServerPolicy(),
                    )
                )

            events = parse_sse_events(payload_text)
            delta = "".join(
                data["text"]
                for event_name, data in events
                if event_name == "delta"
            )
            self.assertIn("OMI 無法完成這次請求", delta)
            self.assertNotIn("OMI 已完成", delta)
            self.assertEqual(events[-2], ("final", rejected))
            self.assertEqual(
                events[-1],
                (
                    "done",
                    {
                        "ok": False,
                        "transport_ok": True,
                        "request_status": "rejected",
                    },
                ),
            )
        finally:
            engine = db.get_bind()
            db.close()
            engine.dispose()

    def test_extract_answer_text_prefers_consumer_human_answer(self) -> None:
        text = ai_streaming.extract_answer_text(
            {
                "analysis": {
                    "human_answer": {
                        "kind": "consumer_market_answer",
                        "headline": "短線偏多但追高風險偏高",
                        "text": "結論：短線偏多但追高風險偏高\n重點：先看 MA20。",
                    }
                },
                "result": {
                    "llm": {
                        "report": {
                            "headline": "完整長文不應優先",
                            "key_observations": ["這段不應優先出現在串流文字"],
                            "interpretation": [],
                            "risks": [],
                            "missing_data": [],
                            "next_checks": [],
                            "disclaimer": "",
                        }
                    }
                },
            }
        )

        self.assertIn("短線偏多", text)
        self.assertNotIn("完整長文不應優先", text)


if __name__ == "__main__":
    unittest.main()
