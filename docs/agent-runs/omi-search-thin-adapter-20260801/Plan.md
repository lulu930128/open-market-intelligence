# 執行計畫

## Milestone 1：責任邊界與基線

- [x] 檢查 OMI 與 GPT_MCPtool dirty worktree，隔離本任務相關差異。
- [x] 追蹤 adapter 判斷邏輯與 backend 現有 owner。
- [x] 執行修改前 targeted tests，建立行為基線。

驗收：能逐項指出應刪除的 adapter 判斷，以及對應的 backend owner。

## Milestone 2：Backend ownership 驗收

- [x] 在 question stage 補 regression test。
- [x] 證明 backend 依原始問題推導 effective horizon。
- [x] 證明 `allow_external_fetch` 不因語意推導被擴權。

驗收：targeted backend test 通過，不需新增第二套判斷。

## Milestone 3：Standalone adapter 收斂

- [x] 改為 backend live schema + generated snapshot fallback。
- [x] 移除 live intent、question rewrite、auto refresh、budget clamp/default 與 dead response projection。
- [x] 保留固定 read-only policy 與純欄位映射。
- [x] 更新 tests、README、boundary doc 與 env example。

驗收：`omi.ask` 是 canonical mapping；`omi.search` 僅作 legacy alias；shortcuts 只做明確 tool-to-target mapping。

## Milestone 4：跨邊界驗證

- [x] 執行 standalone unit tests 與 syntax check。
- [x] 執行 backend targeted tests。
- [x] 驗證 generated snapshot 與 backend public schema parity。
- [x] 執行 initialize -> tools/list -> representative tools/call 的 stdio MCP smoke。
- [x] 執行 source audit 與 `git diff --check`。

驗收：所有檢查通過；若 live backend 不可用，明確區分 snapshot/protocol 驗證與 live runtime 驗證。

## Stop-and-fix 規則

- schema 來源不再由 backend 擁有時停止。
- adapter 出現依 question/market/freshness 改變 payload 的行為時停止。
- backend business rejection 被轉成 MCP transport error 時停止。
- 測試需要改寫成接受非 v4 response 或隱藏 freshness/limitations 時停止。
