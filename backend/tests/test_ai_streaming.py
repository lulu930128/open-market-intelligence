from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai import ask as ai_ask
from app.ai import streaming as ai_streaming
from app.ai.schemas import AiAskRequest
from app.db.models import Base


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
            self.assertEqual(events[event_names.index("evidence")][1]["trust_level"], "high")
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
            self.assertEqual(events[-1], ("done", {"ok": False}))
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


if __name__ == "__main__":
    unittest.main()
