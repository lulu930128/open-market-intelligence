# 對外能力與補值閉環 v1 契約設計

## 問題定義

現況有四套互相關聯但未完全同源的真相：

1. `CAPABILITY_SPECS`：57 項 public capability 與部分 fill/refresh metadata。
2. `ALLOWED_TOOLS`：26 個 backend 可執行工具與 trust/budget policy。
3. `EXECUTABLE_FILL_OPERATIONS` / `FILL_OPERATION_PRODUCED_CAPABILITIES`：20 個 continuation 可下達的 operations。
4. `capability_context`：15 項 curated provider readiness。

這造成三類漂移：

- capability id 相同但不同 scope 的 refreshability 不同，例如 `quote.snapshot`、`intraday.bars`、`daily.ohlcv`、crypto market/asset。
- planner 可以執行 internal composite tool，但 fill plan 不會告訴 consumer，例如 cross-market、TW watchlist、US company profile/actions。
- operation 逾時雖建立 `ai.tool_refresh` job，對外只回 raw `/api/jobs/{id}`；純 MCP caller 沒有同一 surface 的安全查詢方式。

## 單一 registry

新增 backend-owned `CapabilityResolutionSpec`（實際檔名可沿用 `capability_contract.py` 或拆成 pure module），每筆以 `(scope_type, capability_id)` 為唯一 key。最少包含：

| 欄位 | 用途 |
|---|---|
| `scope_type`、`capability_id` | 避免同 capability 跨市場誤共用 action |
| `implementation_status` | `connected`、`conditional`、`private`、`provider_not_connected`、`deprecated` |
| `resolution_mode` | `reader_fetch`、`granular_fill`、`composite_fill`、`scheduler_cache`、`cache_only`、`derived`、`not_applicable` |
| `operation` | 可執行 tool；無 operation 時必須為非 action resolution |
| `produces` | operation 完成後可重建的 capabilities |
| `depends_on` | derived capability 的輸入與 lineage |
| `provider_contract_id` | 連到 15 項 provider readiness 或新 provider contract |
| `freshness_owner` | reader、service、scheduler、cache table 或 derived projection |
| `side_effect_policy` | read-only、cache write、DB write、private read、paid/quota |
| `trust_requirement` | public local、loopback trusted、token trusted、key required |
| `bounds` | request count、wall clock、rows、date range、symbols、retry |
| `market_session_policy` | market-open、post-close、latest completed session、calendar-aware |
| `backgroundable` | 是否可轉為 tracked `ai.tool_refresh` job |
| `blocking_reason`、`next_fill` | conditional/blocked 時的 consumer-visible 說明 |
| `deprecated`、`replacement` | 相容 migration |

由這個 registry 衍生或驗證：

- public capability catalog metadata。
- allowed tool names 與 policy references。
- executable fill operation set。
- produced capability mapping。
- fill-plan action/deferred/unfillable partition。
- `capability_status` full registry view。
- `/api/ai/tools` schema metadata與 generated snapshots。

若為降低第一版 diff 而暫時保留既有常數，必須新增 pure parity assertion，任何集合漂移都讓 tests 失敗。

## 三層狀態模型

每個 capability 必須同時保留三層狀態，不以單一 `status` 取代：

| 層 | 例子 | 回答的問題 |
|---|---|---|
| implementation/provider | connected、private、key_required、provider_not_connected | 系統是否有合法能力與 provider？ |
| operation | not_requested、planned、running、background_running、succeeded、partial、failed、timeout、blocked、skipped | 本次是否有執行補值，結果如何？ |
| evidence | current、stale、partial、missing、not_applicable、unobserved | 回答使用的資料現在是否可用？ |

Transport 狀態另列，例如 HTTP/MCP protocol success、timeout、malformed response；MCP business failure 維持 `isError=false` 並由 structured result 表達。

## Public resolution projection

在 `omi.decision.v4` additive 增加每個 selected capability 的 resolution metadata；舊 consumer 可忽略：

```json
{
  "capability_id": "cross_market.relations",
  "scope_type": "stock",
  "implementation_status": "connected",
  "resolution_mode": "composite_fill",
  "provider_status": "connected",
  "evidence_status": "stale",
  "operation_status": "not_requested",
  "action_ids": ["fill_cross_market_relations_01"],
  "job_ids": [],
  "blocking_reason": null,
  "next_fill": "Select the bounded cross-market refresh action."
}
```

欄位名稱可配合既有 `evidence.capability_status` 與 `execution.refresh_reconciliation`，但不得建立 frontend-only 第二套狀態。

## Fill plan partition invariant

對每次 request 的 selected capabilities 建立集合：

```text
selected
  = already_satisfied
  ∪ actions
  ∪ jobs
  ∪ deferred
  ∪ unfillable
  ∪ not_applicable
```

規則：

- 六組必須 pairwise disjoint。
- union 必須等於 selected；不能有 orphan capability。
- 一個 action 可以 produce 多個 capabilities，但每個 capability 的 resolution 只能指向一個 canonical action owner。
- `cache_only`、`scheduler_cache`、`derived` 不得偽裝成 executable action。
- `provider_not_connected` 必須有 `blocking_reason` 與 `next_fill`。
- `key_required` 必須指出 config key identity，但不得回傳 secret 值。
- continuation 最多選 8 個 action；Backend runtime、OpenAPI schema、repo MCP snapshot、獨立 OMI_search schema一致。
- plan/action 簽章與 target/capability 重新驗證保留，不能接受 caller 自造 operation name。

## Background job 與續接

### Backend

- 保留既有 `ai.tool_refresh` job 與 dedupe。
- 新增 read-only、redacted AI operational endpoint，只允許讀取 `job_type=ai.tool_refresh`；不得藉 job id 讀取其他內部工作或 secret request payload。
- public job shape 至少包含：`job_id`、`status`、`operation`、normalized target、created/started/finished time、progress、retryable、deduplicated、error code、produced capabilities、evidence_rebuild_required。
- job 成功只代表 operation 完成；仍需重建 evidence 後判斷 current/partial/missing。

### MCP

- repo MCP 與獨立 `OMI_search` 增加 `omi.read_refresh_status` read-only tool。
- tool 只轉呼叫 backend redacted endpoint，不直接讀 DB、不重做 job state mapping。
- 回傳完成狀態時附 `resume` request template，讓 caller 以原 `omi.ask` target/selection 重建 evidence；不自動啟用 LLM 或 write。
- 獨立 `OMI_search` 保留 `allow_llm=false`、`allow_write=false`；`refresh_if_missing` 只有 literal `true` 才轉成 caller intent，最終仍由 backend trust gate 決定。

## Existing operation closure

### 正式公開映射

- `cross_market.refresh_context` -> `cross_market.overnight`、`cross_market.relations`、`cross_market.parity`、`market.cross_market`，依 scope限制 produced set。
- `us.refresh_company_profile` -> `company.profile` (`us_stock`)。
- `us.refresh_corporate_actions` -> `corporate.actions` (`us_stock`)。
- `tw.refresh_watchlist_evidence` -> TW watchlist ranking/radar 所需 cache resources，作為 bounded composite action；coverage仍為 derived。
- `tw.refresh_stock_evidence` 保留 composite convenience；public fill plan預設先列 granular actions，只有多 capability selection 才可列 composite，避免重複 provider calls。
- `us.read_sec_fundamentals` 與 `us.refresh_sec_facts` 選一個 canonical owner；另一個成為 internal alias/deprecated，不得同時產生 action。

### 接 existing service，但不是強迫即時 refresh

- TW futures derivatives：沿用 bounded refresh service與 scheduler；v4 以 composite action或 `scheduler_cache` deferred呈現。
- Resource：若現有 backend reader可在 trust/budget內 bounded refresh，登記 reader/composite action；否則明確維持 best-effort cache。
- FRED：有 key時可登記 bounded refresh；無 key時回 `key_required`，不回 generic missing。
- Market/screening/hot groups：維持 scheduler-owned cache，公開 last job/coverage/next eligible time，不在 ask read path掃全市場。
- Index/crypto market aggregate：只有現有 bounded service時才列 action；否則以 cache/derived resolution 完成契約。

## Capability status v1

`target.type=capability_status` 提供兩個 view：

1. `registry`
   - 57 項正式 capabilities，支援 market/scope/capability/status filter。
   - 回傳各 scope 的 resolution、operation、bounds、trust、dependency、deprecated/replacement。

2. `providers`
   - 保留目前 15 項 curated provider contracts。
   - connected、private、key-required、derived、provider-not-connected 與 next_fill。

`source_health` 仍負責當下 runtime/provider incident；不得因 registry 說 connected 就宣告目前資料 current。

## Consumer 與版本策略

| consumer | 必要變更 | 不得做的事 |
|---|---|---|
| Backend HTTP | additive schema、registry、fill partition、redacted job endpoint | 不接受 caller 自造 tool，不在 GET 啟動昂貴 side effect |
| Repo MCP | schema/snapshot同步、`omi.read_refresh_status`、env alias修正 | 不複製 provider/freshness 邏輯 |
| 獨立 OMI_search | 七個 public read tools、snapshot同步、refresh/job結果完整投影 | 不直接讀 DB、不開 LLM/write、不自行判讀市場狀態 |
| Frontend OMI dock | 能顯示 action/job/deferred/unfillable/provider gap | 不自行決定何時外抓或把 blocked隱藏 |
| Kuro | 使用 canonical human answer + structured status，必要時查 job | 不重做 technical decision或 provider fallback |

契約仍是 `omi.decision.v4`；registry 可由 `omi.capability.registry.v3` additive 升到 v4。若移除或更名欄位，另做 migration，不在本版 silent breaking change。

## 已知同步修正

- repo MCP README 使用 `OMI_MCP_SCHEMA_TIMEOUT_SECONDS`，實作讀 `OMI_SCHEMA_TIMEOUT_SECONDS`；v1 讓 canonical 名稱一致，舊名稱保留一版 alias。
- `continuation.selected_action_ids` runtime 限制最多 8 個，但 Backend 與 repo MCP public schema 缺 `maxItems: 8`；三個 consumer schema全部補齊。
- `docs/ExternalInterfaces.md` 的獨立 OMI_search tool/version 描述已落後 live six-tool surface；實作完成後以 current source + live protocol重寫。
- `/health` transport version與 MCP core version語意不同；欄位改名為 `transport_version`、`server_version` 或在 README明確定義，避免被誤判為 deployment drift。

## 安全與資源邊界

- 預設 `allow_external_fetch=false`；caller 明確要求且 backend policy允許才執行。
- `tool_budget.max_external_fetches <= 8`、`max_total_seconds <= 90` 保持硬上限；每個 operation另有更小的預設。
- Background timeout 不表示 worker 可無限制執行；provider client仍需 connection/read timeout、request count與 cancellation checks。
- Job request/output需 redaction；secret、authorization header、API key、private portfolio內容不進 public payload或 log。
- SQLite write由 service transaction owner處理；adapter/reader不直接 commit。
- 外部 provider大量 refresh、付費 quota與 provider onboarding屬 Tier 5，實際執行前另行確認。
