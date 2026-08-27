# 計畫

## 里程碑

1. Official daily resource 收斂
   - 範圍：TWSE MI_INDEX parser、descriptor、acquisition、daily transaction 與 candidate repository。
   - 驗收：同日 fixture 能以既有 owner 原子寫入並由 Resolver 選出。
   - 驗證：`pytest backend/tests/test_tw_official_daily_platform.py -q`

2. EOD lifecycle 與 health 收斂
   - 範圍：market-owned venue refresh 注入既有 EOD reconciliation；coverage checkpoint 接管 all-market health。
   - 驗收：transport、dataset advance、venue/full-market postcondition 分開；兩 venue 不再被 `max(date)` 壓成 current。
   - 驗證：`pytest backend/tests/test_eod_coverage.py backend/tests/test_market_source_health.py backend/tests/test_tw_daily_freshness.py -q`

3. Frontend authority 收尾
   - 範圍：unknown volume unit、普通／專業 K canonical indicator policy、technical snapshot mapping 與 UI。
   - 驗收：unknown unit 不除以 1000；canonical missing/mismatch 為 null；finalized/provisional 分區。
   - 驗證：`npm run lint`、`npx tsc --noEmit`、`npm run build`

4. Freeze gate
   - 範圍：architecture guard、targeted TW regressions、diff review。
   - 驗收：沒有新增 undeclared architecture debt，session-close 與 existing TW lifecycle tests 無 regression。
   - 驗證：`python scripts/check-architecture.py` 與最小相關 safe-validation profile。

5. 隔日 catch-up temporal 修正
   - 範圍：既有 EOD release guard、deferred retry、scheduler request date 與 post-release quote projection。
   - 驗收：已發布 historical session 可立即 repair；same-day 15:15 guard 保留；provider backoff 保留；queued job 使用 pinned expected date；released-but-missing 不再標 pending。
   - 驗證：`pytest backend/tests/test_eod_coverage.py backend/tests/test_eod_coverage_scheduler.py backend/tests/test_tw_quote_depth_shared_projection.py -q`

6. Runtime-discovered outward gap 收斂
   - 範圍：full-market provider route bound、presentation-session intraday range、跨 session 的 close finalization、前端 headline atomicity。
   - 驗收：TWSE／TPEx universe 不被 500-symbol typed contract 截斷；08:00 前「今日」讀前一展示交易日；合法 13:30 candidate 在 13:33 後跨午夜仍是 session final；價格與漲跌不跨 evidence 混用。
   - 驗證：provider catalog／official daily／intraday／public quote targeted pytest、AI／quote regression、frontend lint／typecheck／focused Playwright contract、architecture guard。

## Stop-and-fix 規則

- 任一 parser／transaction／Resolver test 失敗，先修正，不能用 legacy source 或 frontend fallback 隱藏。
- coverage 未達 full-market postcondition 時保持 partial/error，不將 provider HTTP success 當產品成功。
- 若 MI_INDEX schema 無法穩定識別 exact daily table，停止 promotion 並保留 raw receipt／parse failure。
- 若前端 backend-authoritative policy 影響非 TW consumer，改為 explicit caller policy，不做全域禁止。

## 決策

- 2026-08-27：保留 15:15 official release 與 13:33 session final 兩層語意。
- 2026-08-27：同日 `MI_INDEX ALLBUT0999` 與 D+1 `STOCK_DAY_ALL` 都屬 TWSE official daily resource，由既有 planner 排序；consumer 不看 provider-specific payload。
- 2026-08-27：不建立新 scheduler；EOD job 注入 market-owned official venue refresh，既有 coverage checkpoint 保持 postcondition owner。
- 2026-08-28：不新增 catch-up owner；修正既有 release policy 對 pinned historical date 的判定，並只讓 `release_guard` deferred 在 eligibility 改變時重算。
- 2026-08-28：不新增 session-close service 或 presentation clock；沿用 provider catalog、Taiwan presentation session、public quote platform 與既有 frontend projection seam 修正 outward gap。
