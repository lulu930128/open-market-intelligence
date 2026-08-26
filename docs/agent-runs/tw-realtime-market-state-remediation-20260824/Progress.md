# Progress

## 狀態

- Source implementation：完成。
- Source-ready：通過；30-target base、28-target realtime extension 與 13-target Data Core convergence overlay 形成 33 個 effective targets，SourceOnly preflight 為零 mismatch。
- Runtime-adopted：通過；2026-08-26 正式 launcher-owned runtime 維持 `compare`，health／ready、frontend proxy、stdio MCP 與 zero-lease baseline 均通過。
- Runtime-accepted：morning partial；Regular、2330→2317→2330 symbol switch 與 Market-State 通過，Preopen／Opening 保持 `pending`，Closing 尚未到時窗。
- Scheduled acceptance：morning job `0b4ecca2-0481-4674-9b68-76ba9b661800` 已 completed；Closing、`compare -> off` rollback 與 final validation 仍待後續正式時窗，不在本 checkpoint commit 執行。

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
- `scripts/omi-launcher.ps1` 是本任務開始前已存在的 dirty worktree state；本任務未修改它，但將 current hash 作 acceptance dependency capture，並由 full suite 與 launcher targeted tests 驗證。
- `scripts/invoke-mdf-m5-preflight.ps1` 因內嵌 extension SHA 而排除 extension target，改由每次 preflight self-hash。

## 剩餘風險／限制

- Source-ready 不代表現有 backend／frontend process 已載入本次 source；未重啟、未驗證 runtime SHA adoption。
- Provider callback 的真實順序、正式成交／試撮配對、L5 first-useful latency 與 `delay_time` 單位仍需 live probe；raw delay unit 目前維持 `unknown`。
- RT-02 目前根除的是 phantom trade 與 cumulative integrity；沒有證據時仍不宣稱 provider exactly-once。
- 本任務 source 已納入整批 release integration；source publication 仍不等於 runtime adoption 或 live-session acceptance。

## 2026-08-26 主動排障決策

- 舊「確認基礎架構工作稿」heartbeat已暫停且任務已封存；不得重新啟用，避免舊30-target-only gate與新版extension overlay衝突。
- 新heartbeat只綁定本任務，08:20開始；第一次failure不是停止條件。Runtime／frontend／MCP／idle cleanup與localized task-owned source／harness問題由automation在安全邊界內修復、重驗並續跑。
- 08:20～10:00保留給SourceOnly、正式launcher adoption、最多180秒backend啟動、120秒frontend readiness、240秒idle cleanup與必要retry；不因短暫慢啟動或單一session窗口經過而提前停止。Runtime乾淨後立即取得當下仍有效的session evidence。
- Source／config修正會使修正前session evidence失效；必須重建extension checkpoint、同步automation pin、重新adopt並從受影響最早gate重跑。
- Credential／entitlement／人工作業、外部owner逾有效時窗、source ownership不明／廣泛drift或需要越界操作可提前暫停並通知；其餘可修復問題持續到10:00。已錯過的Preopen／Opening只能標pending並留待下個交易日，不得以Regular補pass。

## 精確下一步

1. 2026-08-26 08:20 由本任務heartbeat執行SourceOnly、正式launcher adoption／Check與單一probe readiness；morning remediation最晚持續到10:00。
2. 同一交易日依序執行Preopen、Opening、Regular與Closing live gates；可安全修復failure先修正、重驗並繼續，不等待隔日。
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
