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

## Stop-and-fix rules

- 如果 validation 顯示既有 dirty worktree 已經壞，先修 baseline，不進入 refactor。
- 如果 slot status 與實際 payload 矛盾，先修 contract test。
- 如果 runtime gate 讓正式 launcher 少啟動應有背景任務，立刻停下改回產品預設。
- 如果拆分造成 circular import，先抽更小的 pure helper，不用強行維持原拆分方案。
- 如果某 batch 需要 live provider 或大量 refresh，先改成 mocked parser/contract test；live smoke 另列明確確認步驟。
