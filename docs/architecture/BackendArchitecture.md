# OMI Backend Architecture

本文件描述 Open Market Intelligence backend 的穩定責任邊界。它是長期架構參考，不取代 `AGENTS.md` 的產品規則，也不取代單次維護任務的 `Progress.md`。

## 依賴方向

```text
FastAPI app / runtime
        |
        v
routers -> market services -> provider adapters / parsers
                    |                    |
                    v                    v
              SQLAlchemy models   provider_http -> http_client
                    |
                    v
        provider events / source-health snapshots

AI tools -> backend market services and contracts
frontend / MCP / Kuro -> backend HTTP API only
```

依賴只應沿箭頭方向前進。Provider adapter 不讀寫 DB；router 不重做市場邏輯；frontend、MCP 與 Kuro 不複製 freshness、provider fallback 或 AI decision logic。

## Runtime 與 API

- `backend/app/main.py` 只建立 FastAPI app、middleware、exception handler 與 route registry。
- `backend/app/runtime.py` 擁有 startup/shutdown lifecycle。每個 process 先以 `schema.lock` 序列化 Alembic upgrade；正常啟動只使用 migration，不呼叫 `Base.metadata.create_all()`。
- 各 API process 以 `background.lock` 非阻塞競選背景 ownership；只有 leader 執行 interrupted-job recovery、scheduler、Crypto auto-refresh 與 realtime collectors，follower 保持可服務 API。shutdown 只停止並釋放本 process 實際持有的元件與 lock。
- `backend/app/routers/` 只負責 HTTP schema、參數、status code 與 service dispatch。跨市場共用的 error/job pattern 放在 `market_family_helpers.py`。
- 大型 router 可依 route family 拆成 subrouter，例如 Taiwan index 與 futures routes 分別由 `tw_market_indices.py`、`tw_market_futures.py` 擁有；原 router 應 include subrouter 並保留既有 handler import seam。
- Router 不擁有 SQLAlchemy transaction，不直接呼叫 `commit()`、`rollback()` 或 `flush()`；transaction recovery 與 job persistence 留在 service/domain owner。
- Router 不 import `requests` 或辨識 provider transport exception；transport failure 必須先在 service boundary 轉成市場 domain error，再由 router 映射既有 HTTP status/detail。
- Public route、method、query parameter 與 response shape 預設向後相容；共用 helper 不得改變 request envelope。
- Router 搬移後必須比較 OpenAPI operation ID、response model 與 path/method inventory，不能只以 route 數量判定相容。
- Watchlist Radar snapshot 由 scheduler/job/service 鏈路擁有：預設涵蓋所有 active group，保存前驗證預期交易日，重跑區分 created/existing，並以收盤後 reconciliation 補足漏跑；router 與 GET read path 不隱性建立快照。

## Market Service

- `market/` 是台股核心；`us_market/`、`jp_market/`、`kr_market/`、`crypto_market/` 與 `resource_market/` 是 context layers。
- Service 擁有 normalization、fallback、upsert、bounded refresh、resource aggregation 與市場特有 policy。
- Parser 與 provider adapter 保持純 IO / payload conversion，不接受 SQLAlchemy `Session`。
- Taiwan stateless read paths 使用 `market/providers/`；provider identity、resource、target 與 bounded timeout 由 adapter 統一提供。需要 cookie/session 的期貨與 history/backfill workflow 保留 stateful transport boundary。
- Taiwan futures quote/daily refresh 由 `tw_futures.py` 擁有 transaction，失敗時 rollback 並重新拋出；provider fallback job lifecycle 由 `tw_futures_jobs.py` 協調 `jobs.service`，不放在 router。
- US、JP、KR provider 都使用各市場的 `providers/` namespace。Service 直接 import provider fetcher，讓 provider ownership 可被辨識與獨立測試。
- US、JP、KR `sources.py` 不直接執行 provider HTTP；舊 `fetch_*` 名稱保留為 forwarding wrapper，保護既有 import seam。US `fetch_symbol_directories()` 只組合 NASDAQ/SEC provider payload 與既有 parser。
- US、JP、KR 的 provider exception 與 symbol normalization 分別放在 `errors.py`、`symbols.py`，provider 與 parser 共同依賴純 contract，禁止互相反向 import。
- 對外 service entrypoint 使用 `translate_provider_http_errors()` 將未處理的 `requests.RequestException` 轉成各市場 `MarketDataFetchError`；既有 provider-specific domain error 不重包裝，原 transport error 保留為 cause。
- US、JP、KR OHLC aggregation/projection 分別放在 `chart_projection.py`；transaction-owning refresh、cache 與 public service entrypoint 留在 `service.py` façade。
- Crypto 與 resource 的 bounded REST request 使用各自 `providers/` namespace。Crypto realtime/WebSocket lifecycle、persistence 與 stateful refresh 不因 REST adapter 拆分而移動。

## Provider HTTP Contract

- `backend/app/http_client.py` 是最低層 transport，只管理 `requests.Session` 與 `OMI_HTTP_TRUST_ENV`。
- `backend/app/observability/provider_http.py` 是市場 provider request contract，負責：
  - 明確 `market/provider/resource/target` identity；
  - 必填且大於零的 bounded timeout；
  - `timeout`、`rate_limited`、`blocked`、`failed`、`error` 分類；
  - `Retry-After` 秒數或 HTTP-date 解析；
  - 不含 query secret 的 safe source URL；
  - 可交給 `record_provider_event()` 的結構化欄位。
- Provider HTTP 層不得直接寫 DB。事件是否落庫由擁有 transaction 的 service、job 或 pipeline 決定。
- Service fallback 若已取得 canonical `ProviderHttpFailure`，使用 `provider_fallback.py` 另開短生命週期 session 寫入 `event_type=fallback`。此 telemetry 是 best-effort，不得 commit/rollback 呼叫端 transaction，也不得因自身寫入失敗取代市場 fallback。
- `translate_provider_http_errors()` 只提供 service boundary translation；它不得吞掉非 transport error，且 exception chaining 必須讓 `provider_http_failure()` 仍能取回結構化 failure。
- Stateful multi-request flow 可使用 `http_client.new_session()`，但仍須明確 timeout、錯誤分類與來源資訊。

## Provider Events 與 Source Health

- `provider_health.py` 負責 event persistence、event summary、entry enrichment 與 snapshot sync。
- 複合 provider key，例如 `krx_data+yahoo_chart`，會匹配其中任一 provider event；`all` 仍是 wildcard。
- `source_health_contract.py` 只提供跨市場共用 primitives：UTC 產生時間、daily freshness lag、row status 與 summary counting。
- 各市場 module 保留交易日曆、session、required/not-applicable、秒級 freshness 與 provider-specific reason，不把市場差異塞進通用 helper。
- Source-health 不得隱藏 `stale`、`empty`、`partial`、`disabled`、`rate_limited` 或 recent provider errors。
- Persisted source-health read contract 會回傳 `snapshot_age_seconds` 與 `snapshot_is_stale`；GET 只揭露 snapshot 本身是否過期，不在讀取路徑隱性重算或刷新全市場資料。
- JP `/api/jp-market/source-health` 預設是 `availability_only`。日本交易所假日曆尚未建模時，不得自動宣稱 daily data 為 `current`；只有提供 `expected_daily_price_date` 才做精確判定。

## Transaction Ownership

目前 repo 的 service contract 採下列規則：

- Query/read helper 不 commit。Source-health snapshot 只由明示 sync/maintenance owner 保存；list/read route 只計算 age，不產生寫入。
- `upsert_*`、`refresh_*`、job worker 與 maintenance pipeline 是 transaction owner；它們可以 commit，失敗時必須 rollback 或讓上層 owner rollback。
- 直接擁有 `commit()` 的 service owner 必須在 commit failure 時 `rollback()` 並重新拋出，避免 session 留在 failed transaction 狀態。
- Transaction-owning refresh 若允許 provider/cache fallback，必須先恢復 session 再執行 fallback query；router 不補做 session recovery。
- Provider adapter、parser、payload contract 與 source-health pure helper 不持有 transaction。
- `record_provider_event(..., commit=...)` 與 `sync_source_health_snapshots(..., commit=...)` 必須明確選擇 transaction 行為。
- Composite refresh 必須隔離單一 provider/symbol failure，不得因 event recording 失敗而提交半套 market data。

新增 service 時不要同時提供「有時 commit、有時只 mutate」的隱性模式。若需要讓呼叫端擁有 transaction，應增加明確參數或拆成 `mutate_*` 與 transaction-owning wrapper。

## AI 與 Consumer Contract

- `backend/app/ai/market_payload_contract.py` 擁有 payload level、bounded intraday points 與 slot completeness primitives。
- `answer_localization.py`、`answer_data_limits.py` 與 `answer_scenarios.py` 分別擁有 locale/text、資料限制/confidence cap、scenario/counter-evidence 純投影；`answer_composer.py` 保留高階組裝與相容 re-export。
- `backend/app/ai/market_context/common.py` 擁有 source-ref 去重、freshness、resource counting 與 compact slot/context 純投影；tool registry、schema、budget、planner 與 execution policy 仍留在原 façade。
- Backend AI 層擁有 evidence、freshness、tool orchestration、human answer 與 decision contract。
- Consumer 只呈現 backend contract；不得依 UI 狀態自行推論 freshness 或重做 provider fallback。

## Database Model Registry

- `backend/app/db/models.py` 保持唯一 ORM model registry，`Base.metadata` 是 model contract；Alembic revision head 是 deployed schema 的唯一啟動真相來源。
- 目前不按 domain 拆 model 檔案：model import 密度、foreign-key resolution 與 migration discovery 的風險高於檔案縮短的收益。
- 未來若重新評估，必須先保護 `app.db.models` import set、table metadata、constraint/index identity 與 Alembic discovery；不得建立第二個 `Base`。
- 本次 evidence 與決策記錄在 `docs/agent-runs/backend-architecture-consolidation-20260713/DatabaseModelDecision.md`。

## 驗證層級

- Pure contract：`test_provider_http.py`、`test_source_health_contract.py`。
- Provider/event integration：`test_provider_fallback.py`、`test_provider_health.py`、`test_market_provider_adapters.py`、`test_taiwan_index_provider_adapters.py`、`test_crypto_resource_provider_adapters.py`。
- 市場 contract：`test_market_source_health.py`、`test_us_market_data.py`、`test_jp_market_data.py`、`test_kr_market_data.py`、`test_crypto_market.py`、`test_resource_market.py`。
- 架構 contract：`test_market_transaction_contracts.py`、`test_market_chart_projections.py`、`test_ai_answer_pure_modules.py`、`test_ai_market_context_projection.py`、`test_api_contract_inventory.py`、`test_database_model_contract.py`。
- Router transport boundary 與跨市場 error translation：`test_api_contract_inventory.py`、`test_provider_http.py`、`test_market_provider_adapters.py`。
- Taiwan futures job/fallback contract：`test_taiwan_futures_jobs.py`。
- Watchlist Radar daily snapshot/coverage contract：`test_watchlist_radar_automation.py`、`test_calendar_status_integration.py`。
- Runtime/schema ownership：`test_runtime.py`、`test_runtime_lock.py`、`test_database_migrations.py`。
- 跨模組修改完成後使用 `scripts/run-safe-validation.ps1 -Profile backend` 跑完整 backend regression。
- GitHub backend CI 使用 `pytest -p no:cacheprovider backend/tests`，與 repo-local backend profile 採相同 collection surface。

## 後續拆分原則

大型 service/module 只按穩定責任拆分，不按行數拆分。優先順序是 provider adapter、payload projection、source-health projection、schema conversion，並保留原 import seam。避免同時重寫 service、route 與 response contract。
