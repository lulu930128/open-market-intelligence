# M8 最終收尾報告

## 結論

M8 已於 2026-08-01 完成。一般產業 `ci` 財務流程已具備全市場 query-only
分類、bounded official ingestion、immutable parser lineage、exact-hash review、
reviewed production promotion、idempotency、資料完整性與 API／AI／MCP／frontend
一致性證據。

這個結論不等於全市場 1,928 檔都完成正規化。最終 manifest 有 5 檔
`normalized_ready`，其餘 1,923 檔為 `missing_official_filings`，不得用 legacy/raw
YTD EPS 自行相加成單季或 TTM。

## Production canary

| 股票 | Report scope | Normalized | TTM EPS | PE TTM | 價格判定 |
|---|---|---|---:|---|---|
| 2324 | C／AI1 | ready | 1.33 | unavailable | 2026-07-17，落後 expected 2026-07-31 |
| 3528 | A／AI2 | ready | 3.11 | unavailable | 2026-05-12，落後 expected 2026-07-31 |
| 5902 | C／AI1 | ready | 2.16 | unavailable | 2026-05-12，落後 expected 2026-07-31 |

三檔各新增 7 個 normalized facts；重套 package 均為 0 create／7 reuse。三檔
valuation 都輸出 `valuation_price_expected_close_stale`，沒有將正確 TTM 與過期
價格組合成可用 PE。

## 不可變證據

- Production backup：
  `data/backups/open_market_intelligence-before-m8-ci-canary-20260801-151400.db`
- Backup SHA-256：
  `5195a3ecff894b2237edd8a8aca391362ca2b73bed524f897a29a013805cfac1`
- Backup size：13,144,727,552 bytes；full `integrity_check=ok`。
- Production ingestion：21／21 requests、15 filings、15 parser v4 runs、390 facts。
- Parse runs：3920–3934；append-only approval events：3925–3939。
- Canonical package hashes：
  - 2324：`a1c46783b3b0bcfff5362a708575bf54471e90d5bff62aa8d45bbe9cd24b88c1`
  - 3528：`49def746792cdea8f497981b2addd849379db0560212f4fde549a3353b01279e`
  - 5902：`0a803080301f6246fc43f87aac92545954400f7cba38526234b02c509314501c`

## 最終 DB 狀態

- Alembic revision：`20260731_0049`
- `tw_financial_filing`：3,921
- `tw_financial_parse_run`：3,934
- `tw_financial_parse_run_review`：3,939
- `tw_financial_statement_fact`：39,312
- `tw_financial_normalized_fact`：56
- `financial_metric_quarterly`：3,883
- `PRAGMA quick_check`：`ok`
- `PRAGMA foreign_key_check`：0 violations

## Public runtime 證據

- Formal launcher 重新啟動 backend `8400` 與 frontend `3000`；health、readyz 與
  frontend proxy 均成功。
- 三檔 HTTP `omi.decision.v4` 均為 completed／ready，financial capability 為
  available／complete，projection 未截斷且 required payload 保留。
- Repo stdio MCP 完成 protocol `2025-06-18` 的
  `initialize -> tools/list -> tools/call(omi.ask)`；public tools 僅
  `omi.ask`／`omi.ask_stream`，schema 只接受 v4，5902 call `isError=false`。
- Frontend 2324 盈餘面板顯示來源揭露 EPS 不可相加、正規化單季 EPS、TTM
  EPS 1.33，以及因 stale close 顯示「待有效價格」。

## 營運邊界

後續增加 coverage 時必須使用明示 symbols／periods、provider-call ceiling、單檔
transaction、persistent audit output、exact-hash review 與 reviewed promotion。
不能在 GET/read path 或單一無界批次抓取 1,923 檔；公司行動、重編、report
scope conflict 與會計基礎轉換繼續進 exception queue。
