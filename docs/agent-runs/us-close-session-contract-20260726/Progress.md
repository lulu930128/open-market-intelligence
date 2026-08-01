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
- 正式 launcher runtime 已於 2026-07-30 22:38 依 source-stale 流程重啟；
  8400 backend 啟動時間為 `2026-07-30T22:39:02+08:00`。
- 既有 `build_us_source_health` 讀取流程會同步 source-health snapshot；read-only smoke 需 mock 此副作用，本任務未擴張處理。

## 2026-07-30 相對日期語意補強

### 根因

- `requested_us_trade_date()` 只支援 ISO 日期、中文年月日、月日與「幾號」；
  `昨天`、`昨日`、`yesterday` 皆解析為 `None`。
- 因此問句沒有綁定 historical `trade_date`，後續可能讀 current context，
  或由模型看到日期不一致後錯誤判斷「昨天沒有資料」。

### 修正

- `昨天`、`昨日`、`yesterday`、`前一交易日`、`previous/last trading
  day/session` 先以 `America/New_York` 決定參考日期。
- 先取美東曆日的昨天，再遇週末或已知休市日向前解析到最近交易日。
- relative historical request 強制 `include_intraday=false`，不以目前盤前、
  盤中或盤後報價代替歷史資料。
- 保留原 exact-date 行為：明確指定不存在的歷史日資料時仍回 missing，
  不靜默換成別日或 current quote。

### 驗證

- 週末、時區跨日、Independence Day observed holiday 與 public params
  regression 已涵蓋。
- Taiwan quote-depth 與 US dated-close focused：
  `26 passed, 10 subtests passed`。
- 正式 `POST /api/ai/ask`、`omi.decision.v4`、`allow_llm=false`、
  `allow_external_fetch=false` smoke：
  - 問句 `AAPL 昨天的成交量`
  - `request_status=completed`
  - `requested_trade_date=2026-07-29`
  - `trade_date=2026-07-29`
  - `quote_semantics=historical_regular_session_close`
