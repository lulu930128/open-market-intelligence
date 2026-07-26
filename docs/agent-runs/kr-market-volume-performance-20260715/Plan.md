# 計畫

## Milestones

1. 資料鏈與 runtime 基線
   - 範圍：Naver intraday/realtime parser、service cache/merge、API response、frontend chart aggregation。
   - 驗收：用 live payload 與 localhost API 證明累計量被當成區間量及分鐘重複。
   - 驗證：`Invoke-RestMethod http://127.0.0.1:8400/api/kr-market/indices/KOSPI/intraday`

2. Backend contract 與效能修正
   - 範圍：canonical minute、cumulative delta、incremental refresh、volume metadata、tests。
   - 驗收：同分鐘 realtime update 覆寫而不新增；總量等於最新 cumulative；refresh 使用同日 cache。
   - 驗證：`.\.venv\Scripts\python.exe -m pytest backend\tests\test_kr_market_data.py`

3. Frontend 操作改善
   - 範圍：KR index selection、intraday volume顯示、source label、stable reveal key、API type。
   - 驗收：不先對 index 發出必然 404 的 stock lookup；成交量顯示千股；輪詢不重播全圖動畫。
   - 驗證：`npm exec tsc -- --noEmit --incremental false`、`npm run lint`

4. 整合驗證與建議
   - 範圍：safe validation、build、runtime/browser spot check、後續 API roadmap。
   - 驗收：沒有回歸、資料限制可見、剩餘效能債有證據與優先級。
   - 驗證：`.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs @('backend\tests\test_kr_market_data.py')`、frontend build、`git diff --check`

## Stop-and-fix rules

- 若成交量差分出現負值、跨日累計或缺累計基準，保留 provider page 的區間量並回傳 warning，不製造負成交量。
- 若 API contract 需要 breaking change，停止並改採 optional field 擴充。
- 若驗證碰到既有未提交變更造成失敗，先隔離證據，不修改無關檔案。
- 若 live runtime 未載入新程式，先辨識 stale process，不把舊 payload 當成修正失敗。

## 決策

- 2026-07-15：成交量修正在 backend 完成，frontend 只消費 `volume`、`cumulative_volume` 與 unit metadata。
- 2026-07-15：`refresh=true` 定義為 bypass fresh TTL，但保留同交易日 cache 做 incremental merge；完整重建不再是一般 UI refresh 的隱性副作用。
- 2026-07-15：本次不做 intraday DB migration；先以 bounded in-memory cache、canonical minute 與向後相容 contract 收斂高優先問題。
