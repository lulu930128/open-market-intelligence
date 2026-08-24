# OMI Market Data Foundation v1 執行計畫

## Plan status

- 狀態：M0-M6 source implementation 已完成；Gate G1 runtime acceptance 尚未授權、未執行。
- 2026-08-19 使用者已核准本文件的 source implementation scope。
- 執行從 Milestone 0 baseline 開始，未跳過 dirty-worktree ownership gate。
- 每個 milestone 只有在 acceptance 與 validation 全部成立後才能前進，並同步更新 `Progress.md`。

## Execution model

- 採 Strangler Pattern：contract -> adapter shadow -> pure resolver -> registry/contract validation -> shadow compare -> documentation/handoff。
- Foundation 先建立 internal truth，再讓後續 02 執行 acquisition、Research Lease、canary 與 consumer cutover。
- 每個 milestone 形成局部、可審查、可回退的 patch boundary；不因長專案就允許大型混合 diff。
- 驗證從 pure unit/fixture tests 開始，再跑 targeted integration、public contract tests、safe backend profile；runtime adoption 是獨立 gate。
- 只要發現 status 軸重新混合、unknown 被壓成零、cache-only 發生 IO、public contract 無意變更或 dirty hunk ownership 不清，就立即 stop-and-fix。

## Workstream map

```text
M0 Baseline and inventory
        ↓
M1 Canonical value contracts
        ↓
M2 KGI/MIS direct adapters
        ↓
M3 Pure resolver and policies
        ↓
M4 Dataset/capability registries
        ↓
M5 Shadow/compare integration
        ↓
M6 Source validation and docs handoff
        ↓
G1 Separately authorized runtime acceptance
```

M1-M4 可在 pure fixtures 上完成；M5 才接入 legacy runtime seam，但仍不改 outward selected behavior。G1 未獲授權時不執行。

## Milestone 0 — Integration baseline、contract map 與 fixture inventory

### Scope

- Git/worktree、current truth docs、README/config、KGI/MIS quote path、AI capability/realtime contract、source health/status taxonomy、scheduler/repair、public API/MCP inventory、相關 tests。
- 只讀 repo/runtime/DB evidence；不新增 production code、不寫 DB、不 refresh provider、不 restart。

### Work

1. 保存 branch、HEAD、`git status --short --branch`、target-file scoped diff、untracked relevant files hash 與 existing task ownership。
2. 為以下 target 建立 pre-existing hunk map：
   - `backend/app/config.py`
   - `backend/app/market/quote_depth.py`
   - `backend/app/market/twse_mis_observation.py`
   - `backend/app/market/providers/kgi_superpy.py`
   - `backend/app/market/providers/kgi_superpy_bridge.py`
   - `backend/app/ai/capability_contract.py`
   - `backend/app/ai/capability_resolution_registry.py`
   - `backend/app/ai/realtime_contract.py`
   - `backend/app/ai/market_context/us_context.py`
   - `backend/app/jobs/scheduler.py`
   - `backend/app/jobs/taiwan_daily_metric_repair.py`
   - related tests/docs/MCP snapshots。
3. 畫出目前 KGI viewer lease -> snapshot -> `_kgi_quote_to_mis_message` -> MIS parser -> DB snapshot -> API/AI 的實際 call chain。
4. 盤點現有 TW MIS observation、KGI callback、quote/depth schemas、source lineage、volume units、timezone、session、trading status 與 health/status contracts，建立 ContractMap。
5. 盤點 public `omi.decision.v4`、`REALTIME_POLICIES`、capability scopes/paths/projectors、MCP snapshot 與 frontend consumers，建立 compatibility inventory。
6. 建立可安全提交的 fixture corpus：優先重用 sanitized unit fixtures；不得直接保存真實 KGI raw log、credentials、account identity 或巨大 provider response。
7. 檢查 `docs/product/*` 與 `BackendArchitecture.md` 的未提交 diff，區分「已確認產品方向」與「由本提案同步但尚未實作的內容」。
8. 決定 shared module 實際檔名與 import boundary；不為了符合提案文字硬搬既有 module。

### Acceptance

- 每個預定修改檔都有 owner、pre-existing diff、existing tests、public consumers 與 rollback seam。
- KGI->MIS masquerading、viewer-only lease、AI arbitrary quote、daily-price repair gap、US technical advertisement gap 都有 source-level evidence與至少一個 fixture/test seam。
- Fixture corpus 不含 secrets、account data、personal identifiers 或不可再生 raw provider logs。
- 可明確判斷是否能在目前 dirty worktree安全施工；若不能，記錄 blocker 並請使用者決定 integration base。
- 沒有 production source mutation、runtime mutation、DB write、provider fetch 或 commit/push。

### Validation

```powershell
git status --short --branch
git diff --name-only
git diff --numstat -- <target files>
rg -n "_kgi_quote_to_mis_message|not_subscribed|REALTIME_POLICIES|technical.structure" backend
```

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  tests\test_kgi_superpy_quote.py `
  tests\test_taiwan_stock_quote_depth.py -q
```

### Stop conditions

- Target file 的既有修改無法判斷 ownership。
- Untracked KGI source 並非使用者希望保留的 integration base。
- Current truth docs 與使用者核准的六項 proposed decisions 發生衝突。

## Milestone 1 — Versioned canonical value contracts

### Scope

- 新增 pure shared package，候選為 `backend/app/market_data/`。
- 新增 pure unit/serialization tests；不接 runtime，不 import provider/DB/AI。

### Work

1. 建立 strict enums/value objects：
   - market / venue / instrument type / interval / currency / quantity unit。
   - market session、instrument tradability、observation state、regulatory flags。
   - bar finalization、provider resource dimensions、freshness/evidence health。
2. 定義 `InstrumentKey`：
   - market、venue/listing、symbol、instrument type。
   - normalized representation、case rules、stable equality/hash/serialization。
   - 明確處理 TW stock/ETF/index、US stock/ADR/index，避免 provider symbol 成為 canonical key。
3. 定義 `SourceLineage`：
   - provider ID、feed/resource ID、event/received/fetched timestamps。
   - raw contract version、observation ID、cache state、bounded authority metadata。
   - timestamp awareness/order validation，禁止以 fetch time 假冒 provider event time。
4. 定義 Quote/Depth/Auction/Bar observations：
   - Decimal price、canonical quantity + unit、null/unknown rules。
   - trade evidence tri-state、auction provisional semantics、depth level capability。
   - finalized/partial 單一 enum、bar interval/start/end invariants。
5. 定義 Trading Status observation：
   - 只放 instrument tradability evidence，不放 PREOPEN/MARKET_CLOSED。
   - reason code、effective range、official/authority、lineage。
6. 定義 ProviderResourceHealth 多維 contract：
   - enablement、connection、entitlement、operational、evidence freshness。
   - effective summary 只能由 backend projection 計算，不取代各維度。
7. 定義 internal `CandidateSummary`、`Resolved*` 與 `SelectionReason`；candidate list bounded，raw payload 不進 resolved/public contract。
8. 建立 versioning、JSON serialization、forward-compatible optional fields 與 validation error contract。

### Acceptance

- `Unknown != 0`、missing/zero-like、timezone、unit、out-of-order、duplicate、partial/finalized、tri-state trade evidence 均有 tests。
- `MarketSession` enum 不含 tradability，`InstrumentTradability` 不含 session/regulatory/observation states。
- TW lots 可明確轉換並保留 raw unit lineage；US shares 不被當成 lots。
- Naive datetime、negative quantity、invalid Decimal、矛盾 bar state、listing identity collision fail closed。
- Shared package import graph 不包含 `app.market`、`app.us_market`、SQLAlchemy、FastAPI、provider SDK 或 `app.ai`。

### Validation

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  tests\test_market_data_contracts.py -q
..\.venv\Scripts\python.exe -m compileall -q app\market_data
```

### Stop conditions

- Contract 需要用 provider raw field 才能表達核心 semantics。
- Instrument identity 無法在 TW/US 現有資料模型下避免 collision。
- 型別設計需要新增 dependency 或 DB schema 才能成立；先提出替代方案，不直接新增。

## Milestone 2 — KGI TW / TWSE MIS direct canonical adapters

### Scope

- Market-specific pure conversion modules與 fixtures。
- Legacy quote-depth path仍 active；不改 provider selection、不新增 subscription。

### Work

1. 將 KGI raw quote callback直接轉為 Quote/Depth/Auction observation，不經 `_kgi_quote_to_mis_message()`。
2. 將 TWSE MIS raw message直接轉為同一 canonical contracts；MIS-specific `z/y/ts/pz/ps` 不擴散到 shared layer。
3. 將 provider `suspend`、`simtrade`、missing quote、odd-lot scope、entitlement/error 分別映射到正確 observation/health dimensions。
4. 確保 indicative auction 不被當 actual trade；cumulative volume 不製造不存在的 last trade price。
5. 建立 `legacy_projection_for_comparison` 或等價 comparator input，但不讓 canonical adapter依賴 legacy MIS schema。
6. 建立 sanitized fixtures：
   - KGI regular quote、simtrade、suspend hint、missing price/volume、stale event、depth partial。
   - MIS regular、preopen/closing auction、awaiting first trade、empty quote、provider error。
   - zero-like、malformed、timezone boundary、out-of-order、duplicate。

### Acceptance

- KGI canonical adapter import/call graph不包含 `_kgi_quote_to_mis_message()` 或 MIS parser。
- 同一 canonical field在 KGI/MIS 具有一致 unit/time/null semantics。
- 正常盤 last trade / OHLC / cumulative volume / five levels與 legacy fixture 等價；不等價項目有明確 semantic mismatch reason。
- KGI suspend hint不會因單一 provider hint直接升級成 official suspended；Trading Status Resolver 可保留 candidate與 authority。
- Adapter 無 IO、無 DB、無 global manager state，純 fixture test deterministic。

### Validation

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  tests\test_market_data_contracts.py `
  tests\test_market_data_taiwan_adapters.py `
  tests\test_kgi_superpy_quote.py `
  tests\test_taiwan_stock_quote_depth.py -q
```

### Stop conditions

- 為追求 parity 而把 MIS raw fields塞回 canonical contract。
- Adapter 必須讀 DB或市場 session 才能 parse raw payload；應改成由 caller傳入明確 context。
- 無法判斷 provider value是 missing、zero或not applicable；保持 unknown並記 limitation，不猜測。

## Milestone 3 — Pure resolver、policy 與 reason codes

### Scope

- `market_data/policies.py`、`market_data/resolution.py`、pure tests。
- 不接 provider manager、不建立 lease、不改 public response。

### Work

1. 定義 internal data requirement：`cache_only / prefer_live / require_live / completed_session` 與 purpose、capability、market/session context。
2. 將 `completed_session` 保持 internal；public v4 值擴張延後到 02。
3. 定義 provider policy input：market、capability、session、instrument eligibility、entitlement、candidate freshness、authority與 purpose；不得使用 consumer-provided provider priority。
4. 實作 pure `resolve_quote()`、`resolve_depth()`、`resolve_bar_series()`、`resolve_trading_status()`。
5. 產出 bounded candidate summaries、selected observation、selection reason code、fallback chain、policy satisfaction、freshness、facts/research usability與 limitations。
6. 定義 temporal coherence：quote/depth若選自不同 provider，outward projection必須保留各自 lineage，不合成單一虛構 snapshot。
7. Provider disagreement以 issue/reason呈現；不得任意平均、混欄或用單一 global `source_grade` 決定。
8. 定義 acquisition port protocol，但不提供 production KGI Research Lease implementation。

### Acceptance

- Same inputs always produce same resolved result與 reason code。
- Resolver tests覆蓋 primary live/fallback live、primary stale/fallback current、unavailable、all unavailable、provider disagreement、cache-only、completed-session、require-live unmet。
- `cache_only` acquisition mock call count為0；pure resolver不能 import或呼叫 fetch/lease。
- Candidate list與fallback chain有 hard bound，response size不隨 raw provider payload無界增長。
- `require_live` 未滿足時不把 completed/stale冒充live；`prefer_live` fallback保留 semantics。
- Official trading status evidence優先於 provider quote hint；衝突保留 candidates與confidence/authority。

### Validation

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  tests\test_market_data_resolution.py `
  tests\test_market_data_contracts.py -q
```

### Stop conditions

- Resolver開始取得global settings、provider manager、DB Session或network。
- Provider priority無法用版本化policy/reason code解釋。
- Resolved result需要複製完整raw candidates才能被consumer理解。

## Milestone 4 — Dataset Registry v1 與 Capability truth validation

### Scope

- Shared Dataset Registry、AI capability mapping/validators、targeted capability fixes/tests。
- 不啟動scheduler repair、不做DB migration、不實作US technical engine。

### Work

1. 定義 `DatasetSpec`：
   - dataset ID/version、market、scope kind、owner service/read operation。
   - frequency/release policy、expected-state policy、eligibility policy。
   - storage/read projection reference、postcondition、health resolver。
   - refreshability、optional operation ID、scope/budget/timeout、repairability。
   - capability IDs僅作stable mapping，不import AI registry。
2. 註冊五個初始dataset：TW quote/intraday/daily與US intraday/daily。
3. 將AI Capability Registry對應到dataset IDs與registered projectors；避免在AI層複製expected date/provider policy。
4. 建立兩層 contract test：
   - registry-level：advertised scope有projector registration。
   - fixture-level：每個advertised scope至少能由代表context產生非placeholder payload或truthful unavailable status。
5. Refreshable capability必須連到已註冊operation、server-side trust/budget與postcondition；否則改成non-refreshable/planned/unavailable。
6. 處理 `technical.structure / us_stock`：若本專案沒有真US technical projection，縮小advertised scope或truthful標成planned，不建placeholder。
7. 建立registry relationship圖與import contract，防止Dataset Registry、AI Capability Registry、scheduler互相循環。

### Acceptance

- 五個 DatasetSpec 都能回答 expected state、eligibility、owner、read/projection、health、refreshability與postcondition語意。
- `advertised + scope` 無projector或fixture payload時CI fail。
- `refreshable` 無operation/budget/postcondition時CI fail。
- US `technical.structure` 不再落入 `derived_payload_bug`。
- Dataset Registry不import `app.ai`、scheduler或provider SDK；AI可引用dataset IDs但不反向依賴。
- Existing public capability catalog變更若有，為truthful且有snapshot/contract test；不宣稱production runtime已採用。

### Validation

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  tests\test_market_data_registry.py `
  tests\test_ai_capability_contract.py `
  tests\test_technical_capability_contract.py `
  tests\test_ai_public_v4_contract.py `
  tests\test_api_contract_inventory.py -q
```

### Stop conditions

- Registry需要直接call scheduler/provider/DB才能判斷truth。
- 為通過contract test而塞placeholder payload或把missing轉空object/zero。
- Capability catalog改動造成HTTP/SSE/MCP語意分叉或consumer snapshot未同步。

## Milestone 5 — Shadow/compare integration 與 bounded observability

### Scope

- Existing quote-depth service seam、config、structured telemetry、shadow tests。
- Legacy仍為唯一outward selection owner；不建立Research Lease、不切consumer。

### Work

1. 實作單一 `canonical_market_data_mode`：`off/shadow/compare/canary/on`；Foundation只允許off/shadow/compare，invalid state fail closed。
2. 預設 `off`。`shadow` 只產canonical observation並做validation；`compare` 額外比較legacy/canonical summary。
3. KGI與MIS在同一次既有payload處理中產生legacy與canonical結果，避免shadow額外fetch/provider call。
4. Comparator使用versioned mismatch taxonomy：
   - identity、time、session、price、volume/unit、depth、auction、trade evidence、trading status、freshness、lineage、serialization。
5. Telemetry只記bounded counts、field names、reason codes、provider/resource、market phase與sanitized values；禁止raw payload、credentials/account IDs。
6. 設定hard bounds：candidate/mismatch數量、log length、sampling rate、per-symbol memory與error rate。
7. Legacy fallback若被canonical projection path使用，明示 `legacy_compatibility_used`；shadow模式不得改public response。
8. 加入fault injection：canonical adapter exception、malformed payload、comparator exception、telemetry failure都不得中斷legacy quote path。

### Acceptance

- `off`與修改前outward behavior等價。
- `shadow/compare`不新增provider call/subscription、DB write、public field或latency超出既定bounded budget。
- 正常fixture zero semantic mismatch；允許的representation differences有版本化分類與明確allowlist。
- 任何price/volume unit、session、trade evidence、trading-status mismatch都不是warning-only，必須fail targeted acceptance。
- Shadow exception/telemetry failure不影響legacy response，但error可觀測且不被silent吞掉。
- Config invalid combination在startup/config validation fail closed；不再使用四個可互相矛盾的boolean flags。

### Validation

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -p no:cacheprovider `
  tests\test_market_data_shadow_comparison.py `
  tests\test_market_data_taiwan_adapters.py `
  tests\test_taiwan_stock_quote_depth.py `
  tests\test_kgi_superpy_quote.py `
  tests\test_api_contract_inventory.py -q
```

### Stop conditions

- Shadow需要第二次external fetch或額外KGI subscription。
- Comparator/telemetry會寫raw provider payload、放大response或污染caller transaction。
- Legacy outward response因shadow結果而改變。

## Milestone 6 — Source validation、architecture sync 與 02 handoff

### Scope

- Full targeted regression、safe backend profile、docs/task progress、02 interface contract。
- 未授權時不restart、不live provider smoke、不commit/push。

### Work

1. 跑Foundation targeted test matrix、compile/import contract、public API/MCP inventory與safe backend profile。
2. 驗證no DB migration、no frontend code、no account/portfolio coupling、no provider-specific shortcut擴散。
3. 產出Foundation acceptance report：
   - contract versions、registered datasets/capabilities。
   - fixture coverage、mismatch categories/counts。
   - public compatibility、known limitations、not production-accepted items。
4. 只在source/test成立後同步`BackendArchitecture.md`、product docs與README必要段落；保留其他任務既有未提交hunks。
5. 建立02 handoff：
   - acquisition port與Research Lease lifecycle。
   - viewer/research/collector lease separation。
   - public `completed_session` contract decision。
   - KGI TW/MIS production policy、KGI US、Yahoo/AlphaVantage alignment。
   - canary/on、consumer cutover、runtime acceptance prerequisites。
6. 更新`Progress.md`，將狀態標為`source-complete, runtime adoption pending`或實際失敗狀態，不過度宣稱。

### Acceptance

- Foundation source-complete Done criteria全數有test/file evidence。
- Backend safe validation通過；任何無關既有failure都需證明隔離且不得掩蓋相關failure。
- Public routes/schema/MCP snapshots維持預期相容；truthful capability scope改動有明確contract evidence。
- Docs描述的是已實作truth，不把02/03 planned work寫成completed。
- No runtime restart/provider live smoke/DB write/commit/push without separate authorization。

### Validation

```powershell
cd "C:\project\Open Market Intelligence"
.\scripts\run-safe-validation.ps1 -Profile backend
git diff --check
git status --short --branch
```

必要的targeted contract commands以Milestone 0發現的repo現況為準，並記錄在`Progress.md`。

### Stop conditions

- Safe backend profile出現Foundation-related failure。
- Public contract/snapshot變更沒有同步consumer證據。
- Product docs與source reality不一致。

## Gate G1 — Separately authorized runtime acceptance

### Authorization requirement

只有使用者另行明確授權component-scoped runtime restart/adoption後才能執行。Source implementation approval不包含此gate。

### Work

1. 透過OMI正式launcher/component owner重啟或reload；不依process name broad-kill。
2. 確認launcher log actual selected backend/frontend port。
3. 確認listener、PID、executable path、command line、start time、repo/source identity與health。
4. 驗證`/api/ai/tools` public catalog、代表性quote API與frontend proxy維持相容。
5. 先用no-external/fixture或既有viewer流程驗證shadow/compare telemetry。
6. 若另行授權KGI live smoke：single symbol、single login、bounded timeout、no Account/Order、finally cleanup，並驗證active lease/subscription歸零。
7. MCP若受contract catalog影響，做session-preserving `initialize -> tools/list -> representative tools/call`。

### Acceptance

- Runtime source adoption可由owner/path/start time/contract/behavior共同證明；HTTP 200 alone不算。
- Shadow/compare無outward regression、無額外provider subscription、無raw/secret leakage。
- Mismatch為0或所有差異已分類、核准、測試化；重大semantic mismatch先rollback mode to off並stop-and-fix。
- Runtime acceptance結果寫入`Progress.md`，不將盤後fixture誤稱盤中live acceptance。

## Detailed validation matrix

### Canonical serialization

- TW KGI regular quote、simtrade、suspend hint、missing/zero-like、stale/out-of-order/duplicate。
- TW MIS regular、preopen/closing auction、awaiting first trade、empty/provider error。
- TW level5與US level1 model compatibility。
- Decimal、timezone-aware timestamps、shares/lots/contracts conversion。
- Naive datetime、negative quantity、invalid symbol/venue、contradictory finalization fail closed。

### Resolver

- primary live / fallback live。
- primary stale / fallback current。
- unavailable / plan restricted / rate limited / disconnected。
- all unavailable。
- require-live unmet、prefer-live completed fallback、completed-session、cache-only。
- provider disagreement、official status vs broker hint、quote/depth provider mix。
- bounded candidates/fallback chain、stable reason codes、deterministic serialization。

### Registry and capability

- dataset current/stale/not-applicable/pending release/unknown eligibility。
- refreshable/non-refreshable/planned/unavailable。
- operation missing、budget missing、postcondition missing -> fail。
- advertised scope without projector/fixture payload -> fail。
- US technical missing projection -> truthful status, not placeholder。
- import-cycle/ownership contract。

### Shadow safety

- mode off/shadow/compare與invalid reserved modes。
- no extra fetch/subscription/DB write。
- adapter/comparator/telemetry fault isolation。
- bounded sampling/log/payload/memory。
- legacy outward parity與explicit legacy compatibility marker。

### Existing regression surfaces

- KGI provider/lease/quote-depth。
- TWSE MIS observation/session/auction。
- AI capability selection/projection/public v4。
- API inventory/MCP schema snapshot。
- source health/status dimensions。
- backend safe validation。

## Rollback strategy

- Default mode始終為`off`；Foundation失敗時停用shadow，不改legacy public path。
- Shadow/compare沒有DB schema或data migration，不需資料rollback。
- 不在Foundation刪除MIS/KGI legacy helper、snapshot table、route或consumer fields。
- Feature mode/config必須可在不改DB、不重建cache的情況回到off。
- Canonical adapter/resolver failure不得覆蓋legacy snapshot或寫出synthetic data。
- 若truthful capability scope改動產生consumer問題，以registry版本與snapshot回退，不恢復placeholder support。
- 任何rollback都不得使用`git reset --hard`、`git checkout --`、force push或清除user worktree。

## Stop-and-fix rules

- 任一Foundation-related targeted test失敗，先修正，不帶失敗進下一milestone。
- Unknown/missing被轉成0、false、empty-success或current時立即停止。
- Session、tradability、observation state或regulatory flag再次混成單一enum時立即停止。
- cache-only發生external IO、shadow額外fetch/subscription、read path寫DB時立即停止。
- Provider adapter開始決定cross-provider fallback、AI readiness或transaction時立即停止。
- Resolver開始import provider/DB/global manager或做side effect時立即停止。
- Public HTTP/SSE/MCP/front-end business semantics分叉時立即停止。
- Advertised capability沒有projector/fixture或refreshable沒有operation/postcondition時不得以skip/placeholder放行。
- Dirty worktree ownership不清或patch會覆蓋user hunk時暫停並請使用者確認。
- 需要DB migration、runtime restart、live provider login、付費/quota、commit/push時停在授權gate。

## Decisions

- 2026-08-19：採條件式通過的Foundation方向；先修正status axes、health dimensions、typed contract與milestone邊界。
- 2026-08-19：01停在source-complete + shadow/compare；production Research Lease與consumer cutover移至02。
- 2026-08-19：Foundation不新增public `completed_session` value，不做DB migration，不改frontend。
- 2026-08-19：rollout改為單一mode，避免多boolean無效組合。
- 2026-08-19：目前dirty worktree先視為integration base，但Milestone 0必須證明可安全共存。
