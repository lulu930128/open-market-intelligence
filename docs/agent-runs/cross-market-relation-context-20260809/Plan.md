# 實作計畫

## 執行策略

本專案依「先凍結、再建真相、後接 consumer、最後才考慮決策影響」推進。每個里程碑需留下可重現 evidence；任一 gate 未通過就維持上一個安全狀態，不以 UI 看起來合理代替 contract 或 point-in-time 證明。

### Release 線

- Foundation Release：里程碑 0–3。Relation registry、canonical context、direct parity 與個股相容 facade 可用。
- Consumer Release：里程碑 4–6。Proxy snapshot、完整個股 evidence、Radar display-only、OMI v4/MCP 對齊。
- Evidence Release：里程碑 7–8。Event policy、statistics、walk-forward 與可選 ranking shadow。
- Production Hardening：里程碑 9。Runtime adoption、rollback 與文件收斂。

## 里程碑 0：基線凍結與 contract golden

### 工作

- 建立本長專案文件並記錄 branch、dirty worktree、current Alembic head、active Radar 與 outward contract。
- 保存既有 `ADR_MAPPINGS`、factor weights、basket mapping、overnight response、capability registry 與 MCP public snapshot golden。
- 為代表性個股建立 fixtures：2330/TSM、2303/UMC、3711/ASX、8150/IMOS、2408/MU、無 relation 個股。
- 固定時間語意：pre-open、台股盤中、台股收盤後、美股休市、FX stale、不同市場日期。
- 先補 regression，再改 owner code。

### 驗收

- Golden 能重現現有 parity、overnight summary、freshness、warnings 與 Radar baseline。
- Active Radar 明示 `radar_v2.0`；validation readiness 與 operational active 分開。
- 明確記錄 legacy overnight GET 的 bounded refresh 行為與所有內部 caller。
- Alembic revision 只依實作當下實際 head 建立，不根據本設計文件預占 revision number。

### 驗證

```powershell
$env:PYTHONPATH=(Resolve-Path '.\backend').Path
.\.venv\Scripts\python.exe -m pytest -q `
  backend\tests\test_adr_parity.py `
  backend\tests\test_ai_capability_contract.py `
  backend\tests\test_ai_outward_contract.py `
  backend\tests\test_watchlist_radar_active_v2.py
```

## 里程碑 1：Relation／Evidence Registry

### 工作

- 新增 `backend/app/market/cross_market/` domain skeleton、enum 與 `InstrumentRef`。
- 新增 relation／evidence ORM、Pydantic schema 與 Alembic migration。
- Idempotent seed 現有已驗證 ADR mappings；direct、limited 與 disabled 狀態分開。
- CHT、AUOTY 等新增 direct mapping 先做 evidence/provider review；2408/MU 先以 Tier C shadow proxy 建立，不因原始規格列出就直接進 production composite。
- 新增 trusted maintenance command：validate、list、create candidate、approve、supersede、disable；不提供 public CRUD。
- 建立 validity resolution、overlap rejection、evidence grade 與 audit trail。
- 新增 read-only relation API 與 diagnostics。

### 驗收

- Migration 可 upgrade/downgrade，既有 DB 不重建、不覆蓋。
- Seed 重跑不重複，DB 與 hardcoded mapping 在指定日期 zero diff。
- Direct relation ratio constraint、proxy ratio NULL、validity overlap、A/B primary evidence 都 fail closed。
- `not_applicable`、`limited`、`blocked` 與 `missing` 不混成 error 或零分。

### 驗證

```powershell
$env:PYTHONPATH=(Resolve-Path '.\backend').Path
.\.venv\Scripts\python.exe -m pytest -q `
  backend\tests\test_cross_market_relation_store.py `
  backend\tests\test_cross_market_relation_migration.py `
  backend\tests\test_database_model_contract.py
```

## 里程碑 2：Parity v2 與 canonical context foundation

### 工作

- `adr_parity.py` 改成 relation store dual-read；保留 hardcoded fallback 與 shadow diff。
- 建立 `cross_market.context.v1`、status vocabulary、signal、coverage、freshness 與 evidence passport。
- Direct parity 使用 ratio、FX、aligned TW reference、target TW trade date 與 corporate-action validity。
- 新增 read-only context API；engine 只讀 local cache，不發 provider HTTP。
- 新增 bounded refresh plan/job，沿用 provider owner 與 JobStatusCenter。

### 驗收

- 舊 `AdrParityRead` golden 全部通過，新增 relation ID/version/evidence 為 additive。
- ADR raw return 不進 proxy bucket；FX missing 不產生 implied price。
- Relation current 但價格 stale 時，context 仍為 stale／decision unusable。
- Read-only context GET 在 provider unavailable 時不產生 network side effect。
- Refresh request 有 max 8 symbols、dedupe、timeout、attempt/result 與 source-health event。

### 驗證

```powershell
$env:PYTHONPATH=(Resolve-Path '.\backend').Path
.\.venv\Scripts\python.exe -m pytest -q `
  backend\tests\test_adr_parity.py `
  backend\tests\test_cross_market_context.py `
  backend\tests\test_ai_tool_boundaries.py `
  backend\tests\test_market_source_health.py
```

## 里程碑 3：Overnight facade 與個股詳細頁第一版

### 工作

- `OvernightImpactRead` additive 新增 `cross_market_context`、bucket scores、coverage 與 methodology/version IDs。
- `overnight_impact.py` 改由 canonical service 取得 relation 與 signals；保留既有 stance、score、factors、baskets、ADR parity、freshness、missing、warnings。
- Frontend type 與 `OvernightDataViews.tsx` 改讀 structured contract，不依名稱／industry 重算。
- 延續截圖的 summary-first 版面：預設顯示 stance/date/top driver；parity/FX strip 與詳細 evidence 可展開。
- Load/refresh/provider failure 走共享「更新狀態」flow。

### 驗收

- 舊 response consumer 與 snapshot 不因 additive 欄位中斷。
- 2330 顯示 direct parity；2408/MU 顯示 industry proxy 且不使用因果文案。
- Partial/stale/limited 仍顯示資料日期與限制；無資料不顯示 `0%` 假中性。
- Desktop/mobile 無溢出、遮擋或重複控制；技術主體與 OVERNIGHT context 層級清楚。

### 驗證

```powershell
$env:PYTHONPATH=(Resolve-Path '.\backend').Path
.\.venv\Scripts\python.exe -m pytest -q `
  backend\tests\test_adr_parity.py `
  backend\tests\test_cross_market_context.py

Set-Location .\frontend
npm run lint
npm exec tsc -- --noEmit --incremental false
```

只有在版面實作完成且 UI 風險存在時，才以短時 browser/screenshot 驗證代表個股；不預設啟動長駐 dev server。

## 里程碑 4：Proxy residual、aggregation 與 point-in-time snapshot

### 工作

- 建立 proxy signal engine：raw return、benchmark residual、event context、freshness／evidence multiplier。
- 實作 bucket normalization、coverage threshold 與 direct/proxy double-count guard。
- 新增 `cross_market_signal_snapshot` migration、materializer 與 replay reader。
- Scheduler 批次解析 relation sources、去重 refresh、固定 `decision_at` 後 materialize。
- 建立 shadow diff：legacy weighted overnight vs canonical bucket result；只報告，不自動調 production weight。

### 驗收

- 2408/MU/SOX fixture 可對帳 raw、benchmark、residual、effective weight 與 contribution。
- Benchmark missing 時 `excess_return_pct=null` 且 signal 降級／blocked。
- Event 未分類時明示 `event_context=unresolved`，不能宣稱已知道漲跌原因。
- 同一 source 只進一個應有 bucket；coverage 低時不放大 macro signal。
- Replay 在同一 snapshot/version 下 deterministic；任何 `available_at > decision_at` 的 input 被拒絕。

### 驗證

```powershell
$env:PYTHONPATH=(Resolve-Path '.\backend').Path
.\.venv\Scripts\python.exe -m pytest -q `
  backend\tests\test_cross_market_proxy_signal.py `
  backend\tests\test_cross_market_aggregation.py `
  backend\tests\test_cross_market_point_in_time.py `
  backend\tests\test_cross_market_scheduler.py
```

## 里程碑 5：Radar v2 display-only 接線

### 工作

- Radar active projection 批次讀取同一 `decision_at` 的 cross-market snapshots，不逐檔 refresh。
- 由 backend Radar projection 將 signed context 與 technical direction 轉為 confirm／contradict／risk／info。
- Additive 寫入 `context_snapshot.cross_market`、`context_signals`、`context_alignment_score`、coverage 與 limitations。
- 保存 snapshot lineage 到 Radar point-in-time record／payload。
- Radar UI 顯示 compact alignment badge 與展開 evidence。
- 建立 `CROSS_MARKET_RADAR_DISPLAY_ENABLED` 與 rollback fallback。

### 驗收

- 開／關 display flag 時，`direction_score`、family scores、bucket、`priority_score`、rank 與 matched universe 完全一致。
- Missing/stale/blocked/limited context 的 alignment 為 0 且 limitation 可見。
- 同一 Radar run 不混用不同 context snapshot date/version。
- Active Radar readiness 仍保留 unverified／backtest missing，不因 context 有資料就宣稱模型已驗證。

### 驗證

```powershell
$env:PYTHONPATH=(Resolve-Path '.\backend').Path
.\.venv\Scripts\python.exe -m pytest -q `
  backend\tests\test_watchlist_radar_active_v2.py `
  backend\tests\test_watchlist_radar_v2_cross_market.py `
  backend\tests\test_cross_market_point_in_time.py

Set-Location .\frontend
npm run lint
npm exec tsc -- --noEmit --incremental false
```

## 里程碑 6：OMI v4、MCP、報告與 Kuro-facing contract

### 工作

- Additive 註冊 `cross_market.relations`、`cross_market.parity`，擴充既有 `cross_market.overnight` bounded fields。
- 修正 stock-level `cross_market.overnight` 的 `signals`／`factors`／`baskets` shape 漂移，指定 canonical projection。
- 保留 `market.cross_market` 為 market-level 能力。
- `decision_envelope_v4` 支援 summary／compact／full budgets 與 stable field paths。
- `answer_composer` 讀 structured reason codes，保留反證、資料限制與非因果語氣。
- 更新 MCP public snapshot、tool policy 與代表性 `omi.ask` cases；產出 Kuro consumer 範例，但不在 Kuro 端重算。

### 驗收

- Readiness 只出現在 `evidence.capability_status`，資料只出現在 `evidence.data`；不建立旁路欄位作第二真相。
- Summary 不因壓縮隱藏 status/date/warnings；compact 保留 top signals 與 coverage；full 遵守 bytes/cardinality budget。
- HTTP 與 MCP 對相同 request 回傳同 contract version、snapshot ID、methodology、freshness 與 limitations。
- Kuro 可只靠 enum、stable IDs 與 structured fields 顯示；中文 sentence 可改寫而不破壞 consumer。

### 驗證

```powershell
$env:PYTHONPATH=(Resolve-Path '.\backend').Path
.\.venv\Scripts\python.exe -m pytest -q `
  backend\tests\test_ai_capability_contract.py `
  backend\tests\test_ai_outward_contract.py `
  backend\tests\test_ai_decision_envelope.py `
  backend\tests\test_ai_answer_composer.py `
  backend\tests\test_api_contract_inventory.py
```

另做實際 MCP protocol smoke：`initialize -> tools/list -> omi.ask`，保留 `Mcp-Session-Id`，並檢查 public snapshot digest。

## 里程碑 7：Event policy、relation statistics 與 Radar ranking shadow

### 工作

- 新增 event policy 與 relation statistics schema；所有正式 policy/version 可回放。
- 建立 beta/correlation/stability job，最小樣本不足時不輸出偽精確統計。
- 凍結 validation protocol 後，產生 `context_priority_modifier_shadow` 與 shadow ranking。
- 建立 T+1/T+3/T+5 outcome dataset、purged walk-forward、embargo 與 segment report。
- Statistics 只產生 candidate weight／disable review，不改 production relation。

### 驗收

- Dataset 每列具 decision_at、input available_at、relation/event/methodology version 與 freshness state。
- 至少 60 eligible sessions、1,000 decision-usable snapshots、3 個 purged folds，或維持未達門檻狀態而不 promotion。
- Missing/stale subset 的 shadow ranking 與 baseline 相同。
- Direct、industry、theme、macro、coverage quartile 與 market regime 都有分層結果。
- Threshold、modifier cap、primary metric 與 guardrail 在看 outcome 前已 versioned。

### 驗證

```powershell
$env:PYTHONPATH=(Resolve-Path '.\backend').Path
.\.venv\Scripts\python.exe -m pytest -q `
  backend\tests\test_cross_market_event_policy.py `
  backend\tests\test_cross_market_statistics.py `
  backend\tests\test_watchlist_radar_v2_cross_market_outcomes.py
```

## 里程碑 8：Promotion decision

### 路徑 A：未通過

- 保持 Radar display-only。
- 保留個股頁與 outward evidence，因為「可解釋 context」不依賴「能改善排名」。
- 記錄失效 segment、coverage、資料量與後續研究假設，不調參掩蓋失敗。

### 路徑 B：通過

- 先以 `CROSS_MARKET_RADAR_PRIORITY_SHADOW_ENABLED` 完成穩定觀察。
- 建立 versioned active config，modifier 有 hard cap，並保留 baseline score、shadow score 與 reason。
- 使用者明確核准後，才開啟 `CROSS_MARKET_RADAR_PRIORITY_ACTIVE_ENABLED`。
- `direction_score` 仍不受影響；只能在既有 decision direction 之上做受限 priority modifier。

### 驗收

- Promotion decision 有固定資料集、metric、guardrail、版本與 reviewer 紀錄。
- Feature flag 關閉可即時回到 baseline，不需 rollback DB。
- Active 版本的 readiness 明確揭露 validation period 與 limitations。

## 里程碑 9：營運、runtime adoption 與收尾

### 工作

- 補 diagnostics／source health／provider events／relation review runbook。
- 更新 BackendArchitecture、RadarV2、capability inventory、README 與 API examples。
- 執行 safe validation、migration smoke、frontend checks、API/MCP smoke。
- 透過正式 launcher reload，驗證 owner/PID/listener/health/build identity 與代表性 outward behavior。
- 完成 rollback drill：flags off、legacy facade、migration downgrade 僅在 disposable DB 驗證。

### 驗收

- 個股頁、Radar、HTTP v4、MCP 對相同 sample 可對帳 snapshot/version/freshness。
- Refresh job failure、provider stale、relation evidence stale、benchmark missing 都在 UI／outward status 可見。
- 正式 runtime 證明採用新 source，不以 isolated test process 代替。
- Progress 記錄所有 verification、known limitations、promotion decision 與未完成項。

### 驗證

```powershell
.\scripts\run-safe-validation.ps1 -Profile backend
.\scripts\run-safe-validation.ps1 -Profile frontend
```

正式 runtime 僅在需要 user-visible acceptance 時啟動，並依 launcher 實際 selected ports 驗證：

- `/api/system/health`
- 代表性 relation/context／overnight endpoint
- 代表性 Radar v2 endpoint
- `/api/ai/ask` 的 `omi.decision.v4`
- MCP `omi.ask`

## Consumer hardening 軌：M6.1／M1.1／M2.1／M4.1／M9.1

這條工作軌補齊 Consumer Release 已暴露出的契約與資料生命週期缺口。施工順序固定為 M6.1 → M1.1 → M2.1 → M4.1 → M9.1；每一段驗收失敗就 stop-and-fix，不提前擴大 Radar ranking 能力。

### M6.1：Capability scope 與 phantom unsupported

#### 工作

- 在 backend capability owner 建立明確 stock／market scope mapping；stock-level cross-market domain 只允許三個 stock capabilities。
- 將 inferred-domain candidates 在 unsupported diagnostics 前依 target scope 過濾；保留 caller 顯式要求不適用 capability 時的 unsupported 回應。
- 鎖住 default selection、required capability、readiness、quality 與 `data.freshness` 的一致性，避免被 phantom capability 誤判為 blocked。
- Backend contract 穩定後才重生 repo 與 OMI_search public snapshots；snapshot 仍以完整 generated artifact 原子同步。

#### 驗收

- 2330／2408 stock request 的 selection 不含 `market.cross_market`，也不產生其 unsupported／unmet warning。
- 顯式要求 `market.cross_market` 搭配 stock target 時仍回 machine-readable unsupported，不靜默吞掉 caller 錯誤。
- `facts_usable`／`decision_usable` 只受實際 stale、missing、partial 或 provider failure 影響。

#### 驗證

```powershell
$env:PYTHONPATH=(Resolve-Path '.\backend').Path
.\.venv\Scripts\python.exe -m pytest -q `
  backend\tests\test_ai_capability_contract.py `
  backend\tests\test_ai_decision_envelope.py `
  backend\tests\test_ai_outward_contract.py `
  backend\tests\test_ai_tool_boundaries.py
```

另以代表性 2330／2408 `/api/ai/ask` request 檢查 selected capabilities、unsupported diagnostics 與 freshness；不以只跑 helper unit test 代替 outward contract 驗收。

### M1.1：Proxy relation 時間治理與 forward-only 修復

#### 工作

- 先重查實際 Alembic heads 與 dirty migration ownership；不得預留 revision number，也不得修改已套用的 `20260809_0052`。
- 以新的 forward-only migration／maintenance transaction 處理已知 seed fingerprint：舊紀錄保留歷史，重新 review 後建立可稽核的新版本或 supersede 狀態。
- 新 `verified_at`／`reviewed_at` 使用實際執行的 review 時點；不任意 backdate，也不宣稱修復前已可用。
- Repair 僅接受完整 relation identity、舊時間、review state 與 evidence hash 都符合已知 seed；任何人工修改、重複 evidence 或狀態衝突都 fail closed。

#### 驗收

- 2408／MU 在新 review 可用時間之前仍不可見，之後可由 relation API、canonical context 與 outward evidence 一致讀取。
- 重跑 upgrade 不重複建立 relation／evidence；downgrade 只在 disposable DB 驗證，不刪除 live data。
- Audit trail 可說明舊 seed、修復 transaction、reviewer、實際時間與 supersede 關係。

#### 驗證

```powershell
$env:PYTHONPATH=(Resolve-Path '.\backend').Path
.\.venv\Scripts\python.exe -m pytest -q `
  backend\tests\test_cross_market_relation_migration.py `
  backend\tests\test_cross_market_relation_store.py `
  backend\tests\test_cross_market_point_in_time.py `
  backend\tests\test_database_migrations.py
```

### M2.1：AI/tool bounded refresh orchestration

#### 工作

- AI 先讀 local cache 與 freshness；只有 request policy 明確允許 `allow_external_fetch` 時，才由 tool orchestration 呼叫既有 bounded refresh owner。
- Refresh plan 同時涵蓋所需 US daily source、proxy benchmark 與 USD/TWD resource quote；`cache_only`、GET relation/context 與 Radar read path 永遠不 refresh。
- 固定上限：最多 8 個來源、總 timeout 120 秒、symbol／resource dedupe、同 request coalescing 與 cooldown；不得寫 relation governance 或自動核准 candidate。
- Provider partial failure 時回傳 stale local context、provider event 與 visible warning，不以 refresh failure 清空可用 cache。

#### 驗收

- `cache_only` 測試可證明零 provider call；`allow_external_fetch` 只執行 planner 列出的 bounded operations。
- FX stale 時 planner 不只刷新 US daily；refresh 後重新建 evidence，仍保留 event time、fetched time、source health 與 remaining limitations。
- Timeout、quota／cooldown、部分成功與全部失敗都有 deterministic status，不造成隱性重試風暴。

#### 驗證

```powershell
$env:PYTHONPATH=(Resolve-Path '.\backend').Path
.\.venv\Scripts\python.exe -m pytest -q `
  backend\tests\test_cross_market_context.py `
  backend\tests\test_ai_tool_boundaries.py `
  backend\tests\test_market_source_health.py
```

### M4.1：Materialized snapshot lifecycle

#### 工作

- Contract 明確區分 `projection_source=latest_local_cache` 與 `projection_source=materialized_snapshot`。
- Materializer 寫入 immutable snapshot，包含 `snapshot_id`、`decision_at`、`materialized_at`、`materialized_by`、source cutoff、relation/methodology version 與 payload hash；相同 identity 重跑只能驗證同 hash，不得原地覆寫。
- Materialized payload 移除或改寫 `latest_local_cache_projection_not_materialized_snapshot`，避免 snapshot 自我矛盾。
- Ask／個股說明可讀既有 snapshot；Radar batch 只讀同批 materialized snapshots。任何 read path 都不臨時 materialize 或 refresh。

#### 驗收

- 同 stock／decision_at 的 Radar、個股說明、HTTP 與 MCP 可對帳同一 snapshot ID、hash、versions 與 freshness。
- Replay 不讀取 source cutoff 之後才 available 的 relation、evidence、price 或 FX。
- Live DB snapshot count 為零時明確回報 not materialized；不得把 latest cache 偽裝成 point-in-time snapshot。

#### 驗證

```powershell
$env:PYTHONPATH=(Resolve-Path '.\backend').Path
.\.venv\Scripts\python.exe -m pytest -q `
  backend\tests\test_cross_market_point_in_time.py `
  backend\tests\test_cross_market_aggregation.py `
  backend\tests\test_watchlist_radar_v2_cross_market.py `
  backend\tests\test_ai_outward_contract.py
```

### M9.1：Outward、Frontend、runtime 與 rollback acceptance

#### 工作

- 以相同 request 對帳 backend HTTP 與 MCP `omi.ask` 的 capability selection、snapshot lineage、freshness、warnings 與 data limits。
- 驗證 MCP live schema 的 include／required enums；若 ChatGPT host 保留舊 schema，記錄 reconnect／new-session 邊界，不在 adapter 加永久旁路。
- 用 user-visible browser acceptance 檢查個股 `OVERNIGHT`、Radar display-only badge 與 stale／limited／provider failure 呈現。
- 完成 feature flags off、legacy facade 與 disposable DB migration rollback drill；正式 runtime 需驗證 owner、PID replacement、listener、health、build identity 與代表性 outward behavior。

#### 驗收

- HTTP、MCP、個股頁與 Radar 對同一 sample 不再出現 phantom capability、時間線互斥或 materialization 語意矛盾。
- Radar 開關前後 direction、priority、bucket、rank 與 universe 完全一致。
- Rollback 不需刪除 live SQLite、不遺失 relation/evidence/snapshot audit trail，也不 broad-kill 非本任務 runtime。

#### 驗證

```powershell
.\scripts\run-safe-validation.ps1 -Profile backend
.\scripts\run-safe-validation.ps1 -Profile frontend
```

再依 launcher 實際 selected ports 做 HTTP／MCP protocol smoke 與 browser acceptance；只有 source、runtime identity、outward behavior 三者都吻合才標記完成。

## Stop-and-fix 規則

- Migration head、ORM 或 schema 與 worktree 其他修改衝突時，先停止並重排 revision；不得建立平行 head 或覆寫他人 migration。
- Golden 不一致時先判定是 legacy bug、預期 semantic change 或新 regression；未決前不切 DB primary。
- Relation validity overlap、A/B evidence 缺失、ratio invalid 或 point-in-time leakage 一律 fail closed。
- GET path 出現 provider HTTP、全市場隱性 refresh 或 Radar N+1 時，停止該里程碑。
- Consumer 若開始重算 relation、weight、freshness 或 alignment，將邏輯移回 backend owner 後再繼續。
- Radar display-only 若改變 baseline score、bucket、rank 或 universe，視為 regression，不進下一里程碑。
- Outward projection 若隱藏 stale／partial／missing，或 human answer 把 proxy 寫成因果，視為 contract failure。
- 驗證失敗先修正相關 root cause；無關既有失敗需隔離並記錄，不能混稱本專案通過。
- 大量外部 refresh、付費 quota、report/memory 寫入、production migration 或 active ranking promotion 都依既有 trust policy與使用者確認邊界執行。

## 任務狀態更新規則

每完成一個里程碑，更新 `Progress.md`：

- 實際 changed files 與 migration revision。
- 驗證命令、結果、log path 與 runtime identity。
- Contract／feature flag／methodology 決策。
- 已知限制、deferred 項與下一步。
- 不以「程式寫完」標記完成；只有該里程碑 acceptance evidence 齊全才完成。
