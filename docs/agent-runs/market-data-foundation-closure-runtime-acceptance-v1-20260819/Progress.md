# OMI Market Data Foundation 1.1 進度

## Status

- Current phase：M5 source recovery validated / compare adopted / external 3711 viewer conflict / formal sessions pending / automation paused
- Last updated：2026-08-24 09:09 +08:00（Asia/Taipei）
- Source implementation authorization：已授權（2026-08-19，完整1.1計畫）
- Runtime mutation authorization：已授權（component-owned mode/restart acceptance）
- Live provider/session authorization：已授權（bounded KGI viewer-lease，無Account/Order）
- Commit / push / PR / release：未授權
- Foundation final status：`source-hardened / runtime-adopted / M5 sessions pending`

## Completed

- 完整讀取使用者附件，並將其視為待驗證工程提案而非自動執行指令。
- 對照repo AGENTS、Product Vision、Operating Model、Quality Bar、Roadmap、Backend Architecture與前一階段AcceptanceReport/Progress/Handoff02。
- 以source inspection與pure reproducer逐項確認C01-C03。
- 以唯讀launcher log、process metadata、health與public catalog建立current runtime baseline。
- 建立本長專案的：
  - `Prompt.md`
  - `IssueReview.md`
  - `Plan.md`
  - `RuntimeAcceptanceMatrix.md`
  - `Progress.md`
- 將source hardening、runtime restart/mode、live KGI session與commit/push拆成獨立授權gate。
- 使用者已確認一次完成完整1.1計畫；Gate S、R、L已通過，Gate C仍未授權。
- 保存M0 target-file hashes與21:00 runtime baseline到`artifacts/source-manifest.json`。
- M1 C01完成：Trading Status先比較currentness tier，再比較official/authority；current broker與stale official衝突回`PARTIAL`且`research_usable=false`，candidate lineage保留。
- M1 C02完成：`tw.daily.ohlcv` registry policy明示listed instrument、market day與instrument eligibility；沿用`False -> NOT_APPLICABLE`、`None -> UNKNOWN`。
- M1 C03完成：US general defaults不再含technical/insider；insider market正規化為`US`，explicit/domain selection恢復但general default不增加SEC工作。
- 新增safe startup log：`Market Data Foundation runtime mode=<mode>`，讓running process的effective mode可驗證。
- 重新產生MCP public snapshot；新digest為`fec3d7d071dd7ca92d5245b94fca59d99801b901a8228f09e62cc2e9ebfdd7e2`。
- M2 backend safe validation完成：compileall passed、`1911 passed, 801 warnings`、`git diff --check` passed；新增mode health與runtime telemetry observability後的最終source log在`.tmp/validation/20260819-221432`。
- 修正全套驗證揭露的既有13F test isolation缺口：clock mock改為只替換13F module內的`time`物件，不再修改Python共用`time.monotonic`；產品batching邏輯未變。
- 保存post-change target hashes、public contract digest與驗證結果到`artifacts/source-checkpoint.json`。
- 第一次正式runtime adoption證實一般module `logger.info`未進入uvicorn log；依stop-and-fix新增`/api/system/health.runtime.canonical_market_data_mode`，targeted `10 passed`且full backend validation重跑通過。缺少machine-readable mode欄位的22:05 runtime evidence已作廢。
- 第一次shadow probe再證實quote-depth一般module INFO logger未進正式runtime log；改由`uvicorn.error` INFO logger輸出bounded telemetry（無raw payload），targeted `20 passed`且full backend validation重跑通過。22:13以前缺少telemetry的mode evidence只作診斷、不作正式pass。
- M3正式mode acceptance以同一source checkpoint `703caf9b23b79189a5db65dfb8b248686e4f2c4635c251d4f3174ab0ea573799`完成：off/shadow/compare health均直接回報effective mode，三者2330 post-close穩定語意hash皆為`f11a91a285ed97f42a6371cbf5ea33925532db20abce783091121c0a2997bc2a`。
- Shadow產生單一`validated` telemetry、mismatch=0；compare產生單一`matched` telemetry、mismatch=0、未分類核心mismatch=0。
- compare期間DB file mtime有變但size不變，因legacy quote upsert與背景排程並存而不可歸因；artifact保留`null` counter與limitation，不把unknown偽造為0。Canonical seam無DB/session argument，targeted same-payload test亦證明不額外external fetch。
- Backend authoritative calendar確認next TW trading day=`2026-08-20`、preopen=`08:30`、open=`09:00`。
- 建立同一task heartbeat `omi-mdf-1-1-preopen-acceptance`：08:35 preopen，成功後自調08:58 opening，再調09:05 regular/rollback/closure；每階段鎖定source fingerprint與Gate L邊界。
- 2026-08-20 08:37 preopen硬閘門複驗：local date=`2026-08-20`、source checkpoint SHA-256=`703caf9b23b79189a5db65dfb8b248686e4f2c4635c251d4f3174ab0ea573799`、TWSE authoritative calendar=`trading_day / preopen`均通過；但正式backend `/api/system/health`回報effective mode=`off`，不符合必須為`compare`的前置條件。
- 依stop rule未建立2330 viewer lease、未啟動KGI subscription、未取provider sample，也未修改source；失敗證據保存於`artifacts/session-preopen.json`，heartbeat暫停，preopen/opening/regular仍全部未驗收。
- 確認真正runtime transition：compare launcher於2026-08-19 22:21:49啟動；Windows於23:22:20重新開機；一般startup launcher於23:24:46啟動，backend於23:24:51依安全預設回到`off`。因此blocker是reboot後沒有acceptance bootstrap，不是KGI semantic failure。
- 建立`M5RetryPreparationPlan.md`，將off->compare補成正式launcher owner handoff，而不是在另一個shell設env後啟動被mutex拒絕的第二個launcher。
- `scripts/omi-launcher.ps1`新增local-only `Exit`/`RestartServices` control event；實際stop/restart仍由持有mutex的tray owner執行，不broad-kill、不新增第二個lifecycle owner。
- 新增`invoke-mdf-m5-preflight.ps1`單一入口：source/checkpoint、runtime lineage、authoritative calendar、public catalog、frontend、stdio MCP、viewer baseline與可選Quote-only readiness都以dated artifact fail closed。
- 新增`smoke-omi-mcp-stdio.py`，只做`initialize -> notifications/initialized -> tools/list`，不call provider、不LLM、不write。
- 保存08:37失敗的dated副本`artifacts/session-preopen-20260820-failed.json`；後續正式session artifact不可覆寫歷史失敗證據。
- 新preflight對目前off runtime的唯讀baseline已通過：checkpoint與14個target hash一致、launcher PID=9632、listener PID=5760、health/ready、TWSE calendar、public digest、frontend proxy、MCP與viewer/bridge baseline=0；artifact=`artifacts/m5-preflight-20260820-off-check.json`。
- 使用者透過舊tray owner執行`Exit Launcher`後，確認8400/3000 listener均已乾淨退出；未使用broad-kill。
- 新launcher首次off->compare bootstrap通過：launcher PID=56716、listener PID=54552、effective mode=`compare`，checkpoint、calendar、public catalog、frontend、MCP與viewer baseline全數pass。
- 同一launcher的`RestartServices`通過：launcher PID維持56716，listener由54552更新為9764，重啟後仍為`compare`；第二次`Prepare`為冪等，未再次換listener。
- 2330 Quote-only viewer readiness通過：before=`0 lease / 0 bridge`、active=`1 lease / 2 bridge`、release成功、idle cleanup後=`0 / 0`；盤後狀態僅記為`subscribing/warming`，未宣告live semantics pass。
- 依RuntimeAcceptanceMatrix的launcher invalidation rule，以新launcher重新建立off/shadow/compare process identity；三者source target mismatch=0、viewer/bridge baseline=0，最終running runtime回到`compare`。
- 未用`refresh=true`重跑runtime same-payload probe，因該legacy path可能造成外部fetch與quote upsert；舊process identity已作廢，先前同一Foundation source checkpoint的deterministic/same-payload semantic evidence保留並明示限制。
- 建立`M5ManualRunbook.md`及`artifacts/m5-retry-preparation-20260820.json`；今晚狀態只提升為`READY_FOR_MANUAL_M5`，未標記`runtime-accepted`或`ready-for-02`。
- 2026-08-21 08:23 manual preflight pass：local date與TWSE authoritative trading day通過，source checkpoint SHA-256與14個target hashes一致；昨晚launcher PID=56040、listener PID=54432持續存活，effective mode=`compare`，未發生額外restart。
- 同次preflight確認health=`ok`、ready=`ready`、public catalog digest、frontend proxy與stdio MCP一致；2330 viewer=`not_subscribed / 0 lease`、KGI bridge process=0，未建立lease或取provider sample。
- 盤前dated evidence：`artifacts/m5-preflight-20260821-082311-206.json`；result=`passed`、calendar phase=`preopen_pending`、next trading day=`2026-08-24`。
- 2026-08-21 08:34~08:35在既有2330 viewer lease下完成bounded Preopen sampling；runtime=`compare`、KGI stream=`live`，quote-depth正確投影`preopen_auction / actual_trade_occurred=false / last_trade_price=null`。
- 同一window的realtime stream卻累積21筆current-session `recent_trades`，event time=08:33:47~08:35:38、price=2340~2355、volume=1154~1156 lots，而所有`total_volume_lots=0`；同時22筆auction observations明示`provider_simtrade_indicative_not_formal_trade`。
- Compare telemetry沒有未分類核心mismatch：KGI僅`LEGACY_ZERO_NORMALIZED_TO_MISSING`，TWSE MIS為`matched`；因此failure集中在realtime stream trade classification，不是quote-depth canonical projection或compare taxonomy。
- 依stop rule將Preopen標記failed，artifact=`artifacts/session-preopen-20260821.json`，failure code=`PREOPEN_TRIAL_LEAKAGE_IN_REALTIME_STREAM`；Opening、Regular與rollback均未執行。
- 現有viewer lease並非本probe建立，缺少ownership/lease id，因此未做不安全release；08:36狀態為1 lease / 2 KGI bridge processes，cleanup仍待外部viewer結束。
- 盤前失敗root cause已確認：KGI callback雖有正`close/volume`且`simtrade=0`，但`total_volume=0`；realtime manager只排除`simtrade=1`，因此把零累計量試撮誤列為actual trade。
- Provider/canonical classification已收斂為同一pure contract：actual trade必須同時具備非試撮、正price、正single volume與正cumulative volume；零累計量正價量只能是indicative/auction evidence。
- Stream buffer新增per-symbol event-date isolation；日期只能前進，昨天quote/KBar不得覆蓋或混入今天buffer。`recent_trades`維持既有newest-first outward contract。
- Source checkpoint coverage由14個擴充為30個runtime owner/test owner；舊`703caf9b...` checkpoint保留為`artifacts/source-checkpoint-20260819.json`，最終checkpoint=`99f95233bb35afb033bcce7c0f959a00eb74b785c4734608b80e0f153e80a39d`且`validation.result=passed`。
- Preflight修正跨午夜launcher log rollover：同一launcher在新日期執行`RestartServices`時，即使新log沒有重複`Launcher started`，仍可從component-owned service marker發現endpoint；process lineage依舊是mandatory gate。
- 最終component-owned restart通過：launcher PID=56040、listener 56364 -> 51492、effective mode=`compare`、source 30/30、health/ready、calendar、public contract、frontend、MCP與viewer baseline全pass；artifact=`artifacts/m5-preflight-20260821-preopen-fix-final-restart.json`。
- 新fingerprint的09:08 regular bounded probe只用TW 2330：lease=`0 -> 1 -> 0`且release成功；4個samples的invalid trade、cross-date trade/KBar、newest-first ordering error、跨sample sequence/event-time regression全部為0。
- 外部frontend viewer在restart後會自動reacquire並可切換symbol（本輪依序觀察6173、2478各自為1 lease）；本task未建立、取樣、release或終止這些lease。2330 cleanup已回0；全域bridge count維持2是活躍外部viewer lifecycle，不歸因本probe。
- Consolidated remediation evidence：`artifacts/m5-preopen-fix-validation-20260821.json`。本次regular只證明修正後行為，不可跳過同fingerprint Preopen/Opening而算正式M5 Regular pass。
- 正常Windows權限層的official backend wrapper最終通過：compileall passed、`1915 passed, 801 warnings in 233.56s`、`git diff --check` passed；log=`.tmp/validation/20260821-091318`，artifact=`artifacts/m5-preopen-fix-source-validation-20260821.json`。先前非零exit確認是sandbox basetemp ACL cleanup限制，不是產品regression。
- Preflight source gate新增`validation.result=passed`強制檢查；最終checkpoint `99f95233...`的09:25 read-only check已通過source 30/30、runtime lineage、compare、calendar、public contract、frontend與MCP，最後只因外部2478 viewer使global bridge baseline非0而如實failed；artifact=`artifacts/m5-preflight-20260821-final-checkpoint-check.json`。
- 2026-08-21 13:24受限執行環境的第一次Closing Auction preflight因Win32 process lineage不可見而以`RUNTIME_IDENTITY_MISMATCH`停止，未建立lease；原始artifact=`artifacts/m5-preflight-20260821-closing-diagnostic.json`保留。相同唯讀preflight在正常Windows權限層重驗通過：launcher=56040、listener=51492、mode=`compare`、TW calendar=`closing_auction`、health/ready/public/frontend/MCP與`0 lease / 0 bridge`全pass；artifact=`artifacts/m5-preflight-20260821-closing-diagnostic-windows.json`。
- 13:28:32建立本probe唯一擁有的TW 2330 viewer lease；lifecycle=`0/0 -> 1/2 -> 0/2`，13:30:10 release成功。Bridge依設定的120秒component-owned idle timer於13:32:52自行回到0；未release未知lease、未終止process。
- Closing Auction bounded probe取得13個sample。quote-depth在正式收盤撮合前持續正確投影`closing_auction / AUCTION_INDICATIVE_ONLY / actual_trade_occurred=false / last_trade_price=null`，volume conversion `11655 lots = 11655000 shares`正確，cross-date/order regression均為0，13筆compare telemetry全為`matched`且mismatch=0。
- Realtime stream在13:28:42起卻把試撮加入`recent_trades`；正式13:30撮合前累積16筆false trade。13:29:58的auction seq=33與trade seq=34具有相同price=2410、volume=4045，而trade沿用未變的regular cumulative=11655；13:30正式撮合seq=35才把cumulative推進至15700，delta=4045。
- Root cause確認為stream classifier未傳closing session：`kgi_superpy.py`以session unknown呼叫canonical predicates，使paired非simtrade callback的正價量與既有正cumulative誤過actual-trade gate；quote-depth有session context所以語意正確。Failure artifact=`artifacts/session-closing-diagnostic-20260821.json`，code=`CLOSING_AUCTION_TRIAL_LEAKAGE_IN_REALTIME_STREAM`。
- 2026-08-24 08:21執行正式M5 preflight時，checkpoint artifact本身SHA-256仍為`99f95233...`且`validation.result=passed`，但30個受保護target中有14個目前hash已不同；preflight以`FOUNDATION_TARGET_CHANGED`在source gate停止。主artifact=`artifacts/m5-preflight-20260824-082122-735.json`，完整mismatch清單=`artifacts/m5-preflight-20260824-082122-source-mismatch.json`。
- 本次停止發生在calendar、runtime preparation與provider acquisition之前；未建立viewer lease、未取KGI sample、未執行Account/Order、backfill/repair、DB write probe、process kill、commit或push。Preopen、Opening、Regular均未執行，automation依stop rule暫停。
- 14個target的ownership audit確認02A完成時Foundation 30-target mismatch=0；目前漂移全部來自02A之後已存在的EOD、US first-class與research consumer變更，不是02A越界修改。舊checkpoint完整封存為`artifacts/source-checkpoint-20260821.json`。
- Closing Auction stream classifier新增per-symbol cumulative-volume evidence：同日candidate只有在cumulative advance時才可成為actual trade；paired simtrade/non-simtrade且cumulative unchanged維持trial evidence，13:30 cumulative advance才接受為正式成交。新增closing pair與一般盤中unchanged cumulative regression。
- 同步修正MCP capability enum漏掉`news.events`及stale tool catalog digest expectation；Foundation owner matrix=`167 passed, 233 subtests passed`，MCP contract=`33 passed, 2 subtests passed`。
- 正常Windows權限層官方backend validation最終通過：compileall passed、`2096 passed, 801 warnings in 248.56s`、`git diff --check` passed，log=`.tmp/validation/20260824-085844`。sandbox中的pytest temp `.lock`/cleanup PermissionError已隔離為runner ACL限制。
- 新30-target checkpoint=`6f2e0e8724704b83a22a63750583e6a5d4d2ed7a4a8d651e0332b9e64d1c543e`、`validation.result=passed`、30/30 mismatch=0、public digest=`63f5197d...`；checkpoint guard=`7 passed`。
- 09:03 component-owned `Prepare`成功採用compare runtime：source、launcher/listener lineage、health/ready、calendar與public catalog皆pass；第一次preflight因frontend在launcher重啟後約4秒才ready而被單次probe過早判fail，artifact=`artifacts/m5-preflight-20260824-090349-790.json`。
- Preflight harness新增bounded frontend readiness retry（預設30秒，每500ms一次）與attempt/wait/error evidence；PowerShell parser=0 errors。後續`Check`的frontend與stdio MCP均pass。
- 09:06 preflight最後以`VIEWER_BASELINE_NOT_CLEAN`停止：外部OMI頁面持有3711 viewer lease並持續heartbeat，2330本身active lease=0但global bridge count=2。artifact=`artifacts/m5-preflight-20260824-090641-554.json`；本task未建立、release或終止該外部lease/process。
- 因source recovery與validation完成時已09:03，2026-08-24 Preopen與Opening時窗已不可補測；Regular不得跳過前兩個gate。今日三個formal session均維持pending，未取provider sample、未做rollback或closure。

## Validation evidence

### C01 reproducer

- Stale TWSE official `TRADABLE` + live KGI broker `SUSPENDED`。
- Actual：selected provider=`twse`、status=`tradable`、resolved health=`stale`。
- Verdict：confirmed correctness bug。

### C02 probe

- `tw.daily.ohlcv` eligibility policy=`listed_instrument`。
- `eligible=False -> not_applicable / DATASET_NOT_ELIGIBLE`。
- `eligible=None -> unknown / ELIGIBILITY_UNKNOWN`。
- Verdict：policy expressiveness gap；health evaluator已具備tri-state truth。

### C03 probe

- Raw US defaults包含`technical.structure`。
- Normalized required不包含`technical.structure`。
- Raw US defaults也包含`ownership.insider_transactions`，但其capability market為小寫`us`，normalized required同樣將它移除。
- Verdict：confirmed double-truth cleanup，並發現額外market-casing defect；計畫採不擴大general default acquisition的修法。

### Runtime baseline

- Launcher log：`logs/launcher/2026-08-19/launcher.log`。
- Launcher PID 42700；official script `scripts/omi-launcher.ps1`。
- Backend wrapper/listener 69668/66124；selected port 8400。
- Frontend wrapper/listener 26684/55704；selected port 3000。
- `/api/system/health`與`/api/ai/tools`均200。
- Live/local catalog canonical JSON SHA-256同為`ebe6233ae0b3023a358e6976fc6bff4485879e74fa8e1ef0d132bb1438e2eb66`。
- Runtime start晚於目前Foundation target file last-write time。
- Verdict：source adoption已有強證據，但effective mode、off/shadow/compare、live session與rollback仍未驗收；不得標記runtime-accepted。

### M1 targeted validation

- Compileall：passed。
- Contract/runtime/API/MCP focused：`109 passed, 278 subtests passed`。
- Foundation/KGI/MIS/shadow/runtime matrix：`165 passed, 288 subtests passed`。
- C01 reproducer修正後：selected provider=`kgi`、status=`suspended`、health=`partial`、`research_usable=false`。

### M2 backend safe validation

- Official wrapper：`.\scripts\run-safe-validation.ps1 -Profile backend`。
- Compileall：passed。
- Full backend pytest：`1911 passed, 801 warnings in 237.67s`。
- Git diff check：passed。
- Validation log root：`.tmp/validation/20260819-221432`。
- 前一次`.tmp/validation/20260819-214856`的唯一失敗是13F test clock mock污染全域`time`；隔離修正後整檔`5 passed`且full suite乾淨通過。

### M5 retry preparation runtime evidence

- Initial OFF baseline：`artifacts/m5-preflight-20260820-off-check.json`，passed。
- Compare bootstrap 1：`artifacts/m5-preflight-20260820-compare-bootstrap-1.json`，passed。
- Component-owned restart：`artifacts/m5-preflight-20260820-compare-restart.json`，listener 54552 -> 9764，mode=`compare`，passed。
- Idempotent bootstrap 2：`artifacts/m5-preflight-20260820-compare-bootstrap-2.json`，listener仍為9764，passed。
- Quote viewer lifecycle：`artifacts/kgi-viewer-readiness-20260820.json`，release與idle cleanup均回baseline，passed。
- New-launcher mode identities：`artifacts/m5-preflight-20260820-mode-off.json`、`mode-shadow.json`、`mode-compare-final.json`，全部passed。
- Final runtime：launcher PID=56040、listener PID=54432、health=`ok`、ready=`ready`、effective mode=`compare`、viewer/bridge baseline=0。
- Final validation：PowerShell parser passed、Python syntax passed、10份JSON parse passed、4份文件UTF-8讀回passed、stdio MCP smoke passed、targeted `git diff --check` passed；精確bridge process probe=0。
- Consolidated result：`artifacts/m5-retry-preparation-20260820.json`，result=`passed`、target status=`READY_FOR_MANUAL_M5`。

### 2026-08-21 manual preflight

- Command：`.\scripts\invoke-mdf-m5-preflight.ps1 -RuntimeAction Prepare -ExpectedMode compare -ExpectedDate 2026-08-21`。
- Artifact：`artifacts/m5-preflight-20260821-082311-206.json`。
- Result：passed；source mismatch=0、calendar trading day=true、effective mode=`compare`、health/ready/frontend/MCP passed、viewer lease=0、bridge process=0。
- Side effects：未restart、未建立viewer lease、未啟動KGI subscription、未取provider sample。

### 2026-08-21 Preopen live acceptance

- Window：08:34:21~08:35:39 +08:00，TW 2330，existing viewer lease，bounded samples。
- Quote-depth projection：`preopen_auction`、`actual_trade_occurred=false`、`last_trade_price=null`、freshness=`live`，passed。
- Realtime stream：21筆same-session `recent_trades`且`total_volume_lots=0`，同時存在22筆indicative auction observations，failed。
- Compare telemetry：KGI只有核准的`LEGACY_ZERO_NORMALIZED_TO_MISSING`；MIS=`matched`；unclassified core mismatch=0。
- Artifact：`artifacts/session-preopen-20260821.json`，result=`failed`。

## Decisions made

- C01只改Trading Status specialized policy，不改quote/depth/bar一般resolver排序。
- C02只補registry eligibility policy與tests，不提前實作official status acquisition。
- C03移除US general raw default中的technical/insider，將insider market正規化為`US`以恢復explicit truth；compatibility filter保留。
- 現有21:00 runtime不取代修正後的Gate R；任何M1 source改動後必須重新adopt。
- Mode acceptance使用process-scoped、component-owned runtime flow；不直接修改或輸出`.env` secrets。
- Production default維持`off`；`compare`只由manual preflight在正式launcher process scope內建立，重開機後必須重新preflight。
- 真實session以同一source fingerprint及最多3 symbols完成；不做MCP arbitrary-symbol KGI acquisition。
- Commit不是Foundation closure條件；文件化checkpoint才是必要條件。

## Known issues / risks

- Worktree仍有大量既有modified/untracked entries，且Foundation source本身位於dirty integration base；本次未reset、clean、commit或push。
- Effective canonical mode已有running health、launcher/listener lineage與dated artifacts；但process-scoped `compare`不保證跨重開機保留，明早仍須重新執行preflight。
- Current resolver health schema沒有machine-readable conflict enum；計畫優先使用既有`PARTIAL`、selection reason、limitations與candidate lineage，若無法truthful表達再停下評估versioned schema，而不是默默擴contract。
- 真實preopen/opening/regular驗收受交易日、KGI entitlement、viewer lease與provider availability限制；fixture不能替代live-session pass。
- 2026-08-21的realtime trial-leakage與cross-session buffer缺口已完成source fix、targeted regression、正式runtime adoption及regular bounded diagnostic；但同fingerprint的正式Preopen/Opening仍須下一交易日重跑，不能由盤中證據替代。
- 2026-08-21尾盤揭露第二個session-specific leakage：Preopen的zero-cumulative修正不足以涵蓋Closing Auction，因closing trial沿用正的regular cumulative volume。修正必須讓realtime stream取得backend-owned session context，或採能區分unchanged cumulative trial與final cumulative advance的等價canonical evidence；不得用價格/volume單獨猜測。
- Full backend wrapper的sandbox basetemp ACL問題已由正常Windows權限層乾淨重跑隔離；產品validation現為green，sandbox runner cleanup仍保留在artifact作工具環境限制。
- Frontend viewer目前可持有並切換外部lease（最新觀察為2478）；下一次正式preflight前必須由viewer owner正常退出並確認所有viewer lease與bridge baseline=0，本task不代為釋放未知lease。
- 2026-08-24的14-target drift已完成歸屬、validation、checkpoint重建與component-owned compare adoption；舊`99f95233...`只保留為歷史fingerprint，不得再用於新的session acceptance。
- Current source checkpoint為`6f2e0e87...`；acceptance harness本身不在30-target checkpoint內以避免self-reference，須另外以parser/hash與dated preflight artifact驗證。
- Provider event endpoint顯示背景市場工作可能同時存在；side-effect delta必須以target/provider/request correlation判讀，不能拿全系統總數直接歸因shadow。
- Runtime probe只能確認目前source；M1改動後baseline會失效。

## Authorization ledger

- [x] Gate S：確認本計畫並授權source hardening。
- [x] Gate R：授權component-owned mode/restart與runtime acceptance。
- [x] Gate L：授權bounded KGI viewer-lease live session smoke。
- [ ] Gate C：授權commit/push（非closure必要條件）。

## Next step

- 14-target ownership audit、closing fix、完整backend validation、30-target checkpoint重建與compare runtime adoption均已完成；不得回退使用舊`99f95233...`。
- 下一輪依`M5RetryRunbook20260825.md`執行。08:10 Prepare前須由3711 frontend viewer owner正常退出，確認global lease summary與KGI bridge process回0；沒有ownership證據時不得直接刪除lease或broad-kill。
- 2026-08-21的Opening/Regular/rollback formal acceptance維持未執行；09:08 regular evidence只作fix diagnostic，不覆蓋Preopen failure。
- Closing Auction classifier的paired callback、positive unchanged cumulative與13:30 cumulative advance regression已完成；正式Closing Auction live retest仍pending，不能由source test替代。
- 下一個authoritative TW trading day是2026-08-25；使用checkpoint `8acbaea6...`依序執行07:50 SourceOnly -> 08:10 Prepare -> 08:20 Check -> Preopen -> Opening -> Regular，任一30-target source/config變更仍須重算fingerprint並重新adopt。
- 正式preflight前由frontend viewer owner正常退出並確認2330/所有其他viewer lease與KGI bridge process回到baseline；沒有ownership證據時不得直接刪除lease或broad-kill。
- 三個session全pass後才可執行`compare -> off` rollback與Foundation closure；目前不得標記`runtime-accepted`或`ready-for-02`。

## M5 reliability hardening — 2026-08-24

- Viewer lease新增bounded `owner_kind=frontend_viewer|acceptance_probe`；heartbeat/release保留ownership。新增`GET /api/market/realtime-quote-leases/summary`，只回傳owner/symbol/count與manager process lifecycle，不回lease ID、credential或私人identity。
- Frontend viewer lifecycle改為`visibilitychange/pagehide`主動release、`visible/pageshow`reacquire；acquire/release/heartbeat序列化，pagehide使用bounded keepalive DELETE，release失敗不立即製造replacement lease。
- Preflight升級為v2並新增`SourceOnly`。Global baseline先看redacted summary：任何lease=`EXTERNAL_VIEWER_LEASE_PRESENT`；只有零lease但bridge未自然退出才bounded等待並以`BRIDGE_IDLE_CLEANUP_TIMEOUT`分類；probe只建立`acceptance_probe`並只release自身lease ID。
- Source/full validation：targeted=`35 passed, 60 subtests`；pre-check full=`2091 passed, 801 warnings`（只排除checkpoint boundary file）；frontend lint/typecheck/build與git diff check passed，log=`.tmp/validation/20260824-101537`。重建後guard=`7 passed`，含guard backend full=`2098 passed, 801 warnings in 276.49s`，log=`.tmp/validation/20260824-102358`。
- 舊checkpoint `6f2e0e...`封存為`artifacts/source-checkpoint-20260824-pre-lease-hardening.json`；current checkpoint SHA-256=`8acbaea6fa4566416c67dc1e1745e4a080e2b6ee8e341fd1c0edc501f56badf2`，30/30 mismatch=0、validation passed。
- `SourceOnly`實測passed，artifact=`artifacts/m5-preflight-20260824-102923-431.json`；runtime/calendar/frontend/MCP/viewer全部明示`not_run`，證明早期gate沒有runtime side effect。
- 10:29 `Prepare`完成正式launcher compare adoption：listener PID=46688、health/ready/calendar/public catalog/frontend/MCP均passed。Global summary辨識外部`frontend_viewer`在3711持有1個lease，精確以`EXTERNAL_VIEWER_LEASE_PRESENT`停止；本次未建立或release lease，artifact=`artifacts/m5-preflight-20260824-102944-059.json`。
- 明日runbook改為07:50 SourceOnly、08:10 Prepare、08:20 Check、08:34 Preopen；Closing Auction live retest仍為獨立blocker，Foundation closure狀態不變。
- Harness最後加入`RUNTIME_LINEAGE_PROBE_UNAVAILABLE`，把sandbox無法讀listener/WMI與真實`RUNTIME_IDENTITY_MISMATCH`分開。Sandbox artifact=`artifacts/m5-preflight-lineage-sandbox-20260824.json`如實failed；相同Check在normal Windows permission完整passed，artifact=`artifacts/m5-preflight-owner-clean-final-20260824.json`。
- Final clean Check觀察global lease=0、owner/symbol counts空、bridge=false、subscription worker=0，且compare runtime lineage/health/ready/calendar/catalog/frontend/MCP全pass。這證明外部3711 viewer已由owner lifecycle正常釋放；本task沒有release或kill它。
- Final harness SHA-256=`4787148eee2e520ab047bc033500a929ee20a4a8ffda1acc1befada8c3e42d5b`；final SourceOnly artifact=`artifacts/m5-source-only-harness-final-20260824.json`。

## 08:20 active observation policy — 2026-08-24

- 使用者明確要求08:20起主動監控；第一次preflight failure不再自動等同PAUSED。Automation會先保留真實artifact，再依failure taxonomy做bounded現場修復、完整重驗並自動續排。
- 08:20 Check增加單一2330 `acceptance_probe` viewer readiness lifecycle，提早暴露KGI Python／CA／login／subscription／release／idle-cleanup問題；此readiness不能替代08:30後的正式Preopen evidence。
- Runtime adoption/readiness只走正式launcher；global zero-lease bridge逾時可component-scoped RestartServices。外部viewer lease永不代為release，改在08:24／08:28／08:31重驗。
- Localized task-owned source/harness問題可修復，但必須執行affected validation、重建30-target checkpoint、同步automation pin與重新adopt；未知／廣泛dirty ownership保持fail closed。
- 只有credential／entitlement／人工作業、外部lease逾session窗口、未知source ownership、越界操作需求或已錯過真實session window才暫停並回報。中間成功修復與重試不通知使用者。
