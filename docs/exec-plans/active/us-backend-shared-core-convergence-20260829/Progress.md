# 美股 Backend Shared Core 收斂進度

## Status

- Current phase：`m9_4_4_0_source_consolidation_passed`
- Task status：`SOURCE_CONSOLIDATION_PASSED_RUNTIME_PENDING`
- Last updated：2026-08-29 Asia/Taipei
- Source baseline：branch `codex/tw-etf-provider-normalization`，HEAD `f8085f5ef607b1cda4196dc863b652918f86b5fc`
- Authorization：2026-08-29 使用者已核准 M0–M9.0，並授權precommit source closeout、正式OMI restart、read-only DB、AAPL／TSM／`^SOX` bounded provider I/O與production DB writes、後續bounded priority／full-market、正式MCP lifecycle及commit／push／release。2026-08-29另行授權加入Alpaca SIP Historical Daily P2與Twelve Data Quote／Intraday source-ready基礎，用新P2重新解除AAPL provider blocker。所有授權仍受credential／entitlement、quota、target、milestone與stop condition約束。

## Milestone status

| Milestone | Status | Evidence / blocker |
| --- | --- | --- |
| M0 Approval / baseline | `source_passed` | M0 targeted baseline：143 passed、4 pre-existing failed；無provider/DB/runtime side effect |
| M1 Shared Contract Gate | `source_passed` | refresh coverage/cursor、series coherence、dispatcher與per-capability rollout完成；66 Shared tests與41 TW affected tests通過 |
| M2 US V2 Acquisition | `source_passed` | Yahoo/Alpha Vantage V2 descriptors與fixture-bound canonical acquisition完成 |
| M3 Repository / Transaction | `source_passed` | raw receipt + canonical bar atomic transaction、cache-only lineage repository及additive migration完成；production已採用`20260829_0073` |
| M4 Daily Platform / GET purity | `source_passed` | Gateway-first read/refresh、US expected state/identity、GET cache-only boundary與outward `point_count`完成 |
| M5 TSM + `^SOX` slice | `source_passed` | TSM shares volume、`^SOX` not-applicable volume、fallback/conflict/stale fixture slices通過 |
| M6 Priority / Full-market | `source_passed` | priority與full-market接同一platform；US typed lifecycle port移除Shared EOD的US service/calendar/rollback debt |
| M7 Consumer convergence | `source_passed` | API／AI／technical／valuation／overnight／ADR／cross-market與freshness改用canonical platform；raw consumer import guard已建立 |
| M8 Source closeout | `source_passed` | manifest source binding、acceptance artifact與architecture freeze完成；runtime已adopted但current truth需在M9.0修正 |
| M9.0 Rollout stabilization | `accepted` | 最終restart後direct/proxy health、OpenAPI、三檔cache-only GET、unknown identity 404與read-only scheduler/DB inventory全數通過 |
| M9.0.5 Pre-live semantic / owner closeout | `source_passed` | semantic quality／refresh axes、canonical repair owner、candidate store removal、Chart／field parity完成；256 tests + 27 subtests通過 |
| M9.0.6 Source closeout runtime adoption | `accepted` | 官方tray `RestartServices`採用本輪source；root／`.venv`／8400／3000、direct/proxy/UI、OpenAPI與DB revision一致，無新增US job或US raw receipt |
| M9.1 Three-symbol live seed | `partial_at_index` | AAPL與TSM均由Yahoo P1後Alpaca P2補至2026-08-28；`^SOX`只呼叫Yahoo一次且因8/28 malformed維持8/27，planner沒有誤送Alpaca stock endpoint |
| M9.1A Free provider contract / inventory | `source_passed` | Daily inventory改由V2 descriptors投影；resource-level health、typed failure與安全auth metadata完成；Shared／TW affected regression通過 |
| M9.1B Alpaca SIP Daily P2 | `source_passed` | bounded SIP client、canonical adapter、STOCK／ETF eligibility、Yahoo short-circuit與malformed->Alpaca persist／reread／Resolver fallback均由fixture驗證；index negative gate通過 |
| M9.1C Alpaca bounded live AAPL | `accepted` | credential／SIP entitlement通過；receipt `116862`保存AAPL Alpaca final observed-volume bars，8/28 close=319.7，mandatory reread由Shared Resolver選為fallback |
| M9.1D Twelve source-ready | `source_ready_live_quote_accepted` | AAPL Quote live canonical probe通過並保留`PARTIAL_US_MARKET_VOLUME`；`^SOX` 1day probe回HTTP 404，因此不升格Daily/index production |
| M9.1E Alpha Daily cutover | `accepted_for_stock_etf` | active／candidate descriptors、manifest與legacy projected priority固定Yahoo→Alpaca；negative guard禁止Alpha Daily重返production inventory，Fundamentals／Corporate Actions與quarantined rollback parser保留 |
| M9.2 Restart readback | `partial_index_fallback_missing` | 正式launcher重啟後AAPL／TSM均8/28 current且direct/proxy一致；`^SOX`持久化8/27 stale truth可重建但缺8/28 index fallback，故三檔fresh gate不成立 |
| M9.3 Product parity | `accepted_for_aapl_tsm_partial_for_sox` | AAPL REST／proxy／running OMI MCP／Frontend一致呈現Alpaca、8/28、current；TSM REST/proxy同樣current；`^SOX`一致呈現Yahoo 8/27 stale、decision unusable |
| M9.3A Candidate history coverage | `accepted` | typed coverage intent、Resolver/Gateway coverage eligibility、`us.ensure_daily_history_coverage`、Index applicability、pagination fail-closed與legacy quarantine完成；AAPL／TSM各以1次Alpaca call取得537根canonical bars，restart後direct/proxy 260/260 complete且cache-only零I/O |
| M9.4 Precommit staged-tree acceptance | `blocked_by_index_and_mixed_tree` | stock／ETF source/runtime/live/product已通過，但`^SOX` index fallback與mixed worktree dependency closure未完成；不得把整個ahead-6 branch或worktree冒充US Daily isolated staged tree |
| M9.5 Commit / push / release checkpoint | `blocked_by_m9_4` | 本輪未commit／push；target/upstream/ancestry/version與isolated staged closure未建立 |
| M9.6 Closeout | `partial_index_provider_gap` | AAPL／TSM與Yahoo→Alpaca cutover完成；`US_DAILY_PRECOMMIT_CLEAN`與三檔canary Product gate仍受`^SOX`可用index fallback缺口阻擋 |
| Deferred priority / full-market | `pending` | 已授權但不是Daily precommit blocker；US scheduler維持paused直到另立bounded rollout |

## Completed

- 將使用者原始附件明確區分為architecture proposal，不當成直接執行指令。
- 讀取root／backend／Shared Market Data Foundation scoped instructions與current architecture/product truth。
- 對照current source確認：
  - Shared Gateway/Resolver/Quality與V2 contracts存在，但durable status仍為partial。
  - US manifest仍`production_binding_available=False`、contract version null、handoff G0。
  - `RefreshRequirementV1`缺reason/coverage/cursor。
  - Dataset lifecycle尚無共用executable dispatcher/result/postcondition owner。
  - Persisted bar series尚未驗證provider/source coherence。
  - `USDailyPrice`與candidate reader無法保存／重建完整canonical lineage。
  - GET OHLC仍公開並轉送provider/acquisition controls。
  - `^SOX` identity與volume applicability需要正式contract。
  - AI五日stale、payload-exists=current與valuation Yahoo preference仍存在。
- 完成read-only architecture preflight，提出Shared Contract Gate、Gateway-first control flow、mandatory lineage decision、index applicability與GET purity修正。
- 建立本active exec plan的`Prompt.md`、`Plan.md`、`Progress.md`，所有implementation milestone維持`pending_approval`。
- 2026-08-29 使用者核准依長專案完成M0–M8全部Source工作，並明示由使用者自行重啟檢查；M9與外部side effects仍保持未授權。
- M0 targeted baseline從`backend`使用root venv執行147個Shared Core／US tests：143 passed、4 failed。
- M1完成additive Shared contract、provider/source/authority series coherence、typed operation dispatcher與per-capability rollout；TW affected regression保持相容。
- M2/M3 Source階段完成V2 daily descriptors、雙provider canonical acquisition、raw receipt/full lineage schema、atomic transaction、cache-only candidate repository與Alembic `20260829_0073`定義；當時僅在in-memory／isolated SQLite測試，後續正式restart已套用production migration。
- M4/M5完成`USDailyOhlcvPlatform`、market-owned expected state與identity、GET purity、TSM／`^SOX` applicability及fallback/conflict/stale垂直切片。
- M6完成US full-market typed port、Shared job/scheduler composition binding、priority explicit bounded repair與dataset operation binding；scheduler設定未啟用。
- M7完成public chart/history、AI compact context、agentic refresh、financial valuation、technical／Radar、overnight impact、ADR／cross-market與regional freshness的canonical consumer cutover；固定天數與payload-exists=current不再是US daily authority。
- M7補上candidate receipt `available_at` cutoff，歷史研究不讀取當時尚未取得的backfill receipt。
- M8將integration manifest切至canonical candidate reader factory並標記`US_DAILY_BACKEND_V1_SOURCE_ACCEPTED`；`production_binding_available=True`只代表source binding存在，limitations明示effective rollout off及Runtime／Live／Product pending。
- M8新增`us_consumer_canonical_daily_access` architecture rule，AI／market／watchlist production consumer直接import `USDailyPrice`會fail；legacy service/provider diagnostics留在US-owned quarantine，不是production selection owner。
- M9 runtime adoption：使用者於2026-08-29 13:07自行透過正式tray lifecycle重啟；launcher證明repo root、`.venv` Python、backend 8400、frontend 3000，API/UI均回OK。
- Startup已套用Alembic `20260826_0072 -> 20260829_0073`；read-only DB probe確認current revision與九個lineage/applicability欄位存在。
- Direct／frontend proxy readiness皆為`ready`；health顯示US effective mode=`canary`、allowlist=`AAPL`、max symbols=5。
- 完成`OMI_US_Daily_Mainline_Closeout_and_Branch_Convergence_20260829.txt` read-only preflight；確認方向正確，但原順序缺M9.0且過早退役Daily canary/shadow。
- Read-only source/live review確認：public Daily read對所有symbols直接走canonical Platform，現有AAPL allowlist不限制outward cutover；REST response model會丟棄部分selection/limitation facts；refresh route接受但忽略provider參數。
- Read-only caller inventory補出quality repair、history repair與`ensure_history` legacy write seams；`candidate_store.py`仍有test caller，Daily／Intraday canary-shadow共檔。
- Read-only DB確認AAPL 2,659、TSM 2,662、`^SOX` 2,569筆legacy rows，但三者canonical lineage均為0；同時背景US full-market job曾持續寫入其他canonical symbols，使三檔acceptance baseline移動。
- 使用者授權後，在ignored本機`.env`設`SCHEDULER_EOD_COVERAGE_MARKETS=TW`並透過正式launcher restart；重啟後direct/proxy readiness均ready，runtime設定讀回TW，沒有建立新US full-market job。
- 將Daily收尾修正版排成M9.0–M11：先rollout/contract補洞，再三檔live、quality、product parity、restart gate、priority、full-market，最後才清legacy/debt並封存。
- M9.0新增`daily_rollout.py`作US market-owned設定adapter，重用Shared `CapabilityRolloutState`：所有read維持canonical cache-only，acquisition則依`off/shadow/compare/canary/on` fail closed；AAPL canary不再容許TSM或`^SOX`refresh。
- `USDailyOhlcvPlatform.refresh()`在identity lookup／Gateway／provider I/O前驗證target；US full-market EOD scheduler只有rollout=`on`才可排程，避免canary狀態先建立全市場error job。
- REST chart schema新增expected/latest trade date、selection/fallback、facts/decision usability與limitations；refresh response新增persistence/postcondition/raw receipt facts。Deprecated provider query對非`auto`明確回400，不再靜默忽略。
- 本次未restart、未provider I/O、未寫production DB；本機`.env`的TW-only scheduler pause未改動。
- 使用者於14:17透過正式launcher重啟；launcher log證明repo root、root `.venv` Python、backend 8400、frontend 3000與API/UI OK。Direct／proxy health均回傳M9.0新增rollout欄位。
- Runtime rollout facts：read binding=`canonical`、acquisition mode=`canary`、scope=`canary_targets`、target count=1、configuration=`valid`；direct／proxy readyz均為runtime/database `ok`。
- AAPL／TSM／`^SOX`合法cache-only GET direct與proxy逐欄一致；expected date=`2026-08-28`，因尚無canonical live seed而truthful回point count 0、freshness missing、facts/decision unusable與`READ_POLICY_FORBIDS_ACQUISITION` limitation。
- Read-only DB query以`mode=ro`與`PRAGMA query_only=ON`確認revision=`20260829_0073`；restart後EOD job只新增TW，最近US full-market job仍是pause前舊紀錄，沒有新US job。
- Probe command曾因PowerShell variable interpolation送出malformed symbol path；此操作未觸發provider或DB write，但揭露unknown canonical identity會逸出`LookupError`成500。Public refresh/history/chart現已統一在router轉成404，並加入三route parameterized regression。
- 使用者於14:32再次透過正式launcher重啟；repo root、root `.venv`、backend 8400、frontend 3000與API/UI OK均由launcher log確認。Direct／proxy health與readyz逐欄一致。
- 最終runtime readoption：UNKNOWNZZZZ在direct與proxy均回結構化404；AAPL／TSM／`^SOX`在兩條路徑均回200、point count 0、expected date=`2026-08-28`、freshness missing、facts/decision unusable與`READ_POLICY_FORBIDS_ACQUISITION`，未偷觸發refresh。
- Runtime OpenAPI確認refresh provider parameter為deprecated、default=`auto`，chart與refresh additive parity fields均存在。Read-only DB以`mode=ro`、`query_only=1`確認revision=`20260829_0073`；14:32 restart後只新增TW job 8101，最新US full-market仍是restart前job 8084。
- 將`OMI_US_Daily_Precommit_Final_Closeout_20260829.txt`視為proposal evidence後，逐項對照current source、typed contracts、callers與tests；沒有把附件中的步驟直接當成execution instruction。
- 以pure-function probe重現兩個既有測試未捕捉的contradiction：technical payload明示`missing`／facts false／decision false，generic builder卻輸出`available/ready`且facts/decision true；Daily missing payload的`refresh_recommended=true`被輸出為false。
- Caller／owner inventory確認public diagnostics repair仍經legacy `repair_us_ohlc_history()` -> `refresh_us_daily_prices()`形成第二個fallback／write owner；`candidate_store.py` production caller為0但test contract仍存在。
- Outward inventory確認Chart仍重算freshness、current與refresh recommendation；REST chart schema與consumer parity尚未完整保留`selected_event_at`。Request-specific timeframe coverage可留在Chart，但不能覆寫canonical dataset truth。
- 依驗證結果把後續順序改為M9.0.5 Source semantic／owner closeout -> M9.0.6 runtime adoption -> M9.1三檔live seed -> M9.2 restart readback -> M9.3 Product parity -> M9.4 staged-tree -> M9.5 publication -> M9.6 closeout。Priority/full-market改為不阻擋precommit的deferred rollout。
- M9.0.5 generic quality改為只接受typed `payload.quality` semantic cap：missing／stale／facts／decision會限制generic inference，但realtime policy仍保留較高authority；recommendation、allowed、requested與possible不再互相覆寫。
- Diagnostics OHLC repair job改由`USDailyOhlcvPlatform`執行bounded acquisition/persistence/reread；quality repair的refresh也改走canonical wrapper。Legacy service fallback不再有production job／router caller。
- `app.us_market.market_data.candidate_store`已移除，Foundation seam改以negative import/file guard保護；canonical candidate truth只剩`USDailyBarRepository`。
- Platform現在擁有Daily freshness、current、refresh recommendation與usability；Chart只保留request coverage／continuity／aggregation，新增`request_coverage_status`與`selected_event_at`，Frontend type同步完整selection／quality fields。
- 新工程文稿核准後只補上一個Yahoo-first retry入口與stale contract parity regression；沒有放寬原本的AAPL stop rule、沒有Alpha fallback、沒有觸碰TSM／`^SOX`或priority/full-market。
- `daily.ohlcv` canonical typed fields現在會完整進入AI capability selection；generic quality只在`daily.ohlcv`且存在明確typed freshness／usability facts時採用top-level semantic truth，避免影響其他market capability。
- Tracked Daily repair result新增truthful `inserted_count`／`updated_count`／`unchanged_count`，來源直接取自Shared `PersistenceSummary`；已完成的job 8128不回填或推算舊result。
- 官方generator已同步repo與standalone OMI Search `public_contract_snapshot.json`，digest=`107685377b25ccd1bcca72f4273a321d2aeeb4f15bbdbd172725622412f1321b`。
- 唯一追加的Yahoo repair job 8128實際`provider_call_count=1`、`providers_attempted=[yahoo_chart]`、`fallback_used=false`；raw receipt `116418` HTTP 200但8/28 `close=null`，postcondition truthfully failed，latest仍為8/27。
- 透過正式OMI launcher重啟後，8400／3000 direct與proxy均採用新stale contract；透過Control Center只重啟`omi_search`，build ID更新為`df381534481ac358`，upstream與tunnel ready。
- AAPL running parity已驗證：REST與proxy均回186點、Yahoo selection、`COMPLETED_SESSION_STALE`、facts usable=true、decision usable=false；decision v4與MCP quality均為stale/limited，`data.freshness.is_current=false`且`stale_datasets=[daily.ohlcv]`。
- Frontend可見DOM顯示AAPL資料日`2026-08-27`、`180 根 K 線`、`已解析日線不足或過期，技術判斷暫不可用。`與`過期`，未把舊資料呈現為可用技術判斷。

## Validation evidence

- Read-only architecture checker：`Architecture guard: PASS`，`Actual violations: 26`，`Declared debt: 26`。
- Baseline worktree：branch ahead 6，存在大量modified/untracked TW、US、architecture與其他工作；本輪沒有revert或覆寫既有檔案。
- Source implementation前baseline未執行runtime smoke、provider call、正式DB mutation或migration apply。
- 文件Tier 0驗證完成：三檔UTF-8讀回無replacement character、皆有結尾換行、無trailing whitespace；必要章節與`pending_approval`狀態存在。
- M0 targeted pytest：143 passed、4 pre-existing failed。失敗分別為dirty worktree造成Foundation checkpoint hash漂移、US outward projection缺`point_count`、以及兩個OHLC expected-session/coverage既有契約不一致；後3項納入M4/M7修正，checkpoint hash測試只作dirty baseline記錄，不更新歷史artifact冒充驗收。
- M1：66 Shared contract/dispatcher/rollout tests passed；41 TW affected regression passed。
- M2–M5：descriptors、acquisition、transaction、repository、migration、platform、identity、GET/outward及vertical slice targeted suites皆通過；其中lineage migration isolated SQLite test通過並產生69則既有adapter deprecation warnings。
- M6：`test_eod_coverage.py`、scheduler、priority、dataset lifecycle、registry共45 passed；architecture guard PASS，actual/debt由26/26降至22/22。
- M7 consumer matrix：AI/context/cross-market/overnight/ADR與canonical repository共111 passed；ADR + cross-market point-in-time regression 28 passed。
- M8 primary targeted matrix：350 passed；另有2個failure，其中dark-boundary authorized import清單已隨manifest收斂修正，剩餘Foundation歷史hash checkpoint為M0已記錄的dirty-worktree baseline mismatch，不用更新歷史artifact冒充通過。
- Architecture：guard PASS，22 actual／22 declared；architecture + US boundary tests 24 passed，另加dark-boundary import test共25 passed。
- 最終Source acceptance matrix：353 passed、451個既有SQLAlchemy／sqlite3 adapter deprecation warnings；涵蓋architecture、AI/API、US acquisition／lineage／transaction／platform、EOD／priority、ADR／overnight／cross-market與relation suites。
- Repo標準`run-safe-validation.ps1 -Profile backend`：architecture checker passed、architecture pytest passed、compileall passed；backend全量pytest跑至100%，但共享dirty baseline仍出現與本計畫無關的AI catalog hash、Foundation hash、台股／KGI／MCP等failure，且pytest session cleanup被既存`.tmp` ACL拒絕而無法產生可信總結。本計畫涉及的legacy fixture failures已修正並由353項矩陣重跑通過。
- Runtime identity：launcher log記錄project root=`C:\project\Open Market Intelligence`、Python=`.venv\Scripts\python.exe`、backend child及uvicorn PID；`netstat`確認127.0.0.1:8400與:3000 listeners，受限shell的`Get-NetTCPConnection` ACL拒絕不當成ownership mismatch。
- Runtime cache-only smoke：TSM、`^SOX`、AAPL direct GET與TSM frontend proxy均回200及新canonical response shape，但`point_count=0`、`freshness=missing`。Read-only DB probe顯示既有TSM 2,662筆／`^SOX` 2,569筆legacy rows的canonical lineage count均為0；Resolver正確fail closed，未把舊row偽裝成canonical evidence。
- 2026-08-29 Daily closeout preflight：architecture guard PASS，22 actual／22 declared；三檔chart/research/technical共9次cache-only GET均HTTP 200且truthful missing。
- Scheduler pause：job 8084最後為US full-market `error`、41/250；launcher restart後新EOD job只包含TW，`new_us_after_pause=0`。舊job紀錄未改寫。
- Restart proof：launcher在13:48停止舊frontend/backend並啟動新PID；backend `8400`與frontend `3000` listeners更新，direct／proxy readyz均`ready`，runtime/database=`ok`。
- M9.0 primary targeted：rollout/platform/vertical slice/system health/API purity/scheduler/architecture boundary共35 passed；Shared Gateway/integration/outward/EOD/dataset跨邊界矩陣84 passed。
- M9.0 architecture：checker PASS，22 actual／22 declared；architecture pytest passed；backend compileall passed。
- M9.0 OpenAPI source probe：refresh provider parameter為deprecated；chart與refresh要求的10／6個additive parity fields均存在，missing field set皆為空。
- M9.0 runtime OpenAPI probe：正式8400 runtime同樣回provider deprecated，chart／refresh parity missing field set皆為空。
- M9.0 unknown identity hardening targeted matrix：35 passed；14:32正式runtime已採用，direct／proxy均回404。
- M9.0 full backend：排除既有不可讀`backend/tests/tmpla6tzx59`後收集2505 tests並執行到100%，輸出無test failure；pytest最後在清理`.tmp/pytest-safe-validation-*`時遇既有Windows ACL `PermissionError`，故wrapper exit 1，不能宣稱full profile clean pass。未刪除目錄或變更ACL。
- Precommit focused matrix：`test_us_daily_ohlcv_platform.py`、`test_us_ohlc_contract.py`、US architecture／Foundation seam、AI capability與outward contract共`101 passed, 12 subtests passed in 6.36s`。
- Precommit negative semantic probe：technical missing實際輸出`status=available`、`status_class=ready`、facts／decision usable=true；Daily missing實際輸出`status=available`、`freshness=available`、`refresh_recommended=false`。這是明確coverage hole，不以既有green tests冒充已修正。
- Precommit architecture checker：PASS，`Actual violations: 22`、`Declared debt: 22`。
- Precommit runtime read-only probe：ready/runtime/database均ok，project root與`.venv`正確；Daily read binding=`canonical`、acquisition=`canary/canary_targets`、target count=1、configuration valid。未做restart或side effect。
- Precommit DB read-only baseline：migration=`20260829_0073`；AAPL 2,659、TSM 2,662、`^SOX` 2,569筆legacy rows，canonical lineage均為0；三檔cache-only read仍truthful missing，expected date=`2026-08-28`。
- M9.0.5 focused regression：AI quality／v4、US Platform／outward／architecture、job retry與transaction boundaries共`256 passed, 27 subtests passed in 29.61s`。
- M9.0.5 targeted repair／repository matrix：`36 passed in 7.19s`；legacy diagnostics fixture只走canonical Platform並truthfully保留partial postcondition。
- M9.0.5 architecture checker：PASS，`22 actual / 22 declared debt`；沒有新增allowlist或debt。
- Python compileall首次因既有`backend/app/us_market/__pycache__` ACL拒絕無法寫`.pyc`；改用獨立`PYTHONPYCACHEPREFIX`後affected modules `py_compile`通過，未修改ACL或刪除目錄。
- Frontend targeted ESLint與`tsc --noEmit`通過。
- M9.0.6 refresh outward contract補上`selected_event_at`、`external_call_count`、`providers_attempted`與`resource_attempts`，targeted Platform／OHLC tests `8 passed`，Frontend ESLint／TypeScript通過。
- M9.0.6於15:30透過既有tray owner的官方`RestartServices` lifecycle重啟；launcher證明repo root、root `.venv` Python、backend `8400`、frontend `3000`及API/UI OK。
- Restart後direct OpenAPI已出現本輪refresh／chart欄位；direct與frontend proxy chart都維持cache-only missing truth，UI health回報proxy target=`http://127.0.0.1:8400`。
- Read-only DB確認migration仍為`20260829_0073`、US job count仍235、AAPL／TSM／`^SOX` canonical row仍為0。Restart後新增34筆raw receipt全屬既有TW scheduler（nStock 32、TWSE 1、TPEx 1），US-like raw receipt為0；因此M9.0.6未把背景TW工作誤算為US side effect。
- M9.1 AAPL explicit refresh只送出一次request，實際使用Yahoo + Alpha Vantage共2/2 provider calls。Yahoo寫入raw receipt `116371`並將186筆rows補成完整lineage，Alpha Vantage失敗；mandatory reread回`partial_success`，不能建立Live gate。
- Live evidence揭露Gateway reread cutoff bug：receipt在request開始後數秒取得，原邏輯卻以request開始時間做`available_at` cutoff，導致同一operation剛commit的receipt不可見。已將post-acquisition reread cutoff只推進到本次最新receipt時間，歷史as-of read不變；相關矩陣`290 passed / 27 subtests`、architecture guard與Frontend ESLint／TypeScript通過。
- Live response另揭露`inserted_count`／`updated_count`誤把written／unchanged當成insert／update；Shared `PersistenceSummary`以additive exact counters補強，US transaction與REST／Frontend新增truthful `unchanged_count`，未改既有其他transaction default。
- 修正後正式restart採用source；AAPL direct／proxy cache-only read一致為point count 5、expected=`2026-08-28`、latest=`2026-08-27`、freshness=`stale`、facts usable=true、decision usable=false、refresh recommended=true，且未新增US raw receipt或US job。
- Receipt `116371`原始Yahoo payload的8/28 bar有open／high／low／volume但`close=null`；canonicalizer正確以`MALFORMED_BARS_SKIPPED`拒絕，不能用0、legacy row或推算值補齊。AAPL每檔budget已耗盡，依plan立即停止，TSM／`^SOX` allowlist未擴充、provider calls為0。
- Stale parity新增regression先紅後綠：typed Daily quality原本被降成`available`，v4 projection也遺失`expected_trade_date`；修正後capability／decision targeted為`131 passed`，完整exact-scope matrix為`396 passed, 52 subtests passed`。
- US repair persistence counter regression與architecture boundary共`10 passed`；architecture checker維持PASS、`22 actual / 22 declared debt`，沒有新增debt或allowlist。
- Repo標準backend profile的architecture checker、architecture pytest與compileall通過；全量pytest仍受既有不可讀`backend/tests/tmpla6tzx59`、dirty baseline的financial/KGI/TW等failure與cleanup ACL影響，不能宣稱full suite clean。受本輪影響的related rerun為`198 passed, 31 subtests`，唯一剩餘failure是既有financial freshness expectation。
- AAPL Yahoo-only retry job 8128：external calls=1、raw receipt=`116418`、HTTP 200；8/28 open/high/low/volume存在但close仍null，canonical full-lineage latest維持8/27。依stop rule沒有第二次retry、Alpha、TSM、`^SOX`或full-market call。
- Restart後direct與frontend proxy REST逐欄一致：expected=8/28、latest=8/27、stale、Yahoo、186 points、facts=true、decision=false、refresh=true、coverage=partial。
- Direct與frontend proxy `omi.decision.v4`逐欄一致：Daily stale/facts-only、quality stale/limited、`data.freshness.is_current=false`、`stale_datasets=[daily.ohlcv]`、`temporal_status=stale`；兩次cache-only decision read前後raw receipt/job/US job計數不變。
- Standalone OMI Search source validation為`37 tests OK (skipped=1)`與syntax OK；restart後current與exact legacy `2025-06-18` handshake、resources、11 tools、代表性business call全數通過。
- AAPL MCP cache-only call回`omi.decision.v4`、`is_error=false`、Yahoo stale selection與decision unusable；呼叫前後`raw_fetch_result=116488`、`job_run=8141`、`us_job_run=236`完全不變。
- Browser DOM完成user-visible驗證：AAPL頁面明確顯示2026-08-27與過期／技術判斷暫不可用；另有一個既有初始請求失敗banner，本輪未修改或歸因為Daily stale contract。
- M9.1A／M9.1B完成單一Daily executable inventory、resource-level health isolation、typed auth／rate／plan failures、Alpaca SIP bounded client與canonical transaction integration；Yahoo完整expected session時P2零call，只有缺目標session或malformed時才繼續P2。
- AAPL 2026-08-28 fixture已重現Yahoo `close=null`，Alpaca final OHLCV經同一transaction持久化、mandatory reread與Shared Resolver選為fallback；`^SOX`不具Alpaca stock endpoint eligibility。
- M9.1D完成Twelve Data Quote／Intraday source-ready client與canonical fixtures，保留`PARTIAL_US_MARKET_VOLUME`，且沒有加入Daily production plan、manifest或Frontend／MCP provider selection。
- Free-provider最終targeted matrix為`85 passed`，AAPL／TSM fallback與HTTP health補強矩陣另為`16 passed`；US outward／AI／system health／TW affected矩陣為`255 passed, 27 subtests passed`；architecture checker維持PASS、`22 actual / 22 declared debt`。
- Credential presence probe只讀布林值：Alpaca key id=false、secret=false、Twelve=false、既有Alpha Vantage=true。依gate未送出Alpaca／Twelve live call、未寫production DB、未切換active tuple或移除Alpha Daily。
- Production DB以SQLite read-only URI驗證：AAPL／Alpaca rows=0；AAPL 2026-08-28符合raw receipt + final/corrected + observed volume的canonical rows=0；latest canonical trade date=`2026-08-27`。DB中雖有一筆8/28 Yahoo legacy row，但`raw_result_id`、finalization與volume_status皆null，不能冒充修復完成。
- Repo backend profile的architecture checker、architecture pytest與compileall通過；全量pytest最初被既有不可讀`backend/tests/tmpla6tzx59`擋在collection。精確排除後2,545 tests執行至100%，本次新增provider與所有US market tests均顯示通過；session cleanup仍被既有`.tmp` ACL中止摘要，單獨重跑出12個既有dirty-baseline failures與1個tmp ACL error，沒有落在本次Alpaca／Twelve／US Daily範圍。
- 測試credential只寫入Git ignored `.env`，驗證僅輸出configured布林值；Alpaca SIP bounded AAPL probe回2026-08-28 final OHLCV、observed volume與`ALPACA_SIP_DELAYED_EVIDENCE`，Twelve Data AAPL Quote live canonical probe回8/28且保留`PARTIAL_US_MARKET_VOLUME`。
- AAPL canonical repair receipts `116861`／`116862`；Resolver選Alpaca receipt `116862`，latest=expected=2026-08-28、close=319.7、volume=38,852,398、final/observed。TSM bounded live使用2 calls與receipts `116906`／`116907`，選Alpaca 8/28 close=417.52。`^SOX`只使用Yahoo receipt `116908`，8/28 malformed後latest=8/27，沒有呼叫Alpaca。
- Active/candidate Daily descriptors、integration manifest與legacy priority已切為Yahoo→Alpaca；Alpha Daily negative guard、provider policy、acquisition、transaction、repository、Platform、vertical slice、architecture與system health targeted matrix為`63 passed`，另一次primary matrix為`37 passed`；architecture guard PASS、`22 actual / 22 declared`。
- 19:56正式launcher restart採用root `.venv`、backend 8400與frontend 3000；direct/proxy readiness均ready，runtime/database均ok。三檔cache-only direct/proxy逐欄相等：AAPL／TSM為8/28 current Alpaca fallback，`^SOX`為8/27 stale Yahoo且decision unusable。baseline後新增34筆receipt全屬TW scheduler，沒有US provider receipt。
- Running OMI Search MCP `omi.decision.v4`對AAPL回current、Alpaca、fallback、decision usable、`data.freshness.current`，execution policy為allow_external_fetch=false；可見Frontend DOM顯示AAPL 2026-08-28、319.7與11根K線。技術面因同源history僅11根仍誠實顯示資料不足，這不被改寫成Daily freshness failure。
- M9.3A Source：Shared bar requirement與refresh coverage scope新增minimum bar intent；Gateway不再把fresh-but-short candidate當完成，Resolver對不足深度candidate fail closed。Dataset registry以同一`us.daily.ohlcv`宣告額外bounded operation `us.ensure_daily_history_coverage`，ordinary refresh仍只驗temporal postcondition；history operation則同時要求temporal與coverage postcondition。Priority與diagnostics repair均改走explicit history owner，GET仍維持cache-only。
- M9.3A quality：Index Daily的`volume_status=not_applicable`正式視為applicable success；Alpaca若帶`next_page_token`而本次2-call budget不能完成同一candidate history，必須partial/fallback，不得宣稱coverage complete；`legacy_compat.*`／`compatibility_adapter` lineage不得進production candidate selection。受影響consumer tests改用完整canonical test lineage，避免以synthetic legacy rows冒充production evidence。
- M9.3A Live／Runtime：依AAPL -> TSM順序各執行一次bounded operation，兩檔均只呼叫Alpaca 1次；各自DB為537根、範圍2024-07-10至2026-08-28，cache-only platform read為260 points、0 external call、persistence attempted=false。正式tray `RestartServices`後8400 direct與3000 `/omi-data` proxy皆回260/260、coverage complete、latest/expected=2026-08-28、Alpaca canonical source、current且decision usable。
- M9.3A validation：focused backend matrix `173 passed`；architecture checker、architecture pytest與compileall通過；Frontend TypeScript `--noEmit`與targeted ESLint通過。正式backend profile的全套pytest受到既有`backend/tests/tmpla6tzx59` ACL拒絕而在collection前停止；明確排除該暫存目錄後，本次legacy-quarantine受影響矩陣已收斂為107 passed，未以刪除來源不明目錄規避環境問題。

## Decisions made

- 新任務使用`docs/exec-plans/active/us-backend-shared-core-convergence-20260829/`；不續寫歷史`docs/agent-runs/us-market-data-core-integration-20260825/`作current truth。
- 美股接單一Shared Core；US只擁有市場特有identity、calendar、acquisition、persistence與research semantics。
- 在US canonical acquisition前先補Shared contract/lifecycle gaps；不以US-only compatibility層繞過。
- Source工作可分milestone推進，但production binding、runtime/live/product adoption要分別通過gate。
- Lineage storage不足已在M3以additive migration解決；existing legacy rows維持null lineage，不做偽造backfill。
- TSM + `^SOX`是acceptance targets，不是hardcoded special cases。
- 第一版daily backend與fundamentals/intraday拆線，避免同時重寫。
- Precommit negative evidence已證明quality與refresh recommendation不能延到live seed後才修；M9.0.5改為最先執行的Source gate。
- 三檔vertical slice建立`US_DAILY_CANARY_RUNTIME_LIVE_PRODUCT_ACCEPTED`；priority/full-market不是本次precommit blocker，改由closeout後的bounded rollout處理。
- Daily canary/shadow繼續作rollback evidence；只有priority/full-market evidence完成後才另案退役Daily部分，Intraday compare不受影響。
- US full-market scheduler在本task維持paused；TW與其他既有scheduler不因本任務一併停用。
- 使用者已授權OMI／MCP lifecycle、bounded external writes與publication；授權只解除permission blocker，不取代runtime、budget、staged-tree、target／ancestry與remote SHA gate，也不包含branch delete。
- AAPL final bar不完整時，stale-path Product acceptance可獨立完成，但不得把它升格為三檔Runtime／Live canary acceptance；M9.2、M9.4、M9.5與M9.6必須保持blocked/pending。
- `data.freshness.status`目前因self-capability缺失仍為`missing`；Daily的authoritative temporal facts則是`is_current=false`、`stale_datasets=[daily.ohlcv]`、`refresh_recommended=true`與`temporal_status=stale`。本輪不在aggregator重算第二份status。

## Known issues / risks

- Working tree高度混合，後續每個milestone都必須先做exact diff/hunk ownership與isolated validation；不可 broad stage/commit。
- Shared contract變更會影響TW caller，即使本任務只實作US，也必須跑TW regression並保持additive compatibility。
- 現有US source seam多為modified/untracked，未固定commit/source identity；Source acceptance前需重取baseline。
- Alembic `20260829_0073`已套production DB；existing rows保持legacy/null lineage的既定語意，不可回填假receipt。
- `^SOX`仍受真實provider coverage阻擋：Yahoo 8/28 close不完整，Alpaca stock endpoint不支援INDEX，Twelve Data `^SOX` 1day probe實際HTTP 404。不能把SOXX ETF替代為`^SOX`，也不能把兩檔stock成功升格為三檔fresh gate。
- AAPL／TSM Alpaca同源series已各補至537根並通過260-bar Product readback；其他symbol仍不得因GET或current short-circuit隱性fetch，需由bounded dataset operation逐標的補齊。
- Taiwan reference implementation目前仍有Runtime/Live/Product pending，不能當成US acceptance substitute。
- Full-market EOD與priority scheduler可能有重複owner/race；deferred rollout正式開始前不得enable新US scheduler。
- 首次M4 isolated platform測試只注入Yahoo fixture、遺漏注入Alpha Vantage failure；若本機當時存在API key，該次測試可能曾嘗試一次provider I/O。該測試只使用in-memory SQLite、未觸碰production DB/runtime；後續及最終測試已完整fixture-bound。
- Compatibility removal可能影響Frontend/API callers；M0 consumer inventory前不得做silent breaking change。
- `backend/tests/tmpla6tzx59`與pytest basetemp存在Windows ACL拒絕；未刪除或改權限，full-suite cleanup問題保留為repo環境債，不拿來取代Source acceptance evidence。
- Production migration只新增nullable lineage欄位，不偽造existing-row receipt；因此首次canonical live seed前，已cutover的daily consumers會truthfully呈現missing。需要bounded explicit refresh寫入新raw receipt／canonical lineage後才能進Product parity。
- ignored `.env.runtime` canary allowlist已擴為AAPL／TSM／`^SOX`且正式restart採用；`^SOX`被允許acquisition不代表它有第二個eligible index provider。
- Full-market scheduler雖已在本機paused，但`.env`是ignored local state；任何新host、清除`.env`或設定override都必須重新驗證，不能只相信文件。
- Existing focused tests全綠但未覆蓋已重現的negative semantic cases；修正後必須保留contradiction tests，不能只重跑原矩陣。
- Working tree仍高度混合且current branch ahead 6；commit/push雖已授權，仍必須exact-hunk stage、isolated staged-tree validation並證明target/upstream/ancestry，不能直接發布整個branch或worktree。
- Running MCP host與repo offline schema是不同truth layer；本輪已驗running OMI Search AAPL current read，但任何後續public contract變更仍需重做host adoption驗證。

## Next step

1. M9.3A已完成；維持AAPL／TSM cache-only 260-bar truth與US full-market scheduler paused。
2. `^SOX`保持Yahoo-only truthful stale，待取得真實可用的Index Daily fallback後另立bounded gate，不以ETF替代index身份。
3. 若進入commit／push，先建立US Daily exact-hunk isolated staged tree並重跑staged validation；不得提交整個mixed worktree。

## 2026-08-29 OMI 4.4.0 Daily contract closeout

- Yahoo Daily INDEX canonicalization不再把raw zero volume建成observed shares；`0`與`null`都輸出`not_applicable`，STOCK／ETF與intraday規則不變。
- `omi.decision.v4` normalized selection的`daily.ohlcv`／`daily.points` effective limit現在會提升US context既有`bars` bound；selection 260會使Platform與chart reader都讀260，且保持cache-only。
- Regression使用真正`build_query_plan()`產生selection，再驗證AAPL／TSM reader call bound；沒有在Frontend、MCP或consumer建立補資料邏輯。
- Source matrix、architecture與Frontend validation已通過；版本surface更新為4.4.0。
- Running Backend／MCP尚未restart採用本輪source；AAPL／TSM既有live/history evidence保留，`^SOX`仍為Yahoo-only truthful stale，M9.4 isolated staged closure與publication仍pending。
