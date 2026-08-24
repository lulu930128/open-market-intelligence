# OMI 美股 First-Class Market：Shared Research 與 Consumer Convergence

## Authorization state

- 2026-08-23使用者已明確授權開始第二塊source implementation，並沿用前一輪對OMI services restart後繼續工作的授權。
- 本輪授權包含backend／frontend localized mutation、targeted tests、safe validation、OMI services restart與本機runtime／UI／MCP acceptance。
- External provider refresh、DB migration／write、commit、push與release未獲授權；本輪research read path保持cache-only。
- 使用者將在本輪完成後進行外部檢查；外部檢查不取代本輪source、runtime與consumer-visible驗證。

## Goal

- 將現有backend/app/market/technical_evidence.py中的可重用演算法抽成provider-neutral Shared Technical Engine，由Canonical OHLCV與明確Market Analysis Profile驅動，同時保持TW既有結果與outward contract相容。
- 先讓美股daily technical.indicators成為真實backend capability，再逐步建立technical.structure、current_state、支撐／壓力、breakout／divergence與relative strength等研究證據。
- 將1m → 5m／15m／30m／1h／4h聚合移回backend，使用session-aware、timezone-aware、partial-bar-aware contract，停止frontend自行擁有K棒語意。
- 在完整、版本化universe與coverage contract成立後，逐步建立US breadth、sectors與hot groups；sample／index-membership不得冒充full market。
- 讓Frontend、MCP與Kuro只消費backend-owned evidence與omi.decision.v4，不自行重算technical、freshness、provider selection或market semantics。
- 保留現有美股高密度研究工作台的功能與使用習慣；本工作流做資料與語意收斂，不以視覺改版掩蓋contract缺口。

## Non-goals

- 不在本工作流新增或重寫Yahoo、Alpha Vantage、KGI US provider IO、cross-provider fallback、research lease或canonical adapter；它們屬於第一塊。
- 不把Research Engine變成猜漲跌、保證績效、自主交易或單一buy／sell分數工具。
- 不把portfolio holdings、cost、cash或account health放進Market Data Foundation；portfolio universe只能作為明確input scope。
- 不在coverage不足時宣稱full-market breadth、sector rotation或hot groups ready。
- 不以frontend client-side aggregation／indicator計算作為canonical AI evidence。
- 不一次重寫3812行USStockDetailPanel、不做大型design system替換、不新增UI library。
- 不先做所有indicator與所有timeframe；先完成最小可信daily profile，再逐步擴張。
- 不執行無界全市場回補、未批准外部API refresh、付費資料抓取或大型DB schema變更。

## Hard constraints

### Dependency and ownership

- 研究依賴方向只能是Resolved／Canonical OHLCV → Shared Research Engine → AI／API projection → Frontend／MCP／Kuro。
- Shared Technical Engine只接收provider-neutral points、market profile與quality context；不得import Yahoo／KGI／Alpha Vantage adapter或自行fallback。
- backend/app/market與backend/app/us_market保留市場特有calendar、benchmark、corporate action與session profile；pure algorithms不得綁SQLAlchemy、router或consumer。
- evidence.data[capability_id]是canonical outward payload；evidence.capability_status與quality決定readiness。

### Numerical and temporal integrity

- technical calculation必須明確使用raw或adjusted price basis，並保留basis、source、as_of、latest completed／provisional period與warm-up狀態。
- MA200、RSI、MACD、ATR等window資料不足時必須partial／insufficient，不得以較短樣本冒充完整。
- Corporate action coverage不足或price discontinuity無法解釋時，technical decision usability必須降級。
- Decimal／price precision、volume unit、NaN／null、duplicate date、missing bar與out-of-order timestamp必須有tests。
- Daily、weekly、monthly與intraday session aggregation不得混淆；extended-hours是否納入必須是contract input與outward metadata。

### Market profile

- TW與US可共享演算法，但參數、calendar、benchmark、currency、session與corporate-action policy由versioned Market Analysis Profile明確定義。
- 第一版US daily profile不得默認等同TW 5／20／60參數；若採MA5／10／20／50／60／200，需定義最小bars與warm-up。
- Relative strength benchmark預設候選SPY，但未確認symbol、price basis與freshness前不得寫死為全US唯一truth。
- US sector／industry taxonomy與universe membership必須有來源、版本、effective date與coverage。

### Consumer convergence

- Frontend不得繼續產生canonical technicalTitle、bullish stack、price-vs-MA或multi-timeframe bars。
- Consumer可以format、layout、local interaction與display sampling，但不得改寫indicator value、period completeness、session或readiness。
- MCP維持thin adapter，不新增US專用研究邏輯或第二套schema。
- Frontend錯誤與provider／refresh狀態沿用shared更新狀態 flow，不新增重複inline error owner。

### Rollout and compatibility

- 先做TW regression-preserving extraction，再啟用US daily indicators；technical.structure與consumer cutover後置。
- 新outward capability採additive projection與compatibility，不一次移除legacy technical fields。
- frontend migration採feature-gated dual-read／compare；backend evidence不ready時保留truthful unavailable，不回退client-side canonical calculation。
- source、runtime、UI-visible adoption與MCP adoption分開驗收。

## Context

- Repo：C:\project\Open Market Intelligence
- Source proposal：`%USERPROFILE%\Downloads\OMI_US_First_Class_Market_Engineering_Plan_v1.txt`
- Task docs：docs/agent-runs/us-first-class-research-consumer-20260823/
- Upstream dependency：docs/agent-runs/us-first-class-foundation-outward-20260823/
- Planning date：2026-08-23（Asia/Taipei）
- Related systems：Shared Technical Engine、US market services、AI capability／decision contract、daily／intraday data plane、full-market coverage、frontend US detail、MCP與Kuro consumers。

### Confirmed current state

- backend/app/market/technical_evidence.py已有canonical indicator points、swings、Fibonacci、divergence、breakout、volume profile、anchored VWAP、relative strength與structure算法。
- 同一模組仍import TW DB model、TAIEX benchmark、TW market service與Taiwan trading calendar；build_tw_stock_technical_evidence是TW-specific owner。
- 現行technical parameter baseline主要是5／20／60，不等於附件提出的US MA5／10／20／50／60／200 profile。
- technical.indicators與technical.structure目前對US target會truthful unsupported；尚無US projection。
- US intraday backend只取Yahoo 1m；frontend自行聚合其他professional timeframes。
- USStockDetailPanel自行計算MA5／20／60、volume MA20、price-vs-MA20與technicalTitle。
- 最新唯讀DB baseline中corporate action symbols為0；直接啟用adjusted／structure分析有高語意風險。
- US EOD checkpoint為7,427 universe中current 1,820、stale 342、missing 5,265；目前不具full-market breadth claim基礎。
- MCP已維持thin adapter，可直接沿用第一塊完成的backend capability與Decision v4 projection。

## Deliverables

- Pure Shared Technical Engine與TW compatibility wrapper，保留既有canonical formula與regression。
- Versioned MarketAnalysisProfile contract，先定義TW compatibility profile與US daily profile。
- US technical data usability gate：price basis、corporate actions、minimum bars、warm-up、freshness、period completeness與decision usability。
- US daily technical.indicators capability與projection，包含MA／EMA、RSI、MACD、ATR、volume state等首批指標及method／parameter metadata。
- US technical.structure與canonical current_state，包含trend、support／resistance、breakout／failure、counter-evidence與limitations。
- Backend-owned session-aware multi-timeframe aggregation contract，支援1m／5m／15m／30m／1h／4h且揭露regular／extended scope與partial bar。
- Versioned US universe／sector／industry membership與coverage model。
- US market.breadth、market.sectors、market.hot_groups的truthfulresearch projection；不足時保留partial／missing／not_applicable。
- Frontend移除client-side canonical aggregation／technical judgement，改讀backend evidence；保留現有layout與操作。
- HTTP／SSE／MCP／Kuro consumer parity與runtime-visible acceptance evidence。
- Performance budget、fixture corpus、TW／US numerical golden tests與持續更新的Progress.md。

## Done criteria

### Shared engine complete

- Pure algorithms不import DB、provider、router、frontend或market-specific calendar。
- TW canonical technical fixture在抽離前後數值、rounding、period completeness與outward schema保持相容。
- MarketAnalysisProfile versioned，US參數、warm-up、benchmark、session與price basis不靠隱性default。

### US research complete

- US daily technical.indicators在足夠且可用的resolved OHLCV上產生deterministic evidence；不足時truthful partial／insufficient。
- technical.structure引用backend-ownedindicators／bars／quality，不直接call provider。
- Corporate action coverage、adjusted／raw basis與data gaps會影響decision usability，不被warning文字掩蓋。
- Multi-timeframe bars由backend產生，regular／extended、DST、early close與partial finalization都有tests。
- Breadth／sector／hot groups每筆結果都有universe_id、version、scope、as_of、coverage、unknown與is_full_market語意。

### Consumer convergence complete

- Frontend不再執行aggregateUsProfessionalIntradayBars或產生canonical technicalTitle。
- Frontend、HTTP／SSE、MCP與Kuro對同一request使用相同capability status、indicator values、current_state、freshness與limitations。
- UI在missing／partial／stale時清楚但不重複建立error owner；desktop／mobile操作不退化。
- runtime採用與實際可見UI已驗證，不以typecheck或backend health單獨宣稱完成。

## Open questions / assumptions

- Shared Technical Engine最終package位置需在Milestone B1依import graph決定；候選為backend/app/research/technical，不直接複製technical_evidence.py。
- US daily首批indicator與default windows需依產品用途、minimum history與TW compatibility決定；附件的5／10／20／50／60／200不是無條件既定值。
- adjusted／raw price basis優先使用現有us_daily_price欄位與lineage；若不足才提出migration。
- Corporate action source、coverage與freshness尚不足；在資料gate完成前，technical.structure可能只能partial。
- SPY benchmark、sector taxonomy與full-market universe source需在實作前做來源／授權／coverage審查。
- Frontend visual overhaul不在本工作流；若資料contract adoption揭露layout問題，再另開design task。
