# 實作計畫

## Milestone 1：日期與 session 契約

- 新增美股指定交易日解析器。
- US context 支援 exact `trade_date`，精確篩選日線與 chart 上限。
- quote 補齊 `trade_date`、`quote_time`、`timezone`、`quote_semantics`、regular close 欄位。

驗收：

- 指定日期存在時，quote 價格與日期完全對應該筆日線。
- 指定日期不存在時，不回退到最新日線。
- 盤後價與 regular close 可同時存在且語意不同。

## Milestone 2：對外傳遞

- public ask 從明確參數或收盤價問題推導 US `trade_date`。
- HTTP reader、MCP schema 與 capability projection 公開相同欄位。
- agentic intraday tool 傳遞 `session_scope`，historical close 不抓 current intraday。

驗收：

- public v4、HTTP、MCP 皆能指定 `trade_date`。
- `session_scope=all` 不會在 tool stage 被降回 regular。

## Milestone 3：回答與資料品質

- historical close 使用 historical observation state。
- quote answer 明確顯示 regular close 或盤前／盤中／盤後 last trade。
- 指定美股收盤時間可同時辨識美東時區與台北換算時間。

驗收：

- historical close 不標示 live/latest。
- after-hours last trade 不被稱為 closing price。

## Milestone 4：驗證

- 新增日期解析、US context、realtime contract、MCP 與 answer regression tests。
- 執行 compile、targeted pytest 與 backend safe validation。
- 以隔離測試或 TestClient 驗證 public v4；不在 dirty worktree 未確認時重啟正式 launcher。
