# Plan

## Milestones

1. Stage 0：保護現況與建立可信 fixtures
   - Scope: task docs、legacy schema/service regression、最小化 SEC fixtures、AI projection gap regression inventory。
   - Acceptance: parser 可保存同一 period end 的 discrete/YTD facts；legacy fundamentals shape 固定；不同 accession revisions 同時存在。
   - Validation: `python -m pytest backend/tests/test_us_sec_fundamental_engine.py backend/tests/test_us_market_data.py -q`

2. Stage 1：Period／Unit／Canonical Core
   - Scope: `backend/app/us_market/sec_fundamentals/` pure contracts、registry、period resolver、unit resolver、candidate selector。
   - Acceptance: 3m／6m／9m／annual／instant、non-calendar fiscal year、amendment、mixed units、comparative later filings 都有 deterministic result 與 issue codes。
   - Validation: focused pure tests plus `compileall`。

3. Stage 2：Derived Engine
   - Scope: direct/discrete quarter、YTD subtraction、Q4、TTM、FCF、margin、growth、net debt、annual reconciliation。
   - Acceptance: 只有四個連續 fiscal quarters 與相容 input 才產生 TTM；每個 derived value 有 formula/input fact ids/status。
   - Validation: derivation tests covering missing/mixed/disputed/zero denominator。

4. Stage 3：SEC Access Policy、Submissions 與 Freshness
   - Scope: provider request gate、bounded retry、Submissions metadata/cache、filing-aware source health、watchlist job reuse。
   - Acceptance: request target <= 4 rps；429/403 行為受控；local/latest accession 可判斷是否需要 explicit refresh；GET 無 external call。
   - Validation: provider pure tests、source-health tests、per-symbol batch isolation tests。

5. Stage 4：Versioned API Contract
   - Scope: service façade、Pydantic schemas、`GET /sec/{symbol}/financials`、OpenAPI inventory、legacy adapter。
   - Acceptance: new route 穩定且 old routes unchanged；quality/source refs/freshness 完整；no-migration on-read path 效能有量測。
   - Validation: router/service/contract inventory tests與 bounded local API smoke。

6. Stage 5：AI Contract Adoption
   - Scope: US market context、`fundamentals.financials` projection、agentic reader、data-quality guard、answer data limits、MCP regression。
   - Acceptance: US financial capability 不再是空物件；partial/blocked 會降低 readiness/confidence；streaming/non-streaming 與 MCP 相容。
   - Validation: targeted AI capability、market-context、freshness、outward-contract、MCP tests。

7. Stage 6：Frontend Adoption
   - Scope: frontend types、US detail financial rendering、更新狀態整合；移除 frontend 核心財務推導。
   - Acceptance: 顯示 quarter/TTM/quality/source；legacy/absence/malformed payload 安全降級；不隱藏 partial/provider failure。
   - Validation: lint、typecheck、build；有實際 UI 風險時才做 screenshot/e2e。

8. Stage 7：Production proof 與延伸決策
   - Scope: AAPL/NVDA/MU real-data probes、runtime adoption、效能 profiling、materialization/IFRS/bulk decision。
   - Acceptance: running backend/API/frontend 採用新 contract；source/runtime/representative behavior 有證據；延後範圍有明確限制。
   - Validation: safe backend/full profiles plus bounded runtime/API/UI smoke。

## Stop-and-fix rules

- 任一 metric 將 YTD 當單季、混用 unit/currency、失去 accession lineage 或把缺值轉 `0` 時，停止進入下一 milestone。
- Legacy route/schema、AI public invariant 或 frontend consumer regression 失敗時，先修正或保留 compatibility seam。
- GET/read path 發出 SEC request、batch refresh 失去 per-symbol isolation、或 retry 可能無界時，停止並修正 ownership。
- 若需要 migration，先補 Alembic/model/rollback 設計；不得直接改本機 SQLite。
- 若 worktree 既有變更與本任務開始重疊，先檢查 exact diff 並調整，不覆蓋使用者內容。
- 若演算法無法對真實 fixture 解釋結果，回到 registry/period contract，不以更多 heuristic 掩蓋。

## Decisions

- 2026-08-11：採用原 v0.1 的 L0/L1/L2/L3 分層，但 public AI contract 對齊既有 `omi.financial.v1`，不建立第二套互不相容 envelope。
- 2026-08-11：canonical issuer identity 使用 CIK；symbol 是 lookup/display alias。
- 2026-08-11：Phase 1 no migration、on-read canonicalization；效能證明不足前不 materialize。
- 2026-08-11：Submissions/freshness 提前到 public API production 前，避免把 raw availability 誤標為 current。
- 2026-08-11：先完成 market-parity-ready 技術路徑；是否取消台股核心定位另以產品 milestone 決定。
