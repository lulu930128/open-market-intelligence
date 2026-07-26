# Productized Market Payload Contract Progress

Last updated: 2026-07-07

## Current Status

Status: contract skeleton is now connected through backend, MCP, and OMI frontend Ask Dock; remaining work is Kuro-side consumption and market-by-market data enrichment.

## Completed

- 確認 `docs/product/` 仍是 TODO 範本，尚不能作為更高優先級產品事實。
- 確認既有 AI contract baseline 在 `docs/agent-runs/omi-ai-decision-core/ContractMap.md`。
- 確認 backend 已有 `market_data_params.include_intraday`、`payload_level`、`intraday_limit` 的初步台股盤中分級能力。
- 新增台股個股 compact `slots`。
- 新增台股指數 compact `slots`。
- 新增台股市場 overview `data.slots`。
- 新增跨市場 generic compact `slots`，覆蓋 US/JP/KR/crypto 的共用 `_compact_market_context`。
- `ask_finalizer` 會把 compact slots 投影到 public slim result。
- 補 targeted regression tests。
- MCP `omi.ask` 與 direct tools 支援頂層 `include_intraday`、`payload_level`、`intraday_limit`，並合併到 backend `market_data_params`。
- Backend direct GET endpoints for market overview / Taiwan stock context / Taiwan stock brief support `payload_level` and `intraday_limit`.
- Cross-market compact evidence includes top-level `payload_level`; US intraday compact bars now respect summary/compact/standard/full point limits.
- OMI frontend `OmiAskDock` now sends bounded `market_data_params` for intraday requests and renders backend slot status from `result.data.slots` / `result.data.compact.slots`.

## Decisions

- Slot envelope 先用 metadata 與 `payload_ref` 指向既有欄位，不在 slot 內重複塞大包 payload。
- 未完成資料不留空白假裝成功，而是輸出 `planned`、`missing`、`not_requested` 或 `not_applicable`。
- Taiwan-first 不變；跨市場 slot 是 context layer，不把 US/JP/KR/crypto 提升成與台股同等核心。
- MCP 與桌寵只讀 OMI backend contract，不直接接 DB 或 provider。
- MCP 頂層 payload controls 只是 caller convenience；backend canonical shape 仍是 `market_data_params`。
- Frontend 只負責提出 bounded payload preference 與呈現 slot completeness；freshness、market logic、provider policy 仍由 backend 決定。

## Known Gaps

- `payload_level` 對 US intraday 已有裁切；JP/KR 目前沒有 live intraday payload，crypto 仍主要靠 `limit` 控制資料量。
- JP/KR 目前主要是 local-cache-only compact context；盤中 slot 多數仍是 `planned`。
- Crypto slot 還是 generic skeleton，後續應拆成更清楚的 `ohlcv`、`liquidity`、`derivatives`、`event_risk`。
- News/events slot 僅是設計插槽，尚未接 provider policy 與 source attribution。
- Kuro 尚未調整語音/桌寵呈現 slot 狀態；OMI frontend 已有第一版 slot status 顯示。

## Next Step

下一步應讓 Kuro 依 slot status 呈現 ready / missing / planned 狀態，並逐步細化 JP/KR/crypto 的分市場 slot adapter。
