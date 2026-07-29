# 美股收盤與盤中盤後時間契約修正

## 目標

- 指定美股交易日時，只回該交易日的 regular-session close。
- 盤前、盤中、盤後資料明確標示為 last trade，不與收盤價混用。
- OMI public v4、HTTP reader 與 MCP 對外介面共用同一個 `trade_date` 與 `session_scope` 契約。
- 日期、quote time、exchange timezone、session semantics 與 regular close 可由外部 consumer 分辨。

## 非目標

- 不重建或修改本機市場資料庫。
- 不新增自動交易或投資建議行為。
- 不改動台股、日股、韓股的交易日模型。
- 不在 frontend 或 MCP adapter 重做 backend 市場邏輯。

## 硬性限制

- `trade_date` 是 `America/New_York` 的市場交易日，不是呼叫端本地日期。
- 找不到指定日期時回報 missing，不得退回最近交易日。
- historical close 不得被標示成 live 或 latest completed session。
- 不隱藏 stale、partial、missing 或 provider failure。
- 保留既有欄位與 route，相容性變更採 additive contract。

## 完成條件

- 自然語言「20 號收盤價」與明確 `trade_date=YYYY-MM-DD` 都會綁定同一個美股交易日。
- exact-date context 只查該日日線並忽略 current intraday quote。
- after-hours quote 同時帶有 extended-hours last trade 與 regular-session close。
- public v4 與 MCP schema 公開 `trade_date`。
- targeted tests、compile 與安全 backend validation 通過。
