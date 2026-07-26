# 進度

## 目前狀態

- 狀態：已完成
- 日期：2026-07-24

## 已完成

- v4 已具備 capability registry、欄位 allowlist、row/point limits、
  `max_response_bytes`、data manifest、quality contract、realtime state 與 granular
  fill plan。
- HTTP、SSE、OpenAPI、repo MCP、standalone `OMI_search`、Frontend OMI Dock
  與 Kuro live preflight 已收斂為 `omi.decision.v4`。
- 公開 request 使用 v4-only model；明確傳入 v3/v2 會被拒絕。
- `/api/ai/tools` 與 MCP `tools/list` 只宣告 v4，並同步 38 個 capability。
- v4 capability projection 已擴充 market、derivatives、watchlist、portfolio、
  macro、resource、US profile/actions/short-volume，避免收斂時遺失舊資料面。
- MCP 不再製作 consumer-specific 摘要，HTTP、SSE 與 MCP 都保留同一 canonical
  envelope。
- Kuro 只向 OMI 取 v4 資料；可念稿、角色語氣與 TTS 仍由 Kuro 模型/呈現層處理。
- 能力與限制已整理至 `docs/OMI_v4_能力設計表_2026-07-24.txt`。

## 決策

- v2/v3 builder 保留為 backend 私有實作與回歸 seam，不再是 consumer 可選版本。
- 公開入口使用獨立的 v4-only request model，避免破壞內部既有測試與功能。
- MCP 的 `include_raw` 保留為相容 transport flag；在 v4 下不改寫 canonical
  envelope，consumer-specific 整理留在 consumer。

## 驗證證據

- Targeted backend/MCP/v4 contract：70 passed，另含 18 個 subtests。
- Backend safe validation：compileall 與 980 tests passed；
  log：`.tmp/validation/20260724-201005`。
- Frontend safe validation：lint 與 TypeScript typecheck passed；
  log：`.tmp/validation/20260724-201132`。
- Standalone `OMI_search`：26 unittest passed，AST syntax check passed。
- Kuro：20 unittest passed；`tool_catalog.json` parse passed。
- Main repo 與 Kuro 本次相關檔案：`git diff --check` passed。
- Backend 已重啟；`127.0.0.1:8400` listener PID 58228，health 指向本 checkout
  與 `.venv`，readyz 為 ready。
- Live `/api/ai/tools`：contract enum 只有 v4，selection 與 registry 均為
  38 capabilities。
- Live OpenAPI：ask/stream request 均為 `AiAskV4Request`，ask response 為
  `AiDecisionEnvelopeV4`。
- Live HTTP：v4 success；v3/v2 均回 422；不存在代碼回 canonical v4
  `TARGET_NOT_FOUND`。
- Live SSE：包含 `status/evidence/delta/final/done`，final 為 v4。
- Live payload bound：2330 quote response 20,472 bytes，小於 32,768 bytes
  request budget。
- Live capability projection：TXF 回傳 `derivatives.positioning` 與
  `derivatives.structure`；後者 stale 狀態未被隱藏。
- Live granular fill：DOGE `crypto.order_book` stale 時只產生一個 capability、
  一個 target、limit=5、estimated_calls=1 的 fill action，沒有自動執行全抓。
- Live MCP：完成 `initialize`、`tools/list`、success call、business-error call
  與 legacy rejection；success/business error 均保留 v4 canonical envelope。

## 已知執行條件

- Backend runtime 已載入本次 v4 source。
- Standalone `OMI_search` tunnel/stdio 與 Kuro 若已有舊常駐程序，仍需由其正常
  啟動流程重新載入；本輪沒有啟動或干預 Kuro GUI。
- 本輪沒有呼叫付費 LLM 或大量外部 refresh；只驗證 policy、schema、cache
  evidence 與 bounded fill plan。
- P0-17、P0-25～27、P0-50、P0-69、P1-74 依使用者指示維持不處理。
