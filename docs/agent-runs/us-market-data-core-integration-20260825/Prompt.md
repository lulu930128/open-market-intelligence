# OMI 美股 Market Data Core 接軌

## Project status

- Mode：long-horizon production convergence program。
- Planning state：master plan與supporting control docs已建立；production implementation尚未開始。
- Target label：`US_MARKET_DATA_PLATFORM_PRODUCTION_CONVERGED`。
- Execution rule：per-capability／per-dataset Strangler migration；「一次把架構拉好」表示完整範圍有單一計畫與完成定義，不表示一次Big Bang改寫或同時切production。
- Shared Core dependency：正式接線前必須通過`CoreHandoffChecklist.md` G0；台股task必須以actual-data、runtime、consumer與rollback證據達到`TW_MARKET_DATA_PLATFORM_PRODUCTION_CONVERGED`。

## Goal

- 在不複製 Shared Market Data Core 的前提下，整理出可長期維護的美股 market-owned 架構：provider descriptor、provider adapter、Canonical Observation、candidate persistence/read、US market policy 與 stable projection。
- 先建立 Data Core 完成前可安全落地的邊界與防呆，停止 legacy provider ownership 繼續擴張。
- 待台股側完成正式 Shared Market Data Core 與 `OMI Market Data Core Integration Contract` 後，將美股 quote、intraday bars、daily OHLCV、refresh/repair lifecycle、AI/API/Frontend consumer 逐步接入唯一 truth path。
- 全程保留 rollback、shadow/compare/canary、truthful freshness／missing／partial／fallback／lineage，避免 Big Bang rewrite。

## Non-goals

- 本任務不實作或修改台股側 Shared Market Data Core。
- Shared Core contract 尚未定版前，不自行建立第二套 `DataRequirement`、`RefreshRequirement`、Resolver、Control Plane、Dataset Registry 或 health model。
- 不把 SEC、FINRA、FRED、SEC ownership、corporate filing event 等 US authority datasets 強行 genericize 成 quote/OHLC provider；它們保留 US domain ownership。
- 不在準備階段切換 production 主路徑、不啟用 KGI US、不執行付費／稀缺 quota refresh、不做無界全市場 backfill。
- 不因架構整理同時重寫 UI、technical math、watchlist、portfolio、account 或 AI decision contract。
- 不刪除或重建 `data/open_market_intelligence.db`，不做未經確認的 migration、資料清理、commit、push 或 release。

## Hard constraints

- 唯一正式依賴方向：`Provider -> Canonical Observation -> Shared Core / Resolver -> US Projection -> Research / API -> Frontend / AI / MCP / Kuro`。
- Consumer、router、AI tool、scheduler、repair workflow 不得指定 `yahoo_chart`、`alphavantage`、KGI 或其他 production provider。
- Provider adapter 只能擁有 provider-specific IO、authentication/session、parsing、error normalization、timestamp normalization 與 Canonical conversion；不得做 cross-provider fallback、selection、dataset lifecycle、AI decision 或 DB transaction ownership。
- US provider descriptors 由 `app.us_market` 擁有；Shared Core 只能透過正式 registration/binding 使用，不反向 import `app.us_market.service`。
- Provider candidates 必須保持 provider coherence；不得把不同 provider 的欄位混成單一 Canonical Observation。
- `cache_only` read 不得啟動 provider IO、subscription、repair 或 DB write。
- `prefer_live`／`require_live`／`completed_session`、fallback、freshness、health 與 lineage 由 Shared Core 擁有；US layer 只提供 market session、early close、symbol/venue、corporate-action applicability 等市場語意。
- Unknown != 0；No Quote != No Trade；No Trade != Suspended；Market Session != Instrument Trading Status。
- Provider Health、Dataset Health、Resolved Evidence Health 分開；outward selected evidence 保留 provider、source、event time、received/fetched time、fallback 與 selection reason。
- 既有 public API 與 local data 優先維持 compatibility；必要 breaking change 必須有 migration window、diagnostic replacement、contract test 與 rollback。
- 目前 dirty worktree 屬於使用者或其他工作；不得 reset、restore、clean 或覆寫無關變更。

## Context

- Repo：`C:\project\Open Market Intelligence`
- Reference proposals：
  - `OMI_US_Market_Data_Platform_Convergence.txt`
  - `OMI_Market_Data_Core_Integration_Contract.txt`
- Input hashes：
  - US convergence proposal SHA-256：`ecc996c57da5a3131ef82a081cbbb344c5d78226244ed5f583dddefd9c7a8c2a`
  - Core integration proposal SHA-256：`65e1b217aa3e4bbfaf9c31a7740d9bb3ed6ad605369742ac004f521f0eca3ce9`
- Shared Core umbrella dependency：`docs/agent-runs/tw-market-data-platform-convergence-20260825/`；目前是planned/audited，不視為G0已通過。
- Current truth：`docs/product/*`、`docs/architecture/BackendArchitecture.md`、`docs/architecture/OmiDecisionContract.md` 與 repo `AGENTS.md`。
- 2026-08-25 A0以前的initial source audit已確認（後續處置以`Progress.md`為準）：
  - `app.us_market.market_data_policy`、pure canonical adapters、Resolver projection、cache-only resolved daily reads 已存在。
  - `build_us_acquisition_plan()` 幾乎只有測試 caller；`execute_acquisition()` 沒有 US production provider port。
  - daily、intraday、public router、AI refresh、Frontend 與 scheduler 仍主要透過 `app.us_market.service` 直接選 provider 或自行 fallback。
  - `app.market_data.eod_coverage` 反向 import `app.us_market.service` 並寫死 Yahoo，尚未形成真正 dependency-inverted Core。
  - 現有 `DataRequirement` 無法完整表達 timeframe、bars、completed-only、coverage 與 repair postcondition；repo 尚無附件所定義的 `RefreshRequirement`。
  - dirty worktree 正在新增 OHLC continuity/repair/priority scheduler；continuity 與 postcondition 可保留，但 acquisition path 仍 hardcode Yahoo，且 scheduler source default 為 enabled。

## Trust boundaries

| Owner | 可以擁有 | 不得擁有 |
| --- | --- | --- |
| Shared Market Data Core | Data/Refresh Requirement、planning、fallback、Resolver、freshness、health、dataset lifecycle、bounded acquisition、lineage | US session/business projection、SEC/FINRA interpretation |
| US Market Domain | provider descriptors、adapter factory、US calendar/session、symbol/venue、Canonical conversion、US projection、authority datasets | cross-provider fallback、consumer-specific provider selection、第二套 Core |
| Persistence transaction owner | provider-coherent candidate upsert、commit/rollback、post-write readback | selection/fallback、將 provider payload 直接當 resolved truth |
| Research / AI / API | 描述 capability 與 bounded requirement、消費 resolved evidence | provider IO、provider choice、freshness/session 推論 |
| Frontend / MCP / Kuro | 顯示、互動、viewer intent、workflow/presentation | provider priority、repair policy、market-data truth |

## Deliverables

- 一組可續跑的 Prompt／Plan／Progress 文件與明確 Shared Core readiness gate。
- `ArchitectureMap.md`：current/target graph、ownership、asset disposition、gap/work-package mapping。
- `WorkBreakdown.md`：A0–F3 work packages、依賴、file ownership、acceptance、validation與更新節奏。
- `CoreHandoffChecklist.md`：台股Shared Core交付packet、G0-01至G0-15與US compile-only probe。
- `AcceptanceMatrix.md`：從planning、Pre-Core、Core binding、daily、lifecycle、realtime、consumer到closure的truthful status。
- `RiskRegister.md`：trigger、owner、mitigation、contingency與automatic blockers。
- `CutoverRunbook.md`：off/shadow/compare/canary/on、evidence packet、rollback與closure procedure。
- Data Core 完成前的 boundary guard 與 legacy-expansion quarantine。
- 清楚的 US market-data package ownership，包含 descriptors、provider adapters、candidate store/read、US projection 與 compatibility seam。
- 待 Core 定版後的 US provider port bindings、dataset operation bindings 與 end-to-end resolved evidence path。
- Daily OHLCV、repair/scheduler、intraday/live、AI/API/Frontend 的分階段 cutover 與 rollback。
- Contract、fixture、DB transaction、API、AI、frontend、scheduler、runtime/data smoke 驗證矩陣。
- Legacy fallback、provider selector、reverse dependency 的移除證據。

## Done criteria

### Pre-Core ready

- 新增或修改的 US market-data 程式不再把 provider selection 擴散到 consumer、router、AI、scheduler 或 repair workflow。
- Yahoo／AlphaVantage adapter 能以 fixture 輸出 provider-coherent Canonical observations，且不做 fallback／DB transaction。
- Candidate persistence/read 與 US projection 有單一責任與 targeted tests；既有 production behavior 尚未被未完成 Core 取代。
- Dirty OHLC continuity 邏輯與 provider-specific acquisition 解耦；未接 Core 前不會由預設啟用 scheduler 自動擴張 legacy refresh。
- 已建立 Core readiness checklist；任何必要項缺失時，integration milestones 明確維持 blocked。
- A0–A3 work packages與AcceptanceMatrix B區全部passed；long-project docs能由新回合直接續跑，不依賴對話記憶。

### Final convergence

- US product path 由 `DataRequirement`／`RefreshRequirement` 進入唯一 Shared Core，再由 US stable projection 提供 API／Research／AI／Frontend。
- Daily、intraday、repair、full-market/priority scheduler 的 provider planning、fallback、budget、health、postcondition 與 lineage 都由 Core／Dataset Registry 擁有。
- Frontend、AI、public product API 與 scheduler 不再傳入 provider selector；provider-specific 操作只存在於明確 diagnostic/admin/raw-source maintenance surface。
- `app.market_data` 不再直接 import US legacy service；`app.us_market.service` 不再擁有 cross-provider fallback。
- `cache_only`、Yahoo success、Yahoo failure + AlphaVantage fallback、both unavailable、stale/partial history、early close、premarket/regular/after-hours、provider conflict 與 fallback lineage 都有 regression coverage。
- Shadow／compare／canary／on 與 rollback 經 source、runtime、HTTP、AI/MCP、Frontend 使用者可見流程驗收。
- `AcceptanceMatrix.md` B–H required rows全passed，並正式標記`US_MARKET_DATA_PLATFORM_PRODUCTION_CONVERGED`；不可用KGI或其他planned provider維持truthful未advertised，不被假算完成。

## Open questions / assumptions

- Shared Core 的最終 Python module、type name、registration API、operation dispatcher 與 persistence callback contract 尚未定版；不得依現有 prototype 名稱猜測 final interface。
- `USDailyPrice` 現有 provider+symbol+trade_date raw-candidate storage 可在第一階段沿用；若 Core 要求額外 lineage 欄位，必須另做 migration proposal 與資料相容性審查。
- Public provider-selecting routes 的 compatibility 策略預設為「product route provider-neutral；provider-specific 行為移到 diagnostics/admin」，實作前需以實際 caller inventory 確認是否有 repo 外 consumer。
- US KGI 是否支援 quote、depth、extended-hours 與 historical data，待 entitlement 與 live validation 後才加入 descriptor；Unknown 不提前宣告 supported。
