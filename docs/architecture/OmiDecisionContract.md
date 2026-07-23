# OMI 統一決策出口

狀態：已實作 `omi.decision.v3`，`omi.ai.ask.v2` 暫時保留為明確相容版本。

## 目標

OMI 的市場資料、freshness、tool orchestration、AI reasoning、答案語意與決策
readiness 都由 backend 擁有。Frontend、桌寵、Kuro、MCP、ChatGPT 或其他 consumer
只需要送出問題並讀取同一個 `omi.decision.v3` envelope，不得在 consumer 端重建
市場判斷。

統一的是「AI 決策語意出口」，不是把所有市場與維運 API 塞進同一條 route：

| 平面 | 對外入口 | 用途 |
| --- | --- | --- |
| Decision plane | `POST /api/ai/ask`、`POST /api/ai/ask/stream`、MCP `omi.ask` | 問答、情境、決策、限制與 continuation |
| Data plane | `/api/market/*` 與各市場 service | 圖表、表格、資料探索及 backend AI tools |
| Operations plane | `/api/system/*`、jobs、scheduler、settings | runtime、provider、health 與維運 |

## 單一路徑

```text
Consumer request
  -> target/scope resolution
  -> query plan
  -> bounded readers and optional refresh
  -> evidence passport and domain freshness
  -> deterministic answer or trusted LLM analysis
  -> canonical readiness evaluator
  -> OMI Decision Envelope v3
  -> HTTP final / SSE final / MCP result
```

HTTP、SSE `final` 與 MCP result 必須是相同 envelope。Reader profile 或
`payload_level` 只能調整資料量，不得改變 `ok`、target、readiness、freshness、
limitations、error 等核心語意。

## Request

```json
{
  "contract_version": "omi.decision.v3",
  "question": "2330 可以怎麼規劃進場？",
  "target": {
    "type": "tw_stock",
    "id": "2330",
    "market": "TW"
  },
  "mode": "brief",
  "caller_profile": "frontend_readonly",
  "allow_llm": false,
  "allow_write": false,
  "allow_external_fetch": false,
  "tool_budget": {
    "max_calls": 4,
    "max_external_fetches": 2,
    "max_total_seconds": 25
  },
  "refresh_policy": {
    "mode": "stale_first",
    "before_answer": true,
    "fallback_to_cached": true
  },
  "market_data_params": {
    "payload_level": "compact"
  }
}
```

`caller_profile` 只用於識別與記錄，不構成信任。`allow_llm`、
`allow_external_fetch`、`allow_write` 是 caller intent，最終權限仍由
server-side trust policy 決定。

## Canonical response

```json
{
  "kind": "omi_decision",
  "contract_version": "omi.decision.v3",
  "ok": true,
  "request_status": "completed",
  "question": "2330 可以怎麼規劃進場？",
  "target": {},
  "mode": {},
  "action": "omi.generate_stock_brief",
  "caller_profile": "frontend_readonly",
  "status": {
    "ok": true,
    "request_status": "completed",
    "readiness": {
      "facts_ready": true,
      "analysis_ready": true,
      "answer_ready": true,
      "decision_ready": true,
      "decision_required": true,
      "evidence_status": "ready",
      "trust_level": "high",
      "blocked_sections": [],
      "available_sections": []
    },
    "fallback_used": false,
    "cached_data_returned": false
  },
  "answer": {
    "headline": "",
    "text": "",
    "detail": "",
    "summary": [],
    "stance": "",
    "confidence": "",
    "source": "",
    "style": ""
  },
  "decision": {
    "intent": "",
    "action_plan": [],
    "scenarios": [],
    "counter_evidence": [],
    "risks": [],
    "data_limits": [],
    "price_levels": {},
    "position": {},
    "blocked_sections": []
  },
  "evidence": {
    "passport": {},
    "freshness": {},
    "freshness_by_domain": {},
    "slots": {},
    "result": {},
    "source_refs": []
  },
  "limitations": {
    "missing": [],
    "warnings": [],
    "provider_failures": []
  },
  "execution": {
    "strategy_profile": "",
    "policy": {},
    "query_plan": {},
    "tool_plan": {},
    "tool_runs": [],
    "reasoning_steps": [],
    "diagnostics": {},
    "report_level": "",
    "job": {},
    "cancellation": {}
  },
  "continuation": {
    "resolution": {},
    "next_context": {},
    "clarification": {},
    "next_actions": []
  },
  "error": {},
  "compatibility": {
    "source_contract_version": "omi.ai.ask.v2"
  }
}
```

### 欄位責任

- `status`：request 與 readiness 的唯一判定位置。
- `answer`：可直接顯示或語音化的內容。
- `decision`：情境、行動條件、風險、反證、價位與部位結構。
- `evidence`：來源、slot、freshness 與原始 bounded result。
- `limitations`：missing、warning 與 provider failure，不得靜默隱藏。
- `execution`：tool、policy、budget、diagnostics、job 與 cancellation。
- `continuation`：resolved target、追問 context、clarification 與 next action。
- `error`：business error；consumer 不得只看 HTTP status 或 SSE 是否結束。

## Readiness

`facts_ready`、`analysis_ready`、`answer_ready` 與 `decision_ready` 是四個不同概念：

- `facts_ready`：至少有可交付的 evidence，不表示足以做交易決策。
- `analysis_ready`：backend 已完成可讀分析；`data_only` 不成立。
- `answer_ready`：本次 mode 所需的答案已完成。
- `decision_ready`：decision intent、request status、evidence passport、required
  domains 與 trust 都通過。

`decision_ready=true` 必須同時符合：

1. `ok=true` 且 `request_status=completed`。
2. response mode 不是 `data_only`。
3. 問題 intent 確實需要決策。
4. backend decision composer 已產出可執行結構。
5. Evidence Passport trust 是 `high` 或 `medium`。
6. required domains 的 `decision_readiness.status=ready`。

只要 required domain 是 `stale`、`missing`、`blocked`、`failed`、`timeout`、
`provider_failure` 或 `unknown`，不得標示 decision-ready。`partial`、`cached`、
`delayed` 可供事實摘要，但也不得升級成可執行決策。

交易日收盤資料使用 session-aware 語意；`daily_close`、
`latest_completed_session`、`latest_session_close` 都是有效 ready 狀態，
不應誤判成未知。

## Market-level target

畫面沒有個股標的時，regional context 不得退回台股 reader：

| Market | Canonical target |
| --- | --- |
| TW | `market` |
| US | `us_stock:^GSPC` |
| JP | `jp_index:^N225` |
| KR | `kr_index:KOSPI` |
| CRYPTO | `crypto_market` |

如果畫面已有市場 watchlist，優先使用該 watchlist target。無法支援的市場
必須回 clarification 或 structured business error，不得猜測。

## Paid API、refresh 與寫入

允許付費 API 不等於無條件呼叫：

- `analysis` / `report` 需要 `allow_llm=true` 與 server-side trust。
- 外部 market provider 需要 `allow_external_fetch=true` 與 bounded tool budget。
- report/memory/user data write 需要 `allow_write=true` 與 write trust。
- 預設 budget 為 `max_calls=5`、`max_external_fetches=3`、
  `max_total_seconds=25`，且仍受 server 上限裁切。
- provider/LLM 的 timeout、rate limit、credential failure 與 fallback 必須出現在
  `tool_runs`、`provider_failures`、`warnings` 或 `error`。
- cached fallback 可以回答，但不得宣稱是 live/current。

Frontend 目前維持 deterministic brief；只有具明確產品操作與 server trust 的
consumer 才應開啟付費 LLM。

## Transport semantics

### HTTP

成功解析 request 只表示 transport 成功。Business outcome 必須讀 body：

- `ok`
- `request_status`
- `status.readiness`
- `error`

### SSE

`final` 是完整 `omi.decision.v3`。`done` 不取代 `final`：

```json
{
  "ok": false,
  "transport_ok": true,
  "request_status": "rejected"
}
```

Worker、serialization 或 transport failure：

```json
{
  "ok": false,
  "transport_ok": false,
  "request_status": "transport_error"
}
```

### MCP

`omi.ask` 與 `omi.ask_stream` 只 forward backend request/response。MCP 不重做
readiness、freshness、answer 或 market logic。`include_raw=false` 對 v3 不會
建立第二種 summary contract；v2 的舊 projection 暫時保留。

## Compatibility

- 新 consumer 必須明確請求 `omi.decision.v3`。
- `omi.ai.ask.v2` 仍可明確指定，確保既有功能與 caller 可逐步遷移。
- v3 現階段由既有 v2 pipeline 經 backend canonicalizer 投影；consumer 不得依賴
  `compatibility.source_contract_version` 做業務判斷。
- v2 的移除必須等 frontend、repo MCP、Kuro／桌寵與外部 OMI adapter 都完成
  contract tests，且經過一個明確 deprecation window。

## 程式所有權

| 責任 | 位置 |
| --- | --- |
| Canonical envelope 與 readiness | `backend/app/ai/decision_envelope.py` |
| Request validation / policy | `backend/app/ai/ask_policy.py` |
| Scope resolution | `backend/app/ai/scope_resolution.py` |
| HTTP routes | `backend/app/routers/ai.py` |
| SSE transport | `backend/app/ai/streaming.py` |
| OMI Dock consumer | `frontend/src/components/OmiAskDock.tsx` |
| Dock target mapping | `frontend/src/components/market-dashboard/omi/buildOmiAskContext.ts` |
| Repo MCP adapter | `agents/omi_mcp_server/server.py` |

## 驗證要求

- Pure contract：ready、stale、blocked、clarification、business error、data-only。
- Markets：TW、US、JP、KR、crypto target routing。
- HTTP：v3 canonical shape 與明確 v2 compatibility。
- SSE：`final` parity 以及 business／transport `done` 語意。
- MCP：initialize、tools/list、valid call、business error。
- Frontend：typecheck、lint、build 與 Dock 實際問答。
- Runtime：實際 selected PID/port、`/api/ai/tools`、deterministic call，以及在
  trusted config 存在時的一次 bounded paid-LLM smoke。
