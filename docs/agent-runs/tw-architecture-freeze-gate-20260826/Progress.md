# Progress

## Status

- Current phase：ADOPT-01 runtime pass / LIVE-01 in progress
- Program status：`SOURCE_FROZEN`
- Last updated：2026-08-26 20:45 +08:00
- Source changes：既有freeze source + canonical health、disposition fail-closed、intraday auction、platform-evidence、bounded acquisition scope
- Runtime changes：none
- Live acceptance：`PARTIAL`（Opening／Regular／Market-State current evidence passed；Closing與final-source Preopen pending）

## Completed

- 讀取repo/current product truth、backend architecture、前一輪Shared Data Core長專案與pre-commit remediation紀錄。
- 把附件Freeze Gate當作待驗證提案，未直接執行附件中的修改/migration/runtime指令。
- 以current source確認depth/auction lifecycle、DatasetHealth、AI evidence、daily/valuation、GET/sidecar、freshness owner與EOD debt。
- 確認部分疑點已不是現存bug：V1 TW direct import為0、stream已presentation-only、CP0 consumer import debt為空、core GET已cache-only。
- 建立獨立freeze-gate task folder、長計畫、architecture map、acceptance、work packages、validation、risk與execution文件。
- BASE-01唯讀檢查使用者DB：實際revision為`20260826_0072`，depth/auction canonical tables皆為0筆。
- 確認舊`auction` capability沒有durable row或durable capability欄位；決定source contract直接統一為`quote.auction`，不建立永久雙ID。
- 保存`artifacts/wp-base-01-source-20260826.json`，沒有provider IO、runtime action或DB mutation。
- LIFE-01：`auction` capability統一為`quote.auction`；Gateway typed result kind維持`auction`。
- LIFE-02：新增depth/auction Shared Registry、TW Catalog、bounded refresh metadata與storage-lineage probes。
- LIFE-03：intraday、depth、auction、current index、current breadth均回傳非空DatasetHealth；TW session/applicability留在market layer。
- AIQ-01：新增provider-neutral typed quote bundle，cache read與explicit acquire分離；component health/lineage不合併。
- AIQ-01 closeout：bundle補齊official daily close，四個component共用同一`requested_at`且各自保留完整result/health/lineage；quote projection移除`MarketDailyPrice`/`SourceRegistry` direct read。
- Realtime snapshot不再自行確認official close；只有canonical completed daily result可升級official-close projection，既有current-session pending語意保持fail closed。
- AIQ-02：AI production dependencies改走bundle projection；canonical KGI depth fixture已進入AI order-book component，MCP/outward regression通過。
- VAL-01：新增canonical latest daily evidence reader；AI Taiwan contexts不再直接依賴legacy raw ORM latest-price reader。
- VAL-02：新增provider-neutral valuation contract、TW market-owned reader與US/JP/KR market-owned compatibility readers；Portfolio AI context不再import/query price models。
- Portfolio unknown cost basis保持`None`，market value可呈現，但unrealized PnL與百分比維持unknown，不再暗示cost=0。
- GET-01～03：legacy metrics、overnight、holding ratio、futures、index list/contribution/OHLC的GET均為cache-only；舊refresh flag只會409或被明示降級，explicit provider IO移至POST/job/lease。
- Institutional holding ratio改為atomic compatibility cache；payload固定`canonical_truth=false`、`raw_receipt_id=null`與lineage limitation，不偽稱Shared Core evidence。
- Current index list/contribution/OHLC GET不再呼叫Yahoo/TWSE/TPEx provider；cache缺失時回truthful missing/partial，explicit POST才取得來源。
- SIDE-01～02：新增machine-readable sidecar classification，覆蓋disposition、holding ratio、corporate events、ETF、futures/derivatives；catalog或compatibility exemption二選一且route coverage exact。
- FRESH-01～02：新增market-owned canonical daily freshness projection；AI不再import/query`MarketDailyPrice`來重算platform-owned price freshness，而只投影Shared `DatasetHealth`。
- `tw_dataset_health.py`新增明確`read_taiwan_dataset_platform_projection`名稱；舊名稱保留compatibility alias，storage/lineage probe仍固定`freshness_status=not_evaluated`。
- CROSS-01：backend 36-file integration、migration、frontend lint/typecheck/build、safe validation與docs/diff hygiene皆通過；source manifest已固定，Git index保持空。
- FINAL-01：`market_daily_price` source-health entry不再自行重算freshness，改投影`tw_daily_freshness`的canonical `DatasetHealth`；compatibility長尾仍留在legacy evaluator，沒有冒充已converged。
- FINAL-02：新增TW market-owned instrument trading policy；disposition cache為missing/stale/degraded，或current但缺少typed `is_active`時，trading mode與analysis basis皆fail closed為unknown。
- FINAL-03：把`AuctionType.INTRADAY`接入request、KGI/MIS converter、descriptor session、transaction、repository reread與lease orchestration；continuous session只有current且active的disposition instrument適用，普通或未知狀態不會誤讀opening/closing row。
- FINAL-04：新增非deprecated`/data-core/datasets/{dataset_id}/platform-evidence`；舊`/health`只作deprecated compatibility alias，projection固定`contract_scope=storage_lineage_only`且不宣稱freshness。
- FINAL-05：quote bundle新增requested/acquired/materialized capability scope；AI/outward canonical vocabulary固定`quote.snapshot`，只在market-owned realtime boundary正式alias到內部`quote.last_trade`，避免quote-only intent退化成全bundle refresh。
- FINAL-06：freeze hash checkpoint擴充為37個final-closure source/test檔；完整regression、hash guard與safe quick均通過，current source重新達到`SOURCE_FROZEN`。

## Validation evidence

- 初次從repo root執行targeted pytest：collection失敗，原因為`app`不在import path；不是source regression。
- 從`backend/`重跑9個targeted test files：`103 passed in 8.92s`。
- Git baseline：branch=`codex/tw-etf-provider-normalization`、dirty entries=`160`、staged files=`0`。
- 本planning checkpoint只修改task docs；依Tier 0不執行backend build、frontend build、migration、runtime smoke或external provider IO。
- Planning checkpoint的11個task files全部通過strict UTF-8 readback；當時共1,172行。
- `planning-baseline-20260826.json`成功parse，schema與planning-only旗標正確。
- 文件trailing whitespace=`0`；Execution Board預期20個package缺漏=`0`。
- `git diff --check -- docs/agent-runs/tw-architecture-freeze-gate-20260826`無輸出；新folder為untracked，因此另以逐檔trailing-whitespace檢查覆蓋新檔。
- Planning完成後Git dirty entries=`161`、staged files=`0`；新增entry只有本task folder。
- VAL-01/02 focused regression：`83 passed, 21 subtests passed in 13.52s`。
- 另驗canonical TW daily valuation與unknown cost/AST guard：`3 passed, 64 deselected in 2.72s`。
- GET/index/futures/holding/sidecar regression：`107 passed, 64 subtests passed in 17.48s`。
- Freshness/lifecycle/AI/boundary regression：`133 passed in 27.19s`。
- Cross-surface backend integration：`500 passed, 99 subtests passed in 69.82s`；只有Python 3.12 SQLite adapter deprecation warnings。
- Quote四元bundle與official-close增量：`163 passed, 33 subtests passed in 14.06s`；另focused daily/quote regression `23 passed in 5.08s`。
- 最終36-file cross-surface重跑：`360 passed, 97 subtests passed in 44.31s`；先前checkpoint drift已用task-owned 9-file extension收束，未替無關US/scheduler/runtime修改擴大baseline。
- Disposable migration regression：`13 passed in 56.43s`，覆蓋0069～0072與general migration tests；沒有修改user DB。
- Holding outward contract最後增量：`44 passed, 64 subtests passed`；frontend TypeScript重跑通過。
- Frontend：ESLint通過、`tsc --noEmit`通過、Next.js production build通過。
- Safe quick profile：compileall、frontend tsc、`git diff --check`全通過；log=`.tmp/validation/20260826-191833`。
- Final safe quick：compileall、frontend tsc、`git diff --check`全通過；log=`.tmp/validation/20260826-193858`。
- Final task docs：25個檔案strict UTF-8、10個JSON artifacts parse、trailing whitespace 0、Git staged files 0。
- Final-closure focused slice：`103 passed, 67 subtests passed`。
- Quote scope / platform-evidence increment：`26 passed, 64 subtests passed`。
- Final-closure broad regression第一次：`420 passed, 100 subtests passed`；唯一失敗為checkpoint SHA drift，功能與contract tests均通過。
- 更新37-file checkpoint後architecture hash guard：`2 passed`。
- Final-closure cross-surface重跑：`422 passed, 100 subtests passed in 46.25s`。
- Safe quick：backend compileall、frontend TypeScript noEmit、`git diff --check`全通過；log=`.tmp/validation/20260826-204545`。
- Final artifact：`artifacts/final-closure-source-gate-20260826.json`；source frozen，runtime/live仍pending。
- `compileall`曾因既有`backend/app/us_market/__pycache__`權限失敗；後續由完整pytest import/collection與83個tests覆蓋syntax/import，未修改或清除該cache。

## Decisions made

- 新task不覆蓋`tw-shared-data-core-convergence-20260826`；舊folder是前置證據與歷史，不是新freeze gate進度。
- Prior runtime adoption只證明舊source identity；本輪source修改後必須重新adopt。
- DatasetHealth不能由generic Gateway猜測，必須由market-owned lifecycle evaluator提供。
- AI quote bundle保留component獨立health/lineage；read與acquire分離。
- Portfolio valuation fallback/price table ownership位於各market reader；Portfolio與AI只消費`ValuationPriceEvidence`。
- US/JP/KR本輪只加market-owned compatibility seam，明確標`REGIONAL_DAILY_LINEAGE_NOT_YET_SHARED_CORE`，不偽稱Shared Core fully converged。
- Sidecar可以truthfully維持compatibility/lineage-gap，不要求一次全部canonicalize。
- GET legacy參數保留只為compatibility；不得控制provider或在GET觸發mutation。
- Disposition與institutional holding ratio採explicit `COMPATIBILITY_CACHE` exemption；AI decision usability固定false，直到typed raw lineage完成。
- Canonical TW daily freshness的storage query與DatasetHealth evaluation由market layer擁有；AI只做舊outward shape projection。
- Official close是quote bundle的第四個canonical result；presentation realtime row即使是最後成交也不能取代completed official daily owner。
- Disposition active/inactive只能在cache current且`is_active`為typed bool時成立；false-y或malformed payload不可推定continuous。
- Intraday auction是TW instrument policy，不是generic market session；shared core只接收explicit `auction_type`與eligible candidate batch。
- `platform-evidence`只代表storage/lineage；完整freshness仍由各dataset lifecycle owner提供。
- Quote intent對外使用`quote.snapshot`，internal public-last-trade capability alias只存在market-owned orchestration boundary。

## Known issues / risks

- Worktree有160個既有dirty entries，包含其他市場與並行修改；每包實作前需重讀touched hunks。
- `backend/.tmp_pytest_runtime_20260826_1420/`目前git status讀取有Permission denied warning；不是本計畫修改面。
- `RawFetchResult`目前只以`parser_version`保存parser contract；realtime typed row另有`raw_contract_version`，是否需要把resource/capability durable identity提升到raw receipt schema將在lineage package評估。
- Intraday 1m fixture最後bar距request 30秒，但acquiring requirement的max age為1秒，因此DatasetHealth如實為`stale`；未擅自放寬既有freshness policy。
- G5 KGI official-session acceptance尚未完成。
- US/JP/KR valuation仍是market-owned daily compatibility readers，尚未具Shared Core raw receipt / Resolver lineage。
- Full backend suite與running UI不屬planning checkpoint evidence。
- 未執行全repo backend suite；本輪以500個cross-surface targeted tests加13個migration tests作source gate，避免把無關US/scheduler dirty work擴入。
- `backend/tests/tmpla6tzx59/`與`backend/.tmp_pytest_runtime_20260826_1420/`為既有權限拒絕目錄；本輪未刪除或修改，`git status`/`rg`仍會顯示warning。

## 2026-08-27 runtime adoption handoff

- 使用者已透過既有M5 live acceptance automation明確授權runtime adoption；沒有建立第二個launcher owner或第二個automation。
- Freeze checkpoint `fd68817a...`與後續task-owned live-remediation overlay `3de4da96...`均由SourceOnly驗證零mismatch，再以正式launcher component-scoped restart採用。
- `ADOPT-01=RUNTIME_PASS`：listener 49884於08:56:12啟動，selected backend `127.0.0.1:8400`、frontend `127.0.0.1:3000`；launcher lineage、project root、Python、compare、health／ready、Data Core catalog、frontend proxy、stdio MCP、Alembic `20260826_0072`與global zero-lease baseline均有dated artifacts。
- `LIVE-01=PARTIAL`：Opening compound gate、Regular與Market-State已通過；Closing與final-source Preopen仍pending。不得把partial升格為production accepted，也不得提前compare-to-off rollback。
- Index list與legacy index OHLC compatibility refresh仍由`indices.py`的explicit command physical owner實作；GET已封閉，但完整provider-module physical extraction列為保留debt，不冒充已完成。
- Final closure沒有重跑frontend production build，因本段沒有修改frontend source；TypeScript noEmit已由safe quick通過，前一個freeze gate的ESLint/build證據仍保留但不冒充本輪新build。

## Next step

- 取得使用者明確runtime adoption授權後才執行ADOPT-01；其後依合法盤中時段完成LIVE-01。現在只可宣稱source frozen，不可宣稱production accepted。

## 2026-08-27 live acceptance handoff update

- Current source的Opening、Regular、Closing、symbol isolation、cleanup與Market-State gates均已通過；final-source Preopen仍pending，因此`LIVE-01`與runtime-accepted不得升格完成。
- 另一個Codex Bridge對話於13:35與13:41以過時結論提前切到off，第二次並造成frontend readiness timeout；這些artifact只作owner conflict evidence，不是final rollback。
- M5 automation完成兩輪正式launcher component-scoped修復；第二輪compare listener 36700經120秒stable soak後，lineage、health／ready、frontend proxy、stdio MCP、source identity與global zero-lease／bridge baseline通過。
- 同一automation續排2026-08-28 08:20補final-source Preopen；只有該gate通過後才執行真正compare→off rollback與final validation。
- 13:50第二輪compare修復與stable check通過後，外部Codex Bridge owner於13:51第三次切回off。依兩輪完整修復仍被覆寫的滯澀條件，M5 automation不再互相重啟，保存terminal artifact並暫停。
- Current off runtime的正式launcher lineage、health／ready、frontend proxy、stdio MCP與global zero-lease／bridge baseline均通過；這是安全cleanup state，不是production acceptance。恢復前必須先停止或協調外部runtime owner。
