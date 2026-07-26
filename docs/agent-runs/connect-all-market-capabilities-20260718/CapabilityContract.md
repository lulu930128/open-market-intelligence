# 市場能力對外契約

## 契約邊界

- 唯一 public AI entrypoint 仍是 `POST /api/ai/ask` 與 MCP `omi.ask`。
- 新能力採 additive `target.type`，不建立第二套市場判斷或 freshness 邏輯。
- `source_health` 回報當前 runtime/provider 狀態；`capability_status` 回報功能、provider 與政策是否已接通。兩者不可混用。
- `provider_not_connected` 是可查詢的 blocked contract，不代表零值、沒有事件或行情中性。
- Portfolio 是私人資料；只有 server-trusted caller 可取得持倉，未受信任呼叫回 `blocked`。

## 已接通 targets

| target.type | 必要 id | 主要資料 | refresh 邊界 | 關鍵限制 |
|---|---:|---|---|---|
| `resource_asset` | 商品／匯率 symbol | quote、OHLCV、source health | read path 只讀 cache | watch-only、Yahoo best-effort/delayed |
| `portfolio` | 否 | active holdings、各幣別估值、coverage | read path 只讀本機 | trust-gated；不靜默合併幣別 |
| `us_macro` | FRED series id | cached observations、frequency | refresh 需 `FRED_API_KEY` | 非即時行情；release calendar 仍是 partial |
| `us_watchlist` | group id | ranking、radar、可選 intraday | intraday 受 external-fetch trust gate | configured watchlist，不是全市場廣度 |
| `jp_watchlist` | group id | ranking、radar | local cache | configured watchlist |
| `kr_watchlist` | group id | ranking、radar | local cache | configured watchlist |
| `source_health` | 否；可用 id/params 過濾 market | persisted health snapshots | 不觸發 refresh | runtime health，不是 capability readiness |
| `capability_status` | 否；可選 capability id | connected/blocked provider contracts | static backend contract | blocked 項目不可當作市場資料 |

## 既有 target 增強

- `market`
  - `data.breadth`：官方全市場廣度；若不可用才退回清楚標示的 OMI sample。
  - `data.market_chips`：官方 TWSE/TPEX aggregate 與 per-stock DB coverage 分離。
  - `data.cross_market`：US、JP、KR、Resource、Crypto 的 bounded local-cache 台股輔助 context。
- `tw_stock`
  - `data.compact.cross_market` 與 `slots.cross_market` 改接既有 US overnight impact，不再無條件 `planned`。
- `tw_futures`
  - 官方盤後外資 OI、Put/Call volume/OI ratio。
  - `data.market_chip_trend`：3/5/20 日 positioning、PCR 變化與 price divergence。
  - 仍不得把盤後法人資料描述成夜盤即時籌碼。
- `kr_stock` / `kr_index`
  - `include_intraday=true` 且 server policy 允許 external fetch 時，回傳 bounded 1m bars；否則維持 cache/missing 語義。

## Provider 未接通 contracts

以下項目由 `target.type=capability_status` 對外提供 `blocking_reason` 與 `next_fill`：

- `news_events`
- `us_options_flow_earnings`
- `jp_tdnet_disclosures`
- `kr_opendart_disclosures`
- `hk_market`

這些能力在 provider、授權、identity、freshness、persistence 與 bounded refresh policy 完成前，不得標成 `ready`。

`tw_options_chain_iv_greeks`、`tw_large_trader_positions`、`tw_futures_basis_term_structure` 已於第二階段改由 TAIFEX OpenAPI 接通；其 official／derived 與盤後限制見下方契約。

## Consumer 規則

- 優先讀 `result.data.slots` 或 `result.data.compact.slots`。
- 依 `status` 區分 `ready`、`partial`、`missing`、`blocked`、`provider_not_connected`、`not_requested`、`not_applicable`。
- 排行與廣度必須連同 `scope`／`coverage` 呈現；`omi_database_coverage` 不得改寫成交易所全市場。
- `missing`、`warnings`、`freshness`、`source_refs` 與 `evidence_passport` 不得在 frontend/MCP 被隱藏或重新推斷。

## 第二階段資料契約：TAIFEX 衍生品

| 能力 | Universe | 官方／衍生 | Release/Freshness | Persistence | 對外預設 |
|---|---|---|---|---|---|
| TXO 完整鏈 | `TXO` 所有到期序列、履約價、Call/Put、正規盤/盤後 | 行情與 Delta 官方；IV/Gamma/Vega/Theta 為 OMI derived | 官方盤後日資料；非即時夜盤 Greeks | `taiwan_option_chain_daily` | 最新交易日、指定 expiry、bounded strikes |
| 大額交易人 | `TX` futures、`TXO` options | 官方集中度統計 | 盤後；13:45/16:15 商品揭露差異需保留 | `taiwan_derivatives_large_trader_daily` | all-contract/weekly/monthly，可分 all/specific institution |
| 基差／期限結構 | `TX` 正規盤月契約 | 結算價官方；basis/slope/annualized basis derived | 日結算；需同日 TAIEX close | `taiwan_futures_term_structure_daily` | 最多 12 個月份，由近到遠 |

### Refresh contract

- `POST /api/market/tw-futures/derivatives/refresh`
- 固定 provider request 上限為五次，單次只取官方 endpoint 當日資料；沒有日期 range 或全歷史參數。
- provider/parser 不碰 DB；service 完成 normalize/upsert 並擁有 commit/rollback。
- 部分 endpoint 失敗時，成功 resource 可保存並回 `partial`；全部失敗才回 provider error。
- 交易日 16:20 scheduler 使用相同 bounded service；未到正式時點、休市日、active duplicate 或成功 cooldown 期間不排入。
- 排程 job 以 official calendar 的 expected trade date 驗收；`partial`、stale 或必要資料日期落後會明確標為 job error，不把不完整 refresh 記成成功。
- refresh response 逐資料集回傳 `dataset_trade_dates`、`stale_datasets`、`unverified_date_datasets` 與 `is_stale`。沒有日期欄位的官方 latest-only payload 不推定日期，保留 `unverified_date_datasets` warning。

### Read contract

- `GET /api/market/tw-futures/options-chain`
- `GET /api/market/tw-futures/large-traders`
- `GET /api/market/tw-futures/term-structure`
- GET 只讀 cache，所有 `limit`、expiry、session 與 trader type filter 均 bounded。
- Empty 不轉成零；資料日落後時由 `as_of`、`fetched_at`、`status` 與 warnings 顯示。

### Calculation contract

- `official_delta` 原樣來自 TAIFEX `DailyOptionsDelta`。
- `implied_volatility_pct`、`gamma`、`vega_per_vol_pct`、`theta_per_day` 使用 TAIEX close 作 spot，以 `black_scholes_spot_v1` 計算。
- 預設 `risk_free_rate=0`、`dividend_yield=0`，是透明的 research approximation，不是 TAIFEX 官方 IV/Greeks。
- 到期日已到、價格低於 intrinsic、無有效 option price、缺 TAIEX close 或求根未收斂時，Greeks 保留 `null` 並回傳具體 `calculation_status`。
