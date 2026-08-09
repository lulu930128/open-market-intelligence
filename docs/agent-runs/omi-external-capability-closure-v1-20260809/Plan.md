# 施工計畫

> 狀態：Milestone 0-7 已於 2026-08-10 完成並通過 source、snapshot、完整 backend regression 與 live runtime 驗收；Milestone 8 是需另行選定授權／quota 的 provider expansion，不屬於本次 `contract_complete=true` 的未完成項。完整證據見 [Progress.md](Progress.md)。

## Milestone 0：鎖定基線與避免覆蓋現有工作

- 範圍：確認 branch、dirty files、產品文件、Backend/MCP/OMI_search source 與 live runtime identity。
- 變更：只建立本任務文件；後續實作開始前重新抓取 source/live digest。
- 驗收：記錄 22 targets、57 capabilities、26 allowed tools、20 public fills、15 provider contracts；現有使用者變更未被覆蓋。
- 驗證：

```powershell
git status --short --branch
cd backend
..\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q tests\test_omi_mcp_server.py tests\test_mcp_schema_contract.py tests\test_ai_tool_boundaries.py tests\test_ai_capability_contract.py
```

## Milestone 1：建立單一 capability resolution registry

- 範圍：`backend/app/ai/capability_contract.py`、`agentic_policy.py`、`agentic_planning.py`、必要的 pure registry module。
- 施工：
  - 以 `(scope_type, capability_id)` 建立 resolution specs。
  - 納入 implementation、resolution mode、operation、produces、dependencies、provider、freshness owner、side effect、trust、bounds、session、background與 blocking metadata。
  - 先讓既有常數從 registry衍生；若 diff風險過高，保留常數但加 parity assertions。
- 驗收：
  - 57 項 capabilities在每個適用 scope都有唯一 resolution。
  - 兩個 deprecated capability有 replacement。
  - 無 operation 的項目必須是 cache/scheduler/derived/private/blocked/not-applicable之一。
- 驗證：新增 pure registry coverage/parity tests；執行 `test_ai_capability_contract.py`、`test_ai_tool_boundaries.py`。

## Milestone 2：收斂現有 operations 與 scope-specific refreshability

- 範圍：`agentic_planning.py`、`agentic_execution.py`、`ask_tool_stage.py`、`agentic_tools.py`、相關 market service adapters。
- 施工：
  - 將 cross-market、US profile/actions、TW watchlist等內部工具正式映射或標為 internal-only。
  - 解決 `us.read_sec_fundamentals` 與 `us.refresh_sec_facts` canonical ownership。
  - 對 quote/intraday/daily/crypto capability採 scope-specific resolution，不再用 capability id 全域判定。
  - TW futures、resource、FRED只接既有 bounded service；沒有安全 service則回 scheduler/cache/key-required，不臨時新增無界抓取。
- 驗收：
  - 26 allowed tools與 public/internal classification完全可查。
  - 每個 executable operation都能證明 produced capabilities；不重複呼叫同 provider resource。
  - Ask tool stage能處理需要 action的 target，非 action target維持 truthful deferred/unfillable。
- 驗證：新增各市場 targeted planner/execution tests；以 fake provider驗證 request/time/row/date bounds與 partial failure。

## Milestone 3：完成 fill plan partition 與 reconciliation

- 範圍：`capability_contract.py` 的 fill plan、selected fill validation、`ask_response_stage.py`／`decision_envelope_v4.py` 的 additive projection。
- 施工：
  - 實作 selected set的六組 partition invariant。
  - 每個 action保留 signed plan/action id與 backend revalidation。
  - 對 composite action建立 canonical ownership與 produced capability reconciliation。
  - 把 provider blocked、key required、scheduler next eligible、cache-only、derived dependencies投影給 consumer。
- 驗收：
  - 無 orphan、重複分類、無理由 unfillable。
  - operation success後仍以 evidence freshness決定 ready/partial/missing。
  - `continuation.selected_action_ids` 在 runtime與全部 schema均為最多 8。
- 驗證：property/table-driven tests覆蓋 57 capabilities、invalid/tampered plan、scope mismatch、duplicate action、partial provider與not-applicable。

## Milestone 4：加入 background refresh status 閉環

- 範圍：`backend/app/routers/ai.py` 或獨立 AI operational router、`agentic_execution.py`、jobs service、schemas/tests。
- 施工：
  - 對 `ai.tool_refresh` 建立 redacted read endpoint。
  - 只允許對外讀 AI refresh job，不洩漏其他 job/request/private payload。
  - 回傳 operation與evidence分離的 status、produced capabilities與resume template。
  - 完成、失敗、partial、timeout、deduplicated、untracked都可預測。
- 驗收：
  - request deadline後的 worker可被查詢；完成後caller可重建 evidence。
  - job id越權、非 AI job、未知 job回 predictable error。
  - frontend現有 `/api/jobs` 行為不被破壞。
- 驗證：job service/router tests、detached worker tests、dedupe/race tests、redaction tests。

## Milestone 5：擴充 capability status 與 public schema

- 範圍：`market_context/capability_context.py`、`tool_catalog.py`、public schema、generated snapshot script。
- 施工：
  - `capability_status` 增加 `registry` 與 `providers` views。
  - 支援 capability/scope/market/status filter與bounded result。
  - `/api/ai/tools` 公開 resolution taxonomy、limits、registry/version digest。
  - 修正 selected action `maxItems: 8`。
- 驗收：
  - full registry view為57項正式 capability；provider view保留15項。
  - connected implementation不被描述成current evidence。
  - generated snapshot可重現且digest穩定。
- 驗證：capability status contract、filter/bounds、schema digest與snapshot generation tests。

## Milestone 6：同步 repo MCP、獨立 OMI_search 與 consumer

- 範圍：
  - 主 repo：`agents/omi_mcp_server/server.py`、README、snapshot、MCP tests。
  - 獨立 adapter：`C:\GPT_MCPtool\OMI_search` 的 server、README、snapshot、tests。
  - 視 schema變更需要：Frontend OMI dock/Kuro types與status rendering。
- 施工：
  - 新增 `omi.read_refresh_status` read-only operational tool。
  - repo MCP保持 `omi.ask`、`omi.ask_stream`；獨立 OMI_search由六個read tools增為七個。
  - 修正 schema timeout env名稱並保留舊 alias一版。
  - 同步 selected action limits、registry/job schema與fallback snapshot。
  - Consumer只呈現backend status，不重做市場邏輯。
- 驗收：
  - repo/live/standalone snapshots同 digest。
  - MCP `initialize` -> `notifications/initialized` -> `tools/list` ->代表性 `tools/call` 成功。
  - Business error仍為 protocol success；blocked/private/job status語意不被adapter改寫。
- 驗證：repo MCP tests、獨立 adapter tests、raw HTTP MCP smoke與必要的Frontend typecheck。

## Milestone 7：更新外部介面文件與 runtime adoption

- 範圍：`docs/ExternalInterfaces.md`、兩份 MCP README、launcher contract probe、live backend與OMI_search runtime。
- 施工：
  - 以 current source重寫 target/capability/provider/job/tool列表。
  - 分開 transport/server/contract/registry/snapshot版本。
  - 正式 launcher/restart後驗證 PID、executable path、listener、health、ready、tool digest與代表性 outward behavior。
- 驗收：
  - 文件與 live tools/list一致。
  - Backend與OMI_search各自的process ownership、port、build identity可證明。
  - 不以HTTP 200、cache hit或PID變動單獨宣告 deployed complete。
- 驗證：launcher log、health/ready、`/api/ai/tools`、HTTP ask、MCP smoke、snapshot hash。

## Milestone 8：Provider expansion gates

這一階段不與 contract closure混在同一個未授權變更；每個 provider是獨立 capability task：

1. News/events：先決定license、attribution、dedupe、entity mapping、retention與quota。
2. US options/earnings：拆成options chain/flow與earnings calendar兩個provider contract。
3. TDnet：issuer mapping、document identity、attachment storage、language與event polling。
4. OpenDART：key handling、corp-code mapping、report identity、normalization與bounded backfill。
5. HK：symbol master、calendar、daily、intraday、freshness、source health，再接watchlist/UI。

每個 gate 都需使用 `omi-add-market-capability` 工作流、獨立 migration/provider tests與 bounded live smoke；未獲確認前維持 `provider_not_connected`。

## 驗證矩陣

### Targeted source tests

```powershell
cd "C:\project\Open Market Intelligence\backend"
& '..\.venv\Scripts\python.exe' -m pytest -p no:cacheprovider -q `
  tests\test_ai_capability_contract.py `
  tests\test_ai_tool_boundaries.py `
  tests\test_ai_outward_contract.py `
  tests\test_mcp_schema_contract.py `
  tests\test_omi_mcp_server.py `
  tests\test_ai_supplemental_contexts.py
```

### Safe backend regression

```powershell
cd "C:\project\Open Market Intelligence"
.\scripts\run-safe-validation.ps1 -Profile backend
```

### Contract snapshot

```powershell
cd "C:\project\Open Market Intelligence"
.\.venv\Scripts\python.exe .\scripts\generate-ai-public-contract-snapshot.py `
  --output .\agents\omi_mcp_server\public_contract_snapshot.json `
  --output C:\GPT_MCPtool\OMI_search\public_contract_snapshot.json
```

獨立 adapter 路徑的輸出屬跨 workspace 寫入；實作時需明確權限與該 runtime的測試/重啟流程。

### Frontend（只有實際 type/rendering 受影響才執行）

```powershell
cd "C:\project\Open Market Intelligence\frontend"
npm run lint
npm exec tsc -- --noEmit --incremental false
```

### Live acceptance

- 從 launcher log取得實際 Backend URL，不假設固定 port。
- 驗證 `/api/system/health`、`/readyz`、`/api/ai/tools` 與 registry digest。
- HTTP代表案例：cache-only、TW reader fetch、US/JP/KR/crypto granular fill、cross-market composite、key-required FRED、blocked provider、private portfolio、background job。
- HTTP MCP：`initialize` 後保留 `Mcp-Session-Id`，再做 `tools/list`、`omi.ask`、`omi.read_capability_status`、`omi.read_refresh_status`。
- 不在預設 acceptance啟動全市場 refresh或大量provider quota。

## Stop-and-fix 規則

- 任一 capability在selected partition中遺失或重複，立即停止後續consumer同步。
- 任一 adapter開始自行判斷freshness、market session、provider fallback或fill policy，退回backend owner設計。
- 任一 GET/read route新增未明示的外部side effect、DB write或大量job，停止並改成explicit bounded action。
- 任一 provider回成功但evidence仍stale/partial時，不得把結果提升為ready。
- 發現secret、private portfolio、raw provider credential或未redact job request進入public payload/log，停止並修正後重跑安全測試。
- Snapshot/source/live任何一層版本不一致，不得宣告runtime adoption完成。
- 現有dirty files與本任務衝突時，先理解/協調，不revert使用者變更。

## 決策紀錄

- 2026-08-09：將「完整」定義為所有能力都有可執行或明確不可執行的閉環，而非強迫所有provider顯示ready。
- 2026-08-09：以 `(scope_type, capability_id)` 作registry key，因同名capability跨市場的refreshability不同。
- 2026-08-09：新增read-only job status tool；它是operational surface，不是第二套AI/market logic。
- 2026-08-09：五個provider gap另設gate，避免未確認授權、key與quota就擴張外部side effect。
