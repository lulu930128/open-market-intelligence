# Progress

## Status

- Current phase: complete
- Last updated: 2026-08-25 Asia/Taipei

## Completed

- 已讀repo／frontend AGENTS、ProductVision、OperatingModel、QualityBar、Roadmap與BackendArchitecture。
- 已讀productized workflow、market capability、freshness trace與update-status skills及必要references。
- 已確認worktree source clean；branch為`codex/tw-etf-provider-normalization`，HEAD `6d508c7`，branch既有ahead commits不屬於本任務。
- 已用live API、SQLite、scheduler與Yahoo bounded probe重現SPX與UMC缺日及錯誤previous-close基準。
- 已盤點現有cache-only OHLC GET、full-market EOD checkpoint、bounded cursor、Dataset Registry、JobRun與frontend data status path。
- 已固定capability contract、milestones、stop-and-fix rules與done criteria。
- 已新增OHLC continuity/history/previous-close additive contract；latest、內部缺日、歷史深度與provider full-range分開表達。
- 已讓daily/intraday previous-close reference date不符時fail closed，SPX與UMC fixture regression均已鎖定。
- 已新增`us_market.ohlc_history_repair` tracked POST job，最多2次Yahoo call並以cache reread postcondition決定success/error。
- 已新增`us.daily.ohlcv.priority_research` Dataset Registry entry與scheduler；index、active US holding、enabled active watchlist優先，25-call/600-second bounded，durable JobRun cursor輪替。
- 已讓priority repair執行時暫緩US full-market shard，並把full-market startup錯開1分鐘。
- 已將frontend headline change切換為backend exact previous-close contract；partial/history-short會自動enqueue explicit repair並送共用更新狀態。
- 已讀Next.js 16 client/fetch官方本機文件後修改client component。
- 已重現runtime adoption後的DB pool starvation：backend/listener仍存活，但DB-backed readyz／jobs逾時，log顯示`QueuePool size 5 overflow 10`與frontend `ECONNRESET`。
- 已修正OHLC `include_intraday=true`先查cache後等待provider時占住caller connection的ownership缺口。
- 已將explicit repair與priority reconcile改為短生命週期read／write Session；tracked JobRun Session不再兼任market-data provider工作。
- 已保留priority startup delay設定但production預設0；live驗證證明單worker FIFO下固定30秒延遲會排到長任務後方，正確隔離改由短Session ownership保證。
- 已補frontend additive-contract安全降級，舊backend缺`missing_trade_dates`時不再因`.join()`崩潰。
- 已確認僅修OHLC Session ownership仍不足：大量初始請求可使SQLite預設`QueuePool(size=5, max_overflow=10)`全數被慢請求占用，造成全站30秒checkout timeout。
- 已將本機SQLite engine切換為`NullPool`；每個Session結束即關閉連線，WAL與30秒`busy_timeout`仍保留，慢provider請求不再耗盡共用pool。
- 已將US日／週／月K首屏固定為completed-session cache read；intraday provider不再阻塞歷史K線首屏，盤中資料仍由「今日」與明確intraday path取得。
- 已由launcher精準重載最終backend/frontend；實際runtime為backend `127.0.0.1:8916`、frontend `127.0.0.1:3000`。

## Validation evidence

- Live `^GSPC`: expected 2026-08-21，persisted finalized latest 2026-08-19，缺8/20與8/21。
- Live `UMC`: resolved finalized latest 2026-08-20；intraday previous-close date為8/20；Yahoo bounded read已存在8/21 close 18.34。
- Live full-market US checkpoint: universe 7,427，current 5,323，stale 425，missing 1,679，status partial。
- Source inspection: OHLC GET `ensure_history=false`時沒有provider I/O；current frontend仍以latest/previous chart points計算headline change。
- Targeted new backend tests：11 passed；US market/overlay/job/dedupe/EOD regression首輪97 passed，修正scheduler mock後相關23 passed。
- Frontend TypeScript：`node_modules\\.bin\\tsc.cmd --noEmit`通過。
- Frontend targeted ESLint：US detail/types/三語messages通過。
- Backend US continuity／repair／priority／registry／jobs／scheduler相關 regression：136 passed。
- API contract inventory：10 passed、60 subtests；新增repair route與總operation count已鎖定。
- Frontend safe validation：full lint、TypeScript、`git diff --check`通過；Next.js 16 production build通過。
- Backend全套以隔離Windows temp lifecycle分批執行：2106 passed；唯一未執行項為既有`test_service_runner_classifies_backend_bind_failure_without_retry`，其`tmp_path`在managed sandbox內於setup階段被Windows ACL拒絕，尚未進入產品程式碼。
- Market Data Foundation extension checkpoint已更新為30 targets／15 superseded base targets；checkpoint tests 2 passed，SourceOnly preflight為0 mismatch且result=`passed`。
- Final `git diff --check`通過；本機DB、provider cache、logs與pytest temp均未進入tracked diff。
- Runtime contention targeted regression：20 passed；新增pool size 1並行probe證明OHLC intraday overlay與explicit repair等待provider時仍可取得DB connection。
- US OHLC／intraday regression：32 passed（42 deselected）。
- Job／API contract／Dataset Registry regression：35 passed、60 subtests。
- Priority tracked-job Session隔離：4 passed。
- Frontend TypeScript與targeted ESLint通過。
- Backend full regression在最終Session ownership修改後的基線：2125 passed、3 deselected、581 subtests passed；3項為2個跨台北午夜的既有KGI regular-session時間假設與1個managed sandbox Windows `tmp_path` ACL setup，均與本次資料／pool diff隔離。
- 最終`NullPool`與US首屏cache-only修改後 targeted regression：18 passed；frontend TypeScript與US detail targeted ESLint再次通過。
- 最終live provider contention probe：`^VIX`含intraday請求耗時6039ms期間，direct/proxied `readyz`各10次皆200，最大91ms／92ms。
- 最終runtime log（latest backend/frontend start之後）：`QueuePool` errors 0、backend request failures 0、frontend `ECONNRESET`／`socket hang up`／`TypeError` 0。
- 最終in-app browser smoke：US TSM日K顯示180根、latest completed date 2026-08-21，無「backend連線中斷」、無空K線；warm SSR log為1.7至2.5秒。

## Decisions made

- 使用additive outward fields與既有SQLite tables／checkpoint，不以DB reset處理。
- Priority repair lifecycle不污染full-market stock universe語意；progress/cursor保存在JobRun，不新增schema migration。
- Repair success必須由postcondition決定，不以HTTP無exception代替dataset current。
- Provider full-range資料不足時使用`best_available`，不讓新上市標的永久偽裝成provider failure。
- SQLite不使用固定容量QueuePool承載本機file-handle連線；Session仍須短生命週期，`NullPool`是跨endpoint的fail-safe而不是放寬provider工作邊界。
- 歷史日／週／月K首屏不等待Yahoo intraday；先呈現completed-session cache，盤中trend由「今日」path獨立載入。

## Known issues / risks

- US calendar尚無instrument-level halt/suspension eligibility owner；continuity缺日需保留eligibility limitation。已補2025-01-09 Carter national day of mourning特殊休市fallback。
- Yahoo對Nasdaq Trader部分特殊symbol需provider mapping；404不得阻塞valid priority symbols。
- `NullPool`會讓每個active Session各自持有一條SQLite連線；因此仍需維持bounded worker、短Session與WAL，不能把它視為允許無界provider concurrency。
- Backend full-suite仍有2個依實際台北時間判斷regular session的既有KGI測試，以及1個Windows launcher `tmp_path` ACL setup項未納入最終綠燈；相關產品路徑與本次targeted regression已通過。

## Next step

- 讓`us_market.priority_ohlc_reconcile`依既有bounded cursor繼續完成381個priority targets；不需要為本次修復再啟動額外全市場refresh。
