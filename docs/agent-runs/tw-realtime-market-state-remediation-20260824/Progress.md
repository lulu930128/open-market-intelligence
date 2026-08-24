# Progress

## 狀態

- Source implementation：完成。
- Source-ready：通過；base checkpoint 與 28-target extension overlay 都由 SourceOnly preflight 驗證為零 mismatch。
- Runtime-adopted：未執行；使用者已授權 2026-08-25 排程只透過正式 launcher 完成 component-scoped adoption／repair。
- Runtime-accepted：未執行；仍需下一個正式台股交易 session 的 bounded live acceptance。
- Scheduled acceptance：heartbeat `omi-tw-realtime-m5-live-acceptance` 已建立並啟用，綁定本任務，2026-08-25 08:20 起主動待機、component-scoped runtime adoption／repair、現場修復與重驗。

## 已根除的 source 問題

- Regular／Post-close 第一筆 eligible positive cumulative callback 只建立 baseline，不再新增 phantom trade；只有下一筆 strict cumulative advance 才能進 trade buffer。
- Same／decreasing cumulative、trial callback、duplicate signature 與 cross-date rejection 都有 bounded counter 與明確 projection action。
- Diagnostic event history 預設不出現在 GET／SSE；只有 `diagnostic_limit` 明確開啟才回傳去識別化事件，raw payload、account、credential 與 lease id 不會進 artifact。
- Frontend L5 不再等待 GET quote-depth baseline；matching、live、non-stale SSE depth 可先顯示。
- Hook return boundary 依目前 `stockId` 隔離 quote depth、stream、replay 與 load state，舊 request 即使晚回也不會在切股後 outward。
- Index Resolver additive outward `selected_provider`、`selected_authority`、`selected_finalization`、`official_source`、`official_close_confirmed`、`provisional_estimate`；dashboard 只投影 Resolver 語意，legacy `official/provisional` 保留 compatibility。
- Thin MCP Taiwan dashboard schema snapshot 已重生，digest=`70479f355559963757862b1b562e0ec4659197327744ac240de751afba36b381`。
- 新增 executable M5 live-session harness：支援 `OfflineFixture` 與 bounded `Live`、`acceptance_probe` lease、heartbeat、owner-only cleanup、2330→2303→2330 first-useful depth、callback counter reconciliation 與 latency p50／p95／max／missing／negative。
- Preflight 現在同時驗 dated 30-target base checkpoint 與 28-target extension overlay；13 個既有 base drift 由 extension 明確 supersede，不覆寫歷史 checkpoint；digest 僅正規化 CRLF，保留 BOM 與其他 byte 差異。

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
- Final SourceOnly preflight artifact：`.tmp/m5-source-only-release-20260824-final-v2.json`，result=`passed`；extension SHA-256=`91d03b633749a0f98da6bf16ce2d4e43ac481bebb339ddd3ffd94cd9f9c621dd`、28 targets、13 superseded base targets、0 mismatch。

## Checkpoint 邊界

- Base checkpoint SHA-256 維持 `8acbaea6fa4566416c67dc1e1745e4a080e2b6ee8e341fd1c0edc501f56badf2`，保留為 dated historical evidence。
- Extension checkpoint：`artifacts/acceptance-extension-checkpoint.json`，SHA-256=`91d03b633749a0f98da6bf16ce2d4e43ac481bebb339ddd3ffd94cd9f9c621dd`。
- `scripts/omi-launcher.ps1` 是本任務開始前已存在的 dirty worktree state；本任務未修改它，但將 current hash 作 acceptance dependency capture，並由 full suite 與 launcher targeted tests 驗證。
- `scripts/invoke-mdf-m5-preflight.ps1` 因內嵌 extension SHA 而排除 extension target，改由每次 preflight self-hash。

## 剩餘風險／限制

- Source-ready 不代表現有 backend／frontend process 已載入本次 source；未重啟、未驗證 runtime SHA adoption。
- Provider callback 的真實順序、正式成交／試撮配對、L5 first-useful latency 與 `delay_time` 單位仍需 live probe；raw delay unit 目前維持 `unknown`。
- RT-02 目前根除的是 phantom trade 與 cumulative integrity；沒有證據時仍不宣稱 provider exactly-once。
- 本任務 source 已納入整批 release integration；source publication 仍不等於 runtime adoption 或 live-session acceptance。

## 2026-08-25 主動排障決策

- 舊「確認基礎架構工作稿」heartbeat已暫停且任務已封存；不得重新啟用，避免舊30-target-only gate與新版extension overlay衝突。
- 新heartbeat只綁定本任務，08:20開始；第一次failure不是停止條件。Runtime／frontend／MCP／idle cleanup與localized task-owned source／harness問題由automation在安全邊界內修復、重驗並續跑。
- Source／config修正會使修正前session evidence失效；必須重建extension checkpoint、同步automation pin、重新adopt並從受影響最早gate重跑。
- 只有credential／entitlement／人工作業、外部owner逾有效時窗、source ownership不明／廣泛drift、需要越界操作或正式session已錯過，才暫停並通知。

## 精確下一步

1. 2026-08-25 08:20 由本任務heartbeat執行SourceOnly、正式launcher adoption／Check與單一probe readiness。
2. 同一交易日依序執行Preopen、Opening、Regular與Closing live gates；可安全修復failure先修正、重驗並繼續，不等待隔日。
3. 只有live artifact的callback、trial leak、latency、first-useful depth、symbol switch、lease cleanup與Market-State gates全部通過，且compare-to-off rollback與final validation完成，才把Runtime-accepted標為完成。
