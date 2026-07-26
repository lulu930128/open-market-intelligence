# Progress

## Status

- Current phase: completed
- Last updated: 2026-07-24 Asia/Taipei
- Public contract: `omi.decision.v4`

## Completed

- 已完成 live 問題清單與 repo owner 對照。
- 已重現 US intraday、TW daily OHLCV、source-health projection、multi-intent、refresh/fill、trust、projection metadata、rejected-envelope 與 standalone MCP business-error 問題。
- 已確認 OMI Dock 送出 v4 request 並以 canonical answer/evidence/decision 欄位優先讀取。
- 已建立本續作的目標、non-goals、里程碑、stop-and-fix 規則與 done criteria。
- Canonical v4 projection 改用 mode projection 前的完整 result，修正 US
  intraday、TW daily OHLCV 與 source-health 空殼。
- Multi-intent 會合併 quote、chart、technical、chips、broker branch 與
  freshness；quote/broker fast path 只處理純意圖。
- 新增 `omi.refresh.reconciliation.v1`，對帳 tool attempts、final payload、
  quality limitations 與 remaining fill actions；成功但無 payload 不會假裝完成。
- Quality status 改用 realtime/freshness/payload/legacy 的明確 authority；
  producer 補上台股 lots、美股 shares；source trust 與 decision readiness 分離。
- Projection metadata 可說明 trimmed fields/lists/capabilities；rejected target
  使用 unresolved identity 與精簡 envelope。
- Repo MCP、standalone `OMI_search` 文件與 business-error transport semantics
  已對齊；`TARGET_NOT_FOUND` 保持 `isError=false`。
- `diagnostics.source_health` 在 bounded entries 上增加
  `returned_entry_count`、`returned_count`、`truncated` 與 `is_partial`。
- Repo MCP capability enum 已和 backend 38 個 capability registry 完全一致，
  並有 regression test 防止 transport schema 漂移。
- 4 KiB response budget 增加最終 hard-cap envelope；保留 v4、target、quality
  摘要、limitations 與 projection metadata，不再允許 `budget_met=false`。

## Validation evidence

- Baseline targeted contract tests: `63 passed in 4.35s`。
- Canonical/multi-intent/refresh targeted regression:
  `74 passed in 6.31s`。
- Final contract-focused regression：`69 passed, 14 subtests passed in 1.67s`。
- Rejected-target integration：`1 passed in 1.85s`，serialized response
  小於 8 KiB。
- Final backend safety profile：
  - compileall passed
  - `995 passed in 93.24s`
  - `git diff --check` passed
  - logs: `.tmp/validation/20260724-224613`
- Frontend safety profile：
  - lint passed
  - TypeScript noEmit passed
  - `git diff --check` passed
  - logs: `.tmp/validation/20260724-221653`
- Standalone `OMI_search`：`26 tests passed in 2.239s`。
- Live runtime：
  - backend `127.0.0.1:8400`, listener PID `62248`
  - health root `C:\project\Open Market Intelligence`
  - reported interpreter `.venv\Scripts\python.exe`
  - frontend `127.0.0.1:3000`, listener PID `43384`
- Live HTTP：
  - 2330 quote 為 `latest_completed_session`、`facts_usable=true`、
    `volume_unit=lots`。
  - 2330 daily OHLCV 回 30 points、`volume_unit=shares`、
    `trade_value_unit=TWD`。
  - AAPL bounded refresh 執行 `us.read_intraday_trend` success，36 筆中回
    5 筆，保留 latest point/provider/source/event time；因 event age 1,551
    秒明確標 stale，沒有重複 fill action。
  - source-health `entry_count=200`、`returned_count=20`、
    `problem_count=65`、`truncated=true`，entries 有定位欄位。
  - 4 KiB hard-cap response 為 3,124 bytes、`budget_met=true`。
  - rejected target response 為 3,410 bytes、identity unresolved、零 tool
    runs、零 fill actions、沒有 quality。
- Live SSE：18 events，包含 evidence、delta、final、done；final 是
  `omi.decision.v4` completed response。
- Repo MCP stdio：
  - protocol `2025-06-18`
  - public tools `omi.ask`、`omi.ask_stream`
  - success 與 `TARGET_NOT_FOUND` business rejection 都是 `isError=false`
- Standalone `OMI_search` stdio：
  - protocol `2025-06-18`
  - public tool `omi.search`
  - schema v4-only，success/rejected semantics 與 repo MCP 一致。

## Decisions made

- 將三個 payload 空殼視為雙重 projection 的共同缺陷。
- Multi-intent selection 與 reader routing 必須同時修正。
- Refresh success 必須在 quality/fill-plan 前對帳。
- External adapter 的 business rejection 必須與 repo MCP 一致。
- Fill plan 保持 continuation，不遞迴自動執行；主請求 refresh 的實際結果由
  `execution.refresh_reconciliation` 表達。
- Status source disagreement 保留為 issue，但不再讓舊 slot 任意覆蓋 authoritative
  realtime/payload。
- Passport top-level trust tuple 保留 source semantics；decision quality 放在
  `passport.decision_readiness`。

## Known issues / risks

- Worktree 已有大量使用者或先前流程的 v4 變更；所有修改必須局部疊加，不能 revert。
- 目前 8400 是本次驗證直接從 checkout `.venv` 啟動的 backend process，
  不是由 launcher 重新建立；下次完整 launcher restart 應再次確認 selected
  PID/port。
- AAPL live provider response 的最新事件比檢查時間落後約 26 分鐘，故契約
  正確保留 stale/blocked decision readiness；這是當下資料狀態，不是零值或
  projection 缺失。
- 本次最終變更集中 backend/contract；frontend lint/typecheck 已通過，但未
  另外跑 build/E2E，因沒有新增 frontend interaction。

## Next step

- 由使用者檢視整個既有 dirty worktree 的發布範圍；只有在明確確認後才做
  staging、commit 或 push。
