# Architecture: OMI Canonical Decision Envelope v3

## 1. Architecture boundary

OMI 保留三個平面：

1. Decision plane
   - 唯一公開 AI 業務能力：`omi.ask`
   - HTTP：`POST /api/ai/ask`
   - SSE：`POST /api/ai/ask/stream`
   - MCP：`omi.ask`
   - Canonical response：`omi.decision.v3`

2. Data plane
   - `/api/market/*`、market services、provider adapters、local cache。
   - 提供 K 線、報價、圖表、ranking 與 backend AI tools。
   - 不要求所有純資料 UI 經過 AI decision pipeline。

3. Operations plane
   - `/api/system/*`、health、source health、provider events、jobs、scheduler、settings。
   - 預設為 loopback／trusted operations surface，不是 public AI contract。

## 2. Component flow

```text
market services / provider health / local DB
  -> scope resolution
  -> query plan
  -> bounded evidence readers and optional refresh
  -> evidence passport and domain freshness
  -> answer / scenario / risk composition
  -> canonical readiness evaluator
  -> OMI Decision Envelope v3
  -> HTTP final / SSE final / MCP result
  -> Frontend / Kuro / ChatGPT / other consumers
```

Backend owns every arrow before the canonical envelope。Consumer 只能呈現、語音化、保存短期 continuation context 或要求另一個 payload level。

## 3. Contract versioning

### `omi.ai.ask.v2`

- 保留目前 request/response shape。
- 供舊 consumer 與 compatibility tests 使用。
- 修正 correctness bug 時可同步改善，但不移除既有欄位。

### `omi.decision.v3`

- 新 canonical domain contract。
- 正常、clarification、rejected、timeout 與 cached fallback 使用相同外框。
- 不以 `analysis.human_answer`、`analysis.decision_contract`、top-level readiness 與 passport readiness 多套欄位並列讓 consumer 猜測。
- v2 pipeline 先產生現有完整 evidence，再由 backend canonicalizer 產生 v3；待 migration 穩定後可讓 pipeline 直接建立 v3 domain model。

## 4. Canonical response

```json
{
  "kind": "omi_decision",
  "contract_version": "omi.decision.v3",
  "ok": true,
  "request_status": "completed",
  "question": "2330 的進場與失效條件？",
  "target": {
    "type": "tw_stock",
    "id": "2330",
    "market": "TW",
    "label": "台積電"
  },
  "mode": {
    "requested": "brief",
    "effective": "brief",
    "response": "brief",
    "payload_level": "compact",
    "diagnostics_level": "none"
  },
  "action": "omi.generate_stock_brief",
  "caller_profile": "frontend_readonly",
  "status": {
    "ok": true,
    "request_status": "completed",
    "readiness": {
      "facts_ready": true,
      "analysis_ready": true,
      "answer_ready": true,
      "decision_ready": false,
      "evidence_status": "partial",
      "blocked_sections": ["decision"],
      "available_sections": ["evidence", "answer"]
    },
    "fallback_used": false,
    "cached_data_returned": false
  },
  "answer": {
    "headline": "資料不足以形成可執行進場決策",
    "text": "",
    "summary": [],
    "detail": "",
    "stance": "wait",
    "confidence": "low",
    "source": "question_intent",
    "style": "question_aware_summary"
  },
  "decision": {
    "intent": "entry_decision",
    "action_plan": [],
    "scenarios": [],
    "counter_evidence": [],
    "risks": [],
    "data_limits": [],
    "price_levels": {},
    "position": {},
    "blocked_sections": ["decision"]
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
    "policy": {},
    "query_plan": {},
    "tool_plan": {},
    "tool_runs": [],
    "diagnostics": {},
    "report_level": "brief",
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

## 5. Readiness semantics

Canonical readiness 是一次性 evaluation，不由 consumer 推導。

### Facts readiness

- Target 已解析。
- Reader 有可辨識結果。
- 不因 `data_only` 而變 false。
- stale facts 可以存在，因此 `facts_ready=true` 不等於 decision-ready。

### Analysis readiness

- 有 backend-produced answer。
- 不在 clarification／rejected 狀態。
- `mode=data_only` 必須為 false。

### Decision readiness

必須同時成立：

- Request `ok=true` 且 `request_status=completed`。
- Mode 不是 `data_only`。
- 問題 intent 需要 decision，且安全/價格 invariant 通過。
- Evidence Passport trust 不得為 `low|blocked`。
- Required domain readiness 必須為 `ready`。
- Required domain 不得 `missing|stale|blocked|failed|unknown`。

`facts_ready`、`analysis_ready` 與 `decision_ready` 是不同維度，不得互相取代。

### Freshness vocabulary

可直接使用：

- `ready`
- `available`
- `current`
- `fresh`
- `live`
- `daily_close`
- `latest_completed_session`
- `latest_session_close`
- `not_requested`
- `not_applicable`

限制使用：

- `partial`
- `cached`
- `waiting`
- `delayed`
- `stale`

不可作為 executable decision evidence：

- `unknown`
- `missing`
- `unavailable`
- `blocked`
- `failed`
- `provider_failure`
- `timeout`

盤後 `daily_close` 是合法的 session-aware quote semantics，不應自動變成 unknown。

## 6. Slot semantics

Slot status 與 freshness 必須在 backend 合併。

```text
payload missing                  -> missing
provider/policy blocked          -> blocked
payload exists + stale domain    -> partial, usability=limited
payload exists + current domain  -> ready, usability=usable
not requested                    -> not_requested
not applicable                   -> not_applicable
planned but unavailable          -> planned
```

Canonical slot projection不得修改原始 evidence payload，只建立 consumer-facing status。

Default domain mapping：

- `quote` -> `quote`
- `intraday` -> `intraday`
- `technical` -> `technical`
- `chips_flows` -> `chips`
- `fundamentals` -> `fundamentals`
- `cross_market` -> `cross_market`
- `market_breadth` -> `breadth`
- `index_intraday` -> `intraday`
- `data_quality` -> all requested domains + top-level missing/warnings

## 7. Market scope semantics

Explicit/ambient market context 使用 canonical default targets：

- TW -> `market`
- US -> `us_stock:^GSPC`（S&P 500 context）
- JP -> `jp_index:^N225`
- KR -> `kr_index:KOSPI`
- CRYPTO -> `crypto_market`

若有 selected regional watchlist，優先使用 `us_watchlist|jp_watchlist|kr_watchlist`。

不得保留 outward `market=JP`，卻執行 Taiwan reader。Unsupported market 必須 clarification 或 business error。

## 8. Transport contract

### HTTP

- HTTP success 代表 request envelope 可處理。
- Business success 由 body `ok` 與 `request_status` 表達。
- Target not found 可以維持 HTTP 200 + structured business error，或由既有 route policy轉 HTTP error；consumer 必須讀 body。

### SSE

- `final`：完整 `omi.decision.v3`。
- `done`：

```json
{
  "ok": false,
  "transport_ok": true,
  "request_status": "rejected"
}
```

- Worker/transport failure：

```json
{
  "ok": false,
  "transport_ok": false
}
```

### MCP

- `omi.ask` forward v3 request/response。
- 已完成的 tool call 即使 canonical response `ok=false`，仍以
  `structuredContent` 回傳並保持 `isError=false`，讓 caller 能讀取
  `error.code`、`resolution`、`limitations` 與可恢復動作。
- `isError=true` 只用於 tool 無法完成呼叫的 execution／transport failure；
  JSON-RPC protocol failure 則使用 JSON-RPC error object。
- `omi.ask_stream` 暫時保留 compatibility；不得產生另一種 final response。

## 9. Reader profiles

沿用 `payload_level`：

- `summary`：桌寵、語音、通知。
- `compact`：MCP、ChatGPT、一般 brief。
- `standard`：OMI Frontend detail。
- `full`：trusted debug/research。

所有 profile 必須保留：

- `contract_version`
- `ok/request_status`
- target
- readiness
- answer/decision status
- passport/freshness
- missing/warnings/provider failure
- continuation

Profile 只能裁掉大型 evidence rows，或以 `*_ref` 取代，不得裁掉可信度與限制。

## 10. Trust, paid API and write boundaries

- Client fields `allow_llm`、`allow_write`、`allow_external_fetch` 只表示 intent。
- Server-side trust token/local allowlist 決定實際能力。
- 每次外部/付費呼叫必須進入 `tool_plan/tool_runs`，包含 provider、timeout、status、cost/quota metadata（provider 有提供時）與 fallback。
- 預設 budget 沿用：
  - `max_calls=5`
  - `max_external_fetches=3`
  - `max_total_seconds=25`
- Client 可在 server max 內縮小 budget，不可提高 server max。
- `allow_write=false` 阻擋 report/memory/user-data writes。
- Market cache refresh 與 user-data write 必須繼續分離。
- Provider/LLM failure 不得把 cached answer 標成 live/current。

## 11. Compatibility and migration

1. 新增 v3 projection 與 pure tests。
2. 修正 readiness、scope、SSE business semantics。
3. Frontend 與 repo MCP 明確 request v3。
4. 切換 OMI_search 與 Kuro。
5. Live parity tests 同時驗證 v2/v3。
6. 發布 deprecation notice；v2 保留至少一個明確 migration window。
7. 所有 consumer 完成後，才考慮把 request default 從 v2 改為 v3。

## 12. Validation matrix

| Surface | Required validation |
| --- | --- |
| Pure contract | normal / stale / blocked / clarification / rejected / data-only |
| Scope | TW / US / JP / KR / crypto default and explicit target |
| HTTP | v2 compatibility + v3 canonical shape |
| SSE | final parity + done business/transport semantics |
| MCP | initialize / tools/list / valid call / business error |
| Frontend | lint / typecheck / OMI Dock render and follow-up |
| Paid API | trusted bounded call, tool_runs, timeout/failure visibility |
| Runtime | launcher selected PID/port, `/api/ai/tools`, representative business probes |
