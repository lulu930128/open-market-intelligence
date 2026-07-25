# Plan

## Milestones

1. 建立驗收基線與 invariant matrix
   - Scope：v4 request/response、diagnostic scopes、market contexts、runtime。
   - Acceptance：每個納入問題都有 owner、root-cause cluster、reproduction 與
     regression 位置；deferred IDs 不進修改。
   - Validation：focused pytest collection、bounded live read probes。

2. 建立 canonical data-quality contract
   - Scope：`backend/app/ai/` pure contract 與 v4 envelope。
   - Acceptance：availability、freshness、completeness、realtime、continuity、
     release phase、unit 與 decision usability 只計算一次；manifest、slots 與
     readiness 引用同一結果。
   - Validation：pure invariant tests、v3/v4 compatibility tests。

3. 隔離診斷意圖與收斂 outward projection
   - Scope：scope resolution、selection、finalizer、capability/source health。
   - Acceptance：`capability_status`、`data_freshness`、`source_health` 不繼承
     market/chips capability，也不產生投資決策；v4 能選取實際診斷資料。
   - Validation：HTTP pipeline、MCP business-result、payload projection tests。

4. 實作 fusion gate 與資料語意
   - Scope：market-context observation metadata、跨模組合成、confidence/readiness。
   - Acceptance：跨交易日、單位不明、release phase 不相容、continuity 不足時
     明確 partial/blocked，且不產生高強度價位或評分。
   - Validation：TW/JP/KR focused fixtures 與 outward invariant tests。

5. 補齊 observability 與市場 capability
   - Scope：source-health snapshot/event aggregation、provider failures、TW
     trade-value/TPEX、JP/KR data status。
   - Acceptance：沒有資料時回明確 capability gap；有資料時全域 diagnostics
     可查；refresh result 區分 request success 與 newer-data acquired。
   - Validation：source-health/provider-event/service/API tests，加 bounded provider
     probes（若需要）。

6. 收斂 compact payload 與 consumer 呈現
   - Scope：payload limits、locale/number/null formatting、Frontend/MCP thin
     projection。
   - Acceptance：compact 不帶未選取大包；limit 有效；繁中輸出與 missing
     presentation 一致；舊 consumer 可安全忽略新增欄位。
   - Validation：MCP tests、frontend lint/typecheck、必要 Playwright。

7. 完整回歸與 runtime 驗收
   - Scope：backend/frontend、HTTP/SSE/MCP、launcher-selected runtime。
   - Acceptance：targeted 與 full regression 通過，代表性問題在正式 runtime
     有 request/response 證據。
   - Validation：`run-safe-validation.ps1`、bounded business probes。

## Stop-and-fix rules

- 任一 canonical invariant 測試失敗，先修正再進入市場 provider 工作。
- 若修正需要改動 deferred ID 的 universe、TAIEX 序列、ADR 公式、fallback
  故障注入或 threshold，停止並記錄，不越界。
- 若 provider 不提供所需資料，回傳 `not_applicable`、`provider_unavailable`
  或 capability gap，不以合成值冒充正式資料。
- 若需要 migration，先完成 model/migration contract 與 round-trip test。
- 若需要付費或稀缺 quota，先定義單次 cost/call bound。
- 每個 milestone 完成後更新 `Progress.md`。

## Decisions

- 2026-07-24：以 canonical quality/fusion gate 處理共同根因，不建立 81 個獨立
  patch。
- 2026-07-24：v4 additive 演進；v2/v3 compatibility 保留。
- 2026-07-24：診斷 scopes 是 operations/evidence request，不是 decision
  synthesis。
- 2026-07-24：七個 milestone 均已完成；最終證據與 provider 限制記錄於
  `Progress.md`、`AcceptanceMatrix.md`。
