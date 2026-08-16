# OMI US SEC Fundamental Engine

## Goal

- 將 OMI 美股基本面從「每個候選 tag 取最新 fact」升級為可驗證的 SEC 財務語意引擎。
- 對美國本土 US-GAAP 10-Q／10-K issuer，正確處理單季、YTD、年度、Q4、TTM、FCF、margin、growth 與 balance-sheet metrics。
- 讓美股基本面在 API、AI evidence 與 frontend 使用和台股一致的 `omi.financial.v1` 外層語意：`as_reported`、`normalized`、`derived`、`valuation`、`quality`、`source_refs`。
- 保留 SEC accession、input fact、derivation、issue code、freshness 與 missing／partial／blocked／not_applicable 語意。

## Non-goals

- 不保證每家公司會揭露每個 metric，也不把缺值合成 `0` 或推測值。
- 第一階段不處理任意 custom taxonomy、segment／product／geography、6-K 自動季度化或全市場無邊界 backfill。
- 第一階段不讓 IFRS／20-F、非 USD valuation 或 ADR share-basis 假裝 production-ready。
- 不改成自動交易、下單或保證結果的系統。
- 不在演算法尚未驗證前新增 canonical materialized table。
- 不在本任務中靜默改寫「台股核心」產品定位；先做 market-parity-ready contract，產品核心市場改版另以明確里程碑與產品文件更新處理。

## Hard constraints

- 保留 `USSecCompanyFact` L0 raw fact 語意與既有 `/sec/{symbol}/facts`、`/sec/{symbol}/fundamentals` response compatibility。
- 新功能採 additive、versioned route；GET/read path 不觸發外部 refresh。
- CompanyFacts canonical identity 以 CIK／issuer 為主，symbol 只作查詢與顯示；share-class metric 需另保留 class/basis 限制。
- 財務計算一律優先由 `value_text` 建立 `Decimal`，不得以 binary float 作核心計算。
- SEC provider/parser 不讀 DB；service 擁有 bounded refresh 與 transaction；router 不重做市場語意。
- SEC access 宣告 User-Agent，內部 target 不超過 4 req/s；429 遵守 `Retry-After`，403/blocked 不密集 retry。
- Frontend、MCP、Kuro 只呈現 backend contract，不自行計算財務語意、freshness 或 fallback。
- 不刪除、重建或覆蓋 `data/open_market_intelligence.db`；若未來 schema 變更必須使用 Alembic migration。
- 保留目前 worktree 中與本任務無關的台股／FX 變更。

## Context

- Repo: `C:\project\Open Market Intelligence`
- Source design: `C:\Users\thoma\Downloads\OMI_US_SEC_Fundamental_Engine_Architecture_v0.1.txt`
- Related systems: backend US market、SEC provider、SQLite、source health、AI capability contract、US detail frontend。
- 現有 ingestion 已包含 SEC ticker mapping、CompanyFacts provider/parser、`USSecCompanyFact` raw store 與 explicit refresh route。
- 現有 summary 只依 `period_end_date`、`filed_date`、tag priority 與 row id 取最新 fact，沒有 period/unit/restatement semantics。
- 2026-08-11 唯讀 DB 檢查顯示：AAPL、MU 最新 Revenue 為 91 天單季，但 OCF／CapEx 為 182 天 H1；NVDA 現有 CapEx 選到 2020 年。
- 現有 `fundamentals.financials` AI projection 會把 US SEC summary 投影成空物件但不標 unavailable。
- 既有 `us_market.watchlist_resource_refresh` job 已提供 per-symbol failure isolation 與 job polling，後續 SEC freshness 應沿用該 ownership。

## Deliverables

- 本任務的 capability contract、milestone plan、progress 與決策紀錄。
- 真實、最小化、具來源 metadata 的 SEC CompanyFacts fixtures。
- Period resolver、unit resolver、canonical metric registry／selector 與 issue-code contract。
- 單季、Q4、TTM、FCF、margin、growth、net debt 等 derived engine。
- SEC request gate、bounded retry、Submissions metadata 與 filing-aware freshness。
- Additive `/api/us-market/sec/{symbol}/financials` contract，以及 legacy fundamentals compatibility。
- `omi.financial.v1` 相容的 US AI evidence projection與 data-quality guard。
- Frontend 使用 backend-derived metrics，並呈現 partial／blocked／not_applicable／stale。
- Targeted unit／service／API／AI／frontend regression 與必要的 bounded runtime proof。

## Done criteria

- AAPL／NVDA／MU fixture 不會把 H1／9M 當成單季，且非曆年 fiscal calendar 可正確識別。
- Q4 flow、TTM、FCF 與 margin 只有在 inputs 連續、同 metric basis、同 unit 時產生，並保留 `input_fact_ids`。
- Amendment／later-filing revision 可確定性選取；舊 raw accession 不被刪除。
- Unit mismatch、currency mismatch、period ambiguity、missing quarter 與 unsupported taxonomy 會降級而不是補假資料。
- 新 API 不破壞舊 facts／fundamentals route，且 GET 不發出 SEC request。
- SEC refresh 有明確 request bounds、source health、provider event 與 retry 行為。
- `fundamentals.financials` 對 US 回傳非空、market-neutral financial contract；缺資料時 readiness／confidence 受限。
- Frontend 不再從 legacy latest facts 自行計算核心 margin／TTM／valuation。
- 所有 milestone 的 targeted regression 通過，Progress.md 有 runtime adoption 或明確未執行說明。

## Open questions / assumptions

- Phase 1 只承諾 `current_comparable`；完整 `as_reported_as_of` 需要 Submissions known-at 與 append-only raw revision／payload snapshot 策略。
- IFRS／20-F、6-K、segment engine、bulk maintenance 與 canonical materialization 只有在前一階段品質與效能證據足夠後啟動。
- 美股升格為與台股平等或取代台股主線，需另行更新 `docs/product/` 與 repo policy；本任務先消除技術與契約障礙。
