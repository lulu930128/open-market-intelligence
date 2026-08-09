# Plan

## Milestones

1. Provider contract
   - 找出官方、可程式化的 PCF REST 與 iNAV SignalR contract。
   - 驗證 request 數、response schema、source time 與 TLS 行為。

2. Persistence and service
   - 新增 Alembic migration、ORM models、idempotent upsert 與 bounded retention。
   - 延伸 overview freshness/source/capability 與明示 refresh flags。

3. Validation
   - Parser/schema drift、SignalR 5-request sequence、PCF/inNAV service、migration tests。
   - 0050 bounded live provider smoke、backend safe validation、diff audit。

## Stop-and-fix rules

- 官方來源若只能透過停用 TLS 驗證取得，不將 capability 標為已接入。
- PCF 同時回傳申購籃子與參考權重時，不得重複投影成兩份「成分股」。
- iNAV 沒有 source timestamp、NAV 無效或非交易時段時，不得標成 live/current。
- 新 request flags 必須預設關閉，避免既有 frontend refresh 隱性增加外部流量。
