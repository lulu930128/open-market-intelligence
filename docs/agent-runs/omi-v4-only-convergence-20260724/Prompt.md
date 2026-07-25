# OMI v4 對外契約收斂

## 目標

- 將 OMI 對外 AI 問答契約收斂為唯一的 `omi.decision.v4`。
- HTTP、SSE、OpenAPI、MCP 與 frontend consumer 使用相同 backend-owned envelope。
- 保留既有市場 reader、細粒度 capability selection、欄位/筆數/byte budget、
  bounded refresh、fill plan 與資料品質語意。
- 交付 UTF-8 純文字能力設計表，明確區分目前可做到、條件式可做到與不能做到。

## 非目標

- 不刪除 backend 私有的 v2/v3 builder 與回歸測試 seam。
- 不把市場判斷或 Kuro 可念稿整理移到 MCP、frontend 或 Kuro。
- 不新增自動下單、無邊界全市場 refresh 或隱性付費 API 消耗。
- 本輪不處理使用者明確排除的 P0-17、P0-25～27、P0-50、P0-69、P1-74。

## 硬限制

- 對外 request 明確指定 v2/v3 時必須可預期拒絕，不得靜默降級。
- 對外 response 與 schema 只宣告 `omi.decision.v4`。
- stale、partial、missing、provider failure 與 decision readiness 必須保留。
- Adapter 維持 thin，不直接讀 DB、不重做市場邏輯。

## 完成條件

- `/api/ai/ask` 與 `/api/ai/ask/stream` 的 OpenAPI request 只接受 v4。
- `/api/ai/ask` 的成功 response schema 只宣告 v4 envelope。
- `/api/ai/tools` 與 MCP `tools/list` 的 `contract_version` enum 只有 v4。
- MCP 明確傳入 v2/v3 時在送出 backend 前可預期拒絕。
- targeted tests、backend regression、frontend contract check 與 live HTTP/SSE/MCP
  smoke 都通過。
- `docs/OMI_v4_能力設計表_2026-07-24.txt` 完整且 UTF-8 可讀。
