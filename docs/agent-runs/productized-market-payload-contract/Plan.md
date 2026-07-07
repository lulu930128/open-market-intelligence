# Productized Market Payload Contract Plan

Last updated: 2026-07-07

## Milestone 1 - Contract Skeleton

Acceptance criteria:

- 新增 canonical slot envelope，欄位包含 `status`、`capability`、`priority`、`payload_ref`、`payload_level`、`missing`、`warnings`、`next_fill`。
- 台股個股 compact evidence 輸出 `slots`，且不移除既有 `quote`、`intraday_bars`、`technical`、`chips`、`fundamentals`。
- 台股指數 compact evidence 輸出 `slots`，支援大盤/櫃買指數盤中 slot。
- 台股市場 overview 輸出 `data.slots`，讓 market brief/data_only 可直接讀到大盤盤中 slot。
- 跨市場 `_compact_market_context` 輸出 generic `slots`，讓 US/JP/KR/crypto 有同一個插槽骨架。

Validation:

```powershell
cd "C:\project\Open Market Intelligence\backend"
..\.venv\Scripts\python.exe -m unittest tests.test_technical_report tests.test_ai_freshness_guard
..\.venv\Scripts\python.exe -m unittest tests.test_omi_mcp_server
..\.venv\Scripts\python.exe -m compileall app\ai
```

## Milestone 2 - Consumer Contract

Acceptance criteria:

- `ask_finalizer` 在 brief/data_only slim result 內投影 `result.data.slots`。
- ChatGPT Web / MCP / Kuro 可以優先讀 `analysis.human_answer`，並用 `result.data.slots` 判斷是否需要 request `payload_level` 升級或第二段查詢。
- `omi.ask` schema 文案描述 `market_data_params.include_intraday`、`payload_level`、`intraday_limit`。

Validation:

- MCP tests 確認 adapter 仍 thin forwarding。
- 針對 stock、market、tw_index 的 data_only/brief response 做 regression。

## Milestone 3 - Data Backfill By Slot

Acceptance criteria:

- Taiwan core slots 先完整：`quote`、`intraday`、`daily_chart`、`technical`、`chips_flows`、`fundamentals`、`market_breadth`、`index_intraday`。
- US slot adapter 補齊 `payload_level` 對 intraday bars 的實際裁切與 `standard/full` 行為。
- JP/KR slot adapter 先清楚標示 local-cache-only、planned intraday 與 provider limitation。
- Crypto slot adapter 明確拆出 `quote`、`ohlcv`、`liquidity`、`derivatives`，並保留 event-driven empty 的資料限制。

Validation:

- 每個市場至少一個 compact context test 驗證 `slots` 狀態與 `payload_ref`。
- 對外 API smoke 只在需要 runtime 驗證時執行。

## Stop-and-fix Rules

- 若 slot 狀態和實際資料矛盾，例如 missing 資料標成 ready，先停下修 contract。
- 若新增欄位讓 payload 大幅膨脹，改成 `payload_ref` 或二段查詢。
- 若 consumer 需要重做 freshness 或市場邏輯才能解讀 slot，回到 backend 修 projection。
- 若 external fetch 會超出 bounded policy，不在 slot 實作中偷跑。
