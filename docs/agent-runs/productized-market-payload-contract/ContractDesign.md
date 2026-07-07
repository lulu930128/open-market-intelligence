# Productized Market Payload Contract Design

Last updated: 2026-07-07

## Product Goal

OMI 的市場資料輸出要成為一個穩定、可分級、可被多種 consumer 使用的 backend contract。Frontend、MCP、ChatGPT 網頁版與桌寵/Kuro 應該只需要理解同一套 response shape，不需要自己判斷資料是否新鮮、是否缺口、是否需要外部 provider。

核心原則：

- 台股是主市場；其他市場是輔助 context layer。
- OMI backend 是市場資料、freshness、tool orchestration 與 AI answer contract 的真相來源。
- 所有未完成能力都要顯示成 slot 狀態，不隱藏、不編造。
- 大資料用 `payload_level` 分級，預設回 compact，必要時再要求更高密度。

## Request Controls

Consumer 透過 `market_data_params` 控制資料密度與盤中資料：

```json
{
  "target": {"type": "market"},
  "mode": "brief",
  "allow_external_fetch": true,
  "market_data_params": {
    "include_intraday": true,
    "payload_level": "summary",
    "intraday_limit": 1
  }
}
```

MCP tools may also expose the common controls at the top level:

```json
{
  "include_intraday": true,
  "payload_level": "summary",
  "intraday_limit": 1
}
```

The MCP adapter must merge these values into `market_data_params` before calling
the backend. Nested `market_data_params` remains the canonical backend shape.

### Payload Levels

| Level | Intended use | Intraday default | Consumer guidance |
| --- | --- | ---: | --- |
| `summary` | 語音、桌寵、ChatGPT 快答、大盤現況 | 1 point | 只給 latest/摘要，不給完整序列 |
| `compact` | 一般 MCP/ChatGPT/brief | 80 points | 預設等級，足夠判斷盤中狀態 |
| `standard` | UI 展開卡、圖表摘要 | 160 points | 需要看盤中走勢時使用 |
| `full` | 明確要求完整 evidence/debug | 500 points | 只在 full/report/debug 類場景使用 |

`intraday_limit` 可以覆蓋預設值，但 backend 必須有上限，避免一次回傳過大。

## Slot Envelope

每個 slot 是穩定插槽，不保證每個市場都已經有資料。slot 預設只放 metadata 與 `payload_ref`，避免重複放大 payload。

```json
{
  "status": "ready",
  "capability": "live_intraday_bars",
  "priority": "core",
  "payload_ref": "intraday_bars",
  "payload_level": "compact",
  "as_of": "2026-07-07T10:05:00+08:00",
  "missing": [],
  "warnings": [],
  "next_fill": null
}
```

### Slot Status Values

| Status | Meaning |
| --- | --- |
| `ready` | 該 slot 有足夠資料可直接使用 |
| `partial` | 有資料但 freshness、coverage 或欄位不完整 |
| `missing` | 此市場理應有資料，但目前沒有可用 payload |
| `not_requested` | 能力存在，但本次 request 沒要求或 policy 不允許 |
| `planned` | contract 已保留插槽，資料 adapter 尚未完成 |
| `not_applicable` | 該市場/資產類型不適用 |
| `blocked` | policy、quota、provider failure 或 trust boundary 阻擋 |

Consumer 不應把 `planned` 或 `missing` 當成 0，也不應自行補資料。需要更多資料時，用下一次 `omi.ask` 提高 `payload_level` 或調整 `market_data_params`。

## Canonical Slots

| Slot | Purpose | Payload ref examples |
| --- | --- | --- |
| `identity` | target identity、market、symbol/id | `target`, `scope` |
| `quote` | 即時或延遲 quote snapshot | `quote` |
| `intraday` | 個股/資產盤中 bar | `intraday_bars` |
| `daily_chart` | 日線 OHLC/技術分析基礎 | `full.data.chart`, `full.data.charts.daily` |
| `technical` | OMI 技術位階與 decision evidence | `technical` |
| `market_breadth` | 大盤漲跌家數、成交值、分布 | `breadth` |
| `index_intraday` | 大盤/櫃買等指數盤中 | `index_intraday` |
| `sector_industry` | 族群強弱與產業分布 | `top_industries,weak_industries` |
| `chips_flows` | 三大法人、融資券、分點、投資人流向 | `chips`, `resources` |
| `fundamentals` | 營收、財報、profile、SEC/本地基本面 | `fundamentals`, `resources` |
| `flows_liquidity` | liquidity、order book、short volume、spread | `resources` |
| `derivatives` | 期貨、選擇權、crypto derivatives | `resources` |
| `cross_market` | 海外指數、匯率、crypto risk context | future bounded context payload |
| `news_events` | 新聞、事件、法說、重大公告 | planned provider-backed payload |
| `data_quality` | missing、warnings、freshness、source refs | `data_quality`, `freshness_by_domain` |

## Current Capability Matrix

| Market target | Core status | Intraday | Index/market intraday | Slot maturity |
| --- | --- | --- | --- | --- |
| `tw_stock` | core | ready when trusted request includes `include_intraday` | n/a | implemented skeleton |
| `tw_index` | core | ready for supported index intraday | ready | implemented skeleton |
| `market` / Taiwan overview | core | n/a for every stock by default | ready for bounded TAIEX/TPEX pack | implemented skeleton |
| `tw_futures` | auxiliary Taiwan context | existing endpoint, slot unification pending | n/a | planned |
| `us_stock` | context layer | partial, tool-backed compact intraday exists | n/a | generic skeleton |
| `jp_stock` / `jp_index` | context layer | planned, local-cache-only read path | planned | generic skeleton |
| `kr_stock` / `kr_index` | context layer | planned, local-cache-only read path | planned | generic skeleton |
| `crypto_asset` / `crypto_market` | context layer | local/cache-backed depending collector coverage | n/a | generic skeleton |

## Response Shape

For compact evidence:

```json
{
  "data": {
    "compact": {
      "kind": "stock_compact_evidence",
      "version": "stock_compact_evidence.v1",
      "payload_level": "compact",
      "target": {"type": "tw_stock", "id": "2330", "market": "TWSE"},
      "quote": {},
      "intraday_bars": {},
      "technical": {},
      "freshness_by_domain": {},
      "data_quality": {},
      "slots": {
        "quote": {"status": "partial", "payload_ref": "quote"},
        "intraday": {"status": "not_requested", "payload_ref": "intraday_bars"},
        "cross_market": {"status": "planned"}
      }
    },
    "slots": {
      "quote": {"status": "partial", "payload_ref": "quote"},
      "intraday": {"status": "not_requested", "payload_ref": "intraday_bars"}
    }
  }
}
```

For Taiwan market brief/data_only:

```json
{
  "data": {
    "breadth": {},
    "index_intraday": {
      "enabled": true,
      "payload_level": "summary",
      "indices": []
    },
    "slots": {
      "market_breadth": {"status": "ready", "payload_ref": "breadth"},
      "index_intraday": {"status": "ready", "payload_ref": "index_intraday"}
    }
  }
}
```

## Consumer Rules

### ChatGPT Web / MCP

- Use `analysis.human_answer` for readable response.
- Use `result.data.slots` or `result.data.compact.slots` to decide whether data exists.
- If `status` is `summary`-level but user asks for chart/detail, call again with `payload_level: "standard"` or `full` instead of asking MCP adapter to expand locally.
- Preserve `missing` and `warnings` in the final answer when the slot is not `ready`.
- Prefer top-level `payload_level` / `intraday_limit` only as MCP convenience input; backend and logs should still see the merged `market_data_params`.

### Kuro / Desktop Pet

- Default to `payload_level: "summary"` for spoken brief.
- Display or speak only key slots: `quote`, `intraday`, `market_breadth`, `index_intraday`, `data_quality`.
- Open a richer card or second query before using `standard`/`full`.
- Never infer technical decision locally when OMI returns `missing`, `partial`, or `blocked`.

### Frontend

- Continue rendering existing fields.
- `OmiAskDock` should send `market_data_params.payload_level="compact"` by default.
- For intraday/real-time questions, `OmiAskDock` may request `payload_level="summary"`, `include_intraday=true`, and a small `intraday_limit` so the first answer remains bounded.
- Render `result.data.slots` or `result.data.compact.slots` as completeness status, not as market judgment.
- Use slots for card enable/disable state, loading placeholders, warnings, and expandable details.
- Do not duplicate selection controls or move market logic into components.

## Migration Plan

1. Add `slots` as additive metadata in compact evidence.
2. Project `slots` into public slim result.
3. Add tests for Taiwan stock, Taiwan index, Taiwan market, and at least one cross-market target.
4. Extend slot adapters per market with real `payload_level` trimming.
5. Update MCP README / Kuro consumer docs with request examples.
6. Add UI affordances only after backend contract stabilizes.

## Compatibility Rules

- Existing fields remain valid.
- Consumers should tolerate missing slot keys.
- New slot keys are additive.
- `payload_ref` points to existing payload path; it is not guaranteed to be JSONPath-complete yet.
- A slot with `planned` is a product contract promise, not available data.
