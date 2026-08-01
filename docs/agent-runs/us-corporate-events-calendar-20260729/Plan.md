# 實作計畫

## 里程碑 1：契約與持久化

### 工作

- 定義 `USCorporateEvent` logical identity、日期與來源欄位。
- 新增 Alembic migration。
- 定義獨立的 US corporate-event schema，避免擴大現有 dirty schema 檔案衝突。

### 驗收

- ORM metadata 可建立新表。
- migration revision 接在目前最新 revision 後。
- 唯一鍵能讓 earnings 日期修訂更新同一 logical event。

## 里程碑 2：Provider、服務與 API

### 工作

- 新增 Alpha Vantage `EARNINGS_CALENDAR` CSV fetch。
- 解析與正規化 earnings rows。
- 合併 `USCorporateEvent` 與既有 `USCorporateAction` 成單一 read contract。
- 實作 list、7 日 summary、bounded refresh。
- 記錄 provider event，保留 failure、stale 與 cached fallback。
- 新增 `/api/us-market/corporate-events` routes。

### 驗收

- GET 無 external side effect。
- POST refresh 每次最多一個 upstream request。
- provider failure 時 DB rollback，既有 cache 可繼續讀。
- list 與 summary 使用 `America/New_York` 市場日期。

## 里程碑 3：Scheduler

### 工作

- 新增獨立開關與 3 小時 interval。
- 啟動時若 key 存在可執行 bounded catch-up；未設定 key 則不呼叫 provider。

### 驗收

- `max_instances=1`、`coalesce=True`。
- scheduler disabled 條件包含新開關。
- 失敗有 log 與 provider event，不使 scheduler thread 崩潰。

## 里程碑 4：既有 UI 擴充

### 工作

- 將 `MarketCalendarDialog` 泛化為 TW/US 共用呈現。
- 上方增加 TW/US/JP/KR 市場按鈕。
- JP/KR disabled 並顯示規劃中。
- US detail panel 讀取 7 日 summary 並顯示事件標籤。
- 加入 zh-TW/en-US 文案與共用 frontend types。

### 驗收

- 不新增第二個 modal 或頁面。
- 台股現有 filter、來源與事件卡片行為不退化。
- 市場切換取消舊請求並清除不相容 filter。
- US source coverage 與 freshness 可見。

## 里程碑 5：驗證

### Backend

- compile/syntax。
- US corporate event targeted tests。
- migration/model parity 相關測試。
- OpenAPI route contract spot check。

### Frontend

- lint。
- TypeScript noEmit。
- production build。
- 需要時執行 focused browser/e2e，確認市場切換、JP/KR disabled 與 7 日 badge。

### 整體

- `git diff --check`。
- 稽核 changed files，確認未混入 Radar、DB、log、cache 或 secret。

## Stop-and-fix 規則

- migration head 在實作期間改變：停止新增 migration，重新確認 revision graph。
- 既有 Radar 變更與本任務發生同一區塊衝突：停止 patch，改以獨立 module/router/type 避開。
- provider CSV schema 不符：不得 silent skip；回報 malformed count 與明確 warning。
- frontend 顯示無 backend 證據的 freshness 或 event time：移除推測，修正 contract。
