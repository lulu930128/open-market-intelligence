# OMI Market Data Foundation v1 長專案

## Authorization state

- 規劃建立：已完成。
- Foundation source implementation（M0-M6）：已授權並完成。
- Production runtime adoption：**尚未授權**。
- Runtime restart / provider live smoke / DB write or migration：未授權，且不因核准 source implementation 自動取得授權。
- Commit / push / PR / release：未授權。

## Goal

- 建立 OMI 第一版 provider-neutral Market Data Foundation，讓 KGI、TWSE MIS、Yahoo、AlphaVantage 與未來來源都只能透過明確的 Canonical Observation、pure Resolution、Dataset Registry 與 backend-owned projection 進入 Research / AI / API。
- 消除 KGI 台股行情必須先偽裝成 TWSE MIS message 才能進入新資料路徑的架構耦合，同時保留 legacy quote-depth outward behavior，採 shadow / compare 遷移，不做 Big Bang rewrite。
- 將 Market Session、Instrument Tradability、Observation / Trade State、Regulatory Flags 與資料 Freshness 拆成正交維度，避免 `no quote`、`no trade`、`suspended`、`market closed`、`awaiting first trade` 再次被壓成單一 status。
- 建立 deterministic、可解釋、無 IO 的 resolver primitives，保留 selected provider、candidate summary、event/received/fetched time、fallback chain、selection reason 與 source lineage。
- 建立 Dataset Registry v1 與 Capability / Projection 一致性檢查，讓 expected state、eligibility、read owner、refreshability、bounded operation、postcondition 與 health 不再散落於 freshness、scheduler、repair 與 AI registry。
- 在不改 public API、不切 consumer、不啟動 production Research Lease 的前提下，完成 KGI TW / TWSE MIS canonical adapters、resolver shadow 與可量測比較，作為後續 `02_OMI_TW_US_Market_Data_Integration` 的穩定地基。

## Non-goals

- 不在本專案完成 KGI US、Yahoo / AlphaVantage production cutover、TW / US provider policy production adoption或 shared technical engine。
- 不在本專案把 AI/MCP `require_live` 接上 production KGI Research Lease；本專案只定義 acquisition / lease port 與 policy boundary，production lifecycle 留給 02。
- 不切換 Backend Quote API、Frontend、MCP 或 Kuro 到 canonical outward contract；既有 public response 第一階段保持相容。
- 不把 Portfolio / Account 放進 `market_data`；KGI Account health、Position、Cost、Cash 與 destructive sync protection留給 Account Plane / 03。
- 不把 `KGI Account 503` 註冊成 Market Data provider/dataset 狀態；Operations Plane 可彙整跨 plane 診斷，但 owner 必須分離。
- 不重建、清理、搬移或覆蓋 `data/open_market_intelligence.db`；Foundation 預設不做 DB migration。
- 不一次搬走 `backend/app/market/`、`backend/app/us_market/` 或現有 provider modules，不建立巨大共用 `MarketService`。
- 不刪除 `_kgi_quote_to_mis_message()`、MIS legacy parser、既有 quote snapshot table 或 compatibility tests；legacy removal 留到後續 production cutover 全面驗收後。
- 不在 cache-only/read path 隱性執行 provider fetch、subscription、repair、全市場 backfill、LLM、寫入或其他 side effect。
- 不新增 frontend redesign、inline warning workaround、consumer-side provider fallback 或 consumer-side freshness/trading-status inference。
- 不做無界 subscription、無界 retry、無界 raw candidate projection、付費／稀缺 quota smoke 或真實帳戶操作。
- 不處理與 Market Data Foundation 無關的 dependency upgrade、格式化、repo 清理或既有 dirty work。

## Hard constraints

### 1. Dependency and ownership

```text
Provider / Integration Adapter
        ↓
Canonical Observation
        ↓
Pure Resolution
        ↓
Market / Research Service
        ↓
AI / API Projection
        ↓
Frontend / MCP / Kuro
```

- Dependency 只能沿箭頭方向。Shared `market_data` 不得 import `app.market`、`app.us_market`、provider SDK、SQLAlchemy Session、router、frontend 或 MCP。
- Provider adapter 只做 IO、payload parsing、provider-specific error normalization 與 canonical conversion；不得決定 cross-provider fallback、AI readiness 或 DB transaction。
- Resolver 必須是 pure function：輸入 candidates + policy context，輸出 resolved result；不得 fetch、subscribe、sleep、讀寫 DB 或取得 global mutable provider state。
- Acquisition / lease、dataset health、repair planning、outward projection 與 transaction owner 必須是可辨識邊界，不得全部堆入單一 `resolution.py` 或 god service。
- Frontend、MCP、Kuro 與其他 consumer 不得指定 provider priority、自己 fallback、重算 freshness 或推導 trading status。

### 2. Orthogonal state model

- `MarketSession` 與 `InstrumentTradability` 是不同 contract。
- `PREOPEN`、`REGULAR`、`CLOSING_AUCTION`、`POST_CLOSE`、`CLOSED` 屬於 market session，不得放進 Instrument Trading Status enum。
- `AWAITING_FIRST_TRADE`、`INDICATIVE_OBSERVED`、`TRADE_OBSERVED` 屬於 observation/trade state，不得被當成停牌或市場 session。
- `DISPOSITION` 等法規狀態是 regulatory flags，不等於不可交易；不得與 `SUSPENDED`、`STOP_TRADING` 共用單一互斥 enum。
- `No Quote != No Trade`、`No Trade != Suspended`、`Provider unavailable != Dataset unavailable`、`Unknown != 0`。
- Freshness 必須考慮 market calendar、session、release window、instrument eligibility、event time 與 received/fetched time。

### 3. Canonical type and value integrity

- Canonical price 使用 `Decimal` 或等價的十進位安全型別；不得以 binary float 當持久 canonical truth。
- 所有 timestamp 必須 timezone-aware。`event_at`、`received_at`、`fetched_at` 語意分離，不得用 fallback current time 假裝 provider event time。
- `actual_trade_observed` 不得是會把 unknown 壓成 false 的普通 bool；需要明確 tri-state / observation-state enum。
- Bar finalization 使用單一 enum，避免 `finalized=true` 與 `partial=true` 等矛盾組合。
- Volume、depth size 與 auction quantity 必須有 canonical unit / scale；TW lots、shares、US shares、futures contracts 不得只靠自由文字猜測。
- Instrument identity 必須能穩定區分 market、venue/listing、symbol、instrument type；上市標的不可因 `exchange optional` 產生 collision。
- `provider_specific_hints` 若保留，必須 namespaced、versioned、bounded、sanitized，且不能成為 canonical decision/fallback 的秘密輸入。
- `source_grade` 不使用單一全域排名；authority / trust 必須依 capability、market、session 與 policy context 判定。

### 4. Health and capability dimensions

- Provider resource health 至少區分 enablement、connection、entitlement、operational request health 與 evidence freshness；`live / stale / rate_limited / not_connected / plan_restricted` 不得再塞入單一 status 後失去原因。
- Provider Health、Dataset Health、Resolved Evidence Health 是不同層；fallback provider 的問題不得污染已由其他 provider 補足的 selected evidence。
- Existing `request_live / scheduler_contract / provider_availability` 與 `omi.status-dimensions.v1` 不得被新的單一 enum 回歸覆蓋。
- Dataset Registry 是 Market Data lifecycle truth；AI Capability Registry 只能引用 dataset IDs / projection registrations，不得複製 expected-date、repair 或 provider policy。
- `advertised capability + scope => registered projector + fixture payload` 必須有 contract test；只有 path string 不算 projection 已存在。
- `refreshable => registered bounded operation + budget + postcondition`。沒有 operation 時必須 truthful 地標示 non-refreshable / planned / unavailable。

### 5. Public and internal contracts

- Foundation 先建立 internal canonical / resolved contracts；`omi.decision.v4`、HTTP、SSE、MCP 與 frontend public shape 預設不變。
- Resolved candidates 在 internal contract 中只保留 bounded candidate summaries；不得把完整 raw payload 或無界 observations outward。
- `execution_grade_usable` 不作為 Foundation 欄位，避免被誤解成交易授權。只表達 facts / research usability 與 limitations。
- `completed_session` 在 Foundation 先視為 internal data requirement / resolution mode；是否加為 public v4 `realtime_policy` 值留到 02 另做 additive contract gate。
- Legacy projection 若被使用，必須標示 `legacy_compatibility_used`、reason 與 lineage；不得靜默走 legacy 後仍宣稱 canonical cutover 完成。

### 6. Side effects, data, and security

- Foundation source implementation 不需要 DB schema 變更。若 Milestone 0 證明確有持久化必要，先暫停，另提出 migration、backfill、容量與 rollback 設計，取得使用者確認後才可進行。
- Shadow / compare 預設只保存 bounded counters、reason codes 與 sanitized summaries；不落 raw KGI callback、credentials、account identity 或巨大 provider payload。
- KGI SDK 維持 isolated Python 3.12 quote runtime，不修改 TLS/CA 驗證、不移回 backend 主 venv、不觸碰 Order/Account API。
- External fetch、KGI live login/subscription、provider quota、runtime restart、DB write、commit/push 都是獨立授權 gate。
- Feature rollout 使用單一 mode：`off -> shadow -> compare -> canary -> on`。Foundation 只實作／驗證 `off`、`shadow`、`compare`；`canary`、`on` 與 Research Lease 交給 02。

### 7. Dirty worktree and change control

- Integration base 是目前 branch `codex/tw-etf-provider-normalization`、HEAD `aa65e65` 的 dirty worktree；規劃時共有 49 筆 modified/untracked entries。
- `quote_depth.py`、`config.py`、KGI provider files、tests、product docs 與 Portfolio files 已有使用者／其他任務變更，全部視為既有基線，禁止 reset、restore、clean、reformat 或覆蓋。
- Milestone 0 必須先保存 target-file status、diff、hash 與 ownership；若無法安全區分 Foundation 與既有 KGI/Portfolio hunks，暫停並請使用者決定 integration base。
- 不因 product/architecture docs 已在 dirty worktree 改成 Foundation 方向，就把它們當成 implementation 已完成的證據。

## Context

- Repo：`C:\project\Open Market Intelligence`
- Source proposal：`%USERPROFILE%\Downloads\01_OMI_Market_Data_Foundation_v1.txt`
- Task docs：`docs/agent-runs/market-data-foundation-v1-20260819/`
- Planning date：2026-08-19（Asia/Taipei）
- Branch / HEAD：`codex/tw-etf-provider-normalization` / `aa65e65`
- Current worktree：49 筆 modified/untracked entries；`backend/app/market_data/` 尚不存在。
- Related systems：backend Market Data、KGI isolated runtime、AI capability / decision contract、scheduler / repair、source health、Frontend / MCP consumers、local SQLite、launcher runtime。
- Current truth references：`AGENTS.md`、`docs/product/*`、`docs/architecture/BackendArchitecture.md`、`docs/architecture/OmiDecisionContract.md`。

### Confirmed current-state evidence

1. `backend/app/market/quote_depth.py` 的 KGI path 仍由 `_kgi_quote_to_mis_message()` 產生 MIS-style message，再交給共用 MIS snapshot parser。
2. `backend/app/market/providers/kgi_superpy.py` 在 active lease 為 0 時回 `not_subscribed`；目前 lease 由 frontend viewer lifecycle 建立。
3. AI Taiwan stock context 直接呼叫 `get_taiwan_stock_quote_depth(refresh=True)`，沒有 request-scoped KGI Research Lease，因此 arbitrary AI/MCP quote 與 viewer-selected quote 的 provider path 不同。
4. `scheduler.market_daily_refresh` 目前主要更新 institutional trade；`taiwan_daily_metric_repair.py` 的 repair specs 未涵蓋 `market_daily_price`。
5. `technical.structure` 仍宣告給 `ALL_INSTRUMENT_SCOPES`，包含 `us_stock`，但 US context 沒有對應 technical payload projection。
6. Public AI capability contract 目前只接受 `cache_only / prefer_live / require_live`，尚未接受 `completed_session`。
7. 2026-08-19 planning review 的 KGI/quote targeted baseline 為 `39 passed, 10 subtests passed`。

## Corrected Foundation v1 architecture

### Shared boundary

候選 shared package：

```text
backend/app/market_data/
    __init__.py
    contracts.py        # pure value objects / enums
    policies.py         # pure request and selection policy types
    resolution.py       # pure candidate selection
    registry.py         # dataset/provider-policy specs, no AI import
    comparison.py       # bounded shadow comparison primitives
```

Market-specific adapters 留在市場 owner：

```text
backend/app/market/providers/
    kgi_canonical.py        # candidate name; final name follows existing style
    twse_mis_canonical.py

backend/app/us_market/providers/
    ...                     # 02 才做 production alignment
```

`market_data` 不持有 provider IO、不 import SDK、不讀 DB。Adapter 輸出 canonical observations；現有 market service 擁有 IO/transaction；resolver 只選已取得的 candidates。

### Core contracts

- `InstrumentKey`
- `SourceLineage`
- `QuoteObservation`
- `DepthObservation`
- `AuctionObservation`
- `BarObservation`
- `MarketSessionContext`
- `TradingStatusObservation`
- `RegulatoryFlag`
- `ProviderResourceHealth`
- `DatasetHealth`
- `ResolvedEvidenceHealth`
- `ResolvedQuote` / `ResolvedDepth` / `ResolvedBarSeries` / `ResolvedTradingStatus`
- `CandidateSummary` / `SelectionReason`

### Initial Dataset Registry scope

- `tw.quote.snapshot`
- `tw.intraday.bars`
- `tw.daily.ohlcv`
- `us.intraday.bars`
- `us.daily.ohlcv`

Registry v1 先建立 read-only expected-state、eligibility、owner、projection、health 與 optional refresh metadata；不在 Foundation 自動執行 repair。Scheduler / repair cutover 留給後續 integration/reliability milestone。

## Deliverables

- Versioned, typed canonical and resolved contracts with explicit invariants and serialization tests。
- KGI TW 與 TWSE MIS direct canonical adapters，使用 sanitized fixtures，不依賴 KGI->MIS masquerading 才能產生 canonical observation。
- Pure quote/depth resolver、policy context、reason codes、candidate summary 與 fallback lineage。
- Dataset Registry v1，涵蓋 TW/US quote/intraday/daily core datasets，且不反向 import AI。
- Capability / projection / refresh-operation consistency validator；修正或 truthful disable `technical.structure / us_stock` 的虛假 advertised support。
- 單一 canonical rollout mode 與 dependency validation；Foundation 只允許 `off/shadow/compare`。
- Legacy-vs-canonical bounded comparator、mismatch taxonomy、metrics/logging contract、fixture corpus 與 acceptance report。
- 既有 public quote/API/AI/MCP contract compatibility tests；Foundation source-complete 時 consumer 行為不變。
- `docs/architecture` / product docs 的最終同步，只在 code contract 與 tests 證明後進行，不以文件先行改寫當完成證據。
- 本目錄持續更新的 `Progress.md`，記錄 baseline、每個 milestone、實際檔案、測試、決策、known risks 與授權 gate。
- 02 handoff contract：acquisition port、Research Lease lifecycle requirements、consumer cutover prerequisites 與尚未 production-accepted 的限制。

## Done criteria

### Foundation source-complete

- Canonical schemas 為 versioned、typed、timezone-aware、unit-safe，且 unknown/null/zero、tri-state trade evidence、bar finalization 與 status axes 有 regression tests。
- KGI TW 與 MIS fixture 可直接轉成 canonical quote/depth/auction observations；KGI canonical path 不呼叫 `_kgi_quote_to_mis_message()`。
- Resolver 為 pure、deterministic、bounded、可解釋；`cache_only` 測試證明 resolver/acquisition port 不產生 external IO。
- Market Session、Instrument Tradability、Observation State、Regulatory Flags 分離，沒有 `PREOPEN`／`MARKET_CLOSED` 被放回 Trading Status enum。
- Provider resource health 是多維 contract，沒有用單一 enum 覆蓋既有 `status_dimensions`。
- Dataset Registry v1 可對五個核心 dataset 回答 owner、scope、expected state、eligibility、health、projection 與 refreshability；沒有平行複製 AI/scheduler truth。
- `advertised + scope => projector + fixture payload` 與 `refreshable => operation + budget + postcondition` contract tests 通過。
- `technical.structure / us_stock` 不再形成 advertised-but-missing projection；若未實作則 truthful disable/planned。
- Legacy vs canonical comparator 對正常盤、試撮、missing、stale、suspend hint、unit conversion 與 provider failure 產出 deterministic mismatch classification。
- Foundation 預設 mode 為 `off`；`shadow/compare` 不改 public response、不建立 provider lease、不寫 DB、不影響 legacy selected source。
- Existing quote-depth、KGI provider、AI capability、public v4、API inventory 與 MCP schema regressions通過；backend safe validation 通過。
- 沒有未授權 DB migration、runtime restart、provider live smoke、commit、push 或 release。

### Foundation runtime-accepted

此狀態需要另行授權，且不能由 source-complete 自動推定：

- 正式 launcher 以 component-owned action 採用新 source；actual selected port、listener、PID、executable path、start time 與 health 均已確認。
- `/api/ai/tools`、代表性 quote API 與既有 frontend proxy outward behavior 保持相容。
- `shadow/compare` 在明確 bounded symbol/session sample 下運作，沒有 raw credential/account leakage、無界 payload、額外 subscription 或 DB mutation。
- Mismatch report 按 category、market phase、provider、field 與 reason 彙整；任何 price/volume/unit/session/trading-status semantic mismatch 都先 stop-and-fix。
- 若進行 KGI live smoke，必須另有 single-symbol、single-login、timeout、cleanup 與 quota bound，並證明 lease/refcount cleanup；否則只宣稱 fixture/source acceptance。

## Approved implementation decisions

2026-08-19 使用者確認依本計畫執行；本次交付遵守以下決策：

1. 01 的 production scope 停在 canonical contracts、registry、shadow/compare 與 source validation；Research Lease production、consumer canary/cutover 移至 02。
2. `completed_session` 在 01 先是 internal data requirement，不立即擴張 public `omi.decision.v4` request enum。
3. Foundation 不做 DB migration；任何 persistence 需求都需停下另行確認。
4. `technical.structure / us_stock` 若沒有真 projection，先 truthful disable/planned，不以 placeholder 通過 CI。
5. 目前 dirty worktree 是 integration base；先做精確 baseline，保留所有既有 KGI、Portfolio、docs 與 frontend hunks。
6. Foundation source-complete 不等於 runtime-accepted；restart、live provider smoke、commit/push 各自仍需獨立授權。

## Open questions / assumptions

- Canonical value objects 優先使用 repo 既有 Pydantic/dataclass pattern；Milestone 0 會以 serialization、performance、strict validation 與 import boundary 決定具體工具，不新增 dependency。
- `InstrumentKey` 的最終 `venue/listing/canonical_id` 欄位會先盤點 TW stock/ETF/index、US stock/ADR/index、JP/KR/Crypto 現有 identity contract，避免只為台股設計。
- Provider health 多維欄位會優先對齊現有 `omi.status-dimensions.v1` 與 observability primitives，不建立第二份 taxonomy。
- Shadow telemetry 預設使用 structured logs / in-memory bounded aggregation；若需要 persistence，另行設計，不偷用 provider raw table。
- Product/architecture docs 目前已有未提交大幅修改；最終同步需逐段確認哪些是本專案 decision、哪些屬其他任務，不做整檔覆蓋。
- 若現有 dirty hunks使 target file 無法安全修改，專案應停止在 Milestone 0 並請使用者決定是否先固定 integration base；不得自行 commit 或搬移使用者變更。
