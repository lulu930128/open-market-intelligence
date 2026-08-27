# Progress

## 狀態

- Source implementation：完成。
- Source-ready：通過；base、M5、Data Core、Shared Core、architecture freeze 與 2026-08-27 live-remediation 六層 checkpoint 形成 64 個 effective targets，最終 SourceOnly preflight 為零 mismatch。
- Runtime-adopted：通過；2026-08-27 08:56 只透過正式 component-owned launcher 採用最終 source，盤中 `compare` listener 49884 的 health／ready、frontend proxy、stdio MCP 與 zero-lease baseline 均已驗證。
- Runtime-accepted：`PENDING`。Opening、Regular／Level 5／symbol switch、Market-State、Closing Auction／formal match 與 cleanup 均為本日 current-source `PASS`；final-source Preopen 因真實時窗已過仍為 `PENDING`，不得由後續 session 補造，因此 `release_ready=false`。
- Final runtime：依本輪明確要求，所有今日可取得 gate 通過後已由正式 launcher 完成 `compare -> off` rollback。13:38 另一既有 acceptance automation 曾把 runtime 重設為 `compare`；競態清除後已再次由正式 launcher rollback，最終為 launcher PID 13480、listener PID 51132、effective mode=`off`、global zero lease／bridge idle。完整判定見文件末端的本輪權威 final handoff 與 `artifacts/m5-final-status-20260827.json`。

## 已根除的 source 問題

- Regular／Post-close 第一筆 eligible positive cumulative callback 只建立 baseline，不再新增 phantom trade；只有下一筆 strict cumulative advance 才能進 trade buffer。
- Same／decreasing cumulative、trial callback、duplicate signature 與 cross-date rejection 都有 bounded counter 與明確 projection action。
- Diagnostic event history 預設不出現在 GET／SSE；只有 `diagnostic_limit` 明確開啟才回傳去識別化事件，raw payload、account、credential 與 lease id 不會進 artifact。
- Frontend L5 不再等待 GET quote-depth baseline；matching、live、non-stale SSE depth 可先顯示。
- Hook return boundary 依目前 `stockId` 隔離 quote depth、stream、replay 與 load state，舊 request 即使晚回也不會在切股後 outward。
- Index Resolver additive outward `selected_provider`、`selected_authority`、`selected_finalization`、`official_source`、`official_close_confirmed`、`provisional_estimate`；dashboard 只投影 Resolver 語意，legacy `official/provisional` 保留 compatibility。
- Thin MCP Taiwan dashboard schema snapshot 已重生，digest=`70479f355559963757862b1b562e0ec4659197327744ac240de751afba36b381`。
- 新增 executable M5 live-session harness：支援 `OfflineFixture` 與 bounded `Live`、`acceptance_probe` lease、heartbeat、owner-only cleanup、2330→2303→2330 first-useful depth、callback counter reconciliation 與 latency p50／p95／max／missing／negative。
- Preflight 現在同時驗 dated 30-target base checkpoint、28-target realtime extension 與 13-target Data Core convergence overlay；newer overlay 只覆蓋重疊 target，不覆寫歷史 checkpoint；digest 僅正規化 CRLF，保留 BOM 與其他 byte 差異。

## 驗證證據

- Full safe validation：`.tmp/validation/20260824-195959` 全數通過。
  - backend compileall passed。
  - backend pytest：`2107 passed, 801 warnings in 272.38s`。
  - frontend lint passed。
  - frontend TypeScript no-emit passed。
  - frontend Next.js 16.2.12 production build passed。
  - `git diff --check` passed。
- Backend checkpoint／overlay targeted：`7 passed`；原 remediation targeted `58 passed` 證據仍保留。
- Launcher recovery targeted：一般 Windows 權限 `3 passed`；sandbox 首次嘗試因 pytest temp lock PermissionError，不是 assertion failure。
- Offline acceptance harness：passed；3 個 switch step、10 個 callback 全部分類守恆，無 trial leak、負 latency 或 artifact leakage。
- UI Playwright：production build、獨立 port 3221、controlled fixtures，`58 passed`；涵蓋 SSE-first、GET failure、快速切股、共享更新狀態、投資組合與跨市場流程。
- 2026-08-25 preparation SourceOnly artifact：`artifacts/m5-source-only-prep-20260825.json`，result=`passed`；extension canonical SHA-256=`78f1709ab75b3d436482423e7ccf18ae1d64f5d671a495f50be118ba41ad6735`、30 targets、15 superseded base targets、0 mismatch。
- Preparation targeted regression：`33 passed`；PowerShell parser 0 error；offline live harness passed with 10 categorized callbacks。

## Checkpoint 邊界

- Base checkpoint SHA-256 維持 `8acbaea6fa4566416c67dc1e1745e4a080e2b6ee8e341fd1c0edc501f56badf2`，保留為 dated historical evidence。
- Extension checkpoint：`artifacts/acceptance-extension-checkpoint.json`，clean 28-target realtime overlay canonical SHA-256=`2ec7456200c310a778621df31747974cc468839c560d025680d870bc7d478619`。
- 後續 Data Core convergence overlay：`../tw-market-data-platform-convergence-20260825/artifacts/foundation-extension-checkpoint.json`，canonical SHA-256=`460903c9692e09e3e81315b12a6c39fac3f36fcfa3eb5c4176516b4190e453ba`；preflight 依 newer-overlay-wins 驗證重疊 target，不改寫舊 checkpoint evidence。
- Shared Data Core pre-commit overlay：`../tw-shared-data-core-convergence-20260826/artifacts/precommit-remediation-source-checkpoint.json`，canonical SHA-256=`5eec32a6e49a5e3e7d58c3b63d4a02dfdbda12d653430229d1339314188edf8d`；19 targets、零 mismatch，並以最新 validated-source precedence supersede 17 個先前 overlay entries。
- `scripts/omi-launcher.ps1` 是本任務開始前已存在的 dirty worktree state；本任務未修改它，但將 current hash 作 acceptance dependency capture，並由 full suite 與 launcher targeted tests 驗證。
- `scripts/invoke-mdf-m5-preflight.ps1` 因內嵌 extension SHA 而排除 extension target，改由每次 preflight self-hash。

## 剩餘風險／限制

- Runtime source adoption已完成，但post-close readiness不等於任何正式session pass；16:32的lease plan因當下已是`post_close`而回傳`VIEWER_LEASE_PLAN_UNFILLABLE`，不可為了製造pass而放寬session descriptor。
- Provider callback 的真實順序、正式成交／試撮配對、L5 first-useful latency 與 `delay_time` 單位仍需 live probe；raw delay unit 目前維持 `unknown`。
- RT-02 目前根除的是 phantom trade 與 cumulative integrity；沒有證據時仍不宣稱 provider exactly-once。
- 本任務 source 已納入整批 release integration；source publication 仍不等於 runtime adoption 或 live-session acceptance。

## 2026-08-26 主動排障決策

- 舊「確認基礎架構工作稿」heartbeat已暫停且任務已封存；不得重新啟用，避免舊30-target-only gate與新版extension overlay衝突。
- 新heartbeat只綁定本任務，08:20開始；第一次failure不是停止條件。Runtime／frontend／MCP／idle cleanup與localized task-owned source／harness問題由automation在安全邊界內修復、重驗並續跑。
- 08:20起執行SourceOnly、正式launcher adoption、最多180秒backend啟動、120秒frontend readiness、240秒idle cleanup與必要retry；沒有10:00或其他固定停止時間，只要仍能安全取得新證據或推進有效session gate就持續。Runtime乾淨後立即取得當下仍有效的session evidence。
- Source／config修正會使修正前session evidence失效；必須重建extension checkpoint、同步automation pin、重新adopt並從受影響最早gate重跑。
- Credential／entitlement／人工作業、外部owner持續阻擋、source ownership不明／廣泛drift、需要越界操作，或同一component blocker在完整診斷與至少兩輪給足等待的修復／重試後仍無新證據，才可暫停並通知。已錯過的session gate只能標pending並留待下個交易日，不得以後續時段補pass。

## 精確下一步

1. 2026-08-27 08:20 由同一heartbeat重新驗SourceOnly與正式launcher runtime，再於真實Preopen建立單一probe readiness；不得用post-close plan-unfillable補成readiness pass。
2. 同一交易日依序執行Preopen、Opening、Regular與Closing live gates；可安全修復failure先修正、重驗並繼續，錯過的gate保持pending並由同一automation續排。
3. 只有live artifact的callback、trial leak、latency、first-useful depth、symbol switch、lease cleanup與Market-State gates全部通過，且compare-to-off rollback與final validation完成，才把Runtime-accepted標為完成。

## 2026-08-26 morning execution

- `08:35` 首次 SourceOnly fail closed：11 個 realtime extension target 已被 2026-08-25 Data Core convergence checkpoint 合法 supersede，但 M5 preflight 尚未套用 newer overlay。保留 `artifacts/m5-source-only-takeover-20260826-0835.json`，未建立 lease、未動 runtime。
- 修正 `scripts/invoke-mdf-m5-preflight.ps1` 後，SourceOnly 同時驗 base 30 targets、realtime extension 30 targets、convergence 14 targets；effective overlay 33 targets、mismatch=0。Checkpoint guard `7 passed`。
- 第一次 sandbox `Prepare` 啟動的 backend 可達 `compare`，但 process lineage 在 sandbox 不可讀且 frontend `next dev` 反覆 `spawn EPERM`。normal Windows `Check` 證明 listener 52308 的原祖先鏈、health/ready、calendar與public schema；frontend gate fail closed。
- 只使用正式 launcher lifecycle 修復：零 global lease/bridge baseline 後送出 owner `Exit`，建立唯一 normal Windows launcher owner，再由 component-owned `RestartServices` exact cleanup orphan listener。`08:57:25` 新 listener 47556 的祖先鏈回 launcher 51752；compare、health/ready、public schema、frontend proxy、stdio MCP、zero baseline 全部通過。
- Viewer readiness `09:00:09` 通過 acquire/sample/owner-only release/idle cleanup，但它不是 Preopen evidence。Preopen 因沒有在時窗內取得 callback維持 `pending`。
- Opening live harness 在 lease acquisition 前揭露 PowerShell URL interpolation bug：`$encodedSymbol?diagnostic_limit` 被當成一個變數。改為 `${encodedSymbol}?diagnostic_limit`，新增 source guard、parser與 offline harness皆通過；重建 realtime extension checkpoint並重跑 SourceOnly/Check。修正完成已超過09:02，Opening維持 `pending`，不得用Regular補pass。
- Regular 60秒 `artifacts/session-regular-20260826.json` 通過：147 callbacks、27 unique cumulative advances、27 trade additions、119 same-cumulative suppressions、0 decreasing、0 trial leak、0 request error；2330 first-useful L5=6147ms，callback分類守恆、無負 latency、cleanup回零。
- A4 `artifacts/session-regular-symbol-switch-20260826.json` 通過：2330→2317→2330 first-useful L5=530/2559/2568ms；三段皆0 request error、0 trial leak、matching depth可用、cleanup回零。
- Market-State `artifacts/market-state-regular-20260826.json` 通過：headline fields使用resolved projection；TWSE/TPEX resolution IDs與index summary一致，current-session index缺資料保持honest missing；legacy與resolved breadth所有coverage/universe/reason equations對帳，未證明reason維持null。
- Morning checkpoint：`artifacts/m5-morning-status-20260826.json`。截至09:10 runtime仍為正式launcher-owned `compare`、health=`ok`、ready=`ready`、active leases=0、bridge=false。
- Morning live artifacts保留當時 checkpoint SHA-256=`29a74a6472285c17e7933276ecbd1f855a1a2b447762c306eb24380ffb9a34c6` 的原始provenance；10:25 local commit整理另建立上述clean 28-target realtime + 13-target convergence source overlay並重跑SourceOnly/offline guard，沒有重啟或重新adopt runtime。
- Remaining：13:25起獨立Closing auction/formal match gate；完成後才能做component-scoped `compare -> off` rollback與final validation。現在不可提前rollback，也不可把Regular evidence當Closing。

## 2026-08-26 Shared Data Core adoption recheck

- Automation實際於`16:20` Asia/Taipei觸發；原`DTSTART;TZID=Asia/Taipei:20260826T082000`被scheduler按`08:20Z`執行，當日Preopen／Opening／Regular／Closing真實時窗均已經過，四個gate對新source identity全部維持`PENDING`。
- 首次SourceOnly artifact `artifacts/m5-source-only-20260826-1620.json`因15個M5 overlay target與10個Data Core overlay target已被合法Shared Data Core source supersede而fail closed；未接受新hash、未回復正確source。
- Preflight新增第三層validated overlay，固定`precommit-remediation-source-checkpoint.json` SHA-256=`5eec32a6...`且要求`validation.result=passed`。`artifacts/m5-source-only-20260826-1624.json`通過：base 30、M5 28、Data Core 13、Shared Core 19 targets均零 mismatch，effective targets=35。Affected validation：dark-boundary `7 passed`；offline harness 10 callbacks passed。
- Sandbox `Prepare`只因process lineage不可讀而fail closed；完全相同參數在normal Windows permission重跑，`artifacts/m5-prepare-normal-permission-20260826-1624.json`通過，確認selected backend=`127.0.0.1:8400`、frontend=`127.0.0.1:3000`、named launcher lineage、`compare`、health／ready、frontend proxy、stdio MCP與global zero baseline。
- 因現有listener 08:57啟動、早於16:14 Shared Data Core checkpoint，不能把Prepare健康檢查冒充source adoption。先證明zero baseline後以正式launcher component-scoped `RestartServices`；`artifacts/m5-restart-shared-core-adoption-20260826-1632.json`通過，新listener 54792於16:29啟動且祖先鏈回原launcher 51752。Alembic read-only確認`20260826_0072`，Data Core catalog為30 datasets／21 operations。
- 120秒stable soak後的`artifacts/m5-check-readiness-shared-core-post-close-20260826-1632.json`如實fail；後續redacted diagnosis保存於`artifacts/m5-post-close-readiness-diagnosis-20260826.json`：global baseline為0，但common planner在`post_close`拒絕建立subscription route，detail code=`VIEWER_LEASE_PLAN_UNFILLABLE`；沒有lease id、沒有bridge process，after baseline仍為0。這是session eligibility fail-closed，不是credential／entitlement failure，也不得把KGI descriptor擴到post-close來製造pass。
- 16:26較早舊runtime readiness artifact只證明legacy runtime wiring，不能升格為Shared Data Core runtime readiness。下一個合法驗證面為2026-08-27真實Preopen；automation改用UTC `00:20Z`對應Asia/Taipei 08:20，避免再次偏移八小時。

## 2026-08-27 current Data Core live remediation

- Source-ready：`PASS`。Preflight 依序驗 base `8acbaea6...`、M5 `2ec74562...`、Data Core `460903c9...`、Shared Core `5eec32a6...`、architecture freeze `fd68817a...` 與本日 live-remediation overlay `3de4da96...`；effective targets=64、全部 mismatch=0。Freeze checkpoint 是 validated newer architecture source，沒有回復其正確變更。
- Runtime-adopted：`PASS`。正式 launcher 在 `08:56:12` component-scoped restart 到 listener 49884、selected backend `127.0.0.1:8400`；lineage、project root、Python、`compare`、health／ready、frontend proxy、stdio MCP 與 zero-lease baseline通過。Data Core catalog唯讀驗證32 datasets／22 operations，Alembic revision=`20260826_0072`。
- Runtime-accepted：`PENDING`。Opening、Regular與Market-State已有本日 evidence；Closing仍待13:25真實時窗。Preopen M5 callback artifact在後續 Market-State source與cleanup harness修正前取得，依同一source-identity規則只保留為已證明但不可升格的歷史 evidence；最終Preopen gate續排下一個交易日。
- 第一輪 current runtime 揭露兩個task-owned source bug：dashboard把Shared Data Core `unknown_count`誤當完整unknown partition，造成`coverage + unknown != universe`的500；derived stock lineage把`datetime`直接交給`json.dumps`，使scheduler反覆失敗。修正後17個targeted tests通過，dashboard 200、兩市場breadth classification／universe／reason equations均平衡，重啟後scheduler沒有再出現serialization failure。
- 第二輪 Market-State檢查揭露dashboard仍讀舊resolver shape，丟失current Data Core status／event time／trade date並輸出`resolution_version=unknown`。已改由`current_data_core.index`薄投影，不重選provider；TWSE／TPEX status、value、provider、source、event time、trade date、selection reason與decision usability對帳。`artifacts/market-state-regular-current-source-20260827.json`的index與breadth gates均通過。
- Readiness在 current backend source上完成單一2330 `acceptance_probe` acquire／release／idle cleanup；首次retry遇到另一owner的`acceptance_probe`，本任務未release，等對方自行清除與bridge自然idle後再跑即通過。
- Opening `08:58:28–08:59:28` session semantics通過：19 callbacks全部分類為auction evidence、0 trial leak、0 request error、三段L5 depth可用。原artifact只因另一acceptance owner在本任務release後重疊而記為global cleanup failure；本任務未release外部lease，`artifacts/m5-live-opening-cleanup-extension-20260827.json`證明對方自行release且240秒內global lease／bridge baseline回復，compound gate=`passed`。
- Live harness已根除上述cleanup誤判：owner-only release後最多240秒等待global lease baseline與bridge idle；外部overlap只記redacted boolean，不release unknown lease。Offline regression通過，checkpoint overlay已納入新harness hash。
- Regular `artifacts/m5-live-regular-current-source-retry-20260827-0908.json`通過：284 callbacks、3 baseline-only、150 cumulative advances／150 trade additions、127 same、4 decreasing、0 trial leak、0 request error；2330→2303→2330 first-useful L5=7186／2561／2556ms，全部callback分類守恆、無負latency。Owner cleanup後自然等待120.359秒，global leases=0、bridge=false。
- 截至09:12，current runtime與global baseline乾淨，維持`compare`等待13:25 Closing Auction／formal match；未提前rollback。若Closing通過，仍因final-source Preopen缺口由同一automation續排2026-08-28 08:20，不建立duplicate。

## 2026-08-27 Closing Auction／formal close

- 13:21 SourceOnly重驗通過：base、M5、Data Core、Shared Core、architecture freeze與live-remediation六層checkpoint均為零mismatch；current overlay仍為`3de4da962ae589dbef85a8fa5aaa7f177b89ddcfcb39da7caca803c8ab5c4a8c`，未接受drift。
- 13:22正式launcher `Check`通過：selected backend=`127.0.0.1:8400`、frontend=`127.0.0.1:3000`、listener 49884 lineage回launcher 45068；`compare`、health／ready、calendar、frontend proxy、stdio MCP與global zero-lease／bridge baseline均通過，因此沒有不必要重啟。
- `artifacts/m5-live-closing-current-source-20260827-1324.json`於13:24:18啟動，2330→2303→2330三段各120秒；第一段覆蓋13:25 Closing Auction，最後一段跨過13:30 formal match。共204 callbacks、119 auction additions、24 strict cumulative advances／24 trade additions、177 same-cumulative suppressions、0 decreasing、0 trial leak、0 request error，callback分類守恆且latency無負值。
- 最後2330段13:28:18–13:30:18有41 auction additions；跨過formal match後只有1次strict cumulative advance且只新增1筆trade，另有41次same cumulative與1次non-trade suppression，證明Trial != Trade且同／倒退cumulative不新增成交。三段first-useful L5=6665／2588／2566ms。
- 本任務owner-only release後自然等待120.299秒，global leases=0、bridge=false；無external overlap，未release任何unknown lease。獨立判定保存於`artifacts/m5-closing-evaluation-current-source-20260827.json`。
- `artifacts/market-state-post-close-current-source-20260827.json`獨立通過。Dashboard headline維持current Data Core projection；TWSE／TPEX的status、value、provider、source、event time、trade date、selection reason與decision usability全部對帳，legacy proxy仍`official=false`／`decision_usable=false`。兩市場breadth的classification、coverage+unknown=universe與reason bucket方程均平衡，未證明reason維持null。
- Post-close cache-only index evidence如實為`stale`／provisional／not decision-usable，`official_close_confirmed=false`；Closing的KGI formal-match語意通過不會冒充Data Core官方收盤finalization。
- Runtime-accepted仍為`PENDING`：Opening、Regular、Closing、cleanup與Market-State為current-source pass，但final-source Preopen仍缺真實時窗；不得用後續session補造。13:35另一個Codex Bridge對話依過時結論提前執行compare→off；`artifacts/m5-rollback-compare-to-off-20260827-1335.json`與`m5-final-off-check-20260827-1336.json`只保留為owner衝突證據，不是本任務final rollback，也不授權升格runtime-accepted。
- 本任務第一次用正式launcher恢復compare後，外部對話於13:41再次切回off並留下frontend未ready；完整診斷與第二輪component-scoped修復後，`artifacts/m5-check-restored-compare-retry2-20260827-1349.json`曾在120秒stable soak後通過compare、frontend、MCP與zero baseline。然而外部owner於13:51第三次切回off，證明不是單一transient。
- Final safe validation：`.tmp/validation/20260827-133630`通過backend compileall、frontend TypeScript noEmit與`git diff --check`。另有本輪targeted Market-State／lineage `17 passed`、checkpoint guard `7 passed`與新版live harness offline 10 callbacks regression通過。
- `artifacts/m5-final-status-20260827.json`與`m5-runtime-owner-conflict-recovery-20260827.json`都只作先前snapshot；current terminal evidence為`artifacts/m5-terminal-external-runtime-owner-blocker-20260827.json`。兩輪完整component-scoped修復都被同一外部runtime owner覆寫，已達runbook的external-owner滯澀停止條件。
- 停止前唯讀off check通過：current listener=51132、launcher=13480、health／ready、frontend proxy、stdio MCP與global leases=0／bridge=false。沒有第三輪互相覆寫、沒有broad-kill或unknown lease release。`runtime_accepted=false`、`release_ready=false`維持不變。
- 同一automation設為`PAUSED`，不建立duplicate。恢復條件：先停止或協調會送出off-mode launcher transition的Codex Bridge對話，再於下一個有效Preopen前恢復本automation；先建立單一compare owner並重驗，取得final-source Preopen後才可做真正final rollback。

## 2026-08-27 本輪權威 final handoff

- 本段依使用者本輪明確指令「全部今日可取得 gates 通過後執行 component-scoped compare→off rollback」記錄最終 current truth；上節保留另一既有 automation 依舊策略維持 compare 的 owner-conflict 稽核，不覆蓋本段。
- 競態清除後，只透過正式 launcher 執行 `Prepare -ExpectedMode off`。三次中間診斷分別如實留下 `RUNTIME_LINEAGE_PROBE_UNAVAILABLE`、`RUNTIME_IDENTITY_MISMATCH` 與 `COMPARE_BOOTSTRAP_FAILED`；沒有 broad-kill、沒有 unknown lease release、沒有 DB/cache rollback。
- `artifacts/m5-final-rollback-after-race-cleared-20260827-1351.json` 通過：launcher PID=13480、listener PID=51132、父鏈回到 `omi-launcher.ps1`，effective mode=`off`；health／ready、public schema、frontend proxy、stdio MCP、64-target source、global zero lease 與 bridge idle 全部通過。
- `artifacts/m5-final-off-check-after-race-20260827-1352.json` 與 `artifacts/m5-final-off-stable-check-after-race-20260827-1355.json` 在分離時間點均通過，PID 與 mode 未再漂移。
- Final gate：`PASS`=SourceOnly、runtime compare preflight、Opening、Regular／Level 5／symbol switch、Market-State、Closing Auction／formal match、compare→off rollback、off stable checks、final validation；`PENDING`=final-source Preopen；`FAIL`=none。`runtime_accepted=false`、`release_ready=false`、verdict=`partial_pending_preopen`，今天不可標記可封版。
- 另一既有 automation 已因 owner conflict 自行設為 `PAUSED`，本輪不建立 duplicate。若要在下一個交易日補 Preopen，必須先協調單一 runtime owner，再透過正式 launcher rearm process-scoped `compare`；不得用今天後續 session 補造 Preopen。
