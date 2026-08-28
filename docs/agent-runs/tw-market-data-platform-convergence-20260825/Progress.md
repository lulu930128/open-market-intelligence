# Progress

## Status

- Current phase：`cp8_production_adopted_cp5_r_source_converged_runtime_adoption_pending`
- Current label：`TW_CLOSE_LIFECYCLE_SOURCE_READY_RUNTIME_AND_CHRONOLOGICAL_ACCEPTANCE_PENDING`
- Target：`TW_DATA_CORE_COMMON_PLATFORM_OPERATIONAL`
- Last updated：`2026-08-27 Asia/Taipei`
- Production wiring changes：`base_data_core_adopted_cp5_r_source_converged_runtime_not_adopted`
- External provider calls：`6 bounded public official calls across the task; 2026-08-27 added one read-only 3711 TWSE MIS diagnostic call`
- Runtime/live acceptance：`18:10 runtime predates critical source changes; post-close session close missing; official EOD partial; active_session_public_quote_pending`
- Commit/push：`not_authorized`

## 2026-08-27 CP5-R source implementation

- CR0～CR6 source gate已完成；本次維持既有 `tw.quote.snapshot -> Gateway -> Resolver -> projection` 集中管理路徑，沒有新增session-close service、resolver、dataset、table、scheduler或provider plane。
- CR1將Taiwan cash-equity phase一律收斂至`trading_calendar.py`；`public_quote_platform`、`taiwan_realtime_platform`、`tw_current_market_platform`、AI、technical與legacy comparison不再自定13:30～13:33時鐘。
- CR2修正intraday response schema對`datetime`的錯誤序列化；source health拆開raw quote、session-close readiness與official-daily release state，11:49／601不再被標成當日completed-session price。
- CR3沿用existing single-symbol acquisition／repository／transaction／Gateway／Resolver保存與重讀session close。Promotion必須同時滿足current trade date、actual trade、non-trial、event time在13:30～13:33合法final-match／resolution window、post-resolution confirmation與non-regressing volume；13:24或更舊成交fail closed。
- CR4將quote headline、AI／MCP projection、technical `current_partial`與前端「今日」狀態對齊backend-owned `quote.session_close`；official daily未到前不用昨日close或stale intraday冒充今日收盤。
- CR5將session-close／official-daily reconciliation收斂至existing public quote platform owner；matched／mismatched不會將session-close偽裝為official daily，technical completed仍只接受finalized daily bar。
- CR6修正full-market EOD job postcondition；provider fetch完成但coverage仍為861／1,973時，internal JobRun不再誤報success，outward維持truthful `partial`與structured result。
- 直接相關最終regression：`407 passed, 242 subtests passed`；frontend ESLint、TypeScript與production build全部通過。
- Backend safe profile完成compileall並跑到100%；其中2個失敗來自共用worktree另一組未追蹤US OHLC continuity tests，另有Windows pytest basetemp清理`WinError 5`。本任務沒有修改或回退那批US變更，也不宣稱full-repo green。
- CR7的source regression已完成；runtime adoption、installed MCP loaded contract與launcher-selected outward probe仍待明確重啟授權。CR8必須在下一個可用台股交易日按13:30～13:33、14:00、15:15+真實時序驗證，不用fixture或晚場replay代替。
- 唯讀runtime probe：`127.0.0.1:8400` listener PID 53076／start 18:10:22，`/api/system/health` 與 `readyz` 正常，但`GET /api/market/intraday/3711`仍為500；這證明目前runtime確實未採用18:10後的schema/source修正。
- 本輪未重啟runtime、未觸發provider refresh／repair、未寫production DB、未reload installed MCP、未commit／push。

## 2026-08-27 full audit rebaseline

- 已完成本輪規劃整理，沿用existing `tw-market-data-platform-convergence-20260825`長專案與`CP5PostCloseFinalizationPlan.md`，沒有另開平行close-lifecycle專案。
- 將CP5-R狀態由`source_implemented_regression_ready_runtime_pending`改為`full_audit_rebaselined_implementation_pending`。
- 建立CR0～CR8 authoritative execution order與六個獨立completion gates；source、runtime、live、official EOD、MCP/UI不再互相代替。
- 重新分類先前source completion claims：
  - phase owner仍分散；13:31可落入`close_resolution`、`UNKNOWN`或`POST_CLOSE`。
  - 3711 live quote仍為11:49:55／601且session close missing；13:30／605只存在intraday non-owner path。
  - intraday outward有datetime/string response validation 500。
  - source health把舊quote誤標completed-session available。
  - EOD scheduler有執行，但full-market coverage僅861／1,973 current。
  - repo MCP snapshot有68 capabilities；installed OMI_search snapshot仍為66且缺`quote.session_close`。
- 本輪只修改task docs；未修改backend／frontend、未重啟runtime、未觸發provider refresh／repair、未寫DB、未reload MCP、未commit／push。

## Completed

- 2026-08-27先前CP5-R source implementation紀錄（經full audit重新分類，不能視為production closure）：
  - 沿用existing `tw.quote.snapshot`、canonical `QuoteObservation`、public quote transaction/repository、Market Data Gateway與shared Resolver；沒有新增service、resolver、dataset、table、scheduler或第二套provider plane。
  - 建立authoritative `regular -> closing_auction -> close_resolution -> post_close` taxonomy，消除calendar／quote-depth的13:30～13:33分歧。
  - 新增resolved `quote.session_close` projection；official daily 15:15 ownership與`TAIWAN_DAILY_PRICE_RELEASE_TIME`保持不變。
  - 既有schema通過same-event later-receipt、append-only raw receipt、single-row idempotent upsert與cold-read confirmation測試，不需要migration。
  - Post-close headline、AI freshness與technical provisional改用session-final evidence；official daily arrival後支援matched／mismatched且official wins。
  - Final exact-scope cross-module gate為`553 passed, 1 deselected, 284 subtests passed`；MCP static enum與offline public-contract snapshot已同步。
  - Backend safe wrapper的compileall通過；full suite的mixed-worktree failures與locked pytest temp已分離記錄，不以它們冒充本次source failure或全repo綠燈。
  - Runtime adoption、正式API／MCP probe與bounded live sample仍待明確重啟授權。
- 2026-08-27完成3711 post-close ownership gap的source／runtime／SQLite／official-rule read-only audit：OMI最後persisted quote為11:49:55／601，TWSE MIS 15:28仍可取得13:30:00／605；證明來源可觀察但既有post-close acquisition/finalization path缺席。
- 建立 `CP5PostCloseFinalizationPlan.md`，把修正收斂為既有CP5 Data Core corrective extension：
  - 沿用`tw.quote.snapshot`、QuoteObservation、Gateway、Resolver、repository、transaction、raw receipt與existing SQLite table。
  - `quote.session_close`只作resolved projection，不新增dataset/service/resolver/table/scheduler。
  - 明定session-final必須有13:30～13:33合法final-match／resolution event；13:24與其他舊成交不可因時鐘跨過13:33而升格。
  - 定義PCF0～PCF7、acceptance、stop-and-fix、bounded live與runtime adoption gates。
- 既有相關regression read-only baseline為265 passed、18 subtests passed；這證明舊contract仍全綠，但不覆蓋post-close finalization gap。

- 完整讀取兩份使用者附件，並將其視為proposal/contract input，而非直接執行指令。
- 讀取repo current product/architecture truth、README、dependency/validation入口與現有長任務文件。
- 記錄附件SHA-256、branch、HEAD與dirty worktree baseline。
- 驗證`quote_depth.py`、`intraday.py`、`indices.py`、generic lease router、daily chart seam、Dataset Registry、AI TW context、backend research與frontend indicator math。
- 確認Shared Foundation與02A dark core已存在，不應建立第二套；production TW wiring仍未完成。
- 盤點第一條actual-data pipeline所需storage與ingress：
  - `SourceRegistry`保存source identity/operational status。
  - `RawFetchResult`保存fetched_at、URL/method/status、content hash與raw receipt。
  - `MarketDailyPrice`以`(source_id, stock_id, trade_date)`唯一保存source-scoped OHLCV。
  - `MarketDatasetCoverageCheckpoint`保存expected date、coverage partition與repair state。
  - `refresh_source()`及parse pipeline已能取得TWSE/TPEx official bulk data並寫入daily rows。
  - EOD reconcile已具unresolved-venue targeting、safe release window、post-refresh recompute、backoff與scheduler startup catch-up。
- 將umbrella plan重排為actual-data-first：official daily OHLCV -> EOD lifecycle -> official index/breadth -> non-KGI public request-time data -> provider/dataset/consumer convergence。
- 將既有realtime M5與KGI移出共同平台依賴鏈與done criteria；保留為CP8後的獨立provider onboarding任務。
- 更新Goal、target ownership、component map、CP0-CP8 milestones、stop-and-fix rules與acceptance matrix。
- 完成CP0 storage/transaction/boundary decision：daily read seam沿用現有schema，不先建generic observation table；production write cutover仍未核准。
- 建立pure `DailyBarCandidateRepository` contract與bounded query/read/rejection models。
- 建立read-only `TaiwanOfficialDailyBarRepository`：
  - venue-scoped TWSE/TPEx official source mapping。
  - persisted row -> Canonical `BarObservation`。
  - source/raw/trade date/fetched time/observation ID lineage。
  - missing/inconsistent OHLC explicit rejection。
  - max rows/range fail closed，不silent truncate。
  - zero provider IO、zero commit/rollback、zero fallback/selection。
- 建立machine-enforced debt baseline與boundary tests；既有debt可縮小但不可增加。
- 完成CP1 additive common core：
  - `DataRequirementV2`以typed instrument/dataset target、snapshot/bar/dataset capability、freshness、quality與bounded policy表達consumer intent；禁止provider control。
  - `RefreshRequirementV1`將explicit repair/background mutation與read request分離。
  - `ProviderCapabilityDescriptorV2`以provider + market + capability + resource表達authority、venue/instrument/interval/session scope、acquisition mode、health policy與硬上限。
  - shared planner只接受market-owned descriptor注入，不含production provider catalog；`cache_only`/`completed_session`永遠產生zero-I/O plan。
  - `MarketDataGateway`執行persisted pre-read -> Resolver -> bounded shared plan -> executor -> transaction owner -> mandatory repository reread -> Resolver。
  - executor實際嘗試的provider/resource必須是shared plan子集；超出route或call/subscription/time/row bounds即fail closed。
  - acquisition adapter、transaction owner與candidate repository以獨立protocol分責；Gateway不import DB/provider/market service且不commit/rollback。
  - raw receipt、acquisition、persistence與`MarketDataResultV1`為typed contract；provider/dataset/resolved health維持分離。
  - `ResolvedAuction`補齊typed shared resolution contract；既有Resolver仍是final selection owner。
- 完成CP2 official Taiwan daily OHLCV production slice：
  - 建立TWSE `STOCK_DAY_ALL`與TPEx `tpex_mainboard_quotes` capability/resource descriptors；scope鎖定TWSE/TPEX、completed-session、單symbol/單日/單call bounded refresh。
  - 建立pure official payload adapters，完整保留OHLC、shares、turnover、trade count、price change、instrument name與trade date；empty、malformed、duplicate、missing target與invalid row皆有reason code。
  - 建立market-owned acquisition executor；只執行shared plan routes，不做DB write、fallback或selection，HTTP/parse failure仍產生durable raw receipt與provider health。
  - 建立`TaiwanOfficialDailyTransaction`；同一transaction寫入source、append-only raw receipt、quality check與idempotent `MarketDailyPrice`，commit失敗全部rollback。
  - `SourceLineage`以additive optional欄位補上`raw_receipt_id`與`content_hash`；persisted resolved bar可直接回溯canonical row與raw receipt。
  - 建立`TaiwanOfficialDailyPlatform`；refresh完成後強制經repository重讀與Resolver，postcondition不相信provider success字串。
  - 既有daily chart預設read已改由`MarketDataGateway`讀取official persisted candidates；GET維持zero provider IO，explicit legacy history repair後也回到platform rere讀。
  - 新增provider-neutral `POST /api/market/daily/{stock_id}/refresh-official`；public input只有stock/date，不接受provider控制。
  - TWSE/TPEx actual recorded public receipt excerpt皆完成canonical conversion、in-memory DB persist、readback、resolution、idempotent rerun與stable chart schema驗證。
- 完成CP3 full-market EOD lifecycle source convergence：
  - 新增shared `DatasetLifecycleContract` / `DatasetLifecycleEvaluation`，從Registry衍生owner、read/refresh operation、bounds、expected/eligibility policy、postcondition與health；shared module不import DB/job/scheduler/provider。
  - `tw.daily.ohlcv.full_market`的expected-state policy、scope、repair operation與bounds在runtime fail closed驗證，enqueue request與worker effective work均被Registry上限clamp。
  - reconcile先由persisted rows重算coverage；healthy時provider calls為0，partial/missing只修unresolved venue，修後再次重算並更新checkpoint。
  - scheduler decision不再只相信舊checkpoint status；會重算當下persisted coverage並尊重retry boundary。
  - checkpoint detail與job result outward帶有dataset lifecycle與Dataset Health；provider/dataset/resolved health仍維持分離。
  - startup catch-up、job dedupe、retry/backoff與cache-only GET沿用既有成熟路徑，但其effective bounds與postcondition由Registry contract約束。
  - production SQLite唯讀重算1973檔active ordinary stocks：854 current、26 partial、1091 stale、2 missing，partition總和正確且與checkpoint完全一致；未隱藏TWSE未完成狀態。
- 完成CP4 official market breadth source/platform gate：
  - 新增typed `MarketBreadthObservation` / `ResolvedMarketBreadth`、Gateway/Resolver/result-envelope support與`tw.market_breadth.daily` Registry spec。
  - breadth repository只從同一venue/date/raw receipt的official daily rows與active registered universe導出advance/decline/unchanged/unknown/missing；`unknown != 0`、`missing != unknown`，receipt混用與partition不守恆會fail closed。
  - 新增provider-neutral cache-only `GET /api/market/breadth/official`；read path為0 external call、0 persistence。
  - production DB唯讀證據：TWSE 2026-08-24為315 advance、638 decline、129 unchanged、4 missing；TPEx 2026-08-25為367 advance、381 decline、90 unchanged、42 unknown、7 missing；兩者均如實`partial`。
- 完成CP4 official market index source/platform gate：
  - 新增distinct `MarketIndexObservation` / `ResolvedMarketIndex`、TWSE/TPEx pure adapters/descriptors、bounded acquisition、explicit transaction owner、lineage-enforcing repository、Gateway/Resolver platform與`tw.market_index.daily` Registry spec。
  - 新增nullable additive migration `20260825_0067`，補上`MarketIndexDailyStat.source_id/raw_result_id` FK lineage；正常0066升級/降級保留legacy row，歷史stamped partial schema安全no-op，不在錯誤owner migration中憑空造表。
  - legacy index row保留但因無raw/source linkage被新repository明確拒絕，避免把不可驗證資料冒充official evidence。
  - 新增provider-neutral `GET /api/market/indices/{index_id}/official-daily`與explicit bounded `POST .../refresh`；public input不接受provider控制。
  - TWSE/TPEx official public payload各完成actual parse、canonical conversion、isolated SQLite persist/readback/resolve/idempotent rerun；outage仍保存raw receipt，provider conflict由Resolver選official candidate。
  - 現有dashboard/summary仍是compatibility consumer；CP7切換前`E-06`維持partial，不用新增API掩蓋consumer debt。
- 完成CP5 non-KGI public last-trade quote source/platform gate：
  - 先建立`CP5CapabilityContract.md`，將能力鎖定為TWSE MIS single-symbol `quote.last_trade`；不納入KGI、subscription、M5、depth或intraday bars。
  - provider contract是`public_best_effort_no_sla`：每次最多1 provider attempt、1 external call、1 symbol、10秒、0 retry、0 subscription；public API不接受provider/channel/budget控制。
  - 新增pure MIS parser/descriptor、bounded acquisition、`QuoteAcquisitionResult` Gateway port、atomic quote transaction、lineage-enforcing repository與platform service；完成source/raw/quality/quote同transaction commit與rollback。
  - 新增nullable additive migration`20260825_0068`，補`TaiwanStockQuoteSnapshot`的source/raw/received/state/session/trade-state/contract lineage；legacy row保留但新repository fail closed。
  - TWSE 2330 actual trade與TPEx 6173 preopen indicative兩筆production SQLite唯讀樣本已封存；actual payload完成canonical persist/reread/resolve，trial/zero volume不被轉成actual last trade。
  - 新增provider-neutral cache-only GET與explicit bounded POST；route handler以actual persisted row驗證`MarketDataResultV1`、0 external calls與cache-hit lineage。
  - 正式`intraday.py` trend路徑不再直接抓MIS current quote，也不再把MIS snapshot製造為minute bar或把`tv/v`混入NStock/Yahoo bars；只從共通platform做cache-only resolved quote projection。
  - legacy MIS merge/snapshot helpers暫時保留供既有unit contract與CP8精確移除，但production `_load_intraday_trend_uncached`已有source guard證明不再呼叫。
  - active-session live smoke未在收盤後補造；保留F-07 pending，於production adoption後的下一個台股active session完成。

- 完成CP6 Taiwan dataset catalog與common health/lineage surface：
  - 建立28個typed production dataset contracts，逐一包含payload、storage、owner、read/projection/health、expected-state/eligibility、refreshability、bounds、postcondition、lineage與convergence狀態。
  - 建立18個market-owned bounded operation specs；所有callable由test實際resolve，router/AI/KGI不可成為mutation owner。
  - 新增cache-only Data Core API列出dataset、describe operation與讀actual storage/lineage health；沒有generic refresh-all endpoint。
  - Production DB以read-only URI取得CP6 point-in-time artifact：當時27個dataset中9 observed、1 missing、15 lineage incomplete、2 lineage limited、0 schema unavailable；未執行migration/provider IO/DB write，也未製造共同freshness verdict。
  - CP7加入`tw.technical.daily`為第28個non-refreshable derived dataset；不建立重複indicator value table。
- 完成CP7 AI quote source cutover：
  - Taiwan AI dependencies由`quote_depth`改成`read_taiwan_public_quote_projection`，不再由AI指定provider、重做fallback或製造provider attempts。
  - Intraday bars在AI path固定cache-only；quote lineage/freshness/health/limitations由Data Core result投影。
  - `omi.decision.v4`與MCP outward contract parity維持。
- 完成CP7 backend-authoritative technical series gate：
  - Indicator API與AI technical evidence都從`read_taiwan_official_daily`取得Resolver-selected official bars，不直接讀raw daily table。
  - Indicator point帶algorithm version、raw-unadjusted price basis、backend-authoritative role與parameter contract；新增active-engine contract endpoint。
  - Frontend metadata/parameter match時直接使用backend MA/EMA/RSI/MACD/KD/ATR/ADX/MFI/ROC/Donchian/Bollinger/support-resistance；legacy local math只作`presentation_only` compatibility。
  - Golden test加入close=10,000 vendor duplicate仍共同選TWSE official close=179，API/AI RSI、MACD、KD完全一致。
  - Completed-session cache read預設最近已發布交易日、0 external calls、1-5000 rows與36,600日range硬上限。
- 完成CP7 index dashboard completed-session adapter：
  - `/indices/summary`分開投影`completed_official_index`與`completed_official_breadth`，只在Data Core Resolver選到evidence時取代legacy completed fields。
  - Current-session observation與completed official evidence各自保留trade date；前一交易日official close不會被誤認成今日盤中official close。
  - Index與breadth read failure各自隔離，component health/lineage/limitations與`data_core_projection_scope`對外可見。
  - 0067尚未runtime adoption或canonical lineage缺失時回`data_core_missing`並fail closed，不復活legacy completed row；current-session observation維持獨立capability。
- 完成CP8第一批migrated-capability legacy closure：
  - 刪除`intraday.py` direct MIS request、fake MIS snapshot series與snapshot-to-bar price/volume injection helpers。
  - 台股OHLC GET的legacy `ensure_history=true`不再啟動provider/backfill；保留參數只為相容並回`not_attempted`。
  - Dashboard completed official components移除`legacy_compatibility`fallback；Data Core missing時fail closed。
  - `CP8LegacyClosure.md`界定未onboard current-session/depth/KGI與Registry-owned explicit EOD mutation，不以誤刪範圍製造假closure。
- 完成CP8 production adoption（F-07除外）：
  - 使用者重啟OMI後，launcher startup migration自動將production DB由0066升至0068；agent未重複手動migration。
  - 以正式launcher離線建立26,334,392,320-byte current backup；SHA-256、revision、quick check、FK與row counts均已驗證。
  - Verified backup clone完成0068 -> 0066 -> 0068 rehearsal；legacy row與unknown lineage保留，temp clone移除、正式backup保留。
  - Named launcher PID 58996管理backend `8916`與frontend `3000`；兩條listener ancestor chain、health/ready、DB check、UI health與proxy皆通過。
  - Data Core runtime公開28 datasets／18 bounded operations；TPEX 2026-08-25 official index以raw receipt 96206持久化並由Resolver選中，cold restart後lineage/value/transaction count不變且GET為0 external calls。
  - TAIEX 2026-08-25來源response沒有target date，truthful `TARGET_TRADE_DATE_NOT_FOUND`且不寫假row；2330 public quote在post-close以0 call回session policy unsatisfied。
  - Visible browser可見TPEX 389.41、+3.31、+0.86%與truthful breadth failure；console無warning/error。MCP `omi.ask`以`quote.official_close`、`cache_only`回decision v4 ready/high-trust evidence。
  - Stop-and-fix修正latest technical range的calendar-day／row-limit錯配，以及legacy restart writer覆寫canonical index lineage；正式cold restart後兩項都通過。
  - Evidence：`artifacts/cp8-production-adoption-20260825.json`。

## Validation evidence

- Read-only source inspection：completed。
- Attachment hashes：
  - `6660ad710db349a0990df0d8289ba4c04c7b98c3d0240b6e6ba8a3e8be410491`
  - `65e1b217aa3e4bbfaf9c31a7740d9bb3ed6ad605369742ac004f521f0eca3ce9`
- Git baseline：branch`codex/tw-etf-provider-normalization`，inspection HEAD`6d508c7021c1050680262ce4a83f5b33e9f5eda7`，39 status entries。
- Architecture evidence：
  - production `execute_acquisition()` callers：0。
  - TW production shared `resolve_*()` callers：0。
  - TW production ProviderDescriptor catalog：not found。
  - Dataset Registry production lifecycle caller：not found；目前主要用於capability/projection consistency。
  - Official TW EOD目前由`eod_coverage._repair_tw_eod()`呼叫`refresh_source()`，完成後重算coverage並persist checkpoint。
  - Daily candidate schema保有`source_id`、`raw_result_id`與source-scoped unique key；raw receipt保有`fetched_at`與`content_hash`。
- CP0 baseline regression：backend-compatible cwd，45 passed。
- CP0 implementation regression：55 passed。
- Safe validation `20260825-181248`：
  - backend compileall：passed。
  - targeted backend pytest：55 passed。
  - git diff check：passed。
- CP1 targeted regression：66 passed。
- CP1 shared/legacy regression：127 passed、2 failed；兩項均隔離為共享worktree既有/並行變更：
  - US `integration_manifest.py`新增02A import但舊dark-boundary allowlist尚未更新。
  - M5 foundation checkpoint對既有`config.py`等檔案的hash已不一致。
  - 本任務未修改上述US manifest、M5 checkpoint或其baseline來掩蓋失敗。
- CP1 safe validation `20260825-183001`：
  - backend compileall：passed。
  - scoped backend pytest：122 passed。
  - git diff check：passed。
- CP2 focused integration：58 passed（official platform、chart read、boundary、registry、shared contracts/resolution）。
- CP2 safe validation `20260825-185559`：
  - backend compileall：passed。
  - scoped backend pytest：117 passed。
  - git diff check：passed。
  - OpenAPI inventory：398 operations，其中397個位於`/api/`；official refresh route有精確method/path guard。
- CP2 actual-data artifact：`artifacts/cp2-official-daily-evidence.json`。
- CP3 safe validation `20260825-190423`：
  - backend compileall：passed。
  - scoped backend pytest：132 passed。
  - git diff check：passed。
- CP3 production read-only artifact：`artifacts/cp3-production-eod-coverage-readonly.json`。
- CP4 breadth/index focused integration：130 passed、160 subtests passed；包含完整migration suite、API inventory、Gateway/Resolver、official daily/breadth/index與technical consumer regression。
- 月線consumer range stop-and-fix：bounded daily candidate上限由3,660日調整為36,600日，仍受5,000 rows硬上限；`test_tw_daily_candidate_repository.py + test_technical_report.py`為29 passed。
- CP4 migration compatibility：0066 -> 0067 -> 0066 row preservation與兩條historical partial-schema upgrade共3 passed。
- CP4 actual breadth artifacts：`artifacts/cp4-production-official-breadth-readonly.json`。
- CP4 actual index artifact：`artifacts/cp4-official-index-evidence.json`；TWSE/TPEx官方公開response SHA-256與parsed rows已保存。
- CP5 actual quote artifact：`artifacts/cp5-public-last-trade-evidence.json`；TWSE/TPEX actual raw hashes、trial/actual semantics、isolated persistence與consumer separation evidence已保存。
- CP5 focused integration：89 passed、162 subtests passed；涵蓋public quote、intraday trend/history、dashboard、Gateway、Registry、boundary、model/migration與OpenAPI inventory。
- CP5 import validation：以`PYTHONDONTWRITEBYTECODE=1`成功import新增platform/transaction/repository/acquisition/router；一般`compileall`曾因Windows鎖住`tests/__pycache__`無法寫暫存`.pyc`，非source syntax failure。
- Backend safe validation `20260825-193838`：compileall passed；full pytest跑到100%，但session finish受Windows basetemp PermissionError中止。測試本體當時另有2項本task月線range failure（已修正並由29/130項回歸證明）及2項隔離的共享worktree US/M5 dark-boundary failure；未修改其他任務baseline掩蓋。
- Production SQLite僅用URI `mode=ro` + `PRAGMA query_only=ON`檢查；未執行migration、未寫production/local OMI DB、未啟動或切換runtime。breadth查詢期間DB仍由既有runtime更新，因此artifact明示不是frozen snapshot。
- CP6 catalog/health regression：111 passed、68 subtests；另有CP6 source/platform先前36 passed與production read-only storage artifact。
- CP7 AI quote/consumer regression：115 passed、3 subtests；decision v4/MCP parity 202 passed、272 subtests。
- CP7 resolved-input/technical/capability/AI/MCP合併regression：337 passed、340 subtests。
- CP7 frontend targeted ESLint：passed；`npx tsc --noEmit`：passed。
- CP7 index dashboard Data Core adapter/index-date regression：111 passed。
- CP8 quote/OHLC legacy removal regression：79 passed；strict dashboard/index regression：91 passed。
- CP8 migration/model/platform regression：39 passed、102 subtests；0067/0068 upgrade/downgrade compatibility通過。
- CP8 actual-data cold restart：1 passed；同一fresh file-backed SQLite持久化actual TWSE daily/index與TWSE MIS quote，dispose/reopen後daily/index/breadth/quote皆Resolver selected、0 external calls，chart/dashboard projection可讀回。
- Foundation successor checkpoint：舊Foundation/M5 artifacts未改寫；本任務新增13個TW Data Core/common platform精確source hash overlay，並將共存的US integration hunk保留在checkpoint外。dark-boundary 7 passed。
- Full safe validation第一次解除checkpoint drift後完成2280 passed，但300秒wrapper上限在pytest teardown前誤標timeout；backend bounded default調為420秒後重跑取得乾淨終態。
- Full safe validation `20260825-222211`：backend compileall passed；2280 tests passed（939 warnings，307.10秒）；frontend lint passed；TypeScript passed；production build passed；`git diff --check` passed。E2E未執行，runtime/browser evidence歸H-06。
- CP8 read-only production preflight：active DB 24.512 GiB、WAL/SHM存在、Alembic `20260822_0066`；現有2026-06-07 1.61 GiB backup不足作current rollback point。Launcher selected backend `8916`/frontend `3000`均healthy，但10:41啟動的runtime對Data Core catalog/health routes回404，明確為尚未adopted。Evidence：`artifacts/cp8-production-adoption-preflight.json`。
- CP8 production adoption targeted regression：118 passed、8 subtests passed；涵蓋official daily/index、technical、legacy index persistence與cold-read相關路徑。
- Full safe validation sandbox run `20260825-230607`：測試本體跑到100%，但pytest session finish因sandbox-created basetemp `WinError 5`失敗；不計為passed。
- Full safe validation host run `20260825-231250`：backend compileall passed；2282 tests passed（939 warnings，295.17秒）；frontend lint、TypeScript、production build與`git diff --check`全綠。
- Production outward smoke：backend health/ready 200、Data Core datasets/operations/health 200、TPEX cache-only cold read selected、indicator/technical 200、frontend UI/proxy 200、visible browser與MCP decision v4 passed。

## Decisions made

- Data Core Integration Contract是internal platform contract；不建立public mega-endpoint。
- 完整重架構採actual-data vertical slices；完整範圍不等於一次性Big Bang rewrite。
- 既有02A dark Control Plane/Research Lease/Resolver直接承接；新工作補Gateway、candidate repositories、transaction owner、TW descriptors/ports與production cutover。
- 第一條production slice使用TWSE/TPEx official daily OHLCV；這條路徑同時驗證actual IO、canonical conversion、persistence、lineage、Resolver、Lifecycle與stable output。
- 既有M5/KGI完全deferred，不阻塞共同平台；不得用共同平台完成狀態暗示KGI/realtime已完成。
- Request-time market evidence與durable dataset evidence共用stable envelope，但保持typed payload與market ownership。
- 現有daily/raw/source/coverage schema先由repository seam沿用；CP0 contract audit證明不足時才做additive migration。
- CP0決定daily read不需要migration；correction revision、不可重建quality/limitations或request-time received semantics出現時才重開migration decision。
- Raw receipt transaction、canonical parse transaction與coverage postcondition transaction保持分階段；不強迫跨階段atomic，以保留parse失敗時的raw evidence。
- Provider-specific compatibility只能留下outward lineage alias；不得再擁有acquisition/fallback logic。
- Provider catalog採market-owned injection；shared Core只持有descriptor schema與pure planner，不持有任何TWSE/TPEx/KGI/Yahoo/NStock等production名稱。
- Gateway只執行shared plan；provider executor不能回報plan外resource，transaction成功後仍不得直接信任acquisition payload，必須repository reread。
- Raw receipt identity與content hash是shared lineage的一部分；`observation_id`與`raw_receipt_id`不可互相代替。
- CP2正式read採platform-owned cache read，正式repair採provider-neutral explicit POST；舊`ensure_history=true`只保留相容性，不是新read contract。
- Dataset Registry不是文件型catalog：runtime lifecycle、enqueue有效範圍、health evaluation與postcondition evidence必須從同一spec衍生。
- CP3 source acceptance與production health分開；partial checkpoint是正確結果，不得因架構已接線就宣稱資料已健康。
- Official breadth只能從coherent official receipt與registered universe產生；unknown、missing、not-tradable與no-trade不可互相代換。
- Official index storage使用additive nullable lineage欄位；migration保留legacy資料，新platform則只接受具source/raw receipt的可驗證rows。
- CP4 source/platform acceptance不等於consumer cutover；existing dashboard/summary最後仍必須在CP7改讀共同resolved projection。
- Public request-time第一個capability是TWSE MIS actual last trade，不是minute bar；quote/depth/auction/volume各自保留component與lineage，不允許snapshot-to-bar masquerading。
- `intraday.py`相容輸出保留bars與current observation，但current trade只能由platform cache result投影，不能直接fetch MIS或改寫NStock/Yahoo歷史點。
- Public MIS缺少正式endpoint SLA文件，僅作single-symbol bounded personal-research best effort；未取得TWSE同意前不宣稱raw/value-added資料可向外傳播。
- CP5 source/platform acceptance與active-session runtime acceptance分開；recorded actual row可證明資料語意與pipeline，不能替代live-session provider/runtime證據。
- CP6 catalog/health完成的定義是「每個dataset都能被共同contract誠實描述與查證」，不是把lineage gap或missing data改名為ready。
- `tw.technical.daily`是resolved daily OHLCV的versioned derived projection；不另建indicator value table，避免第二份無lineage的市場事實。
- Backend research indicators是正式truth owner；frontend只在authority/parameter contract吻合時直接顯示backend值，local math降為`presentation_only` compatibility且不得回流AI/MCP。
- Production rollback首選保留additive 0067/0068 schema並回退application build；已有新canonical writes後downgrade會移除直接lineage欄位，不作首選。Migration downgrade只作emergency compatibility proof。

## Known issues / risks

- Worktree有其他進行中變更；後續source implementation必須exact-scope並避開M5/US OHLCV owner。
- 既有02A v1 DataRequirement/ProviderDescriptor/Control Plane仍只支援有限能力與Research purpose；CP1以additive v2 adapter承接，production route尚未切換。
- Full-market EOD reconcile目前仍由legacy `refresh_source()`負責fetch/parse/persist；CP3需讓Registry runtime operation擁有plan、postcondition與checkpoint，但保留既有job/API compatibility。
- CP2已證明daily schema足以保留source/raw/fetched/hash/quality與idempotent row；尚未處理historical correction revision history，若後續需求不能由append-only receipt重建才重開migration decision。
- `indices.py`既有summary/refresh仍包含legacy provider orchestration；CP4新增路徑不會假裝它已消失，CP7/CP8必須以guard/snapshot逐步切換與移除。
- TWSE MIS public endpoint沒有正式SLA且對外傳輸有授權邊界；目前只允許single-symbol bounded personal-research use，provider變更時必須truthful fail而非自動轉大量fallback。
- Durable dataset convergence可能發現真正schema/lineage缺口；未有證據前不預先建立migration。
- Shared worktree的legacy dark-boundary full regression曾有2項非本任務失敗；本輪CP2 scoped gate全綠，但仍不得擅改US/M5其他任務baseline。
- CP2的source-only proof已由CP8 production DB/runtime adoption補上；仍不得把completed-session／post-close evidence延伸成active-session F-07。
- Production EOD在2026-08-25 19時的唯讀證據仍為partial；TWSE 1086檔中1085 stale、1 missing。不得在未執行explicit bounded reconcile前改寫成healthy。
- TW full-market repair目前仍透過legacy `refresh_source()` compatibility port執行bulk fetch/parse/persist；CP3已把plan/bounds/postcondition/health ownership收回Registry lifecycle，但bulk transaction port本身仍是後續legacy-removal debt。
- Production DB已在0068；5,170筆legacy index rows與既有quote rows沒有被假造lineage。只有新platform transaction rows可被canonical repository接受；latest quote health目前仍truthful `lineage_incomplete`。
- TAIEX official source在bounded 2026-08-25 request只回到2026-08-24；Data Core沒有接受backdated retry冒充expected date，需後續釐清官方資料發布時點／endpoint coverage。
- Official breadth current production projection仍不完整；UI/MCP保留missing/partial，不以sample movers代替。
- CP5 active-session live provider smoke尚未執行；F-07維持pending，不能把收盤後recorded replay或policy rejection標為live acceptance。
- 2026-08-27確認CP5 post-close policy原本刻意zero-I/O，造成13:30至official daily發布前缺少session-final projection；source contract已修正，但正式runtime尚未採用，不能以source test冒充production pass。
- Existing quote snapshot schema已由PCF0證明足以重建post-resolution `confirmed_at`；若未來要保存多版candidate revision或durable reconciliation事件，再以新contract evidence重開migration decision。
- TW Data Core範圍的dark-boundary drift已由本任務successor checkpoint收斂；共存的US integration allowlist修改未納入本checkpoint。舊M5 checkpoint仍保持歷史不可變。

## Next step

- CR0～CR6與CR7 source regression已完成；取得明確重啟授權後，再使用existing launcher lifecycle進行CR7 scoped runtime／MCP adoption與outward probe。
- CR8在下一個可用台股交易日依真實時序驗證3711、TWSE／TPEx、official EOD reconciliation與可見「今日」UI。
- F-07 active-session live acceptance仍獨立排程；不得用post-close finalization evidence替代。KGI、depth／auction、realtime lease與M5不納入本corrective extension。

## 2026-08-27 K線／成交量／技術／EOD cleanup source implementation

### 已完成

- `MarketOhlcChartRead`／台股個股 OHLC service 新增 `volume_unit`、`volume_semantics`、`volume_status` 與 `latest_finalized_data_date`；個股正式 contract 為 shares，index 未提供時維持 `None/not_provided`。
- Normal K線在 shares contract 下改用整數股數 formatter；professional chart原本即用 raw volume。SSR initial response與後續 chart reload共用同一 volume unit state。
- Daily technical report 已移除 current price × finalized indicators hybrid：rows/title/score/badges固定 finalized decision state；current state改由 `current_partial_indicator`完整計算，並新增 `current_observation`、decision/current state time/status與decision usability。
- Post-close有session-final時，即使 intraday series最後停在11:49，`price_context/current_partial_indicator/current_state`改用session close；正式日線 decision state不變。
- AI Taiwan compact technical projection新增 latest finalized close、decision state與current observation，保留 `decision_usable=false`，MCP／consumer不需自行推導。
- Frontend daily indicator series合併backend technical report的current partial point；projection scope同時檢查chart date coverage、active indicator與parameter contract，custom/local-only projection會標`mixed`。
- EOD coverage detail新增TWSE／TPEx venue breakdown；repair provider result新增raw receipt、fetched time、duplicate、observed dates、expected-date observation、before/after coverage、dataset advancement與venue postcondition。
- Fetch/parse成功但資料仍是previous date或duplicate時不再增加repair succeeded count或更新last success；job final postcondition仍依重新讀取coverage判斷。

### 驗證證據

- Targeted backend：85 passed；擴大 lifecycle/AI/quote regression：308 passed + 26 subtests；OHLC/technical/EOD/AI regression：180 passed + 8 subtests。
- Frontend：`npm run lint -- --quiet` passed；`npm run build` passed，包含Next.js production compile與TypeScript。
- 最終 architecture guard passed（26 actual violations全部由26項declared debt覆蓋）；architecture pytest 17 passed。
- Safe backend profile：architecture checker、architecture pytest、compileall passed；full pytest第一次collection被既有受保護目錄`backend/tests/tmpla6tzx59`擋下。
- 排除該目錄後2,402 tests跑到100%，但pytest teardown又因受保護basetemp無法輸出正式summary；過程中的existing mixed-worktree failures已單獨重跑為15 failed／62 passed／1 temp-permission error，集中於Atlas fixture venue、DB model count snapshot、KGI stream schema、freeze hash、current index/intraday既有cutover、US OHLC continuity，與本次modified files／targeted surfaces不同。
- `git diff --check` passed（只有既有LF/CRLF提示）。
- 直接讀目前production SQLite的3711 source smoke（無provider IO、無runtime重啟）：finalized decision `2026-08-26 / 592`；current provisional `2026-08-27 / 605 / 11,106,000 shares`；`technical_price_basis=session_close_provisional_daily_bar`；chart `latest_finalized_data_date=2026-08-26`且latest provisional point為605。EOD coverage仍truthful partial：TPEX 861/887 current、TWSE 0/1086 current。

### 尚未宣稱完成的 gate

- 尚未重啟 production backend/frontend；目前8400／3000仍是既有runtime，不能把source/build結果冒充runtime adoption。
- visible 3711 UI、HTTP／MCP runtime payload與下一次official daily provider publication仍需使用existing launcher完成adoption後驗收。
