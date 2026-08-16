# Capability Contract

## 1. Product contract

| 項目 | Form 4 first | 13F full market |
|---|---|---|
| Research meaning | 內部人已申報交易與申報後數量 | 機構投資經理季度申報持倉 |
| Canonical target | issuer CIK + accession + reporting owner CIK | report quarter + manager CIK + accession + CUSIP |
| Primary source | SEC ownership XML；官方 Insider Transactions quarterly data sets 用於 bootstrap/audit | SEC Form 13F quarterly data sets；Official 13(f) list 用於 security reference |
| Time semantics | transaction date、filed date、accepted at 分開 | report period end、filed date、dataset release/check time 分開 |
| Freshness | latest checked filing state；通常近即時但非 real-time | quarterly；申報可能晚於期末約 45 天，不套 daily freshness |
| Refresh owner | explicit symbol/watchlist job；後續可加 bounded incremental scheduler | explicit quarter job；release checker 只 enqueue 缺少／變更季度 |
| Read path | cache-only symbol API | cache-only symbol／manager／CUSIP API |
| Main limitation | 沒有 Form 3/5 時不能宣稱完整 current position | 不涵蓋所有投資人；shared discretion/confidential treatment/mapping 會限制 aggregate 解讀 |

## 2. Layer ownership

```text
SEC archive / EDGAR XML
        |
        v
backend/app/us_market/providers/sec_ownership.py
    download/fetch only, shared SEC request policy
        |
        v
backend/app/us_market/sec_ownership/
    manifests, XML/TSV parser, semantics, amendments, CUSIP mapping
        |
        v
backend/app/us_market/ownership_store.py
    staging, append-only filing rows, upsert, projection transaction
        |
        v
backend/app/us_market/ownership_service.py
    bounded jobs, checkpoints, freshness, symbol/manager queries
        |
        +--> backend/app/us_market/source_health.py
        +--> backend/app/ai/market_context/us_context.py
        +--> backend/app/routers/us_market.py
                         |
                         +--> frontend / MCP / Kuro
```

- Provider/parser 不 import SQLAlchemy session。
- Router 不解析 XML/TSV、不下載 ZIP、不持有 ingestion transaction。
- Frontend/AI 不自行重算 amendment、CUSIP mapping、transaction code 或 13F QoQ comparability。

## 3. Local archive contract

預設 root 使用 configurable path，例如 `data/cache/us_sec/ownership/`，且必須在 `.gitignore` 中。實作時不硬編碼使用者機器路徑。

```text
ownership/
  manifests/
    insider-transactions.json
    form-13f.json
    section-13f-list.json
  archives/
    insider-transactions/<year>q<quarter>/<sha256>.zip
    form-13f/<year>q<quarter>/<sha256>.zip
    section-13f-list/<release-date>/<sha256>.<ext>
  staging/
    <job-id>/...
```

- Download 先寫 `.part`，完成 size/content-type/ZIP integrity/SHA-256 驗證後 atomic rename。
- Extract 防 zip-slip；拒絕 absolute path、`..`、symlink、過多 entries 與超過 configured uncompressed-size limit。
- 成功後移除 staging；source ZIP、manifest、hash、ETag/Last-Modified（若有）與 source URL 保留。
- 相同 release/hash rerun 不重複 parse；同季度 source hash 改變時建立新 release version，不 silent overwrite。

## 4. Shared ingestion metadata

### `us_sec_dataset_release`

- `id`
- `dataset_code`: `insider_transactions`、`form_13f`、`section_13f_list`
- `period_key`: `2026Q2` 或 release date
- `source_url`
- `source_sha256`
- `source_size_bytes`
- `published_at`／`checked_at`／`downloaded_at`
- `schema_version`／`parser_version`
- `status`: `discovered|downloaded|staged|completed|partial|failed|superseded`
- `source_row_counts_json`
- `persisted_row_counts_json`
- `quarantined_row_counts_json`
- `error_summary`
- timestamps

Unique: `(dataset_code, period_key, source_sha256)`。

### `us_sec_ingestion_checkpoint`

- `dataset_release_id`
- `stage_code`
- `partition_key`
- `cursor_value`
- `processed_count`／`error_count`
- `status`
- `started_at`／`completed_at`／`updated_at`

Unique: `(dataset_release_id, stage_code, partition_key)`。Checkpoint 只代表可重跑進度，不代表 release 已可見；只有 release transaction 完整完成後才切換 current projection。

## 5. Form 4 canonical model

### `us_sec_ownership_filing`

- accession number unique、form type (`4|4/A`；schema 預留 `3|3/A|5|5/A`)
- issuer CIK/name/trading symbol
- period of report、filed date、accepted at
- amendment flag、amendment description、deterministic supersession link（若可判定）
- source URL、source SHA-256、dataset release id、parser version、fetched at

### `us_sec_reporting_owner`

- reporting owner CIK unique、name、latest normalized name、source lineage

### `us_sec_filing_reporting_owner`

- filing id + owner id unique
- director/officer/ten-percent/other flags、officer title、other text

### Transaction/holding rows

- `us_sec_nonderivative_transaction`
- `us_sec_derivative_transaction`
- `us_sec_ownership_holding`
- `us_sec_ownership_footnote`

每列至少保留：

- accession + source table + source row sequence/raw row hash
- security title、underlying title/shares（如適用）
- transaction date、deemed execution date（如有）
- transaction code、form type、equity swap flag
- acquired/disposed、shares、price、post-transaction amount
- direct/indirect ownership、nature of indirect ownership
- exercise/conversion price、exercise date、expiration date（derivative）
- 10b5-1 flag（來源有揭露時）、footnote references
- canonical Decimal text、raw text、issue codes

Unique 優先使用 SEC dataset stable ids；沒有 stable id 時使用 `(accession, source_table, source_row_sequence, raw_row_hash)`。不得以相同日期/股數/價格去重，因為真實 filing 可存在外觀相同的多筆交易。

## 6. Form 4 semantics

- `P`/`S` 可投影為 open-market purchase/sale；其他 transaction code 保留獨立 category。
- `A`/`D` 是 acquired/disposed direction，不等同 market buy/sell。
- `F`、`G`、`M`、award/vesting、derivative conversion、indirect ownership 不併入「公開市場淨買賣」。
- `4/A` 原 filing 保留；只有 deterministic selector 可把 amendment 標為 current。無法確定 supersession 時 status=`disputed`，不自行刪除疑似重複列。
- `shares_owned_following_transaction` 是該 row 所申報的 after-transaction amount，不必然等於 reporting owner 的完整跨證券 current position。
- Form 4 first 階段的頁面標題可為「內部人交易」，不能標「完整內部人持股」。加入 Form 3/5 並完成 position reconstruction 前，summary 必須帶 limitation。

## 7. 13F canonical model

### `us_sec_13f_manager`

- manager CIK unique、filing manager name/address、latest source lineage

### `us_sec_13f_filing`

- accession unique、manager id、submission type
- report calendar/quarter、filed date、accepted at
- amendment number/type、is restatement、other-included-manager count
- information table entry count/value（raw reported）
- confidential treatment／notice-only flags、source release/version

### `us_sec_13f_other_manager`

- filing id + sequence/name/CIK/form13f file number

### `us_sec_13f_holding`

- filing id + source row sequence/raw row hash
- issuer name、class title、normalized CUSIP
- raw reported value + documented value scale、shares/principal amount/type
- put/call、investment discretion、other-manager refs
- voting authority sole/shared/none
- raw text、issue codes、source release/version

Canonical holdings 不存 mutable ticker truth。Unique 使用官方 stable id；否則 `(filing_id, source_row_sequence, raw_row_hash)`。

### `us_security_identifier_map`

- identifier type/value（首版 `cusip`）
- symbol、issuer CIK、security class
- mapping source、source release id、confidence/status
- valid from/to、mapping version、manual override flag、evidence JSON

只有 exact/approved mapping 能進 production symbol projection。Name-only fuzzy match 可作 review candidate，不可自動標 ready。

### `us_sec_13f_symbol_quarter`

Materialized、可重建 projection，至少包含：

- symbol、issuer CIK、report quarter、mapping version、source release id
- reporting manager count、reported row count
- reported long shares/value、put/call 分組值
- comparable prior-quarter counts/changes
- new/increased/reduced/exited manager counts（僅同 manager + 同 security identity 可比較）
- mapping row/value coverage、unresolved rows/value
- aggregate limitations/status

Shared investment discretion 可能造成 aggregate double count，因此欄位命名使用 `reported_*`；未有可信 dedup policy 前不輸出精確「機構持股比例」。

## 8. Amendment and comparability policy

- `13F-HR/A` 與 `4/A` 永遠 append-only 保存。
- Current view 只在同 manager/issuer、同 report period、同 filing family 且 amendment metadata 足以判定時選 latest effective filing。
- `13F-NT` 是 notice，不等於零持倉；status=`notice_only`，不得建立 empty holding projection。
- QoQ 只比較相鄰 report periods、同 manager identity、同 normalized CUSIP/security class、相同 put/call 與 shares/principal basis。
- 缺前季、manager identity 改變、CUSIP remap、amendment dispute 或 confidential treatment 時，change status 必須 partial/blocked。

## 9. Freshness and status

### Form 4

- `current`: latest check/sync 成功且在 configured 24-hour observation window 內。
- `ready_empty`: 已成功檢查 issuer 且該 bounded period 沒有 Form 4。
- `stale`: 有 local rows，但 latest successful check 超過 observation window。
- `partial`: 有 rows，但部分 filing/transaction/quarantine/schema issue 未解決。
- `missing`: 尚未成功檢查或沒有 local snapshot。
- `blocked`: issuer CIK 缺失、provider blocked 或 contract 無法安全投影。

### 13F

- Freshness basis 是 latest expected official quarter/release，不是美股交易日。
- `current`: latest expected official release completed 且 current projection 指向其 hash/version。
- `ready_empty`: symbol mapping 已完成但該季度沒有持倉 rows。
- `partial`: release 完成但 confidential treatment、quarantine、mapping/aggregation limitation 影響 requested view。
- `stale`: 官方已有較新 expected release，而 local latest completed release 較舊。
- `missing`: requested quarter 未匯入。
- `blocked`: source archive invalid、capacity/mapping gate 未通過或 projection 無法安全建立。

Source health 分開報告 transport、archive integrity、parse completeness、mapping coverage、projection freshness；HTTP 200 不代表 dataset ready。

## 10. Refresh and job contract

### Form 4 jobs

- Job type: `us_market.sec_form4_sync`
- Request scope: `symbol|watchlist|all_known_issuers`；首版 production route只開放 `symbol|watchlist`。
- Bounds: `from_date`/`to_date`、max symbols、max filings、timeout、concurrency=1 for SEC ownership sync。
- Historical bootstrap 使用 official quarterly Insider Transactions data set，一季一 job；recent incremental 使用 issuer filing metadata/XML。

### 13F jobs

- Job type: `us_market.sec_13f_quarter_sync`
- 一個 job 一個 quarter/release；batch coordinator 只 enqueue 缺少的單季 jobs。
- Request: `quarter`, `force=false`, `mode=discover|download|ingest|rebuild_projection`。
- 每個 stage 記 progress/checkpoint；retry 從安全 checkpoint 繼續。
- 同 dataset+quarter 用 DB/advisory lock 防重複；不同季度首版仍 serial，經容量證明後才允許 bounded parallelism。

### Scheduler

- Scheduler 只檢查 expected release window 與 manifest；沒有新 hash 不啟動 ingestion。
- 不輪詢 SEC 即時 filing feed；Form 4 增量頻率先採 daily bounded window，之後用實測需求決定是否縮短。

## 11. Public API contract

Routes 全部 additive，實作前以 Pydantic schema 與 OpenAPI inventory test 固定。

### Read routes

- `GET /api/us-market/sec/{symbol}/insider-transactions`
  - bounded `from_date`, `to_date`, `codes`, `include_derivatives`, `limit<=200`, `cursor`
  - 回傳 `omi.sec.insiders.v1`、summary、rows、freshness、quality、source refs、limitations
- `GET /api/us-market/sec/{symbol}/institutional-holdings`
  - `quarter=latest`, `compare_quarters=2..8`, `limit<=100`, `cursor`
  - 回傳 `omi.sec.13f.v1`、current/prior quarter、top managers、changes、mapping coverage、limitations
- `GET /api/us-market/sec/13f/managers/{manager_cik}/holdings`
  - bounded quarter/limit/cursor；保留 CUSIP-native rows
- `GET /api/us-market/sec/ownership/coverage`
  - dataset/quarter/release/hash/counts/status/storage/mapping coverage

### Mutation routes

- `POST /api/us-market/sec/ownership/jobs/form4-sync`
- `POST /api/us-market/sec/ownership/jobs/13f-quarter-sync`
- `POST /api/us-market/sec/ownership/jobs/13f-backfill`

Mutation route 只 enqueue tracked job 並回 202；job result 使用 compact summary，避免把全市場 rows 塞進 `JobRun.result_json`。

## 12. AI and consumer contract

- 新增 market-neutral capability ids：`ownership.insider_transactions`、`ownership.institutional_holdings`。
- Compact evidence 只含 bounded summary/top rows/source refs/status，不含 raw XML、全 manager list 或全季度 table。
- AI limitation 固定包含：Form 4 reporting scope、13F quarter/reporting lag、mapping/confidential/shared-discretion limits。
- 問「今天法人買賣」時，不可用 13F 冒充即時 flow；問 insider buy 時只把 `P` 類公開市場買進當相符 evidence，其餘 code 分開說明。
- Frontend 使用現有「內部人」「機構」tab；refresh/error 進共享 JobStatusCenter／更新狀態，不新增孤立 error banner。
- MCP/Kuro 維持 thin consumer，只呼叫 backend API/AI answer contract。

## 13. Capacity and mapping gates

最近兩季 full-market pilot 必須產生：

- source ZIP/compressed/uncompressed size
- source/persisted/quarantined rows
- DB table/index bytes before/after（可量測範圍內）
- peak parser memory與 elapsed time
- latest symbol query warm-cache p50/p95
- CUSIP→symbol mapped rows/value coverage
- projected full-history storage與 backfill duration

Gate defaults：

- query warm-cache p95 <= 1 second under bounded latest-symbol request；
- mapping coverage >= 90% rows and >= 95% reported value before symbol-level `ready`；
- projected footprint 不超過 configured storage budget，且完成下載前保留 archive + staging + DB growth 的安全空間。

Gate 未通過時，CUSIP-native warehouse仍可完成，但 symbol projection 必須 partial/blocked，並觸發 Prompt 中的 major-decision stop。

## 14. Validation matrix

| Layer | Required proof |
|---|---|
| Provider/archive | headers, timeout, size bounds, ZIP integrity, hash, retry, 403/429, zip-slip |
| Parser | official-shaped fixtures, malformed rows, Decimal, encoding, schema drift, all semantic variants |
| Store/migration | empty DB upgrade, populated DB upgrade, downgrade where safe, unique/idempotent, rollback, indexes |
| Jobs | progress, checkpoint, retry, cancel/restart, concurrency lock, partial failure isolation |
| Reconciliation | source rows = persisted + quarantined + explicitly skipped, by table/quarter |
| Freshness | ready_empty/missing/partial/stale/blocked and expected-quarter rules |
| API | Pydantic/OpenAPI invariants, cursor/limit/date validation, GET no external IO |
| AI | bounded compact slots, source refs, data limits, no daily-flow conflation |
| Frontend | loading/empty/partial/stale, keyboard tabs, 390px/desktop, no overflow, shared update status |
| Runtime | launcher-owned processes, migration head, representative API/UI behavior, provider/source health |
