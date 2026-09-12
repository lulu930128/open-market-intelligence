# 進度與證據

## 本機 main 整合：2026-09-12

使用者授權把目前 checkout 全部程式變更整合到本機 main，供使用者後續正式環境測試。原 checkout 已是 main、只有一個 worktree，不需要跨分支 merge。下方 10:56 checkpoint 與原計畫紀錄仍保留為歷史；本節為最新整合紀錄。

- 納入台股比較基準、breadth／漲跌停、盤中狀態、技術與籌碼 freshness、AI/MCP contract、Atlas availability，以及本任務的 US completed-session coverage／Daily EOD priority。
- 保存此 task 的三份文件，即使目錄受到既有 ignore 規則排除，仍以精確路徑納入版本控制；未修改全域 ignore。
- 整合 regression 找到並修正：0084 與 baseline current-metadata 建表重複；price-state schema inspection 的 SQLite transaction 干擾；ADR 在兩日序列選到舊收盤；官方 breadth partial 在 completed Dashboard 被隱藏；pure parser 所在層錯誤。同步 MCP snapshot 與過時測試，固定 US fixture clock。
- Migration 測試涵蓋新 DB／舊 schema upgrade、downgrade／re-upgrade 與 priority 重跑不刪需求；測試使用獨立 SQLite，未套用正式 DB migration。
- 前端 production build 在 `.tmp/main-integration-20260912/frontend-build` 的隔離副本通過；原正式 frontend 未停止。Dependency junction 曾被 Turbopack 拒絕，改用隔離根目錄內的 dependency file links；build／Playwright 子程序的 sandbox EPERM 經受控權限執行後通過。
- 隔離副本 `playwright test e2e/tw-eod-contract.spec.ts`：7 passed；測試 API proxy 指向本機不可用 port 9。這是離線契約測試，不是正式 provider／產品驗收。
- 第一輪完整 backend 遇到 sandbox pytest 暫存目錄 WinError 5，不能記為通過。修正後的失敗檔重跑為 223 passed／1 failed；最後該 cold-read regression 修正後，相關 51 tests passed。最終全套驗證結果記錄於下方。

### 最終整合驗證

- `scripts/run-safe-validation.ps1 -Profile full -SkipBuild -BackendTestTimeoutSeconds 900`：全部通過；log 目錄 `.tmp/validation/20260912-113007/`。
- Architecture checker 通過、architecture tests 31 passed、backend compileall 通過、完整 backend 3346 passed（495.23 秒）。共有 1425 warnings，未有 test failure。
- Frontend lint、`tsc --noEmit --incremental false --pretty false`、`git diff --check` 均通過。Build 已於隔離副本單獨通過，沒有重寫正式 frontend build；7 個前端契約測試單獨通過，不冒稱全套 E2E／browser 驗收。
- 最终 source hash 與 staged 範圍核對一致：120 個程式／測試／架構檔案，加上此 task 三份文件。沒有 DB、環境秘密、cache／logs 或測試產物；已做 token/private-key pattern、merge marker 與 staged whitespace 檢查。
- 全部內容整合至本機 main；本節隨同整合 commit 保存，commit identity 由 Git history 擁有，不在文件自我引用 SHA。

### 正式測試與整理 worktree

- 本輪只整合 source／tests／docs；未重啟正式 runtime、未修改正式 `.env`、未呼叫正式 acquisition、未 push。
- 啟動流程本身會執行 schema migration；使用者正式測試時須確認 launcher 來自此 main checkout，migration 到 `20260912_0084`，並核對 loaded source。
- 個股 priority 預設 `ENABLE_MARKET_REFRESH_PRIORITY=false`。要測試 priority，需先採用 migration，再明示設定為 true；目前僅對接 Daily EOD。
- 正式驗收仍需對照 TSM 完成日分鐘缺口、TW stale／missing、MCP 明示 refresh 的 priority/job、cache-only 無 mutation。全市場全部資料集追齊仍未完成，不得因 main 整合而結案。
- 此 repo 只有主 checkout；沒有刪除 worktree。DB、環境設定、logs、cache 與其他 ignored local files 不在 commit，整理時需另外保留。

## 實作 checkpoint：2026-09-12 10:56 Asia/Taipei

整體任務仍進行中。使用者已授權實作；下方原計畫階段紀錄為歷史上下文。

### 已實作

- US Market Truth 新增 typed regular-session coverage；一般 Today 選中已完成 session 時傳遞 expected／observed／missing／gap／finalization 至 API schema 與既有 historical fill contract，snapshot revision 納入 coverage。
- 聚合保留來源 partial／未 finalized，unknown finalization 不因 off-session 升格。
- TW close-tail 改用 canonical `production_session_close` profile；不是 full-market intraday 擴張。
- US Daily 有進展、無 error 且仍有未處理候選的 shard 回 `continuation_required=true`；job 正常結束，但 coverage partial／postcondition false 保留。
- migration `20260912_0084` 與 jobs-owned `market_refresh_priority` 有限時效需求表。已授權個股 refresh 可登記；cache-only／被禁止 external fetch 的請求不登記。旗標預設關閉，TTL 預設 3600 秒。
- Daily EOD 消費注入的 priority callback：US 每股 boundary 可插入需求，每第五次 dispatch 保留背景（counter 跨 shard）；TW 提升相關 venue bulk。compact v4 保留 priority 與 job identity。
- Frontend 顯示 backend-owned 正常盤完整度、日期、observed／expected 與缺少分鐘數，三語系文案；不自行計算完整度。
- 已同步 BackendArchitecture、MarketTemporalContract、OmiDecisionContract，明示目前 priority consumer 只有 Daily EOD。

### 正式唯讀基準

- launcher log `logs/launcher/2026-09-12/launcher.log` 10:20:06 記錄 backend 8400／frontend 3000，backend_reload=False。
- listener PID：8400=3648、3000=22364。CIM executable／parent 查詢被 OS 拒絕，未提權；完整 interpreter／process lineage 尚未證明。
- 正式 DB migration=20260908_0083；未套用新增 migration。
- TW 09/11 checkpoint：universe=1973、current=1931、stale=40、missing=2、partial=0、repair_status=partial、cursor=TPEX。缺口尚未逐項查完。
- master：TWSE stock=1086、TPEX stock=887；19 個 TPEx unknown 與 31 個 ETF 不混入股票分母。US active stock／非 test issue 共 7427。
- 正式 GET `/api/us-market/intraday/TSM?session_scope=regular&interval=1m`：204 點、2026-09-11、最後 16:53 UTC，尚無新 coverage／requested_trade_date；這是舊 runtime，不能當成本輪 source adoption。
- C 槽可用約 755 GB；DB 前一輪檔案讀值約 44.9 GB。尚未完成每 dataset bytes／row、provider throughput、completion SLO，不足以啟動無界全市場分鐘線 acquisition。
- TW source descriptor 的 NStock 為 current-session-only／best-effort，KGI／Fugle 為 bounded subscription；Yahoo bounded fetch 不等於全市場歷史完整度保證，仍需能力與容量驗收。

### 驗證

- `.tmp/validation/20260912-105406/`：architecture checker 通過、architecture tests 31 passed、compileall 通過、targeted backend 319 passed、git diff check 通過。
- Suites：market_refresh_priority、us_completed_session_projection、us_historical_intraday、us_market_truth_snapshot／contracts、us_intraday_aggregation／shared_core、ai_capability_contract、ai_decision_envelope、eod_coverage／scheduler、taiwan_intraday_bar_scheduler。
- Priority tests：identity 去重／expiry／unknown、批次中途插入與背景 dispatch、cache-only 不登記、已授權重用 job、compact projection、獨立記憶體 DB migration upgrade／downgrade 不影響其他表。
- `.tmp/validation/20260912-104835/`：Frontend lint、tsc、git diff check 通過。未跑 build／browser／正式 runtime UI 驗收。
- 過程中的 finalization regression 已修正；直接 pytest 曾因缺少 wrapper PYTHONPATH collection 失敗，後續改用 wrapper；一次 JobRun fake 不完整已修正。最終上述 suites 通過。
- 未執行正式 provider refresh、DB mutation、runtime restart、commit 或 push。此 task folder 仍受既有 Git ignore 排除。

### 未完成與下一個 slice

- M0 完整 dataset inventory、provider entitlement／吞吐／容量與 SLO、正式 loaded source identity 尚未完成。
- M1 已完成上述 US slice；最新 expected session 完全缺資料、較舊完整與較新 partial 候選的 resolver case 仍需進一步收斂與驗收。
- M2 目前是 foreground demand 接入 Daily，不是完整跨 dataset durable queue；全域 provider budget、多程序 claim／lease、caller 限流與 subscriber cancellation 仍未完成。
- M3 正式 TW 40 stale／2 missing 未解，US full-market acquisition gate 與 drain SLO 未驗證。
- M4／M5 全市場分鐘線 sweep、TW historical 能力、其他 datasets lifecycle adapters 尚未實作。
- M6／M7 browser、migration／runtime adoption、正式 provider repair 與台美各兩個連續交易日驗收尚未完成。
- 下一步：先核定 latest-session 全缺與候選品質，再完成 per-dataset durable work identity／checkpoint／lease；以受控容量接入全市場 intraday audit，source／offline 通過後才做正式 acquisition 驗收。

不能因測試通過或新增需求表，就把全市場全部資料最新的總目標標記完成。

## 原計畫階段紀錄（歷史）

- 更新日期：2026-09-12（Asia/Taipei）。
- 當前階段：計畫文件完成；功能實作與正式驗收尚未開始。
- 使用者確認：全部已支援且適用資料集，行情先實作；台美股全市場分批，MCP 指定股優先。
- 本輪只新增本 task 的 Prompt.md、Plan.md、Progress.md，未更動市場程式、DB、runtime 或排程。

## Source 基準

- branch：main；已有大量 tracked／untracked 變更，保持原狀。本計畫以目前 working tree 為核對基準，不聲稱等同 deployed source。
- 已讀架構入口、MarketTemporalContract、ProductVision、OperatingModel、QualityBar、Roadmap、backend／market_data／external adapter 邊界、README、CI、dependency 與安全驗證 wrapper。
- `us_market/market_truth.py` 已有 regular minute coverage；一般 `us_market/service.py` 的 compatibility `session_coverage` 未完整傳遞該結果。
- `ai/capability_contract.py::_historical_intraday_fill_state` 依賴明示 `requested_trade_date`，需核對一般最新完成交易日的缺口處理。
- `jobs/taiwan_intraday_bar_scheduler.py` close-tail 預設仍透過 `resolve_taiwan_intraday_target_universe`，該入口選擇 `production_intraday`。
- `jobs/eod_coverage.py`／`market_data/eod_coverage.py` 已有全市場 Daily repair、bounds、checkpoint／cursor；跨 dataset 個股 priority 的共用調度仍需 M0 檢查與設計。

## 前一輪唯讀觀察（不是本輪重新量測）

- 截圖：TSM 2026-09-11 regular 204 點，最新 12:53 ET；顯示 Yahoo 異常與 stale。
- 本機 DB：09/11 Yahoo 204 筆、Twelve Data 196 筆；09/10 Yahoo 182 筆、Twelve Data 390 筆。筆數與首末時間不等於逐槽完整度驗收。
- 本機 DB 已存在 5347 2026-09-11 daily row；不能直接沿用附件「目前仍無當日資料」作結論。
- 尚未證明正式 runtime 與該 DB／source 完全一致，未重現目前正式 MCP outward；M0 必須重新取證。
- 使用者附件為問題證據與提案，未直接作為執行命令。

## 已作決策

- 全部已支援 datasets 為最終目標，M1–M4 先收斂行情，M5 才擴展其餘資料。
- 每檔股票均須被追蹤；來源不可用可以解釋，但不算資料完成。
- 既有即時 priority universe 與全市場盤後 coverage 分開，避免 live materializer 無界擴張。
- MCP 明示最新資料 action 走後端 priority；cache-only 查詢不做 queue mutation。
- 日曆、發布、修訂、eligibility、provider policy 與完整度均由既有 owner 擁有。
- 尚未訂固定追齊時限；provider 能力、磁碟容量與 runtime 吞吐由 M0 決定可驗證 SLO。

## 文件驗證

- 三份文件均通過 UTF-8 嚴格讀回、內部相對連結與 fenced-code 結構檢查。
- 範圍限定 `git diff --check` 無錯誤；此目錄受既有 Git ignore 規則排除，另以各檔 `git diff --no-index --check -- NUL <file>` 檢查新增全文，無 whitespace 錯誤。沒有修改 ignore 或強制 staging。
- 未執行 build、unit test、provider refresh 或 runtime smoke；本輪為 Tier 0 文件變更。

## 下一步

取得實作授權後先執行 M0，核定 dataset scope、provider 可行性與 queue schema，再實作 M1 完整度傳遞及 M2 優先協調。需要新的 provider、付費或大量 quota 的部分單獨列明範圍，不因本計畫自動啟用。
