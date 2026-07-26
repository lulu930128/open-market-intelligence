# Plan

## Milestones

1. Capability-level freshness
   - Scope: Taiwan compact evidence、canonical envelope、data quality、manifest/fill plan。
   - Acceptance: institutional/margin current；ownership stale/pending；domain stale 不污染 sibling capabilities。
   - Validation: focused projection、quality、fill-plan tests。

2. Capability-level query selection
   - Scope: Query Plan natural-language hints、selection normalization、diagnostics。
   - Acceptance: specific chips hints 只選對應 capability；negation 優先；structured selection 相容。
   - Validation: focused query-plan tests與 pure probe。

3. Release/cooldown 與 answer policy
   - Scope: Taiwan weekly release window、provider-event cooldown、pullback zone、stale quote facts。
   - Acceptance: pending window、不重複 refresh、answer 顯示 aggressive zone、stale quote facts 可用但不可決策。
   - Validation: Taiwan rules/freshness/tool/answer/quality tests。

4. Source Health 與 contradiction cleanup
   - Scope: problem/status/provider filters、MCP schema、resolved contradiction diagnostics、passport dedupe。
   - Acceptance: problem-only rows純淨；ready/high-trust passport 無 resolved noise；debug detail保留。
   - Validation: Source Health、MCP schema、decision-envelope tests。

5. End-to-end validation
   - Scope: targeted suite、safe backend profile、isolated HTTP/MCP。
   - Acceptance: regression 全綠、代表 business calls符合驗收、隔離 runtime graceful shutdown。
   - Validation: `scripts/run-safe-validation.ps1 -Profile backend` 加隔離 runtime probes。

6. Final review closeout
   - Scope: provider failure filtering、pending release refresh、stale fact provenance、best-effort telemetry transaction ownership。
   - Acceptance: Source Health不隱藏 shared failure statuses；空資料仍可 refresh；stale facts需完整 timestamp/provider/source；telemetry failure不污染 caller session。
   - Validation: negative fixtures、完整 backend regression、隔離 HTTP business smoke。

## Stop-and-fix rules

- 任一 milestone 的 targeted test 失敗時先修正，不帶著紅測試進下一批。
- 若 additive 欄位造成 v4 public schema、MCP 或既有 consumer breaking change，先保留 alias/fallback。
- 若 cooldown 需要 DB migration、昂貴外部 refresh 或會污染既有資料，停止並改用既有持久化 primitive。
- 若隔離 runtime 與 launcher runtime 不同，不把隔離結果描述成已部署 8400。

## Decisions

- 2026-07-25：`freshness_by_capability` additive，`freshness_by_domain` 保留總覽。
- 2026-07-25：structured selection 為 caller authority；自然語言 capability hints 只補未明確指定的 request。
- 2026-07-25：resolved status contradictions 留在 capability diagnostics，不進一般 issues/passport reasons。
- 2026-07-25：TDCC weekly release window採次日 12:00 Asia/Taipei；no-new-data cooldown一小時並用 provider event持久化。
- 2026-07-25：best-effort provider telemetry改用獨立 short-lived session；commit failure只 rollback telemetry session並保留 caller transaction。
