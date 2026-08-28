# OMI MCP Server

> 本文件說明 adapter 啟動與 transport 行為。Public schema、capability inventory
> 與 readiness 以 OMI backend runtime 及
> [`docs/architecture/OmiDecisionContract.md`](../../docs/architecture/OmiDecisionContract.md)
> 為準；本文列出的 tools 不應被視為永久完整 inventory。

OMI 的 stdio MCP thin adapter：

```text
MCP client -> agents/omi_mcp_server/server.py -> OMI backend /api/ai/*
```

Adapter 不讀 OMI DB、不直接呼叫 market provider，也不重做 target、freshness、
decision readiness 或 answer。預設公開：

- `omi.ask`
- `omi.ask_stream`
- `omi.read_refresh_status`

可選公開：

- backend internal tools（只限明確 trusted debug 情境）

## 啟動

先啟動 OMI backend，再執行：

```powershell
python agents/omi_mcp_server/server.py
```

設定：

```powershell
$env:OMI_API_BASE_URL = "http://127.0.0.1:8400"
$env:OMI_API_TIMEOUT_SECONDS = "180"
$env:OMI_MCP_SCHEMA_TIMEOUT_SECONDS = "2"
$env:OMI_MCP_EXPOSE_INTERNAL_TOOLS = "false"
$env:OMI_MCP_AI_TRUST_TOKEN = ""
$env:OMI_MCP_TRUSTED_DEFAULT_EXTERNAL_FETCH = "true"
```

實際 backend port 以 launcher 的 `selected=` 紀錄為準；`8400` 是預設偏好值，
不是永久保證。

## Public contract

`omi.ask` 只接受公開契約 `omi.decision.v4`。v4 讓模型選擇 capability、
field、limit、output 與 realtime policy：

```json
{
  "question": "NVDA 的即時報價與趨勢",
  "target": {"type": "us_stock", "id": "NVDA", "market": "US"},
  "contract_version": "omi.decision.v4",
  "output": "decision_with_evidence",
  "realtime_policy": "require_live",
  "selection": {
    "include": ["quote.snapshot", "technical.structure"],
    "fields": {
      "quote.snapshot": [
        "price",
        "change_pct",
        "quote_time",
        "fetched_at",
        "provider"
      ]
    },
    "max_response_bytes": 65536
  },
  "allow_external_fetch": true
}
```

完整 schema 與 capability catalog 由 backend `/api/ai/tools` 擁有。MCP
`tools/list` 會讀取這份 schema，確保 HTTP 與 MCP 不維護兩套欄位；backend
暫時無法連線時才退回
`agents/omi_mcp_server/public_contract_snapshot.json`。這份 fallback 是由
backend registry 產生的 artifact，不是 adapter 手工維護的第二份市場契約；
adapter 只添加 transport-local `include_raw`。

Registry、target、capability 或 `selection.parameters` schema 有變更時，從 repo
root 重新產生 snapshot：

```powershell
.\.venv\Scripts\python.exe .\scripts\generate-ai-public-contract-snapshot.py
```

需要同步 standalone `OMI_search` 時，可在同一次產生兩份完全相同 digest 的
snapshot：

```powershell
.\.venv\Scripts\python.exe .\scripts\generate-ai-public-contract-snapshot.py `
  --output .\agents\omi_mcp_server\public_contract_snapshot.json `
  --output C:\GPT_MCPtool\OMI_search\public_contract_snapshot.json
```

正常連線時仍以 backend `/api/ai/tools` 為即時權威；snapshot 只負責離線
`tools/list` 相容，不能讓 adapter 自行判斷 market semantics 或 freshness。

Consumer 應直接讀：

- `status` 與 `status.readiness`
- `answer`
- `decision`
- `evidence.manifest`、`evidence.realtime`、`evidence.data`
- `limitations`
- `execution.selection`、`execution.tool_runs`
- `execution.refresh_reconciliation`
- `continuation.fill_plan` 與其完整六組 `partition`
- `error`

`omi.decision.v4` 不含 legacy `evidence.result` 大包。資料量由
`selection.fields`、`selection.limits` 與 `selection.max_response_bytes`
限制。舊 `market_data_params`、`payload_level`、`requested_domains` 與
`excluded_domains` 仍在相容期間保留。

## 缺資料續補

Missing/stale capability 會出現在 `continuation.fill_plan.actions`。每個 action
只對應一個 capability 與 target，並包含 `action_id`、operation、fields、
limit、timeout、cache write 與 external-fetch metadata。

若模型決定補其中一項，使用 action 內的 `invoke.arguments` 再呼叫 `omi.ask`；
backend 會重新驗證 `plan_id` 與 `selected_action_ids`。Consumer 不得直接呼叫
內部 refresh function，也不得自行把單一缺口擴成全市場 refresh。

`allow_external_fetch=true` 表示允許主規劃器在 budget 內嘗試 bounded refresh，
不保證所有 fill action 都在同一次請求自動執行。Consumer 應讀
`execution.refresh_reconciliation` 判斷實際 attempt、tool outcome、最終 payload
是否可用，以及仍保留哪些 fill action。

若 capability 尚在正常發布窗口或 no-new-data cooldown，backend 會把它放在
`continuation.fill_plan.deferred_actions`，並揭露 `release_status` /
`next_eligible_refresh_at`；adapter 不自行覆寫或提前執行。`source_health`
查詢可在 `market_data_params` 使用 `problems_only`、`status_filter`、
`include_healthy`、`market`、`resource`、`target` 與 `provider`。

`continuation.fill_plan.partition` 會將每個 selected capability 恰好放入
`already_satisfied`、`actions`、`jobs`、`deferred`、`unfillable` 或
`not_applicable` 一組。Consumer 應以這個 backend-owned partition 判讀續補狀態，
不能從 UI label 或 action 數量推斷。

## Background refresh status

當 `omi.ask` 回傳 background refresh job 時，使用 job reference 的
`status_url`，或呼叫：

```json
{
  "name": "omi.read_refresh_status",
  "arguments": {"job_id": 123}
}
```

這個 tool 只轉送 `GET /api/ai/refresh-status/{job_id}`，且只能讀
`ai.tool_refresh` 的 redacted 狀態。`operation_status=completed` 只表示工作已結束；
`evidence_status=rebuild_required` 或 `partial_rebuild_required` 時，consumer 必須使用
回傳的 cache-only `resume` 重新呼叫 `omi.ask`，不得直接宣稱資料已 current/fresh。
未知 job、其他 job type 與不允許公開的 job 使用相同 predictable 404，adapter 不會
退回 generic `/api/jobs/{id}` payload。

## Realtime

`realtime_policy` 支援：

- `cache_only`
- `prefer_live`
- `require_live`

OMI 會區分 `live`、`delayed`、`stale`、`latest_completed_session`、
`final_snapshot` 與 `unavailable`。`current` 標籤不等於 live；event time、
received/fetched time、timezone、provider、session 與 age 必須一起成立。
休市最新完成 session 可供分析，但不冒充即時。

## Trust、外部 API 與 OpenAI

`caller_profile` 只是一個 label。下列 caller intent 最終都要通過 backend
server-side trust：

- `allow_external_fetch`
- `allow_llm`
- `allow_write`

外部 refresh 受 allowlisted tool、target、provider policy、call count、timeout
與 response limit 約束。OpenAI analysis/report 需要 backend process 設定
`OPENAI_API_KEY`、`OPENAI_LLM_API_KEY` 或 `OMI_OPENAI_ENV_FILE`；MCP server
不讀、不保存也不轉送 API key。Report/memory persistence 另需 write trust。

若 backend 關閉 loopback trust，請在 backend 設定 `OMI_AI_TRUST_TOKEN`，並以
`OMI_MCP_AI_TRUST_TOKEN` 傳給 adapter。一般外部 caller 應只使用 `omi.ask`。

## MCP error semantics

Structured business rejection（例如不存在的代碼、缺資料、trust 拒絕）是成功
傳輸的 canonical result，因此 `isError=false`。只有 MCP protocol、HTTP
transport、serialization 或 adapter internal failure 使用 `isError=true`。

`include_raw` 是已棄用但仍接受的 caller compatibility flag；v4 下不做 MCP
transport projection。請以 backend `selection.fields`、`selection.limits` 與
`selection.max_response_bytes` 控制 payload，確保 HTTP、SSE 與 MCP 讀到同一份
canonical envelope。

## Internal tools

只有設定 `OMI_MCP_EXPOSE_INTERNAL_TOOLS=true` 才公開 direct internal tools。
這是 trusted local debug 能力，不是一般 consumer contract。Internal memory
tools只處理 AI research memory；不得修改 market、watchlist 或 source data。
