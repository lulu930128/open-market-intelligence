# Taiwan Data Surface v1

## 目標

- 以台股為基準，將 OMI 已存在於 specialized HTTP routes、market services、AI readers 與本機資料庫的能力，正規化成可被 Frontend、MCP、ChatGPT、Kuro 與其他 consumer 一致使用的 `omi.decision.v4` capability surface。
- 建立 backend-owned、可產生 schema、可驗證 market applicability、parameters、freshness、quality、coverage 與 compatibility 的 canonical capability registry。
- 先完成可驗證的垂直切片，再逐步加入 screening、quote components、market aggregates 與 events；避免一次性大改與平行第二套 response contract。

## 非目標

- 不新增 `tw_screener`、`tw_calendar` 或 `tw_market` target。公開 universe／calendar 查詢使用 `target.type=market`、`target.market=TW` 與 capability-scoped parameters。
- 不刪除或重命名既有 capability、specialized HTTP route、legacy compact path 或 MCP compatibility alias。
- 不做自動交易、下單、帳戶資金、未授權即時行情、一般新聞 provider、任意 SQL／join 或全市場無邊界 refresh。
- 不重做 US／JP／KR／Crypto contract；只有共用 registry、quality、realtime 或 envelope regression 所需的相容修改。
- 不把所有 frontend-only technical indicators 一次搬到 backend。

## 硬性限制

- Public decision/data contract 維持 `omi.decision.v4`。
- Canonical outward data 只放在 `evidence.data[capability_id]`；freshness、quality、manifest 與 slots 分別由既有 v4 envelope owner 提供。Reader `compact.*` 只能作為內部 projection 或 legacy compatibility source。
- Backend 是 target resolution、market semantics、coverage、freshness、quality、provider fallback、bounded refresh 與 decision logic 的真相來源。
- Specialized routes 與 AI readers 呼叫同一 market service；AI reader 不呼叫 FastAPI route，MCP adapter 不讀 DB、不計算 ranking、不判斷 freshness。
- 新 capability 必須宣告 target/scope、market applicability、parameter schema、paths、fields、default fields/limit、slot、unit/frequency/event-time semantics、freshness datasets、side-effect policy 與 tests。
- Screening read path 預設 cache-only；不得因單次外部問答隱性刷新約 1,900 檔股票或建立 Radar snapshot/outcome。
- Full-market、requested universe、watchlist 與 local sample coverage 必須分開；missing、stale、partial、not-released 與 excluded 不得轉成 0。
- `generated_at` 表示 envelope assembly time；`as_of` 保留 market event/data time，不得用 fetch time 或 assembly time冒充。
- 不 commit 或 push，除非使用者另外明確授權。

## 上下文

- Repo：`C:\project\Open Market Intelligence`
- 基線 branch：`codex-kr-market-readiness`
- 基線 commit：`abff4c2 feat: harden cross-market freshness and evidence`
- 工作 branch：`codex/taiwan-data-surface-v1`
- Related systems：
  - Backend AI：`backend/app/ai/`
  - Taiwan market services：`backend/app/market/`
  - Repo MCP：`agents/omi_mcp_server/`
  - Standalone MCP：`C:\GPT_MCPtool\OMI_search`
  - Frontend specialized routes consumer：`frontend/`
- 現行 public request 使用 `AiAskV4Request`，但 `selection` 與 `market_data_params` 仍是 untyped dictionaries。
- 現行 capability registry 只用 internal scope 判 applicability；public metadata 缺 market、parameters、frequency、unit、deprecation 與 replacement semantics。
- Backend `/api/ai/tools` 可由 registry 產生 capability enum，但 target enum、repo MCP 與 standalone MCP 仍各有人工清單。
- `backend/app/ai/market_context/taiwan_projection.py` 約 96 KB／2,614 行，新增 projection 時必須保留 facade/patch seams 並逐步拆分。

## 交付項目

- 任務文件與 Taiwan Data Surface v1 contract design。
- Canonical capability manifest／registry version／digest 與 public metadata。
- Capability-scoped typed parameter contract，以及 target+market applicability validation。
- Taiwan screening service、ranking／coverage capabilities 與第一批 bounded metrics。
- Taiwan quote component capabilities 與盤前 component-level freshness/quality。
- Taiwan market aggregate 與 event capabilities。
- Repo MCP 與 standalone OMI_search schema parity，不增加市場邏輯。
- Compatibility、cross-market regression、safe validation 與 live HTTP/MCP smoke evidence。

## 完成條件

- `target={type:market, market:TW}` 可明確讀取 screening ranking／coverage 與 market calendar；單一股票事件仍使用 `tw_stock`。
- 每個新 capability 都能在 `/api/ai/tools` manifest、selection validation、`evidence.data`、manifest、slots、freshness 與 quality 中被一致追蹤。
- Adapter schema 與 backend registry version/digest 一致；未知或不相容 capability／parameter 會 predictable rejection。
- Screening 回傳 stable metric definition、unit、trading-day window、snapshot identity、universe/eligible/covered/missing/excluded counts、coverage ratio 與 deterministic ordering。
- 盤前 order book／auction 可獨立 ready/partial，不因 last trade unavailable 將整包 quote blocked。
- Legacy capabilities、paths、specialized routes 與跨市場 regression 保持可用。
- Focused tests、backend safe validation、`git diff --check`、live `/api/ai/tools`／`/api/ai/ask` 與 MCP initialize→tools/list→tools/call smoke 通過；未驗證項目明確列出。

## 假設

- 使用者已將 `abff4c2` 推送保存，並授權在獨立分支進行長專案實作與驗證。
- Standalone `C:\GPT_MCPtool\OMI_search` subtree 已在修改前確認乾淨；parent monorepo 的其他既有 dirty changes 不在本任務範圍，所有檢查維持 path-scoped。
- 只有在 schema／service inspection 證明現有資料不足時，才新增 migration 或 provider；不預設需要新 DB table。
