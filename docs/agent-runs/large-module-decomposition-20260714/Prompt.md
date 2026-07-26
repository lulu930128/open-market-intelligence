# OMI 大型模組責任解耦

## 目標

- 以責任、state ownership、side-effect ownership 與 public contract 為單位，分階段拆解 OMI 的大型 frontend/backend 模組。
- 把目前集中在少數檔案中的 URL routing、資料載入、polling、refresh、圖表 lifecycle、AI context projection 與 provider use case 移到可獨立驗證的邊界。
- 保留穩定 shell / facade，讓既有 UI、API、SSE、tool name、資料 envelope、測試 patch seam 與外部 consumer 不需要同步改寫。
- 建立可以長期重複使用的拆分流程：先 characterization、再移動 ownership、最後才評估共用抽象。

## 非目標

- 不進行整檔 rewrite、視覺 redesign、資訊架構改版或新增產品功能。
- 不改 public route、query parameter、response shape、SSE event、AI tool name、watchlist URL 或 selection contract。
- 不新增 state management、圖表、測試或 backend framework dependency。
- 不做 DB migration，不刪除、重建或修改本機 `data/open_market_intelligence.db`。
- 不因行數大就拆 `backend/app/db/models.py`、i18n message、測試 fixture 或其他宣告型檔案。
- 不在本任務順便統一所有市場 service；US/JP/KR/crypto 仍維持台股 context layer 定位。

## 硬性限制

- 台股仍是資料 contract、UI pattern 與驗證深度的基準；frontend 不新增市場判斷、freshness 或 provider fallback 邏輯。
- 一個批次只移動一個可命名 ownership，不同時搬 routing、fetch、render 與 business behavior。
- 抽離前必須先有可重現的 characterization；抽離後必須以同一案例驗證行為等價。
- Presentation component 不直接 fetch；domain hook 不同時擁有不相干的 URL、資料與 UI state machine。
- Backend provider adapter 不持有 DB transaction；query/read helper 不 commit；refresh/upsert owner 必須維持既有 commit/rollback 契約。
- `tools.py`、`agentic_tools.py` 與 `us_market/service.py` 在拆分期間保留 compatibility facade。既有測試會 patch facade module symbols，實作移動後必須由 wrapper 每次把 facade dependency 傳入新模組，不能只做靜態 re-export。
- 不複製實作換取較短檔案；共用 abstraction 只在至少兩個已驗證 use case 真正一致後建立。
- 每個批次獨立驗證、獨立 commit；前一批失敗時不疊加下一批修改。
- implementation 前先保存目前已驗證的 dashboard ranking 第一批 baseline；本輪規劃階段不 commit、不開始下一批程式修改。

## 背景與目前基線

- Repo：`C:\project\Open Market Intelligence`
- Branch：`codex-kr-market-readiness`
- Product alignment：`docs/product/Roadmap.md` M3 要求 routing/type/helper、slot rendering 與 market shell 可維護；`OperatingModel.md` 要求 backend 保有市場邏輯與 freshness 真相來源。
- 目前工作樹包含尚未提交的 dashboard ranking 第一批抽離與 E2E characterization。
- `MarketDashboardClient.tsx`：5,365 行；主 component 直接持有大量市場 selection、ranking、radar、refresh 與 URL state。粗略結構統計為 96 個 `useState`、27 個 `useEffect`、21 個 API call expression。
- `StockDetailPanel.tsx`：4,206 行；集中 chart data、drawing persistence、quote depth、data tabs、refresh/backfill、index context 與 fallback technical report。粗略統計為 67 個 `useState`、21 個 `useEffect`、23 個 API call expression。
- `LightweightKLineChart.tsx`：4,492 行；集中 imperative chart lifecycle、projection、drawing hit testing、pointer/keyboard interaction 與大型 overlay render。主 lifecycle effect 約 590 行。
- `backend/app/ai/tools.py`：3,373 行；`list_ai_tools()` 約 736 行，並集中 TW market/index/futures/stock/watchlist readers。
- `backend/app/ai/agentic_tools.py`：2,949 行；集中 tool planning/execution 與 US/JP/KR/crypto context readers。
- `backend/app/us_market/service.py`：3,275 行；已有 provider modules，但 service 仍集中 master、price、SEC/profile、corporate action、FINRA、FRED、watchlist 與 resource refresh use cases。
- `backend/app/db/models.py`：3,158 行、79 個 ORM class，依既有 migration/import contract 維持單一 registry。

以上數字是規劃快照，用來觀察責任是否下降，不作為硬性完成門檻。

## 交付範圍

- Dashboard：ranking/radar/selection/market tape/OMI context 各自具有明確 state owner，`MarketDashboardClient` 收斂成 composition shell。
- Stock detail：chart data、drawing persistence、quote depth、index context 與 data panel refresh 各自形成 domain hook；純 technical/view projection 移出 container。
- Chart：imperative chart lifecycle、drawing interaction、projection/indicator 與 overlay presentation 分層；不改既有圖形語意與操作方式。
- AI：TW 與跨市場 context readers、tool catalog、tool execution、answer composition 分層；`tools.py` 與 `agentic_tools.py` 保留相容入口。
- US market：按 use case 拆成 master、prices、fundamentals、macro、watchlists、resource refresh；`service.py` 保留 public facade。
- Validation：補足每個 ownership 的 characterization、contract regression、frontend build/E2E 與 backend targeted/full safe validation。
- Documentation：維護 `TargetArchitecture.md`、`Plan.md`、`Progress.md` 與最終 `ARCHITECTURE_REVIEW.md` 證據。

## 整體完成條件

- 大型 shell 不再直接擁有多個互相獨立的 network/polling state machine；presentation boundary 不直接呼叫 API。
- Dashboard 與 StockDetail 的 URL、selection、refresh、loading、empty/error、freshness 顯示和目前 characterization 等價。
- Chart 的 timeframe、drawing、selection、undo/redo、pointer/keyboard interaction 與 desktop/mobile 版面通過實際 browser 驗證。
- AI public tool inventory、tool names、payload levels、slot envelope、source refs、warnings、SSE/answer contract 不變。
- US market routers、jobs、dispatch、AI callers 與既有 patch-based tests 仍可透過 `app.us_market.service` 使用原 public symbols。
- Backend transaction、provider event、source-health 與 bounded refresh 契約不變，沒有新增隱性外部 API 或 DB side effect。
- `models.py` migration parity、API contract inventory、frontend TypeScript/lint/build/Playwright 與相關 backend regression 全部通過。
- 每個 milestone 都在 `Progress.md` 留下修改範圍、驗證證據、決策與剩餘風險。

## 規劃假設

- 預設不新增全域 store；先用 colocated domain hooks、`useReducer` 或小型純 projection module 管理 ownership。
- 預設保留目前 UI 與 backend response，不把 refactor 和產品功能混在同一批。
- 預設依 `Plan.md` 的 commit boundary 執行，不做一個難以 review 或回退的 mega commit。
- 使用者確認本規劃後，第一個實作動作是重新驗證並提交目前 dashboard ranking baseline；確認前不開始下一批。
