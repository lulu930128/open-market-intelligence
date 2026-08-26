# CP6 Taiwan Dataset Inventory

## Audit rule

本表盤點的是會承載台股市場事實、直接支援研究/AI/API，或作為其必要durable evidence的production dataset family。純UI設定、watchlist、AI log、job log與portfolio/account不列入Market Data catalog。單一family可包含多張normalization/quality/supporting tables，但只能有一個lifecycle owner。

`ready`不等於資料目前healthy，只表示schema、lineage與bounded lifecycle足以接入共同平台。`compatibility`表示有實際讀寫路徑但仍由legacy service擁有transaction/provider semantics。`lineage_gap`表示現有row不足以追到raw receipt或canonical time/state，不能直接宣告platform-ready。

## Inventory

| Dataset ID | Family / payload | Durable storage | Current owner / refresh path | Lineage state | CP6 status |
| --- | --- | --- | --- | --- | --- |
| `tw.quote.snapshot` | request-time `QuoteObservation` | `taiwan_stock_quote_snapshot` + `source_registry` + `raw_fetch_result` | `public_quote_platform` / `tw.acquire_public_last_trade_quote` | 0068補source/raw/received/event/session/trade-state；legacy row fail closed | ready, CP5 wired |
| `tw.intraday.bars` | stock intraday bars | `market_intraday_bar` | `intraday.get_market_intraday_history`; GET仍可refresh Yahoo | provider/source但無raw receipt、received/finalization | lineage_gap；不得advertise repairable |
| `tw.daily.ohlcv` | completed-session `BarObservation` | `market_daily_price` + source/raw | `daily_ohlcv_platform` / `tw.refresh_daily_price` | source/raw/event/fetched/hash可回溯 | ready, CP2 wired |
| `tw.daily.ohlcv.full_market` | full-market coverage | coverage checkpoint + daily rows | EOD lifecycle / bounded reconcile | checkpoint與canonical rows可交叉驗證 | ready, CP3 wired |
| `tw.technical.daily` | backend-authoritative indicator/structure series | derived from resolved `tw.daily.ohlcv`; no duplicate persisted value table | `technical_indicator_gateway` + `technical_evidence` | component lineage指向selected official bars、raw receipt、algorithm/version/parameter contract | ready, CP7 wired；non-refreshable derived projection |
| `tw.market_breadth.daily` | official breadth | derived from coherent official daily receipt + universe | `official_breadth_platform` | 繼承同venue/date/raw receipt；partition守恆 | ready, CP4 wired |
| `tw.market_index.daily` | official index observation | `market_index_daily_stat` + source/raw | `official_index_platform` / bounded refresh | 0067補source/raw；legacy row fail closed | ready, CP4 wired |
| `tw.chips.market.daily` | market-level institutional/options/margin state | `market_chip_daily` | `market_chips.refresh_market_chip_daily` + background job | `source_details_json`但無source/raw FK | lineage_gap |
| `tw.chips.institutional.daily` | per-stock institutional flow | `institutional_trade_daily` + source/raw | `ensure_stock_daily_metrics` / `tw.refresh_institutional` | source/raw FK完整，writer仍是compatibility | compatibility |
| `tw.chips.margin.daily` | per-stock margin/short | `margin_trading_daily` + source/raw | `ensure_stock_daily_metrics` / `tw.refresh_margin` | source/raw FK完整，writer仍是compatibility | compatibility |
| `tw.chips.broker_branch.daily` | Top15 censored branch evidence + quality/features | trade + snapshot quality + behavior feature tables | broker-branch refresh/job | trade/quality有source/raw；derived feature有source/input fingerprint | compatibility；必須保留censored semantics |
| `tw.ownership.shareholding.weekly` | TDCC distribution | `shareholding_distribution_weekly` + source/raw | history backfill / `tw.refresh_shareholding` | source/raw FK完整 | compatibility |
| `tw.fundamentals.revenue.monthly` | monthly revenue | `monthly_revenue` + source/raw | history backfill / `tw.refresh_revenue` | source/raw/report date完整 | compatibility |
| `tw.fundamentals.financials.quarterly` | filing/facts/normalized financial evidence | legacy quarterly metrics + filing/parse/fact/action/normalization/basis tables | financial history + MOPS filing pipeline / `tw.refresh_financials` | core filing與legacy metric有source/raw；derived rows有explicit lineage | compatibility；需統一read projection owner |
| `tw.company.profile` | listed-company profile | `stock_profile` + source/raw | fundamental snapshot refresh | source/raw/report date完整 | compatibility |
| `tw.events.corporate` | ex-dividend/conference calendar/history | local typed cache + `provider_event` telemetry | corporate-event refresh/scheduler | cache item有source URL/time但非shared raw receipt store | lineage_gap |
| `tw.etf.profile` | ETF profile | `taiwan_etf_profile` | `tw_etf.refresh_taiwan_etf` | source URL/fetched only，無raw receipt FK | lineage_gap |
| `tw.etf.nav.daily` | ETF NAV/discount | `taiwan_etf_nav_daily` | same multi-resource refresh | source URL/fetched only | lineage_gap |
| `tw.etf.pcf.snapshot` | PCF header/components | `taiwan_etf_pcf_snapshot` + component | issuer-specific registry | source URL/fetched only；不同issuer contract | lineage_gap |
| `tw.etf.inav.snapshot` | estimated NAV | `taiwan_etf_inav_snapshot` | issuer-specific registry | source URL/fetched only | lineage_gap |
| `tw.futures.quote.snapshot` | futures quote | `taiwan_futures_quote_snapshot` | TAIFEX/KGI compatibility refresh | provider/raw JSON/fetched但無source/raw receipt FK | lineage_gap；KGI port deferred |
| `tw.futures.intraday.bars` | futures intraday bars | `taiwan_futures_intraday_bar` | TAIFEX MIS compatibility refresh | provider/source但無raw receipt/finalization | lineage_gap |
| `tw.futures.daily.bars` | futures daily bars | `taiwan_futures_daily_bar` | TAIFEX daily HTML refresh | raw JSON/fetched但無source/raw receipt FK | lineage_gap |
| `tw.derivatives.option_chain.daily` | option chain/Greeks | `taiwan_option_chain_daily` | `tw_derivatives.refresh_taiwan_derivatives` | provider/source URL/fetched；無raw receipt FK | lineage_gap |
| `tw.derivatives.large_trader.daily` | large-trader Top5/10 | `taiwan_derivatives_large_trader_daily` | same TAIFEX refresh | 無raw receipt FK；Top5/10 scope不得外推成全市場 | lineage_gap |
| `tw.derivatives.term_structure.daily` | futures curve/basis | `taiwan_futures_term_structure_daily` | same TAIFEX refresh | derived from futures rows + spot，但沒有component raw lineage | lineage_gap |
| `tw.market.minute_state` | derived market minute state | `taiwan_market_minute_state` | market-state job | source category/time/quality有欄位，缺raw component IDs | compatibility-derived |
| `tw.stock.intraday.state` | derived per-stock intraday state | `taiwan_intraday_stock_state` | market-state job | provider/component text，缺raw component IDs | compatibility-derived |

## Ordering decision

1. 先建立market-owned typed catalog與executable operation registry，讓所有family都有truthful owner、read/refresh path、bounds、postcondition、lineage gate與convergence status。
2. 先把已有source/raw lineage的chips、shareholding、revenue、financial/profile family接到catalog與health projection；不重寫已成熟parser。
3. ETF是後續第一個適合補raw lineage的multi-resource family：provider registry已存在，可用來驗證「新增issuer只改catalog + adapter」。CP6先如實登錄現有lineage gap、operation bounds與health evidence；在沒有transaction/migration實證前不以大範圍schema rewrite假裝完成收斂。
4. TAIFEX derivatives/futures保留typed dataset-specific tables，後續補raw receipt/component lineage；KGI quote provider仍不作CP6依賴。
5. Intraday bars與derived market state不在證據不足時宣告repairable。舊GET side effect、snapshot-to-bar與component lineage debt留到CP7/CP8逐項切除。

## Hard gates

- `advertised=true`必須有可解析的read projection；不能只填字串placeholder。
- `refreshable=true`必須有可執行operation、bounded policy與DB reread postcondition。
- `lineage_gap`不得被`source`文字或`raw_payload_json`冒充source/raw receipt linkage。
- ETF/derivatives的multi-provider部分不得merge成單一假provider；derived dataset必須列出component lineage與time skew。
- `unknown`、Top15 censored absence、no quote、no trade、not released與not applicable維持不同狀態。

## Point-in-time evidence

`artifacts/cp6-production-dataset-storage-evidence.json`是在`tw.technical.daily`加入catalog前取得的production SQLite唯讀快照，因此保留當時27個dataset、18個operation與27個storage probe，不回寫成事後數字。現行catalog為28個dataset、18個bounded operation、28個health probe；第28個`tw.technical.daily`是由resolved daily OHLCV即時計算的derived projection，production DB沒有也不應新增重複indicator value table。
