# OMI Backend Architecture Consolidation Plan

## Execution result

- M0-M9 completed on 2026-07-13 against baseline commit `910a1ca`.
- Final backend result: `580 passed, 1 warning`; validation logs at `.tmp/validation/20260713-100213`.
- Final isolated runtime smoke: 9/9 read-only endpoints returned HTTP 200.
- M8 selected Option A and retained one `db/models.py` / `Base.metadata` registry.
- Detailed implementation, compatibility evidence and remaining risks are recorded in `Progress.md`, `CompatibilityMatrix.md` and `DatabaseModelDecision.md`.
- The working tree is intentionally uncommitted until an explicit checkpoint commit request.

## Execution model

本計畫是多批次長任務，不要求在單一對話或單一 commit 完成。每次續跑都遵循：

1. 讀取本目錄的 `Prompt.md`、`Plan.md`、`Progress.md`。
2. 確認 branch、HEAD、worktree 與上次 validation evidence。
3. 只啟動一個 active slice；更新 `Progress.md` 的 current phase。
4. 先補 characterization/contract tests，再搬移責任。
5. 跑 targeted regression，失敗即 stop-and-fix。
6. 跨模組 slice 完成後跑完整 backend profile。
7. 檢查 staged scope、secret、產物與 diff，再建立單一目的 commit。
8. 更新 `Progress.md` 的 commit、驗證、決策與下一步。

## Milestone dependency order

```text
M0 Baseline and contract inventory
        |
        v
M1 Taiwan index provider boundary
        |
        v
M2 Transaction ownership map
        |
        v
M3 Market service facades (US -> JP -> KR)
        |
        +------> M4 Crypto/resource service audit
        |
        v
M5 AI answer composer pure modules
        |
        v
M6 AI tool market-context projections
        |
        v
M7 Router/API regrouping
        |
        v
M8 Conditional DB model decision
        |
        v
M9 Convergence, runtime/API smoke and final docs
```

M8 是 evidence-gated milestone。若 M0/M2 證據顯示 DB model split 風險高於收益，可用「不拆分但完成 ownership/import 文件」作為合格結論。

## M0 - Fresh baseline and architecture contract inventory

### Scope

- 重新確認目前 HEAD、worktree、branch 與 tests，不能只沿用 2026-07-13 baseline。
- 建立 `ArchitectureMap.md`、`CompatibilityMatrix.md`、`TransactionOwnership.md` 初版。
- 掃描 direct HTTP、provider adapters、SQLAlchemy `commit/rollback/flush`、public routes、service imports、AI consumer payload 與測試 patch seam。
- 將歷史 scan 中已過期的 line counts/dirty-worktree 描述標成 historical，不直接刪除證據。

### Required inventory

- Public route inventory：path、method、response model、主要 service call。
- Import seam inventory：router/jobs/AI/tests 對大型 service/module 的 import。
- Patch seam inventory：tests 直接 patch 的 private `_fetch_*`、helper 或 façade 名稱。
- Transaction inventory：query-only、mutate-only、commit-owning、rollback-owning、observability write。
- External IO inventory：provider、resource、target、timeout、source URL、error class、event recording。
- AI contract inventory：`human_answer`、`decision_contract`、slots、compact、warnings、missing、source refs。

### Acceptance

- 三份 inventory 文件可回答「誰擁有資料、誰 commit、誰依賴誰、哪些名稱不能直接搬掉」。
- Worktree 有乾淨 baseline 或明確 checkpoint；沒有混入使用者未完成變更。
- Baseline failure 與本計畫尚未修改前的 failure 被清楚區分。
- 後續每個 milestone 的 candidate files 與 tests 能由 inventory 追溯。

### Validation

```powershell
.\scripts\run-safe-validation.ps1 -Profile backend -BackendTestTimeoutSeconds 600
git diff --check -- docs/agent-runs/backend-architecture-consolidation-20260713
```

### Commit boundary

- Docs/inventory-only commit，例如 `docs: map backend architecture consolidation contracts`。
- 不在 M0 順手修改 production logic。

## M1 - Taiwan index provider boundary

### Problem statement

`backend/app/market/indices.py` 同時包含 provider HTTP、TWSE/TPEX/TWSE MIS/Yahoo payload parsing、cache、DB coverage、breadth fallback、index merge 與 public projection。它是台股核心，應先分離外部 IO，但不能改變 fallback/merge 語意。

### Slices

#### M1.1 Provider request contract

- 建立 `backend/app/market/providers/` 或等價清楚 namespace。
- 為 TWSE OpenAPI、TWSE RWD、TPEX、TWSE MIS、Yahoo index 建立 provider modules。
- 將 raw request、timeout、headers、provider context、HTTP error classification 移入 provider layer。
- 保留 stateful/session 特例的明確 module，不把所有 provider 強塞同一函式。

#### M1.2 Parser and payload normalization

- 將無 DB/cache 的 payload parser、date/number normalization、row extraction 移到 pure parser module。
- Parser 只接受 payload/value，回傳 record/dict，不發送 HTTP。
- Malformed、empty、unexpected schema 有 predictable exception 或 empty contract。

#### M1.3 Compatibility façade

- `indices.py` 保留目前 tests patch 的 `_fetch_json`、`_fetch_yahoo_index_points`、`_fetch_twse_*`、`_fetch_tpex_*`、`_fetch_mis_*` wrapper。
- Public `get_market_index_*` functions 保持名稱與 response shape。
- Cache TTL、fallback order、official/Yahoo/MIS merge、DB coverage 留在 service/orchestration layer。

#### M1.4 Remaining Taiwan provider paths

M0 inventory 顯示下列 Taiwan modules 也直接使用 `http_client`，在 index boundary 穩定後逐一處理：

- `market/intraday.py`；
- `market/market_chips.py`；
- `market/quote_depth.py`；
- `market/institutional_holding_ratios.py`；
- `market/broker_branch.py`。

`market/backfill.py`、三個 history backfill modules 與 `market/tw_futures.py` 使用 stateful session 或 transaction-coupled flow，不直接強制改成 stateless adapter。先在 `ArchitectureMap.md` 記錄 transport owner，再決定保留 documented stateful boundary 或建立專用 provider client。

### Acceptance

- `indices.py` 不直接 import `app.http_client` 或 `requests` 來發送 provider request。
- Taiwan read-path provider requests 不再散落 raw `http_get`；任何保留的 stateful session 都有明確 owner 與理由。
- Provider errors 帶有 `market/provider/resource/target` 與 bounded timeout。
- Taiwan breadth、index list、intraday、contribution、OHLC、summary contract 不變。
- `test_market_index_daily_stats.py` 原 patch seam 不需要大規模重寫。
- Source-health/provider-event 能辨識 provider failure，不把 failure 包成正常資料。

### Validation

```powershell
.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs @(
  'backend\tests\test_market_index_daily_stats.py',
  'backend\tests\test_provider_http.py',
  'backend\tests\test_provider_health.py',
  'backend\tests\test_market_source_health.py'
) -BackendTestTimeoutSeconds 420
```

完成 M1 所有 slice 後：

```powershell
.\scripts\run-safe-validation.ps1 -Profile backend -BackendTestTimeoutSeconds 600
```

### Commit boundaries

- `refactor: add Taiwan index provider adapters`
- `refactor: isolate Taiwan index payload parsers`
- `refactor: route index service through provider boundaries`

禁止把三個 slice 壓成一個難以 review 的大量搬移 commit。

## M2 - Transaction ownership and service contract map

### Problem statement

大型 market services 同時包含 query、mutation、commit-owning refresh、partial failure 與 observability writes。若先拆檔再釐清 transaction，容易造成 double commit、partial commit 或 exception 後未 rollback。

### Slices

#### M2.1 Static ownership inventory

- 掃描 `commit()`、`rollback()`、`flush()`、`refresh()`、bulk update 與 background job call chain。
- 在 `TransactionOwnership.md` 列出 function family、owner、idempotency、partial-failure strategy、observability behavior。

#### M2.2 Contract tests

- 為代表性 US/JP/KR/TW/crypto refresh 補「成功 commit、失敗 rollback、單 provider failure 隔離」測試。
- 測試不依賴 live provider，使用 mock payload/exception。
- 對 query-only helper 增加「不 commit」保護，僅在 blast radius 值得時加入。

#### M2.3 Naming and façade rules

- 若函式只 mutate 不 commit，採明確命名或 parameter contract。
- 若既有 public function 必須保留，新增 internal mutate helper 與 transaction-owning wrapper。
- 不在這一 milestone 改 DB schema。

### Acceptance

- 每個後續 service slice 都能指出 transaction owner。
- 不存在新增的「有時 commit、有時不 commit」隱性分支。
- Provider event/source-health write 不會意外提交主要 market-data transaction。
- 代表性 failure path 有 rollback/partial-failure regression。

### Validation

依 M0 inventory 選擇 targeted tests，至少包含：

```powershell
.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs @(
  'backend\tests\test_us_market_data.py',
  'backend\tests\test_jp_market_data.py',
  'backend\tests\test_kr_market_data.py',
  'backend\tests\test_crypto_market.py',
  'backend\tests\test_provider_health.py'
) -BackendTestTimeoutSeconds 600
```

## M3 - Market service façade decomposition

### Shared rules

- `service.py` 保留 façade，router/jobs/AI 暫不改 import。
- 一次只搬一個責任群，不做三市場同步 rewrite。
- Pure query/projection 先搬，transaction-owning refresh 後搬。
- 市場差異留在各市場 module；共用 helper 只處理已證明同 contract 的行為。

### M3.1 US service

Candidate responsibility modules：

- `stock_service.py`：stock master、search/discovery、SEC CIK binding。
- `watchlist_service.py`：group/item/tree/ranking/radar。
- `price_service.py`：daily price upsert/refresh/quality repair。
- `fundamental_service.py`：profile、SEC facts、corporate actions、macro/short volume。
- `resource_service.py`：resource refresh/summary/slot projection。
- `chart_service.py`：OHLC aggregation、intraday cache/projection。

Acceptance：

- `app.us_market.service.*` imports 繼續可用。
- Existing service-level patch targets 繼續有效或有明確 compatibility alias。
- Transaction ownership 與 M2 文件一致。
- `test_us_market_data.py` 與 watchlist/AI consumer regression 通過。

### M3.2 JP service

Candidate responsibility modules：

- stock/watchlist；
- daily price/chart/intraday；
- J-Quants/Yahoo fundamental refresh orchestration；
- margin/investor-type resources；
- resource summary/projection。

Acceptance：

- J-Quants plan/rate-limit fallback message 與 provider order 不變。
- JP source-health `availability_only` 語意不變。
- `test_jp_market_data.py` 與 provider adapter tests 通過。

### M3.3 KR service

Candidate responsibility modules：

- stock/watchlist；
- KRX/Naver index data；
- daily price/fundamental/investor trade；
- resource summary/projection；
- stock/index OHLC and intraday。

Acceptance：

- Naver realtime/intraday、KRX daily/index、OpenDART fallback/shape 不變。
- Composite provider source-health mapping 不變。
- `test_kr_market_data.py` 與 provider adapter tests 通過。

### Validation

每個市場 slice 先跑單市場 targeted，再跑完整 backend。三市場不得只在最後一起驗證。

```powershell
.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs @(
  'backend\tests\test_us_market_data.py',
  'backend\tests\test_jp_market_data.py',
  'backend\tests\test_kr_market_data.py',
  'backend\tests\test_market_provider_adapters.py',
  'backend\tests\test_watchlist_ranking.py',
  'backend\tests\test_watchlist_radar.py'
) -BackendTestTimeoutSeconds 600
```

### Commit boundaries

- 每個市場至少一個 commit；若單市場超過一個責任群，繼續拆 commit。
- Commit subject 應描述責任，例如 `refactor: isolate US market chart services`，不要使用 `cleanup service`。

## M4 - Crypto and resource-market responsibility audit

### Scope

- 盤點 `crypto_market/service.py`、`crypto_market/sources.py`、realtime collectors、REST refresh、cache/persistence 與 source-health 邊界。
- 盤點 `resource_market` provider IO、contract、service、source-health 與 OHLC projection。
- 不直接套用 US/JP/KR request-response pattern到 WebSocket/stateful collector。

### Decision gates

- Stateful stream lifecycle 是否已有清楚 owner；若已有，只抽 pure parser/projection。
- REST provider 是否應移入 explicit providers namespace。
- Collector/retry/backoff 是否涉及 production behavior；若是，另立 bounded slice。
- Placeholder/unfinished signals 不得因重構進入 default UI path。

### Acceptance

- REST、stream lifecycle、parser、persistence、projection responsibility 可辨識。
- 不增加 background task、連線數或 quota 消耗。
- Crypto/resource source-health 與 capability contract 不退化。
- `test_crypto_market.py`、`test_resource_market.py` 與相關 registry tests 通過。

## M5 - AI answer composer pure modules

### Problem statement

`answer_composer.py` 同時包含 locale labels、text normalization、data-limit interpretation、confidence cap、decision evidence、scenario/position planning、watchlist/digest formatting 與 high-level orchestration。直接搬大型 builder 風險高，先從 pure leaf functions 開始。

### Slices

#### M5.1 Characterization baseline

- 為繁中、英文、日文的代表性 answer 建立 exact-structure characterization tests。
- 覆蓋 stale/partial/missing/provider failure、entry/risk/position/watchlist/digest intent。
- 確認哪些文案是 public compatibility，哪些只測 semantic fields。

#### M5.2 Localization and text primitives

- 抽離 locale labels、text normalization、percentage/summary formatting。
- 不引入新的 i18n framework；沿用既有 labels/data structures。

#### M5.3 Data-limit and confidence projection

- 抽離 source-health data limits、generic limits、warning classification、confidence cap。
- Pure module 不讀 DB、不呼叫 provider、不呼叫 LLM。

#### M5.4 Decision evidence and scenarios

- 抽離 evidence summary/risk/data lines、scenario plans、counter evidence、position scenarios。
- 保留高階 builder façade 與輸入 shape。

#### M5.5 Watchlist and digest formatting

- 抽離 radar row selection/text/bucket summary、watchlist/digest answer formatting。
- 不改 ranking/radar business logic，僅搬 presentation projection。

### Explicit restriction

- 在 M5.1-M5.4 完成前，不直接搬移 `build_question_aware_consumer_answer()` 主體。
- 若搬移造成大量雙向 import，停止並縮小 pure leaf boundary。

### Validation

```powershell
.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs @(
  'backend\tests\test_ai_answer_composer.py',
  'backend\tests\test_ai_ask_stages.py',
  'backend\tests\test_ai_response_preferences.py',
  'backend\tests\test_ai_decision_core.py',
  'backend\tests\test_ai_freshness_guard.py'
) -BackendTestTimeoutSeconds 420
```

## M6 - AI tool execution and market-context projections

### Scope

- `ai/tools.py`：Taiwan read tools、compact evidence、freshness/slots projection。
- `ai/agentic_tools.py`：planner、budget、execution、progress events、US/JP/KR/crypto context projection。
- `market_payload_contract.py`：保留共用 payload/slot primitives，不吸收市場特有邏輯。

### Slices

- 建立 `ai/market_context/` 或等價 namespace，按 TW/US/JP/KR/crypto 分離 pure projection。
- Tool registry、input schema、budget 與 execution 留在工具層。
- DB query 可留在 read service，projection module 只接受 records/dicts。
- Source refs、freshness domains、slots、compact payload 由 contract tests 保護。

### Acceptance

- Tool names、schemas、planner steps、budget limits、progress events 不變。
- Projection module 無 DB write、refresh、provider IO 或 LLM call。
- MCP/frontend/Kuro 消費的 payload shape 不變。
- Cross-market overnight context 不因拆分失去台股主線語意。

### Validation

```powershell
.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs @(
  'backend\tests\test_ai_market_payload_contract.py',
  'backend\tests\test_ai_ask_stages.py',
  'backend\tests\test_ai_freshness_guard.py',
  'backend\tests\test_ai_us_decision_adapter.py',
  'backend\tests\test_us_market_data.py',
  'backend\tests\test_jp_market_data.py',
  'backend\tests\test_kr_market_data.py'
) -BackendTestTimeoutSeconds 600
```

## M7 - Router/API regrouping after service stabilization

### Preconditions

- M1、M3、M6 public/service boundaries 已穩定。
- `CompatibilityMatrix.md` 有 route inventory 與 representative response contract。
- 不存在仍在搬移的 service import seam。

### Scope

- 評估 `routers/market.py` 按 Taiwan quote/index/chips/futures/technical route family 拆分。
- 補齊仍未收斂的 Taiwan watchlist router helper，但不強迫與 US/JP/KR 共用市場特有 request。
- Router 保持 validation/schema/status code/service dispatch；市場邏輯移回 service。

### Acceptance

- FastAPI route path/method/response model 數量與 contract snapshot 一致。
- OpenAPI 變更只有預期 ordering/description 差異；不得遺失 route。
- Router import 不啟動 background task 或 provider IO。
- Representative API tests 與完整 backend 通過。

## M8 - Conditional DB model modularization decision

### Evidence required before code changes

- Alembic import/metadata behavior測試。
- 所有 `from app.db.models import ...` consumer inventory。
- Relationship、foreign key、table naming、Base metadata 與 migration runtime map。
- 確認拆分不改 table name、column、constraint、index 或 mapper ordering。

### Option A - Do not split

若 import/migration 風險高於收益：

- 保留單一 `models.py`。
- 完成 domain section map、ownership docs 與 import guidelines。
- 把此決策記錄為 intentional architecture，不再反覆以行數提出拆分。

### Option B - Compatibility package

若證據支持拆分：

- 建立 domain model modules，共用唯一 `Base`。
- `app.db.models` 繼續 re-export 全部舊名稱。
- 分批搬移 observability、market-core、US/JP/KR、crypto/resource、watchlist/portfolio。
- 每批驗證 metadata/table set 完全一致。

### Stop condition

- 任何 Alembic revision discovery、table metadata、relationship resolution 或 existing import 失敗，立即停止並回到 Option A。

## M9 - Convergence and final verification

### Cleanup audit

- 掃描 direct HTTP、duplicate provider helpers、legacy wrappers、dead imports、circular import workaround、TODO/placeholder。
- Wrapper 只有在 consumer inventory 為零且移除不 breaking 時才刪除。
- 更新 `BackendArchitecture.md`、三份 program docs 與所有 supporting maps。
- 將 historical scan 與本 program 的 current truth 清楚區隔。

### Full validation

```powershell
.\scripts\run-safe-validation.ps1 -Profile backend -BackendTestTimeoutSeconds 900
```

若 backend contract 觸及 frontend types/integration：

```powershell
.\scripts\run-safe-validation.ps1 -Profile frontend -FrontendTimeoutSeconds 300
```

### Runtime/API smoke

- 先讀 `logs/launcher/YYYY-MM-DD/launcher.log` 的 `selected=` 與 tray runtime URL。
- 使用實際 backend URL，不假設固定 `8400`。
- Probe health、provider events、source health、Taiwan index、US/JP/KR representative market endpoint、AI read-only ask path。
- 不使用 `refresh=true`、大量 backfill、付費 quota 或寫入型 smoke，除非另行核准。

### Final acceptance

- Worktree clean or only contains explicitly documented unrelated user changes。
- 完整 backend regression 通過。
- Representative runtime/API smoke 通過，或無法執行的外部原因有清楚證據。
- 所有 milestone commit 可獨立說明目的、驗證與風險。
- `Progress.md` 標記 done，列出 final commit、validation logs、known deferred items。

## Validation matrix

| Change type | Minimum validation | Escalation |
| --- | --- | --- |
| Docs/inventory only | UTF-8 readback, links/paths, `git diff --check` | No backend runtime |
| Provider adapter/parser | compileall, provider + market targeted tests | Full backend after slice |
| Transaction/service | market targeted + rollback/partial-failure tests | Full backend mandatory |
| AI answer/projection | answer/ask/freshness contract tests | Full backend mandatory |
| Router/API | route/OpenAPI contract + representative API tests | Runtime smoke if safe |
| DB model imports | metadata/migration/import tests | Full backend and migration smoke |
| Frontend contract impact | frontend lint/typecheck | Build/browser only if actual UI risk |

## Commit plan

預期約 12-18 個 reviewable commits，而不是一個大型 rewrite：

1. M0 docs/inventory baseline。
2. M1 Taiwan provider adapters。
3. M1 parser/compatibility façade。
4. M2 transaction contract tests/docs。
5. M3 US service slice(s)。
6. M3 JP service slice(s)。
7. M3 KR service slice(s)。
8. M4 crypto/resource slice(s)。
9. M5 answer localization/data-limit slice。
10. M5 decision/watchlist slice。
11. M6 tool context projection slice(s)。
12. M7 router regrouping。
13. M8 conditional decision/implementation。
14. M9 final docs/cleanup。

每個 commit 前：

- `git status --short --branch`
- staged file list and diff stat
- blocked artifact scan
- credential pattern scan
- `git diff --cached --check`
- validation evidence recorded in `Progress.md`

## Stop-and-fix rules

- Baseline tests 失敗：先定位既有 failure，不啟動 refactor。
- Circular import：停止搬移，縮小到更低層 pure helper；不使用大量 lazy import 掩蓋。
- Public route/schema drift：恢復 compatibility wrapper 或拆出獨立 migration proposal。
- AI wording/slot/freshness drift：先補 characterization，確認是 bug 還是 breaking change。
- Transaction ambiguity：停止 service split，先更新 ownership map 與 rollback tests。
- Provider live quota/account requirement：改用 mock/fixture；live smoke 另行核准。
- DB metadata/Alembic drift：立即停止 model split，保留 compatibility façade 或 Option A。
- Full backend failure：不得標記 milestone 完成或進入下一個 milestone。
- 發現使用者/其他流程的新改動：不 revert；先判斷是否相關並和它共存。

## Decisions

- 2026-07-13：建立新長任務目錄，不再把後續大型執行塞進 historical backend scan。
- 2026-07-13：台股 index provider boundary 排在 service/AI 前，因台股是產品核心且 `indices.py` 仍直接持有 provider IO。
- 2026-07-13：DB model split 改為 evidence-gated，不以 3158 行作為必拆理由。
- 2026-07-13：保留 compatibility wrappers，直到 consumer inventory 證明可安全移除。
