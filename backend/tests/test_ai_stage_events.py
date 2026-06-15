from __future__ import annotations

import unittest

from app.ai import stage_events


class AiStageEventsTests(unittest.TestCase):
    def test_initial_status_payloads_are_sequenced(self) -> None:
        payloads = stage_events.initial_status_payloads(contract_version="omi.ai.ask.v2")

        self.assertEqual([payload["stage"] for payload in payloads], ["accepted", "resolving"])
        self.assertEqual([payload["sequence"] for payload in payloads], [1, 2])
        self.assertEqual(payloads[0]["stage_label"], "收到問題")
        self.assertEqual(payloads[0]["contract_version"], "omi.ai.ask.v2")

    def test_tool_status_payload_maps_known_tools(self) -> None:
        payload = stage_events.tool_status_payload(
            {"tool": "tw.refresh_stock_evidence", "status": "success"},
            sequence=3,
        )

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["stage"], "tool_execution")
        self.assertEqual(payload["stage_label"], "工具執行")
        self.assertEqual(payload["tool_label"], "台股資料刷新")
        self.assertIn("已完成", payload["message"])

    def test_progress_status_payload_adds_sequence_and_label(self) -> None:
        payload = stage_events.progress_status_payload(
            {
                "stage": "score_model",
                "message": "已完成五因子評分。",
                "phase": "completed",
                "dedupe_key": "reasoning:score_model:已完成五因子評分。",
                "question_intent": "entry_decision",
            },
            sequence=4,
        )

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["stage"], "score_model")
        self.assertEqual(payload["stage_label"], "五因子評分")
        self.assertEqual(payload["sequence"], 4)
        self.assertEqual(payload["phase"], "completed")
        self.assertEqual(payload["dedupe_key"], "reasoning:score_model:已完成五因子評分。")
        self.assertEqual(payload["question_intent"], "entry_decision")

    def test_response_status_payloads_include_evidence_tools_reasoning_and_ready(self) -> None:
        payloads, next_sequence = stage_events.response_status_payloads(
            {
                "evidence_passport": {
                    "trust_level": "high",
                    "trust_score": 92,
                },
                "tool_runs": [
                    {"tool": "tw.refresh_stock_evidence", "status": "success"},
                    {
                        "tool": "us.refresh_daily_price",
                        "status": "blocked",
                        "error": "External fetch is not allowed.",
                    },
                ],
                "reasoning_steps": [
                    {"stage": "question_understanding", "message": "已理解問題。"},
                    {"stage": "decision_synthesis", "message": "已組合回答。"},
                ],
                "answer_ready": True,
                "report_level": "brief",
            },
            start_sequence=3,
        )

        self.assertEqual(
            [payload["stage"] for payload in payloads],
            [
                "evidence_passport",
                "tool_execution",
                "tool_execution",
                "question_understanding",
                "decision_synthesis",
                "answer_ready",
            ],
        )
        self.assertEqual([payload["sequence"] for payload in payloads], [3, 4, 5, 6, 7, 8])
        self.assertEqual(next_sequence, 9)
        self.assertIn("信任度 high", payloads[0]["message"])
        self.assertIn("未執行", payloads[2]["message"])
        self.assertEqual(payloads[-1]["report_level"], "brief")


if __name__ == "__main__":
    unittest.main()
