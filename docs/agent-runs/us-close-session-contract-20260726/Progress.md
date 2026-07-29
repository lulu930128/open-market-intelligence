# 進度

## 狀態

- 已完成實作與 targeted backend validation。

## 已確認根因

- close/closing-price 問句會走 quote intent，但既有 US quote reader 預設選最新 intraday 或最新 daily row。
- 問句內日期沒有綁定美股 exchange trade date。
- 盤後 last trade 與 regular-session close 雖有部分底層欄位，public quote projection 與人類回答沒有穩定區分。
- agentic `us.read_intraday_trend` 沒有傳遞 caller 的 `session_scope`。

## 已完成

- 建立本任務規格與驗證計畫。
- 新增保守的 US close-date 解析器；自然語言推導只在明確收盤價問題啟用。
- US context 支援 exact `trade_date`，不存在時明確 missing 且不回退。
- daily quote 補齊美東交易日、排定收盤時間、timezone、historical semantics 與 regular close 欄位。
- 盤前、正常盤、盤後 intraday quote 分別使用 last-trade semantics，盤後價不再冒充收盤價。
- public ask、HTTP reader、AI tool catalog、MCP schema 與 capability projection 已公開 `trade_date`。
- agentic intraday tool 已傳遞 `session_scope`；historical close 不排程 current intraday。
- 日期型收盤價問句固定歸為 quote intent，避免 brief 跑成一般技術評分。
- deterministic quote answer 同時顯示美東時間與台北換算時間。

## 驗證證據

- Safe validation：`backend compileall` 通過。
- Targeted pytest：`227 passed, 56 subtests passed`。
- `git diff --check` 通過。
- Read-only public v4 smoke（mock 掉既有 source-health snapshot 同步）：
  - AAPL `2026-07-20` price `326.5899963378906`
  - `quote_semantics=historical_regular_session_close`
  - `quote_time=2026-07-20T16:00:00-04:00`
  - `realtime_state=historical`
  - 中文回答標示台北時間 `2026-07-21 04:00`

## 已知限制

- 本機 US fallback calendar 尚未建模特殊提早收盤日，因此 daily quote 的 `quote_time_basis` 明確標為 `scheduled_regular_session_close`，回答也會顯示限制。
- 正式 launcher runtime 尚未重啟；目前 8400 listener 仍是修改前程序。因 worktree 另有進行中的台股變更，本任務未擅自重啟或載入整個 dirty worktree。
- 既有 `build_us_source_health` 讀取流程會同步 source-health snapshot；read-only smoke 需 mock 此副作用，本任務未擴張處理。
