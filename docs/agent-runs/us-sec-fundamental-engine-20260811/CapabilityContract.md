# Capability Contract

| 項目 | 契約 |
| --- | --- |
| Product scope | 建立 US whole-company filing fundamentals，對齊 OMI market-neutral financial contract；不暗示自動交易。 |
| Target | Public US stock symbol；入口先 normalize symbol，再以 10-digit CIK 作 issuer identity。Phase 1 支援 US domestic 10-Q／10-K；index／ETF／無 CIK target 為 not_applicable 或 blocked。 |
| Provider | SEC EDGAR `companyfacts` 與 `submissions`；public、無 API key。必須使用 declared User-Agent、positive timeout、4 req/s internal target、bounded retry。 |
| Resource | Whole-entity standard taxonomy facts。L0 raw 保留 SEC taxonomy/tag/unit/period/form/accession/value；L1 canonical metric；L2 derived metric；L3 AI research evidence。 |
| Forms | Phase 1 allowlist：10-Q、10-Q/A、10-K、10-K/A。20-F／20-F/A／40-F／40-F/A 為 partial/beta；6-K 暫不作標準季度來源。 |
| Units | 保存 SEC raw unit（例如 `USD`、`USD/shares`、`shares`、`pure`），另正規化為 money／per_share／shares／pure 與 currency。Frames URL 的 `-per-` 表示不得直接當 CompanyFacts raw unit。 |
| Period | 以 start/end/duration/form/fp/accession 共同判斷；economic period identity 以實際日期為主，SEC `fy/fp` 只作 reported metadata 與 consistency evidence。 |
| Freshness | Filing-aware，不套用交易日 freshness。Submissions latest relevant accession、local latest accession、filed/accepted/fetched times共同決定 current／stale／missing／unknown。 |
| Request bounds | Interactive explicit refresh 每次單一 symbol；watchlist 使用既有 job、per-symbol isolation 與低併發／序列。GET `/financials` 只讀 local facts。全市場 bulk 不在 Phase 1。 |
| Persistence | Phase 1 不 migration：on-read canonicalization 使用 `USSecCompanyFact`。現有 upsert 不是完整 append-only fetch history；`as_reported_as_of` production 前另定 raw revision/payload snapshot。 |
| Failure | 區分 missing、partial、blocked、disputed、approximate、not_applicable、rate_limited、provider_failed；不得把 missing 轉 `0`。 |
| Transaction | Provider/parser 無 Session；service 查詢、upsert 與 rollback。Batch resource failure 以既有 watchlist refresh 行為隔離；telemetry failure 不取代 domain error。 |
| Public API | 保留 `GET /sec/{symbol}/facts`、`GET /sec/{symbol}/fundamentals`；新增 `GET /sec/{symbol}/financials`。Refresh 維持 explicit POST/job。 |
| AI contract | `fundamentals.financials` 使用 `omi.financial.v1` market-neutral envelope，保留 source refs、quality、missing、warnings、payload bounds。切換採 additive/double-read regression。 |
| Consumer | US detail UI 顯示 backend-derived quarterly/TTM/ratios 與 quality；MCP/Kuro 維持 thin。Alpha Vantage profile 可保留描述欄位，但不再是 financial-statement canonical source。 |
| Validation | Pure period/unit/candidate tests；service/current-comparable tests；provider/rate/freshness tests；API inventory；AI projection/data-quality；frontend lint/typecheck/build；最後才做 bounded runtime/API/UI smoke。 |

## Compatibility invariants

- Legacy `USSecFundamentalSummaryRead` shape 保持不變，直到所有 consumer 完成 migration。
- 新 canonical status 與 issue code 不得被 legacy adapter偽裝為 ready。
- `not_applicable` 不等於 missing；unsupported IFRS／segment 不得污染 US-GAAP issuer 的 ready metrics。
- `HTTP 200`、raw row count、cache hit 與 latest period end 都不等於 canonical decision usability。

## Initial canonical metrics

- Duration：revenue、gross_profit、operating_income、net_income、operating_cash_flow、capex。
- Instant：assets、liabilities、equity、cash。
- Phase 1.5：debt_current、debt_noncurrent、debt_total、shares_outstanding、weighted-average shares、basic/diluted EPS。
- Bank／financial issuer 不強迫產生 gross profit；metric availability 由 registry applicability 與 facts 決定。
