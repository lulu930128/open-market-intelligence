# Architecture Hardening 1/2/4 Prompt

## 背景

使用者要求先處理前一輪總覽中的第 1、2、4 項，避免繼續功能開發時累積更大的技術債。

對應範圍：

1. 固定產品主線與方向保護。
2. 穩定 market payload contract。
4. 收斂 frontend information architecture。

## Goals

- 將 repo 已確認的產品方向整理到 `docs/product/`，讓後續架構與 UI 取捨有可引用基線。
- 補強 market payload slot contract 的 schema invariant，避免 consumer 對 slot 欄位做脆弱假設。
- 抽離 frontend dashboard 的純 routing/type helper，降低 sidebar/dashboard 大元件耦合。

## Non-goals

- 不重寫 dashboard 或 sidebar。
- 不改 DB schema。
- 不新增外部 provider、付費資料或大量 refresh。
- 不改變既有 API response shape；本輪只做 additive/structural hardening。
- 不把市場資料判斷移到 frontend 或 MCP adapter。

## Hard Constraints

- 台股維持核心市場，其他市場是 context layer。
- Freshness、partial、missing、provider failure 必須可見。
- Backend 是市場資料與 AI decision contract 的真相來源。
- Frontend 只負責呈現與互動。
- 驗證使用 repo bounded validation；不啟動長駐 runtime 或無界外部抓取。

## Done Criteria

- `docs/product/` 不再是空模板，且內容與 README/AGENTS 一致。
- 有本輪 agent-run 文件記錄 scope、milestone、驗證與決策。
- Backend tests 覆蓋 slot envelope 的必要欄位與 canonical slots。
- `MarketRegion` 與 dashboard href builder 從 sidebar/dashboard 大元件抽到 shared lib。
- 相關 backend/frontend 驗證通過或失敗原因被明確隔離。
