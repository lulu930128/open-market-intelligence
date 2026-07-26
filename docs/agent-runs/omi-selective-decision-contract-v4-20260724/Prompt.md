# OMI Selective Decision Contract v4

## Goal

- 將現有 `omi.decision.v3` 演進為可由模型細粒度選擇資料、可回傳 bounded fill actions、具 session-aware realtime 語意的 `omi.decision.v4`。
- 保留單一公開 AI 語意出口：HTTP/SSE `POST /api/ai/ask` 與 MCP `omi.ask`。
- 讓 OMI Frontend、OMI 自身 AI、MCP、Kuro 模型與其他 consumer 使用同一份 backend-owned contract。
- 保留 `omi.ai.ask.v2`、`omi.decision.v3` 與既有 target、market data、報告、provider、scheduler、DB 與 runtime 功能。

## Non-goals

- 不建立 Kuro、桌寵、語音或特定 consumer 專用 response shape。
- 不讓 OMI 產生 Kuro 可朗讀稿；語氣、口語化、斷句、persona 與 TTS 由 Kuro 端模型／呈現層負責。
- 不把 `/api/market/*`、`/api/system/*`、jobs、health、設定與管理 API 塞進 AI gateway。
- 不一次移除 v2/v3，不要求所有外部 consumer 在同一個 deployment 瞬間切換。
- 不在 adapter、Frontend 或 Kuro 重做 freshness、provider fallback、decision readiness 或市場分析。
- 不加入自動下單、券商操作、無邊界全市場 backfill、未受控付費 API 或 AI memory 寫入。

## Hard constraints

- Repo：`C:\project\Open Market Intelligence`
- Backend 是 target resolution、multi-intent、capability registry、query plan、evidence、freshness、tool orchestration、decision semantics、projection 與 bounded refresh 的唯一 owner。
- Public answer contract 只按資料用途與資料量投影，不按 consumer 名稱分支。
- 新功能採 additive、versioned、consumer-safe 方式；v2/v3 compatibility regressions 必須先修正才能繼續 rollout。
- 模型只能選 registry 中的 capability、欄位群組與 bounded limits，不能指定 SQL、內部 function 或任意 provider URL。
- 缺資料補齊必須精準到 capability、target、window 與 provider policy；不得只回傳全資料包刷新。
- `current`、`live`、`snapshot`、`delayed`、`latest_completed_session`、`stale`、`missing` 必須分開。
- 所有 realtime evidence 必須有帶 timezone 的 event time、received time、source/provider、session、age、TTL 與 quote semantics。
- `allow_external_fetch`、`allow_llm`、`allow_write` 與付費能力仍受 server-side trust、budget、timeout、quota 與 telemetry 約束。
- 不刪除、重建或覆蓋 `data/open_market_intelligence.db`。
- 保留使用者與其他流程的既有 worktree 變更；不 reset、不做無關重構或 dependency upgrade。

## Context

- Related systems：
  - Backend AI：`backend/app/ai/`
  - HTTP/SSE：`backend/app/routers/ai.py`
  - Repo MCP：`agents/omi_mcp_server/server.py`
  - Frontend：`frontend/src/components/OmiAskDock.tsx`
  - External OMI adapter：`C:\GPT_MCPtool\OMI_search`
  - Kuro：`C:\project\kuro\Open-LLM-VTuber`
- Current known state：
  - v3 已提供 canonical envelope、readiness、slots、freshness、limitations 與 continuation。
  - `payload_level`、`market_data_params`、`requested_domains`、`excluded_domains` 與多種 bounded limits 已存在。
  - 一般 query plan 尚未把所有 requested domain 映射為 required/optional capability。
  - Taiwan 缺資料目前主要落到單一 `tw.refresh_stock_evidence` 大包刷新；US 工具較細，crypto ask 主要讀本機快取。
  - v3 `evidence.result` 仍保留大部分 legacy result，造成 summary/compact payload 過大。
  - Freshness keyword 目前可把 stock target 改成 `data_freshness`，使「分析個股並回資料日期」只剩 freshness。
  - MCP adapter 把 structured business rejection 標成 MCP execution error。
  - Trend headline 可依 price position 寫成「波段偏多」，但 canonical stance 依 score 為 bearish。
  - Runtime probe 顯示 US intraday 可回 live quote；TW closed-session 與 crypto snapshot 的 current/live/slot 語意仍不一致。

## Deliverables

- 任務文件：`Prompt.md`、`Plan.md`、`Progress.md` 與必要的 architecture/contract 文件。
- Additive `omi.decision.v4` request/response contract 與 v2/v3 compatibility。
- Capability registry、selection normalization、field/limit validation、data manifest 與 bounded output projection。
- Multi-intent routing，讓 target 與 freshness/analysis intent 分離。
- Granular fill actions 與 continuation selection；先支援 TW/US/crypto 代表性能力。
- Session-aware realtime evidence contract 與 validator。
- Backend semantic invariant：stance/headline/timeframe/readiness 一致。
- HTTP/SSE/MCP business-vs-transport error alignment。
- Repo MCP 與 Frontend 使用同一 v4 contract；外部 consumer 的切換與驗證若受寫入邊界限制，必須明確記錄。
- Targeted regressions、safe validation、payload/latency checks 與 representative runtime probes。

## Done criteria

- `omi.decision.v4` 正常、clarification、rejected、partial、timeout 與 cached fallback 使用一致 envelope。
- v2/v3 request 仍保留既有 response shape 與核心功能。
- 模型可選 capability、fields 與 limits；未選取的大型資料不會進入 outward payload。
- 「2330 分析並告訴我各項資料日期」保留 `tw_stock:2330` target，並同時產生 analysis 與 freshness manifest。
- 不存在代碼由 MCP 回傳 structured business rejection，且 `isError=false`；只有 protocol/transport/internal failure 使用 `isError=true`。
- Headline、canonical stance、timeframe stance 與 scenario 不得互相矛盾。
- Missing/stale evidence 只產生對應 capability 的 bounded fill action；不會因單一缺口執行整包 Taiwan refresh。
- TW closed session、US regular/extended session、crypto 24/7 snapshot/live 都有明確 realtime semantics 與 regression。
- Payload budget 有 hard-cap regression；超限時以 bounded omission/reference/continuation 表達，不靜默回完整 result。
- Frontend、repo MCP、Kuro 模型與其他 consumer 沒有 consumer-specific OMI response contract。
- Backend targeted/full safe validation、Frontend lint/typecheck、MCP tests 與 bounded runtime smoke 有可追蹤證據。

## Open questions / assumptions

- Assumption：v4 先由現有 v2 pipeline 與 v3 canonicalizer上的 additive modules產生，待 contract 穩定後才考慮直接建立 v4 domain model。
- Assumption：consumer 可依同一 request schema選擇 `evidence_only`、`decision` 或 `decision_with_evidence`；這是資料用途，不是 consumer profile。
- Assumption：付費 API 已獲使用者原則授權，但每次呼叫仍必須受 runtime trust、明確 cost budget 與 bounded validation 控制。
- Assumption：外部 `OMI_search` 與 Kuro 不在本 repo writable root；先完成 OMI truth source，修改外部 consumer 時依權限與其 repo 規則處理。
