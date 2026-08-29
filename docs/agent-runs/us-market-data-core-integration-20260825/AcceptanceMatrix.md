# US Market Data Production Convergence Acceptance Matrix

## Status legend

- `passed`：本task有目前checkout可重現證據。
- `partial`：部分資產存在，但未形成完整owner或production path。
- `pending`：尚未實作或尚未驗證。
- `blocked`：有明確外部gate或已重現阻塞。
- `not_applicable`：有具體理由且不影響completion rule。

## A. Planning and baseline

| ID | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| A-01 | 附件只作proposal，已對照current truth | passed | `Prompt.md`、`ArchitectureMap.md` |
| A-02 | Current/target ownership與legacy graph已建立 | passed | `ArchitectureMap.md` |
| A-03 | 長專案work packages、dependencies與stop rules已定義 | passed | `Plan.md`、`WorkBreakdown.md` |
| A-04 | 台股Core handoff不是source-only gate | passed | `CoreHandoffChecklist.md` |
| A-05 | 風險、cutover與rollback規劃已建立 | passed | `RiskRegister.md`、`CutoverRunbook.md` |
| A-06 | Branch/HEAD/dirty baseline已記錄 | passed | `artifacts/A0Baseline.md`、`Progress.md` |

## B. Pre-Core boundary and US-owned preparation

| ID | Requirement | Status | Planned proof |
| --- | --- | --- | --- |
| B-01 | Consumer provider-control architecture guard | passed | `test_us_market_data_architecture_boundaries.py` |
| B-02 | Existing violations有具名legacy allowlist | passed | module/function allowlist + reverse-import debt guard |
| B-03 | Priority OHLC scheduler未接Core前default off/fail closed | passed | config/scheduler/priority tests；external calls=0 |
| B-04 | OHLC continuity/postcondition與provider acquisition解耦 | passed | cache audit只讀coverage；缺口=`shared_core_refresh_unavailable` |
| B-05 | Yahoo/AlphaVantage adapters只做parse/canonical | passed | `market_data/adapters/*` + no-IO import guard |
| B-06 | Candidate persistence/read保持provider coherence且不selection | passed | existing provider-keyed upsert + new all-provider candidate read tests |
| B-07 | Stable US projection只接resolved evidence | passed | `market_data/projection.py` + outward contract tests |
| B-08 | Pre-Core準備不改production truth path | passed | manifest production binding disabled；legacy product path未切 |

## C. Shared Core handoff G0

| ID | Requirement | Status | Planned proof |
| --- | --- | --- | --- |
| C-01 | G0-01至G0-15critical checklist全passed | blocked | 等待台股Core handoff |
| C-02 | TW task `TW_MARKET_DATA_PLATFORM_PRODUCTION_CONVERGED` | blocked | 台股AcceptanceMatrix B-G all passed |
| C-03 | US fake-port compile-only compatibility probe | blocked | final Core contract + US probe tests |
| C-04 | Core version/SHA/runtime identity固定 | blocked | handoff packet |
| C-05 | US binding不import`app.market` | blocked | import graph test after handoff |

## D. Core binding and daily OHLCV

| ID | Requirement | Status | Planned proof |
| --- | --- | --- | --- |
| D-01 | US descriptors/ports/repository/projection正式registration | blocked | B1 integration tests；requires G0 |
| D-02 | Core擁有Yahoo/AlphaVantage planning/fallback | blocked | primary/fallback/both unavailable fixtures |
| D-03 | Daily product read走Resolved Bar Series | blocked | resolved daily/API/research tests |
| D-04 | `cache_only` daily read external calls=0 | blocked | fake/spy port invocation test |
| D-05 | Chart/Research/Ranking/Radar lineage一致 | blocked | cross-consumer snapshot |
| D-06 | Stale/partial/missing/conflict/early-close truthfulness | blocked | scenario matrix |
| D-07 | Bounded multi-symbol read無N+1 regression | blocked | 376/500-symbol performance artifact |

## E. Dataset lifecycle, repair and scheduler

| ID | Requirement | Status | Planned proof |
| --- | --- | --- | --- |
| E-01 | Daily/priority/full-market有complete registry spec | blocked | registry inventory/consistency tests |
| E-02 | RefreshRequirement驅動operation dispatcher | blocked | operation binding tests |
| E-03 | Scheduler不知Yahoo/AlphaVantage | blocked | source guard + job fixture |
| E-04 | Repair success以postcondition reread判定 | blocked | coverage partial/success tests |
| E-05 | Bounds/cursor/dedupe/retry/quota fail closed | blocked | job/scheduler fault tests |
| E-06 | `eod_coverage`不再importUS legacy service | blocked | import graph test |
| E-07 | GET/read不啟動repair或write | blocked | spy port/DB tests |

## F. Quote, intraday and lease

| ID | Requirement | Status | Planned proof |
| --- | --- | --- | --- |
| F-01 | Quote/intraday走Canonical candidates與Resolver | blocked | provider port + resolver tests |
| F-02 | Outward source status provider-neutral | blocked | API/AI projection snapshots |
| F-03 | Premarket/regular/after-hours/early-close語意 | partial | current calendar/projection exists；Core path未切 |
| F-04 | Interval aggregation與partial-bar語意一致 | partial | backend aggregation tests存在；production provider-neutral path未切 |
| F-05 | `require_live`未滿足truthful policy-unmet | blocked | realtime policy tests/runtime smoke |
| F-06 | Viewer/Research/Collector lease各自bounded | blocked | lifecycle/fault-injection tests |
| F-07 | Closed/completed-session不啟動subscription | blocked | session-aware invocation tests |

## G. API, AI, MCP, Frontend and Research

| ID | Requirement | Status | Planned proof |
| --- | --- | --- | --- |
| G-01 | Product API不接受provider acquisition control | pending | OpenAPI/API inventory |
| G-02 | Provider-specific route只作diagnostic/admin | partial | new OHLC repair已移至diagnostic；legacy product selectors仍allowlisted |
| G-03 | AI planner/executor不選provider | pending | AI boundary/query-plan tests |
| G-04 | HTTP/SSE/MCP Decision v4 parity | partial | current contract存在；US Core cutover未驗證 |
| G-05 | Frontend production requests provider selector=0 | passed | frontend request guard + targeted ESLint/typecheck |
| G-06 | Frontend只renderbackend authoritative technical series | pending | golden-series/API/UI parity |
| G-07 | Data Status顯示backend health/freshness/limitations | partial | shared flow存在；US cutover未驗證 |
| G-08 | SEC/FINRA/FRED authority datasets未被錯誤genericize | pending | ownership/import tests |

## H. Rollout and closure

| ID | Requirement | Status | Planned proof |
| --- | --- | --- | --- |
| H-01 | Per-capability off/shadow/compare/canary/on可用 | partial | existing scaffolding；final reusable mode未驗證 |
| H-02 | Mismatch/latency/quota/health telemetry有bound | pending | rollout artifacts |
| H-03 | Daily/repair/intraday/consumer分開canary | pending | dated evidence packets |
| H-04 | Capability-levelrollback rehearsal | pending | rollback artifact |
| H-05 | Official launcher runtime採用target SHA/mode | pending | PID/port/mode/runtime lineage |
| H-06 | API/AI/MCP/UI使用者可見流程通過 | pending | runtime/browser/MCP evidence |
| H-07 | Legacy service fallback/provider selectors/reverse import移除 | pending | source inventory=0 |
| H-08 | Backend/frontend/full validation通過 | pending | safe validation logs |
| H-09 | Current architecture docs同步 | pending | docs diff/readback |

## Completion rule

只有在：

1. B-H所有required rows為`passed`，沒有`blocked`；
2. production graph為`Provider -> Adapter -> Canonical -> Shared Core -> Resolved Evidence -> US Projection -> Consumers`；
3. rollback已rehearsed，且不需destructive DB操作；
4. source-ready、runtime-adopted、provider-live、dataset-ready、consumer-cutover都有各自證據；

才能標記`US_MARKET_DATA_PLATFORM_PRODUCTION_CONVERGED`。

KGI US entitlement或某個planned provider仍不可用，不一定阻擋closure；前提是其capability truthful未advertise，且Yahoo／AlphaVantage或其他已驗證providers能滿足本task明定的production scope。
