# OMI US SEC Ownership Engine

## Goal

- 先完成 SEC Form 4 內部人交易的 production-ready ingestion、保存、freshness、API、AI evidence 與美股詳情頁呈現。
- Form 4 完成並通過 runtime proof 後，再建立以 SEC 官方季度 bulk data 為主的全市場 13F 倉儲、CUSIP 映射、季度比較與 symbol／manager 查詢能力。
- 沿用既有 SEC `User-Agent`、4 req/s request policy、provider event、source health、tracked job、SQLite migration 與「更新狀態」流程，不建立旁路資料系統。
- 維持 evidence-first：accession、filing date、report period、來源 URL、解析版本、映射版本、缺口與 amendment 都必須可追溯。

## Scope order

1. Form 4 transaction ledger first。
2. Form 4 API／AI／frontend adoption and running-system proof。
3. 13F latest two-quarter full-market warehouse proof。
4. 13F all-published-history resumable backfill。

在 Form 4 的 done criteria 全部達成前，不開始 13F production implementation；可以先保留文件與 fixtures，但不得讓兩條 ingestion 同時擴張而失去驗證邊界。

## Full-market definition

- 「全市場 13F」是指：對每一個標記為 completed 的季度，官方 Form 13F Data Set 中所有 submission、manager 與 information-table rows 都被匯入、明確 quarantine，或以可稽核 reason code 計數；不得只保留 watchlist rows。
- 全市場 completeness 以 CUSIP-native warehouse 為準，不以 ticker 映射率假裝來源 completeness。無法可靠映射 symbol 的 rows 必須保留。
- 初始 production window 是最近兩個可比較季度；完成容量與映射 gate 後，逐季回補 SEC 官方仍提供的全部歷史資料。
- 每個歷史季度是獨立、可重試、可續跑的 tracked job；不得用單一無界 job 一次下載並解析全部歷史。

## Non-goals

- 不把 13F 解讀成台股每日三大法人買賣超；13F 是季度持倉揭露，法定申報可能落後報告期最多約 45 天。
- 不把 Form 4 的所有 transaction code 簡化成買進／賣出；gift、option exercise、tax withholding、award、derivative 與 10b5-1 必須保留原語意。
- 第一階段不宣稱 Form 4 單獨能重建完整 current insider position。Form 3 起始持股與 Form 5 補申報是後續 completeness milestone。
- 不依賴付費第三方資料源作為首版必要條件；若免費、可稽核的 CUSIP→symbol 映射未達門檻，再提出重大資料源決議。
- 不在 GET/read path 下載、解壓或解析 SEC 檔案。
- 不把市場資料邏輯搬到 frontend、MCP 或 Kuro；consumer 只讀 backend contract。
- 不修改已完成的 `omi.financial.v1` 計算與既有 SEC CompanyFacts route 行為。
- 不做自動交易、下單或把揭露資料轉成無條件買賣建議。

## Hard constraints

- Canonical issuer identity 使用零補齊 CIK；symbol 僅是 lookup/display alias。13F canonical security identity 使用 normalized CUSIP，ticker projection 必須帶 `mapping_version` 與 mapping status。
- Filing 以 accession number 作不可變 identity。`4/A`、`13F-HR/A` 不覆蓋或刪除原 filing；current view 由 deterministic supersession policy 投影。
- 交易股數、價格、13F shares/value 等精確數值先以 `Decimal` 解析並保存 canonical text；不得以 binary float 作唯一真相來源。
- 所有 schema change 走 Alembic；不得直接修改或重建 `data/open_market_intelligence.db`。
- Raw ZIP、解壓 staging、manifest 與 checkpoint 放在 configurable local cache，排除 Git；成功後可移除解壓檔，但保留壓縮 source archive、SHA-256 與 release metadata。
- Download、parse、upsert、projection 分階段且可 idempotent rerun。季度未完整成功時，不得讓 partial rows 成為 current production snapshot。
- 所有 external IO 都有 timeout、retry、max archive size、max quarters、max filings、disk free-space floor 與 concurrency lock。
- GET/read path cache-only；refresh/backfill 只能由明確 POST job 或 scheduler owner 執行。
- SEC live request 共用既有 descriptive `US_SEC_USER_AGENT` 與 process-local 4 req/s gate；429、403、timeout、schema drift 必須寫 provider event/source health。
- `ready_empty`、`missing`、`partial`、`stale`、`blocked`、`not_applicable` 不得互相混用，也不得把缺值填 `0`。
- Worktree 目前有其他既有變更；實作只修改 ownership scope 的檔案，不 revert、不做無關 cleanup、不 commit/push，除非使用者另行要求。

## Trust and data boundaries

- SEC 公開 filing／bulk archive 可由 bounded job 自動下載並寫入本機 cache/DB。
- 本機 archive、SQLite、job result 與 logs 不得進 Git；logs 不記錄完整 payload，只記 source、checksum、counts、timing 與錯誤摘要。
- Provider/parser 不持有 DB session；service／store 負責 normalization、transaction、checkpoint 與 rollback；router 只驗證 request 並 enqueue／read。
- AI 只能使用 backend 已投影且帶 freshness/source refs 的資料；不得自行猜測未映射 CUSIP、交易動機或 13F 報告期後的持倉。

## Deliverables

- `docs/agent-runs/us-sec-ownership-engine-20260811/` 的規格、能力契約、里程碑與進度紀錄。
- Shared SEC ownership dataset manifest、checkpoint、archive cache 與 migration。
- Form 4 XML／bulk parser、append-only filing/owner/transaction/holding/footnote store、amendment selector 與 transaction semantics。
- Form 4 symbol/watchlist refresh job、freshness/source-health、versioned API、AI compact evidence、frontend「內部人」頁與更新狀態整合。
- 13F quarterly archive ingestion、manager/filing/holding warehouse、CUSIP-native query、versioned identifier mapping、symbol-quarter projection 與 coverage audit。
- 13F current/prior-quarter API、AI evidence、frontend「機構」頁、全歷史逐季 backfill 與 capacity/runtime proof。
- Parser、service、migration、job、source-health、API、AI、frontend 與 runtime regression evidence。

## Done criteria

### Form 4 first

- 常見 Form 4、`4/A`、multi-owner、non-derivative、derivative、footnote、10b5-1 與 malformed fixtures 有 deterministic parse result。
- 原始 filing 與 amendment 都保留；current projection 不 double count 被取代的 transaction。
- UI 明確區分 open-market purchase/sale、gift、tax withholding、award、option/derivative 與其他 code；不做不相容類別的虛假淨額。
- `GET` 只讀本機；symbol/watchlist refresh 由 bounded tracked job 執行，失敗可重試且不破壞前一個可用 snapshot。
- AAPL 加至少一個含 derivative 或 amendment 的代表 symbol，完成 backend/API/frontend running proof；無資料的合法 issuer 顯示 `ready_empty`。
- Form 4 contract 明示只代表已申報 transactions/after-transaction amounts，不宣稱完整 current position。

### 13F full market

- 最近兩個官方季度的 source ZIP checksum、source row counts、inserted/updated/quarantined counts 可完全對帳，無 silent drop。
- 所有 source holdings rows 以 CUSIP-native 形式留存；symbol mapping 缺口有 row/value coverage 與 reason codes。
- `13F-HR`、`13F-HR/A`、`13F-NT`、put/call、share/principal、other manager、shared discretion、voting authority 與 confidential-treatment limits 均有測試與可見語意。
- Symbol API 可比較相鄰 report quarters，並把 `report_period`、`filed_at`、`data_release` 分開；不稱為即時機構買賣。
- 每季 job 可 idempotent rerun、resume、cancel/retry；季度失敗不污染 current projection。
- 經 capacity gate 後，所有 SEC 仍公開的季度逐季完成或留下明確 blocked reason；coverage API 可看到每季狀態。
- 最新 symbol query 在 bounded limit 下達成計畫內效能門檻，frontend/AI 不載入全市場 payload。

## Major-decision stop conditions

- 最近兩季實測推估的完整歷史 SQLite＋index footprint 超過設定的本機 ownership storage budget，或無法維持 free-space safety floor。
- 目前可用、可合法再現的 CUSIP mapping 在最近兩季低於 90% rows 或 95% reported value，因而不能誠實宣稱 symbol-level coverage。
- SEC bulk schema／授權／access policy 與目前官方文件不一致，或來源不再提供可重現的季度 archive。
- SQLite 在代表資料量下無法讓最新 symbol query 的 warm-cache p95 保持在 1 秒內，且合理 index/materialized projection 仍無法改善。
- 需求改為跨裝置、多使用者或 remote warehouse，超出現有 local-first SQLite ownership boundary。

命中以上任一條件時，保留已完成的 CUSIP-native/source archive 能力，停止擴大 backfill，向使用者提出 storage engine、mapping provider 或部署邊界的重大決議。

## Context

- Repo: `C:\project\Open Market Intelligence`
- Parent capability: `docs/agent-runs/us-sec-fundamental-engine-20260811/`
- Existing frontend slots: `frontend/src/components/us-stock-detail/USFundamentalWorkspace.tsx`
- Existing SEC provider/policy: `backend/app/us_market/providers/sec.py`、`sec_policy.py`
- Existing job/source-health owners: `backend/app/jobs/`、`backend/app/us_market/source_health.py`
- Current Alembic head at planning time: `20260809_0057`；實作時使用當下 next available revision，不硬套 planning-time revision number。

## Official source baseline

- SEC Insider Transactions Data Sets: <https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets>
- SEC Form 13F Data Sets: <https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets>
- SEC Official List of Section 13(f) Securities: <https://www.sec.gov/divisions/investment/13flists>
- SEC EDGAR APIs: <https://www.sec.gov/search-filings/edgar-application-programming-interfaces>
- SEC fair-access guidance: <https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data>
