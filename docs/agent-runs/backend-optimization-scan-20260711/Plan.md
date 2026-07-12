# Backend Optimization Scan Plan

## Batch 0 - 收斂現有變更與基線驗證

Acceptance criteria:

- 先確認目前 dirty worktree 的實際範圍，並避免混入無關 refactor。
- 釐清目前新增中的 portfolio、watchlist radar automation、AI decision contract、JP/KR/index/front-end 修改是否已完成。
- 建立 backend 優化前 baseline，至少能回答「目前是既有壞掉，還是優化引入 regression」。

建議驗證:

```powershell
.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs @(
  'backend\tests\test_ai_ask_stages.py',
  'backend\tests\test_ai_freshness_guard.py',
  'backend\tests\test_jp_market_data.py',
  'backend\tests\test_kr_market_data.py',
  'backend\tests\test_portfolio_holdings.py',
  'backend\tests\test_watchlist_radar_automation.py'
)
```

## Batch 1 - Runtime side-effect boundary

Acceptance criteria:

- `backend/app/main.py` 仍可用同一個 FastAPI app，但 startup components 被清楚分層。
- migration/init DB、scheduler、crypto auto-refresh、crypto WebSocket collector、job executor shutdown 有單一 runtime coordinator。
- 測試與 route registry import 可以使用不啟動 background loops 的 app path。
- 產品預設行為不被靜默關掉；若新增 test/runtime gate，必須是明確設定。

候選檔案:

- `backend/app/main.py`
- `backend/app/runtime.py`
- `backend/app/config.py`
- `backend/tests/test_system_health.py`
- `backend/tests/test_calendar_status_integration.py`

## Batch 2 - AI market payload contract helper consolidation

Acceptance criteria:

- `payload_level`、intraday point limit、slot envelope、slot status helper 由單一 backend AI contract module 提供。
- `backend/app/ai/tools.py` 與 `backend/app/ai/agentic_tools.py` 不再各自維護相近的 market payload helper。
- 既有 `result.data.slots`、`result.data.compact.slots`、`analysis.human_answer`、`analysis.decision_contract` shape 保持 backward-compatible。

候選檔案:

- `backend/app/ai/market_payload_contract.py`
- `backend/app/ai/tools.py`
- `backend/app/ai/agentic_tools.py`
- `backend/app/ai/ask_finalizer.py`
- `backend/tests/test_ai_ask_stages.py`
- `backend/tests/test_ai_freshness_guard.py`

## Batch 3 - Market-family router and job enqueue patterns

Acceptance criteria:

- US/JP/KR watchlist CRUD、ranking/radar、daily refresh、resource refresh 的 error mapping 與 job enqueue shape 有 shared helper。
- Router 只處理 HTTP schema、query parameters 與 service call，不重複拼大量 request envelope。
- 不改現有 route path、method、response_model。

候選檔案:

- `backend/app/routers/us_market.py`
- `backend/app/routers/jp_market.py`
- `backend/app/routers/kr_market.py`
- `backend/app/routers/watchlists.py`
- `backend/app/jobs/job_types.py`
- `backend/app/jobs/service.py`

## Batch 4 - Provider HTTP and source-health policy

Acceptance criteria:

- 外部 HTTP 入口一致使用 repo policy：proxy handling、timeout、error classification、provider event。
- provider failure 能被 source health、warnings、missing、rate_limited 或 skipped status 表達。
- 不把 provider exception 原樣擴散成不穩定的 user-facing detail。

候選檔案:

- `backend/app/http_client.py`
- `backend/app/observability/provider_health.py`
- `backend/app/market/source_health.py`
- `backend/app/us_market/source_health.py`
- `backend/app/jp_market/service.py`
- `backend/app/kr_market/service.py`
- `backend/app/crypto_market/source_health.py`
- `backend/app/resource_market/source_health.py`

## Batch 5 - Large service/module split by responsibility

Acceptance criteria:

- 只拆「責任邊界已清楚」的區塊，不追求單純降低行數。
- 優先拆純 helper、payload projection、provider adapter、source-health projection、schema conversion。
- 每次拆分都以 import compatibility 或 small wrapper 保護舊 call sites。

候選熱點:

- `backend/app/ai/answer_composer.py`
- `backend/app/ai/tools.py`
- `backend/app/ai/agentic_tools.py`
- `backend/app/db/models.py`
- `backend/app/market/indices.py`
- `backend/app/routers/market.py`
- `backend/app/us_market/service.py`
- `backend/app/jp_market/service.py`
- `backend/app/kr_market/service.py`
- `backend/app/crypto_market/service.py`

## 2026-07-13 後續整理規劃

目前已完成 Batch 0-5 的第一輪架構收斂：runtime lifecycle、AI payload contract、market-family router helper、provider HTTP/source-health contract，以及 US/JP/KR provider adapter ownership。完整 backend baseline 是 `547 passed, 1 warning`。

後續不再以「最大檔案優先」排序，而是依下列原則逐批進行：

- 台股核心優先於其他市場 context layer。
- 先拆外部 IO 與 pure projection，再拆 transaction-owning service。
- 舊 public/private import seam 先保留 wrapper；同一批不改 route 與 response shape。
- 每一批只建立一個主要責任邊界，targeted regression 通過後才跑完整 backend。

### Batch 6 - 台股 index provider 與計算責任分離

目標：收斂 `backend/app/market/indices.py` 目前混合的 TWSE、TPEX、TWSE MIS、Yahoo HTTP、parser、cache、DB coverage 與 index calculation。

預定做法：

- 在 `backend/app/market/providers/` 建立台股 index provider adapters，統一走 `observability/provider_http.py`。
- 優先搬移 `_fetch_json`、TWSE/TPEX daily/index list、TWSE MIS、Yahoo chart 等外部 IO；parser 與 index calculation 分開留在明確 module。
- `indices.py` 保留既有 `_fetch_*` compatibility wrapper，因 `test_market_index_daily_stats.py` 目前直接 patch 這些名稱。
- 不改 breadth fallback、cache TTL、official/Yahoo/MIS merge order、public API payload 或 DB coverage policy。

Acceptance criteria：

- `indices.py` 不再直接 import `app.http_client` 或自行發送 provider request。
- 每個 provider request 都有 `market/provider/resource/target`、bounded timeout 與可分類錯誤。
- `get_market_index_list`、`get_market_index_intraday`、`get_market_index_contributions`、`get_market_index_ohlc_chart_data`、`get_market_index_summary` shape 不變。
- `backend/tests/test_market_index_daily_stats.py`、provider/source-health regression 與完整 backend 通過。

主要驗證：

```powershell
.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs @(
  'backend\tests\test_market_index_daily_stats.py',
  'backend\tests\test_provider_http.py',
  'backend\tests\test_market_source_health.py'
) -BackendTestTimeoutSeconds 420
```

### Batch 7 - Market service façade 分批拆責任

目標：降低 `us_market/service.py`、`jp_market/service.py`、`kr_market/service.py` 同時承擔 stock master、watchlist、refresh、resource projection、chart 與 intraday 的耦合。

執行順序：

1. 先從最大的 US service 開始，抽離 pure query/projection 與 chart/intraday helper。
2. 再處理 JP/KR 已對齊的 watchlist、resource slot 與 OHLC aggregation 邊界。
3. 每次只搬一個責任群；`service.py` 維持 façade 與 re-export，router 不改 import。
4. Transaction-owning `sync_*`、`refresh_*`、`upsert_*` 最後處理，並明確記錄 commit/rollback owner。

Acceptance criteria：

- Router、jobs、AI tools 的既有 service import 不變。
- 不新增跨市場共用抽象來隱藏市場差異；只有真正同 contract 的 pure helper 才共用。
- Watchlist CRUD、refresh fallback、resource summary 與 chart payload regression 全部通過。
- 每個市場至少一個獨立 commit，不把 US/JP/KR service rewrite 合成一批。

主要驗證：

```powershell
.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs @(
  'backend\tests\test_us_market_data.py',
  'backend\tests\test_jp_market_data.py',
  'backend\tests\test_kr_market_data.py',
  'backend\tests\test_watchlist_ranking.py'
) -BackendTestTimeoutSeconds 600
```

### Batch 8 - AI answer composer pure modules

目標：讓 `answer_composer.py` 保留 orchestration，將已具穩定測試的 pure formatting/projection 責任拆出。

第一優先拆分：

- locale labels 與 text normalization；
- source-health/data-limit projection；
- decision evidence summary/risk/data lines；
- watchlist radar row formatting。

限制：

- 暫不直接搬移 824 行的 `build_question_aware_consumer_answer()`；先用 characterization tests 固定輸出，再逐段降低依賴。
- `analysis.human_answer`、`analysis.decision_contract`、語系文案、warning 與 missing-data 語意保持相容。
- `ask.py`、`ask_finalizer.py` 與 consumer wrappers 仍只透過穩定 façade 呼叫。

主要驗證：

```powershell
.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs @(
  'backend\tests\test_ai_answer_composer.py',
  'backend\tests\test_ai_ask_stages.py',
  'backend\tests\test_ai_response_preferences.py',
  'backend\tests\test_ai_freshness_guard.py'
) -BackendTestTimeoutSeconds 420
```

### Batch 9 - AI tool market-context projection

目標：讓 `ai/tools.py` 與 `ai/agentic_tools.py` 保留 tool registry/execution，將 US/JP/KR/crypto/TW 的 pure context projection 與 compact payload builder 移到按市場分組的 module。

Acceptance criteria：

- `market_payload_contract.py` 仍是 slot/payload-level 真相來源。
- Tool name、input schema、budget、progress event、source refs 與 consumer payload 不變。
- 不讓 projection module 直接啟動 refresh、寫 DB 或呼叫 LLM。
- `test_ai_market_payload_contract.py`、`test_ai_ask_stages.py`、`test_ai_freshness_guard.py` 與市場資料測試通過。

### 明確延後

- `backend/app/db/models.py`：先不按市場拆檔。Declarative metadata、relationship import、migration 與舊 import compatibility 的風險高，需等 transaction ownership 與 migration tests 更完整後再獨立規劃。
- `backend/app/routers/market.py`：先等 `market/indices.py` 與 service façade 穩定，再按 route family 拆；現在先拆 router 只會搬動耦合。
- 移除 US/JP/KR `sources.fetch_*` wrapper：目前是相容層，不在架構整理期間做 breaking cleanup。

### Commit 與驗證節奏

- 本次 checkpoint 只包含 US/JP/KR provider adapter responsibility split 與規劃文件。
- 後續每個 batch 先跑 targeted regression，再跑 `run-safe-validation.ps1 -Profile backend`。
- 每個 batch 驗證通過後立即獨立 commit；不累積多個大型未提交架構變更。
- Live provider smoke、外部 quota 或大量 refresh 不作為預設驗證；需要時另行確認並限定 target/timeout。

## Stop-and-fix rules

- 如果 validation 顯示既有 dirty worktree 已經壞，先修 baseline，不進入 refactor。
- 如果 slot status 與實際 payload 矛盾，先修 contract test。
- 如果 runtime gate 讓正式 launcher 少啟動應有背景任務，立刻停下改回產品預設。
- 如果拆分造成 circular import，先抽更小的 pure helper，不用強行維持原拆分方案。
- 如果某 batch 需要 live provider 或大量 refresh，先改成 mocked parser/contract test；live smoke 另列明確確認步驟。
