# 進度紀錄

## Status

- Current phase：Milestone 7 source integration 完成；runtime adoption 等待獨立授權
- Last updated：2026-08-14 21:19 Asia/Taipei
- Production implementation authorized：yes
- Formal runtime adoption authorized：no
- Commit/push/PR authorized：no
- Product source changed in this task：yes

## Completed

- 已完整審查使用者提供的 `C:\Users\thoma\Downloads\OMI_台股資料可靠性與自癒機制根除工程書_20260814.txt`。
- 已對照 repo/global `AGENTS.md`、`docs/product/`、`docs/architecture/BackendArchitecture.md` 與既有長專案格式。
- 已將原工程書的六類問題收斂成七個可驗證 milestone，補上 integration baseline、compatibility、runtime adoption 與 stop-and-fix gate。
- 已確認 index direct route、summary 與 AI `market.indices` 存在不同選源路徑，規劃改由 canonical resolver 統一。
- 已確認 response budget 需要 caller explicitness provenance 與 payload-level adaptive ceiling，不能用全域 max 靜默放大。
- 已確認 source-health 問題同時包含舊 target 與舊 provider generation；canonical stale `target=all` 不能因 expired 被當歷史資料忽略。
- 已確認 quote fixed-slot scheduler 是 bounded universe，不足以支撐無條件 `target=all`。
- 已確認 scheduler 已有 startup catch-up；主要故障是 expected trade date 沒有完整傳入 worker，以及 job success 未驗證實際 dataset 日期。
- 已建立本目錄 `Prompt.md`、`Plan.md` 與本 `Progress.md`；尚未修改 production source。
- 使用者已於 2026-08-14 授權依本長專案進行根修。
- Milestone 0 已完成 target owner/caller/test、dirty overlap、DB、contract 與 runtime baseline。
- Milestone 1 已完成 market-owned pure Taiwan index resolver、bounded acquisition policy、resolution identity/provenance、direct/summary/AI/persistence additive projection與相容性回歸。
- Milestone 2 已完成 response budget requested/default/effective provenance、payload-level bounded adaptive ceiling、explicit hard-limit 保護與 final serialized envelope byte gate。
- Milestone 3 已完成 source-health logical scope/provider generation lifecycle、operational/historical 預設分流、canonical all-target stale 保留與 additive counts/query contract。
- Milestone 4 已完成 quote request-live/scheduler-contract/provider-availability 三軸、bounded universe digest/target、slot-symbol coverage 與 scheduler capture provenance。
- Milestone 5 已完成 release-aware expected date 強制工作目標、逐 required source postcondition、結構化失敗結果、歷史 retry date-target 相容、bounded repair controller 與 source-health repair state projection。
- Milestone 6 已完成 backend-owned `omi.status-dimensions.v1` 四軸狀態分類、source-health direct/snapshot projection、AI v4 evidence/passport、MCP 摘要保留與 Frontend OMI dock 呈現；legacy status 欄位保持不變。
- Milestone 7 source integration 已完成 public contract snapshot 重產、backend/frontend safe validation、完整 Git whitespace 檢查與唯讀 live runtime/job evidence；尚未執行正式 runtime adoption。

## Validation evidence

- Integration base：branch `codex/tw-etf-provider-normalization`、HEAD `46c37b3eb031e05792f0706e7437e6d46079528d`。
- `git status --short`：規劃時共有 133 筆既有 modified/untracked entries；全部視為使用者或其他流程的既有工作，未 revert、stage、commit 或 push。
- Index source chain：`backend/app/market/indices.py` 的 direct intraday 與 `_market_index_summary()` 不同；`backend/app/ai/market_context/taiwan_market.py` 再投影 AI `market.indices`。
- Daily refresh source chain：`backend/app/jobs/scheduler.py` 會計算 expected date，但 worker 參數未完整使用；`backend/app/market/daily_metrics_backfill.py` 會從可能 stale 的 `MarketDailyPrice` 推導日期。
- 唯讀 DB evidence：`institutional_trade_daily` 最大日期為 2026-08-12；四個 target 2026-08-13 的 `scheduler.market_daily_refresh` job 標為 success，但 result 仍只處理到 2026-08-12、`fetched_count=0`。
- 唯讀 source-health evidence：TW snapshot 共 201 筆，包含 current/available/stale/empty/partial/pending 與舊 target/provider generations。
- Runtime evidence：2026-08-14 審查時 `127.0.0.1:8400` 無法連線；最後 launcher log 只代表先前選擇，尚無 current runtime adoption proof。
- 本階段未執行 provider refresh、DB write、backend/frontend test、build、runtime start/restart 或 MCP reload；這符合 docs-only Tier 0 範圍。
- Planning artifact Tier 0：三份文件皆通過 strict UTF-8 解碼、必要章節、final newline、trailing-whitespace 與 Git whitespace 檢查；目錄仍為 untracked，未 stage。
- Runtime evidence script（2026-08-14 19:58）：latest launcher log 指向 backend `8400`／frontend `3000`，但 health、`/api/ai/tools`、provider-events 三個 GET 均無法連線；source work 不得宣稱 runtime adoption。
- 唯讀 SQLite baseline：DB `22,442,250,240` bytes；TW source-health 201 筆（available 66、current 95、empty 10、partial 7、pending 3、stale 20）。
- 唯讀 SQLite max dates：`market_daily_price=2026-08-13`、`institutional_trade_daily=2026-08-12`、`market_index_daily_stat=2026-08-14`、quote/index contract snapshots `2026-08-14`。
- False-success fixture：最近四個 `scheduler.market_daily_refresh` target 都是 `2026-08-13` 且 status=success，但 result `end_date=2026-08-12`、`fetched_count=0`、`skipped_existing_count=2`。
- Milestone 0 index baseline：safe backend compileall、Git diff check 通過；index/contract focused pytest `107 passed, 3 subtests passed`，log `.tmp/validation/20260814-200233`。
- Milestone 1 stop-and-fix：首次 validation 發現 `calendar_status -> market_chips -> indices` circular import；已將 `indices` 的 calendar status 改為 function-local lazy import，未帶著失敗前進。
- Milestone 1 final validation：compile、targeted pytest、`git diff --check` 全部通過；pytest 為 `140 passed, 3 subtests passed`，log `.tmp/validation/20260814-201407`。
- Milestone 2 stop-and-fix：新增 provenance 後兩個原本接近 32 KiB 邊界的 default response 出現不必要 trimming；已改由含 projection 的 final-envelope overhead 觸發 bounded adaptation，explicit request 不參與放大。
- Milestone 2 final validation：AI capability/envelope/outward/MCP schema regression 全部通過；pytest 為 `130 passed, 27 subtests passed`，log `.tmp/validation/20260814-202403`。
- Milestone 3 final validation：provider health、AI supplemental/source-health、freshness guard 與 market projection regression 全部通過；pytest 為 `144 passed, 21 subtests passed`，log `.tmp/validation/20260814-202954`。
- Milestone 4 final validation：Taiwan source health、quote replay/components、intraday remediation 與 scheduler regression 全部通過；pytest 為 `100 passed, 13 subtests passed`，log `.tmp/validation/20260814-203726`。
- Milestone 5 targeted validation：expected-date、JobRun outcome、calendar/retry、startup/interval repair、lease/backoff/max-attempts/provider cooldown 與 source-health repair projection 全部通過；pytest 為 `73 passed`。
- Milestone 6 targeted validation：status taxonomy、provider/source health、AI supplemental/capability/envelope/outward contract、MCP schema/server regression 全部通過；pytest 為 `210 passed, 50 subtests passed`。Frontend `npm run lint` 與 `npm exec tsc -- --noEmit --incremental false` 皆通過。
- Public contract snapshot 已由 generator 重產：digest `120d494ae17559caa4f1b80ff9cbfa5cea651568cc07ec04cfd887c7e8891de4`、22 targets、66 capabilities；重產後 MCP schema/server parity 為 `33 passed, 2 subtests passed`。第一次從 repo root 執行因 `app` import root 不正確而 collection 失敗，改由 `backend` 工作目錄重跑即通過。
- Milestone 7 safe backend validation：`.tmp/validation/20260814-210959`；compileall 通過、完整 backend pytest `1811 passed, 801 warnings`、`git diff --check` 通過。
- Milestone 7 safe frontend validation：`.tmp/validation/20260814-211416`；lint、TypeScript no-emit typecheck 與 `git diff --check` 全部通過；未執行 build/E2E。
- Live read-only runtime evidence：launcher 最後選擇 backend `127.0.0.1:8405`；backend PID 35636 與 frontend PID 8852 均於 2026-08-13 20:44 啟動，早於本次 source 變更。`/api/system/health` 為 ok，但 `/api/market/source-health` 尚無 `status_dimensions`，證明 running runtime 未採用本次 build/source。
- Live read-only job evidence：現行 runtime 今日仍建立未含 `request.expected_trade_date` 與 `result.postcondition` 的 scheduler jobs；歷史 false-success rows 仍保留。未呼叫 retry/refresh、未寫 DB。

## Decisions made

- 長專案以「先真相、後自癒」執行；沒有嚴格 expected-date outcome 前，不啟用 repair loop。
- Index resolver 分成 bounded acquisition 與 pure resolution，讓 direct API、summary、AI 與 persistence 共用同一 resolved output。
- Response budget 的 caller explicit limit 永遠是 hard limit；default adaptive 只能在 payload-level ceiling 內調整，並量 final serialized envelope。
- Source health 採 logical scope/active generation；operational 與 historical 分開，但歷史資料仍保留可查。
- Quote freshness 分成 request-live、scheduler-contract、provider-availability，scheduler scope 必須公開 universe/digest/coverage。
- Status taxonomy 使用 additive/versioned contract；保留 legacy `status`、`problem_count` 與 `evidence.capability_status`。
- 目前 dirty worktree 是 integration base，後續每個重疊檔案先保存 baseline，採 localized patch，不大範圍 rewrite。
- Formal runtime adoption、commit/push/PR 都保持獨立授權 gate。

## Known issues / risks

- 目前 133 筆 dirty entries 與本專案可能重疊，尤其是 indices、AI capability/envelope、config/jobs、schema/tests 與 MCP snapshot；實作前必須逐檔辨識既有 hunk。
- SQLite 約 22 GB；任何 validation 都要優先 read-only、targeted，不能複製／重建／全庫掃描當成預設。
- Active provider/scope generation 尚未決定落在既有哪個 registry；若選錯位置會建立第二份 truth source。
- `problem_count` 已有 consumer 語意；直接改成 operational-only 可能造成 breaking behavior，必須 additive migration。
- Quote universe 可能隨設定/watchlist 改變；digest、effective time 與 required slot 必須共同保存，否則重放時無法解釋 coverage。
- Official release window、休市與盤後發布延遲會影響 expected date；不能把 calendar date 直接當 trade/release date。
- 審查時 backend runtime 不可用，尚未 replay 早上精確的 35,901-byte failure；Milestone 0 必須保存代表 fixture 後再改 budget。
- 自癒若在 source-health 判定仍不可信時提早開啟，可能形成錯誤 refresh/retry storm；因此 repair loop 明確排在 outcome truth 之後。
- Running backend/frontend 都早於本次修改；目前只能宣稱 source/test 完成，不能宣稱 runtime adoption。正式採用需走 launcher 的 component-scoped restart，之後再驗證 owner/path/listener、health、status taxonomy、expected-date postcondition 與 MCP session parity。

## Next step

- 等待使用者獨立授權 OMI component-scoped runtime restart；授權後完成 Milestone 7 live adoption 與 MCP session-preserving smoke。未獲授權前不重啟、不觸發 provider refresh、不修改 DB。
