# 美股 Backend Shared Core 收斂

## 文件狀態

- 狀態：`M9_3A_HISTORY_COVERAGE_ACCEPTED`
- 建立日期：2026-08-29 Asia/Taipei
- Repo：`C:\project\Open Market Intelligence`
- Source baseline：branch `codex/tw-etf-provider-normalization`，HEAD `f8085f5ef607b1cda4196dc863b652918f86b5fc`
- 授權：2026-08-29 使用者已核准 M0–M8、M9.0 與下一版Daily precommit closeout；允許本對話直接使用正式OMI lifecycle restart、read-only DB probe、bounded AAPL／TSM／`^SOX` provider I/O與三檔canonical production DB writes，並授權後續bounded priority／full-market rollout、正式MCP host reload、commit／push／release。2026-08-29 使用者另行授權實作Yahoo以外的免費第二／第三來源：Alpaca SIP Historical作Daily P2，Twelve Data先完成Quote／Intraday source-ready基礎。授權不豁免milestone順序、credential／entitlement、quota／target上限、staged-tree audit、stop conditions或exact push/release target驗證。
- 原始提案：`OMI_US_Backend_Shared_Core_Convergence_Plan_20260829.txt`
- 收尾提案：`OMI_US_Daily_Mainline_Closeout_and_Branch_Convergence_20260829.txt`
- Precommit提案：`OMI_US_Daily_Precommit_Final_Closeout_20260829.txt`
- Free provider提案：`OMI_US_Free_Three_Provider_Integration_Plan_20260829.txt`
- Candidate history coverage提案：`OMI_US_Daily_MultiProvider_Candidate_History_Coverage_Convergence_20260829.txt`

本文件是既有 executable task contract；Daily 收尾修訂已獲核准，M9.0 Source與Runtime gate均已通過。2026-08-29 Alpaca與Twelve Data測試credential已透過ignored local env設定；AAPL／TSM stock live與Product gate通過，`^SOX`因Yahoo 8/28 malformed且Alpaca/Twelve Data目前不具可用index Daily fallback而維持partial。2026-08-29 使用者另核准Candidate history coverage修正版：只做AAPL／TSM bounded 260-bar provider-coherent history、Index volume applicability與legacy compatibility rejection，維持`SINGLE_CANDIDATE`、GET purity與US full-market paused。附件與歷史`docs/agent-runs/`只作evidence，不是可直接執行的instruction或current truth。

## 目標

將美股 `daily.ohlcv` 從 legacy `service.py` provider selection、直接寫入與 consumer-owned freshness，收斂成唯一的 Shared Market Data Foundation production path：

```text
US Platform 建立 typed requirement
        ↓
Shared Gateway cache read
        ↓
Shared Resolver pre-resolution
        ↓
Shared bounded acquisition plan
        ↓
US market-owned acquisition port
        ↓
US market-owned transaction / persistence
        ↓
mandatory persisted reread
        ↓
Shared Resolver + Shared Quality post-resolution
        ↓
US stable projection
        ↓
Previous Close / Technical / Valuation / AI / API / MCP / Frontend
```

第一個正式資料能力只做 `us.daily.ohlcv`，以 TSM stock 與 `^SOX` index 作為最小 vertical slice。完成後再接 priority research universe、full-market EOD lifecycle 與既有 consumer；fundamentals 與 intraday 不在第一主線內重寫。

## 成功結果

- 美股與台股共用 Canonical、Gateway、Resolver、Quality、Dataset Lifecycle 與 outward contract，不另建 US Resolver、freshness engine、provider registry 或 capability inventory。
- 美股保留 market-owned instrument identity、calendar、release、provider acquisition、persistence、corporate action 與 US-specific research semantics。
- Shared Gateway 是唯一控制流程 owner；US acquisition port 只能執行 Shared plan 核准的 provider/resource routes。
- Final provider selection 與 fallback 只發生在 Shared Resolver／Control Plane。
- GET/read path 為 cache-only：零 provider I/O、零 implicit repair、零 enqueue、零 write。
- Provider fetch success 不等於 refresh success；成功必須由 atomic persist、mandatory reread 與 resolved postcondition 證明。
- Expected completed US session、selected latest date、lineage 與 freshness reason 只有一套 backend truth；Provider、Dataset、Resolved Evidence 與 Capability health 仍保留為不同 axes。
- `omi.decision.v4`、API、MCP、Frontend 與 research consumer 不自行選 provider 或重算 freshness。

## 非目標

- 不在第一主線收斂 US intraday、premarket 或 after-hours Shared Core production path。
- 不重寫 SEC fundamentals、13F、Form 4、corporate actions 或既有 financial period engine。
- 不全面支援 IFRS、20-F、40-F 或所有 foreign issuer taxonomy。
- 不做 frontend redesign；只在 backend contract 穩定後做必要 consumer cutover。
- 不一次 backfill 全美股歷史，也不執行無界 provider calls。
- 不以 TSM 或 `^SOX` hardcode 代替一般化的 stock/index identity 與 applicability contract。
- 不複製台股 implementation；台股只作已驗證模式的 reference。
- 不自動交易、不下單、不新增 Execution Plane。
- 不刪除、重建或覆蓋 `data/open_market_intelligence.db`。

## 硬性限制

### Ownership 與 dependency direction

- 長期依賴方向固定為 `Provider -> Canonical Observation -> Shared Gateway/Resolver/Quality -> US Projection -> Consumer`。
- `backend/app/market_data/` 不得 import `app.us_market.service`、US provider implementation、SQLAlchemy models 或 transaction owner；既有 exact debt 只能縮小，不能新增 occurrence。
- US provider adapter 只做 I/O、payload parsing、provider error normalization 與 Canonical Observation conversion。
- US acquisition port 不得自行加入 provider route、私下 fallback、commit／rollback、選 final provider 或把 missing 補成零。
- Query/repository helper 不 commit；transaction owner 必須在 US market/job boundary，commit failure 必須 rollback 並保留原始錯誤。
- Consumer 不得直接讀 raw `USDailyPrice` 來選 provider、判 current、previous close、technical 或 valuation。
- Public router 只做 validation、dispatch 與 projection，不選 provider、不持 transaction、不實作 market logic。

### Shared contract gate

在 US production binding 前，必須完成或明確證明不需要以下 Shared Core 能力：

- Refresh requirement 可表達 reason、coverage scope/target、cursor/checkpoint、budget 與 postcondition。
- Persisted/canonical bar series fail closed 保護 provider/source lineage coherence。
- Dataset registry operation 有 executable binding、typed result 與統一 postcondition evaluation，而不是只保存函式名稱字串。
- Per-capability rollout 支援 `off / shadow / compare / canary / on` 與單一 rollback entrypoint。
- US daily expected-state port以 typed contract提供 calendar、expected completed session、release 與 eligibility；Shared Core 不反向 import US calendar implementation。

Shared contract 變更必須是 provider-neutral additive extension，服務本次 US integration；不得順手擴張成無關台股重構。因 shared contract 會影響台股，必須跑相關 TW regression，但不改變本任務「只實作美股能力」的 scope。

### Lineage 與 storage

- 現有 `USDailyPrice` 已確認不足以單獨重建完整 canonical lineage；production binding 前必須選定 normalized raw receipt relation、sidecar metadata 或 additive Alembic migration。
- Persisted evidence 至少能確定性保留 provider、source、authority、event time、fetched time、raw contract/parser version、content hash/raw receipt identity、finalization 與 price basis。
- 不得從 URL、provider name 或 ingestion time 虛構 authority、event time、finalization 或 adjusted/unadjusted semantics。
- Schema 變更只走 additive Alembic migration；需有 isolated upgrade、existing-row semantics、rollback／compatibility 說明，不可用 `create_all`、刪 DB 或重建資料代替。

### Temporal、freshness 與 quality

- Market Session、instrument status、bar finalization、authority、release、reconciliation、freshness 與 applicability 是正交 axes，不建立 universal temporal/status enum。
- Daily current/stale 以 market-owned expected completed session 與 released persisted evidence判斷，不以五個 calendar days 或 payload existence 判斷。
- `Provider Health`、`Dataset Health`、`Resolved Evidence Health`、`Capability Status` 不壓成單一健康燈；它們必須共享相同 expected/latest/lineage facts。
- Unknown 不等於 0；No Quote、No Trade、Suspended、Missing 與 Not Applicable 不互相替代。

### Instrument 與 volume applicability

- `^SOX` 必須能在沒有 company profile/SEC facts 時，以 market-owned instrument identity 建立 canonical `InstrumentTarget`。
- Index identity 不依賴 stock-only universe 或必然存在的 `USStockMaster.exchange` row。
- Index daily volume 不得用 `0` 表示；canonical quality 不把不適用的 volume 當 required missing field，outward 必須明示 `volume_status=not_applicable` 與語意。
- TSM daily volume 使用 shares，保留 canonical/provider unit lineage。

### API 與 compatibility

- `GET /us-market/ohlc/{symbol}` 最終不得接受或執行 `ensure_history`、provider、outputsize、adjusted 等 acquisition controls。
- Legacy GET compatibility 若暫留，只能 deprecated 且 fail closed／不執行 side effect，必須有 owner、consumer inventory、sunset 與 removal gate。
- Production refresh/repair 使用 explicit POST/job，但 public consumer 不指定 Yahoo／Alpha Vantage；provider-specific route只能是明確 diagnostics surface。
- Compatibility wrapper只能包新 canonical owner，不形成永久第二寫入或第二讀取路徑。

### 工作樹、安全與授權

- 現有 working tree 同時包含大量已修改／未追蹤的 TW、US、architecture 與其他工作；一律視為使用者或既有流程所有，不 revert、不 broad overwrite。
- 每一 milestone 先列 exact touched files/hunks，與既有 dirty diff 共存。
- 本任務已取得source、正式OMI restart、三檔bounded live seed、後續bounded rollout與publication授權；所有side effect仍只能在對應milestone prerequisites與stop conditions成立後執行。
- 付費／稀缺quota、full-market repair、production DB write、MCP reload、commit、push與release必須保存exact target、budget、before/after evidence與failure isolation；授權不允許無界擴張或broad staging。

## Current known state

- M0–M8 Source gate已通過；Shared Gateway／Resolver／Quality、US V2 descriptors、canonical acquisition、receipt/lineage persistence、Daily platform、priority/full-market lifecycle與主要consumer cutover均已存在。
- 正式 launcher 已採用 repo root、`.venv` Python、backend `8400`、frontend `3000`與Alembic `20260829_0073`；direct與proxy readiness均通過。
- Public Daily read已對所有symbols固定使用canonical cache-only；production acquisition另由rollout控制，runtime目前為`canary/canary_targets`且allowlist只有AAPL。
- AAPL、TSM與`^SOX`既有legacy rows很多，但符合canonical lineage的rows均為0；Resolver對三檔回missing是正確fail-closed。
- Full-market EOD scheduler原本預設包含`TW,US`，並曾建立US repair job；使用者已授權將本機設定改為`SCHEDULER_EOD_COVERAGE_MARKETS=TW`並正式restart。重啟後只建立TW EOD job，沒有新US full-market job。
- REST chart與refresh schema已additive承載canonical selection、quality、usability、persistence、postcondition與raw receipt facts；runtime OpenAPI已驗證採用。
- Public refresh provider參數已deprecated，僅`auto`可通過；非`auto`明確fail closed。Unknown identity在chart/history/refresh均由public router轉為404。
- `candidate_store.py`無production caller但tests仍依賴；Daily canary/shadow與Intraday功能共檔，不能整檔移除。
- Current architecture checker通過，`22 actual violations / 22 declared debt`；這只代表debt被凍結，不代表M9／M10已完成。
- `CurrentImplementationState.md`已按Source／Runtime／Live／Product分層更新；M9.0 running runtime已採用rollout stabilization source，M9.1 Live已取得授權但仍被M9.0.5／M9.0.6 gate阻擋。
- Precommit source probe已重現：`technical.structure` payload明示missing／quality unusable時，generic quality仍可升級成available／ready／facts與decision usable；`daily.ohlcv` missing payload也可被升級成available並把refresh recommendation壓成false。
- Provider-specific OHLC repair route仍enqueue legacy `service.repair_us_ohlc_history()`；legacy service保留private Yahoo／Alpha Vantage selection/fallback，是第二個Daily write orchestration owner。
- REST chart仍重算canonical freshness／is_current／refresh recommendation；request-specific chart coverage可保留，但不得覆寫Platform／Shared Quality truth。REST schema與Frontend仍缺完整Daily parity，尤其`selected_event_at`。
- Working tree高度混合；Daily closeout只做exact files/hunks，不做Git branch merge或broad staging。Commit／push雖已授權，仍只能在exact staged-tree、target/upstream/ancestry與remote SHA gate成立後執行。

## 交付物

### Source 與 contract

- Shared Core additive contract hardening，只限US接入所需的 provider-neutral gap。
- US V2 provider descriptors與bounded acquisition port。
- US daily candidate repository、raw receipt/lineage storage decision與transaction owner。
- `USDailyOhlcvPlatform` stable read/refresh interface。
- US expected-state/instrument identity/applicability ports。
- Dataset executable operation binding、priority/full-market lifecycle convergence與per-capability rollout。
- GET purity、previous close、technical、valuation、AI freshness/source health/capability projection consumer cutover。
- Exact architecture debt removal與negative tests。

### Evidence

- Failing fixtures／baseline，證明每個已知問題在修正前可重現。
- Contract、repository、transaction、Gateway、Resolver、quality、consumer與architecture targeted tests。
- Migration upgrade／compatibility／rollback evidence（若採schema方案）。
- TSM與`^SOX` source vertical-slice artifacts。
- Source、Runtime、Live、Product分層 acceptance matrix。
- Runtime adoption與restart後cache-only readback artifacts（已授權，依milestone gate執行）。

## 完成條件

### Source Gate G0 — Shared contract ready

- Refresh reason/coverage/cursor semantics有typed contract與tests。
- Bar candidate/provider coherence遇到mixed lineage會fail closed。
- Dataset operation可執行、bounded、輸出typed result並驗證postcondition。
- Per-capability rollout/rollback可重用。
- US manifest對齊實際Shared Core contract version，但仍可保持production mode=`off`。

### Source Gate G1 — TSM + `^SOX` vertical slice

- Yahoo／Alpha Vantage acquisition只執行Shared plan routes。
- Raw receipt與canonical bar atomic persist；mandatory reread後才可成功。
- TSM latest date等於expected completed session，volume為shares。
- `^SOX`不依賴company/SEC，volume為null且`not_applicable`，不出現假0。
- Resolver是唯一final selection owner；stale／partial／missing／provider failure fail-visible。
- GET zero provider I/O/write/queue；explicit refresh bounded。

### Source Gate G2 — Consumer convergence

- Previous close只由resolved daily series取得，缺expected date時不退回更舊日期冒充。
- Technical與Radar共用resolved daily bars；stale historical facts可保留，但research/decision usability降級。
- Valuation共用resolved daily close，不指定Yahoo。
- AI、source health、data freshness與capability projection共享expected/latest/lineage facts，且保留不同health axes。
- Production consumer對legacy raw selection occurrence歸零，或只剩精確登錄且有sunset的compatibility debt。

### Source Gate G3 — Lifecycle與debt closure

- Priority research repair走同一US daily platform。
- Full-market EOD使用同一acquisition/persistence/expected-state owner與bounded cursor/checkpoint。
- `shared-eod-us-service`、`shared-eod-us-calendar`、`shared-eod-us-rollback`、`get-us-ohlc-ensure-history`及伴隨的GET provider-control debt完成移除或有明確、較窄的temporary seam。
- Architecture guard無新增violation；移除occurrence時同步移除stale debt entry。
- Backend targeted與safe validation可接受；未驗證surface明確保留pending。

### Runtime acceptance

- 正式launcher lifecycle持續證明project root、interpreter、selected port、migration、loaded source identity／SHA與effective per-capability mode。
- AAPL、TSM與`^SOX`完成cache read -> explicit refresh -> persist -> reread -> resolve，restart後cache-only readback仍一致。
- Runtime rollout狀態必須真正約束outward selection／acquisition scope；不能只在health宣稱canary。
- 不以health endpoint或source test單獨代替runtime adoption。

### Live acceptance

- 在合法provider entitlement與completed-session release window取得真實Yahoo／Alpha Vantage evidence。
- Provider failure、rate limit、empty、stale/fallback與postcondition failure有正式證據。
- Full-market／priority repair已取得原則授權，但只能在另立的bounded rollout milestone、exact quota與runtime budget內執行。

### Product acceptance

- API、AI、MCP、Frontend對AAPL、TSM與`^SOX`的selected provider/source、fallback、selection reason、expected/latest date、freshness、coverage、usability、previous close、volume applicability與limitations一致。
- `omi.decision.v4` capability readiness與evidence一致；consumer沒有自行修補provider、freshness或volume語意。
- Runtime、Live未通過的surface不標accepted，Source PASS不冒充產品完成。

### Daily Mainline Clean

- Priority與full-market rollout完成前保留可回退的Daily canary／compare telemetry；三檔vertical slice只建立`US_DAILY_CANARY_RUNTIME_LIVE_PRODUCT_ACCEPTED`，不冒充全市場完成。
- Legacy Daily production write caller與legacy upsert caller均為0；diagnostics／compatibility seam有owner、scope、sunset與negative test。
- `candidate_store.py`在tests與exports遷移後移除；`resolved_reads.py`保留為compatibility-only且禁止新增production caller。
- Freshness、coverage、continuity、previous close與refresh recommendation由Platform／canonical projection單一擁有，Chart只做aggregation、pagination與shape mapping。
- Priority與full-market gates通過後才退役Daily canary/shadow部分；Intraday compare功能不受影響。
- Architecture debt同步縮小、guard與targeted regression通過，最後建立`US_DAILY_MAINLINE_CLEAN`。

## 已確認的執行決策與授權

1. **M9.0.5 Pre-live source closeout**：先修technical semantic quality、refresh recommendation、repair single owner、candidate store與Chart／consumer truth；未轉綠前不做provider I/O或production DB寫入。
2. **Bounded live授權**：已核准AAPL、TSM、`^SOX` explicit provider I/O與canonical production DB寫入；每檔最多2次provider attempts／external calls、總上限6次，三檔以外禁止由此slice寫入。
3. **Rollout gate命名**：三檔先建立`US_DAILY_CANARY_RUNTIME_LIVE_PRODUCT_ACCEPTED`；只有priority/full-market完成後才建立全Daily runtime/live/product gate。
4. **Canary/shadow retirement**：不得在三檔通過後立刻移除；預設保留到priority/full-market與rollback evidence完成，再只移除Daily部分。
5. **Legacy compatibility**：public provider參數預設deprecated並對非`auto` fail closed；repair全面改走Dataset Operation／Platform，provider-specific diagnostics不得成為production fallback。
6. **Git/release**：commit／push／release已授權，但只能在`US_DAILY_PRECOMMIT_CLEAN`、exact staged-tree validation、secret/artifact audit與push target/version證明後執行；附件的「旁支收斂」仍不代表Git branch merge或delete。
7. **Free provider extension**：Daily production priority固定為Yahoo P1、Alpaca SIP Historical P2；Twelve Data不進Daily，先只建立Quote／Intraday source-ready client與pure canonical fixtures。Alpha Vantage Daily必須等Alpaca deterministic、Live、persist/reread、runtime與product gate全部通過後才退場；Fundamentals／Corporate Actions保留。
8. **AAPL修復語意**：Yahoo 2026-08-28 `close=null`保留為原始failure evidence，不補值、不覆寫；只有Alpaca完整final bar經既有transaction持久化、mandatory reread與Shared Resolver選中後，才算解決AAPL缺口。
