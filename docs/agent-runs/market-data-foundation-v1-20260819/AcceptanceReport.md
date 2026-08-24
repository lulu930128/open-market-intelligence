# OMI Market Data Foundation v1 驗收報告

## 結論

- 狀態：`source-complete, runtime adoption pending`。
- M0-M6 source implementation 與測試已完成。
- Legacy quote-depth 仍是唯一 outward selection / persistence owner；canonical path 目前只允許 `off`、`shadow`、`compare`，預設 `off`。
- 未執行 runtime restart、KGI live login/subscription、external provider smoke、production DB migration/write、commit、push 或 release。

## 已交付能力

### Canonical contracts

- `InstrumentKey` 使用 market、venue、symbol、instrument type 建立穩定 identity；listed instrument 缺 venue 時 fail closed。
- Market Session、Instrument Tradability、Trade Observation State、Regulatory Flags 與 Freshness 為獨立維度。
- Decimal price、timezone-aware event/received/fetched time、bar finalization、depth capability、TW lots→shares lineage 與 US shares 語意均有 typed validation。
- Provider Resource Health、Dataset Health、Resolved Evidence Health 分層；resolved health 額外保留 facts/research usability 與 limitations。
- Resolved candidate summary 上限為 8，不包含 raw provider payload。

主要 internal schema versions：

| Contract | Version |
| --- | --- |
| Quote Observation | `omi.market.quote.v1` |
| Depth Observation | `omi.market.depth.v1` |
| Auction Observation | `omi.market.auction.v1` |
| Bar Observation | `omi.market.bar.v1` |
| Trading Status | `omi.market.trading_status.v1` |
| Canonical Snapshot | `omi.market.snapshot.v1` |
| Resolved Quote / Depth / Bar / Trading Status | `omi.market.resolved_*.v1` |
| Data Requirement / Acquisition Result | `omi.market.data_requirement.v1` / `omi.market.acquisition_result.v1` |
| Dataset Registry | `omi.market.dataset_registry.v1` |
| Shadow Comparison / Telemetry | `omi.market.shadow_comparison.v1` / `omi.market.shadow_telemetry.v1` |

### Direct adapters and pure resolution

- KGI TW raw quote 可直接產生 canonical quote/depth/auction/trading-status observation，不 import 或呼叫 `_kgi_quote_to_mis_message()`。
- TWSE MIS message 直接映射相同 contracts；`z/y/ts/pz/ps` 不進 shared contract。
- 試撮價不會成為 last trade；cumulative volume 不會製造不存在的 last trade price。
- KGI `suspend` 只保留為 non-official broker hint；official exchange evidence 在 Trading Status Resolver 優先。
- Resolver 只選擇 caller 已取得的 candidates，無 provider、network、DB、scheduler、AI 或 global manager import。
- `cache_only` 與 internal `completed_session` 不允許 external acquisition；`require_live` 不滿足時回 policy-unsatisfied，不冒充 live。
- `MarketDataAcquisitionPort` 只定義 02 的 integration interface，本專案沒有 production Research Lease implementation。

### Dataset Registry 與 capability truth

| Dataset | Owner / read | Refresh truth |
| --- | --- | --- |
| `tw.quote.snapshot` | `app.market.quote_depth` / `get_taiwan_stock_quote_depth` | reader-owned，Foundation 不宣告 repair operation |
| `tw.intraday.bars` | `app.market.intraday` / `get_market_intraday_history` | reader-owned，Foundation 不宣告 repair operation |
| `tw.daily.ohlcv` | `app.market.daily_prices` / `get_stock_daily_prices` | `tw.refresh_daily_price`，有 call/time/range bounds 與 postcondition |
| `us.intraday.bars` | `app.us_market.service` / `get_us_stock_intraday_trend` | `us.read_intraday_trend`，bounded request operation |
| `us.daily.ohlcv` | `app.us_market.service` / `get_us_daily_prices` | `us.refresh_daily_price`，有 call/time/range bounds 與 postcondition |

- AI projection registry 對 TW/US 的 `quote.snapshot`、`intraday.bars`、`daily.ohlcv` 具有 callable projector 與非 placeholder fixture payload。
- `instrument.trading_status` 在尚無 outward projector 時明確 `advertised=False` 並回 truthful unavailable fixture。
- `technical.structure` 已縮為真正有 projection 的 `stock / tw_index / tw_futures` + market `TW`；不再向 `us_stock` 虛假宣告支援。
- Public `omi.decision.v4` realtime policy 仍只有 `cache_only / prefer_live / require_live`；`completed_session` 保持 internal。

### Shadow / compare

- `CANONICAL_MARKET_DATA_MODE` 預設 `off`，設定只接受 `off / shadow / compare`；reserved `canary / on` 在 Foundation fail closed。
- KGI/MIS canonical shadow 使用既有 service 已取得的同一份 payload，不新增 fetch、login、subscription 或 DB write。
- Adapter、comparator、metrics、logging 任一 failure 都不會中斷 legacy quote response。
- Mismatch 上限 16、metric series 上限 128；telemetry 只含 mode/provider/resource/market phase/category/reason code/count，不含 raw payload、credential、account identity。
- Regular KGI 與 MIS fixture 為 zero mismatch；MIS trial fixture 為 zero mismatch；KGI trial 的 legacy `OHLC=0` 對 canonical `missing` 產生三筆明確 `LEGACY_ZERO_NORMALIZED_TO_MISSING` representation mismatch。

## Public compatibility

- HTTP / SSE / MCP / frontend outward quote shape未切到 canonical contract。
- `omi.decision.v4` request enum未新增 `completed_session`。
- `technical.structure / us_stock` truthful scope修正使 public contract digest 合理變更；backend manifest、MCP offline snapshot與 internal catalog hash已同步並通過 contract tests。
- 未修改 frontend code；既有 frontend dirty changes不屬於本任務。

## 驗證證據

- Foundation targeted：`48 passed`。
- KGI / quote-depth / MIS / shadow targeted：`56 passed, 10 subtests passed`。
- Foundation + KGI/MIS + AI/public/API targeted matrix：`196 passed, 320 subtests passed`。
- AI/MCP drift修正後 targeted：`18 passed, 66 subtests passed`。
- Final repo wrapper：`scripts/run-safe-validation.ps1 -Profile backend`。
  - backend compileall：passed。
  - backend pytest：`1907 passed, 801 warnings in 251.81s`。
  - `git diff --check`：passed。
  - Log：`.tmp/validation/20260819-201627/`。
- 第一次 sandbox 內 wrapper 的 tests 跑到 100%，但 pytest temp cleanup 被 sandbox `PermissionError` 阻擋；在 sandbox 外依相同 wrapper重跑後得到上述可靠結果。

## 尚未 production-accepted

- Launcher/runtime 尚未採用或驗證新 source；目前存在的 3000/8400 listeners只被 wrapper觀察，未接管或重啟。
- 沒有 KGI live provider smoke、Research Lease、KGI US、Yahoo/AlphaVantage adapter、consumer canary/on 或 legacy removal。
- Pure resolver尚未成為 quote API / AI / MCP 的 production selection owner。
- Dataset Registry目前是 source-level lifecycle truth與validator，尚未接管 scheduler/repair執行。
- Trading status outward capability尚未 advertised；official exchange/regulator evidence integration留給後續。
- 沒有 Foundation DB schema、migration或persistent shadow telemetry。

## Gate 狀態

- Foundation source-complete：通過。
- Gate G1 runtime acceptance：未授權、未執行。
- Commit / push / PR / release：未授權、未執行。
