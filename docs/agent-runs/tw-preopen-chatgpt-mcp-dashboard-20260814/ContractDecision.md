# OMI 台股盤前 ChatGPT MCP App Contract 決策記錄

## 決策摘要

本文件固化 2026-08-14 M0 的責任邊界。所有 dashboard market truth 由 OMI backend 產生；`OMI_search` 只做 HTTP/MCP projection；ChatGPT widget 只呈現與互動。

## Runtime 與 storage

- `backend/app/runtime.py` 在 API runtime 內啟動 `job_scheduler.start_scheduler()`，目前不需要為 API/collector 跨 process 另建 snapshot storage。
- 既有 `collect_taiwan_market_index_summary()` 負責 refresh，並將結果持久化到 `taiwan_market_minute_state`、`taiwan_index_minute_snapshot` 與 `taiwan_intraday_stock_state`。
- collector registration 已具 interval、`coalesce=true`、`max_instances=1` 與固定 job id。
- dashboard GET 只讀既有 SQLite canonical state；本階段 migration decision 為 `not_required`。
- live refresh window 與 breadth target date 從交易日 08:30 開始；08:30 前輸出 `preopen_pending`／`not_observed`。

## Backend surface

| Surface | 決策 | Side effect |
| --- | --- | --- |
| `GET /api/market/tw-dashboard/snapshot` | 回傳 `omi.tw_market_dashboard.v1` | cache-only；不得 provider refresh |
| `GET /api/market/tw-dashboard/symbols/search` | 查 active Taiwan `StockMaster`，bounded limit | local DB read only |
| `GET /api/market/tw-dashboard/stocks/{stock_id}` | focused K 線與 technical projection | `ensure_history=false`，不得 backfill |

dashboard contract 包含 `snapshot_id`、`state_version`、session、indices、TWSE/TPEx breadth、hot groups、watchlist、freshness、warnings 與 limitations。

## Watchlist policy

- 呼叫端可傳明確 `watchlist_group_id`。
- 未傳時，取 `sort_order`、`id` 最前的 active root group。
- `include_children=true` 為預設；只取 enabled items；預設上限 40、API hard limit 100。
- 缺 quote 的股票保留在清單並顯示 reason，不得靜默 drop。
- response 顯示實際 group id/name、selection policy、children/enabled/limit 與 truncation。

## Breadth 與 group semantics

- 盤前只使用 `indicative_match_available=true` 的 indicative price；不 fallback 成 actual trade。
- 08:30 前即使 DB 有 indicative row，也投影為 `not_observed`。
- regular/closing/post-close 僅接受既有 `has_actual_trade` 且 `decision_usable` 的 state。
- 每個 market 必須維持：
  - `advance + decline + unchanged = coverage`
  - `coverage + unknown = universe`
- group 以 backend `StockMaster.industry/category` membership 聚合；至少 3 個 observed samples 才進排行榜，排序依 median、advance ratio、coverage、group id 決定。

## Index estimate boundary

目前 repo 尚無足以證明指定交易日官方 TAIEX/TPEx 成分股、完整 divisor adjustment 與 corporate-action state 的 canonical dataset。因此本階段只提供 `omi.tw_preopen_index_estimate.proxy.v1`：

- universe 使用 active `StockMaster` stock proxy，股數使用 `StockProfile.issued_shares`。
- baseline 使用前一交易日可用的 official daily index close。
- 缺 indicative quote 時 price delta 視為 0，但該 reference weight 保留在 denominator，不重新正規化。
- component data coverage 低於 80% 或缺 baseline 時不輸出 estimate。
- 一律 `provisional=true`、`official=false`、`decision_usable=false`、`constituent_as_of=null`、`divisor_adjustment_status=not_verified`。
- M4 不得標記完成，直到正式 constituent、shares-as-of、corporate-action 與 divisor 證據具備可重播 fixture。

## MCP Apps surface

採 `interactive-decoupled`：

1. `omi.read_tw_market_dashboard`：data-only，呼叫 backend snapshot。
2. `omi.open_tw_market_dashboard`：render-only，唯一綁定 UI resource。
3. `omi.search_tw_symbols`：bounded local search。
4. `omi.read_tw_stock_dashboard_detail`：focused cache-only detail。

UI resource 固定為 `ui://omi/tw-market-dashboard/v1.html`，MIME 為 `text/html;profile=mcp-app`。新 metadata 使用 `_meta.ui.resourceUri`，`openai/outputTemplate` 僅作相容 alias。

## Compatibility

- 新 route 與模型採 additive 方式，不改寫 legacy `tw.market.breadth.v2`、AI answer contract 或現有 MCP tools。
- `backend/app/market/indices.py` 的 08:30 gate 影響既有 scheduler refresh 起始時間，但不放寬 completed-session decision semantics。
- `OMI_search` 不得 import OMI DB/model/provider，也不得在 adapter/widget 重算 session、breadth、group、MA 或 index estimate。

## 尚未完成

- 官方 dated index constituent/divisor/corporate-action source。
- MCP resources/tools protocol implementation 與 public contract snapshot parity。
- React widget、CSP、bridge、polling與互動測試。
- 正式 runtime adoption、ChatGPT Developer Mode、tunnel 與真實 08:00/08:30/08:55/09:00 evidence。
