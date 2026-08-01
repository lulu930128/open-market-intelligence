# 進度

## 目前狀態

已完成：backend capability、既有行事曆市場切換、美股 7 日提醒與日韓規劃中入口均已實作並驗證。

## 已完成

- 讀取 repo 與 frontend `AGENTS.md`、產品文件與 backend architecture。
- 讀取 `productized-project-workflow` 與 `omi-add-market-capability` 工作流。
- 讀取使用者提供的 API 草案並將 route 收斂至 repo 現有命名。
- 確認既有台股行事曆、7 日提醒、US corporate action、Alpha Vantage provider、scheduler 與 US detail panel 的 owner。
- 確認日股、韓股本次只保留 disabled planned entry。
- 確認工作樹存在另一批 Radar 變更，已規劃以獨立 module/router/type 降低重疊。
- 新增 `USCorporateEvent` 與 migration `20260729_0042`。
- 新增 Alpha Vantage earnings CSV adapter、stable logical identity、upsert 與 provider-event 紀錄。
- 新增 cache-only list、紐約市場日期 7 日 summary 與 bounded refresh API。
- 合併既有 dividend/split cache，並在 source contract 標示 `watchlist_only`。
- 新增 3 小時 bounded scheduler；未設定 provider key 時明確跳過。
- 驗證 OpenAPI 三條 route、單一 migration head、6 個 targeted tests 與空 DB migration。
- 將既有 `MarketCalendarDialog` 泛化為台股／美股共用視窗。
- 加入台股、美股、日股、韓股市場按鈕；日韓 disabled 且明示「規劃中」。
- 美股行事曆顯示 earnings、dividend、split 與 source coverage/freshness。
- 美股個股詳情讀取 7 日 summary，顯示事件標籤並把 warning/failure 送到更新狀態。
- 加入 focused Playwright 覆蓋市場切換、日韓零請求與美股 7 日事件標籤。

## 重要決策

- UI 沿用單一 `MarketCalendarDialog`。
- MVP provider 使用既有 Alpha Vantage key。
- earnings 為全市場 bounded calendar refresh；dividend/split 為既有 cache 的 watchlist-only coverage。
- GET cache-only；POST/scheduler 才可 refresh。
- 市場日期採 `America/New_York`。
- 未知 event time 保持 `null`，不推測 market session。
- 日股、韓股顯示規劃中，不建立假資料或 placeholder API。

## 尚未完成

- 尚未設定本機 `ALPHAVANTAGE_API_KEY`，因此目前 live runtime 只能顯示 provider 未設定與既有快取。
- production build 未執行：同一 frontend 目錄已有 PID 60520 的 Next dev server，為避免改寫其 `.next` runtime，改以 lint、typecheck 與復用該 runtime 的 focused Playwright 驗證。

## 已知風險

- `backend/app/db/models.py` 與 migration `20260729_0041` 目前包含未提交 Radar 工作；每次修改前後需重新檢查。
- Alpha Vantage 的 corporate action coverage 是逐檔快取，不是全市場；UI/API 必須持續明示。
- 未設定 `ALPHAVANTAGE_API_KEY` 時，refresh 不可用，但 cache-only read path 必須保持可用。
- 本次未停止或重啟既有 frontend/backend process；runtime smoke 僅使用現有 3000/8400 process。

## 下一步

設定 `ALPHAVANTAGE_API_KEY` 後，呼叫一次 `POST /api/us-market/corporate-events/refresh` 或等待 3 小時 scheduler，確認 live earnings rows 進入行事曆。

## 驗證證據

- `backend/tests/test_us_corporate_events.py`: 6 passed。
- `backend/tests/test_database_migrations.py`: 5 passed。
- `backend/tests/test_database_model_contract.py`: 2 passed、55 subtests passed。
- `backend/tests/test_us_market_service_boundaries.py`: 3 passed。
- `alembic heads`: `20260729_0042 (head)`。
- OpenAPI: list、summary、refresh routes 均存在且 method 正確。
- safe validation backend: compileall、targeted pytest、`git diff --check` passed。
- safe validation frontend: ESLint、TypeScript noEmit、`git diff --check` passed。
- focused Playwright: 2 passed；復用同專案 port 3000 runtime。
- live cache-only smoke: port 8400 的 list 與 AAPL summary 均為 HTTP 200，timezone 為 `America/New_York`，未設定 key 時狀態正確為 `provider_not_configured`。
