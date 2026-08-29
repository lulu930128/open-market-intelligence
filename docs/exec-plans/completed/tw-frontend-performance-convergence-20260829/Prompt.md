# TW Frontend Performance Convergence

## Goal

- 讓台股首頁、dashboard 與個股頁的高頻資料更新保持可操作，並消除已重現的 cache-only summary read 放大問題。
- 讓高頻市場資料只更新實際消費它的 UI surface，不重新 render 大型 dashboard／detail orchestration tree。
- 讓今日走勢與日 K viewer 維持 cache-first、read-only，不等待或自動觸發 provider acquisition／repair。
- 清除 intraday candidate read 的 raw receipt body hydration，並讓 previous close 由 backend completed-session evidence 獨立投影。
- 收斂 SSR/client duplicate load、日 K 初始讀取量與 OHLC／indicator 串行延遲。
- 讓 today／daily／indicator presentation state 具備明確 stock identity，切換股票時舊資料不可再被新 selection 消費。

## Non-goals

- 不改變 provider selection、Resolver、freshness、market session、official release 或 outward payload semantics。
- 不處理 US／JP／KR／Crypto UI 重構，不做視覺改版、chart library 更換或 i18n bundle 改造。
- 不執行 provider refresh、backfill、production DB migration adoption、runtime restart、commit 或 push。
- 不把原始 checkout 的 provider-lineage／Shared Core dirty diff 整批帶入本 worktree。

## Hard constraints

- `GET /api/market/indices/summary` 保持 cache-only，不新增 external IO 或隱性 repair。
- 所有 frontend mount、polling、selection 與 timeframe read path 都不得自動 POST refresh／backfill。
- Frontend 不建立 provider／freshness／fallback／session truth。
- `previous_close` 不得依賴 current trade freshness／research usability；Unknown 仍為 null，不轉成 0。
- 保留 route、API response、selection、watchlist、chart、quote depth 與 data-status compatibility。
- 所有修改只存在於 `codex/tw-frontend-performance-convergence` worktree，不帶入原始 US/backend dirty worktree。

## Context

- Repo: `C:\project\Open Market Intelligence-tw-frontend-performance`
- Baseline: `f8085f5ef607b1cda4196dc863b652918f86b5fc`
- Runtime evidence on 2026-08-29: health endpoints were fast, while `/api/market/indices/summary` took 12.9-15.5 seconds and `/` took 15.8 seconds.
- Query evidence: breadth reads hydrated full `RawFetchResult.raw_text`; one completed-session breadth projection duplicated roughly 250 MB TWSE plus 304 MB TPEX receipt text through joined rows.
- Frontend evidence: 500 ms quote stream state is owned by `StockDetailPanel`; TW tape/ranking state is owned by `MarketDashboardClient`; initial server summary is immediately fetched again after hydration.
- Round 2 evidence: intraday repository still selects full `RawFetchResult`; 4.75-second projection TTL conflicts with 5-second polling; today/daily/data-panel viewers still contain automatic command paths; daily initial load requests 2,600 bars and re-fetches SSR data.
- Current formal runtime is owned by the original dirty checkout, not this isolated worktree. A parallel provider-lineage guard currently makes representative daily OHLC requests return HTTP 400; that dependency remains an integration gate and will not be patched around in the frontend.

## Deliverables

- Narrow RawFetchResult lineage projections with regression tests proving raw receipt bodies are not selected.
- No redundant immediate TW summary request when valid server initial data exists.
- Surface-owned realtime quote state and smaller render boundary.
- Bounded SSE reconnect/fallback and visibility-aware polling cleanup.
- Intraday lineage-only raw receipt projection with emitted-SQL regression.
- Additive intraday composite read-index migration source; production DB adoption remains separately gated.
- Backend-owned canonical previous-close projection independent of current quote usability.
- Pure-read chart/data-panel lifecycle with explicit-only refresh commands.
- Bounded daily chart initial depth, SSR reuse and parallel OHLC/indicator loading.
- Instrument-scoped today／daily state envelope、current-only selectors、SSR identity preservation 與 response identity rejection。
- Targeted backend/frontend tests plus isolated runtime/API/browser acceptance evidence.

## Done criteria

- Representative summary response remains contract-compatible and cache-only.
- Summary latency is materially lower on the same local DB without changing data semantics.
- 500 ms quote stream state no longer belongs to `StockDetailPanel`.
- SSE/fallback maintains at most one active stream/timer, retries SSE with a bounded backoff, and does not issue hidden-tab fallback requests.
- Intraday candidate SELECT joins lineage without selecting `raw_text`; normal 5-second viewer polling does not miss the projection cache every cycle.
- Opening a stock, changing timeframe or switching data tabs issues no automatic refresh/backfill POST.
- A completed prior-session canonical daily close remains available when current quote evidence is stale or missing.
- Initial daily chart loading does not request 2,600 bars, does not serialize OHLC then indicators, and does not immediately duplicate valid SSR data.
- 已載入 A 股票後切換 B 股票時，A 的 today／daily／indicator／header／technical presentation 不得在 B 的 pending 或 error 狀態出現。
- Intraday／OHLC response identity 不符 request stock/timeframe 時不得 adopt；SSR initial payload 不得由目前 selection 反推 identity。
- Frontend lint, TypeScript, production build, targeted backend tests and relevant browser checks pass.

## Assumptions

- The isolated worktree may reuse installed dependencies and the existing local DB read-only for validation, but it must not adopt or restart the user runtime without separate evidence and authority.

## Closure authorization

- 2026-08-29：使用者明確要求將本 worktree 提交並合併回本機 `main`，完成後移除 worktree；這項後續授權取代原始 non-goal 中的 commit 限制，但不包含 push、production DB migration adoption 或正式 runtime restart。
