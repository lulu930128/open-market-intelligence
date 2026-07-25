# OMI v4 第三輪驗證收斂

## Goal

- 修正第三輪驗證確認的兩個 P0 與五個 P1，使 `omi.decision.v4` 的 capability selection、freshness、quality、fill plan、answer 與 Source Health 對外語意閉環。
- 以 pure contract tests、targeted regression、完整 backend validation 與隔離 runtime 黑箱呼叫證明修正。

## Non-goals

- 不新增市場、provider、Frontend 功能或交易建議能力。
- 不改 public route、contract version、既有 capability id 或 structured `selection.include/exclude` 語意。
- 不 commit、push、重啟 launcher-managed 8400/3000 runtime，除非使用者另行要求。
- 不刪除、重建或覆蓋本機 SQLite。

## Hard constraints

- Backend 繼續擁有 evidence、freshness、query planning、quality、fill plan 與 answer semantics；MCP、Frontend、Kuro 保持 thin consumer。
- `freshness_by_capability` 必須是 additive；既有 `freshness_by_domain` 保留作 domain summary，不再單獨決定 capability usability。
- stale/partial/pending/missing/provider failure 必須可見，不得用 current/ready/0 掩蓋。
- 外部 refresh 必須 bounded；no-new-data cooldown 使用既有 provider event persistence，不新增 DB schema。
- 所有修改與既有 dirty worktree 共存，不回復或覆寫其他既有變更。

## Context

- Repo: `C:\project\Open Market Intelligence`
- Branch: `codex-kr-market-readiness`
- Contract: `omi.decision.v4`
- Related systems: backend AI、Taiwan freshness/source health、repo MCP schema、isolated HTTP runtime。
- 2026-07-25 第三輪黑箱確認：
  - `shareholding_distribution_weekly` stale 會把 current 的 `chips.institutional`、`chips.margin` 一併判 blocked。
  - 自然語言「不要股權分散」無法排除 `ownership.distribution`；structured selection 已能排除。
  - weekly shareholding 缺 release window/no-new-data cooldown。
  - multi-domain answer 只讀 `preferred_zone`，未讀 `aggressive_zone`。
  - stale quote 不具 historical facts policy。
  - Source Health 忽略 `problems_only`。
  - resolved `status_sources_disagree` 仍污染 passport reasons。

## Deliverables

- Additive capability-level freshness projection與 quality authority。
- Capability-level natural-language include/exclude。
- Shareholding release-aware freshness 與持久化 no-new-data cooldown。
- Pullback-zone fallback 與 stale quote historical-facts policy。
- Source Health `problems_only`、`status_filter`、`include_healthy`、`provider` filters。
- Resolved contradiction diagnostics 與 outward reason dedupe。
- HTTP/MCP schema、contract docs 與 regression tests 同步。

## Done criteria

- current institutional/margin 不再受 stale shareholding 污染；fill plan 只規劃真正 stale 且 refresh-eligible 的 capability。
- 「只查法人與融資券，不要股權分散」只選 `chips.institutional`、`chips.margin`，並排除 `ownership.distribution`。
- shareholding 正常發布窗口內為 pending 而非 stale；no-new-data refresh 後顯示 cooldown/next eligible，且不立即重複規劃。
- aggressive pullback zone 能顯示；stale quote 有完整時間/來源時 `facts_usable=true`、`decision_usable=false`。
- Source Health problem filters 不回 healthy rows。
- ready/high-trust response 不再把 resolved contradiction 放入一般 passport reasons；debug evidence 仍可檢查。
- Targeted tests、完整 backend safe validation、隔離 HTTP/MCP representative calls 全部通過。

## Open questions / assumptions

- TDCC 官方說明確認資料代表每週最後一個營業日收盤餘額，但未承諾精確發布時間；本次採保守的次日中午發布窗口，並把 `expected_release_at` 對外顯示，避免週五深夜過早判 stale。
- No-new-data cooldown 預設一小時，透過既有 `provider_event` 記錄，無 migration。
