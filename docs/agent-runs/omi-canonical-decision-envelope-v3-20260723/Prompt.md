# OMI Canonical Decision Envelope v3

## Goal

- 將 OMI 的問答與市場決策能力收斂為一個 backend-owned AI 語意出口。
- 讓 OMI Frontend、Kuro、repo MCP、OMI_search 與後續 consumer 使用同一份 canonical response。
- 保留既有資料讀取、圖表、報告、記憶、provider、scheduler 與 runtime 功能。
- 讓付費 LLM／外部 API 成為受 trust policy、budget、timeout 與來源紀錄約束的可選能力。

## Non-goals

- 不把 `/api/market/*`、`/api/system/*`、jobs、health、設定與管理 API 全部塞進 AI gateway。
- 不刪除現有 `omi.ai.ask.v2`，不要求所有舊 consumer 在同一個 deployment 瞬間切換。
- 不把市場判斷、freshness、provider fallback 或 readiness 搬到 Frontend、MCP、OMI_search 或 Kuro。
- 不加入自動下單、券商帳戶操作或自動交易行為。
- 不藉此進行無關 dependency upgrade、DB migration 或大型 UI redesign。

## Hard constraints

- Repo：`C:\project\Open Market Intelligence`
- Backend 是 scope resolution、evidence、freshness、tool orchestration、decision readiness、answer contract 與 bounded refresh 的唯一 owner。
- Canonical contract 使用 `omi.decision.v3`；`omi.ai.ask.v2` 保留 compatibility。
- HTTP 與 SSE 的 final payload 必須是同一份 contract；SSE `done` 只表達 transport completion，且不可把 business failure 標成成功。
- Reader profile／payload level 只能改變資料量，不得改變 target、readiness、freshness、missing、warnings 或 error 語意。
- Explicit market scope 不得靜默落到其他市場。
- `allow_external_fetch=true` 與 `allow_llm=true` 仍受 server-side trust policy 控制。
- 付費 API 呼叫必須 bounded、可追蹤、可 timeout，且不得因付費來源而隱藏 stale、partial、missing 或 provider failure。
- `allow_write=false` 不得產生 AI report、memory 或其他 user-data write；正常 market cache refresh 依既有 policy 處理。
- 不刪除或重建 `data/open_market_intelligence.db`。
- 保留目前 dirty worktree 中的使用者與其他流程變更。

## Context

- Repo：`C:\project\Open Market Intelligence`
- Related systems：
  - Backend HTTP：`POST /api/ai/ask`、`POST /api/ai/ask/stream`
  - Repo MCP：`agents/omi_mcp_server/server.py`
  - Frontend：`frontend/src/components/OmiAskDock.tsx`
  - Standalone adapter：`C:\GPT_MCPtool\OMI_search`
  - Kuro：`C:\project\kuro\Open-LLM-VTuber`
- Current known state：
  - Backend 已有 v2 response、Human Answer、Decision Contract、Evidence Passport、slots、freshness 與 bounded tool policy。
  - 不同層各自推導 readiness／slot／error，造成 consumer 語意分歧。
  - `target.type=market, market=JP|KR` 可保留外顯市場，但執行台股 market reader。
  - SSE `final.ok=false` 後仍可能送出 `done.ok=true`。
  - Frontend 與 adapter 尚未以同一 canonical contract 為唯一 truth source。

## Deliverables

- `Architecture.md`：資料面、決策面、transport、trust boundary、canonical schema、readiness 與 migration 設計。
- Backend `omi.decision.v3` schema 與 v2-to-v3 compatibility projection。
- Canonical readiness evaluator 與 freshness vocabulary。
- Canonical slot projection，讓 freshness／usability 不再和 slot status 衝突。
- HTTP 與 SSE contract alignment。
- Frontend OMI Ask Dock 改為 request/consume v3。
- Repo MCP 改為 request/forward v3，adapter 不重建市場語意。
- 明確的 regional market default target，禁止 JP/KR/US 靜默落到 TW。
- Regression tests、safe validation 與 representative live probes。
- 外部 Kuro／OMI_search consumer 的切換或明確的剩餘交付紀錄。

## Done criteria

- `contract_version=omi.decision.v3` 的正常、clarification、target error 都回傳同一 envelope shape。
- v2 request 維持既有 response shape 與核心功能。
- v3 的 `status.readiness.decision_ready` 不得在 Evidence Passport blocked、required domain blocked/missing、request rejected 或 data-only mode 下為 true。
- v3 slot 必須反映對應 domain freshness；stale 不得呈現為 ready/usable。
- `market=JP|KR|US` 的 aggregate context 不得執行 Taiwan market reader。
- SSE `done.ok` 與 final business result 一致，並另有 `transport_ok`。
- Frontend、repo MCP 只從 v3 的 `answer`、`decision`、`evidence`、`status` 與 `continuation` 讀取 OMI 語意。
- External fetch／LLM budget、timeout、provider failure 與 source refs 在 v3 `execution`／`evidence` 可見。
- Targeted backend tests、MCP tests、Frontend lint/typecheck 與 bounded live smoke 通過。
- 未能修改或 live 啟動的外部 consumer 必須在 `Progress.md` 明確記錄，不能宣稱已完成。

## Open questions / assumptions

- Assumption：第一個 deploy 採雙版本策略；v3 是新 canonical contract，v2 是 compatibility projection。
- Assumption：`summary|compact|standard|full` 沿用現有 payload level，由 backend 產生，adapter 不再自行裁剪成另一套語意。
- Assumption：US aggregate 使用既有 S&P 500 index context、JP aggregate 使用 Nikkei 225、KR aggregate 使用 KOSPI；watchlist selection 優先使用 regional watchlist target。
- Assumption：付費 API 已獲使用者授權，但只有在 runtime 已有安全 credential 與 server trust policy 允許時才執行。
