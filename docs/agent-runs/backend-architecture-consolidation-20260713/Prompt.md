# OMI Backend Architecture Consolidation Program

## Goal

- 在不改變 OMI 產品定位、public API、資料可信度與本機資料安全的前提下，完成一輪可長期維護的 backend 架構整頓。
- 將外部 provider IO、market domain service、transaction ownership、AI answer composition、AI tool projection、router/API 與 DB model 邊界整理成可辨識、可獨立測試、可分批提交的結構。
- 降低大型 module 的責任耦合、循環 import、patch seam 漂移與跨市場 contract drift，而不是單純追求減少行數。
- 建立後續 agent 可以中斷、續跑、驗證與安全回退的任務文件與 commit 節奏。

## Program outcomes

完成後應具備：

- 台股核心資料取得與 index 計算分層，provider request 統一遵循 OMI provider HTTP contract。
- US/JP/KR/crypto/resource market service 有清楚 façade，query、projection、refresh、transaction 與 chart/intraday 責任可辨識。
- AI answer composer 將 localization、data limits、decision evidence 與 watchlist formatting 等 pure logic 分離，但 consumer contract 不變。
- AI tools 將 tool execution 與各市場 context projection 分開，`market_payload_contract.py` 繼續是 slot/payload-level 真相來源。
- Router 只負責 HTTP contract 與 service dispatch，不重做市場邏輯。
- DB model 是否拆分由 import/migration 證據決定，不因檔案大就強制改動。
- 每個重要邊界有 targeted regression、完整 backend regression 與架構文件證據。

## Non-goals

- 不改變「台股核心、其他市場為 context layer」的產品定位。
- 不新增自動下單、交易執行、保證漲跌或自動交易能力。
- 不重新設計 frontend；frontend 只做必要的 contract compatibility 驗證。
- 不在 MCP、Kuro 或 frontend 複製 backend 市場邏輯、freshness 或 provider fallback。
- 不做大範圍 dependency upgrade、framework migration、format-only rewrite 或目錄全面改名。
- 不刪除、重建或覆蓋 `data/open_market_intelligence.db`。
- 不在沒有獨立核准與 migration 計畫時修改 DB schema。
- 不預設執行 live provider、大量 backfill、付費 quota、報告發送或 AI memory 寫入。
- 不以「每個檔案低於某個行數」作為完成標準。

## Hard constraints

### Product and market constraints

- 台股永遠是主要市場；Batch 排序優先處理台股核心資料與 decision support 基礎設施。
- `stale`、`partial`、`missing`、`best-effort`、`rate_limited` 與 provider failure 必須保留可見性。
- AI 回答仍須保留 evidence、情境、回測區、進場條件、失效條件、風險、反證與資料限制。
- OMI 只提供研究與決策輔助，不執行交易。

### Architecture constraints

- Backend 是市場資料、freshness、provider policy、AI reasoning、tool orchestration 與 answer contract 的真相來源。
- 依賴方向遵循 `docs/architecture/BackendArchitecture.md`：router -> service -> provider/parser -> provider_http/http_client。
- Provider adapter 不讀寫 DB；parser 不持有 SQLAlchemy `Session`；projection module 不啟動 refresh 或呼叫 LLM。
- `backend/app/observability/provider_http.py` 是 provider request context、timeout 與 error classification 的唯一共用 contract。
- `backend/app/ai/market_payload_contract.py` 是 slot/payload-level 共用 contract。
- 新 module 必須對應真實責任邊界；不得只把大型檔案機械切成多個相互 import 的碎片。

### Compatibility constraints

- Public route path、HTTP method、query parameter、response model 與 response shape 預設不變。
- `analysis.human_answer`、`analysis.decision_contract`、`result.data.slots`、`result.data.compact.slots` 保持相容。
- 既有 service、provider、parser 與測試 patch seam 在搬移期間以 façade、wrapper 或 re-export 保護。
- 任何 breaking cleanup 必須獨立列出 deprecation、consumer inventory 與 migration plan，不得混入架構搬移 commit。

### Data and transaction constraints

- Query/read helper 預設不 commit；寫入與 refresh function 必須有明確 transaction owner。
- Composite refresh 必須隔離單一 provider/symbol failure，不得提交半套資料。
- Provider event 或 source-health snapshot 寫入失敗不得污染主要 market-data transaction。
- 不 silent drop、filter、merge mismatch 或吞掉 provider exception；跳過資料必須可回報原因。
- DB schema 變更只能透過 Alembic migration，且需要獨立驗證與回滾說明。

### Execution constraints

- 一次只處理一個主要責任邊界；每個 milestone 可再拆成多個 commit。
- 每次修改前先重新檢查 worktree、目前 branch、最新 tests 與實際 import/call chain。
- Targeted regression 失敗時立即 stop-and-fix，不得累積到完整測試才處理。
- 完整 backend regression 通過後才可標記 milestone 完成。
- 不自動 push；commit 與 push 依使用者明確要求執行。

## Context

- Repo: `C:\project\Open Market Intelligence`
- Branch at planning baseline: `codex-kr-market-readiness`
- Baseline commit: `910a1caf3c88e6aeee217a03067dc3efddb8b827`
- Baseline commit subject: `refactor: align market provider adapter boundaries`
- Baseline full backend validation: `547 passed, 1 warning`
- Existing warning: Python 3.12 SQLite datetime adapter deprecation from SQLAlchemy test execution.
- Durable architecture reference: `docs/architecture/BackendArchitecture.md`
- Historical scan and completed Batches 0-5: `docs/agent-runs/backend-optimization-scan-20260711/`

Completed foundations before this program:

- Runtime lifecycle moved to a coordinator boundary.
- AI market payload helpers consolidated.
- US/JP/KR market-family router helpers introduced.
- Shared provider HTTP and source-health contracts introduced.
- JP source-health parity added.
- US/JP/KR provider IO moved into explicit provider adapters with compatibility wrappers.

Current largest backend hotspots at planning time:

| Module | Approx. lines | Main mixed responsibilities |
| --- | ---: | --- |
| `backend/app/ai/answer_composer.py` | 4116 | localization, data limits, decision evidence, answer orchestration, watchlist/digest formatting |
| `backend/app/us_market/service.py` | 3388 | stock master, watchlist, refresh, fundamentals, resources, charts, intraday |
| `backend/app/ai/tools.py` | 3377 | tool registry, Taiwan context reads, compact projections, freshness, slots |
| `backend/app/db/models.py` | 3158 | all ORM domains in one registry |
| `backend/app/ai/agentic_tools.py` | 3101 | planning, execution, budget, progress, cross-market projections |
| `backend/app/market/indices.py` | 2934 | provider IO, parser, cache, DB coverage, breadth, index calculation |
| `backend/app/jp_market/service.py` | 2804 | stock/watchlist/refresh/resources/OHLC/intraday |
| `backend/app/crypto_market/service.py` | 2709 | REST/realtime/resource aggregation and persistence |
| `backend/app/kr_market/service.py` | 2692 | stock/watchlist/index/refresh/resources/OHLC/intraday |
| `backend/app/routers/market.py` | 1974 | Taiwan market route families |

## In scope

- Taiwan index/provider boundary and provider observability.
- US/JP/KR market-service façade decomposition.
- Crypto/resource-market responsibility audit and bounded extraction.
- Transaction ownership inventory and enforcement.
- AI answer-composer pure module extraction.
- AI tool execution versus market-context projection separation.
- Router regrouping after service boundaries are stable.
- Conditional DB model split feasibility and import/migration contract.
- Architecture, compatibility, transaction and validation documentation.

## Deliverables

- `Prompt.md`, `Plan.md`, `Progress.md` maintained throughout the program.
- `ArchitectureMap.md`: current and target dependency map, module ownership and allowed import direction.
- `CompatibilityMatrix.md`: public routes, service imports, patch seams, AI payload contracts and deprecation decisions.
- `TransactionOwnership.md`: function families that query, mutate, commit, rollback or write observability state.
- Provider adapter modules for remaining Taiwan index external IO.
- Stable market service façades with responsibility-specific internal modules.
- Pure AI answer/projection modules with façade compatibility.
- Focused regression tests for each extracted boundary.
- Updated `docs/architecture/BackendArchitecture.md` after each durable decision.
- Per-milestone commit history and final validation evidence.

## Done criteria

### Functional compatibility

- Existing public backend routes and API schemas remain backward-compatible unless a separately approved migration says otherwise.
- Existing AI consumer contracts remain backward-compatible.
- Existing refresh fallback order, freshness semantics, source-health status and provider warnings remain visible.
- Watchlist, stock/index lookup, chart, intraday, resource summary and AI ask workflows pass regression.

### Architecture quality

- External provider HTTP lives behind explicit provider adapters or documented stateful transport boundaries.
- Large service façades expose coherent public entrypoints while internal modules own one responsibility group each.
- Transaction ownership is documented and testable for write/refresh paths.
- AI composition and projection modules are pure where designed and do not acquire hidden DB/network/LLM side effects.
- No new circular imports, import-time background work or duplicate market logic is introduced.

### Validation quality

- Every milestone has targeted tests and `git diff --check` evidence.
- Every cross-module milestone passes `scripts/run-safe-validation.ps1 -Profile backend`.
- Final backend suite passes from a clean worktree.
- Runtime/API smoke uses launcher-selected URLs and confirms representative Taiwan, US, JP, KR, crypto/resource and AI endpoints without destructive refresh.
- Frontend lint/typecheck is only required if a backend contract change touches generated/frontend types or visible integration behavior.

### Operational quality

- Work is split into reviewable commits with one main architecture purpose per commit.
- `Progress.md` records current phase, last good commit, validation logs, known risks and exact next step.
- No secrets, local DB, `.env`, logs, caches, `.tmp`, `.venv`, `node_modules` or build artifacts are committed.
- Deferred high-risk work is documented rather than partially implemented.

## Open questions / assumptions

- Assumption: public API and DB schema remain stable throughout the main program.
- Assumption: compatibility wrappers may remain after the program if removing them creates more consumer risk than maintenance value.
- Assumption: exact human-answer wording is a compatibility surface where tests already assert behavior; refactors must use characterization tests.
- Open question for the DB milestone: whether splitting `models.py` provides enough maintenance value to justify Declarative metadata, relationship and migration risk.
- Open question for live verification: which provider endpoints may be called without quota or account impact; default remains mocked/bounded validation.
