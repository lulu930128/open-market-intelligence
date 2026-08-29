# US Market Data Production Cutover Runbook

## 1. Scope and authorization

- 本文件只規劃cutover／rollback；目前沒有授權restart runtime、啟用provider、呼叫大量external API、切production mode、改DB或刪legacy。
- 真正執行時，每個capability單獨取得對應授權與call/time/symbol budget。
- 不以backend health endpoint單獨判定成功；必須驗證source identity、runtime adoption、resolved data、consumer contract與可見UI。

## 2. Rollout unit

最小rollout key：

```text
market + capability/dataset + target scope + session scope + consumer surface
```

不得以單一全域開關同時切daily、repair、intraday、API、AI與Frontend。

建議順序：

1. `us.daily.ohlcv` cache-only single symbol。
2. Daily bounded symbol set／research/watchlist read。
3. Daily explicit repair single symbol。
4. Priority research universe。
5. Full-market durable shards。
6. Quote／intraday single symbol regular session。
7. Extended-hours與early-close cases。
8. API、AI/MCP、Frontend依序切consumer。
9. Legacy removal。

## 3. Mode semantics

| Mode | New path activity | Outward owner | Required evidence | Promotion rule |
| --- | --- | --- | --- | --- |
| `off` | no new-path production execution | legacy | baseline only | contracts/tests passed |
| `shadow` | same already-fetched payload或cache做new conversion/resolution；不可新增unbounded call | legacy | no behavior change、candidate/result artifact | no errors/coherence violations |
| `compare` | legacy/new都產生結果並分類mismatch | legacy | lineage/value/status/latency/quota comparison | mismatch within declared bound |
| `canary` | bounded target由new path對外 | new for canary only | API/AI/UI/runtime + rollback proof | stability window passed |
| `on` | selected capability正式由new path擁有 | new | production evidence + monitoring | closure prerequisites met |

若repo final Core使用不同mode名稱，執行前建立明確mapping；不可因名稱相同便假設語意一致。

## 4. Universal preflight

每次升mode前必查：

- [ ] Branch、source SHA、dirty status已記錄。
- [ ] Owned files與unrelated dirty changes已隔離。
- [ ] G0已passed（B1以後）。
- [ ] Target package與依賴package在AcceptanceMatrix為passed。
- [ ] Relevant tests、safe validation profile與contract snapshots通過。
- [ ] Rollout key、symbol/session/range/call/time budget明確。
- [ ] Provider credentials/plan/entitlement只以redacted readiness判斷。
- [ ] `cache_only` no-I/O probe通過。
- [ ] DB transaction、idempotency、postcondition與restart readback已驗證（若有write）。
- [ ] Runtime official launcher、preferred/selected port與process lineage已知。
- [ ] Rollback entrypoint可執行，且不需刪資料/schema downgrade/broad-kill。
- [ ] Data Status／provider/dataset/resolved health能truthful outward。

任何一項不通過，mode不升級。

## 5. Evidence packet

每次rollout保存：

```text
rollout_id:
started_at / ended_at:
source_sha:
runtime_pid / port / mode:
capability_or_dataset:
target_scope:
session_scope:
realtime_policy:
provider_call_budget / actual_calls:
legacy_result_summary:
new_result_summary:
candidate_summary:
selected_lineage:
freshness / fallback / selection_reason / limitations:
mismatch_count / classes:
latency_p50/p95 or bounded elapsed:
db_rows_before/after/restart_readback:
consumer_checks:
rollback_probe:
decision: hold | promote | rollback
```

不得保存secret、token、完整私人payload或不必要raw response；raw receipt只保存安全reference/hash。

## 6. Comparison taxonomy

Compare mismatch至少分類：

- `value_mismatch`
- `event_time_mismatch`
- `session_mismatch`
- `finalization_mismatch`
- `price_basis_mismatch`
- `provider_selection_difference`
- `freshness_difference`
- `fallback_difference`
- `health_difference`
- `lineage_missing`
- `limitation_missing`
- `coverage_difference`
- `latency_regression`
- `unexpected_external_call`
- `unexpected_db_write`

Unknown mismatch不可自動忽略；先分類並說明是否為legacy bug、new-path bug、provider difference或expected policy change。

## 7. Daily OHLCV cutover

### Shadow/compare

- 從同一cache/candidate batch產生legacy與resolved projection，避免為compare增加provider calls。
- 比較bars count/date/OHLCV/finalization/source/fetched time/price basis/coverage。
- Corporate-action coverage未知時保留limitation與`decision_usable=false`。

### Canary

- 第一批：單一高流動symbol，cache-only read。
- 第二批：少量跨venue/symbol類型、含early-close歷史範例。
- 第三批：bounded watchlist／priority universe。
- 不在同一canary同時啟用repair與frontend technical authority。

### Promotion checks

- Query count與elapsed不超過baseline bound。
- Same requirement across chart/research/ranking/Radar得到同一selected lineage。
- Missing/partial/stale不被legacy compatibility壓平。

## 8. Repair and scheduler cutover

- 先single-symbol explicit refresh，再priority universe，最後full-market shards。
- 每次要求包含dataset ID、target/range、max calls/runtime/symbols、cursor、required coverage、postcondition。
- Job success只代表operation execution；dataset complete必須以post-write reread判斷。
- Startup catch-up與scheduled run要dedupe；同dataset/date/scope不可併發重複執行。
- Full-market沒有bulk provider時，只允許bounded、可續跑shards，不宣稱單次完成。

Rollback：disable該operation/schedule或mode回off；保留cursor/checkpoint/candidates，不清空資料。

## 9. Quote/intraday/lease cutover

- Regular、premarket、after-hours、closed、early close分別驗證。
- 先fixture/fake port，再bounded live request；KGI US需另有entitlement/live sample。
- Viewer、Research、Collector lease分開記錄owner、deadline、symbol bound與cleanup。
- `require_live`未滿足回policy-unmet；previous session不可冒充live。
- Last-good只作有lineage/freshness的candidate，不由service直接升current。

Rollback：release本task-owned lease、mode回off、驗證legacy path恢復；不得終止未知owner process/lease。

## 10. Consumer cutover

順序與驗收：

1. Stable backend API：contract snapshot、provider-neutral request、lineage outward。
2. AI／HTTP/SSE／MCP：Decision v4 parity、no provider selection、bounded fill/refresh semantics。
3. Frontend：移除provider input，只renderbackend projection/Data Status；lint/typecheck/build與實際桌面/手機畫面。

任一consumer失敗，只rollback該consumer/capability；不把fallback重新寫進consumer。

## 11. Automatic rollback triggers

- `cache_only`或completed-session產生provider IO、subscription、repair或write。
- Selected evidence缺provider/source/event/fetched/fallback/selection reason/limitations。
- Provider-coherence violation或跨provider欄位merge未顯式reconciliation。
- Unknown/missing被轉成0，或No Quote被轉成No Trade/Suspended。
- Provider call、latency、symbol、runtime、range或quota超過bound。
- Repair回success但postcondition未滿足。
- DB commit failure未rollback/rethrow，或provider IO期間持有transaction。
- HTTP/SSE/MCP/Frontend semantics分叉。
- Runtime source SHA/mode/port/owner不明。
- Canary mismatch沒有分類，或超過當次預先宣告threshold。
- User-visible chart/Data Status出現錯誤、遮蔽warning或資料日期/session不符。

## 12. Rollback procedure

1. 停止promotion，保存當前evidence packet。
2. 將該rollout key回到上一個passed mode；只操作明確task-owned config/runtime。
3. 若有lease，釋放本task建立且ownership可證明的lease。
4. 不刪canonical candidates、coverage checkpoint或local DB rows。
5. 用cache-only API與consumer smoke確認legacy/previous path恢復。
6. 在`Progress.md`與`RiskRegister.md`記錄trigger、影響、recovery與重新解鎖條件。
7. 修正後從失敗mode的前一階段重跑，不直接跳回canary/on。

## 13. Closure checklist

- [ ] 所有AcceptanceMatrix required rows passed。
- [ ] Product source/provider selector inventory為0。
- [ ] `app.us_market.service`無cross-provider fallback owner。
- [ ] Shared Core不direct importUS legacy service。
- [ ] Dataset Registry實際控制US refresh lifecycle。
- [ ] Daily／intraday／repair／consumer rollback各有artifact。
- [ ] Backend/frontend/full validation通過。
- [ ] Official runtime source SHA/PID/port/mode verified。
- [ ] HTTP/AI/MCP/Frontend visible workflow passed。
- [ ] Known provider/schema/corporate-action/KGI limitations truthful。
- [ ] Current architecture/product docs已同步。
- [ ] `Progress.md`標記`US_MARKET_DATA_PLATFORM_PRODUCTION_CONVERGED`。
