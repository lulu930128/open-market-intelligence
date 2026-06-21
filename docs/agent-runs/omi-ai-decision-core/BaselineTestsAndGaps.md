# Baseline Tests And Gaps

Last updated: 2026-06-21 20:20 +08:00

本文件列出 OMI AI decision core 開工前應跑的 baseline tests、各測試代表的 contract，以及目前從靜態檢查看到的缺口。此文件不表示測試已全部執行。

## Recommended Baseline Commands

Run from `C:\project\Open Market Intelligence`.

### Minimal AI Contract Set

```powershell
.\.venv\Scripts\python.exe -m unittest `
  backend.tests.test_ai_decision_core `
  backend.tests.test_ai_answer_composer `
  backend.tests.test_ai_freshness_guard `
  backend.tests.test_ai_ask_stages `
  backend.tests.test_omi_mcp_server
```

### Broader AI / Evidence Set

```powershell
.\.venv\Scripts\python.exe -m unittest `
  backend.tests.test_ai_decision_core `
  backend.tests.test_ai_decision_engine `
  backend.tests.test_ai_evidence_builder `
  backend.tests.test_ai_answer_composer `
  backend.tests.test_ai_freshness_guard `
  backend.tests.test_ai_ask_stages `
  backend.tests.test_ai_streaming `
  backend.tests.test_omi_mcp_server
```

### Syntax Safety

```powershell
.\.venv\Scripts\python.exe -m compileall backend\app\ai backend\app\routers
```

### Runtime Smoke Checks

Only run when backend is intentionally running on `127.0.0.1:8400`.

```powershell
Invoke-RestMethod "http://127.0.0.1:8400/api/system/health"
Invoke-RestMethod -Method Post "http://127.0.0.1:8400/api/ai/ask" -ContentType "application/json" -Body '{
  "contract_version": "omi.ai.ask.v2",
  "question": "2330 現在可以買嗎？如果等回檔看哪裡？",
  "target": {"type": "tw_stock", "id": "2330"},
  "mode": "brief",
  "caller_profile": "local_contract_smoke",
  "allow_llm": false,
  "allow_write": false,
  "allow_external_fetch": false
}'
```

## Test Coverage Map

### `backend/tests/test_ai_decision_core.py`

Protects:

- Chinese question intent routing.
- Entry / pullback / chase / risk / position wording.
- Analysis horizon inference.
- Wrapper compatibility through `app.ai.ask`.
- Progress stages such as `question_understanding`, `evidence_read`, `evidence_passport`, `answer_ready`.

Useful gap checks:

- Add more Taiwan-first scenario questions before expanding market-specific logic.
- Add tests for follow-up context from Kuro `last_resolution` if backend starts relying on it more heavily.

### `backend/tests/test_ai_answer_composer.py`

Protects:

- `analysis.human_answer` structure.
- Price-level based entry scenarios.
- `scenarios` and `counter_evidence`.
- Source-health-derived `data_limits`.
- Confidence capping when critical source health has gaps.
- Position decision answer structure.

Useful gap checks:

- Ensure every supported intent has a stable `text` field suitable for Kuro spoken/briefing transformation.
- Ensure stale/cache fallback wording remains visible in both concise and detailed text.

### `backend/tests/test_ai_freshness_guard.py`

Protects:

- Dataset-aware freshness.
- Missing evidence pack detection.
- Stale-first behavior.
- Cached fallback behavior.
- US stock freshness where relevant.

Useful gap checks:

- Verify Taiwan holiday/session behavior against real recent dates before changing date logic.
- Keep expected-date tests deterministic; avoid relying on live provider state.

### `backend/tests/test_omi_mcp_server.py`

Protects:

- MCP `omi.ask` / `omi.ask_stream` payload shape.
- Trust token / policy behavior.
- External fetch defaults and budget behavior.
- Thin adapter behavior.

Useful gap checks:

- Ensure server default backend URL remains aligned to `8400`.
- Ensure MCP never exposes internal tools by default.

### `backend/tests/test_ai_ask_stages.py`

Protects:

- Ask pipeline stage contract.
- Response construction across mode/policy paths.
- Regression against refactor drift in stage modules.

Useful gap checks:

- Add tests when new answer fields are introduced.

## Current Known Gaps From Static Inspection

- Kuro still has an OMI API fallback of `8300` in `market_preflight.py`; this is downstream but affects Kuro OMI briefing startup reliability.
- The OMI decision answer contract is mostly implicit in tests and helper functions. `ContractMap.md` now documents it, but code has no single exported contract object.
- Runtime API smoke checks were not run during planning; test status must be refreshed before implementation.
- External refresh behavior crosses backend policy, MCP defaults, Kuro tool policy, and OMI `agentic_tools.py`; changes must be tested on both OMI and Kuro sides.
- `report` / persisted report behavior must stay separate from non-persistent `analysis`; Kuro default policy should keep `allow_write=false`.

## Open Questions Before Code Changes

- Should OMI add a first-class `analysis.decision_contract` object, or keep using `analysis.human_answer` plus existing metadata?
- Should Kuro consume only `analysis.human_answer.text`, or also consume structured `scenarios`, `counter_evidence`, `data_limits`, and `tool_runs` for task-wall/briefing cards?
- Should OMI expose a small endpoint or static schema file for downstream consumers, or is test-backed documentation enough for the next iteration?

## Baseline Status

- Not executed in this planning pass.
- First implementation session must start by running the minimal AI contract set above and recording results in `Progress.md`.
