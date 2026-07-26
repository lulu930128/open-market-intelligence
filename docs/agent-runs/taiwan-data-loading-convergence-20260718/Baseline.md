# Baseline

## Snapshot

- Captured：2026-07-18，Asia/Taipei。
- Runtime：frontend `127.0.0.1:3000`，backend `127.0.0.1:8400`。
- Runtime health：backend readiness/health、frontend proxy 均正常。
- Focus：台股首頁、2330 個股工作台、watchlist group 3、K 線、Radar/ranking、法人／籌碼。
- 注意：以下數字是單機診斷基線，不是跨硬體 SLA；後續 benchmark 必須使用相同 probe 與記錄 runtime mode。

## Confirmed causal paths

### Initial page

```text
Next.js Server Component
  -> Promise.all: watchlists + multi-market basics + TW index summary
       -> index summary cache miss
            -> Yahoo/TPEx provider IO + coverage/fallback work
            -> provider slow/failure
       -> frontend server timeout at 20s
  -> only then load Radar + OHLC + indicators
  -> page response becomes cumulative
```

### Stock selection and data tabs

```text
select stock
  -> load local stock/chips summaries
  -> automatically start profile=basic refresh
  -> active tab defaults to chips
  -> automatically start profile=chips refresh
  -> poll job up to 600s
  -> reload cache after job

chips profile
  -> institutional + margin + broker branch + shareholding
  -> one provider failure makes composite job partial
```

### Ranking and Radar

```text
load 83-stock watchlist
  -> serialized ranking batches of 3 (~28 requests)
  -> queue Radar calculation
  -> after initial ranking, automatically start group refresh
  -> 83 stocks x provider throttle
```

## Latency baseline

| Surface | Observed | Interpretation |
| --- | ---: | --- |
| backend readiness | ~2 ms | Runtime/DB readiness不是瓶頸 |
| index summary, warm cache | ~5 ms | Cache read 很快 |
| index summary, cold | ~5.7 s | Cold GET 包含 provider/coverage work |
| homepage SSR during failure | 21.9–24.6 s | 被 20 秒 backend timeout主導 |
| homepage SSR after warm cache | ~2.27 s | 含約 961 KB response |
| 2330 daily OHLC cache | ~8 ms | 本機 K 線讀取不是主要瓶頸 |
| 2330 indicators | ~24 ms | 本機計算可接受 |
| 2330 institutional history | ~8 ms | 法人 cache 本身很快 |
| 2330 shareholding cache | ~17 ms | 慢點在 refresh/provider |
| group 3 Radar | ~1.6–5 s | 83 檔即時計算、無 request snapshot reuse |

## Current data/freshness snapshot

| Resource | Target | Latest observed | Current interpretation |
| --- | --- | --- | --- |
| daily price | 2330 | 2026-07-17 | current |
| institutional trade | 2330 | 2026-07-17 | current |
| margin trading | 2330 | 2026-07-17 | current |
| broker branch | 2330 | 2026-07-17 | current |
| shareholding distribution | 2330 | 2026-05-29 | available but materially behind observed official dates |
| Radar group 3 | 83 requested / 83 ranked | 2026-07-17 | complete, but recalculated per request |

TDCC 官方查詢頁在 2026-07-18 可見 2026-07-17 等較新資料日期，因此 local shareholding 落後不是「上游尚未公布」的充分解釋：

- <https://www.tdcc.com.tw/portal/zh/smWeb/qryStock>

## Confirmed failure evidence

- Frontend current-session log 多次記錄：
  - `path=/api/market/indices/summary code=timeout Backend timeout after 20000ms`
- Recent TPEx index provider events：
  - `tpex_daily_trading_index`
  - `tpex_mainboard_quotes`
  - failure 發生在取得有效 HTTP response 前；現有 event 尚不足以確定是 DNS、TLS、proxy 或其他 transport cause。
- Recent TDCC shareholding job：
  - `SSLCertVerificationError`
  - `certificate verify failed: Missing Subject Key Identifier`
- Recent watchlist group refresh：
  - requested 83
  - refreshed 73
  - errors 10
  - configured sleep 5 seconds per item
- Same-day chart log曾出現：
  - `data must be asc ordered by time`
  - duplicate timestamp assertion
  - 目前 2330 daily/weekly response 未再重現 duplicate，暫列為 intermittent projection/overlay regression。

## Root-cause classification

1. Primary：backend read path 與 refresh/provider side effect 混合，讓 cache miss 變成不可預測的外部 IO。
2. Primary：frontend initial render、選股與 active-tab effects 同步等待或自動啟動昂貴 refresh。
3. Primary：refresh dedupe 只存在於 component lifecycle，無法跨 remount、reload、並發或多 consumer 保證唯一執行。
4. Secondary：Radar/ranking 缺少適合 UI read path 的 snapshot/aggregate contract。
5. Secondary：TDCC TLS 與 TPEx transport failure 使 refresh 反覆 partial/slow。
6. Separate correctness risk：chart timestamp ordering/uniqueness boundary 不夠穩固。

## Existing architecture constraints

- `docs/architecture/BackendArchitecture.md` 已規定：
  - Query/read helper 不 commit。
  - Persisted source-health GET 不隱性重算或刷新全市場資料。
  - Watchlist Radar snapshot 由 scheduler/job/service 擁有；GET read path 不隱性建立。
- `docs/product/OperatingModel.md` 已規定 read path 預設輕量，昂貴 refresh 必須有明確 policy。
- 因此本專案不是單純效能微調，而是讓現有 runtime 行為重新符合已定義的產品／架構 contract。

## Relevant implementation surfaces

- Initial SSR：`frontend/src/app/page.tsx`
- Frontend request contract：`frontend/src/lib/api.ts`、`frontend/src/lib/serverBackend.ts`
- Taiwan tape：`frontend/src/components/market-dashboard/tape/useTaiwanMarketTapeState.ts`
- Stock chart：`frontend/src/components/stock-detail/useTaiwanStockChartData.ts`
- Data tabs：`frontend/src/components/stock-detail/useTaiwanDataPanel.ts`
- Ranking：`frontend/src/components/market-dashboard/ranking/useTaiwanRankingState.ts`
- Index summary：`backend/app/market/indices.py`
- Taiwan OHLC/history：`backend/app/market/service.py`
- Radar/ranking：`backend/app/watchlists/radar_service.py`、ranking service與automation/outcome services
- Refresh jobs：selection refresh、watchlist group refresh、`backend/app/jobs/`
- TDCC shareholding：`backend/app/market/shareholding_history_backfill.py`
- Provider boundary：`backend/app/observability/provider_http.py`、`backend/app/http_client.py`

## Test surfaces already present

- API inventory：`backend/tests/test_api_contract_inventory.py`
- Index stats：`backend/tests/test_market_index_daily_stats.py`
- OHLC overlay：`backend/tests/test_ohlc_intraday_overlay.py`
- Ranking/Radar：`backend/tests/test_watchlist_ranking.py`、`test_watchlist_radar.py`、`test_watchlist_radar_automation.py`
- Provider/source health：`test_provider_http.py`、`test_provider_health.py`、`test_market_source_health.py`
- Job behavior：`backend/tests/test_job_retry.py`
- Frontend E2E mock surface：`frontend/e2e/omi-smoke.spec.ts` 已可攔截 index summary、ranking batch、selection refresh 與 group refresh。

## Baseline gaps to close first

- 尚無明確測試證明 cache-only GET 不會外呼 provider、commit 或建立 job。
- 尚無跨並發／remount 的 refresh dedupe contract test。
- 尚無首頁 provider fault 下「cache 可用仍快速可操作」的 E2E。
- 尚無 Radar warm snapshot latency/request-count contract。
- Shareholding weekly expected date 尚未充分反映在 source-health。
- Provider event 未保留足夠 low-level cause 來區分目前 TPEx transport failure。
- Chart duplicate/out-of-order regression 尚未固定重現。
