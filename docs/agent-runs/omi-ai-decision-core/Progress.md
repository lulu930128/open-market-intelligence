# Progress

## Status

- Current phase: planning scaffold
- Last updated: 2026-06-21 20:09 +08:00

## Completed

- Read `$productized-project-workflow` skill and `references/task-doc-templates.md`.
- Read OMI repo-level `AGENTS.md`.
- Confirmed `docs/agent-runs` did not previously exist in this repo.
- Inspected OMI AI-related structure:
  - `backend/app/ai/decision_core.py`
  - `backend/app/ai/decision_engine.py`
  - `backend/app/ai/answer_composer.py`
  - `backend/app/ai/ask.py`
  - `backend/app/ai/ask_execution.py`
  - `backend/app/ai/schemas.py`
  - `backend/app/ai/freshness.py`
  - `backend/app/ai/agentic_tools.py`
  - `backend/app/routers/ai.py`
  - `agents/omi_mcp_server/server.py`
- Inspected representative regression tests:
  - `backend/tests/test_ai_decision_core.py`
  - `backend/tests/test_ai_answer_composer.py`
  - `backend/tests/test_ai_freshness_guard.py`
- Created initial task docs:
  - `docs/agent-runs/omi-ai-decision-core/Prompt.md`
  - `docs/agent-runs/omi-ai-decision-core/Plan.md`
  - `docs/agent-runs/omi-ai-decision-core/Progress.md`
- Added pre-implementation planning references:
  - `docs/agent-runs/omi-ai-decision-core/ContractMap.md`
  - `docs/agent-runs/omi-ai-decision-core/BaselineTestsAndGaps.md`

## Validation evidence

- `rg --files backend/app/ai`: confirmed AI modules are already split into decision, answer, freshness, orchestration, stage, schema, and tool modules.
- `git status --short --untracked-files=all`: before creating task docs, only `agents/omi_mcp_server/README.md` and `agents/omi_mcp_server/server.py` were modified from the previous prompt/tool-policy work.
- `Test-Path docs\agent-runs`: returned `False` before this task; this is the first OMI long-task doc set.
- Static inspection found the downstream Kuro `market_preflight.py` fallback still points to `http://127.0.0.1:8300`; this is recorded as a downstream planning gap and was not changed in this pass.

## Decisions made

- Start with OMI AI decision core before Kuro OMI briefing because OMI owns market reasoning, freshness, tool orchestration, and answer contract.
- Keep this first pass as task documentation and planning scaffold only; do not change AI runtime behavior until the baseline contract and regression map are explicit.
- Treat `backend/app/ai/answer_composer.py` as the primary user-facing wording/structured-answer layer; frontend and MCP should consume, not reconstruct, the decision.
- Treat bounded external refresh as backend-owned OMI behavior through `allow_external_fetch`, `tool_budget`, `refresh_policy`, `tool_plan`, and `tool_runs`.
- Do not run the baseline test subset as part of this documentation-only pass; record the exact commands in `BaselineTestsAndGaps.md` for the first implementation session.

## Known issues / risks

- The repo currently has unrelated-to-this-doc-set modified MCP files from the preceding setup step:
  - `agents/omi_mcp_server/README.md`
  - `agents/omi_mcp_server/server.py`
- Runtime API smoke checks were not run in this planning scaffold; backend liveness on `127.0.0.1:8400` must be verified before runtime-dependent milestones.
- The first implementation milestone may reveal existing test failures unrelated to the decision-core work; those must be isolated before code changes continue.

## Next step

- Begin Milestone 1: run the baseline backend AI test subset, then update `BaselineTestsAndGaps.md` with actual pass/fail results before changing runtime code.
