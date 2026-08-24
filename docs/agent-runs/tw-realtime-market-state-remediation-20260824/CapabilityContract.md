# Capability Contract

## 1. 能力分界

| Gate | 範圍 | Owner | 不負責 |
|---|---|---|---|
| MDF-M5 Core | selected-symbol quote、trade／auction、L5、latency、lease／switch | Market Data Foundation | 全市場 breadth、官方指數 |
| Market-State Gate | resolved TWSE／TPEX index、breadth coverage／reasons、session phase | Taiwan market service + existing index resolver | selected-symbol callback integrity |

整體 Foundation runtime closure 需要兩個 gate 都通過，但失敗 attribution 必須分開。

## 2. 即時 stream v2

- Kind: `taiwan_realtime_quote_stream`
- Contract: `omi.tw.realtime_stream.v2`
- Acquisition: KGI viewer／acceptance lease，bounded selected symbol only。
- Read path: snapshot 與 SSE 都讀同一 manager projection；SSE 不重算市場語意。
- Compatibility: 保留 v1 的 top-level fields、recent trades、auction observations、minute kbars 與 depth metrics；新增 full depth、latency、session phase。

### 事件處理

```text
KGI bridge normalized callback
        ↓ raw event buffer + manager_ingested_at
session phase from event time / trading calendar
        ↓ canonical_snapshot_from_kgi
cumulative-volume integrity projection
        ↓
recent_trades | auction_observations | depth | latency
        ↓
HTTP snapshot / SSE / frontend
```

- `simtrade=1` 永遠不是正式成交。
- preopen／opening auction／closing auction callback 即使價格、單量、累計量皆正值，仍投影為 indicative auction。
- continuous／post-close cold-start 第一筆 eligible callback 只建立 cumulative baseline；之後只有 actual-trade evidence 且 cumulative volume 嚴格推進才新增正式成交。
- cumulative volume 相同或倒退不得新增正式成交；不得用 price signature 取代 volume integrity。
- 跨交易日清除 intraday event buffer 與 cumulative baseline；較舊日期 callback fail closed。

### Redacted callback diagnostics

- 一般 SSE 不攜帶 callback event history；acceptance GET 只有在明確指定 bounded `diagnostic_limit` 時才回傳 redacted diagnostic events。
- 每筆只允許 sequence、時間、session、normalized trial flag、cumulative relation、projection action 與已建立的 projection event id。
- 不輸出 raw provider payload、credential、account、lease id、私人 identity 或原始 exception。
- Aggregated counters 必須能分辨 baseline-only、advanced／same／decreasing cumulative、trade／auction addition、signature suppression、trial leak 與 cross-date rejection。

### Depth

- `bid_levels`、`ask_levels` 每側最多五檔。
- 每檔保留 `level`、`price`、`price_state`、`size_shares`、`size_lots`。
- top-level 保留 provider、source、capability、state、event／received time 與 freshness。
- stream 不可用、stale 或 symbol 不相符時，frontend 可回退既有 resolved quote-depth snapshot；不得沿用上一檔 stream depth。

### Latency

- Stages: `event_at`、`bridge_received_at`、`manager_ingested_at`、`stream_sampled_at`。
- Derived: event→bridge、bridge→manager、manager→stream、event→stream milliseconds；負值或無法比較時回 `null` 並加 warning。
- Provider raw delay: `provider_delay_raw` 原樣保留，`provider_delay_unit="unknown"`，直到 SDK 文件加 live correlation 能證明單位。
- Latency 是診斷 evidence，不在本次 source-only implementation 設硬 SLA。

## 3. Index authority

- 唯一 resolver：`backend/app/market/index_resolution.py`。
- Dashboard 的 resolved index projection 只讀 `get_market_index_summary()` 的 cache-only result。
- Resolver 明確輸出 `authority=official_exchange|provider|derived_proxy|unknown` 與 `finalization=intraday|provisional|final|unknown`。
- selected provider／source／candidate、decision usability、resolution version 與 warnings 由 resolver contract 決定。
- `official_source`、`official_close_confirmed`、`provisional_estimate` 是 additive clarity fields；舊 `official`／`provisional` 只保留 compatibility 語意。
- 舊 component-weight proxy estimate 保留在 `indices` compatibility field；新 `resolved_indices` 是 headline evidence，並以 `headline_index_field="resolved_indices"` 明示採用。

## 4. Breadth coverage reasons

- Full-market／registered-universe owner 保留在既有 index summary breadth contract；dashboard 以 `resolved_breadth` 作 headline projection。
- 舊 `breadth` 欄位保留 intraday-state compatibility projection，並以 `headline_breadth_field="resolved_breadth"` 避免 consumer 把兩個 scope 混為同一資料集。
- `classified`: 可安全歸類 advance／decline／unchanged。
- `state_missing`: universe 中沒有當日 canonical intraday state。
- `state_not_observed`: 有 state，但 requested session semantics 下無可用 observation。
- `reason_unknown`: 有 gap，但 owner 無法安全判定是無成交、不可交易、provider missing 或 mapping error。
- `valid_no_trade`、`not_tradable`、`provider_missing`、`mapping_error` 只有在 canonical evidence 能證明時才可填 count；否則為 `null`，不是 `0`。
- `unknown` 必須等於 universe 減 classified；reason counts 的已知 bucket 加總不得超過 unknown。
- `not_received` 與 `received_unclassified` 只描述觀察結果，不直接推論成停牌、無成交、provider failure 或 mapping error。

## 5. Freshness 與 fallback

- Realtime stream freshness 以最新 callback `received_at` 與 manager stale policy 為基礎。
- Dashboard cache-only 不因缺 resolved index 或 breadth 自動 call provider。
- Stream fallback 只發生在 consumer 顯示層採用既有 backend-resolved quote-depth snapshot；consumer 不選 provider。
- Missing／partial／stale／warming／unavailable 必須 outward 可見。

## 6. 驗證矩陣

| Layer | 必要證據 |
|---|---|
| Pure projection | cold-start preopen／closing、continuous first trade、13:30 formal match、same／decreasing cumulative、cross-day reset |
| Canonical depth | L1／L5、lots→shares、non-price level、symbol mismatch、odd lot rejection |
| Latency | timezone-aware stages、unknown raw delay unit、negative duration fail closed |
| Stream schema | v1 fields preserved、v2 depth／latency validation、empty／warming／stale |
| Frontend | matching-symbol priority、switch residual guard、fallback snapshot、TypeScript／build |
| Market state | existing resolver adoption、official/provisional flags、cache-only proof、breadth reason reconciliation |
| Live gates | formal session cold-start、callback integrity、symbol switch first useful depth、latency distribution、TWSE/TPEX resolved source |

## 7. Source identity stages

- `source-ready`：base checkpoint 與 acceptance extension checkpoint 都通過、target mismatch=0，且 source validation completed。
- `runtime-adopted`：正式 launcher 採用相同兩份 checkpoint source，runtime／frontend／MCP lineage 與 compare mode通過。
- `runtime-accepted`：真實 Preopen、Opening、Regular、Closing、Market-State 與 cleanup artifacts 全部通過。
