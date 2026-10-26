# OMI 全域工程問題整合｜2026-10-23

> Checkpoint：2026-10-23 約 16:35–16:50 Asia/Taipei。目標是依現役 Runtime、正式 OMI MCP／API、當前原始碼、Git 與既有驗收收據，將真正仍開放的問題去重，與歷史已修復／架構風險／資料來源限制／缺乏證據項分開。**本次只查資料與整合文件，不修改 Source、Runtime、正式DB、Fugle／KGI 租約，也不啟動 Build／測試／重啟／Commit／Push。** 本報告不是聲稱所有未覆蓋模組都已進行端對端測試。

## A. 正式狀態、Source identity 與證據界線

| 觀測 | 2026-10-23 事實 | 解讀 |
| --- | --- | --- |
| Backend、Launcher | Backend PID **61364**（10/22 18:02:19 Asia/Taipei 啟動）、Launcher PID **53040**；Port8400 `python.exe`；`/api/system/readyz` **HTTP200**，runtime/database OK | Backend 提供服務，不等於所有市場資料已合格 |
| Frontend | 3000 `node.exe` PID **57500**；GET `/` HTTP200（約1.18s）、`/_next/static/chunks/app/layout.js` HTTP200（約16ms） | 當前 Chunk 載入成功；10/21 Webpack `ChunkLoadError` 沒有重新出現 |
| 載入版本 | `APPLICATION_SOURCE_SNAPSHOT` Release **`1d11ca7f5bbd3567f5d502cacf5ba37938f611640ad170fa45d562910eee64a1`**；`loaded_lifecycle_source_id=08653016751f771d70818e04d3f9ad280e2d79d9260ae034140c9e4bd66245bd` | 前次 R4-C/G1/G2 原 `pending` checkpoint已過時；新來源有換版，但各 Product Gate仍需獨立驗證 |
| Control source | `disk_matches_import=true` 僅涵蓋 `runtime_control_bundle_only`；`frontend.status=unknown/pid=null`、`mcp_dependency=unknown/EXTERNAL_ADAPTER_NOT_ATTESTED` | 不可由這組Bundle比對宣稱整個Application磁碟完全等於執行程序，也不能把Frontend未知當作Port故障 |
| Restart | `restart.available=true, blockers=[]`，policy `graceful_then_owned_cutoff_180s`；Writer Preflight 尚未要求、`unknown_writer_count=3` | `available` 不是Idle/已完成Writer Drain，本輪未觸發Restart |
| Git | `main`，**112** changed entries（包含歷史WIP/untracked，未驗證遠端Push） | Release/交付管理風險，不是112個Production defect |
| 本輪正式資料 | `omi.ask`／`omi.read_tw_market_dashboard` 全部 `cache_only/refresh=off/external_fetches=0` | 沒有本輪外部Provider request；`quote.snapshot`／`market.volume_state` 以各自原timestamp判斷 |

來源：正式 `omi.read_runtime_status`、`GET /api/system/runtime-control/status`、`GET /api/system/readyz`、Workspace port/http/git；歷史換版細節另見原[台股事故 §20–24](TW-20261020-postclose-breadth-3406-root-cause.md)及[原 Progress](../../exec-plans/active/tw-missing-values-source-contract-20261020/Progress.md)。

## B. 今日新確診 P1：台股臨時休市日未進入 Calendar Owner

**ID OMI-CAL-001｜Confirmed Defect｜P1｜目前重現。**

- 外部正式事件：2026-10-23（五）因薔琵颱風，證交所及櫃買市場全日休市；2026-10-26（一）光復節補假，下一預定交易日 10/27（二）。[CNA 10/22官方轉述](https://www.cna.com.tw/news/afe/202610220388.aspx)、[凱基公告](https://www.kgieworld.com.tw/index/news_mtrade.aspx?nsid=12907)、[證交所天然災害休市原則](https://www.twse.com.tw/zh/clearing/suspended.html)。
- 目前正式Dashboard錯誤顯示 `session.phase=post_close`, `presentation_state=completed`, `trade_date=2026-10-23`, `is_current_trading_day=true`、`next_transition_at=2026-10-27T08:00:00+08:00`。最後有效Breadth實際是**10/22**，`as_of`不是10/23；今日 `resolved_indices` 無當日值。`omi.ask` 2330 10/23 `quote.snapshot` 缺值並輸出 `TW_OFFICIAL_DAILY_RELEASED_BUT_UNAVAILABLE`。
- **根因 Source已定位**：`backend/app/market/trading_calendar.py` 的 `TAIWAN_EMERGENCY_MARKET_CLOSURES` 已有 **2026-07-10** 的 Typhoon緊急休市，但**沒有 2026-10-23**。`taiwan_market_holiday_name→is_taiwan_trading_day→taiwan_presentation_session/taiwan_market_session_phase` 由此誤判；`exchange_calendar_cache` 只保證已驗證年度休假，無法以年度公告沒有列出10/23來證實當日有交易。`calendar_status.py`／Market Dashboard／Daily EOD ExpectedDate 全部繼承同一正式 Calendar Source。
- **衍生假警報合併處理，不拆成新Bug**：`market_breadth`、`broker_branch_trade_daily`、`market_daily_price` 等把10/22視為落後10/23；10/23『官方已發布卻找不到日線』也屬錯誤 expected session。未取得確切JobRun時不能宣稱今日已真的寫入假K或發生資料破壞。
- **最小修復與防回歸**：沿現有Calendar Owner／Emergency overlay增加有來源、日期與停市類型的10/23記錄（短期 hotfix），再設計官方臨時公告維護／來源更新機制；必須測10/22交易→10/23緊急休市→10/24-25週末→10/26補假→10/27開市的 previous/next/date/session/release、TWSE+TPEX統一與US/JP/KR不受影響。**不建立10/23假OHLC／假Volume，不在GET觸發EOD補資料，不重建正式DB。**

## C. 台股仍開放的行情／分析問題（同一根因不重複計數）

| ID／級別 | 分類 | 確認證據（來源時間） | 根因／下一個有效驗收 |
| --- | --- | --- | --- |
| **TW-MIS-002 P1** | Provider Source Gap（現象確診、上游語意部分Unverified） | Oct22 Raw866252原始 `z='-'` 但可以有買賣盤及累計量；10/22收盤Breadth即使11/9批各自成功，仍有無合格actual價。 | 缺合法成交價不等於Parser必然錯；原 `z/v/tv/ts/pz` 與 nested `trade.z` 的正式權威來源及相同symbol的1/10/100控制試驗尚未做完。禁止以 `pz`／bid-ask／昨天close填 actual。 |
| **TW-BREADTH-003 P1** | Confirmed Product Coverage Gap | **10/22 13:33** 每Venue一輪 TWSE 1075/1080 received、**1017/1080 qualified**，TPEX878/887 received、**723/887 qualified**；均 `acquisition_complete=true`，但 qualification/unknown仍缺。 | full batch != full qualified directional；來源缺z、無成交、未覆蓋股票分開計。部分快照禁止宣稱官方全市場方向。此處結論限於10/22原始 session，10/23休市不應重跑。 |
| **TW-SLOT-004 P1** | Confirmed Quote Availability Gap | **10/22 13:15** 3406正式Quote Raw866626：`TWSE_MIS_PREVIOUS_TRANSPORT_IN_FLIGHT`、`external_calls=0`、保留舊事件12:55:57，未取得新合法價。 | 背景Venue Slot在途時 foreground不能及時獲得IO；原序列化與late-thread safe-stop正確，不可改用不受控parallel。原 `bounded_fetch` 的批次間有界前景公平性尚未實作；holder精確時間線缺。 |
| **TW-SCAN-005 P1** | Confirmed Capacity Limitation | Oct21/22多筆自然Raw顯示20秒每Venue scanner耗盡caller budget，剩餘批次skipped；10/22亦有單輪成功。 | 不能把client acquisition deadline當socket timeout，也不可跨輪union或直接加大量並行；改善IO公平性/Provider transport，維持相同Guard與Raw receipt。 |
| **TW-QUOTE-006 P1** | Confirmed Live Product Gate Failure | 10/21/22 多檔正式 `quote.snapshot` EventAge >15s、`price_decision_usable=false`；10/22 2330 Lease曾 KGI subscribing→Fugle connecting，但沒有Fugle股票aggregate ACK/真實LastTrade。 | R3/R4改正價／時間契約與可顯示歷史值，不等於取得新成交。下一正常交易日（預計10/27）正式單租約、保留原Owner選源、同一EventTime／SourceLineage驗收15s。 |
| **TW-KGI-007 P2** | Live Root Unverified／Source Fix Checked | 10/21 13:28 KGI `CANONICAL_SYNC_FAILED:RuntimeError`；R4-C修分步Diagnostic／Canonical資格／DB失敗止步，41+4+99 targeted及54arch有效；10/22正式Lease沒有重現generic error，不能據此確診原RuntimeError來自Depth。 | 僅在下一次自然Live錯誤依 `QUOTE/KBAR/DEPTH/AUCTION` codes定位，不再用exception class猜來源；KGI lease transport ready≠actual quote qualified。 |
| **TW-FUGLE-008 P2** | Partial Routing PASS／Stock ACK Unverified | **10/22 13:03**單Lease由KGI `subscribing`在正常grace後自動選到Fugle `connecting/FUGLE_QUOTE_SUBSCRIPTION_PENDING`；finally DELETE204、leases0；Fugle只證實 index IX0001 bound。 | Provider fallback路由**已實測成功一次**，不可再稱整體failover完全失效；但Fugle股票實際entitlement、ACK、Canonical materialization及15s仍不成立。 |
| **TW-1M-009 P2** | Partial Coverage／Product Limitation | Oct22顯式Demand（不是自動常駐）回讀：3406 237/242 `partial_prefix`，3264 239/239、3105 240/240 `complete_prefix`，均有合法NStock Materialization證據。 | Demand能產生K，不代表Tier-A universe每股自動持續填；3406缺12:12可能是真無成交或資料缺桶，根因未證。按ExistingAdmission/JobRun定點核對，不補假零成交K。 |
| **TW-VOLUME-010 P2** | Current Contract PASS／Historical Baseline Not Ready | 最新正式 `market.volume_state`（來源10/22 13:33）仍呈 estimated **976,788,198,323 TWD** 的 best-effort，`trade_value_qualification.decision_usable=false`，5d／20d各0合格樣本、`pace_ratio=null`，40 prior sessions缺同分鐘可比點。 | G0/G1及S1/S4修補已被10/22 18:02新Release實際採用；不得當成原「錯報有效量比」仍復發。缺正式可比歷史樣本屬資料限制；不得從其他scope/authority硬做比率。 |
| **TW-TECH-011 P2** | Confirmed Historical Runtime Timeout，Current Reproduction Unverified | 10/22正式3105 `technical.indicators`+`technical.structure` cache-only，約**30.09s**回 `READ_NODE_TIMEOUT:technical_evidence`；離線同能力14 fixtures及166 targeted已通過，原盤中延遲未重演。 | Source根因未確認；先對當前Session/domain canonical多週期Bars/ORM/lineage及同Node工作負載定點量測，再談重構或Timeout；不要重跑無關全部 tests。 |
| **TW-INDEX-012 P2** | Confirmed Architecture Coupling Risk | 現行 `indices.py::_refresh_current_market_summary`仍以同一 `_SUMMARY_REFRESH_LOCK` 同包5秒Index和60秒Breadth，Breadth依市場序列完成。 | 具阻塞機會，但缺Index調度/SQLite transaction timing證據，不能宣稱已造成今日某一次指數Timeout。拆鎖前先驗證DB同步與同域atomicity。 |

## D. 其他市場與平台的有效異常

| ID／級別 | 分類 | 最新觀測 | 必要下一步／證據限制 |
| --- | --- | --- | --- |
| **JP-DATA-013 P2** | Data Coverage Gap／Health Snapshot Expired | JP 7203 最新 Quote事件 **9/11**；JP `daily_price` provider Snapshot最終9/11檢查仍標 `latest=8/31`，Fundamentals/InvestorTypes/MarginInterest empty；其 Health Snapshot年齡約42天。 | 優先確認正式JP Refresh Job/Provider、局部 StockMaster與當前交易日後才判斷是Live停擺還是歷史Health未刷新；不能把42天前Health當今日Provider運作事實。 |
| **KR-DATA-014 P2** | Data Coverage Gap／Health Snapshot Expired | KR 005930 最新Quote事件 **9/11**；KR official source-health Snapshot仍停**7/28**，KRX daily、OpenDART financials、InvestorTrading empty、Yahoo daily Stale。 | 先更新有界Source Health再按KR market/dataset定位，勿把過期Health快照當目前Provider錯誤；已有stock報價也遠超可用即時時效。 |
| **US-OPTIONAL-015 P2** | Domain Coverage／Data Freshness | 最新US Health：FINRA short_volume **6/1** vs expected **10/22**；SEC Form4最後**8/10**；FRED macro_series empty、AlphaVantage corporate_actions empty。US AMD `quote.snapshot`/daily品質整體有部分可用，但Yahoo fallback daily 10/2 stale。 | FINRA/SEC若為實際使用的選股與研究能力，逐來源驗證排程、授權與Release；2026/10/23 16:4x Taipei等於美東約04:4x，Intraday pre-market stale不可單憑 status當故障。 |
| **CRYPTO-016 P3** | Unverified / One Tool Timeout | 本輪唯一對 BTCUSDT `omi.ask` `cache_only` 請求回 `timed out`；8400 Readyz仍200。`diagnostics.source_health`彙總只列TW/US/JP/KR，未覆蓋Crypto。 | 可能是MCP/Route/Serialization/Deadline，不足以定案Crypto服務故障；停止同樣重試，待有正式request id/Node timing再定位。 |
| **FRONT-017 P3** | Historical Observation，Current Not Reproduced | 10/21截圖 `Next.js Runtime ChunkLoadError app/layout.js timeout`；本輪 `3000/` HTTP200、layout.js HTTP200約16ms，且Frontend Git無修改。 | `layout.tsx` `<Script>`不是Root Bug證據。只有再復現時抓Browser Network/HMR/Dev log對時，先不改Script或清 `.next`。 |
| **OPS-018 P2** | Restart Reconciliation Observation／Risk | 10/22 `apply-omi-update.ps1`曾經180.041s HARD_CUTOFF，保留 `FORCED_EXIT_CONFIRMED`、`recovery_state=RECONCILIATION_REQUIRED`；後續10/22 18:02 Backend-only已**graceful exact exit**、新PID61364，現在policy `graceful_then_owned_cutoff_180s` 且available。 | 已證明強切能交付而**未證明之前所有JobRun／持久化責任完全對帳**；若要關Gate，只讀稽核該次受影響JobRun/startup cleanup/ID，不能以`readyz`補證；不將forced exit冒充graceful。 |
| **OPS-019 P2** | Identity / Deployment Observability Risk | `/api/system/runtime-control/status`明列Frontend `pid=null/status=unknown/readiness=UNATTESTED`、MCP dependency `EXTERNAL_ADAPTER_NOT_ATTESTED`；但OS實際3000 node PID57500與首頁HTTP200。 | 這是Launcher/Runtime對外所有權證據缺口，不是已確認Frontend停止。應以現有Owner chain/前端identity proof補驗，不新開Process Manager。 |
| **OPS-020 P2** | Delivery/Version Debt | `main` 有112個dirty entries，包括Source、runtime腳本、測試及未追蹤原事故文件；目前正式Release已換版但不代表Git已Commit/Push。 | 未分批收斂與遠端對齊，存在換機／回滾／對帳風險；封版前只提交已驗證、屬該任務的Diff，避免混入Legacy/WIP/DB/Secrets。 |
| **OBS-021 P2** | Health Aggregation Semantics Risk | 統一Source Health現有**714項記錄**、其中651歷史、63 operational，彙總33 operational non-current/failed（TW含臨時休市造成的多項假異常；US含美東盤前Stale；JP/KR本身Snapshot過期）。 | **33並非33個確認程式Bug，更不等於301個現存Bug**。應針對Status checked_at/TTL/session/daypart去重，保留request時鐘與正式資料來源。 |

## E. 本輪已排除／已通過，不再列為待修Defect

- 10/22 S0/S1/S4（Quote Canonical Board-lot/Share Volume + Minute Delta雙端資格）：10/22 **18:02**官方Owner Backend-only重啟 UUID `94c3148e-9e34-4b0e-9182-2f0dd1b42cb4` terminal `SUCCEEDED`，PID2916→61364，Loaded Release `1d11ca7f…`；10/22晚間正式Cache-only Outward已證3105/3406/3264 lots/shares/status/source正確，Volume Delta不合格為null，沒有假量比。
- 10/22曾回 `TW_OFFICIAL_DAILY_RELEASED_BUT_UNAVAILABLE` 的3105／3264：本輪逐檔以**trade_date=10/22**、cache-only required `daily.ohlcv`查回2330／3406／3105／3264最新均為 **10/22**、capability Quality `ready/current`。故10/22這四檔的延遲不能再當目前未修缺陷；今日10/23告警來自臨時休市日判定錯誤。
- R3 Index MIS IO Owner、R4 Last Confirmed Trade／Fugle事件時間Safety、R4-C KGI分步diagnostic、G4 bounded Demand已有可繼承Source＋Targeted證據；各自其他 Live Product Gate尚未全過，不重跑未變更之模組。
- 10/22正式 G3 單筆KGI→Fugle fallback選路與Cleanup曾PASS，不能誤寫成`Coordinator completely cannot fallback`；未得到Fugle股票ACK與實際15秒Quote則仍為Unverified。
- 10/21單次Next.js ChunkLoadError已無當下重演，不能視為當前持續前端停機。

## F. 處理優先序與最小 Gate

| Gate／順序 | 目標 | 完成判準／停止條件 |
| --- | --- | --- |
| **G0 最優先（P1）** | 正式Taiwan Calendar Emergency Closure對齊10/23；不影響10/22、10/26、10/27與其他Market | Source fixture先Red→Green：10/23 TWSE/TPEX `market_closed`、上一交易日10/22、下一預定10/27；正式Backend採用後Dashboard/`omi.ask`不再要求10/23 EOD/Breadth，不產生假Bar。使用者未授權改碼／重啟前保留現役程序。 |
| **G1（P1）** | 台股 Single-Quote SLA + MIS `z`缺價與20s Batch獨立根因 | 10/27有交易時，保留自然單輪Raw/IO holder/deadline/actual z vs v/tv/ts；在原Venue Slot內有界Foreground公平性；若Provider仍欠缺z則fail closed，不拉大Quota、不偽造15s Trade。 |
| **G2（P1/P2）** | KGI/Fugle股票ACK、R4-C診斷、1m需求與官方EOD | 單一`acceptance_probe`有界lease、原Coordinator選路、訂閱Ack、合法Actual EventTime、Canonical/Raw對齊、finally清lease；K GI `QUOTE/KBAR/DEPTH/AUCTION`診斷分離。1m只查已知缺桶，不重複已PASS的完整前綴。 |
| **G3（P2）** | `technical.indicators+structure` ReadNode Timeout與Volume Baseline Product | 用同Release同Session有界Profile/ReadGraph定位30s成本；Volume等待真正可比樣本或有權威歷史來源，不用估值湊pace。 |
| **G4（P2）** | JP/KR Feed來源、新US FINRA/SEC Optional coverage、Crypto單點逾時 | 先刷新或讀取可信當下Source Health Snapshot，再定點找缺資料的Owner/Job與方案／配額；沒有證據不重寫Provider。 |
| **G5（P2）** | Forced cutoff durable reconciliation與Git/Frontend identity | 對10/22 forced receipt查受影響Jobs的正式cleanup與Owner；編號Diff逐批Commit/Push並稽核遠端；其他未授權變更保持原狀。 |

## G. 驗收與操作邊界

1. **本輪只讀**：沒有運行新的Backend Test/Build、Provider HTTP、Fugle/KGI Subscription、Runtime Restart、Job Backfill、Data Migration、DB清理、Commit/Push。唯一對Crypto的cache-only OMI請求於工具側逾時，未重送。
2. **不能把一次SourceHealth聚合當完整Runtime Audit**：CJK市場有過期snapshot、US為非正式盤中時間；Options／Broker/Portfolio權限、Execution及Trading safety沒有做新的E2E，因此標Unverified，而不是缺陷數0。
3. **分別保留 Source PASS／Runtime Loaded／Live Product PASS**。已通過的舊測試證據如Source unchanged與共用依賴未受影響可繼承；出現Schema/Runtime/Config或本次Calendar改動時才重跑受影響的fixtures。
4. **此表為截至當前可取得資料的已知/已觀測問題整合，不代表已證明整個Repository絕無其他缺陷**。若有人按本表開始修復，最小Target是G0 Emergency Calendar，不應一次提交20條無關重構。

**封版判斷：目前不建議 OMI 全域封版。Backend/Frontend可連線，Volume S014等局部Gate已PASS；10/23 Calendar Root confirmed P1、Quote/Breadth/資料覆蓋 P1仍在。**


### 2026-10-23 G0 Calendar 緊急休市修正｜Source fixed / Runtime pending

僅在原 `trading_calendar.py::TAIWAN_EMERGENCY_MARKET_CLOSURES` 增加 2026-10-23 薔琵（Champi）全日休市；維持 `TW_TYPHOON_EMERGENCY_CLOSURE` 與 emergency 優先於 verified annual cache 的既有順序。來源為 [CNA 2026-10-22 20:39 援引 TWSE／TPEx 公告](https://www.cna.com.tw/news/afe/202610220388.aspx)，該 URL 已寫入 closure.source；本輪沒有取得交易所原始公告 URL，不將 CNA 標成交易所網站。

定點 fail-first：舊 Source **3 failed / 18 deselected**，分別證明 10/23 誤判交易日、covered/no-holiday cache 未保留緊急休市、daily release 錯指 10/23。修正後 `test_trading_calendar.py` **21 passed / 6 subtests passed**：10/22 交易；10/23 09:15、14:00 休市，presentation 為 previous_session／10/22／非當前交易日；10/26 補假；next／rollover 為 10/27 08:00、09:15 regular；10/23 16:00 market_daily_price expected_trade_date=10/22，previous=10/22、next=10/27。既有 US／JP／KR calendar 測試通過。未新增 consumer 特例、假 OHLC 或 Volume。

離線命令：`.venv/Scripts/python.exe docs/exec-plans/active/tw-missing-values-source-contract-20261020/s014-evidence-20261022/run_offline.py -q tests/test_trading_calendar.py`；red 額外使用 `-k "october_typhoon or verified_schedule_absence"`。沿用原 offline runner 禁止 network／disk SQLite，`MARKET_CALENDAR_CACHE_PATH` 指向本任務不存在的 cache 檔以使用固定 Source 年曆。`scripts/check-architecture.py` PASS（actual 15／declared 15）；兩個受影響 Python 檔 compile、UTF-8 讀回及 `git diff --check` PASS。

本機 Reviewer 證據：`.tmp/g0-calendar-20261023/` 保存 baseline／四檔 preimage、red.log、green.log、architecture.log、task-only.patch、preservation.json 與驗證命令。開始為 main 113 dirty，Calendar source/test 原為 clean；既有 WIP 按原 hash 保留，兩份文件僅追加，staged diff 不變。**Source PASS／Runtime Pending／Live Pending／獨立 Reviewer Diff 驗收 PASS**。未重啟或停止 OMI、未讀寫正式 DB、未 Provider IO、未修改 Launcher／Frontend／MCP／Subscription、未交易、未 commit/push；G1–G5 未執行。先前 runtime／live 紀錄仍屬歷史證據，本輪不宣稱新 Source 已載入。


### 2026-10-23 17:21–17:24｜G0 正式 Backend-only 重啟與執行路徑驗收：PASS

> 前一段 G0 Source／Runtime Pending 是執行前的歷史Checkpoint，**以本段正式Owner terminal與Live API為最新權威**。使用者已在本輪明示授權重啟；G1～G5仍未修改、未重測。

- 正式重啟前狀態：Launcher Owner `453e7309-250c-402e-8a74-9b458e5538f9`，Launcher **PID53040**、Backend **PID61364**，loaded Release `1d11ca7f5bbd3567f5d502cacf5ba37938f611640ad170fa45d562910eee64a1`；`restart.available=true/blockers=[]`；仍有一項Consumer Demand Future在執行（`run_consumer_demand`, job 174183），原Owner負責停止與Drain。前置 `/readyz` 200不代替Writer Drain。
- **僅提交一次** `omi.restart_backend` 正式Operation：`request_id=c67e379c-9f7e-4ac3-bec1-7bd34537c22a`、expected Owner上述UUID、confirmation `restart_backend`；HTTP202 accepted→running時 /readyz 曾503 `restart preflight in progress`，短暫 Backend `RUNTIME_UNAVAILABLE/ECONNREFUSED`。沒重送/補送另一UUID或手動kill。
- 同一UUID durable terminal **`succeeded/SUCCEEDED`**：Backend **61364→72996**，新Created `2026-10-23T09:21:37.6749900Z`（17:21:37 +08），Launcher PID53040不變；`stop_evidence.State=stopped, Reason=LIFESPAN_AND_EXACT_EXIT, ExactExit=true, Forced=false`，非180秒強切。Port8400獨立Listener為`python.exe` PID72996。
- 新載入 `APPLICATION_SOURCE_SNAPSHOT` Release **`51fc45d4e333a2f3d0b774c8c8993d7593b652bc93468b7f391bc6a8b1fda59d`**，重啟後 `omi.read_runtime_status` 的PID/Release核對一致，`/api/system/readyz` **HTTP200**（runtime/database ok），restart.available=true/blockers=[]。
- **Runtime G0直接驗收**：`omi.read_tw_market_dashboard` 當下 `session.phase=market_closed`、`presentation_state=previous_session`、`trade_date=2026-10-22`、`is_current_trading_day=false`、`next_transition_at=2026-10-27T08:00:00+08:00`。TWSE／TPEX持續標示10/22的歷史單輪快照，不冒稱今日成交。
- 正式 `GET /api/market/calendar-status?market=tw` HTTP200（17:23台北）：`is_trading_day=false`、`phase=market_closed`、`holiday_name='Typhoon Champi (薔琵) emergency market closure'`、`previous_trading_day=2026-10-22`、`next_trading_day=2026-10-27`、`presentation_session.trade_date=2026-10-22`；`release_windows.market_daily_price.status=market_closed, is_released=false, expected_trade_date=2026-10-22`。Institutional、Margin、Broker與Market Chips當日休市release亦為market_closed，不再要求10/23不存在的EOD。其餘月季法規Release依原時間軸維持各自狀態。
- 正式 `omi.ask` 2330 `cache_only/refresh_off/external_fetches=0` 的 `quote.official_close` 返回 `latest_completed_session / 2026-10-22`；沒有前次 `TW_OFFICIAL_DAILY_RELEASED_BUT_UNAVAILABLE:2026-10-23`，歷史`quote.snapshot`仍含stale提示，**不代表15秒即時成交 PASS**。
- **Gate結論：G0 Source／Offline／Independent Diff／Runtime Adoption／正式 Calendar與Dashboard Outward全部 PASS；可以結束這項日曆缺陷。** 明日10/24～26皆非交易日，下個預定正常session為10/27。G1～G5及 MIS z缺價／15秒Quote／Breadth／技術超時／JP KR 資料等原報告仍維持OPEN或UNVERIFIED，不因本次G0換版封版。這次沒有變更Source/DB/Frontend、訂閱/交易、Commit或Push。
