# Progress

## Status

- Current phase：source closure與local runtime acceptance完成；等待使用者external audit。
- Last updated：2026-08-23 23:40 Asia/Taipei。
- Authorization：使用者要求繼續製作並解決已確認問題；包含source、tests、正式OMI runtime restart與本機HTTP／MCP acceptance。仍不含external quota refresh、KGI login、DB migration、commit、push或release。

## Completed

- 讀取current product／architecture truth、兩塊既有task docs、closure audit與相關source／tests。
- Live backend health確認runtime可用，但effective canonical mode為`off`。
- Live cache-only HTTP與MCP重現5m wiring mismatch及after-hours zero-volume被錯標available。
- AAPL resolved daily research確認facts usable、corporate-action completeness unknown、decision blocked；full-market coverage gate未過。
- 建立closure capability contract、milestones、stop-and-fix rules與external gate boundary。
- C0 contract correctness：
  - requested intraday interval已從HTTP／AI／agentic plan一路傳到US reader；supported intervals會由1m source正確聚合。
  - Yahoo extended-hours zero-filled volume改為`null/provider_unavailable`；聚合只要有缺量即保持partial，不再用部分總和假裝完整。
  - 加入versioned US early-close dates、13:00 close、17:00 post-market close與13:05 daily release；session與finalization改用dynamic calendar helper。
- C1 Resolver／provider ownership：
  - provider descriptor加入session eligibility；不支援的session以`SESSION_NOT_SUPPORTED_BY_PROVIDER` fail closed。
  - US daily provider priority收斂到單一policy owner；fetch、source health、chart projection與Resolver使用同一順序。
  - resolved evidence outward新增`selected_session`，candidate保留session。
  - Research改走stable cache-only resolved read seam，不再直接依賴private store／canary builder。
  - Watchlist Ranking與Technical Radar改走同一resolved/raw seam，不再以latest fetched row或`adjusted_close`自行選provider／price basis。
  - Watchlist resolved read採最多500 symbols的batch query、按requested bars計算lookback，避免逐檔N+1；outward明示provider、source、session、selection reason、fallback與`raw_unadjusted` basis。
- C2 selection-bounded consumer：
  - explicit capability selection會傳入US context；intraday-only不再讀SEC、profile、ownership、corporate action、short volume或full-market coverage。
  - technical research可跳過無關market coverage，避免supplemental缺口污染selected answer。
- C3 rollout：
  - US專用mode支援`off -> shadow -> compare -> canary -> on`，不擴張TW global mode contract。
  - `canary`由symbol allowlist與max-symbol bound限制；未通過parity不附加Canonical selected result。
  - 本機ignored `.env.runtime`保存`US_CANONICAL_MARKET_DATA_MODE=canary`、`AAPL` allowlist與max=5；`.env.example`提供可追蹤說明。
- 正式launcher已連續執行兩次`RestartServices`；兩次後backend均在`127.0.0.1:8400`、frontend在`127.0.0.1:3000`，US mode保持`canary`，global mode保持`off`。
- Rollback已實測：`canary -> off`重啟後US enabled=false；再`off -> canary`重啟後恢復AAPL symbol count=1、max=5，health／ready正常。
- Runtime cache-only AAPL context已回傳Canonical daily `selected`：`yahoo_chart`／`yahoo.chart.1d`／session=`closed`／interval=`1d`／fallback=false／260 bars。

## Validation evidence

- Pre-change targeted baseline：101 passed，19 subtests passed。
- MCP stdio baseline：initialize／tools-list／tools-call成功；5m仍effective 1m，extended volume仍錯標available。
- C0 targeted：206 passed，3 subtests passed。
- C1 provider／Resolver targeted：92 passed。
- Rollout／shadow／outward targeted：103 passed。
- Integrated closure regression：290 passed，3 subtests passed。
- Python compile／changed module `py_compile`：passed。
- Backend general regression（排除下面兩個已隔離gate）：2076 passed，1 deselected，578 subtests passed。
- `scripts/run-safe-validation.ps1 -Profile backend`的測試本體跑到100%，但pytest清理sandbox temp時因`PermissionError`讓wrapper exit 1；不是產品assertion failure。
- 原始full suite另隔離：
  - `test_market_data_v2_dark_boundary.py`：既有MDF checkpoint／public snapshot與目前dirty worktree不一致；不在本輪盲目重寫baseline。
  - `test_runtime_launcher_recovery.py::test_service_runner_classifies_backend_bind_failure_without_retry`：sandbox拒絕child PowerShell存取pytest temp；正式launcher restart則已成功兩次。
- Runtime health／readyz：`ok`／`ready`；US `canary` enabled=true，symbol count=1，max=5；global=`off`。
- Runtime rollback／restore：`off` disabled與`canary` restored均由official launcher restart驗證。
- Runtime HTTP cache-only AAPL resolved daily：status=`selected`、selected session=`closed`、facts／research usable=true。
- Runtime public Watchlist Ranking（376 symbols）：8.5秒內完成；353 ranked。AAPL=`yahoo_chart`／`yahoo.chart.1d`／`closed`／`raw_unadjusted`／fallback=false。
- MCP stdio：protocol `2025-06-18`、3 tools、`omi.ask` present；frontend HTTP 200。
- `git diff --check`：exit 0；只有既存LF／CRLF提示。

## Decisions made

- Interval、volume、early close、session/Resolver、stable read seam、selection-bounded workload與rollout是本輪code closure範圍。
- Corporate-action completeness、full-market universe、KGI US live與外部provider資料缺口保持獨立blocked gate。
- 不改DB schema；優先additive contract與cache-only read seam。
- Yahoo仍是US daily auto priority；AlphaVantage只在Yahoo失敗且compact/key允許時fallback，Resolver/read端使用相同優先序。
- Early-close採explicit versioned registry，避免把未驗證未來日期當成永久calendar truth。

## Known issues / risks

- Worktree包含大量使用者既有modified／untracked檔案；本輪只修改closure ownership map中的檔案。
- US Foundation檔案多數仍未納入Git追蹤；使用者未要求commit／push。
- KGI US entitlement／live sample仍未驗證；不可宣稱KGI provider已ready或adopted。
- Corporate-action completeness仍是`unknown`，所以技術facts可用不等於decision可用。
- Full-market expected universe與分類有效日期未證明，full-market readiness仍為false。
- 本輪沒有做外部refresh；source-health的stale／empty狀態不因source closure自動消失。
- `canary`目前只開AAPL；未經external audit不升`on`、不擴大allowlist。
- 全376檔Ranking已從超過30秒timeout降至約8.5秒；correctness與bounded query已成立，但大清單延遲仍可在後續以cache snapshot／索引做非阻塞優化。

## Rollback

1. 將本機`.env.runtime`的`US_CANONICAL_MARKET_DATA_MODE`改為`off`。
2. 透過official launcher執行`RestartServices`。
3. 驗證`/api/system/health`的`runtime.us_canonical_market_data_mode=off`且`runtime.us_canonical_market_data_enabled=false`。
4. 不需要DB migration或資料回滾；`off`會停止Canonical outward adoption，legacy path保持可用。

## Next step

- 由使用者進行external audit；優先檢查AAPL 5m／extended-hours volume outward、corporate-action coverage、source-health與KGI US entitlement。任何external gate未過時保持`canary`，不升`on`。
