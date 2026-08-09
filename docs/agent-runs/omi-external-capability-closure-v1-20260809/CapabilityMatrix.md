# OMI 對外能力完整矩陣

## 判讀方式

本文件描述 2026-08-09 稽核到的 source/live contract 基線。狀態縮寫如下：

| 縮寫 | 意義 |
|---|---|
| `F` | 已有 public granular fill operation，可由 v4 continuation 下達 |
| `R` | `reader_fetch`，由既有 bounded reader 在 request 內取值 |
| `I` | backend 內部已有工具，但未進 public fill mapping |
| `S` | scheduler/cache owner；read path 不應主動外抓 |
| `C` | cache/local read，沒有對外 refresh action |
| `D` | 由其他 evidence 衍生，應補上 dependency lineage 而非獨立抓取 |
| `P` | private 或 key-required，需 trust/config gate |
| `B` | provider 未接；只能回 blocked contract |
| `X` | deprecated，相容讀取但不可再作為新 consumer 首選 |

「可讀」表示 public ask 能回傳對應資料或明確狀態；「補值閉環」表示缺資料時 consumer 能取得可執行 action／job 或明確不能補的原因。

## 22 種 public target

| target.type | scope | id | 目前可讀 | 目前補值 | 判定與 v1 缺口 |
|---|---|---:|---|---|---|
| `auto` | `auto` | 否 | 是 | 不適用 | 只負責解析單一 target；需確保解析後沿用該 target 的完整 resolution |
| `market` | `market` | 否 | 是 | 不閉環 | 廣度、indices、chips、screening、跨市場多為 C/S/D；Ask tool stage 沒有 market refresh session |
| `data_freshness` | `data_freshness` | 否 | 是 | 不應補 | 診斷讀取完整；需明確標示它不等於 refresh action |
| `tw_stock` | `stock` | 是 | 是 | 部分閉環 | 7 個 F、5 個 R；cross-market、company/actions、events/regulation 仍為 I/C/D |
| `tw_watchlist` | `watchlist` | 是 | 是 | 不完整 | backend 有 `tw.refresh_watchlist_evidence`，但不是 public fill；需 composite mapping 或明確 scheduler/cache ownership |
| `tw_index` | `tw_index` | 是 | 是 | 不完整 | quote/intraday/daily/index contribution 可讀，但沒有完整 public fill mapping |
| `tw_futures` | `tw_futures` | 是 | 是 | 不完整 | quote/K/derivatives/TAIFEX cache 可讀，已有專用 refresh route/scheduler，但 Ask continuation 無對應 action |
| `us_stock` | `us_stock` | 是 | 是 | 部分閉環 | quote/intraday/daily/SEC facts 有 F；profile/actions 有 I，revenue/short volume/breadth 只有 C/D |
| `jp_stock` | `jp_stock` | 是 | 是 | 部分閉環 | quote/intraday/daily 有 F；profile、revenue、financials 只有 C/缺值語意 |
| `jp_index` | `jp_index` | 是 | 是 | 主要行情閉環 | quote/intraday/daily 有 F；breadth、technical 是 C/D |
| `kr_stock` | `kr_stock` | 是 | 是 | 部分閉環 | quote/intraday/daily 有 F；profile、revenue、financials 只有 C/缺值語意 |
| `kr_index` | `kr_index` | 是 | 是 | 主要行情閉環 | quote/intraday/daily 有 F；breadth、technical 是 C/D |
| `crypto_market` | `crypto_market` | 否 | 是 | 不完整 | aggregate quote/order book/derivatives 可讀，但 fill mapping 只套用 `crypto_asset` |
| `crypto_asset` | `crypto_asset` | 是 | 是 | 主要行情閉環 | ticker、OHLCV、order book、derivatives 共 5 個 F；technical 為 D |
| `resource_asset` | `resource_asset` | 是 | 是 | 不完整 | Yahoo best-effort cache 可讀，capability status 說可 bounded refresh，但 v4 沒有 public fill action |
| `portfolio` | `portfolio` | 否 | 受信任 caller | 不應外抓 | P；只讀本機 holdings/valuation，不能由未受信任 adapter 取得 |
| `us_macro` | `us_macro` | 是 | 是 | 不完整 | local cache 可讀，FRED refresh 需 key；v4 沒有 key-aware action/deferred contract |
| `us_watchlist` | `us_watchlist` | 是 | 是 | 不完整 | ranking/radar/coverage 可讀，沒有 public fill；configured universe 不是全市場 |
| `jp_watchlist` | `jp_watchlist` | 是 | 是 | 不完整 | local ranking/radar/coverage；沒有 public fill |
| `kr_watchlist` | `kr_watchlist` | 是 | 是 | 不完整 | local ranking/radar/coverage；沒有 public fill |
| `source_health` | `source_health` | 否 | 是 | 不應補 | runtime/provider incident diagnostics；不可冒充 capability readiness |
| `capability_status` | `capability_status` | 否 | 是 | 不應直接補 | 目前只列 15 個 curated provider contract，未覆蓋 57 項正式 capability；v1 必須合併兩層 view |

## 57 項 capability

| # | capability | 適用 scope | 現況 | 補值閉環判定 | v1 處理 |
|---:|---|---|---|---|---|
| 1 | `target.identity` | `*` | D | request/resolver 產生 | registry 標成 `derived_identity`，無 action |
| 2 | `quote.snapshot` | TW/US/JP/KR stock、TW/JP/KR index、TW futures、crypto、resource | R/F/C 混合 | TW stock=R；US/JP/KR/crypto asset=F；其他 scope 無共同 resolution | 拆成 scope-specific resolution，禁止只看 capability id 判斷可補性 |
| 3 | `quote.order_book` | TW stock | R | bounded TW reader 可取 | 保留 R，記錄 session/open-market 條件與 provider event time |
| 4 | `quote.auction` | TW stock、TW index | R/C | stock 有 R；index 無 fill | 分 scope 登記；index 若無獨立 provider action則回 cache/derived limitation |
| 5 | `quote.official_close` | TW stock、TW index | R/C | stock 有 R；index 無 fill | 分 scope 登記，保留 official/date/session semantics |
| 6 | `intraday.bars` | stock/index/futures/crypto/resource/market | R/F/C 混合 | TW stock=R；US/JP/KR/crypto asset=F；market/futures/resource/crypto market 無 public action | 建立 scope-specific mapping；非 action scope 必須顯示 cache/scheduler owner |
| 7 | `daily.ohlcv` | stock/index/futures/crypto/resource | F/C 混合 | TW/US/JP/KR stock、JP/KR index、crypto asset 有 F；TW index/futures/resource 無 F | 補現有 service action或明確 S/C；不可把同名 capability 全域標成 executable |
| 8 | `technical.structure` | stock/index/futures/crypto/resource | D | 依 quote/OHLCV 衍生 | 加 `depends_on`、input freshness 與 recompute policy；不新增 provider call |
| 9 | `chips.institutional` | TW stock | F | `tw.refresh_institutional` | 保留 granular action、交易日與 row bounds |
| 10 | `chips.margin` | TW stock | F | `tw.refresh_margin` | 保留 granular action、T+資料日 semantics |
| 11 | `broker_branch.summary` | TW stock | F | `tw.refresh_broker_branch` | 保留 granular action、provider/quota 與 available-date 限制 |
| 12 | `ownership.distribution` | TW stock | F | `tw.refresh_shareholding` | 保留 granular action、週期與歷史範圍限制 |
| 13 | `fundamentals.revenue` | TW/US/JP/KR stock | F/C 混合 | 只有 TW 有 `tw.refresh_revenue` | US/JP/KR 分別標成 cache-only、not connected 或另接 provider，不得沿用 TW action |
| 14 | `fundamentals.financials` | TW/US/JP/KR stock | F/C 混合 | TW 與 US SEC facts 有 F；JP/KR 無 | 分 scope 登記；JP/KR 缺口回明確 provider/readiness |
| 15 | `cross_market.overnight` | TW stock | I/D | planner 有 `cross_market.refresh_context`，fill plan 無 action | 將 composite action映射到 produced capabilities，或標 scheduler/cache；需 reconciliation |
| 16 | `cross_market.relations` | TW stock | I/D | 同上 | 納入同一 composite refresh，保留 point-in-time/proxy/lineage |
| 17 | `cross_market.parity` | TW stock | I/D | 同上 | 納入同一 composite refresh，保留 ADR/ETF/FX scope 與 stale semantics |
| 18 | `company.profile` | TW/US/JP/KR stock | I/C | US 有 internal `us.refresh_company_profile`，其他 scope 無 public action | 正式映射 US action；其餘 scope回 cache/provider contract |
| 19 | `corporate.actions` | TW/US stock | I/C | US 有 internal `us.refresh_corporate_actions` | 正式映射 US action；TW 維持 cache/provider-owned 並說明 |
| 20 | `market.short_volume` | US stock | C | 可讀但無 public fill | 登記資料 owner、日期/coverage；無 service 時回 unfillable reason |
| 21 | `market.breadth` | market/index/futures/US/crypto | C/S/D | 不同 scope 含義不同，無 public fill | 拆 scope、universe、coverage、provider；禁止以 sample breadth 冒充 full market |
| 22 | `market.indices` | market | C/S | local/current market context | 登記 scheduler/cache owner與 expected session，不新增 read-path side effect |
| 23 | `events.upcoming` | TW stock | C | `cache_only` | 保留 C；fill plan歸入 deferred/unfillable，不能誤列 action |
| 24 | `events.calendar` | market | C | `cache_only` | 保留 C；若未接新聞/event provider，顯示 provider gap |
| 25 | `events.history` | TW stock | C | `cache_only` | 保留 C，清楚日期範圍與 retention |
| 26 | `regulation.disposition` | TW stock | C | `cache_only` | 保留 C；來源日與法律/市場狀態不可由空值推斷 |
| 27 | `regulation.trading_restrictions` | TW stock | C | `cache_only` | 保留 C；empty 與 not applicable 分離 |
| 28 | `market.sectors` | market | S | scheduler cache 或 daily fallback | 登記 scheduler job、last success、fallback；不產生即時 fill action |
| 29 | `market.index_contributions` | market、TW index | C/R | 授權時 bounded external read，但未納入 v4 fill | 若 reader 已存在則正式登記 R；否則回 deferred policy reason |
| 30 | `market.institutional_flow` | market | C/S | local market context | 登記官方資料 cadence、coverage 與 scheduler owner |
| 31 | `market.margin_short` | market | C/S | local market context | 同上；避免把 stock-level margin 合併成錯誤全市場數字 |
| 32 | `market.sample_ranking` | market | X | deprecated bounded local sample | 保留 alias，consumer 改讀 screening/full-market capability |
| 33 | `market.cross_market` | market | I/C/D | internal cross-market refresh 存在，public fill 無 | 映射 composite refresh 或 scheduler cache，保留 point-in-time lineage |
| 34 | `market.chips` | market | C/S | TWSE/TPEX aggregate + DB coverage | 登記兩種 scope，禁止 DB sample 冒充交易所全市場 |
| 35 | `screening.ranking` | market | C | `cache_read_only_no_refresh` | 保留 C，公開 sample/universe/coverage/metric date |
| 36 | `screening.coverage` | market | C | `cache_read_only_no_refresh` | 保留 C，成為 ranking readiness 的 guardrail |
| 37 | `screening.intraday` | market | S | scheduler-owned cache | 顯示 job/last success/coverage；read path 不刷新全市場 |
| 38 | `market.hot_groups` | market | S | scheduler-owned cache | 同上，加入 group universe/version |
| 39 | `market.volume_state` | market | D/C | 由市場量能與 baseline 衍生 | 登記 dependencies/warm-up/coverage，不建立 provider action |
| 40 | `derivatives.positioning` | TW futures | C/S | TAIFEX official daily cache | 對應 existing bounded derivatives refresh/scheduler，加入 composite fill 或 deferred job |
| 41 | `derivatives.structure` | TW futures | C/S/D | option chain/large traders/term structure | 同上；官方與 derived Greeks/basis 必須分欄與分 freshness |
| 42 | `watchlist.ranking` | TW/US/JP/KR watchlist | C/I | local read；TW 有 internal composite refresh | 登記 per-market cache owner；只有有 bounded refresh 的 scope列 composite action |
| 43 | `watchlist.radar` | TW/US/JP/KR watchlist | C/S | backend radar/cache | 登記 engine/version/outcome readiness；不因資料缺口把 engine quality 混掉 |
| 44 | `watchlist.coverage` | TW/US/JP/KR watchlist | D | 由 universe/result 計算 | 登記 dependencies，無 provider action |
| 45 | `portfolio.summary` | portfolio | P/D | trusted local data | 保留 private，顯示各市場/幣別 coverage |
| 46 | `portfolio.holdings` | portfolio | P/C | trusted local data | 不對 public adapter 開放，不直接讀 DB |
| 47 | `portfolio.valuation` | portfolio | P/D | local price cache + holdings | 不靜默合併幣別；缺價/stale 價可見 |
| 48 | `macro.series` | US macro | P/C | FRED metadata/cache | key/config readiness 顯示在 registry，read 不刷新 |
| 49 | `macro.observations` | US macro | P/C | FRED cache，refresh 需 key | 新增 key-aware bounded action 或明確 `key_required` deferred |
| 50 | `resource.metadata` | resource | C | local instrument registry | 保留 C，provider/watch-only/delay semantics 可見 |
| 51 | `crypto.order_book` | crypto asset/market | F/C 混合 | asset 有 `crypto.refresh_order_book`；market 無 | 分 scope；market aggregate 保持 read/cache 或新增 bounded composite |
| 52 | `crypto.derivatives` | crypto asset/market | F/C 混合 | asset 有 `crypto.refresh_derivatives`；market 無 | 同上，保留 exchange/instrument/funding event-time |
| 53 | `diagnostics.capabilities` | capability status | C | 目前只投影 curated 15 | 擴成 full registry view + provider contract view，保留 compact filter |
| 54 | `diagnostics.data_freshness` | data freshness | C | diagnostic read | 保留 read-only，連結 expected date/source health，不執行 refresh |
| 55 | `diagnostics.source_health` | `*` | C | canonical source-health | 保留 canonical；加入 age/checked_at，與 request-local evidence 分離 |
| 56 | `source.health` | `*` | X | deprecated alias | 保留相容投影，replacement 指向 `diagnostics.source_health` |
| 57 | `data.freshness` | `*` | C/D | canonical freshness summary | 保留每 capability evidence status、expected/as-of/session，不當作 operation result |

## 26 個 backend allowed tools 與 public fill 差異

### 已進 public fill registry 的 20 個

| 市場 | operations |
|---|---|
| TW | `tw.refresh_daily_price`、`tw.refresh_institutional`、`tw.refresh_margin`、`tw.refresh_broker_branch`、`tw.refresh_shareholding`、`tw.refresh_revenue`、`tw.refresh_financials` |
| US | `us.read_intraday_trend`、`us.refresh_daily_price`、`us.refresh_sec_facts` |
| JP | `jp.read_intraday_trend`、`jp.refresh_daily_price` |
| KR | `kr.read_stock_intraday_trend`、`kr.read_index_intraday_trend`、`kr.refresh_daily_price`、`kr.refresh_index_daily_price` |
| Crypto | `crypto.refresh_ticker`、`crypto.refresh_ohlcv`、`crypto.refresh_order_book`、`crypto.refresh_derivatives` |

### backend 可執行但 public fill 未登記的 6 個

| operation | 既有用途 | 目前缺口 | v1 決策 |
|---|---|---|---|
| `cross_market.refresh_context` | 更新 TW cross-market context | planner 可自動用，但 continuation 不會列 | 登記 composite action 與 produced capabilities |
| `tw.refresh_stock_evidence` | TW stock composite refresh | internal planner 可用 | 保留 composite convenience，但 granular actions仍是 consumer 首選 |
| `tw.refresh_watchlist_evidence` | TW watchlist refresh | Ask auto path可用 | 登記 bounded composite action或明確 scheduler/deferred |
| `us.read_sec_fundamentals` | 讀/補 SEC fundamentals | 與 `us.refresh_sec_facts` ownership 重疊 | 合併 canonical operation 或標 alias/deprecated，禁止雙重計費 |
| `us.refresh_company_profile` | US company profile | capability 無 fill mapping | 映射 `company.profile` |
| `us.refresh_corporate_actions` | US corporate actions | capability 無 fill mapping | 映射 `corporate.actions` |

## 15 項 provider readiness

| capability contract | 現況 | provider | 可接程度 | v1 處理 |
|---|---|---|---|---|
| `tw_full_market_breadth` | connected | TWSE/TPEX | 已接 | 納入 full registry 與 scope/coverage contract |
| `tw_market_chips_rankings` | connected | TWSE/TPEX local cache | 已接 | 明確 scheduler/cache owner |
| `tw_futures_institutional_oi_pcr` | connected | TAIFEX official daily | 已接 | 映射 TW futures composite refresh/job；保留非夜盤即時限制 |
| `kr_intraday` | connected | Yahoo chart/Naver cache | 已接 | 已有 F；保留 trust gate |
| `resource_quotes_ohlcv` | connected | Yahoo chart best effort | 可補閉環 | 加 public bounded action或明確 cache owner；保留 delayed/watch-only |
| `portfolio_context` | connected_private | OMI local portfolio | 已接但私有 | 保留 server trust gate |
| `fred_macro` | connected_key_required_for_refresh | FRED | 可補閉環 | 新增 key-aware status/action，沒有 key時不是 generic missing |
| `tw_options_chain_iv_greeks` | connected_derived | TAIFEX OpenAPI | 已接 | 對應 futures composite refresh，官方/derived 分離 |
| `tw_large_trader_positions` | connected | TAIFEX OpenAPI | 已接 | 對應 futures composite refresh/scheduler |
| `tw_futures_basis_term_structure` | connected_derived | TAIFEX + TAIEX cache | 已接 | 對應 futures composite refresh，依賴同日 spot close |
| `news_events` | provider_not_connected | 未選 | 不能直接接 | 需 attribution、license、dedupe、entity mapping、retention、quota 決策 |
| `us_options_flow_earnings` | provider_not_connected | 未選 | 不能直接接 | options chain/flow 與 earnings 分成兩份 provider/quota contract |
| `jp_tdnet_disclosures` | provider_not_connected | TDnet candidate | 需設計後接 | issuer mapping、document identity/storage、language、bounded polling |
| `kr_opendart_disclosures` | provider_not_connected | OpenDART candidate | 需 key/設計後接 | key、corp-code mapping、report identity、bounded polling/backfill |
| `hk_market` | provider_not_connected | 未選 | 需新市場 capability | 先建 symbol/calendar/daily/intraday/freshness，再加 watchlist/UI |

## 目前可立即收斂的完整範圍

不需採購新 provider 即可完成：

- 將 20 個 public fills、6 個 internal tools、reader fetch、scheduler/cache 與 derived dependencies 合併進單一 registry。
- 補 cross-market、US profile/actions、TW watchlist/futures、resource、FRED 的 action/deferred/job 契約。
- 將 capability status 從 15 項精選清單擴成 57 項正式 registry + 15 項 provider view。
- 補 background job read tool、fill partition invariant、schema limit、env 文件與 snapshot parity。
- 同步 HTTP、repo MCP、獨立 OMI_search 與 ExternalInterfaces 文件。

需要使用者另行決策才可完成 provider 接入：

- 新聞/事件 provider 與授權。
- US options flow 與 earnings providers。
- TDnet 文件保存、語言與 polling policy。
- OpenDART key 與 report normalization。
- 港股 symbol/calendar/quote/daily/intraday provider 組合。
