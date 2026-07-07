# Productized Market Payload Contract Prompt

Last updated: 2026-07-07

## 背景

OMI 需要同時服務本機 frontend、MCP `omi.ask`、ChatGPT 網頁版與未來桌寵/Kuro 端。使用者希望 OMI 能回傳「盤中資料」與「大盤盤中資料」，但資料不能一次回傳過大；未完成的資料面要先設計成可穩定擴充的插槽，而不是讓外部 adapter 或 consumer 自行猜欄位。

## 目標

- 建立產品化的市場 payload contract，讓台股個股、台股大盤/指數、US/JP/KR/crypto 都能用同一套 slot envelope 表示資料狀態。
- 保留 Taiwan-first：台股是核心市場，其他市場是 context layer。
- 用 `payload_level` 控制資料密度，避免 MCP/ChatGPT/桌寵收到過大的資料包。
- 對未完成資料輸出 `planned`、`missing`、`not_requested`、`not_applicable` 等狀態，不編造資料。
- 保持 MCP/Kuro/frontend thin consumer：市場邏輯、freshness、tool orchestration 都留在 OMI backend。

## Non-goals

- 不把 OMI 變成自動交易或自動下單系統。
- 不讓 MCP adapter 或桌寵端直接讀 DB、呼叫 provider 或重做市場判斷。
- 不為了統一 contract 刪除或改型既有 response 欄位。
- 不在 read path 做無邊界全市場抓取或大量外部 API refresh。

## Hard Constraints

- `result.data.compact` 既有欄位保持相容；新增欄位必須 additive。
- 資料 freshness、missing、warnings、provider failure 必須可見。
- `payload_level` 至少支援 `summary`、`compact`、`standard`、`full`。
- slot 只能描述資料狀態與指向既有 payload；不能因 slot 而重複塞大包資料。
- 任何 external fetch 仍必須受 server policy、tool budget 與 bounded refresh 控制。

## Deliverables

- `ContractDesign.md`：市場 payload/slot contract 設計。
- `Plan.md`：分階段落地與驗證計畫。
- `Progress.md`：本輪完成狀態、決策與已知缺口。
- Backend compact evidence 的 additive `slots` 骨架。
- Targeted regression tests 保護 slot contract。

## Done Criteria

- 台股個股、台股指數/大盤與跨市場 compact evidence 都能輸出 `slots`。
- Public slim view 可讓 ChatGPT/MCP/桌寵讀到 slot metadata。
- 文件明確說明 capability matrix、payload levels、slot status 與 consumer 規則。
- Targeted tests 與 syntax check 通過。
