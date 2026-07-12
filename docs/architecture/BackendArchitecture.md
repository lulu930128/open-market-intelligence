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
- `backend/app/runtime.py` 擁有 startup/shutdown lifecycle，包括 migration、DB init、scheduler、crypto background components 與 job executor cleanup。
- `backend/app/routers/` 只負責 HTTP schema、參數、status code 與 service dispatch。跨市場共用的 error/job pattern 放在 `market_family_helpers.py`。
- Public route、method、query parameter 與 response shape 預設向後相容；共用 helper 不得改變 request envelope。

## Market Service

- `market/` 是台股核心；`us_market/`、`jp_market/`、`kr_market/`、`crypto_market/` 與 `resource_market/` 是 context layers。
- Service 擁有 normalization、fallback、upsert、bounded refresh、resource aggregation 與市場特有 policy。
- Parser 與 provider adapter 保持純 IO / payload conversion，不接受 SQLAlchemy `Session`。
- US provider namespace 已使用 `us_market/providers/` 作為薄 adapter；JP/KR 仍由 `sources.py` 承擔 provider IO 與 parser，後續拆分時必須保留 service import seam。

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
- Stateful multi-request flow 可使用 `http_client.new_session()`，但仍須明確 timeout、錯誤分類與來源資訊。

## Provider Events 與 Source Health

- `provider_health.py` 負責 event persistence、event summary、entry enrichment 與 snapshot sync。
- 複合 provider key，例如 `krx_data+yahoo_chart`，會匹配其中任一 provider event；`all` 仍是 wildcard。
- `source_health_contract.py` 只提供跨市場共用 primitives：UTC 產生時間、daily freshness lag、row status 與 summary counting。
- 各市場 module 保留交易日曆、session、required/not-applicable、秒級 freshness 與 provider-specific reason，不把市場差異塞進通用 helper。
- Source-health 不得隱藏 `stale`、`empty`、`partial`、`disabled`、`rate_limited` 或 recent provider errors。
- JP `/api/jp-market/source-health` 預設是 `availability_only`。日本交易所假日曆尚未建模時，不得自動宣稱 daily data 為 `current`；只有提供 `expected_daily_price_date` 才做精確判定。

## Transaction Ownership

目前 repo 的 service contract 採下列規則：

- Query/read helper 不 commit。既有 source-health builder 為保存 snapshot 會寫 DB，這是明示的 observability side effect。
- `upsert_*`、`refresh_*`、job worker 與 maintenance pipeline 是 transaction owner；它們可以 commit，失敗時必須 rollback 或讓上層 owner rollback。
- Provider adapter、parser、payload contract 與 source-health pure helper 不持有 transaction。
- `record_provider_event(..., commit=...)` 與 `sync_source_health_snapshots(..., commit=...)` 必須明確選擇 transaction 行為。
- Composite refresh 必須隔離單一 provider/symbol failure，不得因 event recording 失敗而提交半套 market data。

新增 service 時不要同時提供「有時 commit、有時只 mutate」的隱性模式。若需要讓呼叫端擁有 transaction，應增加明確參數或拆成 `mutate_*` 與 transaction-owning wrapper。

## AI 與 Consumer Contract

- `backend/app/ai/market_payload_contract.py` 擁有 payload level、bounded intraday points 與 slot completeness primitives。
- Backend AI 層擁有 evidence、freshness、tool orchestration、human answer 與 decision contract。
- Consumer 只呈現 backend contract；不得依 UI 狀態自行推論 freshness 或重做 provider fallback。

## 驗證層級

- Pure contract：`test_provider_http.py`、`test_source_health_contract.py`。
- Provider/event integration：`test_provider_health.py`。
- 市場 contract：`test_market_source_health.py`、`test_us_market_data.py`、`test_jp_market_data.py`、`test_kr_market_data.py`、`test_crypto_market.py`、`test_resource_market.py`。
- 跨模組修改完成後使用 `scripts/run-safe-validation.ps1 -Profile backend` 跑完整 backend regression。

## 後續拆分原則

大型 service/module 只按穩定責任拆分，不按行數拆分。優先順序是 provider adapter、payload projection、source-health projection、schema conversion，並保留原 import seam。避免同時重寫 service、route 與 response contract。
