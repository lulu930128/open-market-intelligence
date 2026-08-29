# Plan

## Milestones

1. Round 2 baseline and integration gate
   - Scope: worktree identity, current task diff, owner map and provider-lineage compatibility.
   - Acceptance: Round 2 target files do not overlap unrelated work; original dirty checkout is not imported; OHLC 400 remains an explicit integration gate until stable canonical truth exists.
   - Validation: `git status --short --branch`, target-file diff audit, read-only source/runtime comparison.

2. Backend cache-only read amplification
   - Scope: Taiwan intraday candidate repository, bounded composite read index and focused emitted-SQL tests, retaining the completed Round 1 current/official repository fixes.
   - Acceptance: lineage metadata remains identical while `RawFetchResult.raw_text` is absent from emitted SELECT statements; migration creates and removes the composite index without touching data.
   - Validation: targeted intraday/current-market/official-breadth and migration tests plus local read-only latency/query-plan probe.

3. Intraday projection and previous-close contract
   - Scope: projection cache TTL and completed-session daily evidence projection.
   - Acceptance: normal 5-second polling obtains real cache hits; previous close remains available when current quote is stale/missing and prior canonical daily exists.
   - Validation: cache timing unit tests and fresh/stale/missing previous-close matrix.

4. Pure-read viewer lifecycle
   - Scope: today trend, daily chart backfill and data-panel automatic refresh paths.
   - Acceptance: mount/polling/selection/timeframe changes issue GET only; refresh/backfill remains explicit user action.
   - Validation: source negative assertions and focused browser network evidence.

5. Daily chart critical path
   - Scope: initial bar depth, SSR reuse, concurrent OHLC/indicator reads, stale-response rejection and cross-symbol presentation state ownership.
   - Acceptance: initial daily load is bounded, valid SSR data is not immediately re-read, OHLC/indicators start concurrently, stock-info resolution does not retrigger the chart, and already-loaded old-symbol state is invisible immediately after selection changes.
   - Validation: ESLint, TypeScript, production build, response-identity mismatch regression, loaded-state today/daily rapid-switch and browser network timing.

6. Render and transport ownership
   - Scope: retained Round 1 summary/quote-depth/SSE work plus tape/ranking/radar profiler evidence.
   - Acceptance: high-frequency child state does not drive unrelated dashboard/detail commits; only evidence-backed surface splits are added.
   - Validation: focused browser lifecycle checks and React render instrumentation where available.

7. Product acceptance
   - Scope: isolated API latency, homepage, dashboard idle, stock detail, stock switching, hidden tab and after-close semantics.
   - Acceptance: no automatic POST, no blocking regression, truthful status semantics and material latency/request-count improvement.
   - Validation: safe validation profiles, task-owned runtime/browser probes and final diff audit.

## Stop-and-fix rules

- 若任何 GET 觸發 provider IO、refresh、repair 或 DB mutation，立即停止並修正。
- 若 outward payload、freshness、official finalization 或 selection reason 改變，視為 boundary regression，先回復相容性。
- 若 render split 造成 selection、chart、watchlist 或 data-status reset，先修正再進入 lifecycle milestone。
- 若 isolated validation 需要破壞性 DB 操作、外部 quota 或正式 runtime restart，停止並另行取得授權。
- 若 provider-lineage compatibility 只能依賴原始 checkout 的未穩定 dirty diff，保留為 integration blocker，不複製或猜測修補。

## Decisions

- 2026-08-29：從 `f8085f5` 建立獨立 branch/worktree，避免 US／Shared Market Data dirty changes 污染。
- 2026-08-29：backend read amplification 是 user-visible blocker，但保持為 owner-correct 的 repository optimization，不在 frontend 建第二套 cache truth。
- 2026-08-29：Round 2 將 viewer automatic repair 視為 architecture violation；保留 manual command，但所有自動 lifecycle 只讀 canonical cache。
- 2026-08-29：previous close 使用 completed-session canonical daily evidence，與 current trade availability 分離。
- 2026-08-29：today 與 daily/indicator 使用 instrument-scoped atomic envelope；consumer 只讀目前 selection，SSR 與 API response identity 必須明確驗證，不以清空 effect 作 correctness boundary。
- 2026-08-29：31 GB production DB 的 intraday cold read 仍被單欄 `interval` index 與 temporary sort 主導；新增 additive composite-index migration source `20260829_0073t`，避開平行 US workline 的未提交 `0073`，本輪不套用正式 DB。
