# Progress

## Status

- Current phase: Fundamental Stage 0–8 與 ownership extension Stage 0–12 complete；全市場 CUSIP inventory 已完整查核，ticker coverage 依 approved mapping 維持 explicit partial
- Last updated: 2026-08-13 +08:00
- Runtime adoption: complete on launcher-selected Backend `8400` / Frontend `3000`

## Completed

### Stage 0：保護現況與可信 fixtures

- 讀取使用者 v0.1 架構設計、repo product/architecture contracts、既有 SEC provider/parser/store/service/schema/router、AI capability 與 US frontend consumer。
- 以 SEC 官方文件確認 CompanyFacts、Submissions、bulk data 與 fair-access 基線。
- 唯讀檢查本機 SQLite，確認舊 selector 會混合單季與 YTD，且可能選到非常舊的 tag series。
- 建立 AAPL CompanyFacts 與 Submissions fixtures，保留真實 accession、91-day discrete quarter、182-day YTD、later-filing comparative 與 amendment evidence。
- 固定 legacy `USSecFundamentalSummaryRead`、parser、store 與 OpenAPI compatibility regression。

### Stage 1：Period／Unit／Canonical Core

- 建立 `backend/app/us_market/sec_fundamentals/` pure domain package：canonical registry、Decimal fact contract、period resolver、unit resolver、deterministic selector。
- 支援 3m／6m／9m／53-week annual／instant、非曆年 fiscal quarter、10-Q/A、10-K/A、later-filing revision、mixed currency 與 scope-aware issue handling。
- 同一 period end 同時存在 discrete/YTD 時，未指定 scope 會 blocked；不依 row id 或輸入順序猜值。
- 保存 CIK、taxonomy、tag、raw/normalized unit、currency、economic period、reported fiscal metadata、form、filed date、accession、source URL 與 issue codes。

### Stage 2：Derived Engine

- 實作 direct quarter、YTD subtraction、Q4 annual-minus-Q1-Q2-Q3、四季連續 TTM、FCF、gross/operating/net margin、YoY growth、debt total、net debt 與 annual reconciliation。
- 所有 derived value 都帶 `formula`、`derivation`、`input_fact_ids`、`status` 與 deterministic issue codes。
- 對 missing、mixed unit/currency、zero denominator、period gap 與 direct-vs-derived dispute fail closed，不把缺值轉成 `0`。

### Stage 3：SEC Access Policy、Submissions 與 Freshness

- 所有 SEC HTTP 經共用 policy：內部目標不超過 4 req/s、2 次 attempt、bounded backoff、429/403 明確分類。
- refresh 先查 Submissions；local latest accession 已等於 remote 時跳過 CompanyFacts 下載。
- Submissions 只保存公開 latest filing metadata，使用 atomic JSON cache；process restart 後仍能判斷 current/stale。
- GET/read path 只讀本機 facts 與 metadata cache，不發 SEC request；watchlist batch 沿用既有 per-symbol failure isolation。

### Stage 4：Versioned API Contract

- 新增 additive `GET /api/us-market/sec/{symbol}/financials`，輸出 `omi.financial.v1`：`as_reported`、`normalized`、`derived`、`valuation`、`quality`、`source_refs`。
- 輸出期間 bounded 為 4-12，raw query bounded 為 20,000 rows；legacy facts/fundamentals routes 與 response shape 保持不變。
- ETF/index 回傳 `not_applicable`；IFRS/custom/segment 缺口維持 partial/unsupported。
- `as_reported_as_of` 因現有 raw upsert 不是 append-only history 而明確 blocked，沒有偽造歷史快照。
- 品質判定只讓最新核心 Revenue／Net Income 四季 continuity 與 freshness 阻斷 decision usability；舊季度或次要 EPS dispute 仍以 `supplemental_semantic_validity=disputed`、`non_blocking_issues` 可見。

### Stage 5：AI Contract Adoption

- US market context、agentic `us.read_sec_fundamentals`、decision adapter 與 report builder 優先使用 `omi.financial.v1`，legacy summary 僅保留 fallback。
- `fundamentals.financials` 不再投影成未標示的空物件；freshness/quality 會進入 capability readiness、warnings 與 data limits。
- stale/missing 允許 bounded refresh；partial/disputed 不被偽裝成 ready；MCP/Kuro 仍維持 thin adapter。

### Stage 6：Frontend Adoption

- 新增 US financial contract types，US 詳情頁直接顯示 backend-derived TTM Revenue/EPS/P-E、gross/operating/net margin、Revenue YoY、FCF、net debt 與 normalized quarterly table。
- 顯示 contract version、申報新鮮度、季度連續性、核心與補充指標語意、blocking/non-blocking issues；保留 legacy summary 安全 fallback。
- 移除前端自行推導 margin、D/E 與 market-cap estimate 的核心財務邏輯。
- 新增繁中、英文、日文文案；未新增 UI library。

### Stage 7：Production proof

- AAPL、NVDA、MU 進行 bounded real SEC refresh；AAPL/MU 更新至最新 accession，NVDA 已 current。後續同三檔 refresh 只抓 Submissions，CompanyFacts `fetched_count=0`，證明 persistent accession cache 可避免重複大 payload。
- 真實 contract：AAPL、NVDA、MU 都是 `freshness=current`、`continuity=ready`、`semantic_validity=valid`、`decision_usable=true`；歷史/次要 dispute 留在 supplemental/non-blocking 區。
- 重啟精確由 OMI launcher 擁有的舊 service trees；最終 wrapper PID 為 backend `42220`、frontend `64112`，launcher health 為 `API OK; UI OK`。
- 實際 Backend、Frontend proxy、OpenAPI 與 `omi.decision.v4` evidence 都讀到 `omi.financial.v1`，AAPL decision usable 為 true。
- 實際瀏覽器 AAPL「申報」頁籤顯示 contract ready/current/valid、所有新增衍生指標與 2025Q1-2026Q3 normalized quarter rows；browser console 無 error。其後補上的 supplemental/non-blocking 透明度顯示另經 lint、typecheck、production build 與 runtime restart 驗證。

### Stage 8：美股基本面工作台改版

- 將舊版「持倉／內部人／空方／申報」改為美股資料類型導向的「概況／財務／機構／內部人／空方／申報」，預設進入財務頁。
- 公司主檔與估值留在概況；`omi.financial.v1` 的品質、衍生指標與標準化季度移到獨立財務頁；13F、Form 4、FINRA 與 raw SEC facts 各自保留明確來源與資料限制。
- 抽出 `USFundamentalWorkspace`，提供台股式資料頁籤節奏、3×2 窄欄配置、ARIA tab contract、方向鍵/Home/End 操作與 responsive panel header；未新增 UI dependency。
- AAPL 實際顯示 ready/current 財務與 8 季資料；TSM 實際顯示 `partial`、`missing`、`unsupported_ifrs_taxonomy` 與安全空值，不把 IFRS 缺口偽裝為 ready。
- 390px 實際 viewport 的 `clientWidth=390`、`scrollWidth=390`；六個頁籤均完整顯示且每格 115×44，browser console 無 error。
- 最終 OMI launcher 於 21:44 重啟，wrapper PID 為 backend `54060`、frontend `54396`；listener PID 為 backend `50840`、frontend `59588`，launcher 顯示 `API OK; UI OK`。

### Ownership extension：Form 4 與 SEC 13F

- 後續 ownership 長專案已完成 Form 4 `omi.sec.insiders.v1`、SEC 13F `omi.sec.13f.v1`、tracked jobs、source health、AI evidence 與新版「內部人／機構」頁。
- SEC 13F 官方公開歷史已完成 53/53 datasets（2013Q2–2026Q1）full-row ingest；120,182,194 source rows 以 Parquet v3 保存並完成 hash/reconciliation verification。
- OpenFIGI key 已只設定於本機 ignored `.env`；138,869 個 canonical CUSIP 全數完成 authenticated lookup。結果為 10,927 approved、2,672 ambiguous、14,648 unverified、110,622 unmapped，未唯一核准者仍保留 source-native CUSIP 與 explicit status。
- 全市場 materialized projection 已完成 252,796 rows／10,650 symbols；row coverage 74.2606%、reported-value coverage 74.0251%。AAPL、MSFT、NVDA 均可讀 53 季，contract 保持 `partial` 且 `decision_usable=true`。

## Validation evidence

- SEC/AI focused regression：49 tests passed。
- SEC + 既有 US/AI/MCP targeted regression：357 tests、14 subtests passed。
- Safe backend profile：`compileall` passed；完整 backend `1724 passed`；`git diff --check` passed。Logs：`.tmp/validation/20260811-192153`。
- Frontend：`npm run lint` passed；`npm exec tsc -- --noEmit --incremental false` passed；`npm run build` passed（Next.js 16.2.12，全部 routes generated）。
- Frontend redesign 最終版：再次執行 `npm run lint` 與 `npm run build` 均 passed；build 內含 TypeScript 檢查與 6 個 routes generation。
- Runtime：`/api/system/health=ok`、`/api/system/readyz=ready`、`/omi-ui-health=ok`；OpenAPI path count 338 且包含新 financials route。
- Backend API 與 frontend proxy：AAPL `omi.financial.v1`、current、semantic valid、supplemental disputed、decision usable、8 個季度、TTM Revenue ready、valuation ready。
- AI outward：`omi.decision.v4` completed、facts ready；`fundamentals.financials.financial_contract` 為 `omi.financial.v1` 且 decision usable/current/valid。

## Decisions made

- 沿用 CompanyFacts ingestion 與 `USSecCompanyFact` 作 L0；財務語意放在 pure domain package，不塞回大型 `service.py`。
- 不建立第二套互不相容的 Fundamental Bundle public envelope；US internal bundle 投影為 market-neutral `omi.financial.v1`。
- Phase 1 採 no-migration、on-read canonicalization。真實本機 contract 約數百毫秒，暫無 materialization 的必要。
- canonical issuer identity 使用 CIK；symbol 只作 lookup/display alias。
- `10-Q/A`／`10-K/A` 才標 formal amendment；later filing comparative 不自動宣稱 restatement。
- filing freshness 使用 persistent public metadata cache；不把交易日 freshness 套到 SEC filing。
- 台股仍是產品核心；本次完成的是可讓美股逐步靠齊的資料與決策技術基座，不在單次工程任務中改寫市場定位。
- 美股頁籤依「研究資料類型」而非 provider 命名；provider lineage 與缺口留在各頁內容，避免主檔、13F 與 SEC financials 混成同一種資料。

## Remaining limits / follow-up scope

- 現有 raw upsert 會更新同 fact key 的 value，不能宣稱完整 append-only fetch history；production `as_reported_as_of` 需要 raw payload/revision snapshot 設計與 migration。
- CompanyFacts 主要涵蓋 standard-taxonomy whole-entity facts；IFRS/custom tags、segment、bank-specific statement layout 與 6-K 不保證同等覆蓋，必須維持 explicit partial/unsupported。
- SEC 13F 與 Form 4 已接入；全市場 canonical CUSIP inventory 已全部送交 versioned mapping，但 127,942 個結果不是 approved unique US-equity mapping，因此未映射 symbol 仍會顯示 explicit partial/empty，不能把 source completeness 解讀為 100% ticker coverage。
- 全市場 13F projection 會產生約 5.8 GiB shadow artifact，正式 SQLite 目前約 20.43 GiB；重建已採 1.5 GiB DuckDB memory limit、disk spill、JSONL shadow 與最後 atomic bulk replace，需保留足夠磁碟與長任務時間。
- 本次驗證是 AAPL/NVDA/MU 與已存入本機的 US watchlist universe，不代表每一家 SEC issuer 都一定具有全部 metric。
- 全市場 SEC bulk ingestion、歷史 materialization 與 IFRS mapping 是後續獨立 milestones；目前不需要為已達成的互動查詢路徑擴大 storage/maintenance cost。
- Windows sandbox 先前 pytest ACL failure 留下 5 個 `.tmp/tmp*` 空測試目錄；已限定精確路徑嘗試清理但被 ACL 拒絕，未升權刪除。它們不屬於產品資料且不影響驗證。
- Worktree 原本已有台股／FX／frontend 變更；本任務未 revert 或覆蓋無關內容，也未 commit/push。

## Next recommended milestone

- SEC ownership 已另立長專案：先完成 Form 4，再依全市場 CUSIP-native 架構建立 13F；規格與執行順序見 `docs/agent-runs/us-sec-ownership-engine-20260811/`。
- Financial engine 後續仍以 US watchlist coverage audit、IFRS mapping、financial-sector registry 與 append-only filing snapshot 為獨立範圍，不與 ownership ingestion 混用 migration 或 contract。
