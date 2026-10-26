# TWSE／TPEx 官方廣度 Source 驗收紀錄

日期：2026-10-23。狀態：**TPEx 官方收盤廣度 Source 接入與離線驗收 PASS；Runtime／正式 EOD Live／Product UNVERIFIED**。

## 範圍與結果

- 在既有 `main` 工作樹續作；前輪 TWSE 分類保留與 `db.no_autoflush` 修正完整保留。本輪修改前定點檔案備份與 SHA-256 位於 ignored `.tmp/tpex-official-breadth-20261023/baseline/`。
- 保留 TWSE `parse_twse_published_breadth` 與 RWD acquisition；在同一 parser module 最小延伸 `PublishedStockBreadth.venue`（舊 payload 預設 TWSE），加入純 TPEx parser，無 migration 或 public observation schema 變更。
- 既有 `TPEX_OFFICIAL_BREADTH_DESCRIPTOR` 指向已存在的 highlight endpoint。`refresh_taiwan_official_daily_venue` 經既有 planner 選出伴隨 route；同一 `TaiwanOfficialDailyAcquisitionExecutor` 取得日線與 highlight，各自保留真實 source／receipt。TPEx EOD 最多兩個 resource calls，各一次，不增加個股 daily refresh 的外部呼叫。
- `TaiwanOfficialDailyTransaction` 在同一次 transaction 儲存兩筆 raw receipts、日線及 `TaiwanPublishedBreadthSnapshot`；快照綁定 highlight 自己的 raw receipt。daily command 的 `raw_result_id` 仍指向日線 receipt，`raw_result_ids` 列出完整批次。
- Executor、transaction 與 reader 分別守住既有 daily release gate（Asia/Taipei 15:15）。這是沿用 OMI release policy，並非由此次 payload 推導官方實際發布時刻。Parser 強制核對兩個日期、表名、scope 註記、必要且不重複的欄位、唯一資料列、非負整數、總數及漲跌停子集合。
- `TaiwanOfficialBreadthRepository` 將 TPEx published snapshot 送入既有 Gateway／Resolver／platform；TWSE／TPEx 各保留 source、日期及 distinct scope。讀取不 fetch、不 autoflush、不讀 raw_text、不重算 provider schema。
- 沒有新增 provider、Service、Manager、Cache、HTTP route、dataset 或 capability；MIS current source 沒有修改。官方 daily 不進 `tw.market_breadth.current`，不補今日價格或冒充 live。
- 未操作正式 DB、服務、交易、訂閱、ACL、branch、commit 或 push；不存取前輪被拒的歷史目錄。

## 本輪唯一一次診斷 GET 與可重播證據

- URL：`https://www.tpex.org.tw/www/zh-tw/afterTrading/highlight?date=2026%2F10%2F22&response=json`
- 單次 `requests.get`，connect/read timeout 為 5/15 秒，`allow_redirects=False`；沒有重試。
- HTTP 200，Content-Type 為 `application/json;charset=UTF-8`，response body 672 bytes。
- 診斷取得時間：`2026-10-23T10:37:58.703533+00:00`。
- 解碼前完整保存 `.tmp/tpex-official-breadth-20261023/raw-response.bin` 與 `receipt.json`；另保存 `decoded.json`。原始 SHA-256：`dd227ea80648d107e6e69b03eb0cb4c5dc3b09a09d2300615a6dd621b53819c7`。
- 第一個 strict `utf-8-sig` decode 及 `json.loads` 即成功，不曾使用 replacement，也不需要 Big5／CP950 fallback；輸出使用 Unicode escapes 避免 console 再次造成中文顯示歧義。相同 hash 的 bytes 可 strict UTF-8 解碼，因此前輪輸出異常不能證明原 payload 非 UTF-8。
- 完整 byte-exact 公開 fixture：`backend/tests/fixtures/tw_market_data/tpex_market_highlight_20261022.json`，hash 與 raw bytes 相同；不是手造 API response。測試搭配的 10/22 個股日線則是明確標註的 synthetic dated input，不聲稱為當日實際價格。
- 頂層日期 `20261022`、table 日期 `115/10/22`；表名「上櫃股票當日彙總資訊」。
- 官方 scope 註記：「標的物:等價與鉅額成交之股票、換股權利證書，不含可轉債、認購售權證、認股權憑證及不動產受益憑證」。因此 canonical scope 為 `tpex_published_stock_and_share_conversion_rights`，不冒充 active ordinary stocks 或 TWSE scope。

| 官方欄位 | 實際值 | 語意 |
| --- | ---: | --- |
| 上櫃家數 | 894 | published universe |
| 上漲家數 | 146 | advance |
| 漲停家數 | 17 | advance 的子集合 |
| 下跌家數 | 659 | decline |
| 跌停家數 | 11 | decline 的子集合 |
| 平盤家數 | 63 | unchanged |
| 未成交(含暫停交易)家數 | 26 | 未成交／暫停交易混合，不能拆成個別 trading status |

`146 + 659 + 63 + 26 = 894`。26 家留在 canonical unknown 分區，outward `classification_reason_counts.unknown=26` 並帶 `PUBLISHED_NO_TRADE_INCLUDES_SUSPENDED`。`valid_no_trade_count=0` 表示沒有可單獨確認的一般未成交分類，不表示官方未成交混合桶為零。資料保持 partial、decision_usable=false；未推導個股名單或合併不同 universe。

## 離線驗證

前輪先以 `4 failed, 1 passed` 重現 TWSE 分類遺失及 autoflush，再修正至 31 passed。本輪完成 TPEx 接入後，執行以下定點測試，並封鎖測試程序的真實 HTTP：

```powershell
$env:PYTHONPATH = 'backend'
@'
import pytest
from unittest.mock import patch
with patch('requests.sessions.Session.request', side_effect=AssertionError('offline tests cannot use HTTP')):
    raise SystemExit(pytest.main(['backend/tests/test_tpex_published_breadth.py','backend/tests/test_tw_published_breadth.py','backend/tests/test_tw_official_daily_platform.py','backend/tests/test_tw_official_breadth_platform.py','backend/tests/test_tw_breadth_convergence.py','backend/tests/test_tw_data_core_boundaries.py::test_official_breadth_read_path_has_no_provider_io_or_transaction_ownership','-q','-p','no:cacheprovider']))
'@ | .\.venv\Scripts\python.exe -
.\.venv\Scripts\python.exe scripts/check-architecture.py
```

- 定點測試：**73 passed**，exit 0；使用 SQLite in-memory fixture 與注入 response，沒有正式 DB 寫入或測試期 provider GET。
- Architecture guard：**PASS**，exit 0；當次 actual violations 與 declared debt 均為 15，無 undeclared／stale debt。未修改 constraint 或 debt manifest。
- 覆蓋：真實 TPEx payload／欄位重排、old date／table date／缺欄／錯 scope／重複欄／不合理 partition 拒絕、executor 零呼叫 pre-release 拒絕、transaction 獨立 release 拒絕、reader 時間／venue／日期 gate、HTTP 或 parser 失敗保留有效日線並降級廣度、讀取零 IO／零寫入、source/hash/receipt lineage、已 flush 的 TPEx snapshot 與日線／raw receipts 同 transaction rollback、daily 主 receipt 相容性、TWSE 舊 payload 及 MIS regression。
- 日線取得失敗時，獨立合格的 highlight 可在同一 transaction 保存；daily postcondition 仍回報 error，不因有廣度就宣稱日線成功。
- 指定變更 Python 檔做 UTF-8 讀回與 syntax compile；指定變更檔做 `git diff --check`。前輪 `official_breadth_platform.py` 與 `test_tw_published_breadth.py` 本輪維持 byte-exact。

## 驗收邊界與未驗證

- Source：**PASS**，已接入既有 canonical acquisition／transaction／repository／Gateway。
- Live payload 證據：本輪單次官方 GET 的 10/22 schema、日期、scope、partition 已確認；只代表此筆 payload，不等同正式 EOD pipeline live 驗收或所有歷史日期覆蓋。
- Runtime loaded source、正式 DB adoption、正式 EOD live acquisition、UI／MCP Product acceptance：**UNVERIFIED**；未啟停服務或更新正式 DB。
- 官方混合桶無法拆出一般未成交與暫停交易各自數量；scope 不同，不和 MIS／TWSE 分母合併。未使用 aggregate 補今日 z 或昨收。
- 依使用者提供的 10/23 休市背景，本次沒有盤中驗收。後續需另行授權 runtime adoption 與正式 EOD 驗收；本輪不再 GET。


---

## 2026-10-23 獨立 Reviewer 靜態架構審查｜10/27 開盤前 Gate

> 此節為上述 Codex Source 實作完成後的 **獨立靜態審查**。原始「73 passed／Architecture guard PASS」是前一輪有效且未受此次審查變更影響的離線證據，**本節未重新執行測試、未聲稱 Runtime 已載入**。

### Current State / 查核範圍

- Repo：`C:\project\Open Market Intelligence`，Git branch `main`；審查開始約 127 筆 dirty WIP（含既有未提交來源、測試、文件）。不以 Source Green 取代 Git Commit、Loaded Release 或正式 EOD 驗收。
- 查核資料流：`backend/app/market/providers/tw_official_daily.py` 的正式 descriptor → `daily_ohlcv_platform.py::refresh_taiwan_official_daily_venue` → `market_data.provider_catalog.plan_refresh_acquisition_v1` → `daily_ohlcv_acquisition.py::TaiwanOfficialDailyAcquisitionExecutor` → `daily_price_transaction.py::TaiwanOfficialDailyTransaction` → `TaiwanPublishedBreadthSnapshot / RawFetchResult` → `official_breadth_repository.py` → `official_breadth_platform.py` → `MarketDataGateway.resolve_market_breadth`。
- 並追到正式 Job 呼叫：`backend/app/jobs/eod_coverage.py::run_eod_coverage_reconcile_job` 注入 venue refresher → `backend/app/market_data/eod_coverage.py::reconcile_eod_coverage / _repair_tw_eod`。另對照 `indices.py::_shared_current_market_summary` 與 `tw_current_market_platform.read_taiwan_breadth_lanes`，確認官方 completed-session 屬 shadow/獨立 scope，現役 MIS current 仍是獨立來源。
- 沒有發現這次整合新增第二套 Provider Manager、Cache、Gateway、HTTP 路由、Dataset、公開 Capability 或 Git branch。現有 `indices.py::_fetch_market_quote_breadth` 為舊相容輔助程式，靜態查詢正式 Source 未發現生產呼叫點；其存在屬潛在 Legacy Debt，不直接判成新 Production 缺陷。
- TWSE 的 Published 類別和 TPEx `tpex_published_stock_and_share_conversion_rights` 獨立，後者「未成交（含暫停交易）」維持 unknown、非持平；parser 校驗雙日期、欄位、scope、總家數及漲跌停子集。Receipt hash/lineage、release gate、同 transaction、read `db.no_autoflush` 及 Gateway 的離線證據可繼承。

### Findings

**AUD-TW-BREADTH-01｜P2 Confirmed Defect（靜態控制流程確定，正式 Runtime 是否觸發尚未驗證）**

- 根因：`backend/app/market_data/eod_coverage.py::reconcile_eod_coverage` 約 1310 行在 `computation.status == "healthy"` 時直接標示 `postcondition_met=True` 並返回；`_repair_tw_eod` 約 882–901 行僅以 `unresolved_symbols` 決定待刷新的 Venue。而 `backend/app/market/daily_ohlcv_platform.py` 約 767–783 行的 TPEx Highlight 取得僅附掛在 `refresh_taiwan_official_daily_venue` 被呼叫時。
- 影響：**日線全數合格、但官方 Published Breadth 快照缺失時，現有 EOD Job 可直接判完成而完全不取得／重試 Highlight**。即使日線刷新時曾因 Highlight 尚未發布或來源失敗而缺它，一旦 Daily 覆蓋成為 healthy，後續自動補齊仍可能被跳過。這是功能完成條件與來源生命週期沒有對齊，不代表 10/22 或 10/27 正式庫已真的發生缺資料。
- 最小修復方向：由**既有 EOD Owner** 把「官方 Published Breadth 是否有合格同日 Receipt」列為獨立的資料補齊判準，並在日線已健康時也能有界嘗試缺少的官方廣度來源。**維持日線 coverage 與廣度 coverage 正交**；不可為了補廣度重掃 2,000 檔日線、不得讓 read GET 觸發外部 Fetch、不要另加 Service／Cache／平行 Manager。若需新增寫入路徑，仍應使用原有 Raw Receipt/Transaction Owner。
- 針對性 regression：`daily_healthy + published_missing`、`daily_healthy + previously_failed_highlight`、`daily_partial + valid_highlight`；檢查不必要的日線取得次數、bounded retry/backoff、單筆 Published Receipt 的 canonical reread、既有日線 EOD postcondition 不誤判。

**AUD-TW-BREADTH-02｜P2 Architecture Risk（尚未證明 Runtime Timeout）**

- `daily_ohlcv_platform.py` 的日線 `RefreshRequirementV1.timeout_seconds=30`；其 `model_copy(update=...)` 形成的 TPEx 官方廣度 requirement 同樣是 30 秒；Planner 分別產生各自 timeout 30 秒的 route。`daily_ohlcv_acquisition.py::acquire_dataset_routes` 依序執行日線與 companion，各自有 socket/request timeout，但未看到**共同 wall-clock deadline** 或二者相加後的總預算驗證。
- 影響：在慢速／卡住來源上，單次 TPEx Venue EOD 可能花費接近兩個個別 timeout 加上序列化與 DB 寫入時間；不能把成功的 73 項離線測試視為實際 30 秒 SLA 已成立。
- 建議沿用既有 Planner/Executor 的 bounded work 概念，核對 EOD 實際工作上限及 job runtime，必要時用剩餘時間縮短 companion timeout，失敗時保留成功的日線及明確的廣度 `partial / source unavailable`，不新增隱性無界 retry。

**AUD-TW-BREADTH-03｜P3 Provider Contract Fragility（Observation／維護性）**

- `backend/app/parsers/twse_published_breadth.py::parse_tpex_published_breadth` 現要求表名和完整 `notes` 列表（包含前置 `\r\n`）字節層級一致。這能防止誤吃其他 scope，但交易所若只更動空白／換行也會進入 parse failure。
- 建議維持 fail-closed；先保留這版有原始官方 payload hash 的 fixture，再按真實樣本決定是否做**等價空白正規化**，不可直接取消 scope 校驗。此問題目前不是已確認資料錯誤。

### Passed / Unverified

- **Source 設計 PASS（有條件）**：舊 TWSE Daily Published 路徑保留；TPEx 由相同 canonical EOD acquisition、Raw Receipt、Transaction、Repository、Gateway 實作；不同 Universe 不合併；讀取是 cache-only 而且避免 SQLAlchemy autoflush；MIS `tw.market_breadth.current` 與官方 `tw.market_breadth.daily` 互不冒充。
- **繼承既有測試**：73 passed、Architecture guard PASS；此次只有 Reviewer 讀檔和文件追加，未新增 Source 變更、未重跑原 Gate。
- **未驗證**：新 TPEx 程式目前正式 Runtime 是否載入、真實 EOD Job 觸發／DB materialization、正式 `omi.ask` / API / Dashboard 對外資料；10/27 盤中 MIS `z` 缺值、即時 Qualified Quote、20 秒掃描與 Source Health 仍需分開檢查，不因官方收盤快照接入就當作修復完成。
- **相鄰 WIP**：工作樹還有 `tw_market_breadth_contract.py`、`tw_intraday_state.py`、`tw_market_dashboard.py` 等前期非本次整合的變更，與 10/27 盤中行為有關。本節僅作靜態影響檢查，未聲稱已替這些 WIP 取得完整盤中回歸或 Loaded Release 證據。
- 未進行真實 Provider refresh／Runtime restart／正式 DB 寫入／ACL 更動／交易／Git stage、commit 或 push。

### 10/27 前的 Gate / 驗收建議

1. **先修 AUD-01**：復用既有 EOD Job／Transaction，確保日線 healthy 不會掩蓋缺失的官方廣度，測試需含不重刷全個股、對應 trade_date/source/raw receipt、有限度重試／回退。
2. **確認 AUD-02 的總時間預算**：只需加最小測試，固定兩個外部來源均延遲或超時，確定不會形成無界占用；不必重跑全庫。
3. **僅重測受影響範圍**：`test_tpex_published_breadth.py`、`test_eod_coverage.py` 對應 Venue branch、既有 73 項中受共用改動影響者、Architecture guard；其餘仍有效的 Gate 繼承。
4. **Source Green 才另行安排 Runtime adoption**。10/27 盤前先核對交易 Calendar/Current MIS 的 session 與 as_of，不以 10/22 EOD 取代盤中行情；官方 Published 只有在 10/27 收盤後合法發布、正式 EOD 取得及對外讀回一致時才算 Live PASS。
5. **封版建議：再修一輪**。原因是 AUD-01 確認存在的修復入口缺口，並非表示盤中行情已被這次官方來源改壞。若選擇先維持現有正式 Runtime，不部署此未封版 Source，則新 TPEx Source 本身不會成為 10/27 開盤回歸的直接原因；仍需另驗證舊有 MIS 盤中問題。


---

## 2026-10-23 AUD 修正後 Current State／獨立離線驗收

本節更新上方 Reviewer 的三項發現，僅代表現有 `main` 工作目錄的 Source 驗收；沒有建立 branch、commit、push、重啟服務、執行真實 Provider/EOD 或操作正式 DB。原有 127 個 dirty 檔案先做 SHA-256 manifest，八個本輪目標檔另存 byte-exact baseline；不覆寫無關 WIP。

### 修正位置與行為

- **AUD-TW-BREADTH-01：Source PASS。** `backend/app/market_data/eod_coverage.py::CoverageComputation` 保留日線 `status`，另記 `published_breadth`；`should_enqueue_eod_reconcile()`、`reconcile_eod_coverage()` 與 `_repair_tw_eod()` 使用兩項 postcondition。daily healthy + published missing 會進入既有 Job，失敗仍保留 daily healthy 與整體 partial，不誤稱完成。正式 `jobs/eod_coverage.py` 原有 qualifier/refresher injection 不變。
- `daily_ohlcv_platform.py::qualify_taiwan_eod_universe(include_published=True)` 從 `read_taiwan_official_breadth(...allow_universe_fallback=False)` 經原 Repository／Gateway／Raw Receipt 資格判斷；不以 daily-derived registered universe 或 decision_usable 取代 published qualification。普通 daily-only compute 不啟用額外讀取，原 batch 查詢預算測試維持。現有 read no-autoflush、無 Provider IO／write 路徑不變。
- `daily_ohlcv_platform.py::refresh_taiwan_official_daily_venue()` 由 Job 傳入 `refresh_daily`／`refresh_published`。TPEx daily 已合格時只取 highlight，一次來源呼叫、零日線 upsert；published 已合格時日線修復跳過 highlight。TWSE 補缺沿原 planner 選出的 RWD `MI_INDEX_ALLBUT0999`，只解析 aggregate、不產生 bar；該官方 endpoint 仍會傳回整份 response，但不逐股重取或重寫已合格日線。
- `daily_price_transaction.py::persist_bar_acquisition()` 仍是唯一 transaction owner。TWSE 無 bars 時只有 explicit `tw.market_breadth.daily`、exact venue/date requirement 可用來落 snapshot；原 ordinary daily wrong-date 行為維持。TPEx highlight／TWSE aggregate 都保留原 receipt 與同 transaction 原子性。highlight 失敗不覆寫 daily primary receipt 或成功日線。
- **AUD-TW-BREADTH-02：Source PASS。** `daily_ohlcv_acquisition.py::acquire_dataset_routes()` 每 venue 共用最多 30 秒 soft admission budget，包含 platform universe／planning 已耗時間、daily fetch／parse 與 companion。每個 route 重新計剩餘整秒 timeout；不足一秒或 calls 用盡即 skip，保留 deadline/call-budget limitation 與 degraded health。四個現役官方 route 均禁 redirect，無新 thread、executor、timer 或隱藏 retry。
- `_repair_tw_eod()` 從 reconcile 起點計外層 runtime，按 registry Job call 上限保守預留、取得可信實際用量才退還；未知／例外不退還。每個 Job 最多兩次來源 dispatch，不再把兩個 venue 當成可各發兩次呼叫。剩餘未完成項目走原 checkpoint／backoff。沿用 `cursor_symbol` 輪替，避免 TWSE 連續失敗用盡 budget 而讓 TPEx 永遠沒有取得機會；即使 priority 持續指向 TWSE，下一輪仍可輪到 TPEx。
- **AUD-TW-BREADTH-03：Source PASS。** `parsers/twse_published_breadth.py::parse_tpex_published_breadth()` 僅 normalize title 與 scope note 的等價空白（空格、tab、CRLF、全形空白、NBSP）；實際文字、日期、欄位唯一性、scope、partition 仍 fail-closed。沒有 schema 或 migration 變更；「未成交(含暫停)」仍為 unknown，不轉為 unchanged。

### 本輪有效證據與重播

證據位於 `.tmp/tw-breadth-audit-fix-20261023/`，本機可核對，未加入 Git index：

- `dirty-baseline.json`、`baseline/`：開始時的 dirty SHA-256 與本輪目標檔原始 bytes。
- `task.diff`：相對本輪 baseline 的八檔差異，便於從大量既存 WIP 分離此次修正；`git-current.diff` 同時保存五個 source／兩個 tests／本文件可由 Git 顯示的現況 diff。
- `verify_offline.py`：可重播 core／regression／baseline 三組，封鎖 `requests.sessions.Session.request` 真實 HTTP；資料 fixture 使用 SQLite in-memory。
- `red-tests.log`：修正前 **4 failed**，直接重現 healthy/missing 零 highlight、22 秒後 companion 仍 30 秒，以及 30／40 秒後仍發 companion。
- `targeted-tests-final.log`：本輪最終 core **151 passed，exit 0**。包含 `test_eod_coverage.py`、`test_tpex_published_breadth.py`、TWSE published、official daily/breadth platform、canonical qualification、breadth convergence 與 data-core boundary。
- 定點涵蓋：healthy/missing 僅補 highlight；present 零額外 IO；daily partial + valid published 由 reconcile 自動跳過 highlight；同 Job HTTP/parser/source/receipt-date 失敗與 backoff；canonical reread；daily primary receipt 保留；transaction rollback；TWSE breadth-only；等價空白／非等價 scope 拒絕。
- fake monotonic 證據：daily 22 秒後 companion timeout 8 秒；29.5／30／40 秒後 companion skip；planning 8 秒剩 22 秒、30 秒後零 IO；外層 Job 10 秒，第一 venue 7 秒後下一 venue 剩 3 秒，第一 venue 10／15 秒則跳過下一 venue；同 Job 兩次 call 上限與跨輪 venue fairness。
- `architecture-final.log`：**PASS，exit 0**；actual violations 15、declared debt 15，無新 debt，未修改 constraints／debt manifest。
- `static-checks.json`：七個 Python source/test 的 UTF-8／syntax compile（不執行 runtime）、八檔 diff whitespace 檢查與無關 dirty 檔 byte/hash parity。`final-hashes.json` 固定本輪最後檔案 identity。

在 repo root 重播（不啟動正式 Job／服務）：

```powershell
.\.venv\Scripts\python.exe .tmp/tw-breadth-audit-fix-20261023/verify_offline.py core
.\.venv\Scripts\python.exe scripts/check-architecture.py
.\.venv\Scripts\python.exe .tmp/tw-breadth-audit-fix-20261023/verify_offline.py regression
.\.venv\Scripts\python.exe .tmp/tw-breadth-audit-fix-20261023/verify_offline.py baseline
```

### 擴大回歸：FAIL，三項既存失敗已隔離

`regression-tests.log` 是 **101 passed、3 failed、11 subtests passed，exit 1**，不是全綠。三項皆位於本輪未修改的 tests/source：

| 測試 | 本輪結果與 baseline 對照 |
| --- | --- |
| `test_tw_intraday_market_capabilities.py::TaiwanIntradayMarketCapabilityTests::test_tpex_registered_universe_breadth_is_cached_with_estimate_semantics` | 預期固定 timeout `10`，實際 remaining 約 `9.9999`；兩邊同一斷言失敗。 |
| `test_tw_intraday_market_capabilities.py::TaiwanIntradayMarketCapabilityTests::test_volume_state_keeps_trade_value_usable_when_breadth_is_missing` | 預期 `1300`，實際 `None`；兩邊相同。 |
| `test_trading_calendar.py::TaiwanTradingCalendarTests::test_october_typhoon_closure_and_presentation_rollover` | 10/26 holiday 名稱字串不符；兩邊相同。 |

`preexisting-failures-baseline.log` 用本輪五個 source 的 baseline import overlay 重播三測試，得到 **3 failed，exit 1**；實際被載入的四個模組確認來自 baseline，這三測試未載入 shared EOD 模組。此隔離不需還原／覆寫 worktree，證明三項失敗非本輪修正引入；不表示失敗無害或已修復。本輪不跨任務改動 MIS／volume／calendar WIP，也不宣稱它們已全數驗收。

### 獨立 Reviewer 與最終 gate

- 獨立 `omi-data-freshness-reviewer` 對照本輪 diff/source，曾重現上述 TWSE→TWSE starvation P2；回到同一 EOD owner 修正後，Reviewer 同一 probe 觀察 **TWSE→TPEx、每 Job budget 2**，阻擋解除。
- Reviewer 自行封鎖 HTTP、使用 in-memory fixture，兩批定點各 **11 passed**（7.27 秒、6.76 秒，exit 0）；覆蓋 repair/backoff、call/runtime budget、planning、transport 與 fairness。Reviewer 另唯讀核對擴大回歸與 baseline 同樣失敗證據，接受下列分開結論。
- **本次修正範圍 Source／離線：PASS。擴大回歸：FAIL（三項既存失敗已隔離，未修復）。Runtime loaded source、正式 DB adoption、正式 EOD Live、API／omi.ask／UI Product：UNVERIFIED。**
- deadline 是 soft admission：會阻止後續 route／venue 並縮短傳入 socket timeout，但不能硬中斷已進入的 OS／DNS／socket blocking request；transaction commit／最終回讀也非硬 deadline 內完成保證。來源 call 額度與無額外 background work 已由 source 和 fake-clock regression 驗證。
- 本輪沒有真實市場、交易、訂閱、正式 DB、runtime adoption 或 10/27 開盤驗證；未使用 completed official breadth 補 MIS `z` 或冒充盤中資料。


### 2026-10-23 獨立 ChatGPT Reviewer 收斂複核（Codex 完成後）

在 Codex 回報 terminal completed 後，另外透過 Project Workspace 唯讀核對目前工作樹：Git branch 仍為 `main`，原任務修改範圍仍為 EOD／Daily 的 5 個 Source、2 個測試及此紀錄；原其餘 WIP 不予修改。針對下列正式程式路徑獨立確認：

- `should_enqueue_eod_reconcile` 與 `reconcile_eod_coverage` 以 `include_published=True` 判定 completed official breadth；其他普通 Daily Coverage 讀取預設不增加官方廣度查詢。Published 檢查仍走 `read_taiwan_official_breadth(..., allow_universe_fallback=False)`／原 Gateway，沒有新 API 旁路。
- `_repair_tw_eod` 僅選 daily 未完成及／或 Published 缺失的交易所，按 Job `max_calls` 扣除實際使用次數，未知例外保守扣除；既有 `cursor_symbol` 輪替避免 TWSE 長期阻擋 TPEx；Retry checkpoint/backoff 持續保留。
- `refresh_taiwan_official_daily_venue` 可設定 `refresh_daily`／`refresh_published`，僅缺廣度時不重寫日線；`acquire_dataset_routes` 有共用 soft deadline 與剩餘整秒 timeout 限額；TWSE 與 TPEx 仍由 `TaiwanOfficialDailyTransaction` 儲存同一正式 Raw Receipt/Snapshot，Source 側保留事件日期與 distinct scope。
- 前輪四項負向測試由 Red 到 Green、最終 151 passed、Architecture checker PASS、以及 Reviewer 兩批 11 passed 的執行證據都已紀錄；擴大回歸 3 項既有失敗與 baseline overlay 一致，**不得寫成全測試通過**。

**剩餘 P3 Observation（不阻擋本輪 Source 封版）**：`backend/app/jobs/eod_coverage.py::run_eod_coverage_reconcile_job` 在 published 缺失而 Daily 已 Healthy 時，JobExecutionError 摘要目前只列 `current/partial/stale/missing` 日線計數，未直接列 `missing_published_venues`；但完整 Job `result` 已有 published 診斷。正式運維可改善摘要可讀性，並非資料流錯誤；不為此修改既有 Job API 或新增檢查。

**封版意見：可以封存本次 Source 修正，但保留已知 P3 診斷文字 Debt；不代表 OMI Runtime／正式 EOD Live／10/27 MIS 盤中 Product PASS。** 未另行執行測試、重啟、正式 DB 變更或 Git 提交。