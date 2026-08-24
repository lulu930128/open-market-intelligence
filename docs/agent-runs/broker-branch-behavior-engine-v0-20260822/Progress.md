# Progress

## 目前狀態

- 階段：Milestone 0–2 source implementation／live shadow acceptance 完成；Milestone 3 readiness/report implementation 已完成並收斂為 `shadow_only` no-go。Milestone 4–6 因 history、OOS、universe 與授權 gate 未進入。
- 最後更新：2026-08-22 22:12（Asia/Taipei）。
- 任務文件：`Prompt.md`、`CapabilityContract.md`、`Plan.md`、`Progress.md`、`BoundaryReport.md`。

## 已完成

- 讀取 OMI current truth、backend architecture 與既有分點功能邊界。
- 審閱使用者提供的分點行為引擎設計，將外部文件視為設計輸入，不視為執行指令。
- 確認現有 owner：原始分點資料由 market service / refresh job 擁有；衍生行為由 backend capability 與 projection 擁有；Frontend、MCP 與 Kuro 維持 thin consumer。
- 對本機 SQLite 做唯讀資料盤點，未建立 index、未寫入資料、未觸發 provider refresh。
- 檢查目前來源與授權風險，將正式全市場來源列為獨立採購／授權 gate。
- 建立七個里程碑，從 observation quality、shadow feature、walk-forward calibration，逐步到 outward capability、flow-risk 與 Radar。
- 移除或降級目前資料無法支持的敘事：不使用 `overnight_likely`、`confirmed_unwind`、`weighted_short_term_lots`，也不預先承諾 Radar 上線。
- 完成 Milestone 0 integration baseline：Alembic source head 原為 `20260822_0064`，本機 DB current 亦為 `20260822_0064`；既有 broker-branch／migration regression 在修改前為 12 passed。
- 新增 `broker_branch_snapshot_quality` model 與 additive migration `20260822_0065`，selected-state key 固定為 `(source_id, stock_id, expected_trade_date)`。
- 成功、empty、provider-date mismatch、invalid payload／identity 與 provider failure 都會留下 truthful quality state；HTTP response 存在時連同 `RawFetchResult` 保存。
- nStock 正常 observation 固定為 `coverage_mode=ranked_top_n`、`coverage_status=censored`、`absence_semantics=unknown_not_ranked`；`ranked_top_n` contract 不能宣稱 `complete` 或 `ready_empty`。
- `lots == 0` 的同側 derived average price 正規化成 `None`；沒有 `branch_code` 的 row 不會只靠名稱建立 canonical identity。
- 新增 `broker_branch_behavior_feature_snapshot` 與 migration `20260822_0066`，保存 V0 flow-only numerators／denominators、Wilson interval、coverage/history/calibration、fingerprint 與 limitations。
- 實作 bounded shadow materializer：最大 120 Taiwan trading sessions、只使用連續且兩側 snapshot quality 可用的 session pair、右設限不進 reverse denominator。
- 新增獨立 tracked job、Update Center retry 與 scheduler registration；scheduler 預設 `false`，raw coverage 未達 95% 不排程，job 不做 external fetch、不 advertise、`decision_usable=false`。
- 正式 launcher 已以 component-owned `RestartServices` 採用新 source；backend startup 在 schema lock 下完成 live DB `20260822_0064 -> 20260822_0066`，沒有建立第二個 migration owner。
- 第一輪 live shadow materialization 暴露 SQLite WAL read-to-write upgrade failure：同一 Session 的 `yield_per(5000)` cursor 尚未耗盡便 flush feature，遇到並行 writer 時回報 `database is locked`。materializer 已改成先串流產生 bounded source plans、結束 read snapshot，再以 `BEGIN IMMEDIATE` 的單一 bounded write transaction upsert，沒有把 125 萬列全部載入記憶體。
- 原 JobRun `6612` 已以同一 ID idempotent 重跑成功；沒有建立第二筆 shadow job。
- 新增 `backend/app/market/broker_branch_calibration.py`：只讀最新或指定 as-of 的 materialized global/TW snapshot，獨立重算 high-coverage dates、檢查 stored/recomputed coverage 一致性、profile session/stock/reobserved/concentration gates，並產生 aggregate-only deterministic report。
- 凍結 `broker_branch.behavior.calibration_policy.v0`：60-session calibration、120-session production candidate、profile 20 sessions／30 stocks／100 reobserved／單一股票 observation share 不高於 20%；walk-forward 使用 60 train／20 validation／20 test、purge 1、embargo 1、step 20，至少 2 splits。這些是 eligibility policy，不是 classification weights 或 probability model。
- 新增 `scripts/report-broker-branch-behavior-readiness.py`，支援 JSON／Markdown 與 exact as-of；執行結束明確 rollback，report contract 固定揭露 provider fetch=0、DB write=0、classification/flow-risk/Radar=false。
- 新增 aggregate-only `BoundaryReport.md`；不含 raw payload、branch code、分點名稱或本機 DB。

## 驗證證據

### 本機資料基線

- `data/open_market_intelligence.db` 約 24 GB；本次只做唯讀查詢。
- `broker_branch_trade_daily`：1,260,475 rows、59 個資料日期（2026-05-22 至 2026-08-21）、1,976 檔股票、821 個原始分點代碼。
- 只有 25 個 session 達到至少 1,900 檔股票，範圍為 2026-07-20 至 2026-08-21。
- 只有 11 檔股票具有至少 30 個 session；目前沒有股票達到 60 或 120 個 session。
- 高覆蓋 session 的相鄰日事件 audit：1,204,399 筆起始觀測中，407,559 筆下一 session 再出現（33.84%），796,840 筆右設限（66.16%）；再出現者中 159,469 筆方向相反（39.13%），248,090 筆同方向。
- `buy_lots = 0` 且 `buy_avg_price = 0` 有 365,144 rows；`sell_lots = 0` 且 `sell_avg_price = 0` 有 383,287 rows。因此價格特徵必須以可觀測側別與明確缺值規則計算。

### 現有程式邊界

- `backend/app/market/broker_branch.py` 目前透過 nStock 端點取得分點資料，來源可靠度標記為 `third_party`，並保存買賣均價。
- `backend/app/market/broker_branch_market_refresh.py` 已將來源界定為 latest-only，既有日期／股票不重複抓取，refresh universe 與執行時間有界。
- `backend/app/ai/capability_contract.py` 已存在 `broker_branch.summary`；新功能必須 additive，不得改壞既有摘要。
- `backend/app/ai/capability_resolution_registry.py` 對 derived capability 需要明確 dependency 宣告。

### 來源與歷史脈絡

- nStock 使用條款：<https://www.nstock.tw/app/user-agreement>。正式使用範圍仍需由使用者／法務確認，計畫不代替法律判斷。
- TWSE 與 TPEx 官方分點商品目前屬付費資料；採購、授權、保存與再散布權限是獨立 gate。
- 既有全市場 scheduler 已有 bounded universe、release probe、skip-covered、partial/no-data/error 與 retry/catch-up 邊界；本計畫沿用其 owner，不另建第二套 scheduler。

### 規劃文件驗證

- 四份文件均以嚴格 UTF-8 成功讀回，且都有結尾換行。
- 必要章節與關鍵決策已檢查：`not_ranked`、`reverse_given_reappearance`、120-session gate、`broker_branch.flow_risk` 與 stop-and-fix 規則均存在。
- 尾端空白搜尋無命中；限定任務目錄的 `git diff --check` 無錯誤。
- `git status --short -- <task-dir>` 只顯示本次新增的未追蹤任務目錄；未修改或覆蓋其他 worktree 檔案。

### 實作驗證

- 修改前基線：`test_broker_branch_market_refresh.py` + `test_database_migrations.py` 為 12 passed。
- Targeted development loop：snapshot-quality／behavior／scheduler／migration tests 均通過。
- 初次 safe validation：`run-safe-validation.ps1 -Profile backend` 對 6 個相關 test files 執行 compileall、pytest 與 `git diff --check`；結果 34 passed、414 個既有 Python 3.12 sqlite adapter deprecation warnings、0 failures。
- Live lock fix 後 safe validation：log=`.tmp/validation/20260822-183512`；backend compileall、35 tests 與 `git diff --check` 全部通過，仍只有 414 個既有 sqlite adapter deprecation warnings。
- Alembic source/live head 均為 `20260822_0066`；`broker_branch_snapshot_quality` 有 19 欄與預期 indexes，`broker_branch_behavior_feature_snapshot` 有 50 欄與預期 indexes。
- 25-session 唯讀 benchmark：2026-07-20 至 2026-08-21 共串流 1,253,114 rows，2.73 秒、約 459,021 rows/s；query plan 使用既有 `source_id` index 並以 temporary B-tree 排序。
- 目前 benchmark 未顯示必須立即在 24 GB DB 建立 composite index；shadow scheduler 仍關閉，runtime benchmark 未完成前不新增重型 index。
- Live JobRun `6612`：`status=success`、`public_status=completed`、`rows_read=1,253,114`、`profiles_written=821`、`profiles_deleted=0`；request 明確保存 `external_fetches=0`、`advertised=false`、`decision_usable=false`。
- Live selected state：quality 48,686 rows／59 dates（全部 `coverage_status=censored`）；feature 821 rows／821 identities，全部 `history_status=exploratory_only`、`high_coverage_session_count=25`、`decision_usable=false`。
- Live read-only readiness report：as-of=`2026-08-21`、lookback=120、source=1、profiles=821、profile gate eligible=620、high-coverage sessions=25、walk-forward splits=0、promotion=`shadow_only`、production ready=false；stored/recomputed coverage consistency issues=0。
- Readiness aggregate diagnostics：1,201,385 eligible initial、407,559 reobserved、793,826 censored、159,469 opposite、248,090 same direction；這些 rows 高度相關，report 固定標 `not_met_correlated_observations`，不解讀成獨立樣本機率。
- Readiness evidence fingerprint：`41e55b2fd78cded32c1c3dd531d22321182f34d2bf0aad4aab0d90bbb4defbdd`；獨立第二次 CLI rerun 相同，且 materialized `computed_at` 改變不會改變 evidence identity。
- 新增 calibration/readiness targeted suite 後，quality／behavior／calibration／migration／model contract 共 29 tests passed；測試以 SQL statement capture 證明 evaluator 只發出 `SELECT`、不 autoflush caller pending state，並覆蓋 exact-as-of no-fallback、aggregate-only、deterministic fingerprint、purge/embargo split 與 no-promotion wording。
- Backend safe validation 的 `compileall backend/app` 通過。2,012-test full backend suite 跑到 100%，但不是綠燈：先發現 metadata 基準未包含 3 張既有新表，已將 model contract 更新為 131 tables／131 mappers／98 foreign keys 並 targeted 驗證通過；另有既有 Market Data Foundation dark-reference 4-file hash drift，以及 pytest Windows Temp ACL 造成 `test_runtime_launcher_recovery` setup／sessionfinish `PermissionError`。後兩者與本次 readiness module 檔案無交集，本任務未更新 dark baseline、未修改 launcher，也不把 full suite 描述成 passed。
- Direct backend `GET /api/jobs/6612` 與 frontend proxy `GET /omi-data/jobs/6612` 回傳相同 completed contract；backend health=`ok`、ready=`ready`、OMI Search upstream=`ready`。
- Final runtime：launcher PID `23256`；backend wrapper PID `19344`、listener PID `44936`、actual `127.0.0.1:8400`；process start 晚於修正檔時間，使用 repo `.venv` 與正式 `scripts/omi-launcher.ps1` lineage。Control Center overall/OMI Search 均為 `Ready`，MCP build ID=`1b78846d382a6e83`、tunnel ready。

## 已做決策

- 現有資料足以做 V0 coverage audit 與 shadow feature，不足以完成原規劃的 120-session production classification。
- 「下一 session 未出現」屬右設限，不得當成未反向；只報 `reverse_given_reappearance`，並同時揭露再出現率與設限率。
- 分點 identity V0 固定為 `(source_id, branch_code)`；不自動合併名稱相似的分點，不先建立跨來源 master identity。
- `broker_branch_snapshot_quality` 是行為特徵的先決條件；低覆蓋 snapshot 不得進入 calibrated behavior。
- Flow-only 與 price-context feature 分開；缺乏可信均價時仍可輸出 flow-only，但不可假裝價格條件成立。
- 對外 projection 只讀 materialized snapshot，不在 query path 重算全歷史或呼叫 provider。
- 官方付費資料源是未來 provider expansion，不是 V0 前置條件，也不會在沒有明確批准下採購或串接。
- Radar 是最後一個 promotion gate；若 walk-forward 沒有穩定增益，允許結論為 no-go。
- Shadow feature 與 raw collector 使用不同 tracked job；provider transaction 不同步執行 heavy research compute。
- Large observation read 與 derived feature write 必須分相；SQLite writer transaction 在 read cursor 完全關閉後才取得，避免 WAL snapshot upgrade failure。
- V0 `observed_sequence_persistence` 明確等於 observed reappearance 中的 same-direction proportion，不描述持倉或未上榜期間的行為。
- Historical coverage 暫以目前 active ordinary-stock universe 作 proxy，並永久附帶 limitation；後續若要 production classify，需改成 effective-dated universe evidence。
- 不因 query plan 出現 temporary sort 就直接建 index；先以實際 bounded benchmark 決定。

## 已知問題與風險

- Worktree 已有大量使用者／其他任務變更；新增 `0065`／`0066` 依賴既有未追蹤 `0064`，在整理 branch 或 migration 前必須保留這條 revision chain。
- Full backend validation 仍有兩個外部於本次 scope 的未綠項目：Market Data Foundation protected hash checkpoint 與 Windows pytest Temp ACL。它們已被 exact failing tests 隔離；本次 broker-branch 29-test validation 為 green，但不能據此宣稱整個 dirty worktree 全綠。
- 正式 `RestartServices` 會維持 backend/frontend proxy 一致，因此不是 backend-only process restart；本輪 frontend 亦短暫重啟並恢復 `3000` health。
- Final restart 剛好碰到既有 scheduler startup catch-up：Job `6608`–`6611` 被 runtime reconciliation 標成 interrupted，scheduler 隨後建立 replacement Job `6617`–`6620`；沒有手動 retry/cancel。這些 raw／EOD scheduler 工作和 shadow Job `6612` 分離，不能把整個 restart window 描述成全域零 external fetch。
- nStock latest-only 來源無法補回缺失歷史；新 code 可保存後續 empty／failure attempt，但不能重建過去沒有留下的原始回應。
- 目前來源條款、商用／衍生使用與再散布範圍尚未完成權利確認。
- 來源頁面顯示資料可能含鉅額交易，但 payload 語意與欄位範圍仍需用樣本及官方／provider 說明驗證。
- 目前只有 25 個高覆蓋 session，尚不足以評估 regime stability、60/120-session 分類或 Radar uplift。
- 目前 materialized evidence 只有單一 as-of batch；即使 aggregate profile 已存在，也沒有 persisted OOS split outcomes，不能把全樣本 rate 當 walk-forward validation。
- 百萬級 row event 統計不是百萬個獨立樣本；驗證必須以 date、symbol 或 regime block 做 bootstrap / walk-forward，避免偽精確。
- 官方資料成本與授權條件可能改變；採購前需重新查證。

## 下一步

- 日常維持既有 bounded latest-only collector；readiness report 不自動 refresh，也不應替代 raw coverage job。累積到 60 個 high-coverage sessions 後才進 calibration candidate review。
- 在 120-session candidate 前補上 effective-dated universe evidence、來源使用／衍生／再散布權利確認，以及多個 as-of 的 frozen OOS outcome persistence；達數量門檻不代表自動 promotion。
- 只有至少 2 個 purged/embargo walk-forward splits 具備事先凍結的 OOS 結果，且不同月份／regime／liquidity／concentration 分層穩定，才重新評估 `broker_branch.behavior` outward。Flow-risk、Radar 與 frontend 仍在其後。
