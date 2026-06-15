from __future__ import annotations

import unittest

from app.ai import pipeline_progress


class AiPipelineProgressTests(unittest.TestCase):
    def test_run_stage_emits_running_and_completed_events(self) -> None:
        events = []
        progress = pipeline_progress.OmiPipelineProgress(events.append)

        result = progress.run_stage(
            stage="evidence_read",
            dedupe_key="evidence_read:test",
            running_message="正在讀取測試資料。",
            completed_message=lambda value: f"已讀取 {value['count']} 筆測試資料。",
            operation=lambda: {"count": 3},
            running_extra={"mode": "brief"},
            completed_extra=lambda value: {"count": value["count"]},
        )

        self.assertEqual(result, {"count": 3})
        self.assertEqual([event["phase"] for event in events], ["running", "completed"])
        self.assertEqual(events[0]["dedupe_key"], "evidence_read:test")
        self.assertEqual(events[1]["dedupe_key"], "evidence_read:test:completed")
        self.assertEqual(events[1]["count"], 3)
        self.assertIsInstance(events[1]["duration_ms"], int)

    def test_run_stage_emits_failed_event_and_reraises(self) -> None:
        events = []
        progress = pipeline_progress.OmiPipelineProgress(events.append)

        def fail() -> dict:
            raise ValueError("boom")

        with self.assertRaises(ValueError):
            progress.run_stage(
                stage="evidence_read",
                dedupe_key="evidence_read:test",
                running_message="正在讀取測試資料。",
                failed_message="測試資料讀取失敗。",
                operation=fail,
            )

        self.assertEqual([event["phase"] for event in events], ["running", "failed"])
        self.assertEqual(events[1]["dedupe_key"], "evidence_read:test:failed")
        self.assertEqual(events[1]["error"], "boom")
        self.assertIsInstance(events[1]["duration_ms"], int)

    def test_pipeline_progress_emits_structured_stage_events(self) -> None:
        events = []
        progress = pipeline_progress.OmiPipelineProgress(events.append)

        progress.question_understood(
            question_intent="entry_decision",
            effective_horizon="swing",
        )
        progress.freshness_checked(
            scope_type="stock",
            freshness_result={"is_current": False, "refresh_recommended": True},
        )
        progress.read_mode(mode="brief")
        progress.reasoning_steps(
            [{"stage": "score_model", "message": "已用五因子權重重算技術分數。"}]
        )
        progress.evidence_passport({"trust_level": "high", "trust_score": 92})
        progress.answer_ready(answer_ready=True, report_level="brief")

        self.assertEqual(
            [event["stage"] for event in events],
            [
                "question_understanding",
                "evidence_read",
                "evidence_read",
                "score_model",
                "evidence_passport",
                "answer_ready",
            ],
        )
        self.assertEqual(events[0]["phase"], "completed")
        self.assertEqual(events[2]["phase"], "running")
        self.assertEqual(events[3]["dedupe_key"], "reasoning:score_model:已用五因子權重重算技術分數。")
        self.assertEqual(events[-1]["dedupe_key"], "answer_ready:completed")
        self.assertTrue(all(isinstance(event["elapsed_ms"], int) for event in events))

    def test_progress_ignores_invalid_reasoning_steps(self) -> None:
        events = []
        progress = pipeline_progress.OmiPipelineProgress(events.append)

        progress.reasoning_steps(
            [
                {"stage": "score_model", "message": ""},
                {"stage": "", "message": "missing stage"},
                {"stage": "price_levels", "message": "已推導價位。"},
            ]
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["stage"], "price_levels")


if __name__ == "__main__":
    unittest.main()
