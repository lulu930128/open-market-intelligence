# OMI 台股 Shared Data Core 剩餘收束長專案

## 任務識別

- Job ID：`2a57c0ff-c928-49da-9c7c-9509bef30333`
- 日期：2026-08-26
- 分支：`codex/tw-etf-provider-normalization`
- 架構稽核 checkpoint：已確認 current checkout 的實際 owner、資料流、架構缺口與既有保護面。
- 長專案規劃 checkpoint：把 P0 / P1 收束與 P2 migration seams 拆成可中斷續跑的 work packages。

## 目標

根據 current product truth、實際 source、tests 與 dirty worktree，逐步將仍由 legacy owner 持有的台股核心 market truth 接回既有 Shared Data Core / Quality Safety Layer，且不重寫已通過驗收的 foundation。

## 專案交付

1. 現況 owner map 與 target seam。
2. P0 / P1 / P2 主張的證據矩陣。
3. 規格漏列或需要修正的風險。
4. 分段實作計畫與每段 acceptance gate。
5. 明確區分 source-verified、runtime-unverified 與 live-session-pending。
6. 可逐包執行的 WorkPackages、ValidationStrategy、RiskRegister、DecisionLog 與 ExecutionBoard。
7. 每一包的 scope、依賴、acceptance、validation、rollback 與 evidence 更新規則。

## 本次不做

- 不修改 production code、schema、runtime 或資料。
- 不進行 KGI subscription、外部 provider refresh、M5 live-session gate 或前端 runtime 驗收。
- 不碰 US market、scheduler、DB contention 與其他既有 worktree 修改。
- 不把歷史 task docs 視為 current truth。
- 不 commit、push、publish、stash、reset、rebase 或 clean。

## Hard constraints

- 保留既有 Shared Gateway、Canonical Observation、Resolver、dataset lifecycle 與已收束的 TW official completed-session paths。
- shared generic core 不得 import 或硬編 KGI、MIS、Yahoo、NStock。
- GET 必須收斂成 read-only / cache-only；refresh、repair、lease 只能由 explicit command surface 發起。
- provider adapter 不擁有 transaction；persist 成功後必須 repository reread 再 resolve。
- unknown、missing、partial、indicative、actual trade、market session 與 instrument status 不得互相替代。
- dirty worktree 中的既有變更一律保留。

## Done criteria（架構確認與長專案規劃）

- [x] current truth 與相關 architecture contract 已讀取。
- [x] Shared Core、KGI / quote-depth、intraday、index / breadth、quality、P2 dataset owner 已由 source 確認。
- [x] 規格中成立、部分成立、漏列與未驗證項目已分開記錄。
- [x] 新 task folder、plan、progress、acceptance matrix、architecture map 與 artifact 已建立。
- [x] 長專案 work packages、依賴圖、驗證策略、風險與執行看板已建立。
- [ ] Production convergence、targeted tests、frontend validation 與 live-session M5 gate：留待後續 implementation phases。

## Program done criteria

- [ ] `QualityRequirement` 已成為 centralized executable eligibility policy，且 API / AI / MCP 不重建相同判斷。
- [ ] Gateway 具備 depth / auction typed read、acquisition、transaction、reread 與 resolve wiring。
- [ ] KGI quote / depth / auction 具完整 canonical raw lineage，並由 market-owned descriptors + Shared Resolver 決定候選與選擇。
- [ ] router 不再直接綁 KGI provider manager；viewer lease 經 provider-neutral market platform 管理。
- [ ] `quote_depth.py` 降級為 compatibility / projection，不再擁有 selection、fallback 或 transaction。
- [ ] NStock / Yahoo intraday bars 經 Shared Gateway；所有 GET intraday surfaces 都是 cache-only。
- [ ] current-session index / breadth 經 Shared Gateway，且 completed official semantics 不 regression。
- [ ] company profile 與 compatibility-derived datasets 建立 market-owned reader / lineage seams。
- [ ] architecture guards、targeted regression、cross-surface contract、frontend validation、runtime adoption evidence 均通過。
- [ ] M5 live-session acceptance 按實際 Preopen / Opening / Regular / Closing / cleanup 時序完成；缺任何正式 gate 時專案狀態維持 partial / pending。
