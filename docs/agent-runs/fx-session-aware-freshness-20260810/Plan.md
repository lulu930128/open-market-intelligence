# Plan

## Contract overview

新增的 canonical evaluator 應是純函式／typed result，至少輸出：

- `purpose`: `spot_quote | adr_alignment | daily_trend`
- `status`: `current | latest_completed_session | delayed | stale | missing | provider_failure | future`
- `usable`: 是否可用於該 purpose；不等同於 provider refresh 是否可執行。
- `session.phase`: `open | maintenance | closed | unknown`
- `session.reason`: `weekday | weekend | provider_maintenance | provider_holiday | calendar_unverified`
- `expected_data_date`、`actual_data_date`、`next_expected_update_at`
- `event_time`、`fetched_at`、`event_age_seconds`、`fetch_age_seconds`
- `refresh_eligible`、`next_eligible_refresh_at`
- `reason_codes`、`warnings`、`limitations`

Consumer compatibility mapping：

| Canonical FX 狀態 | ADR / cross-market | Resource source-health |
|---|---|---|
| `current` | `ready` / usable | `delayed`（best-effort provider）或既有 live-compatible 狀態 |
| `latest_completed_session` | `ready` / usable，附 closure reason | `delayed`, `ok=true`, session closed/maintenance |
| `delayed` | 依 purpose 與 alignment 決定 usable，必須揭露限制 | `delayed` |
| `stale` | `stale`, unusable, refresh eligible 視 policy | `stale`, `ok=false` |
| `missing/provider_failure/future` | `partial` 或 blocked，不得產生 parity contribution | `empty/error/stale` 加 machine-readable reason |

## Milestones

### R0：凍結語意與失敗案例

- Scope:
  - 新增 deterministic fixture matrix，不先改 production logic。
  - 覆蓋普通週末、長 closure、maintenance、market reopen grace、真正多 session stale、future timestamp、missing、provider failure。
  - 分別驗證 `spot_quote`、`adr_alignment`、`daily_trend`，避免一個 fixture 代表三種資料契約。
- Acceptance:
  - 修正前至少精準重現：FX session 為 `unknown`、weekend quote 被 4h threshold 判 stale、73h ADR FX 被固定判 stale、stock detail 無法執行 composite FX plan。
  - `2026-08-03 -> 2026-08-10` open-session case 明確維持 stale。
  - 測試只用固定時間、in-memory SQLite／pure helpers 與 mock provider，不讀寫 live DB、不呼叫外部 API。
- Validation:
  - `\.venv\Scripts\python.exe -m pytest -p no:cacheprovider backend\tests\test_fx_freshness.py backend\tests\test_resource_market.py backend\tests\test_adr_parity.py backend\tests\test_cross_market_refresh.py backend\tests\test_cross_market_context.py -q`

### M1：建立純 FX session／freshness owner

- Scope:
  - 新增 `backend/app/resource_market/fx_freshness.py`（名稱可依 repo pattern微調），只負責 session classification、expected data date、age dimensions、purpose profile 與 canonical evaluation。
  - 將 America/New_York 24x5 weekend／maintenance 規則明確建模；provider holiday 未驗證時只給 limitation，不借用 NYSE holiday 作完整真相。
  - 不查 DB、不呼叫 HTTP、不 commit；輸入 timestamp/date/provider policy，輸出 typed result。
- Acceptance:
  - 同一輸入在三種 purpose 下可得到不同但可解釋的 freshness 結果。
  - closed session 的 latest completed data 可用；open session 超過 grace 的舊 event 必須 stale。
  - `event_time` 與 `fetched_at` 分別計算，新 fetch 不會自動洗白舊 market event。
  - Naive datetime、timezone、future time、DST 切換與週日 reopen 邊界有測試。
- Validation:
  - `\.venv\Scripts\python.exe -m compileall backend\app\resource_market\fx_freshness.py`
  - `\.venv\Scripts\python.exe -m pytest -p no:cacheprovider backend\tests\test_fx_freshness.py -q`

### M2：收斂四條 backend consumer

- Scope:
  - `backend/app/market/adr_parity.py`：移除固定 72h owner，優先選 ADR trade date 對齊的 FX daily input；投影 alignment/freshness lineage。
  - `backend/app/market/fx_flow_context.py`：以 `daily_trend` expected date 判定，不再以 bar wall-clock age 單獨決定 stale。
  - `backend/app/market/cross_market/refresh.py`：由 canonical evaluation 決定 candidate、refresh eligibility、next eligible time 與 reason；多檔 ADR 共用 USD/TWD 時只產生一個 source operation。
  - `backend/app/resource_market/source_health.py`：`exchange=FX` 使用 `spot_quote` session contract；commodity futures 維持既有 exchange-specific 規則。
  - 更新 Pydantic schema、AI/market projection 與 frontend types，只做 additive fields。
- Acceptance:
  - 四條路徑對相同 FX evidence 的 status、usable、reason code 與 refresh eligibility 不矛盾。
  - ADR daily current + aligned FX latest completed session 可維持 usable；ADR daily current + 7-day-old FX 在 open session 必須 stale。
  - `ResourceSourceHealth` 對正常 FX 不再輸出 `session_status=unknown`。
  - Point-in-time replay 只使用 decision-time 可見資料與當時 session；current projection 可隨牆鐘重新評估但不寫 snapshot。
  - Public route inventory、既有 required fields 與 top-level status 相容。
- Validation:
  - `\.venv\Scripts\python.exe -m pytest -p no:cacheprovider backend\tests\test_fx_freshness.py backend\tests\test_resource_market.py backend\tests\test_adr_parity.py backend\tests\test_fx_flow_context.py backend\tests\test_cross_market_context.py backend\tests\test_cross_market_golden_contract.py backend\tests\test_cross_market_ai_contract.py -q`
  - `\.venv\Scripts\python.exe -m compileall backend\app`

### M3：修正 refresh ownership 與個股頁 handoff

- Scope:
  - 將 `scan_us_overnight_impact_gaps`／canonical context 的 `refresh_decision` additive 投影到 stock-detail 可消費的 backend response。
  - 保留 `POST /api/market/cross-market/refresh` 作唯一 job owner；加強 request-key dedupe、共享 USD/TWD source、300 秒 failure cooldown、最大 8 sources、最長 120 秒與 provider-event 摘要。
  - Stock detail 初次 read 不重算 freshness；只在 backend 回 `should_execute=true` 時 enqueue，交給既有 Job Status／更新狀態呈現，job 完成後 reread。
  - Legacy GET compatibility 暫留，但不得擴大為 composite FX refresh；internal frontend 改走明確 read + POST handoff。
  - Resource panel 的 on-select polling 使用同一 evaluator：closed/latest-completed 不重複刷新，open/stale 才刷新。
- Acceptance:
  - 一次選取 3711，若只有 FX stale，只 enqueue 一個 `resource_quote:USD-TWD` operation；切換其他 ADR 股票不重複建立等價 active job。
  - Deferred/cooldown 不會形成 frontend loop；provider failure 保留 cached value、error、next eligible time 與 stale/partial 狀態。
  - GET current/replay、Radar read 與 MCP adapter 不產生 provider side effect。
  - Job lifecycle、provider event、result counts 與 reread outcome 可稽核。
- Validation:
  - `\.venv\Scripts\python.exe -m pytest -p no:cacheprovider backend\tests\test_cross_market_refresh.py backend\tests\test_overnight_impact.py backend\tests\test_ai_tool_boundaries.py backend\tests\test_cross_market_ai_contract.py backend\tests\test_jobs.py -q`
  - `cd frontend; npm exec tsc -- --noEmit --incremental false`
  - `cd frontend; npm run lint -- --no-cache`

### M4：使用者可見狀態與 contract 驗收

- Scope:
  - 個股跨市場與貨幣快照顯示 backend 提供的 actual/expected date、session state、`latest_completed_session`、stale reason 與 refresh state。
  - load/refresh/provider failure 進共用「更新狀態」；資料本身的 stale/partial/limitation 仍留在原卡片，不用 frontend hardcode 掩蓋。
  - 中／英／日文案與 frontend e2e fixtures 同步。
- Acceptance:
  - Closure fixture：顯示「最近完成 session」而非「資料不足」，且不發出 refresh loop。
  - Genuine stale fixture：仍顯示資料較舊、實際日期與 refresh state；不得顯示 ready。
  - Provider failure fixture：沿用 cache 但明示 failure/cooldown，不顯示假零值。
  - 既有 cross-market summary、ADR formula、relation lineage、coverage 與 mobile/desktop layout 不回歸。
- Validation:
  - `\.\scripts\run-safe-validation.ps1 -Profile frontend`
  - `cd frontend; npm run test:e2e -- --grep "Taiwan stock overnight report|resource currency freshness"`（只在安全、可重用的 intentional runtime 上執行）

### M5：全回歸、正式 runtime adoption 與 canary

- Scope:
  - 跑 backend Tier 3 safe validation、必要 frontend checks、正式 launcher-selected runtime adoption。
  - 驗證 PID/path/build identity、readiness、代表性 HTTP、job、provider event、DB row identity 與 outward AI/MCP projection。
  - 最多執行一次 target=`USD-TWD` 的 bounded provider refresh canary；不做全市場 refresh。
- Acceptance:
  - `3711`：ASX expected/latest date 相符時不被 ADR 日線誤判；FX 若真的 7 天舊仍 stale，bounded job 後依 provider event/session 得到 current/latest-completed 或清楚 provider limitation。
  - `/api/resource-market/source-health?symbols=USD-TWD`：FX session 不再 unknown，event/fetch age 與 expected update 可讀。
  - Cross-market job/provider event 各有一條可追蹤紀錄；重跑遵守 dedupe/cooldown，沒有重複 cache identity 或大量 rows。
  - `/api/ai/ask`、local MCP `omi.ask` 與 frontend 顯示同一 backend freshness/limitation；Radar ranking 仍 `ranking_effect=none`。
  - 正式 runtime 的 listener ownership、PID replacement 與 repo build identity 已證明，不以 health 200 單獨宣告完成。
- Validation:
  - `\.\scripts\run-safe-validation.ps1 -Profile backend`
  - `\.\scripts\run-safe-validation.ps1 -Profile frontend`
  - 唯讀 probes：`/api/system/health`、`/api/ai/tools`、`/api/market/calendar-status?market=all`、`/api/market/overnight-impact/3711?refresh=false`、`/api/market/cross-market/context/3711`、`/api/resource-market/source-health?symbols=USD-TWD&intervals=1m,1d`
  - 明確 bounded canary：`POST /api/market/cross-market/refresh?stock_ids=3711&max_symbols=1&max_runtime_seconds=120`，完成後查 job/provider events 與重新讀取上述 GET。

## Stop-and-fix rules

- 若任何修正只靠放寬秒數、前端遮警告或把 stale 直接映成 current，立即停止並回到 R0 contract。
- 若 `2026-08-03 -> 2026-08-10` genuine stale fixture 被判 usable，停止；holiday-aware 不得犧牲資料可信度。
- 若 ADR parity 使用的 FX 無法證明與 ADR session 對齊，必須標 partial/limited，不能產生 decision-usable contribution。
- 若 resource、ADR、cross-market 與 FX flow 對相同 evidence 產生互相矛盾的 freshness，先收斂 owner 再進下一 milestone。
- 若 GET/replay/Radar read 新增 provider call、DB materialization 或 job enqueue，停止並移回明確 POST/job owner。
- 若 provider refresh 失敗卻清掉 stale/missing、覆蓋較新 cache、提交半套 transaction 或無 event，停止並修正 transaction/fallback。
- 若 schema 需要 breaking change、DB migration 或新增 always-on background quota，暫停並先更新 `Prompt.md` 取得方向確認。
- 若測試或實作碰到 `tw_corporate_events` 既有修改，不得 revert；先隔離 task scope。
- M5 未證明正式 runtime PID/build adoption、代表性 outward behavior 與 bounded canary 前，不得標記 done。

## Decisions

- 2026-08-10：採 purpose-specific FX freshness profiles，共享 session primitives但不共用單一 release window。
- 2026-08-10：不直接用 NYSE holiday 當 FX 日曆；先建 provider-defined 24x5/weekend/maintenance，未驗證 holiday 以 limitation 表示。
- 2026-08-10：ADR parity 優先使用 ADR session-aligned FX daily input；current spot 與 aligned parity input分離。
- 2026-08-10：保留 public top-level status 相容，新增 nested canonical freshness 欄位；consumer 不自行重算。
- 2026-08-10：使用既有 cross-market POST job 作 refresh owner，不擴大 legacy GET side effect。
- 2026-08-10：先完成 on-select／AI bounded handoff；是否背景維護 USD/TWD 需待 call-rate 與 provider reliability 證據後另決定。
