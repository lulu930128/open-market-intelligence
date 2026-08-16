# 進度紀錄

## Status

- Current phase: remediation complete
- Last updated: 2026-08-13 20:15 Asia/Taipei
- Implementation authorized: yes
- Runtime adoption authorized: yes
- Product source changed in this task: yes

## Completed

- 已完整讀取使用者提供的 `OMI_Technical_Analysis_Repair_Plan_2026-08-12.txt`。
- 已對照 repo `AGENTS.md`、`docs/product/`、`BackendArchitecture.md`、technical indicator/report/structure、AI capability/v4、MCP snapshot 與相關 tests。
- 已確認底層已有 MA、Volume MA、EMA/MACD、RSI、ATR、DMI/ADX、ROC、MFI、Donchian、Bollinger、KD 與 Support/Resistance。
- 已確認 `_round_price()` 對 100 元以上價格取整，會造成合法價格失真。
- 已用唯讀 DB 查詢確認 2408 於 2026-08-12：high `511.0`、close `482.5`、price change `-6.5`。
- 已確認 current weekly/monthly aggregation 沒有 completed/provisional status。
- 已確認 RSI 為 rolling simple-average gain/loss、EMA/MACD 從第一筆 seed、KD 為 SMA-smoothed RSV；目前 outward parameters 未完整表達方法與 warm-up。
- 已確認 canonical outward readiness 由 `evidence.capability_status` 擁有，資料由 `evidence.data[capability_id]` 提供。
- 已確認 MCP offline snapshot 必須由 backend registry generator 產生，不能手工維護第二份 market contract。
- 已建立本長專案 `Prompt.md`、`Plan.md` 與本 `Progress.md`，將實作鎖在使用者核准之後。

## Validation evidence

- 唯讀 DB：2408 latest rows 包含 `2026-08-12 close=482.5 high=511.0 low=480.5`。
- Pure function：`_round_price(482.5)=482.0`、`_round_price(505.5)=506.0`、`_round_price(100.5)=100.0`。
- Targeted baseline（從 `backend` cwd，repo-local basetemp、`-p no:cacheprovider`）：`138 passed, 20 subtests passed, 2 failed`。
- 兩個既有失敗皆為 MCP offline snapshot digest 與目前 dirty backend registry 不一致；不是 technical formula failure，但在 Milestone 0 前必須修復或隔離。
- Current branch：`codex/tw-etf-provider-normalization`。
- Current worktree：大量既有 backend AI、US SEC、market、frontend 修改；本規劃未 revert、覆寫、commit 或 push。
- Planning artifact Tier 0：三份文件皆通過 strict UTF-8 解碼、保有 final newline、無 trailing whitespace，必要章節與 approval gate 均存在。
- `git diff --check -- docs/agent-runs/tw-technical-analysis-evidence-20260812`：通過；目錄仍為 untracked，未 stage。
- 使用者已於 2026-08-12 核准依本計畫連續實作，並明確包含 formal runtime adoption。
- Integration base：branch `codex/tw-etf-provider-normalization`、HEAD `46c37b3eb031e05792f0706e7437e6d46079528d`；保留目前所有既有 dirty work，不另行 reset 或覆寫。
- Milestone 0 初跑：`173 passed, 235 subtests passed, 5 failed`；五個失敗皆為既有 registry/MCP count、enum 與 snapshot 漂移。
- Milestone 0 stop-and-fix recheck：原五個失敗 `5 passed`。
- Milestone 0 完整聚焦 baseline：`178 passed, 235 subtests passed`，backend manifest 與 MCP snapshot digest 均為 `1e24f8184d7c0c303cb635fec555f5297dd955bd658318bca3ee1d95fde39ab6`。

## Decisions made

- 長專案採「核准後單次連續執行＋內部 milestone gate」，不要求使用者每階段重複下指令。
- 第一個 production milestone 不只修 projection；price precision、period completeness、method/warm-up 與 raw corporate-action semantics 是同一個 outward safety gate。
- `technical.indicators` 不承擔 high-level signal/score；raw indicators 與 decision structure 分開。
- Swing/Pivot 是 Fib、Divergence、Breakout retest 與未來 Chart Pattern 的共同 dependency，必須先做且禁止 look-ahead。
- Same-bar breakout rejection 與 post-confirmation failure 分開建模。
- Volume Profile／AVWAP 的 bar-derived 結果屬 approximation，不能宣稱逐筆真值。
- Active Radar scoring 不在未驗證狀態下切換；新 evidence 先 shadow。
- MCP offline snapshot digest mismatch 已於 Milestone 0 修復；後續新增 capability 後仍必須由 generator 重建並維持 parity。

## Known issues / risks

- `capability_contract.py`、`capability_resolution_registry.py` 與相關 contract tests 正在被其他 dirty work 修改，後續實作有真實 merge/ownership 風險。
- 目前 MCP snapshot 已和 baseline backend registry 一致；後續每次 registry 變動都必須重新驗證 digest parity。
- 目前 indicator 名稱不足以唯一決定算法；若直接公開會和券商／其他 library 產生無法解釋差異。
- Current weekly/monthly technical values可能是 incomplete period，不能直接當 finalized evidence。
- 台股 corporate-action data coverage 尚未證明足以建立完整 adjusted series。
- Frontend drawing Fib/AVWAP/Volume Profile 是 user-selected research evidence，不是 backend canonical evidence。
- 完整長專案觸及 backend market、AI v4、MCP 與可能的 Frontend；必須保留 minimal/localized ownership，不能用大型 rewrite 一次取代既有 contract。

## Approval checklist

使用者已確認下列範圍：

- [x] 保留 technical v1，新增 canonical v2 shadow；`technical.structure` v2 採 v2，Radar active 暫不切換。
- [x] Weekly/monthly decision 預設只用 completed period；current partial 另欄公開。
- [x] Corporate action 先完成 truthful raw/unadjusted guard；coverage 足夠才啟用完整 adjusted series。
- [x] Breakout 加入 `rejected_attempt` 狀態。
- [x] 實作範圍包含 backend v4、MCP 與必要 Frontend；不在 Kuro 端重算。
- [x] 包含正式 launcher runtime adoption 與 outward behavior proof。
- [x] 預設不 commit、不 push、不建立 PR。
- [x] 以目前 dirty worktree 作為 integration base，逐檔相容且不覆寫既有修改。

## Final implementation and adoption evidence (2026-08-12 20:47 Asia/Taipei)

- Status: complete. Milestones 1-10 are implemented and validated; no commit or push was performed.
- Added canonical `tw.technical.indicators.v2` plus eight bounded Taiwan-stock capabilities: indicators, swings, Fibonacci, divergence, breakout, volume profile, anchored VWAP, and relative strength.
- Preserved legacy technical scoring. `tw_technical_current_state_v2` is additive `mode=shadow` evidence with `active_score_impact=false`.
- Price calculations preserve decimals across the 100 price boundary. The live 2408 response keeps close `482.5`, high `511.0`, and breakout resistance `502.0`.
- Weekly and monthly current periods are explicit `current_partial`; decision snapshots use the previous completed period.
- Corporate-action coverage is explicit. The live 2408 cache is `partial`, so advanced evidence remains `partial`, `limited`, and `decision_usable=false`; no adjusted series is fabricated.
- The outward source of truth remains `evidence.data[capability_id]`; readiness remains `evidence.capability_status[capability_id]`.
- Public contract snapshot: 22 target types, 66 capabilities, digest `1ba809162d6222a6355d452bf8edc5db8430b331b3734a5f9cc1ca3288467274`.
- Backend safe validation: compileall passed; full pytest `1763 passed` with 801 warnings; `git diff --check` passed. Log directory: `.tmp/validation/20260812-204135`.
- Focused capability/MCP validation: `115 passed, 245 subtests passed`; technical evidence/contract: `18 passed, 13 subtests passed`; envelope/boundary regression: `82 passed, 36 subtests passed`.
- Frontend: lint passed with one pre-existing unused-variable warning in `USStockDetailPanel.tsx`; TypeScript passed; Next.js production build passed.
- Backend runtime adoption: the original 8400 listener PID 48148 was replaced during implementation, then the official tray completed a final full restart at 20:45. Final listener PID 63788 identifies this repo and `.venv`. Live HTTP `omi.decision.v4` returned all selected technical capabilities with response budget met.
- Frontend runtime adoption: the official tray completed a final full restart at 20:45. Final listener PID 65252 serves the current repo; a fresh `/` request loaded a Next bundle containing `technical.indicators` and `technical.breakout`; `/omi-data/system/health` reached the final backend runtime.
- Standalone `OMI_search`: only `public_contract_snapshot.json` was synchronized; five pre-existing dirty source/test files were preserved. Its 31 tests and Python syntax check passed.
- Control Center restarted only `omi_search`: HTTP MCP PID 20716 -> 22472; build id `6ffe9eb74fcedf59` -> `d2d9ae0ab5de2184`; runtime version 1.0.0; component status Ready.
- Live MCP proof: protocol `2025-06-18`; session retained; seven tools; schema exposes the new technical capabilities; `omi.ask` returned `isError=false`, close `482.5`, breakout `rejected_attempt`, partial/limited readiness, and TAIEX relative-strength context.

## Next step

- 完成 2026-08-13 remediation Milestone 11：canonical formula、parameter contract 與 independent reference vectors。
- 在 formula/time/coverage gate 通過前，不切換 technical report、signal 或 Radar active source。

## 2026-08-13 remediation implementation evidence

- Milestones 11-15 are implemented. Runtime adoption and live outward proof remain before final completion.
- Added a single active technical-indicator gateway with environment rollback flag `TECHNICAL_CANONICAL_V2_ACTIVE`; report, signal, watchlist ranking, and Radar now consume the same active calculator contract.
- Canonical indicator contract advanced to `tw.technical.indicators.v3`; KDJ uses recursive smoothing with configured period and exposes unclamped `J = 3K - 2D`.
- PVO periods and breakout volume threshold are explicit backend settings, API settings fields, frontend controls, and `.env.example` deployment settings.
- Reference-vector tests cover MACD/EMA/PVO, RSI, ATR, ADX, ROC, MFI, Bollinger, Donchian, support/resistance, and configured-period behavior.
- Legacy MA gap handling is Taiwan-trading-calendar aware: legal Lunar New Year closures retain calculations, while a missing expected trading day still invalidates the affected series.
- Breakout evidence freezes event level/date/id and supports `confirmed`, `weak_confirmation`, `rejected_attempt`, `retest_held`, `failed`, and `continuation` lifecycle states.
- Corporate-action readiness is evaluated per capability and its actual lookback/anchor interval; an old historical event no longer downgrades unrelated recent-window evidence.
- Added pure, no-write provisional daily projection. It is emitted only after an observed current-session trade, labels price/range and cumulative volume as partial, and is excluded from finalized decision snapshots.
- Natural-language routing selects raw indicator, Fibonacci, divergence, breakout, volume profile, anchored VWAP, and relative-strength capabilities directly.
- Public contract snapshot remains 22 target types and 66 capabilities; digest is now `120d494ae17559caa4f1b80ff9cbfa5cea651568cc07ec04cfd887c7e8891de4`.
- Focused technical/AI/MCP regression: `138 passed, 26 subtests passed`.
- Full safe backend validation: compileall passed, pytest `1784 passed` with 801 warnings, and `git diff --check` passed. Log directory: `.tmp/validation/20260813-195209`.
- Frontend validation: ESLint passed; TypeScript `--noEmit --incremental false` passed.
- No commit, push, database reset, provider refresh, or unrelated runtime restart was performed during implementation and validation.

## 2026-08-13 remediation runtime adoption evidence

- Formal launcher adoption completed through `Start-OMI-Launcher.cmd` after exact ownership validation. Final launcher PID is `19636`; backend listener PID `12044` serves `127.0.0.1:8405`; frontend listener PID `9784` serves `127.0.0.1:3000`.
- The first non-GUI fallback stopped only the verified launcher PID and halted when child listeners did not release within its 30-second safety bound. Exact orphan lineages were then verified as this repo's uvicorn/Next processes, stopped by enumerated PID only, and the official launcher was restored. No broad process-name termination was used.
- Backend health identifies `C:\project\Open Market Intelligence` and the repo `.venv`; readiness is `ready`. Frontend `/omi-ui-health` and `/omi-data/system/health` both return HTTP 200 and the proxy reaches the same backend identity.
- Live `/api/ai/tools` exposes 22 targets, 66 capabilities, and digest `120d494ae17559caa4f1b80ff9cbfa5cea651568cc07ec04cfd887c7e8891de4`.
- Live 2408 today report exposes active engine `canonical`, algorithm `tw.technical.indicators.v3`, rollback flag `TECHNICAL_CANONICAL_V2_ACTIVE`, `decision_snapshot=completed`, and a separate non-decision provisional observation at `2026-08-13T13:30:00+08:00` with cumulative partial-volume semantics.
- The generated standalone `OMI_search/public_contract_snapshot.json` was synchronized without modifying its five pre-existing dirty source/test files. Its 31 unittests and all-Python syntax check passed.
- MCP Control Center v3 reloaded only `omi_search`: MCP PID `25664 -> 3512`, tunnel PID `39588 -> 47020`, build ID `d2d9ae0ab5de2184 -> b684205ecbf437fc`; post-status is Ready and upstream is Ready.
- Live MCP proof passed `initialize -> notifications/initialized -> tools/list -> tools/call(omi.ask)` with protocol `2025-06-18`, retained session, seven public tools, digest parity, `isError=false`, `omi.decision.v4`, and no caller-requested refresh. The 2408 technical response preserved partial/limited readiness and reported breakout state `failed` rather than fabricating a ready decision.
- UTF-8 natural-language MCP proof with `2408 突破狀態` selected `technical.breakout` additively and returned state `failed`. A prior Windows PowerShell string-body probe was discarded because it did not send explicit UTF-8 bytes and corrupted Chinese before routing.
- No commit or push was performed.

## Remediation wave baseline (2026-08-13)

- 使用者已明確核准依 `OMI_Technical_Indicator_Repair_Plan_2026-08-13.txt` 連續完善長專案。
- Integration base 維持 branch `codex/tw-etf-provider-normalization`、HEAD `46c37b3eb031e05792f0706e7437e6d46079528d`；保留現有 dirty worktree。
- Baseline focused tests：`72 passed, 13 subtests passed`。
- 2408 2026-08-12 已重現 active/canonical 差異：legacy RSI `57.7291`、KD `91.2803/93.4103`；canonical RSI `58.7228`、KD `85.6029/78.8782`。
- KD smooth period 3/5 目前輸出相同；canonical 未輸出 J。
- 2026-02-11 → 2026-02-23 合法長假使 legacy MA/Volume MA 為 null，canonical `max_gap_days=None` 有值。
- 2026-08-13 live intraday 已有 13:30 point，但 `technical.indicators.daily.current_partial=null`；today report 正確明示 finalized daily background。
- Backend、offline snapshot 與本機 MCP 目前皆為 66 capabilities、digest `1ba809162d6222a6355d452bf8edc5db8430b331b3734a5f9cc1ca3288467274`；T-008 留作外部 session cache 驗證，不重做已一致的 registry。
