# Progress

## Status

- Current phase: Stage 0–12 complete；Form 4 與 13F production runtime 已採用，CUSIP→ticker 全市場 mapping 維持 explicit partial
- Last updated: 2026-08-12 +08:00
- Runtime adoption: launcher-owned Backend `8400` / Frontend `3000` 已採用 Form 4、`omi.sec.13f.v1` 與 Parquet v3

## Completed

- 完成 Form 4 v1 pure parser、append-only canonical store、migration、bounded tracked job、freshness/source health、`omi.sec.insiders.v1` API、AI capability 與新版「內部人」頁。
- 正式 runtime 已用 AAPL bounded job 驗證：5 filings、13 transactions、2 positions，GET contract=`omi.sec.insiders.v1`、source health=`current`，來源可追到 SEC accession/XML。
- Frontend desktop 與 390px browser proof 通過；390px `scrollWidth=innerWidth=390`，交易 rows 切為 cards，console 無 error/warning。
- 完成 Stage 7 safe ZIP inventory、zip-slip/oversize fail-closed、UTF-8 TSV streaming parser 與兩個最新完整 SEC 13F releases 的 full-row capacity pilot。
- 兩季實測 7,296,094 holdings；indexed pilot SQLite 1,414,598,656 bytes；Python tracemalloc peak 6,115,517 bytes；完整掃描/索引 324.429 秒。
- 產出 `CapacityReport.json` 與 `CapacityReport.md`；pilot 曾命中 storage/mapping stop gate，經使用者同意後改採 Parquet/DuckDB analytical warehouse，沒有把 120M holdings 塞進 SQLite。
- 完成 Stage 8–9：migration `0059`–`0062`、一季一 release 的 atomic ingest/checkpoint、manager/filing/other-manager metadata、versioned identifier mapping、symbol-quarter materialized projection、coverage 與 bounded symbol API。
- 完成 Stage 11：從 SEC 官方 manifest 匯入目前公開的 53 個 datasets（2013Q2–2026Q1），53/53 completed、0 pending；120,182,194 source holdings 全數對帳為 119,996,888 canonical + 185,306 invalid-CUSIP quarantine，invalid reported value 為 0。
- Warehouse schema=`omi.sec.13f.parquet.v3`，53 partitions 共 7,616,887,777 bytes，低於 32 GiB guard；full hash verifier 與 no-op idempotency rerun 通過。
- 完成 Stage 10：AI 將 13F 定位為 `delayed_quarterly_context_only` 且不納入 decision score；frontend「機構」頁接上 `omi.sec.13f.v1`、shared 更新狀態與三語文案。
- AAPL 已有 approved mapping 與 53 季 projection；最新 2026Q1 顯示 6,037 家申報機構、8,983 rows、9,356,512,110 股與 $2,262,529,531,862 reported long value。
- Stage 12 runtime proof：新版 launcher 回傳 Parquet v3、manifest 53/53、AAPL source health=`current`；桌面 1280px 與手機 390px 實際 browser proof 通過，13F 表格使用局部水平捲動，console 無 error。

- 確認既有US SEC financial engine Stage 0–8已完成，`omi.financial.v1`、SEC request policy、Submissions cache、source health、tracked jobs與新版六頁籤可作為ownership基座。
- 確認目前「機構」「內部人」tab只有explicit empty state，repo尚無13F/Form 4 ingestion或DB tables。
- 將使用者決策固定為：Form 4 first；13F採全市場，不採watchlist-only。
- 完成`Prompt.md`、`CapabilityContract.md`與`Plan.md`，定義canonical identity、migration、archive、jobs、freshness、API、AI、frontend、capacity與stop conditions。

## Decisions made

- Form 4 v1只宣稱已申報transactions/after-transaction amount；Form 3/5未完成前不宣稱完整current insider holdings。
- 13F full-market completeness以CUSIP-native source rows為準，symbol mapping另行量測與版本化。
- 13F先完成最近兩季full-row pilot，再用一季一job回補全部SEC公開歷史。
- 13F production storage 採 compressed Parquet partition + DuckDB query；SQLite 只保存 release/checkpoint/mapping/materialized symbol projection metadata。
- 非 9 碼 legacy identifier 保留 `cusip_raw_text` 與 issue code，canonical `cusip` 留空；不補字、不猜 CUSIP。
- 全市場 source completeness 與 ticker usability 分開：AAPL 可 current，但 coverage contract 在 mapping 未完成前維持 `partial`。
- SEC raw archives/configured cache與SQLite資料都維持local-only、excluded from Git；GET/read path不得下載或解析。
- 若mapping、storage或query performance未達明確gate，視為重大決議，不以silent partial掩蓋。

## Validation evidence

- Form 4 focused backend regression：`336 passed, 1 warning, 87 subtests passed`。
- AI contract regression：`155 passed, 27 subtests passed`。
- Frontend：typecheck、lint、production build 全部通過。
- 13F archive/parser targeted tests：`3 passed`；兩季官方 ZIP CRC/hash/inventory、source-table row counts、Decimal value 與獨立 pilot SQLite 全量 proof 完成。
- SEC 13F 官方資料集與證券清單於 2026-08-12 重新 live verification；原始 archive SHA-256、各 table counts 與容量明細保存在 `CapacityReport.json`。
- 13F full-history verifier：`--require-full-history --verify-hashes` 通過，issues=`[]`、53/53、120,182,194 rows 完整 reconciliation。
- Final SEC/ownership/US/AI/API focused regression：`305 passed, 166 subtests passed`；migration head=`0062`。
- Frontend final：lint、TypeScript no-emit 與 Next.js 16.2.12 production build 通過；runtime UI/API/browser proof 通過。

- Read-only inspection：既有SEC provider/policy/service/source-health/router、job system、US models/Alembic、US frontend workspace、product/architecture與parent task docs。
- Official source baseline已列入`Prompt.md`，implementation開始前仍需對實際release URL/schema再做一次live verification。
- 本輪僅建立docs；尚未執行migration、download、external refresh、runtime restart或DB write。

## Known issues / risks

- 已解決的 storage gate：Parquet v3 全歷史實際使用約 7.1 GiB，32 GiB guard 仍有 headroom；不再使用 pilot SQLite amplification 推估作 production storage。
- 已完成全市場 lookup，但官方 Section 13(f) source 仍以 CUSIP 為主，OpenFIGI 也無法唯一核准所有歷史 identifier；coverage/API/UI 因 74.2606% row coverage 正確維持 `partial`。
- 本機已設定 `OPENFIGI_API_KEY` 並完成 bounded authenticated jobs；ambiguous、unverified、unmapped 結果不得以 fuzzy issuer-name 或 frontend 推導改標 approved。
- Runtime adoption 時發現：直接終止 launcher PID 後，service runner 消失但 listener child 未在 20 秒內自行退出；本次已依確切 port owner/PID 清理並由新 launcher 接管。這是既有 launcher orphan-cleanup follow-up，不影響 SEC contract，但不應宣稱已修復。

- SEC官方13F資料以CUSIP為核心，現有`us_stock_master`沒有CUSIP；symbol projection completeness取決於versioned identifier mapping。
- 全部歷史13F的實際SQLite/index footprint未知，不能用ZIP壓縮大小推估；Stage 7必須先量測最近兩季。
- Form 4交易語意複雜，gift、tax withholding、option/derivative、amendment與multi-owner若簡化會造成錯誤研究結論。
- 現有worktree有大量既有變更；implementation必須逐檔確認ownership diff，不覆蓋其他工作。

## Next step

- 核心 ingestion、全歷史、全市場 mapping inventory、API、AI、frontend 與 runtime adoption 已完成。後續只需依新 SEC release 做增量 ingestion/mapping，並持續保留 source-complete、symbol-partial 的真實邊界。

## 2026-08-13 full-market mapping closure

- `OPENFIGI_API_KEY` 只設定於本機 ignored `.env`；key value 未寫入 repository 文件、fixture 或 log。
- 138,869 個 canonical CUSIP 全數經 authenticated tracked jobs 處理；production lookup 沒有 provider error，也未實際觸發 retry。
- `openfigi.v3` 結果為 approved 10,927、ambiguous 2,672、unverified 14,648、unmapped 110,622。這代表 lookup inventory 完整，不代表 100% ticker approval。
- 最終 zero-pending job 5595 成功完成，materialize 252,796 個 symbol-quarter rows、10,650 個 symbols。
- Warehouse mapping coverage 為 89,248,002 / 120,182,194 rows（74.2606%），reported-value coverage 74.0251%。Contract 正確維持 `partial`，所有 unresolved identifier 仍可見。
- Full rebuild 已改為 1.5 GiB DuckDB query limit + disk spill、串流 grouped rows、JSONL shadow artifact 與最後 atomic SQLite bulk replace；成功 run 不再出現舊路徑 10–16 GiB 的無界記憶體增長。
- Runtime proof：AAPL、MSFT、NVDA 各回傳 53 季且 `decision_usable=true`；warm API reads 為 15–46 ms。Source health 正確顯示 `sec_institutional_holdings=partial`，無 provider error。
- Operational capacity：shadow artifact 約 5.8 GiB；完成後本機 SQLite 約 20.43 GiB。Rebuild 仍是 explicit tracked maintenance job，永不由 GET/read path 觸發。
