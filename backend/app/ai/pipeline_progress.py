from __future__ import annotations

from collections.abc import Callable
from time import perf_counter
from typing import Any, TypeVar

from app.ai import progress_events


ProgressCallback = progress_events.ProgressCallback
T = TypeVar("T")

QUESTION_INTENT_LABELS = {
    "entry_decision": "進場問題",
    "exit_decision": "出場問題",
    "position_risk_decision": "持倉風險問題",
    "risk_check": "風險檢查",
    "trend_view": "走勢解讀",
    "general": "一般問答",
}
ANALYSIS_HORIZON_LABELS = {
    "intraday": "盤中",
    "short": "短線",
    "swing": "中短線",
    "long": "長線",
}
SCOPE_LABELS = {
    "stock": "台股",
    "watchlist": "自選群組",
    "us_stock": "美股",
    "jp_stock": "日股",
    "jp_index": "日股指數",
    "tw_index": "台股指數",
    "tw_futures": "台指期",
    "market": "市場",
}
MODE_READ_MESSAGES = {
    "data_only": "正在整理資料讀取結果。",
    "brief": "正在讀取摘要所需的市場與技術資料。",
    "analysis": "正在組合分析資料並準備 LLM 生成。",
    "report": "正在組合完整報告資料並準備生成。",
}
TOOL_PLANNING_MESSAGES = {
    "stock": "資料 freshness 需要補強，正在規劃台股刷新工具。",
    "watchlist": "自選群組資料需要補強，正在規劃刷新工具。",
    "us_stock": "正在規劃美股資料工具與盤中補強。",
}


class OmiPipelineProgress:
    def __init__(self, callback: ProgressCallback | None) -> None:
        self._callback = callback
        self._started = perf_counter()

    def _elapsed_ms(self) -> int:
        return int((perf_counter() - self._started) * 1000)

    def emit(
        self,
        *,
        stage: str,
        message: str,
        phase: str = "completed",
        dedupe_key: str | None = None,
        **extra: Any,
    ) -> None:
        progress_events.emit_progress(
            self._callback,
            stage=stage,
            message=message,
            phase=phase,
            elapsed_ms=self._elapsed_ms(),
            dedupe_key=dedupe_key or f"{stage}:{phase}:{message}",
            **extra,
        )

    def run_stage(
        self,
        *,
        stage: str,
        dedupe_key: str,
        running_message: str,
        operation: Callable[[], T],
        completed_message: str | Callable[[T], str] | None = None,
        failed_message: str | None = None,
        running_extra: dict[str, Any] | None = None,
        completed_extra: Callable[[T], dict[str, Any]] | None = None,
        failed_extra: dict[str, Any] | None = None,
    ) -> T:
        started = perf_counter()
        self.emit(
            stage=stage,
            message=running_message,
            phase="running",
            dedupe_key=dedupe_key,
            **(running_extra or {}),
        )
        try:
            result = operation()
        except Exception as exc:
            self.emit(
                stage=stage,
                message=failed_message or f"{running_message.rstrip('。')}失敗。",
                phase="failed",
                dedupe_key=f"{dedupe_key}:failed",
                error=str(exc),
                duration_ms=int((perf_counter() - started) * 1000),
                **(failed_extra or {}),
            )
            raise

        if callable(completed_message):
            message = completed_message(result)
        else:
            message = completed_message or running_message
        extra = completed_extra(result) if completed_extra else {}
        self.emit(
            stage=stage,
            message=message,
            phase="completed",
            dedupe_key=f"{dedupe_key}:completed",
            duration_ms=int((perf_counter() - started) * 1000),
            **extra,
        )
        return result

    def question_understood(
        self,
        *,
        question_intent: str,
        effective_horizon: str,
    ) -> None:
        intent_label = QUESTION_INTENT_LABELS.get(question_intent, "一般問答")
        horizon_label = ANALYSIS_HORIZON_LABELS.get(effective_horizon, effective_horizon)
        self.emit(
            stage="question_understanding",
            message=f"已判斷為{intent_label}，採用{horizon_label}視角。",
            dedupe_key="question_understanding:completed",
            question_intent=question_intent,
            analysis_horizon=effective_horizon,
        )

    def clarification_required(self) -> None:
        self.emit(
            stage="decision_synthesis",
            message="OMI 需要先釐清標的，暫停資料推導。",
            dedupe_key="decision_synthesis:clarification",
        )

    def freshness_checked(
        self,
        *,
        scope_type: str,
        freshness_result: dict[str, Any],
    ) -> None:
        self.emit(
            stage="evidence_read",
            message=self._freshness_message(
                scope_type=scope_type,
                freshness_result=freshness_result,
            ),
            dedupe_key="evidence_read:freshness",
            scope_type=scope_type,
            is_current=freshness_result.get("is_current") if freshness_result else None,
            refresh_recommended=freshness_result.get("refresh_recommended") if freshness_result else None,
        )

    def run_freshness_check(
        self,
        *,
        scope_type: str,
        operation: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        scope_label = SCOPE_LABELS.get(scope_type, scope_type)
        return self.run_stage(
            stage="evidence_read",
            dedupe_key="evidence_read:freshness",
            running_message=f"正在檢查{scope_label}資料 freshness。",
            operation=operation,
            completed_message=lambda result: self._freshness_message(
                scope_type=scope_type,
                freshness_result=result,
            ),
            running_extra={"scope_type": scope_type},
            completed_extra=lambda result: {
                "scope_type": scope_type,
                "is_current": result.get("is_current") if result else None,
                "refresh_recommended": result.get("refresh_recommended") if result else None,
            },
            failed_extra={"scope_type": scope_type},
        )

    def _freshness_message(
        self,
        *,
        scope_type: str,
        freshness_result: dict[str, Any],
    ) -> str:
        scope_label = SCOPE_LABELS.get(scope_type, scope_type)
        if not freshness_result:
            return f"已完成{scope_label}資料檢查。"
        if freshness_result.get("refresh_recommended"):
            return f"已完成{scope_label}資料檢查，偵測到需要刷新或補資料。"
        if freshness_result.get("is_current") is False:
            return f"已完成{scope_label}資料檢查，資料仍有缺口。"
        return f"已完成{scope_label}資料檢查，資料可用。"

    def tool_planning(self, *, scope_type: str) -> None:
        self.emit(
            stage="tool_execution",
            message=TOOL_PLANNING_MESSAGES.get(scope_type, "正在規劃資料工具。"),
            phase="running",
            dedupe_key=f"tool_execution:planning:{scope_type}",
            scope_type=scope_type,
        )

    def run_tool_session(
        self,
        *,
        scope_type: str,
        operation: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        return self.run_stage(
            stage="tool_execution",
            dedupe_key=f"tool_execution:planning:{scope_type}",
            running_message=TOOL_PLANNING_MESSAGES.get(scope_type, "正在規劃資料工具。"),
            operation=operation,
            completed_message="已完成工具規劃與執行。",
            running_extra={"scope_type": scope_type},
            completed_extra=lambda result: {
                "scope_type": scope_type,
                "tool_count": len(result.get("tool_runs") or []),
                "warning_count": len(result.get("warnings") or []),
            },
            failed_extra={"scope_type": scope_type},
        )

    def read_mode(self, *, mode: str) -> None:
        self.emit(
            stage="evidence_read",
            message=MODE_READ_MESSAGES.get(mode, "正在讀取 OMI 資料。"),
            phase="running",
            dedupe_key=f"evidence_read:mode:{mode}",
            mode=mode,
        )

    def run_read_mode(
        self,
        *,
        mode: str,
        operation: Callable[[], tuple[str, dict[str, Any]]],
    ) -> tuple[str, dict[str, Any]]:
        return self.run_stage(
            stage="evidence_read",
            dedupe_key=f"evidence_read:mode:{mode}",
            running_message=MODE_READ_MESSAGES.get(mode, "正在讀取 OMI 資料。"),
            operation=operation,
            completed_message="已完成資料讀取與回應素材整理。",
            running_extra={"mode": mode},
            completed_extra=lambda result: {
                "mode": mode,
                "action": result[0],
                "result_kind": result[1].get("kind") if isinstance(result[1], dict) else None,
            },
            failed_extra={"mode": mode},
        )

    def llm_fallback_to_brief(self) -> None:
        self.emit(
            stage="evidence_read",
            message="LLM 分析失敗，改以摘要模式整理資料。",
            phase="running",
            dedupe_key="evidence_read:llm_fallback_to_brief",
            mode="brief",
        )

    def reasoning_steps(self, reasoning_steps: list[dict[str, str]]) -> None:
        for step in reasoning_steps:
            stage = str(step.get("stage") or "").strip()
            message = str(step.get("message") or "").strip()
            if not stage or not message:
                continue
            self.emit(
                stage=stage,
                message=message,
                dedupe_key=f"reasoning:{stage}:{message}",
            )

    def evidence_passport(self, evidence_passport: dict[str, Any]) -> None:
        self.emit(
            stage="evidence_passport",
            message="已建立證據護照並完成可信度檢查。",
            dedupe_key="evidence_passport:completed",
            trust_level=evidence_passport.get("trust_level"),
            trust_score=evidence_passport.get("trust_score"),
        )

    def answer_ready(
        self,
        *,
        answer_ready: bool,
        report_level: str,
    ) -> None:
        self.emit(
            stage="answer_ready",
            message="已完成資料檢查與回應組裝。",
            dedupe_key="answer_ready:completed",
            answer_ready=answer_ready,
            report_level=report_level,
        )
