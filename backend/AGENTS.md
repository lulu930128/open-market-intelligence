# OMI Backend AGENTS.md

本檔適用於 `backend/`。先讀 repo root `AGENTS.md` 與 `docs/architecture/index.md`，再依修改範圍讀 current architecture、executable registry、architecture debt 與相關 tests。

## Backend invariants

- Router 只負責 transport、input validation、status code、dispatch 與 response projection。
- GET／read path 預設不得 fetch provider、refresh、repair、enqueue、subscribe 或寫入資料。
- Provider adapter 只做 IO、登入／訂閱、payload parsing、provider-specific error normalization 與 Canonical Observation conversion。
- Cross-provider selection、fallback、freshness、realtime policy、lease、dataset health 與 repair planning 由 Resolution／Control Plane 擁有。
- AI 只使用 backend-owned resolved evidence，不直接呼叫 provider 或自行重做 market session、freshness、fallback。
- Portfolio 由 Account truth 與 resolved Market Data／FX 組合，不直接選市場價格來源。
- Query helper 不 commit。Transaction owner 必須是明確 persistence／refresh／job／maintenance boundary，失敗時 rollback 並保留原始錯誤。
- Schema 變更使用 Alembic migration，不以 `create_all`、刪除或重建使用者 DB 代替。
- 既有 architecture debt 可以維持在已宣告範圍內，但不得新增 occurrence 或把 compatibility 當永久 owner。

## Layer map

- `app/routers/`：transport boundary。
- `app/market_data/`：provider-neutral Shared Market Data Foundation；另受其 nested `AGENTS.md` 約束。
- `app/market/`：台股特有 session、regulation、dataset 與 research policy。
- `app/us_market/`：美股特有 session、corporate action、provider integration 與 research policy。
- `app/ai/`：evidence、capability、question routing、decision 與 outward AI contract。
- `app/portfolio/`：Account truth 與 resolved valuation projection。
- `app/jobs/`：bounded background、repair、refresh 與 maintenance work。

## Temporal / evidence axes

Market Session、Instrument Trading Status、freshness、evidence-object finalization、authority、release 與 reconciliation 是不同維度。先重用 source 中既有 typed axes，只對缺少的 axis 做 additive extension；不得建立混合 `pre_open`、`session_final`、`official_final` 的 universal `TemporalState`。`official_final` 若需要作為 outward label，只能由 dataset semantics、authority、release 與 item finalization 推導。細節見 `docs/architecture/MarketTemporalContract.md`。

## 完成前

- 跑最接近的 targeted backend tests。
- 若 architecture guard 已存在，必須執行並確認沒有新增未宣告 debt。
- Runtime-affecting 變更要證明 loaded source identity；需要真實市場行為的功能另做正式 session／provider acceptance。
- 明確列出未驗證的 runtime、live 或 product surface。
