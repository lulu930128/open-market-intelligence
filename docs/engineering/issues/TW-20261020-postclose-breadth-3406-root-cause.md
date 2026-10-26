# OMI 台股盤後資料缺漏與 Runtime 中斷根因調查（2026-10-20）

> **狀態：OPEN / EVIDENCE RECORD / NO FIX**\
> **觀測與記錄時區：Asia/Taipei（UTC+08:00）**\
> **調查日期：2026-10-20；主要市場事件日期：2026-10-19**\
> **調查性質：Runtime／MCP 快取唯讀觀測、現行 Source 靜態檢查、既有 Codex 驗收紀錄回讀。**\
> **本文件不是程式修復、現行 Git 封版或已完成 Live Gate 的證明。**

## 0. 快速結論

**目前沒有證據證明「中途重啟 OMI 造成資料庫內容損壞」。** 實際上已觀察到兩條彼此獨立的資料可用性缺口：

1. **TWSE MIS Breadth**：部分輪次的多批擷取遇到 Timeout 與 20 秒 Scan Budget 耗盡，導致整輪資料未收齊；即使 Batch 全數成功，上游原始欄位 `z` 仍經常未提供合格成交價（例如原始 `z='-'`、同時 `v>0`），不能把 Provider Received 當成 Directional Coverage。
2. **3406 玉晶光 1m K**：2026-10-19 官方日收盤價正常；當日已物化 237 根一分鐘 K，但連續撮合 09:00–13:24 共 265 個預期分鐘中有 **28 個缺少可確認證據**。尚未定位是上游漏資料、Parser 排除、Canonical/Persistence 未入庫、Job 延遲／中斷，或當分鐘經官方證明無成交。

**時間因果邊界**：2026-10-19 **13:32** 已保存不完整的 TPEX Breadth 收據；既有 Codex 驗收確認 2026-10-19 **20:39–20:40** 才完成該次 Full-Service Restart，所以**該次晚間成功重啟不是 13:32 缺口的起因**。這不排除其他未核對的歷史中斷或重啟可能影響某個特定 Job。需要逐 JobRun／原始 Receipt 對時才能判斷。

**已確認正常**：官方收盤價、盤前即時快照 `stale/null` 的價格安全保護、Backend `/readyz`、MCP 本機 Ready。**尚未通過**：TPEX 全市場 Breadth、3406 1m 完整 Coverage、Runtime 全部來源的 Loaded Release Attestation。

### 證據與判斷級別

- **CONFIRMED OBSERVATION**：正式 `omi.ask`、唯讀 Dashboard／Health、既有 Raw Receipt／重啟結果直接顯示的數據。
- **CONFIRMED SOURCE BEHAVIOR**：本次實際讀過的原始碼及行號；只代表磁碟 Source，不自動證明 10/19 所有時刻載入相同程式。
- **SUPPORTED INFERENCE**：收據加上 Source 能支持的合理原因，但還沒有逐批 Raw／逐 Job 完全驗證。
- **UNVERIFIED HYPOTHESIS**：仍須查證，不能寫成確定的 Bug、事故根因或資料毀損。

## 1. 觀測時間線與證據來源

所有時間為 **2026 年、台灣時間 UTC+08:00**；注意「資料事件時間」和「進行唯讀查詢的時間」不可混用。

| 時間 | 事件／來源 | 已確認事實 |
| --- | --- | --- |
| 10/19 09:22:53–09:23:38 | 既有 Codex 唯讀 Raw Receipt 分析，`raw_fetch_result:796480`（TWSE）、`:796482`（TPEX） | 同輪資料取得成功但大量合格成交價缺失；詳 §2.2 |
| 10/19 10:09 | 既有 Codex 重啟 Preflight | Source Adoption Guard 拒絕，**重啟請求 0 次**；不能算作停機 |
| 10/19 約 10:19–10:23 | 前輪正式盤中 `omi.ask` | TAIEX 當時可用；3406 最後已確認成交 1,010，事件時鐘 09:58:22，10:23 已判 `stale`；3406 當時 1m 約 0/80 |
| 10/19 13:32:05 | TPEX 盤後 Breadth 收據，10/20 查詢回讀 | Directional 531/887；Batch 7 Timeout，後兩 Batch Budget Exhausted |
| 10/19 13:32:30 | TWSE 盤後 Breadth 收據，10/20 查詢回讀 | Directional 1,027/1,080，來源仍 partial |
| 10/19 18:10:49 | 既有 Codex Launcher 驗收紀錄 | 一次 Full-Service Restart **未完成**，原因 `PREFLIGHT_REARMED / JOB_QUIESCENCE`，Backend 未替換；與 13:32 成因尚無直接關聯 |
| 10/19 20:39:41–20:40:25 | 既有 Codex Full-Service Restart 成功紀錄 | 單次信號、`request_id=c82bc269-9b8c-4b19-a60c-fd24f1661024`，Backend `38660 → 43672`，最終兩服務 Ready；**晚於 13:32 收據** |
| 10/20 08:17:44 | 本輪當地時間核對 | 市場屬 **盤前**；不是當日盤後。此輪讀取 **10/19 已完成交易日**快照 |
| 10/20 08:18:30（Runtime 的 `observed_at`） | 正式 Runtime Control 唯讀 | Launcher PID 25264、Backend PID 43672；`disk_matches_import=true`，但 `loaded_release_identity=UNATTESTED` |
| 10/20 約 08:18–08:21 | 正式 `omi.read_tw_market_dashboard` 與 `omi.ask` cache-only | 昨日指數收盤、昨日 Breadth、3406 官方收盤與 1m K 數量／缺口；詳 §2 |
| 10/20 08:19:38（Dataset Health `checked_at`） | 3406 官方 Daily / `omi.ask` | `tw.daily.ohlcv` 對 10/19 `healthy`／`DATASET_CURRENT` |
| 10/20 08:20:56（MCP Snapshot `observedAt`） | Workspace 唯讀 `omi_search` 診斷 | MCP 本機 `Ready`，Core PID 41884、Connectivity PID 40508；Build ID `db725af64d3fa229`，Source Build 未發布 |
| 10/20 本次靜態調查 | Project Workspace 唯讀原始碼、Git status／diff | 程式碼流程、20 秒 Budget、無證據分鐘的 Coverage、Job 暫停與恢復語意；詳 §3 |

**方法／副作用**：正式 `omi.ask` 明確使用 `realtime_policy=cache_only`、`refresh_policy.mode=off`、`before_answer=false`、`tool_budget.max_calls=0`、`max_external_fetches=0`。Refresh Reconciliation 回傳 `attempted=false`、`provider_fetch_attempted=false`、`refresh_requested=false`。未發送交易、Provider Refresh、Runtime 重啟、資料庫寫入或程式修改；**本次只新增這份紀錄文件**。

## 2. 正式讀取到的資料異常

### 2.1 昨日收盤 Index 與執行時段（正常）

10/20 08:18 左右，Taiwan Dashboard 的 session 是 `preopen_pending`／`today_pending`，下一個轉換 08:30；因此當天沒有即時成交或分鐘 K 屬盤前預期行為。

| 標的 | 10/19 官方收盤值 | Event Time | Provider／Source | 判斷 |
| --- | ---: | --- | --- | --- |
| TAIEX | 46,822.08（相對前收 47,111.26，-289.18） | 10/19 13:30 | `twse_index_daily_ohlc`／`twse_indices_report_mi_5mins_hist` | `final`、`official_close_confirmed=true`、`decision_usable=true` |
| TPEX Index | 394.05（相對前收 400.26，-6.21） | 10/19 13:30 | `tpex_openapi`／`TPEx Official Market Index Daily` | `final`、`official_close_confirmed=true`、`decision_usable=true` |
| 3406 官方日收盤 | **1,045 元** | 10/19 13:30 | `twse_rwd`／`TWSE RWD Daily Trading` | `latest_completed_session`、`available=true`、`tw.daily.ohlcv=healthy` |

**盤前資格區分**：10/20 08:19 時 3406 的當日 `quote.snapshot` 為 `stale`／決策級現價 `null`，`quote.session_close` 對新交易日尚未釋出；但 `quote.official_close` 仍正確保留 10/19 的 1,045 元。不可把昨日收盤值強制升格為今日即時成交。

### 2.2 TWSE／TPEX 10/19 盤後 Breadth 缺漏（CONFIRMED）

這是 **10/19 盤後最後已觀測收據**，不是 10/20 08:xx 新執行的全市場擷取。

| 度量 | TWSE（10/19 13:32:30） | TPEX（10/19 13:32:05） |
| --- | ---: | ---: |
| Universe | 1,080 | 887 |
| Received | 1,075 | 595 |
| Directional（有效上漲／下跌／平盤） | **1,027** | **531** |
| Directional Coverage | **95.1%** | **59.9%** |
| Actual Trade Price Unavailable | 43 | 47 |
| Valid No Trade | 5 | 17 |
| Provider Missing | 5 | **292** |
| Attempted / Failed / Skipped Batches | 11 / 0 / 0 | **7 / 1 / 2** |
| 保留結果 | `partial`、`decision_usable=false` | `partial`、`decision_usable=false` |

- TWSE `receipt_evidence_id=35370f0b64be4ac892889b42d598f2ba`，`acquisition_complete=true`，仍有 43 個有效成交價不足的股票及 5 個未收到來源資料。
- TPEX `receipt_evidence_id=7903048cce6e4558bb4bffe596e66a03`，第 7 批 `timeout`，第 8/9 批因 `budget_exhausted` 未送出，`acquisition_complete=false`。**這是確定的 Acquisition Failure，而不只是收盤時鐘過舊。**
- 上述 Receipt ID 是 Canonical `receipt_evidence_id`，**不是**憑空推導的 RawFetchResult row ID；需要由正式 Raw/Canonical 關聯取回內部 per-batch timing。

#### 較早同日 Raw Receipt：即使完整擷取也缺合法價（CONFIRMED HISTORICAL EVIDENCE）

既有 Codex 唯讀調查曾在 10/19 09:22–09:23 驗證 RawFetchResult `796480`（TWSE）及 `796482`（TPEX）：

| 度量 | TWSE 796480 | TPEX 796482 |
| --- | ---: | ---: |
| Received / Universe | 1,074/1,080 | 878/887 |
| Scan Failed Batches | 0 | 0 |
| 合格 Directional | 111 | 105 |
| 合格來源 `z` | 56 | 32 |
| 合格 Session Cache | 55 | 73 |
| Actual Trade Unavailable | 861 | 578 |
| 已保存的 Missing 原始樣本 | 33 | 27 |
| 樣本中 `z='-'` | 33/33 | 27/27 |

原始樣本另有 `v>0`、`ts='0'`、日期正確的案例。這支持 **Provider 在非試撮條件下仍可能回傳累計量但沒有合格成交價**；並不證明本機 Parser 把有效的正 `z` 刪掉。原始樣本有數量限制，不能由樣本還原全體字面 `z` 分布。

**不允許的修補**：以 `pz` 試撮、買賣中間價、昨日收盤、重新查詢的接收時間或過期 Bar Close 冒充當下有效成交。

### 2.3 3406 玉晶光 10/19 一分鐘 K 缺漏（CONFIRMED COVERAGE GAP，ROOT CAUSE UNVERIFIED）

10/20 08:xx 使用正式 `omi.ask`，指定 `trade_date=2026-10-19`、`intraday_interval=1m`，取得：

| 欄位 | 結果 |
| --- | --- |
| Provider／Source | `nstock`／`nstock_minute_stock_data` |
| Materialization | `materialized`、`persisted_hit`、`cache_hit=true` |
| 對應交易日 | 2026-10-19 |
| K 棒數 | **237 根**（237 個不重複分鐘，未截斷） |
| 第一根 | 09:00 |
| 最後一根 | **13:24 起始、13:25 結束、`finalized=true`、Close 1,045** |
| 歷史 Coverage | `partial`、`TW_CANONICAL_1M_HISTORY_INCOMPLETE` |
| 官方日收盤 | 1,045，與最後 Bar Close 相同 |

原先若把 09:00–13:29 當成 270 個一般連續撮合分鐘，表面會有 33 個空桶；但 **13:25–13:29 屬收盤集合競價，不是一般連續撮合時間 K 的預期**。現行 `tw_bar_aggregation.py` 也明確將該 5 分鐘標為 `NOT_APPLICABLE / CLOSING_AUCTION_NOT_TIME_BAR`。

所以應用於這次問題的分母是 **09:00–13:24 共 265 個連續撮合分鐘**：237 已觀測、**28 個未有可確認 K 證據**。缺口如下（分鐘起始）：

```text
10:10
10:19
10:22
10:26
10:28
10:43–10:44
11:09
11:11
11:13
11:19
11:21
11:25
11:32
11:48
11:51
12:00
12:21
12:26–12:28
12:32
12:37
12:41–12:44
12:47
```

**不能直接稱為「28 根本該有的成交 K 被 OMI 弄丟」**：目前沒有逐分鐘與 nstock 原始回應、官方成交或 Provider JobRun 對帳；無成交分鐘本身也可能沒有 Provider 時間 K。現有 `missing_evidence` 定義只是「欠缺可確認證據」，不是已證實損壞。

### 2.4 TAIEX 10/19 歷史分鐘 K 尚未驗證（QUERY ROUTING OBSERVATION）

10/20 08:xx 的一次 `omi.ask` 對 `tw_index:TAIEX` 指定 `trade_date=2026-10-19`，Intraday 部分卻返回 **2026-10-20 盤前** `series_coverage.trade_date`、`snapshot_phase=warming`、0 根。這僅證明該查詢路徑有今日盤前回傳，**不能據此說昨日 TAIEX 分鐘 K 缺失**。

待查：歷史日期參數是否被意圖解析為當前 Session、`market_data_params.trade_date` 是否有傳到 Index Bar Resolver；必要時另以歷史 Bar Service 的明確日期範圍讀取（唯讀）確認。

### 2.5 今日 Reference Price 的警告語意（正常保護／待補來源）

3406 在今日 08:xx 顯示：

`TW_CHANGE_REFERENCE_CORPORATE_ACTION_UNVERIFIED`

Source 並不是判定 **確定發生公司行動**，而是查到前一交易日官方價的 lineage，但**無法建立今日適用的漲跌比較基準**時採保守缺值。不可將 reason code 直接解讀為「3406 發生除權息／公司行動」或系統資料毀損。

## 3. 程式碼 Owner、行號與靜態根因

以下為 2026-10-20 本次實際讀取的檔案行號；以「Repo Root 相對路徑」表示。Source 持續修改時應重新確認行號與版本。

### TW-201（P1）MIS 批次 Timeout／掃描預算耗盡

**Source：**

- `backend/app/config.py:196–200`：TW Index/Breadth Scheduler 預設啟用；Breadth 間隔 60 秒。
- `backend/app/jobs/scheduler.py:1449–1488, 1770–1783`：Breadth 排程收集、同筆交易提交衍生資料；`max_instances=1`、`coalesce=True`。
- `backend/app/market/indices.py:5106–5158`：TWSE／TPEX 各自走 Breadth Refresh（不是一次跨市場 Snapshot）。
- `backend/app/market/providers/twse_mis_current_breadth.py:41–49, 173–348`：`_BATCH_SIZE=100`、Deadline 餘額、Batch Timeout、`budget_exhausted`，輸出 attempted/failed/skipped Evidence。
- `backend/app/market/providers/twse_mis_breadth_evidence.py:17–69`：每個 Venue 僅一個 in-flight IO Slot；`bounded_fetch` 限制 Caller Wait，逾時可能留下仍在執行的底層 Transport，後續會被 `AcquisitionInFlight` 拒絕，避免失控累積背景 Thread。
- `backend/app/market/tw_current_market_capabilities.py:55–79, 147–159`：MIS Breadth Descriptor 最長 Timeout 20 秒且標註 `PUBLIC_BEST_EFFORT_NO_SLA`。

**已證實結果**：TPEX 在 10/19 13:32 有第 7 批 `timeout`、第 8/9 批 `budget_exhausted`。**根因層級已定位為 Acquisition 時限／Transport 未完成，不是 Dashboard 算錯**。更底層究竟是 connect/read timeout、Caller Deadline、MIS 上游延遲、Guard 或序列化成本，需要完整 Raw per-batch `timeout_origin`、`timeout_stage` 與 duration 才能確定。

**設計風險**：在 887 檔（約 9 批）的範圍內，20 秒固定預算對上游抖動敏感；即使有下一輪輪轉，也不保證同一輪完整。

### TW-202（P1）有累計量但缺合法成交價／Rescue 有限

**Source：**

- `backend/app/market/providers/twse_mis.py:57–81`：將多股代碼組成 MIS 請求並讀 `msgArray`。
- `backend/app/market/providers/twse_mis_current_breadth.py:89–169`：解析原始 `z/v/tv/pz/ps/ts`、保留事件時間並計算 Directional。
- `backend/app/market/tw_market_breadth_contract.py:71–180`：只有合法 `z` 或嚴格同日、成交量無增加的合格 Session Cache 才能當實際成交；量變／日期不符時拒絕誤用舊價。
- `backend/app/market/providers/twse_mis_current_breadth.py:420–641`：以真正 Directional 作覆蓋率；Received／No Trade／Unknown 分開。
- 同檔 `:644–750`：Missing-z Rescue 每輪最多 32 檔／1 批／4 秒，含 Backoff 與 Cursor，不承諾修復整個 Universe。
- `backend/app/market/providers/twse_mis_breadth_evidence.py:72–81`：只存每批最多三筆 Missing 原始欄位樣本，無法還原完整原始行情分布。

**已證實**：10/19 09:23 兩個完整 Scan 的有效價依然很少；這是 Provider/Source Availability 缺口，不是單純 Timeout。上游為何如此回傳、是否有權威等價價格來源，**尚未確診**。保留 `partial/null` 是正確的 Safety Contract。

### TW-203（P1 取證／P2 修復候選）3406 Bar 缺口來源不明

**Source：**

- `backend/app/market/providers/tw_intraday_bars.py:283–305`：nstock `minute-stock-data/data` Endpoint，獨立於 MIS Breadth。
- 同檔 `:307–328, 374–460`：逐行解析 `分K`；日期、時間、OHLC 不合格或交易區間不符即略過；依事件時間物化。
- `backend/app/market/tw_bar_service.py:1131–1214`：讀 Canonical Bar、套用交易政策並建構 `missing_evidence` Coverage。
- 同檔 `:1303–1337`：未達 READY 就輸出 `TW_CANONICAL_1M_HISTORY_INCOMPLETE`。
- `backend/app/market/tw_bar_aggregation.py:102–195`：連續撮合缺 Bar 為 `EXPECTED_BUCKET_EVIDENCE_MISSING`；13:25 後 Closing Auction 為 `NOT_APPLICABLE`。
- `backend/app/jobs/taiwan_intraday_demand.py:208–249`：Job 真正完成條件依 Canonical Re-read／Session Manifest，而非單看 HTTP 成功或 Bar 數量。

**待證原因**：Provider 本來未回傳某分鐘、Parser 因非法數據丟棄、資料保存／解決器未採用、Job 過期／Backoff／被中斷、來源真實無成交。**本次沒有讀取 3406 當日具體 JobRun 與完整原始 nstock payload，因此不得指名其中一種。**

### TW-204（P2）完整覆蓋條件與有限資源造成 Repair 延遲或無法 READY

**Source：**

- `backend/app/config.py:205–225`：Tier-A 背景標的 32、同一標的重訪 300 秒、Completed Window 10 檔／300 秒、關盤尾端僅 3 檔等為 Source **預設**，不等於當日 loaded 設定。
- `backend/app/jobs/taiwan_intraday_bar_scheduler.py:28–86, 89–172`：背景 Slot、Admission、5 分鐘每檔重訪、收盤尾端 13:25/13:30/13:33、Completed Session Audit；Audit 實際會排入 Job，**不是純讀查詢**。
- `backend/app/jobs/taiwan_intraday_repair.py:25–55, 83–181, 505–549`：可持久化 Obligation、5 秒 Audit Slice、可保留未完成工作與 Repair Horizon。
- `backend/app/jobs/taiwan_intraday_demand.py:312–479, 495–644`：單股 JobRun、Deadline／Attempts／外部呼叫預算、原 Owner Retry／Backoff；未達 Postcondition 不應冒充成功。

**設計推論**：若來源從不提供部分 1m Bar 且沒有官方無成交資格證明，嚴格 Coverage 會持續 Partial；大量標的時可能需要多輪有限修復。這是需要對實際 Provider 能力與產品 SLA 設計補足的地方，**不能直接當成 Job Service 漏跑**。

### TW-205（P2）重啟會清掉部分 MIS 程序內狀態，但未證實損毀 DB

**Source：**

- `backend/app/market/providers/twse_mis_current_breadth.py:54–57`：`_CACHE`、`_LAST_GOOD`、`_STOCK_ROWS` 為 Python 程序內 Dictionary。
- 同檔 `:371–417`：30 秒 TTL、最後成功快照僅在程序內保留。
- 同檔 `:891–907`：下輪掃描 `scan_next_code` 從 `_CACHE` 讀取／回寫；本次 Source **未發現持久化此 Cursor 的途徑**。
- 同檔 `:1016–1021`：Reset 函式會清空這些記憶體狀態。

**已證明的 Source 風險**：Backend 程序替換會喪失記憶體輪轉位置與 Last-Good Cache；重啟後第一輪的 Universe Coverage 可能與先前不同。**未證明**：這次 10/19 13:32 TPEX 292 檔 Missing 是重啟所造成、Canonical DB 因此遭刪除，或該時間點有重啟。

### TW-206（P2）安全停止／Job Resume 不等於所有 Producer 已保證無缺口

**Source：**

- `backend/app/runtime.py:452–473`：背景 Leader Startup，對殘留 Job 標記、唯讀讀取 Paused Obligation，元件啟動後再恢復。
- 同檔 `:482–600`：Shutdown 的 Scheduler、Job、Collector、Publisher／Session Drain；未全數完成則不能宣稱 REGISTERED_DRAINED。
- `backend/app/jobs/service.py:1072–1098`：大部分殘留 queued/running Job 在 Startup 標記中斷；帶有 Original Owner 安全交接標記的個案例外。
- `backend/app/jobs/taiwan_intraday_demand.py:43–88, 285–309, 620–644`：Intraday 原 Owner 對未實際開始的 Job 保留原來預算並回到 Queued，並非任意重播已發出的 Provider IO。
- `backend/app/jobs/resumption.py:20–86`：Checkpoint／Resume Task 有明確 Allowlist；`run_consumer_demand` 走 Original State Machine，不是 Generic Replay。

**判斷**：安全停止／Job Ledger 有針對性防止重播和重複消耗額度，且晚間 Full-Service Restart 曾完成實機驗收。但是 Source 上具備 Resume 契約 **不代表當天某個 3406 Job 有成功保留、再排入、重試或補足**。應以該 JobRun、原始 Receipt、Stop Request 時序查證。

### TW-207（P2 Observation）昨日 TAIEX Bar 查詢可能有日期路由不一致

- `backend/app/market/tw_bar_service.py:1093–1150`：Historical From/To 與 Presentation Session 的選擇語意。
- `omi.ask` 的 `market_data_params.trade_date=2026-10-19` 於 10/20 08:xx 返回 10/20 今日盤前 Bar Coverage，尚缺對 Index 選擇器／投影契約的逐層檢查。
- **目前只列 UNVERIFIED QUERY ROUTING ISSUE**；禁止把「當日盤前 0 K」誤當成「昨日 K 不存在」。

### TW-208（正常 Safety 行為）今日漲跌參考價未取得

- `backend/app/market/quote_depth.py:2110–2199`：`_project_change_reference` 先尋找今日適用的官方 change basis 或當日 Provider Previous Close；若只有前日 Close Lineage 但無有效今日適用證據，使用 `TW_CHANGE_REFERENCE_CORPORATE_ACTION_UNVERIFIED`。
- 沒有資格時拒絕計算漲跌比率，**不是公司行動已確認**。
- 需進一步驗證今日盤前是否應釋出官方適用 Reference Source，但不應調低 Source Quality Gate。

## 4. Runtime／MCP／Git 快照與版本限制

**10/20 08:18–08:21 的讀取結果：**

| 項目 | 結果 | 解讀 |
| --- | --- | --- |
| Backend `/api/system/health` | HTTP 200，`status=ok` | 服務可回應 |
| Backend `/api/system/readyz` | HTTP 200，`runtime=ok, database=ok` | Runtime／DB 可用；不代表每個 Dataset 完整 |
| Backend Process | PID **43672**，127.0.0.1:8400 | Runtime Control 觀測到 |
| Launcher | PID **25264** | Runtime Control 觀測到 |
| MCP `omi_search` | 本機 `Ready`，Core **41884**、Connectivity **40508** | 通訊可用；不是 Market Quality PASS |
| MCP Build | `db725af64d3fa229` | Loaded Core build observation |
| MCP Source Build | `NOT_PUBLISHED` | 不能證明 MCP Source 已完全 Adopt |
| Runtime Control Bundle | `disk_matches_import=true` | **只涵蓋 Runtime Control Bundle** |
| Application Loaded Release | `UNATTESTED`（但 Backend `owned_start` 有 `APPLICATION_SOURCE_SNAPSHOT` release ID） | 不能擴大宣稱所有模組已證明一致 |
| Writer Preflight | `NOT_REQUESTED`、`unknown_writer_count=3` | 不是目前已排空 Writer 的證明 |
| Git Branch／工作樹 | `main`；讀取時 **32 modified + 16 untracked**，不是乾淨工作樹 | 尚未提交；不表示這些檔案皆是本次問題修改 |

**版本限制**：Runtime 有 `disk_matches_import=true`，只可證明該 Bundle；不能反推所有 Provider、Job 與 Market Resolver 在 10/19 的 Loaded Code 都等於 10/20 讀到的 Source。先前 Codex 已證明晚間 Full-Service Restart 成功，但仍需對精確 Module／Release Identity 驗證。`restart.available=true` 也不是「可以不做安全 Drain」或「資料一定完整」。

## 5. 根因與中斷關係的結論矩陣

| 疑點 | 觀察／程式碼支持程度 | 目前結論 |
| --- | --- | --- |
| 晚間 20:39 的成功重啟造成 13:32 Breadth 缺漏 | **時間上排除** | 不是該次重啟的後果 |
| 其他未掌握的中途停止影響某個 Bar Job | **未驗證** | 需查具體 3406 JobRun／Launcher／Scheduler 時序 |
| TPEX 13:32 Timeout／Budget Exhaustion | **確認** | P1 Acquisition 可用性問題 |
| 即使 Batch 都成功，MIS 原始 `z` 不足 | **確認** | P1 Provider/Qualified Price 缺口；Parser 損壞尚未證實 |
| 3406 少了 28 個連續撮合分鐘的可確認 Bar | **確認** | Coverage Gap；上游或 Job／Persist 根因待分流 |
| Closing Auction 五個時間桶沒有普通 1m K | **符合 Source Contract** | 不應算成 28 個連續撮合缺口 |
| 重啟會失去 MIS 程序內 Cursor／Last-Good | **確認的程式行為** | 有重啟後短期 Coverage 波動風險，但未證明此次因果 |
| 正式 SQLite 資料庫因重啟損壞 | **沒有直接證據** | 不可宣稱；官方日價和大量已物化 Bar 均可讀 |
| 今日盤前 Quote `stale/null`、Official Close 仍可讀 | **確認正常** | Freshness 與 Decision Quality 保護正常 |

## 6. 下次調查最小取證／預期驗收

以下均為**後續要執行的唯讀調查**，本次未進行查詢正式 DB 的逐 JobJoin／Raw Payload 取證，也未執行任何 Repair。

1. **P1／TPEX Batch Root Cause**：以 10/19 13:32:05 的 `receipt_evidence_id` 反查已保存的 Raw Acquisition Evidence，逐 Batch 核對 `timeout_origin`、`timeout_stage`、`remaining_budget_at_start_seconds`、`caller_wait_seconds`、`transport_seconds`、`decode_seconds`、`scan_start_code`、`scan_next_code`。同市場至少比對三輪**同一輪內**的 Received／Directional／Missing／Failed／Skipped，不用跨輪 Union 假裝同時完整。
2. **P1／3406 缺口定點比對**：限定 10/19、3406、1m，比對 nstock 原始 `分K` 時間與 Parser 接受／拒絕記錄、Canonical Observation 的交易日／Bar 時間、Materialization Receipt、Series Resolver 的 28 個 Missing Bucket。若原始來源沒有該分鐘，須額外查證無成交語意或其他權威來源，不能補假 Bar。
3. **P1／JobRun 與 Restart 因果**：限定 10/19 3406 的 `tw.bootstrap_intraday_base_1m`、`tw-demand:`，查 `consumer`、`trade_date`、`desired_coverage_end_at`、`attempt_count`、`external_call_budget_used`、`reason_code`、`status`、`created_at/started_at/ended_at`；與當日 Launcher Restart Request、Scheduler Pause、服務 PID 變更及 Raw Receipt 時鐘交叉比對。證明哪一個 Job 確實中斷，才能說是重啟造成缺口。
4. **P2／Coverage 語意**：離線增加可重現 Fixture，確認 Provider 空分鐘、真無成交、Closing Auction、Parser Reject、Source Missing 的差異；維持 Fail Closed，不把 Missing 改成 0 或捏造 Close。
5. **P2／MIS Cursor 持久性**：設計獨立持久化 Scan Cursor／Last-Good Source State 的風險評估與離線重啟測試，避免一次重啟重置公平輪轉；不改變單輪收據原始範圍，也不自動擴大 Provider Quota。
6. **P2／Index 日期查詢**：單獨核對 TAIEX 10/19 歷史 Bar 的 Router／`market_data_params.trade_date`，與今日 10/20 盤前 `warming/0` 分開驗證。
7. **驗收標準**：Source/Runtime/Live/Product 分開；Reader 使用正式 `omi.ask`、`cache_only`、`refresh_policy=off`；書面記錄 PID、loaded source、receipt、event/received time、Coverage Reason、JobRun Reason；只有真正改善合格 Data/Bar 才把 Gate 升成 PASS。

**G0–G5 暫定狀態（非重新執行全部測試）**：G0 **PARTIAL**（缺 Raw/Job 完整 Root Cause）、G1 **PARTIAL**（Acquisition）、G2 **PARTIAL**（合格 z／Live Quote）、G3 **PARTIAL**（3406 237 根但 28 個缺口待定位；由先前 0 根改善）、G4 **PARTIAL**（正式 Consumer 如實揭露；TAIEX Historical Routing 待驗）、G5 **BLOCKED**（整體仍不可封版）。先前 G5/G6/G7 與 Job Cooperative Source 測試可以作歷史回歸證據，**本次沒有重跑**，且 Dirty Worktree 不能直接繼承成「目前整份 Source PASS」。

## 7. 相關工程紀錄

- [`TW_INTEGRATION_ISSUES_2026-10-16.md`](../../../TW_INTEGRATION_ISSUES_2026-10-16.md)：前一輪 MIS z 缺價、Batch Timeout、Consumer 覆蓋的歷史事故紀錄。
- [`TW_INTEGRATION_G8_REPAIR_PLAN_2026-10-16.md`](../../../TW_INTEGRATION_G8_REPAIR_PLAN_2026-10-16.md)：方案 A 與 G8 Gate，屬計畫／歷史進度，不自動表示今日已完成。
- [`TW-20261011-post-restart-coverage.md`](TW-20261011-post-restart-coverage.md)：10/11 Job／Completed Audit 的另一份歷史觀察，不能直接當本事件根因。
- [`MarketTemporalContract.md`](../../architecture/MarketTemporalContract.md)：Market Phase、Event Time、Received Time、Finalization／Release 區分。
- [`RuntimeControl.md`](../../architecture/RuntimeControl.md)：安全停止、Restart、Pause／Resume、Source Identity 的 Owner Contract。
- Codex Bridge 歷史任務（只作二級佐證）：`fd998cb0-7c3d-4a5c-b580-cfb17ea82a50`（09:23 Raw 收據）、`0b9d8eb3-e6d2-440e-bd18-c378207859bf`（18:10 未成功重啟）、`f97f1f54-1edc-4ad2-907a-9f90079c0acb`（20:39 成功重啟）。

---

**保存註記**：本輪僅新增這份 Markdown 作為可追溯取證；未修改既有 Source／Runtime／Job／正式資料、未觸發交易、未觸發 Refresh 或重啟、未 Commit／Push。後續所有新的 Root Cause 必須以對應 Raw Receipt、JobRun 與 Source Version 回寫本文件，不能把推論擅自升格為 CONFIRMED。


---

## 8. 追加取證｜2026-10-20 08:34–08:40 盤前試撮與正式 OMI 查詢

> **本節為當日新時間點補充**，保留前面 §0–§7 對 2026-10-19 盤後 TPEX Breadth 與 3406 歷史分鐘 K 的原始取證；不要將 10/19 13:32 與 10/20 08:34 視為同一輪。所有鐘點皆為 Asia/Taipei。\
> 第一階段 Runtime／Dashboard／Source 為唯讀；第二階段對四檔個股**明確以 \`refresh_if_missing=true\` 允許受限 Provider Acquisition／Market Cache 更新**（不是 cache-only）。未重啟、下單、執行 Repair、Backfill、DB Schema 修改、Commit 或 Push；本次 Repo 只追加本工程紀錄。\
> **證據分級**：Live API 回應是 Runtime 觀察；原始碼屬 Source Behavior；未查正式 DB Raw／JobRun 的原因必須標 UNVERIFIED。

### 8.1 Runtime 與 MIS 批次：本輪成功，不等於歷史 P1 已解

| 項目 | 本輪實際證據 | 解讀 |
| --- | --- | --- |
| Backend | PID 43672，127.0.0.1:8400，\`/api/system/health\` HTTP 200、\`status=ok\` | API 可回應；不代表資料完整 |
| Launcher | PID 25264；Runtime Control \`disk_matches_import=true\` | 僅證明 Runtime Control Bundle；Application \`loaded_release_identity=UNATTESTED\` |
| Writer Preflight | \`NOT_REQUESTED\`、\`unknown_writer_count=3\` | 未發 Stop/Drain 時不能當作異常停止證據 |
| Market Session | \`trade_date=2026-10-20\`、\`preopen\`／\`observing\` | 08:30–09:00 試撮辨識正確 |
| TWSE MIS | 08:34:34 event，11 attempted／0 failed／0 skipped；Received **1,075/1,080** | 本輪 Acquisition Complete；不是成交方向全量 |
| TPEX MIS | 08:34:41 event，9 attempted／0 failed／0 skipped；Received **878/887** | 本輪 Acquisition Complete；不能回溯修正 10/19 的 7/1/2 |
| Fallback／Rescue | 雙市場 \`fallback_used=false\`、\`missing_z_rescue=not_needed\` | 盤前缺正式 z 本來常見，不代表 10/19 缺 z 問題修好 |

**TW-201 狀態**：10/19 13:32 TPEX Batch 7 timeout、後 2 批 budget_exhausted 的 P1 仍保留；10/20 試撮這輪 **PASS** 僅證明沒有在此時間窗重演。TW-202 合格 actual \`z\` 缺價需待 09:00 後的連續撮合新收據另驗。

### 8.2 盤前可分類廣度 ≠ 正式成交漲跌廣度

| Venue | Registered Universe | Provisional Auction 可分類（上漲／下跌／平盤） | Auction 未分類 | 當日 Actual Trade Directional | MIS Received |
| --- | ---: | ---: | ---: | ---: | ---: |
| TWSE | 1,080 | **610**（372／98／140；約 56.5%） | 470 | 0（盤前沒有當日正式成交） | 1,075 |
| TPEX | 887 | **319**（205／60／54；約 36.0%） | 568 | 0（盤前沒有當日正式成交） | 878 |

- \`resolved_breadth.auction_breadth.price_semantics=auction_indicative\`，\`is_provisional=true\`、\`decision_usable=false\`；\`resolved_breadth\` 的正式方向另由 \`current_last_trade_vs_reference\` 定義。不能拿 provisional 610/319 當正式開盤上漲家數，也不能將 Unknown 當平盤、NoTrade 或資料庫毀損。
- 10/20 全市場批次接收覆蓋約 99% 並不代表 99% 的股票有試撮價／實際成交價；價與來源接收率是不同分母。盤前收到但沒有 \`pz\` 有效 Match，是可能正常的資料限制。
- \`backend/app/market/tw_market_dashboard.py:L915–1008\` 兼容欄 \`breadth\` 標示 \`deprecated=true\`、\`canonical_ref=resolved_breadth.<VENUE>\`、\`decision_usable=false\`；正式 Headline 使用 \`resolved_breadth\`。目前未見正式 Frontend 一定錯用舊欄位的證據，列為 Consumer Risk 而非已確診 UI Bug。
- \`trading_calendar.py:L135–217\` 的 \`presentation_session.next_transition_at=13:33\` 是**呈現狀態下一次切換**而非 09:00 開盤時間；不是時段判定 Bug。

### 8.3 個股試撮四檔驗收：有正確資料，但須區分刷新策略

首次透過 \`omi.ask\` 查詢 2330、2308、3264、6456，雖採 \`realtime_policy=prefer_live\`，**未明確要求** \`refresh_if_missing=true\`，四檔 \`quote.auction\` 都因當前合格快取不足回 \`missing\`；2330 僅見 07:50 快照，其餘部分為昨日 completed-daily／stale。Outward Answer 明示「本次未要求更新，未查詢來源」，因此**不能宣稱 Provider 故障或沒有今天試撮**。

之後明確允許 bounded refresh、由正式後端 Owner 取得四檔有效當日 Indicative Match：

| Stock | 昨收 TWD | 試撮 Indicative Price TWD | 試撮漲幅 | Event Time | Indicative Lots |
| --- | ---: | ---: | ---: | --- | ---: |
| 2330 台積電 | 2,420 | **2,485** | +2.69% | 08:37:14 | 995 |
| 3264 欣銓 | 258 | **259.5** | +0.58% | 08:37:27 | 16 |
| 2308 台達電 | 1,640 | **1,685** | +2.74% | 08:38:29 | 62 |
| 6456 GIS-KY | 84.4 | **86** | +1.90% | 08:39:22 | 124 |

均為 \`provider=twse_mis\`、\`source=twse_mis_quote_depth\`、\`AUCTION_INDICATIVE_OBSERVED\`、\`freshness=current\`、當日 Reference Lineage；\`quote.auction.status=current\`，但 \`quote.snapshot.last_trade_available=false\`、\`decision_ready=false\`。**這是試撮事實查詢 PASS，絕非當日真實成交或交易執行價格。**

**源碼稽核**：\`backend/app/ai/answer_composer.py:L915–1015\` 的 \`_auction_acquisition_text()\` 與 \`build_quote_consumer_answer()\`，和 \`backend/app/ai/decision_envelope_v4.py:L4161–4242\` 的 \`refresh_reconciliation\` 將「未要求／未執行／完成／失敗／證據未知」與「有沒有合格試撮 Match」分開；這是合理的 Safety Behavior。相應 \`backend/tests/test_tw_preopen_quote_answers.py\` 存在但目前是 **untracked、未執行**，兩個 AI 來源檔亦為 dirty diff，不可把磁碟測試存在當成當前版本全部封版證據。

**TW-210（Observation / P2 Product UX Gap）**：消費者易將 \`prefer_live\` 誤認為已觸發 Provider Fetch；資料能否刷新需看 request \`refresh_if_missing\`、\`refresh_requested / attempted / completed\` 與讀取政策。若要改善，應在已授權的正式入口提供受限 Refresh／Fill Plan 與明確狀態，**不可讓 GET/cache-only 讀取路徑偷偷 Fetch/Write，也不得在 MCP/Frontend 直接另造 Provider**。

### 8.4 TW-209（P2 Confirmed Functional Gap；資料根因 Unverified）：TAIEX 試撮指數估算 Baseline 不一致

**同一 08:34 台灣 Dashboard Snapshot：**

- **正確的正式指數**：\`resolved_indices.TAIEX=46,822.08\`，交易日 10/19，\`selected_candidate=completed_daily_bar\`、\`official_close_confirmed=true\`、\`finalization=final\`，Provider \`twse_index_daily_ohlc\`，Source \`twse_indices_report_mi_5mins_hist\`。
- **但 legacy 非官方盤前估算**：\`indices.TAIEX.status=unavailable\`、\`estimate=null\`、\`baseline_close=null\`、\`baseline_trade_date=null\`，即使 Component Universe=1,086、Eligible=1,075（98.99%）、Observed=610、\`observed_weight=97.71%\`。
- **這輪確定的計算層阻擋**：\`estimate_cap_weighted_index()\` 要求 baseline>0、total_reference_cap>0、observed_count>0、eligible/universe ≥ 80%。除了 \`baseline_close\` 為 null，本輪其他門檻可由已回傳的統計判定已滿足。**不是單純「因全市場試撮覆蓋太少而不得估算」**。
- TPEX 相同公式可得 \`baseline=394.05\`（10/19）、試算 \`≈399.7479\`（+1.446%），但 \`provisional/official=false/decision_usable=false\`，約 **27.99%** 參考權重無合格 Match，不能當官方盤前指數。

**追到實際兩條資料讀取路徑：**

1. \`backend/app/market/tw_market_dashboard.py:L628–648\` 的 \`_latest_index_baseline()\` → \`read_taiwan_official_index_series(index_id, to_date=previous_taiwan_trading_day, limit=1)\` → \`official_index_platform.py:L355–390\` → \`official_index_repository.py:L57–158,L231–279\`。這條讀取 **\`MarketIndexDailyStat\`**，依 \`SourceRegistry\`、\`RawFetchResult\`、來源識別、13:35 Release 後取得時間、\`close_value/price_change\` 等資格規則決定是否回合格 Official Index。
2. \`backend/app/market/indices.py:L4754–4985\` 的 \`get_market_index_summary()\` → \`TaiwanBarService(db).read_bars(instrument_id=index_id, interval="1d", include_partial=False)\` → \`resolve_taiwan_index_truth()\`，能從 **已完成 Daily Bar** 選出 \`completed_daily_bar\`；\`tw_market_dashboard.py:L770–823\` 的 \`_build_resolved_indices()\` 讀這條得到 10/19 官方 46,822.08。
3. \`tw_market_dashboard.py:L665–751\` 的 \`_build_index_estimates()\` 仍依第一條獨立 \`baseline\` 做 Proxy，這使同一 Dashboard 的「官方前收顯示」與「非官方估算基準」可用性分歧。**已確認是 Source of Truth / Projection Consistency 風險及當日 Estimate 功能缺口**；但未唯讀 JOIN \`MarketIndexDailyStat\`、\`SourceRegistry\`、\`RawFetchResult\`，仍無法指認究竟是該日 Record Missing、Release Gate、Source Identity、所需欄位欠缺、Resolver 過濾哪一種。
4. **模型本身仍有獨立 Accuracy Debt**：\`component_universe_source=stock_master.active_stock_proxy\`，不是當日官方指數成分檔；TAIEX 股數資料 \`shares_as_of=2026-05-13\`，公司行動及 divisor adjustment \`not_verified\`，Missing Match 以零 Delta（不重新正規化權重）計算。因此即使修好 Baseline，也**禁止升格為官方或 execution-grade 指數**。

**修復方向**：先用唯讀 Source/DB 對帳釐清是寫入/資格/來源的哪一段缺口。優先讓盤前估算採用**既有 Canonical Index Resolver 所認可的前一交易日 final official evidence**，或補正既有正式 \`tw.market_index.daily\` Producer，使兩條合法 Source 在 Trade Date、Authority、Release 與 Lineage 上一致。禁止直接抄 Headline 數字、硬塞昨日收盤、放寬 Official Release Gate、新增第二套 Index Cache 或在 Frontend / MCP 自己估算。


### 8.5 與 3406 原事件對帳：目前仍是 Missing Evidence，沒有定出 Source Loss 根因

本輪針對 3406 指定 \`trade_date=2026-10-19\`、\`intraday_interval=1m\`、\`realtime_policy=cache_only\`、\`refresh_policy.mode=off\` 再讀正式 \`omi.ask\`，結果仍為 \`point_count=237\`、\`is_partial=true\`、\`cache_status=persisted_hit\`、\`provider=nstock\`、\`source=nstock_minute_stock_data\`、最後起始分鐘 \`13:24\`，沒有新證據能修正原 §2.3 所列 28 個 Missing Bucket 的分類。

**真實資料流（由目前 Source 確認）**：

\`\`\`text
nstock minute-stock-data / 分K
  -> providers/tw_intraday_bars.py 解析日期、分鐘、OHLC、量與 09:00~13:25 的 regular session
  -> BarObservation(1m, start_at/end_at, SourceLineage, finalization)
  -> 正式 Refresh/Materialization Transaction / JobRun owner
  -> Canonical Bar Store
  -> tw_bar_service.py + tw_bar_aggregation.py
  -> intraday.bars / omi.ask (cache_only, partial / missing_evidence)
\`\`\`

- \`backend/app/market/providers/tw_intraday_bars.py:L350–460\`：原始 \`分K\` 日期或價位缺失、超過 Request Time Window、不是 Regular Session 的行會被跳過；**沒有讀 Raw Payload，不能判定 28 個分鐘是否在這一步被 Drop**。每筆合格 K 的 \`BarObservation\` 保留 event/start/end、量與來源 hash。
- \`backend/app/market/tw_bar_aggregation.py:L102–195\`：在截至 \`as_of\` 已經完整經過的連續撮合分鐘中，無 K 記 \`EXPECTED_BUCKET_EVIDENCE_MISSING\`；13:25–13:29 Closing Auction 另記 \`NOT_APPLICABLE\`。因此當日連續撮合分母為 265、不是誤加尾盤 5 分鐘的 270。
- \`backend/app/jobs/taiwan_intraday_bar_scheduler.py:L28–86, L89–172\`：當日背景排程有 Slot／per-stock revisit deadline／15 秒 admission polling，收盤尾端僅有限 Target；\`audit_completed_taiwan_intraday_coverage\` 可 dispatch Demand、讀 Job／重建 Obligation，**不是純讀函式**。
- \`backend/app/jobs/taiwan_intraday_demand.py:L208–249, L253–340\`：\`_reread\` 以 Canonical Series 的 trade date、\`snapshot_phase\`、history coverage 等建立 Postcondition；\`_finish\` 未達 Postcondition 會保留 partial/error，而不是將 HTTP 成功當完成。Job Dispatch、Retry、Original Owner Handoff 的狀態需要看當日確切 JobRun。
- \`backend/app/jobs/service.py\` 正有未提交 Cooperative Pause／Resume／Continuation 相關 Diff；\`taiwan_intraday_demand.py\` 也有 unstarted handoff Diff。**現在磁碟 Source 內容不能直接證明 10/19 的每筆 3406 Job 跑到哪裡、是否採用當時載入版本，也不能替代正式 Job Ledger**。

**維持原 TW-203/204/206 判斷**：現象 confirmed（237 根、28 個未證實分鐘）；Provider 是否沒有那個分鐘、真無成交、Parser Reject、持久化未成功、Job 逾時／恢復未完成、某次 Restart 是否影響某個 Job 均 UNVERIFIED。不得補 0 量 K、複製最後 Close、以別檔股票時間列補齊，或因晚間 20:39 的成功重啟直接歸咎為缺口起因。

### 8.6 Source Health 與其他限制：不把 Partial 一律當程式錯誤

正式 \`omi.read_source_health(market="tw", cache_only)\` 的台股 operational 範圍，\`market_breadth\` (TAIEX/TPEX)、\`taiwan_market_minute_state\`、\`taiwan_stock_quote_snapshot\`、\`market_daily_price\` 仍含 \`partial\`；\`market_daily_price\` 最新 10/19 日價，有 Partial Coverage，並非今日盤前已應有最終版 10/20 日價。這些健康欄位牽涉不同資料集、資料粒度和發布時間，不等於同一缺陷反覆計數。

針對第一次市場查詢選了 \`target=market\` 卻明確要求 \`quote.auction\`，正式 Manifest 回 \`unsupported_target_scope\`（支援的是 **stock / tw_index**）：**這是呼叫端 Capability Scope 選擇錯誤，不是 OMI 市場行情壞掉**。全市場試撮應讀 Dashboard \`auction_breadth\`，個股試撮應用 stock target 的 \`quote.auction\`；\`tw_index:TAIEX\` 的 \`quote.auction=not_applicable\` 也不可拿來否定 Dashboard 的非官方 proxy estimate（TW-209 為獨立議題）。

### 8.7 TW-211（P2 Architecture Risk）：Dashboard 相容欄位與指數估計成熟度

- \`indices\`：Legacy 盤前估算 \`omi.tw_preopen_index_estimate.proxy.v1\`，\`provisional=true, official=false, decision_usable=false\`；不是 \`resolved_indices\` 的替代正式行情。
- \`resolved_indices\`：經現有指數 Truth Resolver 確認的官方前收/當日有資格候選，\`headline_index_field=resolved_indices\`。
- \`breadth\`：相容用的 Legacy 欄，標 \`deprecated=true\`，不能代替 \`resolved_breadth\` 的正式成交定義。
- \`resolved_breadth.auction_breadth\`：可以顯示盤前部分指示性方向，但不可升格成實際成交，也不能用其 completeness 代替 Provider Received Coverage。
- 即使 TW-209 成功給 TAIEX Proxy 一個合格 Baseline，目前該模型的成分 Universe 是活躍 StockMaster 代理集，不是權威、定期的正式指數成分檔。TAIEX 股數基準 2026-05-13，TPEX 2026-10-19；未驗證配股／拆股／調整後 Divisor。當日無法當交易級估值。下游需維持明確 Source／Methodology／Limitations，必要時停用非官方 proxy Headline。

### 8.8 新舊 Issue ID 統一狀態（本節不更改原歷史證據）

| ID | 分類／優先 | 10/20 目前判定 | 下一步 |
| --- | --- | --- | --- |
| **TW-201** | Confirmed Acquisition Failure／P1 | 10/19 TPEX Timeout/Budget Exhaustion 已證實；10/20 08:34 雙市場單輪成功，**未結案** | 原 Receipt per-batch timeout_origin/stage＋09:00 後三輪觀測 |
| **TW-202** | Provider / Qualified Actual Price Gap／P1 | 10/19 \`z='-'\`/有量的證據保留；10/20 盤前試撮非 actual z，無法當修復證明 | 常態連續撮合 \`z/v/tv/pz\` 與分類對帳 |
| **TW-203** | 3406 Coverage Gap／P1 取證、P2 修復候選 | 10/19 237/265、28 個 \`missing_evidence\`；本輪不變 | 原始 nstock／Parser／Bar Store／JobRun 逐分鐘 JOIN |
| **TW-204** | Scheduler/Repair Capacity Risk／P2 | Source 有界機制明確；未證實哪筆 3406 Job 被卡 | 限縮 3406 的 Demand／Result／Backoff |
| **TW-205** | Restart Ephemeral Cache Risk／P2 | 沒有新 Restart；TPEX 10/19 13:32 早於晚間 20:39 重啟 | 保留歷史時間因果；必要時評估 Cursor 持久化 |
| **TW-206** | Job Stop/Resume Boundary／P2 | 存在新的 dirty Source；本輪未跑 Quiescence / Resume Live | 不沿用 Source 到 Runtime 的未證身分 |
| **TW-207** | TAIEX 10/19 歷史 1m Routing／Unverified P2 | 未重測，與 TW-209 Baseline 不同問題 | 明確指定日期核對歷史 Bar |
| **TW-208** | 3406 今日 Change Reference／Observation | 其他四檔昨收已正常，但**不代表 3406 也恢復** | 3406 自身的 Official Applicable Basis/Corporate Action 證據 |
| **TW-209（新增）** | **TAIEX 盤前估算缺基準／Confirmed Functional Gap P2** | Official \`resolved_indices\` 有 10/19 正式值，但 Estimate Baseline null；兩條資料路徑有可用性分歧 | \`MarketIndexDailyStat/Raw/Source\` 與 \`TaiwanBarService 1d\` 的權威證據對帳 |
| **TW-210（新增）** | Auction Refresh Policy/UX／Observation P2 | 初次未授權 Refresh 而缺快取；明確 bounded Refresh 後四檔 current | Refresh Request／Attempt／Receipt／Answer 有序狀態驗收 |
| **TW-211（新增）** | Legacy Projection／Index Proxy Accuracy／Architecture Risk P2 | 相容欄位已有 deprecated 與 provisional 警告，尚無已證實正式 UI 誤用 | Consumer contract parity；維持非官方、非決策級標籤 |

### 8.9 修復排序與最小驗收 Gate（**計畫，不代表已施工**）

1. **R1：TW-209 Index Baseline（定點唯讀根因）**。只看 \`index_id=TAIEX, trade_date=2026-10-19\`：\`MarketIndexDailyStat\` / \`RawFetchResult\` / \`SourceRegistry\` 的存在、\`fetched_at\`、source_name、必要 values、release eligibility；對照同日 \`TaiwanBarService(1d)\` \`completed_daily_bar\` 的 lineage/qualifier。需知道為何 \`_latest_index_baseline()\` 真正給 null，才決定修 Producer/Reader 或統一為既有 Official Index Resolver。
2. **R2：TW-209 離線回歸**。Fixture 覆蓋（a）兩條 Official Daily 均合格、（b）僅 Canonical 已完成 1d 可讀、（c）前日錯誤 Source、（d）資料在 13:35 Release 前取得、（e）缺前一交易日、（f）TPEX 正常同時 TAIEX 缺 Baseline。驗證正確 Trade Date、Exchange Authority、Finalization/Release；不可以 Yesterday Display Value 無資格回填；所有非官方指數估計 \`decision_usable=false\`。
3. **R3：TW-210 受限試撮 Refresh / Answer**。同一股票跑 \`cache_only\`、\`prefer_live\` 但沒有明確取得授權、明確 \`refresh_if_missing\` 並限制外部 calls 的三情境。逐項驗證 \`refresh_requested/allowed/attempted/provider_succeeded/selected_freshness/decision_ready\`；由 Server 對外一份相同 v4 Evidence，Cache-only 不產生 Fetch/Write。僅針對目前 dirty AI diff 與 untracked Regression Test 執行 targeted tests，不重跑無關套件。
4. **R4：TW-201/TW-202 09:00 後 Live Gate**。TWSE/TPEX 至少三個自然相鄰輪次、各輪各 Venue 保留 Raw/Canonical Receipt 與 \`received, directional, missing_z, valid_no_trade, provider_missing, failed, skipped\`；驗證盤前 Auction 退場、Regular Actual Price 生效；不能跨輪合併分母，不變更或放寬合格 \`z\` 的 Quality Gate。
5. **R5：TW-203/204 3406 1m 的最小對帳**。對 10/19 原 §2.3 的 28 個分鐘逐個比較 nstock 原始 \`分K\`、Normalizer Reject Reason、Canonical Bar Store、JobRun／Pause Resume Ledger、Consumer Coverage。先分出真實 Provider 缺價、真無成交、Parser Dropped、Job Budget/Retry、Persistence 問題，**未取得 Raw/Job 後才能指派修法**。禁止補零量或虛構 K。
6. **R6：驗收證據可繼承條件**。舊 G5/G6/G7 及 Safe Restart 的 Source/Runtime 收據可作歷史基準，但要核對相同 Release/Dependency/Schema/Config。Index、AI、Job 新 dirty diffs 只能在 affected dependency scope 重新測，不能因歷史通過便宣布本次已正式 Loaded。Commit/Push 需另外明確授權。

**截至 10/20 這輪調查 Gate 判定**：

| Gate | 狀態 | 證據 |
| --- | --- | --- |
| Runtime API Liveness | **PASS（限定該查詢時間）** | \`/api/system/health\` HTTP 200、MCP OMI Query 成功 |
| Opening Auction Stock Facts | **PASS（4 檔／明確 bounded Refresh）** | 今日試撮與 Reference Lineage，全部 \`current\`；\`decision_ready=false\` |
| Market Preopen Acquisition | **PASS（僅 08:34 這一輪）** | TWSE 11/0/0、TPEX 9/0/0；各自 Provider Received 近 99% |
| TAIEX Provisional Index Estimate | **FAIL／P2 Functional Gap** | \`baseline=null\`、\`estimate=null\`，即使 10/19 Official Close 可讀 |
| Full Market Qualified Actual Trade | **NOT APPLICABLE（08:34 仍盤前）／待開盤驗收** | \`resolved_breadth\` 當時正式成交方向 0，非事故 |
| 10/19 TPEX 盤後 Acquisition | **OPEN／P1** | 歷史 7/1/2 Timeout 與 Budget Exhaustion |
| 10/19 3406 1m Coverage | **PARTIAL／原因 UNVERIFIED** | 237/265；28 個 \`missing_evidence\` |
| Runtime Loaded Release Identity | **UNVERIFIED** | Runtime Control Bundle hash 相符，Application Identity 未證 |
| 整體封版 | **不建議封版** | TW-201/202/203 歷史 P1/P2 尚未取完根因，TW-209 新功能缺口 |

**附註**：本輪沒有正式 Backend Test Run、Build、指定 Raw Join、完整 JobRun Root Cause 或盤中 Live Acceptance；不得將 Source Reading／單輪試撮的通過誤寫成修復已完成。此文為同一份 10/20 Markdown 的持續追加，保持已存在的 10/19 盤後事故及重啟時序不可覆蓋。


---

## 9. 追加回顧｜「OMI Runtime 盤中驗證」問題來源與根因分層（2026-10-20 13:17 Asia/Taipei）

> **用途**：把 10/19–10/20 盤中驗證、後續唯讀根因審計及 Source 修補結果收斂於原事故紀錄；不改寫 §0–§8 的歷史時間點判斷。\
> **證據來源**：本檔既有正式觀測、`TW_INTEGRATION_ISSUES_2026-10-16.md`、`docs/exec-plans/active/tw-missing-values-source-contract-20261020/{Plan,Progress}.md`、Codex Bridge 已保存之唯讀稽核／實作結果，以及本輪定點 Git Diff 和原始碼讀取。**並非已取得完整逐字對話或重新執行所有 Runtime/Live 查詢**。\
> **最新正式驗收取樣**：本節的 Source/Runtime Gate 以 10/20 **12:11** 已存證據為準；13:17 為整理時間，不冒充 13:17 的行情快照。\
> **本次工作邊界**：只整理證據、核對 Source／Diff 並追加此 Markdown。沒有修改業務 Source、正式資料庫、交易、外部行情刷新、Runtime 重啟、Commit 或 Push。

### 9.1 為什麼會一直出現「有抓資料，但分析缺值」

這不是單一故障，至少有五個不同關卡，不能把每次 `partial/null/stale` 都記為同一個 Bug：

1. **MIS Acquisition（TW-201）**：100-code 分批掃描受單輪約 20 秒 Deadline／同 Venue IO Slot 約束；TPEX 10/19 13:32 Receipt／Raw `801585` 的第七批起始僅餘 **0.938 秒**，caller wait **0.943 秒**，`timeout_origin=acquisition_deadline`；後兩批為 `budget_exhausted`。可確定是整輪取得預算耗盡，**不可進一步斷言為 socket connect/read timeout**。
2. **Provider Qualified Actual Trade（TW-202）**：即使 Batch 成功，大量原始 `z` 沒有有限正值。10/20 09:51:35 TWSE `817612` Received **1075/1080**、Directional **144**、合格 z **61**、合格 Cache **83**、actual unavailable **902**；09:51:44 TPEX `817619` Received **878/887**、Directional **167**、合格 z **62**、合格 Cache **105**、actual unavailable **562**；兩筆皆無 failed/skipped Scan。聚合證據中原始 z 非有限正值分別 **1011/1075**、**812/878**；有界 missing 樣本 **33/33**、**27/27** 為字面 `z='-'`，部分同時有 `v>0, ts='0'`。**樣本不可外推全市場字面 z 分布；MIS 為何省略仍 UNVERIFIED，Parser 刪除正價未獲證實。**
3. **Session Cache/Quote Freshness（Source 正常的安全限制）**：新累計量增加卻沒有新合格 z 時，舊成交價不能因新 receipt 而改寫事件時間。保存的 `817647`：2330 新量 **6146** 對舊價量 **5454**，3406 新量 **3675** 對舊價量 **2683**，均拒絕沿用舊價為 current。2883 曾取得合格新 z，但查詢時事件 age **34 秒**仍超過 Quote **15 秒**決策 freshness，因此 `decision_price=null` 符合契約。全市場 Breadth 預設約 **60 秒輪詢＋掃描時間**，無法保證個股隨時滿足 15 秒時效；這是服務級別／資料生產能力缺口，不是把 null 改成昨收或放寬 freshness 可以修正的問題。
4. **持久化不是本批次主要丟價位置**：`817612` Raw／Canonical 都有 **736** 個 price states（verified 144）；`817619` 兩邊都是 **448**（verified 167），事件／價格／量／verified 對帳無數值差異。因此這兩筆的可用性下降源於上游缺合法價與資格淘汰，**不能稱為已證實 Raw → Canonical 遺失**。
5. **下游是不同 Coverage 語意**：Market Breadth 單輪、Sector rolling state、Quote 單股、NStock 1m、Official Daily、Fugle Index、Institutional、Turnover 是不同 capability／時間戳／來源權威；`received`、`directional`、`ranking_eligible`、`decision_usable` 不可混用，不可跨輪 Union 冒充同時完整。

**10/20 新 Raw 補強**：11:13:32 TWSE `819856` 的原始 Scan returned 1080、missing-z 1001、qualified actual-z 71，0 failed/skipped；11:13:37 TPEX `819859` returned 887、missing-z 816、qualified actual-z 60，0 failed/skipped。這是**已保存背景 Receipt 的唯讀回查**，不是本次執行的新單股 MIS 1/10/100 Live 測試。另有多輪 Timeout 原始收據，兩種原因確實並存。

### 9.2 1m K 缺口：已進一步縮小 10/19 根因，但與 10/20 未生產不同

- **10/19 的 3406（TW-203）**：新唯讀 Raw `804181` 對帳顯示 nstock `分K` **238 列**，其中 13:30 一列不屬一般連續撮合時間棒；其餘為 **237 個有效且不重複分鐘**，全部 **237** 均已進入 Canonical，Raw 合法分鐘對 Canonical 的漏存數為 **0**。09:00–13:24 的連續撮合分母 **265**，仍有 **28 個 Raw 未提供的可確認分鐘**。這已排除「這份 Raw 中 237 根被 Parser／Persistence 丟失」的假說；**尚不能判定 28 分鐘是真實無成交還是 nstock 未提供**。Job `151976` 保留 `partial / CURRENT_SESSION_BASELINE_NOT_READY`，不能把 HTTP 成功稱為 Coverage READY。
- **10/20 的 3406（Tier-A 生產範圍）**：正式審計發現 3406 是 active ordinary stock、也在 watchlist，但當日背景 Tier-A `next_due_at` 32 檔名單沒有 3406，查詢時也沒有當日對應的 1m Materialization Job／Bar。Tier-A 優先序與硬上限意味**加入 Watchlist 不保證進入背景生產**；這支持當日「未產生 K」的主要原因是 Admission Scope，而不是本地已取得資料突然消失。當時完整 candidate 排序未重建，不能宣稱所有其他 Lease/持倉決策已逐項驗證。
- 兩天原因**不相同**：10/19 已取得的 Raw 沒有 28 個分鐘；10/20 則沒有對該檔啟動當日背景 K 生產。Closing Auction 13:25–13:29 不應被算成 1m 連續撮合缺失。不得自動合成 0 量 K 或複製最後 Close。

### 9.3 新確認的三個程式 Bug（Phase A 已修磁碟 Source，Runtime 尚未採用）

| Bug / Owner | 修補前已確認的錯誤與證據 | 已存在的 Source 修正／剩餘 Gate |
| --- | --- | --- |
| **A1 / Breadth 試撮分類**：`tw_market_breadth_contract.py`、`tw_intraday_state.py` | `AUCTION_INDICATIVE_ONLY` 且 `v=0` 可能誤列 `valid_no_trade`；TPEX `817619` 的 149 筆 valid-no-trade 有 **3 筆**試撮不具正式無成交資格 | 只有具 `ACTUAL_TRADE_EVIDENCE_MISSING` 合格證明才列 valid-no-trade；離線 Replay TPEX **149→146**、actual-unavailable **562→565**，Universe/Directional 不變。Diff 已核對；**非正式 Runtime 修復證據** |
| **A2 / 法人多日完整性**：`tw_screening.py` | `_metric_value` 跳過 null 但 `observed_periods=len(rows)`，使 `[10,null,20,null,30]` 被算 5/5 完整；正式資料有 **25（5d）／52（20d）** 檔存在 false-complete | 只對有合法 metric 值的日期計數、保留 `missing_value_days`，合法 0 仍可計入；Source Replay 完整窗 **5d 1660→1635／20d 1528→1476**；現役 Runtime 仍見舊數值 |
| **A3 / JobRun 時區**：`taiwan_intraday_demand.py` | `started_at` 可直接寫台北時區 local wall time，`ended_at` 以 UTC 寫 SQLite，Job `155192`／`151976` 可呈約 **8 小時倒序** | `_dispatch` 寫入 SQLite 前轉 UTC；未重寫既有 DB 歷史列，也**未證明**此顯示缺陷直接造成 3406 漏 Bar |

**驗收限制**：10/20 10:52 以前的 scoped Source Profile PASS（`565 passed / 3 deselected`，另 54 architecture PASS）只能證明該時刻 Source／離線 Fixture；3 個 deselected baseline 問題保留且已在舊 Source 重現。此後還有 Runtime Safety 相關修補，因此最後須以 §9.5 的較新 Scoped Gate 判斷。

### 9.4 其他資料限制和獨立風險

- **TW-209 TAIEX 盤前 Estimate Baseline**：08:34 已有 `resolved_indices.TAIEX` 10/19 官方 **46822.08**，Legacy 非官方 `indices.TAIEX` 卻 `baseline_close=null`／`estimate=null`。其 Estimate 走 `MarketIndexDailyStat` Official Series，Headline Resolver 可由 `TaiwanBarService 1d` 取完結資料，形成 Source of Truth 可用性分岔。**資料是缺列、Source Registry、Raw release Gate 還是條件不符，仍需唯讀逐層 JOIN；不可用顯示的 46822.08 直接冒充合格 Baseline。**
- **Quote/MIS 與成交額不是同一事**：Fugle TAIEX Index 有當日分鐘數據，不代表全市場個股有可用 Quote；估算的 `price×cumulative volume` 不是權威成交額。09:55 TPEX Minute 的 component event 不對齊，出現 `component_time_mismatch`；5d 5/5 是「最近五個合格歷史樣本」，不是最近五交易日每天合格，20d 僅 6/20。當前值不合格時 `pace_ratio=null` 是正常保護。
- **法人來源覆蓋**：10/19 Universe 1967，合格一日 Foreign Metric 1789；**161 缺來源 row**、**17 有其他法人列但沒有有效外資欄**。這是不同於 A2「有 row 的多日完整度錯計」的來源缺口；不能把 178 檔補零，也不能歸咎於 MIS z。
- **Consumer/Read Policy**：10/20 盤前四股在明確 `refresh_if_missing=true` 的受限 Refresh 後，`quote.auction` 可讀到合格 indicative；未要求刷新時快取缺失不等於 Provider 掛掉。Market 目標直接要求 Stock 專屬 `quote.auction` 曾被拒 `unsupported_target_scope`，是呼叫端 scope 選錯，不是市場資料壞掉。

### 9.5 為什麼 Source 修好後沒有立即完成 Runtime 重啟／Live 驗收

1. **10/20 09:35 的歷史 Backend 重啟**採用了前一個 G8 Source；**並不是 10:32–12:11 Phase A／Worker Safety 新 Source 的載入證明**。當日 10:52–10:56 cache-only 的三輪原始行情仍嚴重缺 qualified z，但 metadata 來源選取已避免舊 G8 問題。
2. 10:52–10:58 嘗試正式 `omi_restart_backend` 時，**Auto-review 在工具執行前拒絕**，理由包含 `all_writers_drained=false`、未證 Owner readiness，以及工具宣告 production-safe stop 不可用；原 UUID operation 之後返回 `NOT_FOUND`，沒有 terminal restart receipt、沒有 Backend PID 切換。這**不是已執行 Drain 而失敗**。後續沒有換入口繞過或重送不同 UUID。
3. `restart_preflight` 的 `NOT_REQUESTED / unknown_writer_count=3` 是**尚未執行正式 PREPARE**與三種「未具完整證明的 Writer Scope」，不是確定找到三個正在寫 DB 的 Process。C# `ParsePreflight` 嚴格要求五欄和 1024 字元邊界；中間曾把診斷加進原 wire（會污染 POST），**在正式載入前已改回 exact-five**，擴充只留 GET-only `writer_diagnostics`。
4. 靜態和 red/green 測試另確認 **OwnedWorkThread / MIS bounded_fetch 安全缺口**：Native `Thread.start()` 若已發出 worker 卻對 caller 丟例外，舊碼會提早 `leave()` reservation 與清 IO slot；worker 可能仍在執行，而 PREPARE 被誤判 idle。新 Source 改為**只有 Worker `run()` 真正結束的 finally 釋放**；啟動結果不明保留 reservation/slot，拒絕有疑義的安全重啟。修改前新增案例 **4 failed**、後相關 **24 passed**，本輪直接核對 `runtime_admission.py` 和 `twse_mis_breadth_evidence.py` Diff 已確認這兩處修正存在。
5. **較新截至 12:11 Gate**：`backend` scoped **180 passed**；architecture **54 passed**、checker／compileall／diff-check PASS；隔離 PREPARE→STOP／C# parser Negative Tests PASS。先前擴大測試仍有 **232 passed / 3 failed / 1 deselected**、另有已知 baseline/runtime suite 失敗，**不能以 scoped PASS 宣稱整庫全部 PASS**。現役 Backend **PID 56688**、readyz HTTP 200，但 loaded application release 仍 **`c941a624…`**，新版磁碟 Source 尚未採用；本階段 **restart 0 次、新 Provider quote request 0 次、正式 DB 人工寫入 0 次**，Runtime／Live/Product 均 BLOCKED。
6. 對 **10/19 13:32** 已發生的 TPEX 缺口仍保留時間因果：其後 **10/19 20:39–20:40** 才有成功的 Full-Service Restart，不能倒因為果。10/20 的 Source/Restart blocker 也不得推論成 10/19 3406 缺口的根因。

### 9.6 目前狀態與下一步最小證據

| 範圍 | 截至本次整理的實際狀態 | 所需證據／動作 |
| --- | --- | --- |
| MIS Batch Timeout（TW-201） | **P1 Confirmed Availability Failure；未結案** | 同輪 per-batch Deadline/Source latency；正常交易時段三輪 bounded Receipt |
| MIS Qualified z（TW-202） | **P1 Confirmed Data Availability Gap；上游原因未定** | 經正式 Guard/Owner 授權的同股 **1／10／100** 有界 Live 對照，不用外部 CLI 自建第二 Guard |
| Quote 15s vs Breadth 60s | **Confirmed Product SLO/Architecture Mismatch** | 區分 Last Actual Trade／Feed Observation／Decision Price；使用已授權的 canonical 即時單股 Source，而非放寬門檻 |
| 3406 10/19 1m（TW-203） | **237/265；Raw 已無 28 個分鐘，未證實真無成交** | nstock raw缺桶的上游／官方無成交契約取證，不再重查已一致的 237 Canonical |
| 3406 10/20 1m | **Background Tier-A 未選入，當時無 Job** | 有界確認 Tier-A admission、排程容量／Consumer Demand，不在 read path 隱性 dispatch |
| A1/A2/A3 | **Source 修復＋回歸 PASS；Runtime 未採用** | 正式 Owner 能力與 Source Adoption Gate 解除後，只重驗受影響路徑 |
| Safe Worker／Restart | **新 Source red/green PASS；現役 Runtime 未採用且重啟拒絕仍有效** | 正式工具能力／Owner 安全證明獨立覆核；不可繞過既有拒絕 |
| TAIEX Estimate、量能、法人來源 | **P2／部分源頭未定** | 前收 Canonical vs Official Row/Release，Matched-minute 與 institutional raw scope 對帳 |
| Commit/Push／整體封版 | **均未執行／目前不建議封版** | Live/Runtime evidence 與未完成重大可用性 Gate 後再決定 |

**文件與任務邊界**：進一步的施工進度以 `docs/exec-plans/active/tw-missing-values-source-contract-20261020/Progress.md` 為正式單一執行紀錄；本節僅補足**事故原因、時間線、Source 是否已修及驗收邊界**，不另立重複 Patch Owner，也不把 Codex 完成宣告當正式 Runtime 成功。


---

## 10. 2026-10-20 盤後／新版 Backend 已採用後的現存問題與根因矩陣

> **範圍與資料時鐘**：本節只涵蓋此輪已實際驗證的 **台股 Market Data／Intraday／Index／Source Health、Backend Runtime**，並非 OMI 全系統（美股、Portfolio、交易、Frontend）全面健檢。時區 Asia/Taipei。
> **觀測窗口**：Backend-only Restart 約 **14:13**；Runtime/MCP／Dashboard 約 **14:15**，市場 Snapshot 事件 **13:30–13:33**，正式 Cache-only `omi.ask`／Chart／Source Health 讀取約 **14:17–14:25**。查詢時間和事件時間不可混用。
> **方法**：使用正式 `omi.read_runtime_status`／`omi.read_tw_market_dashboard`／`omi.ask`／Chart／Source Health、原有取證紀錄、Project Workspace 原始碼與 Git Status。所有行情讀取 `cache_only / refresh_policy.off / max_external_fetches=0`；本節不把前輪舊 Receipt 當新版重新擷取成果。
> **紀錄分類**：CONFIRMED = 真實回應／Raw／Source 直接可證；SUPPORTED = 已有充分線索但有待更精確 JOIN；UNVERIFIED = 必須保留未知；NORMAL = 契約符合預期。不能把 Quality Fail-Closed 等同根因。

### 10.1 正式 Runtime Adoption Gate 已改變（修正 §9 的歷史狀態）

- 新版 **Backend-only Restart 已成功**，正式 `RestartBackend` 回執 `request_id=ab259be8-75ef-4563-9e19-7db59eeb0bd6`，`state=SUCCEEDED`；Backend PID **56688 → 31340**；Launcher 仍是 PID **25264**，Port 8400。
- Application `owned_start.loaded_release_identity=APPLICATION_SOURCE_SNAPSHOT`，`release_id=4d1eb259cf62da39b91bc94c2b31e284ba3d77170e1f0e079478837b2e883d73`，與前輪已修 Source release 相符；Runtime Control bundle `disk_matches_import=true`。
- Backend `/api/system/readyz` HTTP 200、`runtime=ok/database=ok`；Workspace 觀測 OMI MCP 本機 Ready。
- **注意**：Runtime Control `loaded_release_identity=UNATTESTED` 是較窄的一般欄位，而 `owned_start` 有具體 Application Snapshot；MCP Source Build 仍未發布。此處只認定該次**正式 Backend 版本採用與基礎可用性 PASS**，不擴張成所有 Capability Live PASS。
- **關鍵時序**：以下 13:32 的 MIS 收據產生在 **14:13 重啟之前**。新 Backend 能讀到它，不代表新 Source 曾在該時間點重新抓取相同資料。§9.5 的 `尚未採用` 是 12:11 的歷史快照，已由此次成功回執更新，但不得抹去原失敗證據。

### 10.2 盤後 Market/Breadth 實際數據

| 能力／市場 | 本次正式快照 | 結論 |
| --- | --- | --- |
| TAIEX 官方指數 | 10/20 13:30 **46,292.93**、前收 46,822.08、**-529.15 (-1.13%)**，Source `twse_index_daily_ohlc`、`official_close_confirmed=true` | 當日官方指數已可用 |
| TPEX 指數 | 10/20 13:30 **387.88**、前收 394.05、-6.17 (-1.57%)，但 Source `tpex_index_5s`、Authority `derived_proxy`、`official_close_confirmed=false` | 僅為待官方確認之代理價，不能冒充官方收盤 |
| TWSE 盤後 Breadth（13:32:20） | Universe **1,080**；Received **1,075**；合格方向 **1,042**（**96.48%**）；Unknown **38**（其中 actual-unavailable 30、valid-no-trade 3、未收到 5）；上/下/平 **261/684/97** | `partial`、`decision_usable=false`；本輪 11 batches attempted、0 failed、0 skipped |
| TPEX 盤後 Breadth（13:32:45） | Universe **887**；Received **878**；合格方向 **790**（**89.06%**）；Unknown **97**（actual-unavailable 66、valid-no-trade 22、未收到 9）；上/下/平 **282/416/92** | `partial`、`decision_usable=false`；本輪 9 batches attempted、0 failed、0 skipped |
| 全市場合計 | Universe **1,967**；Received **1,953**；合格方向 **1,832**（**93.14%**）；Unknown **135** | 不可將高 Received Coverage 誤當 100% 有效成交 |
| 盤後分類／相容欄位 | 正式 `resolved_breadth` 有上述真實數據；Deprecated `breadth` 相容欄回 `missing`、數字為 0／unknown | 消費端**必須採 `resolved_breadth`**；相容欄不能代表正式資料品質 |

**根因解讀**：13:32 Batch 無 Timeout，**本輪取得成功**；但仍有 96 檔 `actual_trade_unavailable`、25 檔 `valid_no_trade`、14 檔未收到。不能將其中任意一類改寫為 0 或平盤；不能把 13:32 收據視為 14:13 新 Runtime 的 Live Acquisition Regression。

### 10.3 目前仍需處理的問題清單（按影響優先）

| Issue | 分類／嚴重度 | 已確認事實／根因邊界 | 判定及下一個最小證據 |
| --- | --- | --- | --- |
| **TW-202** 常態盤中缺 `z` | Confirmed Availability Gap／**P1** | 10/20 09:51 Raw `817612/817619` Batch 全部成功仍大量 `z` 不合法；該兩收據 Raw→Canonical price-state 無損；13:32 方向覆蓋升高不代表盤中已修復。 | 上游回應缺價已定位；但**MIS 為何不給（請求尺寸/更新語意/API 策略）未定**。需合規同股 1／10／100 Batch 對照，不自行建立第二 Guard、不得假價。 |
| **TW-201** MIS Scan Deadline | Confirmed Historical Acquisition Failure／**P1**（本輪未重現） | 10/19 13:32 TPEX 第7批僅餘 ~0.938 秒，第8/9因 20s Budget 跳過；10/20 13:32 兩 Venue 各輪完成。 | 原因是 **bounded acquisition deadline** 而非 Dashboard／DB 遺失；更底層來源延遲仍需 per-batch timing，比較 3 輪有效收據。 |
| **TW-Quote-SLO** 即時報價門檻與生產頻率 | Confirmed Architecture/Product Gap／**P1** | `config.py` Breadth 預設 **60 秒**；Quote 決策要求**15秒**事件時效，加上掃描時間根本無法保證任意時刻合格。 | 應用現有合法 per-symbol Stream/Lease + Gateway，保留 Last Actual/Feed Alive/Decision Price 分層；不改 freshness 冒充修復。 |
| **TW-3406-CURRENT** 10/20 沒有1m | Confirmed Product Availability Gap／**P1/P2** | 3406 `not_materialized`、**0/265**、當日 JobRun **0**、nstock Raw **0**；StockMaster active。獨立 DB 對帳確認 watchlist 排位 **110/348**、當日 Tier-A cadence ledger 僅 **32** 檔且不含 3406。 | **Selection/Admission Scope 為已支持的主要原因**；`tw_intraday_universe.py` configured→holding→active lease→watchlist 後 hard cap；但當時完整混合排序／正式逐目標 `scheduler_hard_cap` 收據未保存，不能冒稱已直接證實排除 reason。不得在 GET 偷偷 enqueue。 |
| **TW-2330-1M（新增）** 10/20 缺 1 分鐘 | Confirmed Provider Raw Coverage Gap／**P2**；來源為何缺分鐘仍 UNVERIFIED | 正式 Chart **264/265**、只缺 **11:08**。nstock Raw `823626` 及同日後續保存 **26** 筆 Raw 均無11:08；264合法分鐘 Raw→Canonical OHLCV 全相同，集合差 **0**。 | 根因層已定位在 **Provider 回應沒有該分鐘**，並非已收到的合法分鐘在 Parser／Store 漏掉；接下來只需核對該分鐘是否真實無成交或來源漏報，不能製造零量 K。 |
| **TW-203** 3406 10/19 歷史 1m 不完整 | Confirmed Provider Raw Coverage Gap／**P2** | nstock Raw `804181` 238 列，合法連續撮合 **237** 列全部保存 Canonical；265 預期中缺 **28**，Raw 也沒有這些分鐘。 | 已排除已收到的 237 根在 Parser/Store 丟失。28 分鐘是來源未提供或真無成交，仍 UNVERIFIED；不可自製 0 量 K。 |
| **TW-209** TAIEX 盤前估算 Baseline 為 null | Confirmed Functional／Lineage Defect **P2**；Writer 起因待查 | `MarketIndexDailyStat` 10/19 row **5241** 有收盤 **46822.08**，卻 **`source_id=null, raw_result_id=null`**；`official_index_repository._project_row` 提前拒絕 `INDEX_ROW_LINEAGE_MISSING`。另一條 Canonical Daily row `1834590` 可由 Raw `808644` 正常解決。 | **缺來源外鍵造成兩條 Read Path 分歧**已確診；下一步追 FMTQIK → MarketIndexDailyStat upsert 為何未寫 Source/Raw FK；不可直接拷貝 Headline 數值繞過合格線。 |
| **TW-VOLUME** 市場成交值可比性 | Confirmed Temporal Contract Defect／**P2** | 13:32 估計值 **861,836,237,986 TWD**，非官方成交額。Source 將 finalized 值存 **13:30** 分鐘桶，但成交額 Owner 的 Event 在 **13:32**；`_has_usable_trade_value` 要求同分鐘，實際 **39/39** 歷史日不能通過資格，5d/20d 因此 **0/5、0/20**。目前 Current 比較分鐘 13:32、Baseline 13:30 亦不一致。 | 已定位 **儲存桶與來源事件時間語意衝突**，不是單純缺乏歷史資料。保留 `pace_ratio=null`；先定義收盤後 Snapshot 比較時間規範，再以已存10/20與近5日 fixture 做負面回歸，不放寬資格。 |
| **TW-INSTITUTIONAL-SOURCE** 法人來源不完整 | Confirmed Data Availability Gap／**P2** | 10/19 Foreign Universe 1967：1789 有合格值、161 缺 Row、17 有其他組成但沒有外資欄位；不是 MIS。 | 根因為目前保存的 TWSE/TPEX 法人來源未涵蓋該指標；官方對「未列出是否等於零」的資料契約未證，禁止補0。 |
| **TW-INDEX-AUTHORITY（新增）** TPEX 收盤資格欄位不一致 | Confirmed Cross-Field Inconsistency／**P2 Architecture Risk** | TPEX Index `derived_proxy`、`official_close_confirmed=false`、`official_close_status=pending`，同一 Header 卻 `finalization=final`、`decision_usable=true`；`index_resolution.py` 的 completed-daily 候選可在不驗 official authority 的情況將 decision_usable 設真。 | 程式行為已確認，但實際下游是否誤當官方／交易級資料 **UNVERIFIED**；應對 `decision_usable` 與 Authority 語意作負面 Contract Regression。 |
| **TW-211** Legacy Compatibility 混淆 | Architecture Risk／**P2** | `breadth` Deprecated 相容欄本輪顯示全缺；Canonical `resolved_breadth` 有 1832 檔真實方向；估算欄 `indices` 與 `resolved_indices` 權威不同。 | 目前沒有正式 UI 讀錯的直接證據，列 Consumer Parity 查核，而非確診 Frontend Bug。 |
| **TW-207** TAIEX 指定歷史1m日期路由 | Observation／**P2 Unverified** | 10/20 08:xx 曾指定 `trade_date=10/19` 卻返回 10/20 盤前 `warming/0`。 | 必須定點比對 Query Param → Bar Resolver；不能以 0 根斷言前日歷史 Bar 不存在。 |
| **TW-HEALTH-SCOPE** Tier-A Health 標籤 | Scope/UX Risk／**P3** | Operational `market_intraday_bar_1m=available` 只評估**當輪已選中 Tier-A**，不含未入選的3406。 | 語意符合 Source Contract；若產品要宣稱全 Watchlist 有 K，應明確列 selected/excluded，不能擴大 Health scope 意義。 |

### 10.4 已修復／目前不是 Active Bug 的觀察

| 項目 | 本次判定 | Gate 邊界 |
| --- | --- | --- |
| **A1 試撮誤判 valid-no-trade** | Source 已修，Application release 已採用 | 新 Source 載入 PASS；**沒有新版開盤時段 Trial 同輪 Live Receipt**，不能宣稱 Live Gate PASS |
| **A2 法人 `null` 誤判完整窗** | Source 已修且 Runtime 行為吻合 | 新版 `screening.coverage` 對10/19 的 5d `complete_window_count=1635`，與離線修正 `1660→1635` 一致；屬修復效果支持，不等於整庫全部測試通過 |
| **A3 JobRun SQLite UTC 時鐘** | Source 已修，Application Release 已採用 | 未對**新版建立的特定 Job**重新逐列驗證起訖 UTC；舊歷史倒序仍是歷史資料，不重寫 |
| **Worker Start/Reservation Race** | 有重現與 Source 修復、已載入新 Release | Red/green 4 fail→24 pass 與 Backend-only Restart SUCCEEDED；不等於全部 concurrent stop stress case 均已驗證 |
| **10/20 官方個股日收盤未釋出** | **NORMAL（14:20 仍在 Release Gate 前）** | `taiwan_rules.py` `TAIWAN_DAILY_PRICE_RELEASE_TIME=15:15`；14:xx expected daily 仍10/19，**15:15 後**才需驗證今日 EOD 是否正常發布；TAIEX 當日官方指數的早期13:35 Release 與個股日價不同 |
| **3406 10/20 Change Reference** | 本次恢復有依據的前收基準 | 前日 `TW_CHANGE_REFERENCE_CORPORATE_ACTION_UNVERIFIED`；盤後回 `TW_CHANGE_REFERENCE_PRIOR_CLOSE_CONFIRMED`（價格1045，對應10/20），不再視為現存同型問題 |
| **盤後 Quote stale/null** | Normal Safety／非故障根因 | Session Close 事實可讀，`quote.official_close` 尚未發布是正常分層；不能將舊價時鐘洗新 |
| **Source Health 既有 historical problems** | Operational 14 項，仍有 Partial；過去歷史有 30 problem entries | 歷史事件不等於現在30個 Active Defects；`problems_only` 若用 operational filter 回空，不證明所有資料完整 |

### 10.5 最小根因取證順序與封版判斷

1. **P1 盤中 MIS Qualified z**：先於正常交易時段、由原正式 Guard／Owner 執行最多兩輪同股 1/10/100、保存 Raw `z/v/tv/ts`、Event/Received、HTTP/Budget；判定來源根因。注意 13:32 的 pre-restart 成功 Snapshot 無法取代此 Gate。
2. **P1/P2 3406 10/20 1m**：以該日 Exact Tier-A Plan/Skipped Reasons + JobRun/Raw Ledger 確認 3406 為何沒被排入，再決定提高優先權還是有界 Consumer Demand；不可修改 GET 成有副作用。
3. **P2 2330 11:08**：已證實 nstock Raw 缺該分鐘且264個有效分鐘均已存 Canonical；只需查官方成交／真無成交證據，避免無效重查已通過的 Parser／Store。
4. **P2 TAIEX Baseline 與 TPEX Authority**：確認 FMTQIK `MarketIndexDailyStat` row5241 的 `source_id/raw_result_id` 為 null；追寫入端填充 Lineage 的責任及負面回歸，並核對 TPEX proxy `decision_usable` 是否違反權威性 Contract。
5. **P2 量能/法人**：量能已確診 **finalized 13:30 Bucket vs 13:32 Event** 的合格樣本被排除，先做保守且相同時間語意的修復規格與離線 fixture；法人 Source Coverage 仍需官方契約才能判定未列即零。
6. **不重做**：已確認的 Backend-only Restart、A2 5d Source/Runtime 配對、10/19 3406 已保存237根 Canonical、當日13:32 Batch 0 failed，以及已通過的未受影響定點測試。

**目前結論：正式 Backend 可用、Source Adoption PASS；台股 Full-Market Actual-Trade／全部個股1m與歷史可比較量能仍未達產品驗收，整體不建議封版。P0 未發現；問題層級以 P1 來源可用性／產品SLO、P2 資料缺口與架構一致性為主。**

**停止條件**：本節是對已取得證據的整合，未自動修復、交易、更新正式 DB、下 Provider Fetch 或重啟。針對 Unverified 原因，後續必須以新的明確 Raw／Job／Release 證據才能升級為 CONFIRMED，不能只重跑相同問答與測試。


---

## 11. 正式唯讀 SQLite 根因複核（2026-10-20 盤後，接續 §10）

> 本節是 §10 根因矩陣的**較新、直接 DB 對帳證據**；當 §10 舊的 UNVERIFIED 描述與此處衝突時，以本節及已更新的 §10.3／§10.5 為準。取證者在 OMI 專案中使用 SQLite URI `mode=ro`、實際設定與確認 `PRAGMA query_only=1`、按 ID／日期／目標及 `LIMIT` 查詢，沒有正式 DB 寫入、行情 Refresh、外部連線、測試、程式修改或重啟。Repository source 同時以 Project Workspace 重新核對重點分支。報告時間不同於 Raw/市場事件時間，不將後取得之收據提前歸因。

### 11.1 TW-2330-1M：11:08 在 Provider 回應中缺失（定位至 Source Availability）

| Raw/Store 層 | 保存證據 |
| --- | --- |
| nstock Raw `823626` | 10/20 **13:33:05.724804**；`分K` 265 行：264 個合法 09:00–13:24 連續撮合分鐘＋13:30 收盤事件 |
| 11:08 | 原始 `交易時間=110800` **0 行**；11:07、11:09 有原始行 |
| 11:09 後至 14:25 前 | 保存 **26** 筆可解析 nstock Raw，全部沒有 11:08；首 Raw `819864`（11:13:54），末 Raw `823626`（13:33:05） |
| Canonical | 264 根；Raw 有效分鐘集合對 Canonical **差集 0**、逐分鐘 OHLC／量差異 **0** |
| 較晚採用的 Source | Raw `824554` 在 **14:26:57** 才收回，與前輪 as-of 14:25 不同；仍為相同264合法分鐘、沒有11:08 |

由 `backend/app/market/providers/tw_intraday_bars.py::NStockIntradayAdapter.acquire_route` 可確認日期、價格、請求視窗、regular session 的解析條件；13:30 不屬一般時間 K 分母。**確認：保存的有效 Raw 沒有 11:08，並非已收到的264筆 Parser/Persistence 漏存。** 仍未證明 11:08 是官方真無成交或 nstock 漏報；這是唯一未定的 Source 語意分叉。

### 11.2 TW-3406-CURRENT：未排入當日 Tier-A，並非已抓完資料後遺失

- StockMaster：3406 為合法、Active 的 TWSE Stock，排除 `target_not_found/inactive_instrument/not_taiwan_cash_market`。
- Watchlist 合法候選中的排名為 **110／348**；此為 **Watchlist 自身順位**，**不是**合併 configured／holding／active lease 後的最終順位。查詢沒有讀取或輸出私人持倉。
- 正式當日 `tw-cadence:scheduler:2026-10-20` Ledger（rev. **1072**）的 `next_due_at` 有 **32** 檔，沒有 3406；當日 `3406:2026-10-20` Materialization JobRun **0**、nstock Source `25` 對應該股 Raw **0**、Canonical 1m **0**。
- 保存的 `JobRun 155780` 其實屬於 `3406:2026-10-19`，不能錯歸當日。
- `backend/app/market/tw_intraday_universe.py::resolve_taiwan_tier_a_target_plan` 的 Root Owner 依 configured→holding→active lease→watchlist 排序再套 hard cap，超出時才記 `scheduler_hard_cap`；`config.py` 預設 cap 32。

**結論**：造成 10/20 沒有當日 Bar 的直接執行缺口在**沒有 admitted Job／Raw**；Tier-A Selection 是最強根因。因歷史 Ledger 未保留「3406 的完整合併排名／單股 skipped reason」，不可冒稱 `scheduler_hard_cap` 已由當時 Receipt 逐標的確診。下次修設計應增強 selected／excluded audit evidence，不重新掃正式私人持倉。

### 11.3 TW-209：已找出 Baseline null 的直接故障分支

| Read Path | 已驗證 DB 事實 |
| --- | --- |
| Legacy `MarketIndexDailyStat` | 10/19 TAIEX row **5241**；`close_value=46822.08`、`price_change=-289.18`，來源字串 `twse_rwd_fmtqik` |
| Legacy 必填 Lineage | **`source_id=NULL`、`raw_result_id=NULL`**，無法關聯 SourceRegistry/Raw |
| 正式 Repository | `official_index_repository.py::_project_row` 在驗 Source/Release 之前，即因缺外鍵拒絕 `INDEX_ROW_LINEAGE_MISSING` |
| Canonical 完成日線 | `market_daily_price:1834590`：同日 close **46822.08**、`source_id=35`、`raw_result_id=808644`、Source `twse_indices_report_mi_5mins_hist` |
| Canonical Raw | `808644` 取得於 10/19 **20:40:19.079604**，官方 Final/Released |

因此 `tw_market_dashboard.py::_latest_index_baseline` 的 Legacy Reader 取不到 Baseline，是**已有數值卻沒有必要來源 FK** 的確定性結果；不應再歸因為日期無資料或 Release Gate 未到。哪個 FMTQIK Upsert/Writer 漏寫兩個 FK，仍需沿寫入端追查。**禁止自行捏造 SourceRegistry/Raw FK 或直接把另一條顯示價塞入不合格 Row。**

### 11.4 TW-202：13:32 的 Raw→Canonical 價格對帳零差異

| 比對軸 | TWSE | TPEX |
| --- | ---: | ---: |
| `RawFetchResult` ID | **823649** | **823624** |
| Canonical Breadth Snapshot ID | **19521** | **19522** |
| Event / Received (台灣時間) | 13:32:20／13:33:39.432364 | 13:32:45／13:33:03.918092 |
| Scan Attempted/Failed/Skipped | 11/0/0 | 9/0/0 |
| Raw / Canonical Price-State 筆數 | **1068/1068** | **838/838** |
| Qualified Actual `z`／Session Cache | **1019／23** | **690／100** |
| Scan Missing-z Aggregate | **55** | **188** |
| 保存字面 `z='-'` 樣本 | **28/28** | **27/27** |
| Canonical 有效方向／Universe | **1042/1080** | **790/887** |

- 以股票鍵比對價格、前收、事件時間、累計量、已確認成交及 current verified，**數值差異 0**；方向數與來源分類、交易額也一致。
- Canonical 將部分數值表達為 Decimal 字串，並對來源已合格 `z` 補足本 Raw Receipt 的 Lineage，**不是實際價格遺失**。
- 真正未達方向資格的原因仍為 TWSE `ACTUAL_TRADE_PRICE_MISSING=29`、`AUCTION_INDICATIVE_ONLY=1`、valid-no-trade=3、not-received=5；TPEX 分別 **59／7／22／9**。
- **Scan missing-z 數量不等於最終 unavailable 檔數**：Session Cache、各種資格及分類是不同階段。
- 這些 Event **早於14:13 Backend Restart**，所以可證明既存 Raw/Canonical Consistency，**不能作新版 Live Scan 的性能／來源修復證據**。上游為何不提供每次合法 z 仍是 P1 未定根因，不能將最多三筆每 Batch 的 Raw sample 誇大為全市場。

### 11.5 TW-VOLUME：13:30 存檔與 13:31–13:32 Owner Event 相衝突（已確診 Temporal Bug）

`taiwan_market_state.py` 的現行兩處 Source 已再次獨立核對：

1. `_minute_at_for_payload`：`finalized=True` 時，Minute State 強制使用 **13:30** `TAIWAN_SESSION_CLOSE` 作保存分鐘。
2. `_has_usable_trade_value`：要求 `owns_trade_value` Component 的 `event_at` 四捨五入到分鐘後，**嚴格等於**保存 Row 的分鐘；不一致便拒絕其估計交易值，不論有無 Lineage。

本次 DB 中 `TaiwanMarketMinuteState` **TWSE row33956、TPEX row33957** 都存 13:30，Owner Event 分別為 **13:32:20／13:32:45**；兩者有數值且 `lineage_complete=1`，仍因時間不同遭排除。

以最近 60 日曆日（**8/21–10/19**）有 **39** 個歷史交易日的78筆兩市場 13:30 Row，套現行 Source Pure Eligibility 得：

- **39／39 日皆為 `unusable_value_or_lineage`**、可比較樣本 **0**。不是這批日子沒有兩 Venue 的 13:30 Row。
- 其中 **59/78** 筆擁有成交額的實際 Event Minute 與儲存 Bucket 不一致；同時另有舊資料 Lineage/Value 欠缺。
- 額外有 **17 日** `trade_value_semantic_mismatch`、**17 日** `authority_mismatch`、**4 日** `canonical_scope_mismatch`（與時間拒絕原因可重疊）。這些也須維持獨立資格，不可一律允許比較。
- Current 的值可由 Canonical Breadth 重新組出 **13:32**，但原 Baseline 仍錨定 **13:30**；即使修好歷史部分，也需要統一比較時間基準。

**結論**：不是單純 History Warmup，而是已確認的 **Producer Bucket Policy vs Resolver Eligibility Temporal Contract 衝突**，再加上 Current/Baseline projection 分裂。未定的只有最適當的產品比較規格（13:30收盤桶、13:32有效事件、或明確的 Session-Final State），不應先粗暴拿不同時間、不同 Source Authority 的成交額相除。

### 11.6 複查 Gate／下一步

- **Resolved root / no repeated investigation**：TW-2330 11:08 Provider Raw 已缺；TW-209 Legacy TAIEX Lineage FK NULL；TW-VOLUME 13:30/13:32 Temporal Conflict；TW-202 13:32 Raw/Canonical numeric consistency；TW-3406 當日 No Job/No Raw。
- **真正剩餘的未知**：2330/3406歷史空分鐘是否真無成交；3406 10/20 exact selection skipped reason；TAIEX 兩個 Lineage FK 是哪個 Writer 漏存；MIS 常態盤中合法 z 缺值為何發生；盤後成交額應使用何種不失真的比較時間與權威等級。
- **修復策略**：優先保留既有 Canonical/Gateway/Resolver Owner；每個問題各自寫一個最小可重現 Fixture，再修改其正式 Owner，禁止新增平行 Cache／在 GET 補數／冒充官方或即時價。獨立 OMI Frontend 任務進行中，本輪不觸碰它的檔案與正在使用的 Runtime。
- **Source/Runtime/Live 區分**：本輪新增的是唯讀 DB＋Source Root Cause Evidence，沒有進行任何 Source Fix、Backend 重啟、Provider Live Probe、Regression Test，也未改變 §10.1 的 Runtime 成功回執與市場 Snapshot Event Time。**整體仍不建議封版。**


---

## 12. 盤後 Source 修補與離線進度（2026-10-20，R2）

接續§10–§11，版本 `TW-POSTCLOSE-SOURCE-20261020-R2`；Git基線 `ec9f042c9f8453bb9708f0343077dcad69af0c7f`＋既有dirty WIP。本輪僅Source／離線驗證，未改正式DB、未refresh/restart/commit/push。§10.1 的14:13採用紀錄仍屬前版本，不能當成本節修補已載入。

| 問題 | 原 owner 的定點修補 | 保留限制 |
| --- | --- | --- |
| TW-209 | FMTQIK legacy writer無receipt transaction，可產生NULL FK；estimator改讀既有Daily Repository／Gateway／TaiwanBarService的exact previous session正式證據，再沿原official index reader讀合格legacy observation。 | 不造FK或硬編價格；13:35 release、date、authority、finalization、receipt/hash／requested_at仍合格才讀。Source重現writer形狀，不聲稱取得row5241歷史呼叫堆疊。 |
| TW-VOLUME | minute-state v4保留成交值owner真實event minute，13:32不改13:30；雙市場scope/semantic/authority及lineage一致才比較。Current改時間時拒絕舊baseline樣本並保留診斷。 | 舊13:30/13:32矛盾row仍拒絕，無正式歷史重寫；新fixture可比，不代表事故39日已修。 |
| TW-INDEX-AUTHORITY | proxy保留研究值／來源／finalization，decision=false；typed contract、headline、AI quote、v4 brief保留authority／provisional／official denial。 | final不等於official；無官方證據不能confirmed或升格執行級。 |
| TW-3406-CURRENT／Tier-A | 原selector新增selected／candidate_rank／eligible_rank／reason，原cadence ledger保存target_selection。 | due/job/budget、cap/quota/background上限不變；watchlist110/348不冒充合併rank，不加GET enqueue。 |
| TW-2330-1M／TW-203／TW-202 | 隔離adapter→canonical→bar fixture維持missing_evidence；既有MIS offline 1/10/100兩venue兩輪完成，真外部請求0。 | 來源空分鐘是否真無成交、MIS盤中缺z原因仍UNVERIFIED；不改provider、不補價、不補0量bar。 |

歷史migration/backfill僅評估：新writer不需schema change；舊minute_at重建可能撞唯一鍵，且authority/scope/semantic不同，須另獲授權及逐row證據後由原transaction owner處理。本輪未查寫正式DB，未宣稱事故資料已恢復。

最終離線驗證 **PASS／exit0**：safe backend wrapper `.tmp/validation/20261020-145937/`，targeted **295 passed / 54.96s**、architecture **54 passed / 50.57s**、checker actual15/debt15、compileall與diff check通過。MIS offline tse/otc各simulated6／external0。精確manifest與10/21接手清單見[原任務 Progress 的 R2段](../../exec-plans/active/tw-missing-values-source-contract-20261020/Progress.md)。task-only diff／基線／hashes在 `.tmp/postclose-source-20261020/`；只交外部Reviewer，不自行採用Source。

**尚待10/21 Live**：外部Reviewer核可後由正式Owner另行確認Backend-only採用；盤前baseline/date/release、盤中MIS同股1/10/100、當輪Tier-A排除收據、新量能row時間、proxy outward denial均需新正式證據。獨立MIS CLI不能共享runtime Guard／IO slot，仍BLOCKED，禁止另起Guard或換transport。2330/3406空分鐘不可冒稱no-trade。整體不宣稱Live／Product驗收。


### 12.1 2026-10-20 15:07 補充｜正式 Backend-only 版本採用遭 Lifecycle Source Pin 阻擋

外部 Reviewer 已核對 R2 定點 Source Diff 與修正後 295 + architecture 54 項離線通過證據。**但 Backend-only 尚未重新啟動。** 15:07 的正式 `omi.read_runtime_status` 顯示 `restart.available=false`、`SOURCE_ADOPTION_NOT_ATTESTED`；現役 Launcher PID25264、Backend PID31340、Application Release仍為上輪 `4d1eb259…`，另讀 `readyz` HTTP 200／runtime+DB OK。這是正式採用 Gate BLOCKED，不等同 Backend Crash 或 R2 Source 測試 FAIL。

與單獨 `Runtime Control Bundle disk_matches_import=true` 不同，`omi-runtime-control.ps1::Get-OmiLifecycleSourceId` 對 Launcher/Runtime Control/C# Runner/owned backend entry/venv config 等七個來源路徑封存冷啟 hash；目前 Lifecycle source WIP（包含 `scripts/omi-launcher.ps1`／Control 修改）不同於運作中的 Launcher Cold Pin。詳細路徑與查證邊界見 [Progress R2 Adoption Gate](../../exec-plans/active/tw-missing-values-source-contract-20261020/Progress.md)。

使用者本輪僅允許 **Backend-only**，未授權為了採用新 Launcher 而 Full-Service/Cold Restart 或修改 Pin；也不得用新 CLI、Tray、強殺、回退檔案繞過拒絕。因狀態已拒，未送正式 `omi_restart_backend`：**Restart submission 0、request ID 無、PID 未替換、R2 Runtime/Live/Product 均未驗收**。先解決正式 Lifecycle Adoption（需對實際影響範圍取得相應授權），再重新檢查 Backend-only 入口；10/21盤中的市場資料 Gate 不能代替這個前置條件。


---

## 13. 2026-10-21 開盤前試撮正式 Runtime Live Gate（08:33–08:40 Asia/Taipei）

> 前置：使用者於 08:30 後要求開始試撮驗收。此為**當日正式 OMI 實際回應**，與 §9～§12 的前日記錄分開。驗收僅讀取 Runtime、Dashboard、Source Health／正式 `omi.ask`；指定個股唯一有界刷新經現有 OMI ask/Gateway/Guard，非外部 CLI。沒有重啟、改Source/DB、下單、寫入新行情假值或 bypass。

### 13.1 Runtime 與 10/20 R2 採用前置

- 正式 `omi.read_runtime_status` 於 **08:33:44** 回報 Launcher PID **23480**（10/20 20:01啟動）、Backend PID **21256**（10/20 20:03:24 啟動）、Port **8400**、Owner attested；Application `owned_start.loaded_release_identity=APPLICATION_SOURCE_SNAPSHOT`，loaded Release **`675683f9bf4eef3563e6d5aef1ee0704de827983dc9f5154dd821385f2e4cbd6`**。
- 較 10/20 14:13 的 `4d1eb259…` 為新 Backend Load，正式 `restart.available=true`／`blockers=[]`，昨日 `SOURCE_ADOPTION_NOT_ATTESTED` 已不再出現在正式前置狀態。HTTP `/api/system/readyz` 200、runtime/database ok。
- **但當前最新磁碟 ApplicationRelease 尚未與 loaded ID 精確重新計算對帳**：隔離 Codex Bridge read-only job `af164cef-b1f3-4c0c-9d31-c868f12ff8a3` 嘗試建立時被 local Windows Sandbox `apply deny-read ACLs` helper 錯誤拒絕，沒執行 Source Hash 計算；不可當成 OMI Backend 故障。Runtime Control Bundle `disk_matches_import=true` 不涵蓋 Application 完整 Source。當日功能輸出有 R2 特徵，可支持 Runtime 行為已變更，但不冒稱完整字節哈希一致。

### 13.2 正式全市場 opening auction（背景自然收據）

- `omi.read_tw_market_dashboard`：session `preopen`、trade_date **2026-10-21**、`presentation_state=observing`。當天 08:32:51 快照試撮 TAIEX provisional estimate **46573.66147**、Baseline **46292.93**、基準交易日10/20；TPEX provisional estimate **394.91963**、Baseline **387.88**、基準日10/20。兩者都 `decision_usable=false`，未拿 indicative 替代官方指數。08:38:50 的估值已變為 TAIEX **46944.86284**／TPEX **395.17626**，時間敏感且不可當作最終收盤。
- 正式 `resolved_indices` 在試撮期間維持 **10/20** 已完成官方收盤：TAIEX **46292.93**，TPEX **387.88**，authority `official_exchange`、`official_close_confirmed=true`。不等於10/21新官方數字。
- 08:32 首輪已收到真正 **10/21** MIS 收據：TWSE Raw `839111`，11 Batch Attempted、**0 Failed／0 Skipped**、Received **1075/1080**；TPEX Raw `839112`，9 Batch Attempted、**0 Failed／0 Skipped**、Received **878/887**。和昨天 13:32 舊收據完全分開，**證明新版在試撮時段全市場 Acquisition 成功**。
- TWSE 08:32:45 `auction_breadth`：**591** 合格 provisional（上405／下69／平117），unknown **489**；TPEX 08:32:51：**319**（上239／下47／平33），unknown **568**。
- 較新自然輪次 TWSE 08:39:25：**660** provisional（上474／下80／平106），unknown420；TPEX 08:38:50：**353**（上263／下47／平43），unknown534。上述不是同秒強制合併，不聲稱同步全集覆蓋。
- `omi.ask` 官方 v4 市場廣度於 **08:40:38** `market.breadth` 的 **actual directional coverage=0、advance=decline=unchanged=0、unknown=1967**，`auction_breadth.coverage=1014`、上735／下131／平148，`decision_usable=false`，符合 **indicative ≠ actual traded**；個別市場 `resolved_breadth` actual=0 亦正確。試撮波動和觀測 cache freshness 不代表資料故障；未來正式開盤合格z仍待驗證。

### 13.3 有界單股試撮：Cache-only vs 正式 OMI ask live fill

先對 2330／3406／3264 執行 **cache-only** `quote.auction`，皆暫時 `unavailable/CACHE_ONLY_NO_ELIGIBLE_CANDIDATE`，`refresh_if_missing=false`、external calls=0；**不能直接判定 Provider Failure**。

後續透過 `omi.ask`、明確中文股票代號、`realtime_policy=prefer_live`、`refresh_if_missing=true`、`tool_budget.max_external_fetches=1`、`max_total_seconds=18`，對各檔各做**一筆**有界正式資料取得：

| 標的 | 正式個股 Auction | Indicative 價／預估撮合量 | Event time | Source/註記 |
| --- | --- | --- | --- | --- |
| **2330 台積電（TWSE）** | **PASS / current** | **2410 TWD／678張** | 08:36:53 | `twse_mis_quote_depth`，快照 `live`，`price_decision_usable=false` |
| **3406 玉晶光（TWSE）** | **PASS / current** | **1075 TWD／19張** | 08:37:26 | `twse_mis_quote_depth`，快照 `fresh`，`price_decision_usable=false` |
| **3264 欣銓（TPEX）** | **UNAVAILABLE** | `null/null` | `null` | 已有一次正式 `provider_fetch_attempted=true`，`AUCTION_DATA_UNAVAILABLE`／`NO_SNAPSHOT`；根因尚未釐清，無重送 |
| **3105 穩懋（TPEX）** | **PASS / current** | **471 TWD／168張** | 08:38:07 | `twse_mis_quote_depth`，快照 `fresh`，`price_decision_usable=false` |

- 3264 **單股缺口**不能推論 TPEX 整條 Provider 不可用：同 Venue 3105 取得合法資料，且上櫃全市場 auction 也有合格股數。
- 3264 的 `quote.auction` 為 `NO_SNAPSHOT`，而 `change_reference` 另回 `TW_CHANGE_REFERENCE_CORPORATE_ACTION_UNVERIFIED`；`quote.official_close` 可正確取10/20的 **247.0**。目前**沒有直接證據證明**是除權息資料或 Provider 無試撮單造成 `NO_SNAPSHOT`，各分項保持分離，不補價格。
- 2330／3406／3105 都保留 `price_decision_usable=false`，證明實際 Live Fill 沒有把 indicative 冒充正式成交或執行級報價。

### 13.4 新 Confirmed Defect：自然語言 Target Resolution 誤選 `TIME`

**實際輸出錯誤已確認，Root Cause Pending**：最初一筆 `omi.ask` 問句同時包含 **「2330 台積電」和英文 `event time`**，且在 `market_data_params` 明確填 `market=tw,symbol=2330,trade_date=2026-10-21`，正式回應卻解析為 `target.type=us_stock`、`target.id=TIME`（美股ETF），`quote.auction` 因 scope unsupported 被拒。該次 `provider_fetch_attempted=false`，無外部 Fetch。隨後改成簡短中文 `台股 2330 台積電 盤前試撮報價`、保留 market_data_params，即正確解析 `tw_stock/2330` 並完成正式 Live Fill。

此為 **Confirmed Target Resolution Defect（P2）**、疑似問句中的英文單字壓過顯式台股 Target。仍待實際 resolver priority/negative test 才可定案為特定函式。修法不應由 Consumer 硬編股票、或於 Provider 降低校驗。

### 13.5 本階段 Gate／未驗證範圍

| 驗收 | 結果 |
| --- | --- |
| Backend Live／Database／Owner | **PASS**（PID21256，loaded新Application Snapshot） |
| 新版 10/21 MIS Preopen TWSE/TPEX Acquisition | **PASS**（11/11與9/9均 0 failed/skipped） |
| TW-209 昨收 Baseline／Date | **PASS (Preopen Runtime)**（46292.93／387.88，10/20官方） |
| 試撮與正式成交分流 | **PASS (試撮時段)**（actual directional=0、indicative別列，decision=false） |
| 指定股票正式 Live auction | **PARTIAL**（2330/3406/3105 PASS；3264 UNAVAILABLE） |
| Source Snapshot vs 最新磁碟 Hash | **UNVERIFIED**（Codex Sandbox ACL 初始化拒絕，不等於Backend故障） |
| TPEX 3264 原始 Quote Provider/No Snapshot 原因 | **UNVERIFIED** |
| 問句中英文 event time 導致誤選美股TIME | **Confirmed Defect P2，Root 未定** |
| MIS 正式交易時段合格 `z`／TPEX Batch Deadline | **PENDING 09:00 後**；試撮不提供證據 |
| Tier-A 1m、成交量 Current/Baseline、全天 EOD | **PENDING 有效生產窗口**；未因試撮缺K判Bug |
| 封版 | **Not Yet**，待正常盤中 Source/Provider/Quality Gate |

**操作邊界**：沒有重啟 Backend/Frontend/MCP、沒有改業務 Source/Config、沒有強殺或手動寫行情；有界 Fetch 僅透過正式 `omi.ask` 的原來 Gateway/Guard。舊收到與新收到的 Receipt 均保留真實時鐘。所有盤前估算和個股 indicative 價格隨時間變化，不作交易建議。

## 14. 2026-10-21 開盤後 Source／Saved Raw 定點追查

本節接續使用者提供的 09:03–09:07 正式驗收。查核只用磁碟 Source、SQLite `mode=ro`＋`PRAGMA query_only=ON` 的限定 ID／時間窗 SELECT，以及離線測試；沒有 Provider Live、Runtime 控制、正式 DB mutation、restart、commit 或 push。工具讀取正常，未遇 ACL 拒絕。Git 為 `main`、HEAD `ec9f042c9f8453bb9708f0343077dcad69af0c7f`，保留 dirty baseline。使用者提供 08:47 Backend PID10832、loaded release `675683f9bf4eef3563e6d5aef1ee0704de827983dc9f5154dd821385f2e4cbd6`、readyz200；本輪未重驗完整 loaded identity，不能推定本輪修補已載入。

### 14.1 精確收據與原因分類

下表 Event 是 payload `as_of`，收據時間是 Raw `fetched_at` 換算 Asia/Taipei，不能把兩者混為同一時間。完整有界摘錄存於 `.tmp/tw-opening-20261021/receipt-evidence.json`，包含原始 content hash、batch timing、missing examples 與 cache 統計。

| Raw | Venue／Event／收據時間 | 當輪結果 | 原因分類 |
| --- | --- | --- | --- |
| 839712 | TPEX 09:03:14／09:03:22.893 | received594/887、directional23；7 attempted、1 failed、2 skipped | 第7批 caller acquisition deadline；後2批 budget_exhausted，未發 HTTP。333 actual unavailable 是另一個價格資格缺口。 |
| 839727 | TWSE 09:03:53／09:04:07.049 | received895/1080、directional53；10 attempted、1 failed、1 skipped | 第10批 caller acquisition deadline；第11批未送出。633 actual unavailable、209 valid_no_trade、185 provider_missing 分開。 |
| 839747 | TWSE 09:04:56／09:05:02.749 | received996、directional73；11 attempted、1 failed、0 skipped | 第11批 caller deadline；不是11批全部成功。 |
| 839771 | TWSE 09:05:57／09:06:02.703 | received896、directional60；10 attempted、1 failed、1 skipped | 第10批 caller deadline，第11批 budget_exhausted。 |
| 839800 | TWSE 09:06:56／09:07:02.759 | received596、directional44；7 attempted、1 failed、4 skipped | 第7批 caller deadline；後4批未送出。403 actual unavailable、149 valid_no_trade、484 provider_missing。 |
| 839810 | TPEX 09:07:15／09:07:23.362 | received878/887、directional60；9 scan批全部成功 | 496 actual unavailable、322 valid_no_trade、9 provider_missing；另1批32檔rescue HTTP完成，但0檔取得合格新價，不是32次HTTP失敗。 |
| 839825 | TWSE 09:07:50／09:07:57.000 | received1074/1080、directional74；11 scan批全部成功 | 相鄰自然輪次證明 acquisition 可完成；788 actual unavailable 仍存在，不能把 deadline 修復當成價格完整。 |
| 839797 | 單股2330／09:06:59.399 | status_code=null、raw_text=null、external_calls=0（正式回應） | Raw error=`TWSE_MIS_PREVIOUS_TRANSPORT_IN_FLIGHT`；本機同venue IO admission拒絕，不是HTTP失敗或Registry mismatch。 |

### 14.2 HTTP latency、deadline、Guard／slot／late worker 分層

- Source owner：`twse_mis.py::_fetch_payload` 記錄 transport/decode；`twse_mis_current_breadth.py::_fetch_messages`（173行起）控制單輪 absolute deadline、批次資格與 cursor；`twse_mis_breadth_evidence.py::bounded_fetch`（39行起）保留同venue Future／OwnedWorkThread reservation。
- 839727 前9個完成批次 transport 合計 **14.1986s**，classify＋digest **0.16985s**；第10批剩餘 **5.60827s**、caller實際等待 **5.62092s**。839800 前6批 transport **19.15316s**、classify＋digest **0.15903s**；第7批只剩 **0.66586s**、caller等待 **0.67866s**。兩者 `timeout_origin=acquisition_deadline`、`timeout_stage=null`、失敗批 `transport_seconds=null`。這證明 caller預算耗盡，**不證明底層connect/read socket timeout**。完成批次的transport包含本機HTTP包裝／網路等待，不能細分成純上游伺服器耗時。
- 本組failed batch沒有 `guard_open`／`transport_in_flight`，其後skip明確為 `budget_exhausted`；故不能把全市場截斷歸因於Guard。20s scan＋2s cooperative finalization保護仍有效；毫秒級排程尾差不冒稱可硬搶占的20s wall deadline。
- 839797的時間落在839800第4批約 **09:06:53.430–09:07:00.591** 的完成傳輸區間內（由 receipt_at 減 caller_wait推算）；該批 **7.15945s transport**，最後成功。Source對任何尚未完成Future都回同一 `PREVIOUS_TRANSPORT_IN_FLIGHT`。因此支持**當輪正常在途批次與foreground競爭同slot**；不是證實「前輪timeout殘留worker」。歷史slot owner沒有request關聯ID，無法獨立證明是哪個worker；推算與直接Raw拒絕證據分開。
- Late worker防護沿用原Owner：caller timeout不釋放原生writer reservation、不清slot；完成之前不接受同venue另一個IO，不允許晚到結果更新cache／Guard。不改Guard、IO ownership、Drain或Graceful Stop。
- Cursor確實輪轉：839727 `1319→6933`，839747 `6933→6581`，839771 `6581→4560`，839800 `4560→1906`，839825完整輪次 `1906→1906`。沒有證據顯示尾端永遠餓死或scheduler未執行；**不修改scheduler／scan budget**。提高deadline或並行呼叫不能由本證據推出安全收益。

### 14.3 Raw z、cache證據、Quote SLA 是不同問題

- 839810主scan `actual_z=35`、`missing_z=839`；完整收到878筆但只有35個當輪合格z，加25個嚴格session_cache，合計directional60。Missing-z不是全部actual unavailable：其中可含合法no-trade、cache可用或試撮狀態。保存的27個scan missing樣本 **27/27 `z='-'`**；rescue另3個也全為`-`。樣本不是完整HTTP body，不宣稱839筆字面分布已全部驗證，更不能推定上游為何缺z。
- 839727合格z34＋cache19＝53；839800 z24＋cache20＝44。這些當輪component計數與各Raw一致，沒有跨輪union補received coverage。
- 839810有67筆 `SESSION_CACHE_VOLUME_INCREASED`；839727有106筆、839800有86筆。`tw_market_breadth_contract.py::resolve_twse_mis_breadth_price_state`（71行起）要求同日、可信成交及量未增加；量增時拒絕舊價是正確保護。廣度的方向分類不等於單股15s decision資格。
- 2330具體鏈：839747記錄 `2415 @ 09:04:05`、volume2467、`price_source=z`，batch收到時間 **09:04:54.454**，當時已落後 **49.454s**。839771該股volume增至2543、沒有新合格z，current_price=null，`SESSION_CACHE_VOLUME_INCREASED`；保留的舊價state為`current_price_verified=false`，lineage指向839747。839800當輪component沒有2330，僅保留同一不合格舊state，不能當新收到資料。
- 因此使用者正式Quote age177s／decision=false有直接舊事件證據支撐；本輪未重跑omi.ask。對quote snapshot table兩個限定時間窗查詢均無row，不由此推論沒有breadth companion；上述鏈來自保存的breadth Raw。
- `public_quote_platform.py::build_taiwan_public_quote_requirement` 要求last_trade_price、canonical lineage、EVENT_TIME且 **PUBLIC_QUOTE_MAX_AGE_SECONDS=15**；不以received_at更新event time、不用pz／bid-ask／昨收補null。本輪未放寬。缺z上游原因及Quote SLA仍 **UNVERIFIED／未達成**。

### 14.4 單股正式route追蹤與唯一修補

正式鏈：`taiwan_quote_evidence.acquire_taiwan_quote_evidence_bundle → taiwan_realtime_platform.refresh_taiwan_realtime_snapshot → public_quote_platform.acquire_taiwan_public_last_trade_quote → MarketDataGateway.resolve_quote → TwseMisRealtimeAcquisitionAdapter._acquire → _default_reader → bounded_fetch → twse_mis.get_stock_response`。

Registry descriptor在 `providers/tw_public_quote.py:38`：provider=`twse_mis`、resource=`twse_mis.stock_info`、instrument、TWSE/TPEX、CONTINUOUS、FETCH、單股1 call；requirement能力／venue/session與adapter的resource過濾一致。839797證明已進到adapter並留下Raw，故不是 `MIS_ROUTE_NOT_PLANNED`。`bounded_fetch`在HTTP前發出 `AcquisitionInFlight`；adapter取消原Guard attempt、產生零IO失敗收據；Gateway重新讀不到合格price，再由 `gateway.py:799` 追加 `ROUTE_REQUIREMENT_UNSATISFIED`。**真正未滿足的是fresh actual-price evidence，不是provider/resource字串不匹配。**

Confirmed defect只限**診斷資訊遺失**：adapter失敗summary固定只有 `PROVIDER_REQUEST_FAILED`，沒有把Raw／provider_health既知的零IO拒絕原因帶到acquisition limitations。原owner在 `twse_mis_realtime_acquisition.py:333` 補上 `provider_snapshot.detail_code`（僅該snapshot external_calls=0且有reason時），保留generic code相容性；Guard cooldown／slot busy／admission paused可區分，沒有改成功判斷、路由、retry、wait、quota或持久化owner。這不是單股供價或全市場P1可用性的修復。

### 14.5 Source驗證、未完成Gate與Reviewer接手

- Source **PASS**：safe backend subset `.tmp/validation/20261021-091455/`，targeted **139 passed / 21.52s**、architecture **54 passed / 31.49s**、checker PASS（actual15/debt15）、compileall及git diff --check PASS。9個targeted測試檔清單與命令見同任務Progress。測試只用fixture／隔離DB，沒有Live HTTP。
- 新增formal route的slot／admission failure fixtures、未逾時active slot衝突、10／11批尾端deadline；既有7批輪轉、11批19.184s完整scan、missing-z不補價、Guard正負例、late worker／unknown thread-start、15s freshness與Gateway regression均通過。首輪red紀錄中active-slot案例確實因缺reason失敗；另外2例是測試誤用不存在的summary屬性，修正fixture後才通過，不能將那2例稱為產品red證據。
- 僅改1個production adapter、2個既有test檔與原事故／Progress；沒有改scheduler、price contract、Frontend或Lifecycle。82檔dirty baseline與task-only patch保存在 `.tmp/tw-opening-20261021/`。
- 各項均為 **Source PASS／Runtime-PENDING**：deadline與cursor為既有行為離線驗證；missing-z／cache為Unknown安全契約驗證；route為診斷修補驗證；Quote 15s為拒絕舊價驗證。上述PASS不代表P1解決，Live／Product尚未完成。
- 外部Reviewer需核對task-only diff、Raw 839797與839800時序、no-IO reason向外傳遞且無新呼叫。本Job不提交restart；是否採用由Reviewer／正式Owner另行決定，之後仍須正式loaded source證據。
- 最低成本新證據：沿原scheduler保存至少3個相鄰自然輪次的Raw ID、acquisition_id、scan起訖/cursor、每批remaining/caller_wait/transport/decode/timeout_origin、scan與rescue計數；不能跨輪union。自然發生的單股refresh另核對Raw error、external_calls及summary reason。若需證明busy是active還是late，現有收據欠slot-owner關聯與worker完成時刻，需由原IO owner另行設計有界觀測，不能靠加Live probe判定。HTTP完成仍缺z時保持Unknown；Quote通過需同交易日合格actual price及event age≤15s，否則明示未達標。
- Tier-A第4分鐘0 bars與volume partial／5d0/5不在本輪新增根因結論：缺Job／due／admission或當期同分鐘雙venue證據時，不推定scheduler故障、不補K、不改量能比較資格。

## 15. 2026-10-21 P2 Target Resolution：event time 誤選 TIME

### 15.1 離線重現與確認根因

原輸入為「測試 2026-10-21 開盤前試撮：2330 台積電當下合法的 indicative match price、試撮量、event time、來源與有效性。」，`market_data_params={market: tw, symbol: '2330', trade_date: '2026-10-21'}`。使用真實 `AiAskRequest`，只以簡化 identity fixture 提供 TIME／TSM／AAPL 主檔查詢；不建立正式 DB session、不呼叫 provider。修補前原問句得到 `us_stock/TIME`，短問句「台股 2330 台積電 盤前試撮報價」得到 `stock/2330`，首輪 **1 failed / 1 passed**。正式 v4 contract 的前後對照亦重現相同結果，保存於 `.tmp/p2-target-resolution-20261021/replay.json`；red log 為同目錄 `red.txt`。

根因確認在 canonical `scope_resolution.py`：plain-symbol tokenizer 將小寫 `time` 正規化為 TIME；泛用股票／報價語境與 fixture 中已知的 TIME identity 足以形成美股候選。`_resolve_scope` 的問句分支先回傳美股候選，台股名稱／代碼尚未參與判斷；該分支也沒有核對 `market_data_params`。因此是 lexical evidence 與候選一致性問題，不能只交換美台分支順序。此離線重現證明 target bug，不重新驗證價格、quote.auction provider 或 P1 可用性。

### 15.2 原 owner 內的局部修補

- Plain-symbol tokenizer 將 `event time` 視為 timestamp 欄位語意；不全域封鎖 TIME，`$TIME`、`NYSE:TIME`、明示美股 TIME ETF 仍走原美股解析。
- 美股問句解析接受明示 `market_data_params.market=us` 作為 context；不因此把任意未知英文詞提升成已驗證主檔。
- 同一 canonical resolver 比對台股與美股問句候選；台股與美股同時明示時回傳 `target_conflict`、候選與 clarification。TSM ADR 保留既有 ADR 語意，不固定讓台股優先。
- 對問句解析出的 TW／US stock，只有 market／symbol 相符才增加 identity confidence；錯誤 symbol、另一檔股票或不同市場要求 clarification，不拿 params 偷換問句目標。既有缺主檔 assumption 保留。這項核對不改 explicit typed target 的既有 authority，也不擴張 JP／KR normalization。
- JP／KR 原問句解析、freshness intent 優先規則、provider／routing／refresh／price owner 不變。Production 只改 `backend/app/ai/scope_resolution.py`；測試只追加於 `backend/tests/test_ai_us_symbol_resolution.py`。

### 15.3 驗證與 Runtime Gate

新增測試覆蓋真實 `AiAskRequest`／`AiAskV4Request` 原輸入、短問句、2330／台積電／大寫 EVENT TIME、TIME ETF／美元及交易所 marker、TSM ADR、market=us、錯誤／衝突 symbol、台美雙候選與 JP／KR normal。網路連線及 DNS 在新增 fixture 中禁止；沒有補假市場價格。

首輪 safe backend subset `.tmp/validation/20261021-092713/`：**364 passed / 2 failed**。兩個失敗為 `test_ai_freshness_guard.py` 的 `test_position_cost_question_without_stop_words_uses_position_decision` 與 `test_position_stop_loss_question_uses_entry_price_and_latest_price`，皆預期 `latest_price=2310`、實際 `None`。在隔離 Python 程序載入任務前 resolver snapshot，這兩例仍相同失敗（`baseline-freshness.txt`）；沒有回退磁碟 source，也沒有為滿足舊預期改動價格邏輯。它們是本輪前已存在的測試失敗，不宣稱全 repo green。

最終 safe wrapper `.tmp/validation/20261021-093013/`：**366 passed / 2 deselected / 54.68s**（包含新增30例；排除上述兩個已證實 baseline failure）；architecture **54 passed / 30.70s**；checker PASS（actual15/debt15，未新增）；compileall、git diff --check PASS，wrapper exit0。1個既有 event-loop DeprecationWarning 保留。精確命令見原 Progress 的 P2 段落。原 P1 §14 與歷史證據保持原樣。任務前 `main` 有81筆 dirty entries，保留 WIP；四個任務檔的原始內容保存在 `.tmp/p2-target-resolution-20261021/before-*.txt`，相對任務起點的 diff 為同目錄 `task-only.patch`，不是相對 HEAD 的全部 dirty diff。

**Source-only；Runtime adoption／正式 omi.ask／Live／Product 均 PENDING。** 未重啟、未停止服務、未呼叫正式 API／provider、未改使用者 DB、未交易、未 commit／push。使用者提供的 Backend PID10832／release675683f9… 屬先前證據；wrapper 的 listener 觀測只證明程序佔用 port，不證明新 resolver 已載入。後續需另行授權正式 source adoption，取得 loaded-source 證據後才可判定 runtime 修復，不能把本輪離線 replay 當 live acceptance。


---

## 16. 2026-10-21 09:25–09:34｜3406 正式 Demand 生產驗證及當輪收斂

**來源與操作界線**：以下為本對話直接使用正式 OMI MCP 對今日 3406 的當日 1m K 做的獨立觀測及一次明確有界的 `omi.ask` Refresh。沒有修改原 Tier-A 32 cap，沒有以獨立 CLI 或自建Provider/Guard繞過正式Service；Backend PID未變。由於正式Refresh可能由Owner寫入Canonical，本節不稱「整輪0個市場資料寫入」，只確認**沒有人工寫DB、沒有程式修復期間的服務重啟**。

- 09:09 正式 `omi.read_tw_stock_dashboard_detail`：2330 2026-10-21 **5/9** `partial_prefix`；3406 今日 **0/9**、顯示昨日K與 `TW_CHART_SNAPSHOT_MISSING`。
- 約09:25 再讀：2330 **15/25**（最近 09:14）；3406 今日 **0/25**，沒有本日K。不能由此單獨斷言3406當時的 Job/Admission exact reason。
- 針對3406 09:26 完成分鐘，純快取 `omi.ask` `intraday.bars`：**0/26、`not_materialized`、`persisted_miss`**，正式 Canonical `fill_plan` 提供 `tw.refresh_intraday_bars`、`executable=true`、`repair_recommended=true`。
- 隨後唯一一次明確有界 `omi.ask`，`market_data_params={market:tw,symbol:3406,trade_date:2026-10-21,include_intraday:true,intraday_interval:1m}`、`refresh_if_missing=true`、`max_external_fetches=1`、`max_calls=2`、`max_total_seconds=25`，返回 `request_status=background_in_progress`。**這不是 Job SUCCEEDED receipt**；沒有重送該寫入意圖或強制呼叫其他入口。
- 隨後純快取相同股票正式讀取：**2026-10-21 的24根一分鐘K已物化**，`materialization_state=materialized`、`cache_status=persisted_hit`，當時 expected **27**、observed **24**、missing **3**、`series_coverage.status=partial_prefix`，當輪列出的缺分鐘 **09:01、09:24、09:26**。新近分鐘也可能只是生產尚未跟上，不可直接定性永久缺資料、No Trade 或 Provider 漏報。
- 直接證明**同日 Canonical 1m 從0變成24根，正式有限額 Demand／Materialization 管線有能力產生3406資料**；尚未取得完整 JobRun/Refresh Receipt 證明是哪次請求直接導致此結果，不能聲稱 full coverage PASS，也不能直接提高 Tier-A cap／改成GET暗中enqueuer。
- 09:34:46 正式Runtime狀態：Launcher **23480**、Backend **10832**、loaded Application Release **`675683f9bf4eef3563e6d5aef1ee0704de827983dc9f5154dd821385f2e4cbd6`**，restart.available=true、blockers=[]，readiness HTTP200／Runtime+DB ok；今日兩份 Source Patch（§14的單股零IO診斷、§15的TIME resolver）均**尚未載入**。本輪未執行額外重啟或Commit/Push。
- 應繼承的驗收：R2前日 Source/Offline已有PASS；今天MIS/Quote P1仍未修復，今日 §14 診斷修補139 targeted+54 arch；§15 Target Resolver 366 targeted+2 baseline deselected+54 arch；3406只有可用性改善與部分覆蓋證據。若之後要完整驗收，取得既有 Consumer Demand Job Receipt、幾個 Raw 缺桶的來源與是否真無成交的官方證據，無需重掃其他已通過模組。


---

## 17. 2026-10-21 09:43 後｜MIS 排程／IO Ownership 架構複查（Source 定點；未實作）

> 本節接續 §14–§16 與 09:39 Backend-only 採用正式回執。檢查來源：正式唯讀 OMI Runtime／Dashboard、Project Workspace 原始碼、既存 Raw 839797／839800／839810／839825 的前輪對帳證據。**不是重新抓Provider、不是更換Source，也沒有驗證「目前所有 Batch 都已修好」。** 時鐘 Asia/Taipei。
>
> 新的 Codex Bridge 唯讀 Root Cause Job `2813cd20-fec7-4f74-a461-611e7d4e4188` 在 App Server 初始化時因 Windows Sandbox Helper `apply deny-read ACLs / helper_unknown_error -32603` 失敗，**程式執行前就停止**；因此沒有新增 Runtime SQLite 的 Index/Breadth 逐筆時間線，也沒有新Source測試或Patch。沒有改權限、換 Sandbox、重送 Job 或繞過正式保護。既有 Project Workspace 唯讀程式證據仍可使用，應區分工具阻擋與 OMI Runtime 本身。

### 17.1 今日有效的新Runtime驗證

- 09:39 Backend-only 正式終態 `SUCCEEDED`、Backend PID **10832→9416**、Launcher PID **23480不變**，loaded Release **`2676491727eb1b1c41b55167a5a81c85dc6a91ccea9f9227b1d4c8167fb157d0`**、readyz HTTP200／Runtime+DB OK；重啟後原「2330台積電 + event time」`omi.ask` 真實恢復 `tw_stock/2330`，屬已通過且可繼承的 P2 Gate。
- 約09:42–09:43 正式 Dashboard 的當日 Source：TWSE Received **796/1080**，Qualified Directional **78**，Batch Attempted/Failed/Skipped **9/1/2**；TPEX Received **495/887**，Qualified **76**，Batch **6/1/3**，Market Session `regular`。來源資料依然部分可用，不能稱新版Source解決 P1。
- §14 已由Raw證實：839800 TWSE前6批Transport約 **19.153s**，第7批只剩 **0.666s**，其後4批沒發送；839810 TPEX 9/9 Batch完成仍 `z` 合格35＋合格SessionCache25＝60/887 Directional，另有大量未認證資料。**掃描截斷**和**已收到但上游沒合格z**是兩個根因領域，Raw→Canonical的已收到價格沒發現遺失。

### 17.2 已確認的架構跨界／設計錯配（Source Code Evidence）

| Finding | 分類／級別 | 正式Source與已確定行為 | 證據邊界 |
| --- | --- | --- | --- |
| **ARCH-MIS-INDEX-BREADTH-LOCK** | Confirmed Architecture Coupling／**P2**；可能影響指數更新SLO | `jobs/scheduler.py::_add_taiwan_market_index_collector_job` 分設每 **5s** 指數、每 **60s** Breadth，兩者分別呼叫 `indices.py::refresh_current_market_index_snapshots` 與 `refresh_current_market_breadth_snapshots`，最終都進入 `indices.py::_refresh_current_market_summary` 並持有同一全域 `_SUMMARY_REFRESH_LOCK`。Breadth版本在持鎖內按 `INDEX_CONFIGS` **TWSE、TPEX序列執行**，單Venue上限約20s。持鎖時進來的 index5s工作只能等待，`max_instances=1`／coalesce不等於SLO證明。 | Source依賴／串鎖確定；**未取得新完整Runtime 5s調度延誤的Index Raw/JobRun時間線**，不能杜撰實際延誤秒數或宣稱所有指數缺值因它造成。 |
| **ARCH-MIS-INDEX-IO-BYPASS** | Confirmed Provider Admission Boundary Gap／**P2** | `providers/twse_mis_current_index.py::read_twse_mis_current_index` 有用 **相同 `TWSE_MIS_PROVIDER_GUARD`**，但在Guard放行後**直接** `twse_mis.fetch_index_message`；它沒有透過 `twse_mis_breadth_evidence.py::bounded_fetch` 的Venue `_IN_FLIGHT`與`OwnedWorkThread`。同Provider的Breadth與Single Quote已走該`bounded_fetch`。因此 index lane 不受既有「同Venue最多一個在途IO」規則控管，可以在另一路持有Slot時進入傳輸。 | **不表示這次任何特定Timeout已確認由並發Index IO導致**；要以同時期Index Raw/transport timeline做 runtime correlation。保留ProviderGuard，但不能將Guard視為等同IO Admission。 |
| **ARCH-MIS-QUOTE-FAIRNESS** | Confirmed Product Availability Gap／**P1**，根因為共享容量無前景公平性保證 | Breadth每Venue連續發送多達11/9批，持有該Venue Slot期間前景單股Quote `_default_reader` 同樣須`bounded_fetch`，若Slot忙就直接回`TWSE_MIS_PREVIOUS_TRANSPORT_IN_FLIGHT`。實際Raw **839797** 正式Quote外部請求 **0**，在839800正在等待的批次窗口被拒；這是正確安全保護，不是Registry mismatch。 | 需求為15s `PUBLIC_QUOTE_MAX_AGE_SECONDS` 事件時效，但60s全市場背景刷新不能保證該SLO。前景請求尚無可證的優先服務機制；不能修成跨Slot平行HTTP或把舊價時鐘洗新。 |
| **ARCH-MIS-FULL-SCAN-BUDGET** | Confirmed Capacity／Product Scope Conflict／**P1** | `_fetch_messages` 每批100檔、每Venue11或9批，採序列HTTP與單Venue20s絕對Deadline；前6批Transport即可耗盡19.153s（839800），因此正常負載下無法保證每輪全Universe Complete。已存在scan cursor輪轉，保護尾批不永久飢餓，但不同輪的Raw**不得跨輪Union偽裝為同時Snapshot完整**。 | Provider長時間等待是否來自網路、Provider Server或同機其他index IO尚無細分證據；不能直接增大Deadline或調大Parallelism當解法。 |
| **TW-202-UPSTREAM-Z** | Confirmed Source Qualification Gap／**P1**，上游原因 **Unverified** | 09:07 839810 TPEX 9/9成功仍僅35合格當輪z；27個有界原始樣本皆`z='-'`，SessionCache僅在同交易日且量未增加時能續用。Qualified Directional 不是Received Coverage。 | 不能推測所有缺值都是`z='-'`、也不能將成交量 `v>0` 轉成有證據的成交價。1/10/100的Runtime-owned有界對照仍未做。 |

### 17.3 修復順序與停止條件（尚未改碼）

1. **先解耦資料域排程，而非先調Timeout**。保留原 `TW_CURRENT_INDEX`／`TW_CURRENT_BREADTH` Dataset、各自Gateway/Transaction Owner；先用隔離fixture重現一個受阻的index5s讀取，確定 `_SUMMARY_REFRESH_LOCK` 需要的共同資料不變條件與Commit邊界，之後才可將跨域的粗粒度互斥改為按能力的最小Owner協調。必須驗證SQLite寫入競爭、跨域讀取快照不會半完成。
2. **修復 index 的單Venue Admission一致性**。在既有 `twse_mis_current_index` 走同一`bounded_fetch`／Owner Worker（或等價原有正式入口），讓index、quote、breadth都遵循既有Guard與Venue Slot。忙碌時須明確零IO原因、不得扣失敗配額、不得把Source Fallback做成未認證決策價；保留Vendor/官方優先資格。**必須和第一步的公平性一起驗收**，否則可能只把index也困在long breadth掃描而無產品改善。
3. **既有Slot中的可證公平／有界採集政策**（不能加新Manager）。明確定義Foreground Quote與Index／Background breadth如何取得合法序列化IO機會，避免5秒／15秒需求完全被20秒整輪背景占用。任何新排程只在批次間有界讓出，不中斷在途HTTP／Native Writer，不重發UNKNOWN單、不提高總Provider Calls／每輪Budget。Full-universe仍按單輪Receipt誠實報`partial`。
4. **Provider未提供z不能靠上述架構修補假裝解決**。透過正式Runtime內共享Guard/IO Slot的現有owner，在regular session有界對照同股票1/10/100的Raw `z,v,tv,ts,pz`、事件／接收時間、HTTP latency；不能獨立CLI繞Slot，缺乏合格z時仍`unknown`。
5. **最小驗收集合**：同Venue Index/Quote/Breadth 並發時最多一個正式IO；Owner Drain／Admission Pause後不得啟動未註冊worker；Provider429/cooldown不重試；index5秒job不受跨域大型鎖無限制阻塞；前景Quote接到合法新`z`後仍須event-age ≤15s方可decision usable；9或11批Source缺價時 Raw/Candidate/Canonical一致；Quote P1與Breadth P1的Live驗收獨立標示，禁止僅以一輪成功／單測PASS封版。
6. **當前 Blocked**：Codex作業在Sandbox ACL初始化被拒，不能執行修補及離線回歸。對此不修改ACL、切權限或建立替代PowerShell/CLI；先由人類操作員恢復正常Codex Sandbox使用，保留已通過Gates。工作在此停於 **Architecture Diagnosed / Fix Not Started**。

**封版判斷：** Backend Runtime及P2 Target Resolution仍PASS；此處P1未修復，架構Boundary有已確認不一致，但缺少Runtime index/breadth時間線，故建議按以上次序修復，**不建議直接封版或提高Timeout**。

### 17.4 2026-10-21 明確授權的最小 Index IO admission 修補（Source；後續 Runtime 待驗）

本次授權取代 §17.3 的實作先後限制：先單獨修正 Index 缺少共享 Venue IO admission，不把 Lock 解耦／Quote fairness 當本次前置條件。先前 Job `fb1f224d-b5e2-43ea-8279-46c5eed2e3e7` 未改碼而停止，是自行要求 Sandbox 啟動證明；不代表本次工具已遭 ACL 拒絕。沿用現有使用者授權環境，未切換 Sandbox、要求提升權限或修改 ACL。本次實際讀寫成功。

- `read_twse_mis_current_index` 沿用同一 `TWSE_MIS_PROVIDER_GUARD`、`twse_mis_breadth_evidence.bounded_fetch` 與已註冊 `OwnedWorkThread`，由原 channel 的 `tse`／`otc` 選擇既有 slot。HTTP request、timeout 參數、`tse_t00.tw`／`otc_o00.tw` 與 snapshot parser 不變；沒有第二個 slot/provider/cache/manager。
- `TWSE_MIS_PREVIOUS_TRANSPORT_IN_FLIGHT` 與 `TWSE_MIS_RUNTIME_ADMISSION_PAUSED` 是零 IO：取消原 guard attempt（包括 half-open probe）、`external_calls=0`、`status_code=None`。不得沿用 Payload 預設 HTTP200；不增加 guard failure、不清除原 rate-limit 狀態。Provider timeout／429 仍走既有 failure/cooldown；caller deadline 與 provider timeout 保持不同 detail code。
- Current Index adapter 保留原 provider error，不讓缺 payload 的 parse error 覆蓋拒絕原因；失敗 detail code 加入原 AcquisitionSummary limitations。Raw receipt、Provider health、Summary 均可辨識。成功資料與 lineage 不變。
- 在途或未知 native start 保留原 slot/runtime reservation；只在原 worker 完成後釋放，沒有重試未知 IO。未知 start 的 `external_calls=1` 是既有保守 IO reservation，不宣稱已證明 socket request。
- 新增兩 Venue 共 16 個離線 regression，覆蓋成功／channel／lineage、active slot／recovery probe、late Index 阻擋 Breadth/Quote/Index 與異 Venue 可進入、runtime pause/resume、429/Guard recovery、provider timeout、未知 native start，以及正式 Gateway 到隔離 in-memory Raw/summary。測試禁止 socket connect；不使用正式 DB 或 Provider。

驗證命令、結果、Reviewer 與 task-only diff 位置見 [原 Progress 本次段落](../../exec-plans/active/tw-missing-values-source-contract-20261020/Progress.md)。本修補僅消除 IO admission 缺口；20s scan deadline、upstream missing-z、價格覆蓋、Quote 15s freshness 與實際前景公平性仍未解決。

**A 之外僅記錄，未實作：** 解耦 `_SUMMARY_REFRESH_LOCK` 前須以隔離 DB 證明各域 Session/transaction 不共用、Raw 與 canonical snapshot 原子提交、rollback 不污染另一域、SQLite writer contention 有界且不重試未知 write、跨域 reader 對不同 receipt 時間保持誠實而不宣稱 atomic snapshot。Quote fairness 僅保留既有 owner 在批次間有界讓出／優先需求的候選；需另驗 starvation bound、取消與 shutdown、總 calls/budget 不增加。沒有修改 Lock、Scheduler、deadline、頻率、quota 或價格規則。

**交接邊界：** Codex 不重啟、不做 Live HTTP。Reviewer 通過後由對話工具沿用使用者已授權的正式 Backend-only Restart，另驗 loaded source identity、terminal receipt，再查 TWSE/TPEX 股票（例如2330／3406）的正式結果。不得以本次 source tests 取代 Runtime/Live/Product 驗收。


---

## 18. 2026-10-21 10:10–10:15｜R3 Index IO Admission 正式採用與四檔 Live Gate

> 接續 §17.4 Source 修正，使用者已明確授權**只重啟 OMI Backend**並查多檔股票。正式操作使用原 `omi.restart_backend`；市場呼叫使用 OMI MCP 的 `omi.ask` 正式 Gateway，限制為單股每次最多一個外部取得、`max_calls=2/max_total_seconds=16`，未另開CLI或 Provider 通道。行情時間為事件時鐘，不是現在市價。本節以最新 Runtime 證據更新 §17 的「待重啟」狀態，不抹除歷史 Blocked。

### 18.1 正式 Backend-only Restart

- 前置 `omi.read_runtime_status` **2026-10-21 10:09:30 Asia/Taipei**：Launcher PID **23480**、Backend PID **9416**，Owner `1edab05a-8e16-44a1-8b80-849c4842e921`、`restart.available=true`、`blockers=[]`、unfinished futures **0**。
- 正式 `RestartBackend` **只提交一次** `request_id=e3b18a7c-06de-4674-8fee-19664a0b03af`；HTTP **202 accepted**，切換時短暫 `RUNTIME_UNAVAILABLE/ECONNREFUSED`，沒有第二次重送。
- 同 UUID 的 Durable Receipt 最終為 **`SUCCEEDED`**：Backend **9416→73588**，新進程 2026-10-21 **10:10:00.478 Asia/Taipei**，Launcher PID23480未變；Port8400實際Listener=`python.exe` PID73588、`/api/system/readyz` HTTP **200**（runtime/database均OK）。
- Loaded source `APPLICATION_SOURCE_SNAPSHOT`，新 Application Release **`57729af9f0dca676b10fe78f12b63d869c25047da835395cba3678c7980aaefd`**，先前 **`2676491727eb1b1c41b55167a5a81c85dc6a91ccea9f9227b1d4c8167fb157d0`**；重啟後 `restart.available=true`，blockers=[]。僅 Backend重啟，沒有FrontEnd/Launcher/MCP Restart。
- 重啟後正式 Dashboard 仍回 `regular`，TAIEX `fugle_indices_stream` **47031.32@10:12:35**、TPEX `twse_mis_index_snapshot` **397.65@10:11:00**。證明Index正常讀到新當日資料；但**未進行 Live 同Venue Slot 互斥壓測**，因此只能列 `Index Smoke PASS/Admission Contract Source+Offline PASS`，不擴張成全面SLO PASS。

### 18.2 四檔正式單股 Quote（新Runtime，獨立有界取得）

| Market／Symbol | 本次引用的最後 Actual Trade Event | 查詢時 Event Age | 有界正式取得與 Raw | 15秒決策價 |
| --- | --- | ---: | --- | --- |
| TWSE **2330** 台積電 | 2430 @ **10:06:05** | **302s** | Gateway 有 `provider_fetch_attempted=true`，但本次摘要所示實際外部HTTP次數未被獨立確定，不可冒稱1次成功 | **FAIL** stale／`price_decision_usable=false` |
| TWSE **3406** 玉晶光 | 1140 @ **10:10:02** | **93.85s** | `external_calls=1`，Raw `841557`，`ROUTE_REQUIREMENT_UNSATISFIED` | **FAIL** stale／false |
| TPEX **3105** 穩懋 | 513 @ **10:07:15** | **283s** | `external_calls=1`，Raw `841569`，`ROUTE_REQUIREMENT_UNSATISFIED` | **FAIL** stale／false |
| TPEX **3264** 欣銓 | 262.5 @ **09:54:34** | **1064s** | `external_calls=1`，Raw `841579`，`ROUTE_REQUIREMENT_UNSATISFIED` | **FAIL** stale／false |

- **不要把 `ROUTE_REQUIREMENT_UNSATISFIED` 解讀成Registry接錯**：§14既知它只是已嘗試後無新鮮合格候選的Route Gate結果。今天三筆 Raw 的原始 `z,ts,v,tv`、HTTP status/真正Provider原因尚**未直接取得**，不能以此表猜成全部 `z='-'`、全部Slot busy或Provider timeout。
- `quote.official_close` 仍是10/20的官方完成交易日，不能借它補10/21正式即時價；15秒Freshness和Fail-Closed未放寬。**四檔Event Age均遠超15秒，驗證 Quote SLO 尚未達標**。
- 正式 Chart純快取：10/21 2330 **70/75** Current Session 1m（latest10:09）、3406 **24/75**（latest09:25），狀態均 `partial_prefix`；3406先前因一次合法Demand產生24根，但未因此持續被背景Tier-A保證。分鐘缺桶尚未證實No-Trade或上游漏報，不補假K。

### 18.3 全市場與仍待根因

- 10:12前後自然MIS Snapshot：TWSE received **398/1080**，directional **55**，attempted5/failed1/skipped6；TPEX received **878/887**，directional **201**，attempted9/failed0/skipped0。**Index Admission修補後仍有 Full-Scan Budget與上游合格z缺值**，既有P1不因新版換版關閉。
- 為區分三筆今日Raw的HTTP/字面 `z`，唯一新增的 Codex Bridge唯讀工作 `9c853d3a-7b34-4b5c-8b63-fd9d747e48a8` 在 App Server 啟動即被 Windows Sandbox Helper `apply deny-read ACLs (-32603)` 拒絕，**未執行SQLite讀取、未改資料或再次發Provider請求**；不改權限、不用另一個DB入口繞過。這屬工具環境阻擋，Raw原因標 `UNVERIFIED`，不是OMI Runtime故障。
- Gate：**Source+Offline PASS**（targeted 115／Architecture54、checker、16新例）；**Runtime Adoption PASS**（新Release+PID+readyz），**Index Live Smoke PASS**；**四股 Quote 15s FAIL**，Full Universe Breadth仍Partial，Raw起因Unverified，Phase B大鎖解耦／公平性未實作。**整體不建議封版**。

## 19. 2026-10-21 R4-A／R4-B：Last Confirmed Trade 與 Fugle 時間資格（Source-only）

### 19.1 Current：正式 Fugle health 的有界觀測

本輪第一項操作是唯讀 GET `http://127.0.0.1:8400/api/system/health`，只投影 `fugle_realtime` 指定欄位；未保存或輸出 health 大包／key。對照 runtime source 後，以正確的 `subscriptions`、`active_quote_readiness` 欄位重讀一次：

```json
{"connection":"connected","entitlement":"entitled","subscriptions":{"desired":[{"channel":"indices","symbol":"IX0001"}],"desired_count":1,"bound_count":1,"active_stock":null},"quote_readiness":null}
```

**目前分類：股票訂閱／active lease 缺失，Stock Live Gate BLOCKED。** 這證明現有 runtime 連線／認證與指數 binding；不能證明股票 aggregates entitlement 或股票報價 SLA。沒有修改 enable、憑證、plan、quota、active stock 或背景訂閱；沒有發送 Fugle HTTP／WS 取數或試訂閱。

### 19.2 Source of Truth：已有能力與確診缺口

- `tw_realtime_capabilities.py:146` 已註冊 `FUGLE_QUOTE_SNAPSHOT_DESCRIPTOR`：`tw.fugle.aggregates.stream`、priority 10、TWSE／TPEX、VENDOR authority、active stock／Basic 限制。`fugle_realtime_lease.py` 已有 lease；`fugle_realtime_runtime.py::_materialize_active_stock` 已有原 Transaction + canonical reread。不是缺一個 Provider／Cache／Resolver。
- `public_quote_repository.py` 已按 source／trade date 保留最近 actual role；`public_quote_platform.py` Reader／Gateway 及 `project_taiwan_public_last_trade_quote` 已分離 last-trade lineage 和 `latest_observation_lineage`。同量缺 z、舊事實 stale 顯示、跨日拒絕與失敗後保留事實已有基礎能力。本輪只對缺口修補。
- 官方 [Intraday Quote](https://developer.fugle.tw/docs/data/http-api/intraday/quote/) 與 [Aggregates](https://developer.fugle.tw/docs/data/websocket-api/market-data-channels/aggregates/) 分開定義 `lastTrade`／`lastTrial`，`lastPrice` 包含試撮，`lastUpdated` 是更新時間。保留既有微秒轉換，成交價格、數量取 `lastTrade.price/size`，`lastTrade.serial` 留在完整 Raw，不新增 outward 欄位。

| 確診 Source defect | 修補前 fixture 證據 | 原 owner 的最小修補 |
| --- | --- | --- |
| **Fugle 缺合法成交時間仍形成 actual price** | `lastTrade.price=1210`，time missing／invalid／0／bool，trial／total／lastUpdated 當下且 isTrial true／false，仍產生 `TRADE_OBSERVED`。初次正確 contract 負測中此組 8 failures | `fugle_quote_acquisition` 僅在合法 `lastTrade.time`、與 payload trade date 一致且等於 record event time 時映射 actual price／quantity；否則保留 Raw 與非 actual snapshot，不借其他 timestamp。最終三種 fallback 共 24 負例 PASS |
| Fugle payload 日期可將昨日 lastTrade 標成本日 | date=本日但 lastTrade.time=昨日仍帶本日 actual price | 原 adapter 拒絕此組合的 actual price；不替換成交時間 |
| 更新較晚的 aggregates 可倒退成交事件 | lastUpdated 增加而 lastTrade.time 倒退，buffer 原本接受 | 原 buffer 僅對 aggregates 檢查兩筆明確 lastTrade 時間；拒絕倒退。不更動 indices／candles 或 allocation |
| MIS 缺 z、累計量改變後，舊價仍可 qualified current | 原 actual 後 5 秒 z='-'，v 10→11，單筆／批次 Reader 都回 research_usable=true | 原 Repository 保留原價、時間、receipt 與最新 observation lineage；量變（含退量）降為 stale／CURRENT_PRICE_UNVERIFIED |
| 缺 actual 的 trial snapshot 遮住同日已知成交事實 | Fugle 合法成交後收到缺 time 的 isTrial=true snapshot，單筆／批次 Reader 都遺失可展示的已知 fact | 同 source／同日 actual role 照常保留，state 繼承 indicative，維持 facts 與 research/decision 分離 |
| Quote 顯示資格沒有遵守 Resolver 拒絕 | Repository 修補後 research_usable=false，但 legacy row basis=last_trade 的 compact quote 仍 price_decision_usable=true | `quote_depth.py:2327` 原 headline gate 納入既有 last_trade／current_session_last_trade basis，並遵守 Resolver research_usable；不改 AI consumer 或 outward schema |

**Fugle Safety Contract Gap：Source Defect CONFIRMED → offline PASS；Live occurrence UNVERIFIED。** 合法微秒成交時間即使晚收到 3 分鐘也不更新為 received_at；Raw/hash、VENDOR SourceLineage、quantity、cumulative Volume 保留。`_event_time` 的非成交 fallback 仍可描述 snapshot，但不能提供 actual trade 資格。既有 15 秒 freshness、FutureTimestamp tolerance 與 authority policy 未放寬。

### 19.3 驗證與 task-only 交付

新增 `backend/tests/test_tw_r4_last_confirmed_trade.py`，使用 in-memory SQLite，socket connect 被禁止。涵蓋 MIS 同量／量增／量退、單筆／批次一致、原事件及最新 receipt 分離、AI compact quote.snapshot facts/decision、provider timeout／guard／slot 失敗、跨日禁止 y/pz/買賣盤補價、Fugle actual/trial／缺時間／晚到／事件退序／Raw hash、authority／future gate 與不偽裝 MIS identity。

- 修 production 前的有效負測：`red-confirmed.txt` **12 failed／6 passed**；不把最初測試使用錯誤 health 欄位名造成的 harness errors 當成 source defect。
- 正式 safe wrapper `.tmp/validation/20261021-113220/` exit 0：相關 pytest **179 passed / 19.71s**；architecture **54 passed / 31.38s**；checker PASS（actual 15／declared debt 15）、backend compileall、git diff --check PASS。
- Wrapper 後只增加三種時間 fallback 的參數案例，production 未再改動；定點重跑新增檔案 **47 passed / 6.48s**，見 `.tmp/r4-last-confirmed-trade-20261021/final-r4-tests.txt`。未重跑兩個已知 position decision baseline failures，未宣稱 repository 全綠。
- 六檔 task-only patch：三個既有 production owner、上述新測試、此 issue 與原 Progress。preimage、86-entry baseline／hash、manifest、patch 保存在 `.tmp/r4-last-confirmed-trade-20261021/`，diff 相對本輪起點，包含原本 untracked issue／ignored Progress 的本輪增量。
- `backend/app/ai/decision_envelope_v4.py` 的 Auction consumer／fill reconciliation 是任務起點已存在的 dirty WIP。本輪前後 SHA256 均為 `2eef7cf86259216c6b8a7d4279c70c684ef660501b17bdfd3d927e96388cd7f3`；未改寫、未撤回，不納入本輪 patch／驗收。其餘先前 dirty WIP 保留。

可重現的最小足夠 profile：

```powershell
$env:PATH = 'C:\work\Git\cmd;' + $env:PATH
.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs @(
  '-q', 'backend/tests/test_tw_r4_last_confirmed_trade.py',
  'backend/tests/test_fugle_realtime_provider.py',
  'backend/tests/test_tw_public_quote_platform.py',
  'backend/tests/test_tw_quote_depth_shared_projection.py',
  'backend/tests/test_tw_multi_provider_quote.py',
  'backend/tests/test_tw_quote_components.py',
  'backend/tests/test_tw_quote_volume_contract.py',
  'backend/tests/test_tw_g5_price_safety.py',
  'backend/tests/test_market_data_quality_policy.py',
  'backend/tests/test_tw_realtime_viewer_lease.py',
  'backend/tests/test_tw_realtime_capabilities.py'
) -BackendTestTimeoutSeconds 180
```

### 19.4 Runtime-Pending／Live-Gates

**Source PASS ≠ Runtime PASS。** 本輪沒有服務重啟、正式 DB 讀寫、交易、commit／push；正式唯一讀取是上述 local health。§18 PID73588／release57729af9… 是前輪 R3 證據，不能作為本次新 source 已載入的證據。這次未遇 ACL／policy refusal，也未改權限或換入口。

由外部 Reviewer 核對 task-only patch 後，外部 Owner 才依既有授權以正式 `omi.restart_backend` **單次 Backend-only** 換版，驗證 terminal receipt／loaded source identity，再有界查詢指定 2330／3406／3105／3264。Fugle Stock 必須有實際股票 entitlement、active lease、subscription ack 及 qualified actual record；單純 connected／index bound 不能通過此 gate。未取得這些條件時維持 BLOCKED，不啟用付費方案或擴增訂閱。

MIS 繼續全市場 Best-Effort。上游 missing-z、20 秒 breadth budget、四股 15 秒 actual SLA 與其他既有 incident gaps 未因此關閉。本輪沒有新 Provider／Cache／Resolver、Frontend、Launcher、Runtime Control 或 Auction consumer 修補。

### 19.5 R4-C｜2026-10-21 13:28 Lease sync：Source PASS，Live root UNVERIFIED

使用者提供receipt：正式acceptance_probe選KGI（priority5，Fugle10），POST201 subscribing；約12.8s／15.9s PATCH degraded，只有 `CANONICAL_SYNC_FAILED:RuntimeError`；DELETE204、leases0。Backend PID63932／release `a67a85264ab6315b37752b44e845a6480956b9b7d70a95c8f017593e16287d79` 是提供的runtime context，本Job未重新讀runtime。**不能由exception class判定當時是Quote、Kbar、Depth或Auction拋錯。**

有界log evidence：列出 `logs/backend/2026-10-21/` 四個已知application log；搜尋 `13:28|CANONICAL_SYNC|MIS_DEPTH_FALLBACK`（每檔最多10個命中）無結果，三個非空檔僅另讀末尾共7行。未見13:28 step receipt，未讀未知受保護tmp、帳號／key或正式DB。當時raw payload與step traceback **UNVERIFIED**；最小後續diagnostic沿既有logger與lease error留下step/type/cause code，不新增endpoint。

正式鏈：Coordinator → KgiRealtimeQuoteLeasePort → kgi_superpy.heartbeat/snapshot → `_sync_if_live` → `_sync_canonical_snapshot` → `acquire_taiwan_public_last_trade_quote` → Gateway／TaiwanPublicQuoteTransaction／TaiwanPublicQuoteCandidateReader。Cache-only public-last-trade要求actual，quote.snapshot則允許非actual state；後者選KGI且price=null、前者選MIS歷史actual不代表同一價格互相矛盾。13:28屬closing auction，`kgi_quote_has_actual_trade_evidence` 原本即拒絕該階段snapshot作actual，此規則未改。

確認且修正的Source defects：

1. 原owner未檢查Quote qualification，缺actual／stale仍可能live。現在要求Canonical KGI actual、research_usable與原15s／SourceLineage；fresh cache可能讓Gateway跳過adapter，因此非close-resolution另由既有KGI port唯讀buffer確認current live／actual。Close-resolution仍沿原adapter formal-match gate。未改Reader選源或價格值。
2. 原Kbar／Depth例外會阻斷後續能力，四步錯誤只留class。現在獨立處理step，保留exception class與一層cause class；MIS固定錯誤碼保留，不輸出任意exception message。非DB附屬失敗不掩蓋已commit合格Quote，overall仍degraded並明示QUOTE_QUALIFIED／QUOTE_UNQUALIFIED。合法indicative Auction沿Resolver SELECTED、有observation／price判定，不能誤用actual Quote的research_usable，也不提升成actual。
3. Quote／Kbar／Depth／Auction transaction owner各自commit／rollback。真實SQLite IntegrityError負測證明各owner rollback保留先前已commit Quote。Lease不取得rollback權；inactive或直接／Gateway包裝SQLAlchemyError停止本次後續DB IO，即使is_active=true也不當作安全續寫證明。

| 軸 | R4-C Gate |
| --- | --- |
| LeaseTransportReady | Source只在provider state=live且有lease id才同步；13:28提供receipt證明曾進入同步，非actual證明 |
| CanonicalQuoteQualified | offline涵蓋actual、missing actual、15／16s、fresh-cache+absent-current、persistence failure；13:28 actual仍未確認 |
| DepthAuxiliaryFailed | 真實 `_sync_mis_depth_snapshot` failed可重現固定RuntimeError且Quote仍可讀；只是可發生路徑，非歷史根因 |
| FugleFallback | 未修改／未驗收；外層degraded不回寫Coordinator的provider live，不保證轉選Fugle |

驗證：fixture首輪缺required fallback_source屬setup錯誤；修正後有效pre-fix **10 failed／1 passed**。後續失敗逐一對照Source：13:28不能作actual成功樣本（正例改13:24，保留13:28 auction負例）；Auction research_usable=false是合法indicative契約；舊SimpleNamespace補resolved／is_active。未放寬Guard或15s。定點 **41 passed / 7.55s**（新22例＋既有19例）；之後追加保守DB停止條件，只跑必要負測 **4 passed / 2.31s**，未再整組重跑。

Safe wrapper `.tmp/validation/20261021-134242/` exit0：相關regression **99 passed / 16.27s**；architecture **54 passed / 33.21s**、checker PASS（actual15/debt15）、compileall／diff check PASS。Regression僅realtime persistence、public quote、KGI bars、realtime capabilities及R4 last-confirmed-trade。任務preimages、編號patch與manifest位於 `.tmp/r4-c-lease-sync-20261021/`，只含本次六檔增量，保留main既有WIP。

獨立唯讀 omi-data-freshness-reviewer 最終未發現阻擋問題；cached-current資格與wrapped exception原因兩項finding已修正。**Source PASS；Live root UNVERIFIED；Runtime／Live／Product pending。** 未restart、commit、push、schema/migration、正式DB操作、新Live Lease或Provider HTTP／WS。外部Reviewer／Owner決定採用時機，下一有效交易時段才另行授權正式Lease驗收；收盤後不新增probe補證據，不宣稱Fugle failover已修復。


---

## 20. 2026-10-21 盤後工程交接｜10/22 再更新並續測（R4／R4-C）

> 本節是在 2026-10-21 14:37 Asia/Taipei 盤後根據正式 OMI Runtime、Git 狀態、今日正式 API Live 驗收、Codex 任務收據及 §17–§19.5 既有證據整理。**本節只追加記錄，沒有再次重啟、建立股票租約、對外抓行情、修改 Production Source、Commit 或 Push。** 明日 10/22 需另行啟動正式驗收，不把尚未載入的 Source 說成 Runtime PASS。

### 20.1 盤後 Source／Runtime／Git 凍結點

| 範圍 | 目前正式證據 | 判定 |
| --- | --- | --- |
| Serving Backend | PID **63932**，啟動 10/21 **11:47:07**，`127.0.0.1:8400` | 正常運作 |
| Launcher | PID **23480**，未因 R4-C 停止／重啟 | 保留 |
| Loaded application | `APPLICATION_SOURCE_SNAPSHOT`，Release **`a67a85264ab6315b37752b44e845a6480956b9b7d70a95c8f017593e16287d79`** | **R4-A/B 已採用**，非 R4-C |
| Readiness | `/api/system/readyz` HTTP **200**，`runtime=ok`／`database=ok` | PASS，但不代表市場產品驗收 |
| Restart | `restart.available=true`、`blockers=[]`，正式啟動前仍需 Owner/Writer Drain gate；當時有 3 個 unfinished futures | 未再執行重啟 |
| Local Git | `main`，**94 changed entries**（含既有 dirty／untracked／ignored WIP；無範圍清理） | 保留現有工作樹，**未 Commit/Push** |
| Codex | Job **`4ad59549-7c65-4c8f-8143-de0af5f9e697`** 已完成，沒有執行中的 OMI Job | Source 交接完成 |

### 20.2 已完成且可繼承的驗收

1. **R3 Index MIS IO Ownership**：Index 已與 Breadth／單股 Quote 共用原 Venue Slot／OwnedWorkThread，之前 115 targeted、54 architecture／checker 與 10/21 10:10 Runtime Adoption／Index Smoke 已通過；未解的 upstream `z='-'` 和每Venue 20s 掃描不足不隨之結案。
2. **R4-A/B Last Confirmed Trade／Fugle safety**：R4 11:47 Backend-only Restart 單次 `SUCCEEDED`，PID `73588→63932`，採用 `a67a8526…`。保留當日最後實際成交價、原 `event_at` 與最新 observation／received 時間分立；缺合法 Fugle `lastTrade.time` 不將 `lastTrial`／`lastUpdated` 冒充 actual。R4 179 targeted、54 architecture PASS，新增 fixture 最終 47 PASS。10/21 13:08 四股 2330、3406、3105、3264 均 `facts_usable=true` 但 `price_decision_usable=false`：**Historical Facts PASS ≠ 15s Live Quote PASS**。
3. **R4-C KGI Lease Sync**：Codex `4ad59549…` Source／離線完成。正式修改位於 `backend/app/market/tw_realtime_lease_platform.py`、`backend/app/market/providers/kgi_realtime_lease.py`，新增 `backend/tests/test_tw_r4c_lease_sync.py`，調整既有 `test_tw_realtime_viewer_lease.py`。`QUOTE` 的實際成交資格與傳輸 ready 分開；Quote／KBAR／DEPTH／AUCTION 分步診斷且不洩漏 SDK 私密字串；一般附屬失敗保留先前成功 Commit 的 Quote，DB SQLAlchemy／inactive 失敗保守停止後續 IO；15 秒 freshness、交易日／closing auction 條件未放寬。有效 pre-fix 10 failed/1 passed；定點 41 passed，最後 DB stop 負測 4 passed；其他 regression 99 passed、architecture 54 passed、checker（15 actual/15 declared）／compile／diff check PASS。**這一批只屬 Source＋Offline PASS，尚未 Restart Adoption。**
4. R4-C 已保存 task-only patch／preimage／manifest：`.tmp/r4-c-lease-sync-20261021/`；Safe Validation：`.tmp/validation/20261021-134242/`。§19.5 與原 `Progress.md` 已包含詳細測試及 Reviewer 獨立複查。舊 Gate 未受影響者可繼承，不重跑已通過的大量測試。

### 20.3 今日 13:19–13:28 真實訂閱 Live 收據（已釋放）

- 現役 Fugle Health：`connected`／`entitled`，只有 `indices:IX0001` desired/bound `1/1`；`active_stock=null`，沒有股票 Aggregates ACK 或 LastTrade 事件證據。**Index entitlement 不等於股票 entitlement**。
- 正式 Lease Coordinator 的 `KGI priority=5`，`Fugle priority=10`；依 `sequential_fallback` 與 9s transient grace 操作，不該因測試需要任意改成 Fugle 優先。
- 13:19 2330 `acceptance_probe` 一次 POST 201 → `kgi_superpy/subscribing`，隨即 DELETE 204；未得到 ACK。13:24 同樣選 KGI，測試腳本錯用 `TTL>=12s`（正式傳回 9s）提前退出；未驗證 Provider，已 DELETE 並清租約。此測試腳本限制是驗收瑕疵，不是 OMI Defect。
- 13:28 最後一次單租約驗收：KGI POST201 `subscribing`；Heartbeat 2s/5s仍 subscribing；約12.8s／15.9s 回 `degraded`＋**`CANONICAL_SYNC_FAILED:RuntimeError`**；第五次 PATCH 超時，**已使用 finally DELETE204**，之後 GET Summary `total_active_leases=0`、沒有殘留訂閱。沒有觀察到 Fugle 自動接手。
- 13:28 後的正式 Quote：OMI `quote.snapshot` 曾選中 KGI source，但 `last_trade_price=null`，不能判成 Actual Live；Cache-only `GET /api/market/quotes/2330/public-last-trade` 仍可由 MIS 保留當日最後合格舊成交，`facts_usable=true`、`research_usable=false`。兩者依能力與必要 actual qualification 的契約不同，不能憑選中 Provider 宣稱數據即時合格。
- 13:28 屬**Closing Auction**；該階段 KGI snapshot／indicative 不得冒充 regular session actual trade。既有 App Log 針對 13:28 有界查詢未取得分步 traceback，故當天 RuntimeError 發生在 QUOTE、KBAR、DEPTH、AUCTION 何處仍是 **UNVERIFIED**，不可把 RuntimeError 一律歸因為 Depth。

### 20.4 仍未結案問題

| 問題 | 分類／優先級 | 目前證據／限制 |
| --- | --- | --- |
| MIS 上游 `z='-'` 與全市場 Qualified Actual Breadth 低覆蓋 | Source Gap／P1 | TPEX 9/9 完成仍大量 `actual_trade_unavailable`；MIS 單股也可能返回 `z='-'`。不得用 `pz`、`y`、bid/ask 或昨收填成正式成交。嚴格 1/10/100 同股 Runtime-owned 實驗未完成。 |
| 全市場 20s 每Venue Deadline／背景掃描與前景 Quote 共享單Venue IO Slot | Capacity & Availability／P1 | TWSE 可能在一輪中間耗盡 Deadline，前景 Quote 已實際見 `PREVIOUS_TRANSPORT_IN_FLIGHT` 並得到 0 HTTP。不可放寬 Guard／自行平行請求。 |
| Index 5s 與 Breadth 60s 共用 `_SUMMARY_REFRESH_LOCK` | Architecture Risk／P2 | Source 串鎖證據確定；缺正式 index JobRun 時序和 DB atomicity 證據；尚未改鎖。 |
| KGI Quote Lease `Canonical Sync` 具體實盤錯誤 | Unverified Live Root／P1 | R4-C 新Source 已分步診斷，但 13:28 舊Runtime只回 generic RuntimeError；尚無新版的正式Live收據。 |
| Fugle 股票 Aggregate 權限／訂閱 ACK／成交流 | Unverified／BLOCKED | Fugle指數連線正常，不代表股票可用；KGI正式路徑被優先選用。R4-C 的 `QUOTE_UNQUALIFIED→degraded` 不會自動通知 Coordinator 改選Fugle，**Failover未修復**。 |
| Quote 15秒時效、3406持續1m K／全市場完整性 | Product Live Gate 未達標 | 事實／顯示可用 ≠ 交易決策可用；不得以舊事件或不同輪資料拼成假完整快照。 |

### 20.5 10/22（週四）最小續測計畫與 Stop Conditions

**明日不自動執行，需由新對話或使用者指示啟動。** 不必重新進行 R3、R4、R4-C 已通過的Source/Architecture測試，除非共用依賴／Config／正式路徑又有修改。

1. **Source Adoption Gate（建議盤前）**：先讀正式 OMI Runtime Status、Launcher Owner、Dirty Diff 與 `/readyz`；如 Source 尚未載入 R4-C 且 `restart.available=true/blockers=[]`，在使用者當次要求下走 **一次** `omi.restart_backend` Backend-only（不動Launcher/Frontend、不得force kill）；只追同一Request UUID直到 `SUCCEEDED`／`BLOCKED` 終態，確認新 PID／Loaded Release／Readiness HTTP200。若阻擋則停，不重送。
2. **09:00–13:20 regular session 有界 2330 驗收**：在沒有其他Live Viewer Lease 時，僅透過正式 `/api/market/realtime-quote-leases`，單次 POST `owner_kind=acceptance_probe`，按真實Coordinator允許的 Heartbeat 節奏觀察 `provider/status/error`（不設 >9秒的外來TTL門檻），在finally DELETE並GET Summary清理至0；如Route仍KGI，優先確認新分步 `QUOTE/KBAR/DEPTH/AUCTION` error codes、`QUOTE_UNQUALIFIED` vs `QUOTE_QUALIFIED`、是否只是附屬Depth失敗。不要為了測Fugle更改優先級或二次建Lease。
3. **Quote/Evidence Gate**：租約有效時用 cache-only 正式 public-last-trade及 `omi.ask` 查 `provider/source`、`Raw Receipt`、`last_trade_price`、`last_trade_time`、`received_at`、`trade_date`、累計量／NoTrade／Trial／Actual，`event_age≤15s` 才能 `decision_usable=true`；如無成交，只驗證 stale historical facts仍可用且 `decision_usable=false`。事後如需額外 Raw 用正式有界既有入口，不直接外網抓Provider。
4. **Fugle 驗收**：只有正式 Coordinator 依原順序合法選到 Fugle，且取得2330 `aggregates` 股票訂閱 ACK、合法 `lastTrade.time/price`、Canonical/Raw Lineage吻合，才通過 Stock Live Gate。只看到 `connection=connected/entitled` 或 IX0001 不算。
5. **TWSE/TPEX 自然快照與必要擴樣**：僅讀自然產生的 Breadth attempt/failed/skipped、`actual_trade_unavailable`、`provider_missing` 和受控的少量股票（如3406／3105／3264），不得以 R4-C 換版宣稱解決MIS z或全市場SLO。原始錯誤已重現且無新變更時不再無界重測。
6. **結案判斷**：R4-C Live Adoption、KGI Canonical階段性錯誤與Quote資格、Fugle實際股票訂閱、MIS Provider限制分別標 PASS/FAIL/BLOCKED/UNVERIFIED。任何新阻擋先拿真實收據，不直接展開重構；不提交Git／Push或修改交易功能。

**盤後結論：可停止今日測試並保留 R3/R4 已完成Gate。R4-C Source已完成、正式Runtime尚未採用；最後實際交易日錯誤仍缺分步Runtime證據。明日依上述最小驗收接續，無須從G0重跑，整體台股即時行情仍不建議封版。**

## 21. 2026-10-22 G0/G1 市場量能資格修正｜Source PASS；Runtime／Live pending

### 21.1 授權與固定起點

本輪僅執行使用者核准的第一批 G0/G1；停止於 Source 驗收，不延伸 G2/G3/G4/G5。Git 起點為 `main`、HEAD `ec9f042c9f8453bb9708f0343077dcad69af0c7f`、94 changed entries。修改前保存 task-only preimage、原 dirty diff、全體 dirty 檔案 SHA256；交付增量與 audit 位於 `.tmp/g0-g1-volume-20261022/`，不把先前 R3/R4/R4-C WIP 併入本輪 patch。

12:24 的唯讀 Runtime 證據：Owner `79998c2e-7473-4c83-9a39-dcde1427cb6c`、Backend PID **38148**／Parent **39364**、127.0.0.1:8400、`C:\miniconda3\python.exe`；owned_start child_created `134370662931200375`、instance `ebec9c44-ba2b-4807-adf1-69467f1c7303`、`APPLICATION_SOURCE_SNAPSHOT` release **`a9ea1725bb3644487cdd92b48b71f6ba3a888eac805f03189a5507bb49bcd80e`**。readyz HTTP200、runtime/database OK。這是現役識別，不代表本輪 Source 已載入。

使用者提供的自然資料保留為事故背景，未重新取得 Provider Live：11:07 TWSE received1075/1080 directional151、TPEX878/887 directional219；11:13 TWSE497/1080 directional76、attempted/failed/skipped=6/1/5、receipt `b9d2958cb57c4955ab556475111a5d28`，TPEX297/887 directional75、4/1/5、receipt `dd452926b112488abb673ee29d69f168`。11:19 current13,956,232,687／5d median134,323,923,524，原 pace0.1038998、decision_usable=true；11:21 acquisition 不完整仍 trade_value_complete=true。上述數值不冒充本輪重新驗證的 live receipt。

### 21.2 已確認缺陷與最小修正

原 `compose_taiwan_market_volume_state` 僅驗證雙 venue 數值、日期／分鐘、scope／semantics／authority 與 lineage；`_has_usable_trade_value` 也只驗數值及持久化 lineage，沒有 acquisition／估值價格覆蓋資格。因而可對齊的部分估值仍可形成 usable current 與歷史 baseline。

- 原 Market Service owner 新增 typed `trade_value_qualification`，分開「雙 venue 可對齊」與「對宣告 universe 有代表性」。`trade_value_complete` 與 best-effort 金額保留；未合格的 `trade_value_status=best_effort`，不再用 estimated_complete 表示這種狀態。
- MIS 估值要求明示 acquisition_complete=true、零 failed／skipped、無 fallback，且收到數量及 Canonical reason partition 對齊 universe。現有 Canonical actual-price direction 加 verified no-trade 須完整覆蓋；未知、missing-z、partial、缺證據、malformed counts 均保守拒絕。不新增任意百分比門檻、不拿方向比例代替價格、不補零。
- 沿原 minute-state persistence owner 在 `component_sources_json` 的 trade-value owner 保存該次證據；不新增 table／migration／cache／provider。原 event、minute、raw IDs 與 lineage 保留。既有歷史估值缺證據時只在讀取排除，不回填、不用今日 breadth 替昨日證明。
- Fallback composer 與 persisted direct reader 共用資格 gate；歷史逐日驗證，`qualified_sample_days` 必須涵蓋全部已選 baseline samples，5d／20d 不足或未合格均 pace_ratio=null、decision_usable=false，保留原因。官方／合格估值仍依原同期 scope 與 authority 合約正常計算。
- Typed round-trip 保留 qualification、acquisition／coverage evidence 與 qualified sample count；AI 既有 delegation parity 保持，未修改 AI owner。Current architecture 補記於 `BackendArchitecture.md` 原同時間量能小節。

### 21.3 Red／Green 與定點回歸

有效 pre-fix receipts：`red.txt` **29 failed / 24 deselected**（28 個 TWSE/TPEX × fallback/direct × acquisition／coverage 負例，加缺歷史資格），`red-persisted.txt` **3 failed / 53 deselected**（current、history、legacy history）。失敗為原 decision_usable=true／pace_ratio 非 null，非匯入或環境錯誤；第一版相同 32 cases **32 passed / 24 deselected**。

Safe wrapper `.tmp/validation/20261022-123115/`：**131 passed / 2 deselected / 8 subtests passed / 17.25s**；architecture **54 passed / 34.92s**；checker **PASS，actual15 / declared15**；compileall **exit0**；git diff --check **exit0**；wrapper **exit0**。新增正例驗完整 estimated／official 的 5d、20d、typed round-trip、fallback event/received 日期與 SourceLineage；負例涵蓋缺證據、型別錯誤、分區不平衡、partial acquisition／price coverage、persisted bypass 與舊歷史。新增量能測試禁止 socket connect，DB fixtures 全為 in-memory SQLite。

收尾補驗原 index-summary 的 `official=true` authority alias，先重現本輪證據投影遺漏 **1 failed**（`red-official-alias.txt`），修正只沿用 `_eligible_session_trade_value` 既有 authority 合約。最終相同四套及排除式 **132 passed / 2 deselected / 8 subtests passed / 16.21s、exit0**（`targeted-final.txt`）；checker再驗 **PASS actual15/debt15、exit0**（`architecture-final.txt`），四個變更 Python 檔案 compile **PASS**。54 architecture tests 的先前結果沿用，未重跑無受影響的邊界套件。

執行命令（僅這四個受影響 suite，未全庫重跑）：

```powershell
$env:Path = 'C:\work\Git\cmd;' + $env:Path
.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs @(
  'backend/tests/test_tw_volume_composition.py',
  'backend/tests/test_taiwan_market_state.py',
  'backend/tests/test_tw_postclose_source_contract.py',
  'backend/tests/test_tw_intraday_market_capabilities.py',
  '-k', 'not test_tpex_registered_universe_breadth_is_cached_with_estimate_semantics and not test_volume_state_keeps_trade_value_usable_when_breadth_is_missing',
  '-q', '--tb=short'
)
```

兩項排除均已用 **本輪 preimage source** 獨立載入相同現行測試重現：`test_tpex_registered_universe_breadth_is_cached_with_estimate_semantics` 仍精確要求 timeout10，但原 MIS bounded deadline 傳入9.99996…；`test_volume_state_keeps_trade_value_usable_when_breadth_is_missing` 預期混合 official／estimated current1300，但原 comparability gate 已回 null。`preexisting-check.txt` 為 **2 failed**；不修這兩項其他 WIP、不宣稱四套無排除全綠。初次回歸另發現本輪 reader 重走 fallback 清除 partial available value，已改成只共用資格 gate並由既有 regression 驗證保留數值。R3/R4/R4-C 原通過證據繼承，不重跑該等 suites。

### 21.4 交付與停止邊界

本輪交付七檔：`taiwan_market_state.py`、`schemas.py`、`test_tw_volume_composition.py`、`test_tw_postclose_source_contract.py`、`BackendArchitecture.md`、本事故 §21、原 Progress 新增 G0/G1 小節。原有兩個其他測試檔僅保存 preimage／執行，內容未改。Task-only `task.patch`、`manifest.json`、`preservation-audit.json` 保存前後 hashes／diff；Runtime 結束核對另存 `runtime-identity-after.json`。

收尾 preservation audit：97 changed entries（起點94），**91 個非本輪變更的已固定檔案 hash 全部一致**、staged diff 空、HEAD不變；保留既有行尾，未將其他 dirty WIP 正規化。Task patch 對原 preimage 的 `git apply --check --directory=.tmp/g0-g1-volume-20261022/preimage .tmp/g0-g1-volume-20261022/task.patch` **exit0**，最終 `git diff --check` **exit0**。12:35 唯讀 Runtime 再觀察 Owner／PID／creation／instance／release 均與起點一致，readyz200；服務仍載入原 release，沒有本輪 adoption。

**G0 PASS；G1 Source PASS。Runtime adoption／Provider Live／Product pending。** 本輪無 restart、交易、Provider HTTP／WS、quota／lease、正式 DB mutation、commit／push、ACL 調整。Legacy estimate history 因缺資格證據可能重新顯示 warming_up，這是保守資格結果；保留金額，不宣稱重建歷史完成。到此停止，不自動啟動後續 gates。

### 21.5 同任務 Reviewer 補正：market.volume_state outward allowlist｜Source PASS

Reviewer 指出的遺漏已由實際 Source 路徑確認：`capability_contract._normalized_fields` 依 `CapabilitySpec.fields` 拒絕未宣告欄位；`project_selected_data` 依明確 fields 或 `spec.default_fields` 呼叫 `_project_fields` 過濾；`decision_envelope_v4` 正式 projection 呼叫同一 `project_selected_data`。因此 typed schema 有欄位不足以證明 `omi.ask` 可展示。修補前，明確要求 `trade_value_qualification` 會報 `Unsupported field(s) for market.volume_state: trade_value_qualification`，預設投影則遺失該鍵。

修補僅在 `market.volume_state` 的 `fields`、`default_fields` 各加一個 `trade_value_qualification`，直接轉送原 Backend owner 結果，不改市場資格判斷、不在 AI 重算。`test_ai_capability_contract.py` 新增8個 subcases：qualified／partial × default／explicit fields × compact／data path。使用既有 Market Service fixture 實際產生資料，再經正式 selection normalization 與 projection，驗證完整 qualification（含 `reason_codes`）及5d／20d baseline原樣保留；partial原因為 `TWSE:ACQUISITION_INCOMPLETE`、pace_ratio=null、decision_usable=false；合格正例保留比值與空原因。測試禁止socket connect、不建立DB、不呼叫Provider。

MCP offline snapshot 確需同步：生成器 `_load_snapshot` 與 `public_contract_manifest` 由 executable registry 導出 capability欄位及digest。經JSON正規化後，原 snapshot **完全等於本輪修補前 contract**；因此只同步 `agents/omi_mcp_server/public_contract_snapshot.json` 的兩個清單項目及三處digest，並斷言與修補後生成資料完全相等。未無界重產catalog／manifest，未修改外部已安裝MCP。Digest：`e557cd226ebf0bb3a57a99a25647ebc8f49010b1aff27bc3c151abee27c19dfc` → `30f43115e527f95c50b77318dfd794d8538a6ad463029c79e87492d30d205d8f`。

新增修改檔案均先保存至原task preimage；本次起點97 changed entries及前一版patch／manifest另存 `.tmp/g0-g1-volume-20261022/reviewer-followup/`。失敗先行 `red.txt`：**8 failed subcases／1 parent passed／101 deselected、exit1**。修正後 `regression.txt`：**26 passed／112 deselected／11 subtests passed、2.21s、exit0**，包含8個新subcases、相關selection／catalog／manifest、MCP offline snapshot parity及兩個registry architecture checks。Checker **PASS actual15/debt15、exit0**；兩個變更Python檔compile **PASS**。本次未重跑前段132／54 suites，其證據保留。

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'backend'
.venv\Scripts\python.exe -m pytest -p no:cacheprovider backend/tests/test_ai_capability_contract.py backend/tests/test_omi_mcp_server.py backend/tests/architecture/test_registry_parity.py -k 'market_volume_qualification_survives or catalog or manifest or selection or offline_snapshot_matches_backend_public_contract or registry' -q --tb=short
.venv\Scripts\python.exe scripts/check-architecture.py
```

本次增量只含capability allowlist、其測試、offline snapshot、本節與Progress，共5檔；原G1 Market Service／schema／tests未變。原 `task.patch`／`manifest.json` 已合併這項補正，累計10檔；保留最初94 WIP及今天既有G1成果。Source PASS僅涵蓋實際capability selection／projection及離線snapshot，Runtime／Live／Product仍pending；本次沒有Runtime probe、restart、Provider IO、正式DB寫入、commit／push。

## 22. 2026-10-22 盤中 P1／JOB_QUIESCENCE 定點根因複核

### 22.1 範圍、證據與結論

本輪只讀正式 receipt、既存 Raw、JobRun、Launcher／Backend log 與現行 source，離線重播並追加本節及原單一 Progress。起點 `main` **100 changed entries**；101 個既有檔案（包含 ignored Progress）的 hash／preimage 存於 `.tmp/p1-mis-quiescence-20261022/`。G0/G1、R3/R4/R4-C 原修正與 `.tmp/g0-g1-volume-20261022/` 未修改。**沒有 production source patch，也沒有新增 restart／Demand／Provider 請求。**

結論分開：

- **掃描截斷已確診至 caller acquisition deadline**：四筆不完整 scan 均為既有 20 秒 budget 下，前面已完成的序列 transport 消耗大部分時間，下一批等待至剩餘 deadline，其餘批次未發送。不是已證實的 socket connect/read timeout、Guard 拒絕或 slot 拒絕。
- **高 Received／低 Qualified 已確診至來源價格資格不足**：完整 scan 仍大量缺合格頂層 `z`；保存的缺價樣本是字面 `z='-'`。未證實 MIS 上游省略的原因，也未證明 batch size 是原因。
- **12:51 restart 的確切 blocker 是 `unresolved_enqueues=1`**，不是稍早兩個 Future。Gate 當下 Future／active enqueue 均為 0，安全拒絕與 rearm 符合現行契約，不修改 Gate、不清計數。
- 後續 503 有另一次 **12:56:33 tray-menu safe stop** 的 log 證據，不能歸到同一 12:51 UUID；精確 503／status 時間未提供，逐 request 關聯仍未驗證。

### 22.2 六筆單輪 breadth 對帳（時間皆 Asia/Taipei）

每列保留自己的 event／received，不跨輪 union；`z + cache` 是該 receipt 的 component price_source 計數，cache 沿原同日／同量資格，並非新成交。

| Raw ID／Venue | Scan start → finish | Event／Received | Received／Universe | 合格當輪 z＋session cache＝directional | Attempted／Failed／Skipped |
| --- | --- | --- | --- | --- | --- |
| 864304 TWSE | 11:07:24.788 → 11:07:42.889 | 11:07:35／11:07:42.894 | 1075／1080 | 70＋81＝151 | 11／0／0 |
| 864311 TPEX | 11:07:48.362 → 11:08:05.927 | 11:07:55／11:08:05.931 | 878／887 | 67＋152＝219 | 9／0／0 |
| 864407 TWSE | 11:13:05.733 → 11:13:26.436 | 11:13:15／11:13:26.438 | 497／1080 | 40＋36＝76 | 6／1／5 |
| 864414 TPEX | 11:13:26.986 → 11:13:47.111 | 11:13:11／11:13:47.113 | 297／887 | 31＋44＝75 | 4／1／5 |
| 866205 TPEX | 12:52:27.067 → 12:52:47.261 | 12:52:36／12:52:47.263 | 495／887 | 51＋90＝141 | 6／1／3 |
| 866218 TWSE | 12:53:05.285 → 12:53:25.984 | 12:53:18／12:53:25.986 | 597／1080 | 63＋42＝105 | 7／1／4 |

Receipt IDs 分別為 `4f99013c8db542ddbf6ad10a078bef79`、`ce16a64fa1284eccb48cfb6987b72dd2`、`b9d2958cb57c4955ab556475111a5d28`、`dd452926b112488abb673ee29d69f168`、`1e3312b84dc34005a4aa56548675c7ef`、`bcfe9d1e17974fbb9f9b59af267c986d`。使用者於12:53觀察的 TPEX receipt 實際收於12:52:47，未改寫其 clock。

| 不完整 Raw | 已完成批次 transport 合計 | Timeout 批次／起始剩餘秒／實際 caller wait | 未送批次 | Decode／classification 合計秒 |
| --- | --- | --- | --- | --- |
| 864407 | 17.024s | 6／2.674s／2.680s | 7–11 | 0.0026／0.2604 |
| 864414 | 17.716s | 4／1.945s／1.949s | 5–9 | 0.0016／0.2243 |
| 866205 | 19.274s | 6／0.450s／0.462s | 7–9 | 0.0030／0.2399 |
| 866218 | 16.912s | 7／2.803s／2.810s | 8–11 | 0.0035／0.2427 |

四筆 `provider=twse_mis`、`timeout_origin=acquisition_deadline`、`timeout_stage=null`、`scan_budget_seconds=20`；後續為 `budget_exhausted/attempted=false`，不是額外失敗的 HTTP。失敗批次 transport/decode 未完成，receipt 保持 null，不能推定 DNS、TCP、TLS、server、read 或網路哪一段慢。11:13 TWSE 第2／5批 transport **9.592／6.008s**；TPEX 第2／3批 **12.002／5.096s**。已完成批次主要時間花在 transport，不是 JSON decode。`scan_deadline_exceeded=true` 與 `deadline_exceeded=false` 可同時成立：後者是原有 22 秒 cooperative finalization ceiling，不能當作完整 scan 證明。

完整 scan 的頂層缺合格 z 計數：864304 **1005**、864311 **811**；保存 scan missing_examples **33／27** 筆全是 `z='-'`，其中 `v>0` **32／25**。六筆共 **117** 個有界 missing samples 全為字面缺 z，原 source replay 均不產生 current_price／direction。未保存的完整原始 message 不能由樣本推成全量字面分布。864311 主 scan 9/9 成功，但獨立 rescue caller deadline 約4秒、failed1；不混入主 scan 失敗數。866218／866205 的 `actual_trade_unavailable` **490／334** 是資格分類，與 not-received 或所有 missing-z 並非同一集合。

正式 owner：`twse_mis_current_breadth.py::_fetch_messages` 以絕對 deadline 控制序列100檔批次與 cursor；`twse_mis_breadth_evidence.py::bounded_fetch` 保留同 Venue 單一 Future／OwnedWorkThread，late transport 完成前不釋放為可重發；`twse_mis_guard.py` 擁有 cooldown。這四輪沒有 `guard_open`／`transport_in_flight`，因此不能把它們標作此次 batch timeout 的根因。

`indices.py::_refresh_current_market_summary` 仍以 `_SUMMARY_REFRESH_LOCK` 包住 index／breadth 和 TWSE→TPEX 循環；Quote 的 busy slot 仍零 IO 拒絕，沒有 foreground waiter。這些是 §17 已記錄的排程／公平性限制；目前沒有新的 lock wait／slot holder timeline 可歸因本輪四個 timeout。移除共用鎖尚需 transaction／SQLite writer 一致性證據，加入 waiter 尚需 starvation／取消／shutdown 和 quota 上限證據；本輪不憑 transport 慢推導新 Manager 或擴大 lock 改造。

### 22.3 3105 Raw 866252：頂層缺 z、巢狀 trade 與 depth 分開

正式唯讀 Raw：source_id=23、HTTP200、parser=`twse.mis.getStockInfo.v1`，hash `e8ed44d8f1cfa9843fdd60a3daf14f0588c7f6721a8d6a6df2f29ccd2447ee91`。`d=20261022,t=12:54:25,z='-',tv='-',v=20731,ts=0,pz='-'`；received **12:55:13.295091**，snapshot event age **48.295s**。Bid／ask各五檔存在。

原始 payload **另有** `trade={t:'12:54:15',z:'486.5000',v:1,ft:20}`。`twse_mis_canonical.py::canonical_snapshot_from_twse_mis` 現行契約讀頂層 z/tv/v 與 d/t，未採用巢狀 trade；本輪離線重播得到 quote price=null／partial，depth available、5＋5檔，沒有 parser 丟掉已合格頂層 z 的證據。這能解釋 Quote 與 order-book 有不同可用性，但不能只憑 Raw 證明 outward order_book 的即時資格；使用者提供的 current label 保留為正式工具觀察。

巢狀 trade 是待驗證的 Provider 原始欄位，不等於 pz/bid/ask proxy，也尚未有本輪確認的 timestamp／quantity／ft 契約，故不直接接成 actual fallback。即使將其 t 視為當日成交時間，收到時已 **58.295s**，不能用外層 t 或 received 洗成 ≤15s。`ROUTE_REQUIREMENT_UNSATISFIED` 是此次 requirement 未滿足，不能稱 registry mismatch。沒有新 Provider 連線或 1/10/100 試驗。

### 22.4 12:51 JOB_QUIESCENCE 的確切拒絕條件與起源邊界

正式 durable receipt `8b407ecd-73ad-48ed-bc62-73e1737c08c6`：Owner `79998c2e-7473-4c83-9a39-dcde1427cb6c`；before PID38148／created `2026-10-21T14:24:53.1200375Z`、after=null；updated **12:51:36.7782445**；`blocked/PREFLIGHT_REARMED`、stage=`JOB_QUIESCENCE`、`rearm_evidence=INHERITED_OWNER_ACK_SAME_LIVE_PROCESS`。這不是成功換版；receipt 的 loaded release 為 UNATTESTED，不拿它證明 application digest。

`logs/backend/2026-10-21/backend-owned-39364-ebec9c44ba2b4807adf169467f1c7303.log:4883`（檔名屬 Runner；開頭明載 application PID38148）的原診斷：`failure_type=RuntimeError reason=UNRESOLVED_ENQUEUE`，last/final snapshot 一致：`unresolved_enqueues=1, task_failures=0, active_enqueues=0, unfinished_future_count=0, pending_by_lane={}, tasks=[]`，admission_paused=true；剩餘 **48497ms**。不是60秒等不到 active Future 的 deadline。

唯讀 JobRun 對時：168544／168552 均已 `error/CURRENT_SESSION_BASELINE_NOT_READY`，ended_at UTC **04:51:07.491269／04:51:30.505180**（本地12:51:07／12:51:30），都早於 terminal receipt。較早 runtime status 的 running／queued 及 unfinished=2 是先前快照，不能作終態根因。

Source 路徑：`jobs/service.py::jobs_paused` 要求 pending、active enqueue、`_enqueue_failures` 都為0；`runtime.py::pause_jobs_or_refuse_unresolved` 在持續性 unresolved 非零時立即 raise `JOB_ENQUEUE_OWNERSHIP_UNKNOWN`，原 except 記錄診斷後 `abort_owned_restart` 反向 undo。`task_failures=0` 不表示沒有 enqueue 失敗，也不能清 `_enqueue_failures`。

同一程序 log 可定位的一次 enqueue 例外在 **10/21 22:25啟動附近**：scheduler `enqueue_watchlist_radar_outcome_reconcile` → `enqueue_job` → `_enqueue_job` → `create_job` → `db.commit()` 的 JobRun INSERT `sqlite3.OperationalError: database is locked`（log 143–290；參數 created_at UTC14:25:14.814348）。原 `enqueue_job` 的 catch 會累加 `_enqueue_failures` 再 rollback；這是目前與 sticky1 相符的來源，並非12:51那兩筆 Demand 的未完成。該分鐘同 job_type 的有界唯讀查詢無 durable row；**沒有 per-increment reconciliation ledger，不能僅以目前查無 row 對舊程序完成 ownership reconciliation／解除 latch**。未定出當時佔用SQLite writer者，不展開Radar或其他plane修補。

因此本次安全拒絕合理；沒有足以支持修改 Job／Drain owner 的新 defect。本輪不改 pause/rearm/stop、不放寬 gate、不加 preflight、不取消 Future、不直接改私有計數或正式DB。fail-first/red→green **不適用**，因為沒有提出 production 修補；下節列的是既有安全契約回歸，不偽稱缺陷已修。

### 22.5 12:5x HTTP503／controller_unavailable 與另一個本機退出操作

Launcher `logs/launcher/2026-10-22/launcher.log` 另有 **12:56:33 `Exit requested. reason=tray-menu`**，隨後 `Backend safe stop requested. request_id=5b688885-08bf-4816-a9d2-5015524e0583`。這不是本輪Agent送出，也不是重送12:51 UUID。Backend同檔 **4962** 有第二次 `JOB_QUIESCENCE/UNRESOLVED_ENQUEUE`，Future0、active0、unresolved1、剩餘35761ms，前後scheduler clock落在12:56–12:57。尚無該 local action 的完整 terminal owner證據，不能把它混作原遠端receipt或認定安全退出成功。

現行 source：`RuntimeCoordinator.prepare_owned_restart` 先 pause HTTP，再等各owner；`RuntimeAdmissionMiddleware` 在 accepting=false 回 **503 + Retry-After:1 + Backend restart preflight in progress**，route未執行，所以該3406 Demand沒有 admission。失敗時原 `abort_owned_restart` 恢復HTTP；正式 `owned_restart_rearmed` 要求 accepting=true 且無prepare/commit/undo/stop殘留。定點fixture證實 pause回503、resume後同middleware回200；unresolved拒絕也恢復HTTP。

`/api/system/runtime-control/*` 是 middleware 的既有例外；其status另外經 Launcher named pipe（單一2秒deadline），controller失聯／timeout才投影 `CONTROLLER_UNAVAILABLE`／unknown。這個 unknown 不等於 Backend read admission仍關閉。`readyz` 本身沒有該例外，故**同一Backend在其後readyz200**支持該觀察點HTTP已開放，但不能替代Owner attestation或其他時刻證據。

使用者尚未提供503／status／readyz精確時間與同PID關聯，因此暫分類：**與另一個PREPARE時窗相符，單筆因果與當前殘留bug尚未證實**。本輪不自行呼叫status、readyz、Demand或控制路徑；若需補證，由對話正式OMI Owner提供既有 `writer_diagnostics.owner_observations` 中 http.accepting、prepare_in_progress、stop_committed、native_writer_lease_retained，以及同時刻identity／readyz即可，不新增preflight或額外重啟。

### 22.6 驗證、交付與仍開放Gate

- `.tmp/p1-mis-quiescence-20261022/targeted-tests.txt`：**46 passed／4.87s、exit0**。透過既有 `backend/tests/g3_offline_guard.py` 禁止network與正式DB。涵蓋三份MIS receipt／slot／Index suites，以及timeout／late worker、unresolved立即拒絕、真Future等待、HTTP pause→rearm、觀察不清計數、commit-submit不確定性等定點nodes。
- `replay.py`／`replay-result.json`：六筆既存receipt、117個缺z樣本、partition／price-source對帳、四個deadline tail及3105 canonical quote/depth **PASS**；external requests=0、重播不讀正式DB。補充canonical replay時曾因fixture未填InstrumentKey必填type／venue而失敗，已依typed contract修正並通過；不是production fail-first證據。
- `scripts/check-architecture.py --format json`：**PASS，actual15／declared15，無undeclared／stale debt**；完整結果 `architecture.json`。沒有跑build、全套pytest或runtime smoke。
- 正式資料取證僅 SQLite `mode=ro`＋`PRAGMA query_only=ON`，每次query有progress deadline、固定ID或有界source index範圍；receipt／log僅讀。Raw與摘要、restart receipt／JobRun／選定log行、baseline／preimage與task-only patch均在同artifact目錄。
- 收尾UTF-8讀回、task patch preimage apply-check、git diff --check均PASS；起點／終點100 changed entries，兩份文件之外99個固定檔案hash不變，HEAD不變、staged空，兩份文件原有bytes完整保留。task-only.patch只含本節及單一Progress追加。
- 檔名搜尋曾碰到無關 `docs/exec-plans/active/us-r0-r5-20261009/R1E-Receipts` 的ACL拒絕；該子樹停止存取，未改ACL／提升權限／改道。其內容未用作本輪證據。
- **Source**：既有保護定點PASS，無新production修補；**Runtime**：12:51仍BLOCKED，新G1未證明採用；**Live**：六筆自然receipt與3105保存證據完成對帳，P1仍partial；**Product**：全市場Qualified／Quote15s／前景公平性未驗收。使用者起點release `a9ea1725bb3644487cdd92b48b71f6ba3a888eac805f03189a5507bb49bcd80e` 沿用為提供的Runtime基線，本輪沒有新loaded digest證明。

最小後續證據為上述HTTP對時、既有owner的durable enqueue reconciliation證據，以及nested trade的正式來源契約／同股同時資料；均不能用提高quota、放寬價格資格、跨輪union、清latch或額外restart代替。本節不宣稱P1修復或安全重啟成功。

### 22.7 使用者追加核准：歷史不確定與 Safe Stop 執行靜止分離

本段是後續 Source 修補，不改寫 §22.1–22.6 的歷史取證與當時政策。使用者新增正式時間：**12:56:33 Launcher Exit → 13:01:14 BACKEND_SAFE_STOP_PREFLIGHT_REARMED／JOB_QUIESCENCE**；第二筆 Backend 診斷仍為 `RuntimeError/UNRESOLVED_ENQUEUE`、unresolved1、active enqueue0、pending={}、unfinished0。本輪沿用使用者提供時間，沒有再次查現役 Runtime／DB。

**誰在擋**：JobService 的 `_enqueue_failures` 累計涵蓋 INSERT／commit／continuation 結果不確定，原 `jobs_paused`／`JobDrainResult.drained` 把它等同現行未退出的 writer；RuntimeCoordinator 原 `pause_jobs_or_refuse_unresolved` 直接 raise。Launcher `Exit-Launcher → Stop-Services → Stop-BackendService` 正確保留安全拒絕，因而無法完成退出。不能以 Future=0 推成 durable Job 已完成；也不能把12:51正式拒絕倒寫為本來就已獲重啟許可。

使用者明確核准只解除「已執行完、只剩歷史不確定時仍永久封鎖」政策。最小 production patch 只有 `jobs/service.py` 與 `runtime.py`：Job執行靜止要求所有Future、done callback、active enqueue／rollback退出；歷史counter不清零、不再單獨拒絕。新增memory-only `execution_quiescent`／`reconciliation_required`，Runtime在原流程記錄 `OMI_RESTART_JOB_RECONCILIATION_PENDING`；terminal JobDrainResult仍帶原unresolved數。未修改Launcher、重啟身份／STOP／ExactExit協定、DB schema、startup recovery owner或任何MIS來源。

獨立安全驗收的 invariant：

1. **Execution quiescent ≠ durable complete**。未知JobRun可仍為queued/running，停止前原ID、request/result與時鐘完整保留，不偽造paused或success。下一次正式background-leader startup由原 `mark_interrupted_jobs` 明確標interrupted error；第二次cleanup冪等，無新增job或通用Provider replay。cleanup commit失敗向外傳播並保留原記錄。
2. 合法paused descriptor仍經原validation後resume；intraday-demand handoff由原owner保留episode、CAS、deadline、quota及backoff。來源不支持的continuation不得硬重放，paused或quota不明不得偽造完成。
3. `_pending_tasks=0`單獨不足以放行。active enqueue包含未完成rollback；Session scope／未知close、SQLite physical connection／Engine unknown、native external writer exclusion、detached provider ownership及collector final flush仍走原Gate。沒有Future.cancel、kill、清owner、跨Slot或補送transport。
4. GET/status僅memory觀察，不新增DBquery或repair。counter保留到該程序結束，原log／JobRun留存；不新增持久counter ledger，也不宣稱unknown outcome已reconciled。

已用真temporary SQLite／Future驗證兩種未知結果：「INSERT已commit但回應遺失」保留queued、「worker已start後escaping exception」保留running；實際執行Job drain後記錄不變，再以第二個offline受限Python程序呼叫原Runtime startup cleanup，明確標error並保留ID、request/result、created/started與可追蹤ended_at。cleanup commit失敗、未完成Session／physical writer、未知Session close、active transport與start dispatch未確認的Provider reservation皆有負例。測試子程序有20／30秒外層timeout；這是有界離線驗證，不承諾正式大DB的startup耗時上限。

Source契約同步至 `docs/architecture/RuntimeControl.md`。原no-forced-cancellation／transport-no-owner constraints與既有debt未改；新增manager、DB對帳GET、外部Provider連線均為0。正式現役版本沒有被此Source修改熱替換；**Runtime adoption／Safe Stop成功／Exact Exit仍未驗證**。

### 22.8 P1 QuoteFairness：13:15單股零HTTP拒絕與最小待驗設計

使用者追加正式OMI evidence（約 **2026-10-22 13:15 Asia/Taipei**）：TWSE3406，`prefer_live`、`refresh_if_missing=true`、`max_external_fetches=1`；quote.snapshot stale、last **1155@12:55:57**、decision=false。`primary_reader_acquisition.status=failed, external_calls=0`；limitations為 `PROVIDER_REQUEST_FAILED`、`TWSE_MIS_PREVIOUS_TRANSPORT_IN_FLIGHT`、`ROUTE_REQUIREMENT_UNSATISFIED:twse_mis:twse_mis.stock_info`。正式失敗 **Raw866626** 已寫receipt、observations0。本輪記錄使用者提供的正式工具證據，未重新讀取該Raw或發送Provider請求。

這直接證明**該輪前景Quote被既有Venue Slot拒絕，沒有新HTTP**。它與§22.2四筆breadth caller acquisition deadline是分開輪次／原因，不能合併歸因socket timeout、缺z或Guard cooldown；尚無該Slot holder的精確開始／完成timeline，不能斷言持有者必然是12:53同一批。stale事件仍為12:55:57，不用本次失敗receipt時間洗新。ROUTE_REQUIREMENT_UNSATISFIED是此次actual-trade requirement未取得，並非registry故障證明。

現行Source沒有bounded foreground priority admission，故本輪不硬改。最小可行設計只在既有 `bounded_fetch` Venue slot owner 內討論：前景依原caller絕對deadline登記有界等待意圖，背景僅在一個transport**實際完成並由原owner釋放**後、下一批admission前讓出一次機會；不取消、不替換、不重送仍未完成transport。以固定小額等待容量／每輪讓出上限防止前景暴增餓死breadth；滿額或到期回明確零IO reason。Guard/cooldown、原quota與scan budget在真正IO admission前仍須通過；breadth等待耗用原20秒budget，到期即寫該輪partial與原時鐘，不另開隱藏補掃。這是設計提案，尚未採用。

落地前需離線fail-first與以下驗收：同Venue最大IO=1；late worker在deadline後仍持Slot；前景等待到期／取消／容量滿時external_calls=0；Guard open時不繞過cooldown；兩Venue隔離；交錯多Quote仍有界讓背景前進；quiescence拒絕新waiter並保留既有transport至真退出；每輪attempted/failed/skipped及partial receipt對帳、event/received不改寫、缺z仍unknown。須先取得有界holder／wait時間線確認阻塞來源，才決定是否需要觸及 `_SUMMARY_REFRESH_LOCK`；本輪不移除該鎖、不提高limits、不做1/10/100實盤試驗。

### 22.9 本次修補驗證與保留範圍

本次起點仍main100 changed entries；102個固定檔案（含ignored Progress與原clean preflight test）已保存hash／preimage於 `.tmp/job-quiescence-history-20261022/`。第一組真fail-first：**5 failed／1 passed**（`red.txt`）；相同6 cases修補後 **6 passed**（`green.txt`）。Reviewer追加durable recovery／active writer／Provider ownership首組 **7 passed**（`reviewer-regression.txt`）。最終相鄰regression **125 passed／29 deselected／136.21s、exit0**（`targeted-regression.txt`），涵蓋三份變更測試、Runtime以及相關owner ledger／handoff；deselected為本次未改的shell／Runner integration及EOD排程業務案例。既有offline guard禁止外網與正式DB，只有disposable fixtures。

`test_owned_shutdown_boundary.py` **6 passed／0.14s**；`check-architecture.py --format json` **PASS actual15／declared15、無新增／stale debt**；5個Python變更檔compile PASS。收尾UTF-8、task-only patch對preimage apply-check、git diff --check與非任務WIP hash核對見 `preservation-audit.json`。此前MIS46 cases、G0/G1與R3/R4/R4-C證據保留，不宣稱本輪重新Live驗收。

後續force政策討論已依最新範圍校正取消：曾新增的force-specific測試已撤除，沒有production force hunk。Launcher、`OmiOwnedShutdown.cs`、`OmiRuntimeControl.cs`、`omi-runtime-control.ps1`、`apply-omi-update.ps1`、`owned_uvicorn.py`均與提案前hash一致，證據 `.tmp/owned-force-deadline-20261022/cancelled-policy-audit.json`。**180秒強制截止只列獨立政策提案待使用者明確授權，不是本次實作或採用政策**；force提案的暫存失敗測試不列入G2驗收。未發任何新restart／stop／force kill，未觸碰現役Runtime或正式DB。

交付狀態：**G2 Source／Offline PASS；Runtime adoption／Safe Stop／Exact Exit／Live仍UNVERIFIED**。本次production改動只有JobService與RuntimeCoordinator，另有三份定點測試、RuntimeControl契約、本§22與原單一Progress。MIS P1維持OPEN／partial，13:15 QuoteFairness證據與待驗設計已獨立記錄。


## 23. 2026-10-22 盤中 G3／G4／G5 最小正式驗收與 G2 後續交接

> 時區 Asia/Taipei；本節取證包含正式 OMI MCP / 官方 localhost Backend API、G3 Codex 單租約驗收收據、G5 離線 profile 與 Reviewer 對照。G2 的 MIS / Job Quiescence 根因與 Source patch 詳 §22，本節不將 Source PASS 冒充已載入 Runtime。沒有交易、提交 Git、擴大 Provider quota 或第二次重啟。所有價格僅作資料品質事件證據。

### 23.1 Runtime 版本與安全邊界

本輪 Backend-only restart 原始 UUID `8b407ecd-73ad-48ed-bc62-73e1737c08c6`，正式 terminal `BLOCKED / PREFLIGHT_REARMED / JOB_QUIESCENCE`；未另發新 UUID、未 force kill。盤中最後核對 Backend PID **38148**、Owner `79998c2e-7473-4c83-9a39-dcde1427cb6c`、loaded `APPLICATION_SOURCE_SNAPSHOT a9ea1725bb3644487cdd92b48b71f6ba3a888eac805f03189a5507bb49bcd80e`；`/api/system/readyz` HTTP200（runtime/database ok）、`restart.available=false` 且 `ALL_WRITERS_DRAIN_UNAVAILABLE`。G1／G2 新 Source 未採用，不能宣稱其 Runtime／Live PASS。

### 23.2 G4：同日 1m Demand 與 Materialization 實證

正式 `omi.ask` 先 cache-only 查三檔當日 `intraday.bars` 皆 0／`persisted_miss`；各股票只發一次有明示 `refresh_if_missing=true`、最多1次外部取得與 bounded Consumer Demand，再以純 cache-only 同股票回讀。初次 Demand 的 `request_status=background_in_progress` **只代表已進入背景狀態，不能單獨宣稱 Job SUCCESS**；以下以後續正式 Canonical 快取觀測為準。

| 股票 | Demand 後可讀 Canonical 1m | 查詢時 Coverage | 限制 |
|---|---:|---|---|
| 3406 玉晶光 | 237 根，`persisted_hit` | 13:02 expected242／observed237，`partial_prefix` | 缺 12:12 一分鐘，另尾端12:58–13:02尚未形成可確認Bar |
| 3264 欣銓 | 239 根，`materialized` | 截至12:59 expected239／observed239，`complete_prefix` | 只對當時已完成的分鐘前綴成立，非全日官方 Final |
| 3105 穩懋 | 240 根，`materialized` | 截至13:00 expected240／observed240，`complete_prefix` | 同上 |

三檔正式 `provider=nstock`，沒有跨層直接抓 Provider、合成假零量K或在GET偷偷 enqueue。**結論：顯式 Consumer Demand → Canonical Materialization 可用；背景 Tier-A 未自動納入全部標的，仍須按 `tw_intraday_universe.py` 的 configured→holding→active lease→watchlist hard cap 與當日 JobRun 逐檔確認。** 3406 缺分鐘未證為 OMI Parser 遺失。

### 23.3 G3：2330 唯一正式 Live Lease 與 Quote 資格

13:03:27 先經官方 readyz200 / `GET /api/market/realtime-quote-leases/summary` 看到 `total_active_leases=0`；只做一次正式 `POST owner_kind=acceptance_probe, stock_id=2330` 回 HTTP201 `kgi_superpy/subscribing`，TTL9s。約第2／5秒兩次 PATCH 仍 KGI subscribing；約第10秒第三次 PATCH **自動選成 `fugle_marketdata/connecting`，錯誤 `FUGLE_QUOTE_SUBSCRIPTION_PENDING`**。第4次 PATCH 發生4s timeout（delivery unknown），未重試、未送第5次 PATCH。13:03:44 唯一一次 `finally DELETE` 回 HTTP204；緊接與 13:04:06 再查 Summary 均 `total_active_leases=0, active_symbol_count=0`。Reviewer 另獨立唯讀確認 leases0。

唯一一次 cache-only `public-last-trade` GET @13:03:32：MIS provider `twse_mis` 2395元，原 actual 事件 **12:57:15**、當時 age **377.8s**、Raw `raw_fetch_result:866290`，`facts_usable=true, research_usable=false, status=stale`，**不合格於15s decision**。此 GET 在 Fugle 自動接手前，不能推定接手後的新行情；KGI 原 persisted candidate 為10/21且無 last_trade_price。解除訂閱後 health 只證實 `indices/IX0001` desired/bound 1/1、`active_stock=null`，未證明 Fugle 股票 aggregate ACK／entitlement／qualified actual。**Fallback選路 PASS，股票當日 actual／Canonical 實盤資格 FAIL / UNVERIFIED，租約清理 PASS。** 這次未觀察 `CANONICAL_SYNC_FAILED`，不足以證明 R4-C 被載入或原同步問題修復。

另外13:15 3406 單股正式 MIS `quote.snapshot` 在 Venue Slot 前得到 `TWSE_MIS_PREVIOUS_TRANSPORT_IN_FLIGHT`、`external_calls=0`、Raw866626，只保留 stale 1155@12:55:57；此已在 §22.8 獨立記為前景 QuoteFairness defect evidence。3105的單股有界 MIS Raw866252 為頂層 `z='-'`，五檔可讀但 actual 不合格，詳 §22.3。

### 23.4 G5：3105 技術能力複合查詢的逾時及離線取證

正式 serving Backend 於盤中針對3105同時選取 `technical.indicators`＋`technical.structure`，即使只要求最小 fields、無外部 acquisition，仍約30.091s 回 `READ_NODE_TIMEOUT: technical_evidence`，兩項能力 manifest 缺值。當日3105的1m已另有 240/240 `complete_prefix`，**不能因此直接推論完成日線技術指標有資格**。

獨立 G5 source/profile Job `315046f4-4404-4940-9e4a-ee32388495b3`，使用限制唯讀SQLite及正式 Python `omi.ask` ReadGraph 重播：單 indicators 的 `technical_evidence` 約4.911s；indicators＋structure 的 `technical_reports` 約3.043s、`technical_evidence` 約6.407s；雙能力整體含冷import約13.077s，未重演15s Read Node Timeout。SQL execute 合計分別0.031／0.289s（不含 ORM/深拷貝）；主要成本為日／週／月 canonical Bars、day-state／lineage/ORM；輸出約9KB、JSON序列化約0.10ms。故 **原盤中30s根因仍 UNVERIFIED，未改 production code，也未放寬 timeout**。只新增 `backend/tests/test_g5_technical_read_profile.py` 的14個已通過 fixtures，涵蓋單／雙能力、唯一 read owner、select fields、timeout與不合格 daily；相鄰回歸 **166 passed、8 subtests passed**，architecture checker、compile、diff-check／patch回放 PASS。先前12個失敗屬測試 setup 問題，不算 production red。完整 evidence 在 `.tmp/g5-technical-evidence-20261022/Report.md` 和 `task.patch`。本輪最終 profile 使用全連線 read-only mode=ro＋query_only；最早一組 harness 有 technical-setting SessionLocal 漏接，已標成不可作嚴格唯讀證據，無正式 DB DML。

### 23.5 Gate 與未完成事項

- G0／G1：Source+Offline PASS，尚待正式 Backend source adoption。
- G2：§22 Job Quiescence 正當 Source+Offline PASS；由於現役 Backend 仍為舊版且前次 Restart terminal BLOCKED，尚無 Runtime Safe Stop／Exact Exit PASS；MIS 20s acquisition deadline、上游缺合法 z、前景 Slot fairness 仍 P1 OPEN，沒有憑推論改 Provider。
- G3：Fallback選路與Lease清理已實證；KGI/Fugle 合格 actual 15s仍 FAIL／BLOCKED，股票 entitlement及ACK未確認。
- G4：顯式 bounded materialization路徑可用；背景 admission／3406缺桶仍 PARTIAL。
- G5：ReadNode Timeout 在正式 Runtime 已重演，但離線 Source 未定位唯一根因，產品未修；只補保護與可重現 fixtures。
- 整體 G6 **不建議封版**。未重啟採用新版前不以磁碟 Source 測試宣稱市場功能已在 Live 修復。禁止以非Owner強制終止、第二入口繞過 PREPARE 或把 stale/missing price 洗成 actual。



## 24. 2026-10-22 13:34–13:35 盤後最後純快取觀察

本次只經正式 `omi.read_tw_workspace_header`／Dashboard cache-only讀取，沒有要求Provider新擷取、補資料或再次重啟；Session `post_close/completed`，下一轉換為10/23 08:00。最後互相一致的 `resolved_breadth` 是**各市場獨立單輪收據**，不能跨輪拼成全量。

| Venue | Event Time | Universe／Received／Qualified Directional／Unknown | Acquisition |
|---|---|---|---|
| TWSE | 2026-10-22 13:30:00 | 1080／398／**144**／936 | partial，attempted5、failed1、skipped6，receipt `4d61643dbf4c4ecfb3b9c5b89a837296` |
| TPEX | 2026-10-22 13:30:00 | 887／793／**476**／411 | partial，attempted9、failed1、skipped0，receipt `b98952aef629423ab90a631acc646749` |

13:35:23 的指數 `resolved_indices.TAIEX=46099.28`（Fugle stream）與 `TPEX=381.39`（MIS Index snapshot），事件時間皆13:30，仍 `official_close_confirmed=false`、`official_close_status=pending`、`finalization=provisional`、`decision_usable=false`，不可冒充已正式發布的收盤指數；可能尚待官方Daily Provider釋出。這裡是 OMI當時觀察，不當成外部證交所正式收盤報價。

**盤後門檻仍未過**：兩個Venue `decision_usable=false`，TWSE方向覆蓋144/1080與TPEX476/887均不完整。13:30收盤後仍有MIS Batch failure/source缺價；Runtime仍舊版PID38148，故本輪不能驗證G1/G2新Source在正式服務的產品效果。這組收據作為下次正式採用後的歷史對照，不能把今日所有未分類股票視為平盤或零成交。