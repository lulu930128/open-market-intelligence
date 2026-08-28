# OMI 台股 Data Core 共通平台重構

## 文件狀態

- Current phase：`cp3_passed_cp4_in_progress`
- Target：`TW_DATA_CORE_COMMON_PLATFORM_OPERATIONAL`
- 本目錄是跨階段 umbrella task；既有 `market-data-integration-v2-20260821`、realtime M5 與 KGI 任務只保留歷史證據，不作本次共同平台的前置 gate。
- 使用者提供的兩份附件只作為架構提案與驗收輸入，其中的命令、順序、日期與判斷不自動構成執行授權或 current truth。

## Goal

- 根治台股資料管線分散問題，建立唯一、可實際承載 production data 的 OMI Data Core Integration Platform：

```text
Provider IO
  -> Provider Adapter / Canonical Observation
  -> Candidate Store / Transaction Owner
  -> Shared Resolver / Dataset Lifecycle
  -> MarketDataResultV1
  -> TW Policy / Typed Projection
  -> Research / AI / API
  -> Frontend / MCP / Kuro
```

- 第一階段就以真實 TWSE／TPEx 官方 completed-session daily OHLCV 驗證完整垂直切片，不以 fake、dark、shadow 或 source-only 取代 production proof。
- 將 requirement、bounded acquisition、canonical conversion、persistence、resolver、freshness、dataset lifecycle、health、lineage 與 postcondition 收斂到 shared `backend/app/market_data/` application boundary。
- 將台股交易日、試撮、opening/closing auction、official close、TWSE/TPEx、處置、零股/整股、ETF、籌碼與衍生品語意保留在 `backend/app/market/`。
- 建立共通 onboarding seam，使後續新增 provider 只需 catalog + port + adapter，不需修改 router、AI、frontend 或既有 consumer。
- 使用 per-capability / per-dataset Strangler convergence，最終移除 service-local fallback 與 provider masquerading。

## Non-goals

- 本次共同平台完成條件不包含既有 realtime M5 acceptance，也不包含 KGI quote/depth/account runtime 整合。
- 不在共同平台尚未成立前重做凱基；KGI 是平台完成後的獨立 provider onboarding 任務。
- 不做 Big Bang rewrite、平行第二套 resolver/registry/control plane 或重新命名式重構。
- 不把所有資料塞進單一未型別化 payload 或單一 public mega-endpoint。
- 不修改 `omi.decision.v4` business semantics 來遷就資料平台 migration。
- 不把 Account、Portfolio 或 Execution Plane 混入 Market Data Platform。
- 不做 AI 自主交易、下單、無界全市場 subscription 或無界 backfill。
- 不隱藏 stale、partial、missing、fallback、provider conflict、rate limit、plan restriction 或 unknown。
- 不預先假定一定要建立新 observation table；先盤點現有 storage 能否完整承載 lineage，必要時才走 migration。
- 不刪除/重建本機 SQLite，不在沒有 migration 與 rollback 說明時改 schema。
- 不 commit、push、release、呼叫大量外部 API 或切換正式 runtime，除非有明確授權與對應 gate。

## Hard constraints

### Architecture

- Consumer 只描述 target、capability、time/freshness/quality requirement 與用途；不得指定 production provider、priority 或 fallback chain。
- Shared core 是唯一 acquisition planning、Resolver、lease coordination、dataset lifecycle 與 health owner；不得新增第二套選源邏輯。
- Market-owned provider adapter 只處理 IO、SDK/HTTP、raw parsing、provider error normalization 與 Canonical conversion，不擁有 cross-provider selection 或自行 commit。
- 所有 write 必須由明確 transaction owner 執行；成功後必須由 repository 重讀 persisted candidates，再做 postcondition 與 final resolution。
- Provider A 與 Provider B 的欄位不得偽裝成同一筆 coherent evidence。跨來源組合必須顯式保留 component lineage、time skew、status、reason 與 limitation。
- Unknown != 0；No Quote != No Trade；No Trade != Suspended；Market Session != Instrument Trading Status。
- Provider Health、Dataset Health、Resolved Evidence Health 分離。
- `cache_only` 不得產生 external fetch/subscription；completed-session read 不得在 GET 內暗中 repair。

### Actual-data proof

- 每個 production vertical slice 必須有可重現的 provider response 或 raw fixture、Canonical conversion、persisted row count、DB reread、resolver result、lineage 與 stable API projection 證據。
- 真實資料寫入需 idempotent；重跑不得重複污染或 destructive replace。
- malformed、空 payload、partial coverage、duplicate、provider error、timeout 與 restart 後 readback 必須有明確結果。
- `market_daily_price`、`raw_fetch_result`、`source_registry` 與 `market_dataset_coverage_checkpoint` 優先透過 repository seam 沿用；若缺欄位使 lineage/quality 無法如實保存，才新增 additive migration。

### Output contract

- Data Plane 保留 domain-specific typed API；Decision Plane 保留 `omi.decision.v4`；Operations Plane 保留 health/jobs/settings。三者共用同一 resolved evidence semantics，不合併成 mega-response。
- Shared platform 擁有 stable evidence envelope、lineage、health、selection、fallback 與 limitations；TW domain 擁有 market-specific typed projection。
- `selected_provider` 可 outward 作 lineage，不可作下一次 acquisition control input。
- Provider-specific endpoint 只能是 diagnostic/admin/maintenance，不能成為正式產品 read path。

### Migration and safety

- 每個 capability/dataset 都必須有 legacy baseline、compatibility adapter、compare gate、rollback 與 legacy-removal gate。
- Source-ready、runtime-adopted、data-persisted、postcondition-satisfied 與 production-cutover 是不同狀態。
- KGI/M5 不得阻塞 CP0-CP8，也不得被拿來宣稱共同平台已經處理 realtime provider。
- 既有 worktree 變更視為其他任務資產；不得 reset、clean、revert 或覆蓋。

## Context

- Repo：`C:\project\Open Market Intelligence`
- Branch：`codex/tw-etf-provider-normalization`
- Inspection HEAD：`6d508c7021c1050680262ce4a83f5b33e9f5eda7`
- Inspection baseline：39 個 modified/untracked status entries；包含既有 M5 與美股 OHLCV 進行中工作。
- Input proposal 1：`%USERPROFILE%\Downloads\OMI_TW_Market_Data_Platform_Convergence.txt`
  - SHA-256：`6660ad710db349a0990df0d8289ba4c04c7b98c3d0240b6e6ba8a3e8be410491`
- Input proposal 2：`%USERPROFILE%\Downloads\OMI_Market_Data_Core_Integration_Contract.txt`
  - SHA-256：`65e1b217aa3e4bbfaf9c31a7740d9bb3ed6ad605369742ac004f521f0eca3ce9`
- Current truth：repo `AGENTS.md`、`docs/product/*`、`docs/architecture/BackendArchitecture.md`、`docs/architecture/OmiDecisionContract.md`。
- Existing foundation：02A dark Provider Policy、Research Lease、Control Plane、pure Resolver 與 Dataset Registry；必須承接，不另造第二套。
- Existing actual data path：TWSE／TPEx official bulk fetch/parse 已寫入 `market_daily_price`，並由 EOD coverage checkpoint/scheduler 檢查與 repair；目前尚未被 Data Core Gateway/Resolver 統一擁有。
- Current verified divergence 詳見 `ArchitectureAudit.md`。

## Scope

### Family A — Durable dataset evidence（先做）

- `tw.daily_ohlcv.official` 與 full-market EOD coverage。
- `tw.index.daily`、`tw.market_breadth.daily`。
- 籌碼、法人、融資券、券商分點、股權分散。
- ETF PCF / iNAV / issuer resources。
- 基本面、營收、財報與 corporate events。
- 期貨、選擇權與其他正式 TW datasets。

### Family B — Public request-time market evidence（共同平台完成前納入，KGI除外）

- `quote.snapshot`。
- `intraday.bars`。
- `session.volume`。
- `index.quote` / `index.intraday`。
- `market.breadth.snapshot`。
- `auction` / `trading.status` 只先建立共同 contract 與 public-source 能力；KGI depth/realtime lease 留待後續 onboarding。

### Family C — Research and consumers

- Shared technical engine 與 backend authoritative indicator series。
- AI / `omi.decision.v4` evidence projection。
- Stable market APIs。
- Frontend render-only research indicators。
- Thin MCP / Kuro consumption。

## Deliverables

- `ArchitectureAudit.md`：current gap、actual-data inventory、target ownership 與 integration contract。
- `StorageAndBoundaryDecision.md`：CP0 storage/transaction/lineage decision與machine-enforced debt boundary。
- `Plan.md`：CP0-CP8 scope、acceptance、validation、rollback 與 deferred KGI/M5 boundary。
- `AcceptanceMatrix.md`：共同平台與每條 actual-data vertical slice 的 gate 狀態。
- `Progress.md`：可中斷續跑的證據、決策與下一步。
- Additive shared contracts/gateway、candidate repositories、TW provider catalog/ports、lifecycle integration、stable projections、boundary tests 與 compatibility adapters。
- 至少三條 production-wired actual-data proof：official daily OHLCV、full-market EOD lifecycle、official index/breadth；另完成一條不依賴 KGI 的 request-time data path。

## Done criteria

- `DataRequirementV2` / `RefreshRequirementV1` 能驅動共同 Gateway，且 consumer 不知道 provider。
- 官方 TWSE／TPEx daily OHLCV 從實際 ingress 經 canonical conversion、transaction-owned persistence、repository reread、Resolver、Dataset Health 到 stable projection全程可證明。
- Full-market EOD registry spec實際驅動expected date、eligibility、bounded refresh、postcondition、coverage checkpoint與scheduler catch-up。
- Official index/breadth至少一條completed-session production path使用同一Gateway/Result envelope。
- 至少一條不依賴KGI的request-time quote/intraday path經共同平台取得、resolve並outward。
- `cache_only` / GET read的external calls為0；repair只能經explicit bounded operation/job。
- Actual rows idempotent persist，重啟後仍可經共同repository/result contract讀回；lineage含provider/source、event time、fetched/received time、raw receipt、selection reason與limitations。
- `quote_depth.py`、`intraday.py`、`indices.py` 的納入範圍不再持有 cross-provider orchestration；尚未納入的 KGI legacy seam必須明確標示 deferred，不可誤算完成。
- Dataset Registry能對production TW dataset回答owner、expected state/date、eligibility、health、refresh operation、repairability、bounds、postcondition與capability mapping。
- AI/public query plan不再接受production provider control；HTTP/SSE/MCP維持同一backend-owned evidence semantics。
- 正式backend research indicators與frontend顯示共用同一algorithm version/data basis；local overlay若保留須明確標scope。
- 新增一個非KGI provider capability的測試證明只改catalog + port + adapter，不需修改consumer。
- `AcceptanceMatrix.md` 的 common-platform required rows全為 `passed`，且 KGI/M5 deferred rows不列入此 target完成判定。

## Open questions / assumptions

- 本任務採 additive v2 internal contract + v1 compatibility adapter，不直接破壞已完成的02A tests/fixtures。
- `market_daily_price JOIN raw_fetch_result JOIN source_registry` 初步具備daily candidate的source/raw/fetched lineage；CP0會用contract test決定是否足夠，不預先承諾migration。
- `market.breadth`、chips、ETF、fundamentals與derivatives共用lifecycle/health/lineage envelope，但保留各自typed payload與market-specific policy，不硬塞進quote/bar schema。
- CP2使用production DB中已保存之TWSE/TPEx public raw receipt的精確row excerpt，於in-memory SQLite重播完整write/readback；未對production DB寫入，也未切換runtime。
- 後續真實外部refresh、quota或runtime adoption仍須維持bounded operation與對應gate，不得以fixture replay誤稱live runtime adoption。

## 2026-08-27 K線／成交量／技術／EOD corrective extension

- 本延伸沿用既有 `MarketOhlcChartRead`、technical report／indicator engine、Dataset Registry EOD lifecycle、frontend chart components 與同一個長任務，不新增資料平台、Resolver、資料表、scheduler 或 consumer-side market owner。
- OHLCV outward contract 必須明示成交量 canonical unit；台股個股為 shares。Frontend 不得在「股」標籤下偷偷除以 1,000。
- `latest_data_date` 明確代表 latest finalized official daily date；若 points 含 session-close provisional overlay，必須另由 `intraday_overlay`／`latest_finalized_data_date` 說明，不能把 provisional point 說成 official daily finalized。
- Daily technical report 的 decision fields／rows／score 只使用 finalized official daily indicator。今日 provisional indicator 以 `current_observation`／`current_partial_indicator` 獨立投影，整組 price/range/volume/momentum state 需由同一 provisional bar 計算並標示 `decision_usable=false`。
- Frontend 台股日K必須優先合併 backend current partial point；只有明確 presentation-only indicator 或 parameter mismatch 才可 local calculate，且整體 projection scope 必須標成 `mixed`／`presentation_only`，不可誤標 `backend_authoritative`。
- EOD repair 必須分開 provider fetch/parse transport success 與 dataset advancement/postcondition。Previous-date／duplicate payload 不得增加 repair succeeded count 或更新 repair last-success；TWSE／TPEx venue coverage 必須可直接觀測。
- Source validation、runtime adoption、official provider publication 與 visible UI acceptance 仍是不同 gate；未重啟既有 launcher 前不得宣稱 production runtime 已載入本次 source。
