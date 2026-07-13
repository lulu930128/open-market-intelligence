# 目標架構

## 判斷方式

本計畫不把「大檔」直接等同於「壞架構」。是否需要拆分依下列證據判斷：

1. 是否同時擁有多個可獨立命名的 state machine 或 use case。
2. 是否混合 URL、network、transaction、projection 與 presentation ownership。
3. 是否讓一個市場或 provider 的修改容易影響其他市場。
4. 是否缺乏可單獨 characterization 的 public boundary。
5. 是否只是宣告型 registry、message catalog、test fixture 或單一演算法引擎。

## 目前熱點分類

| 模組 | 目前主要問題 | 分類 | 決策 |
| --- | --- | --- | --- |
| `MarketDashboardClient.tsx` | 四市場 selection、ranking、radar、refresh、URL、tape、OMI context 共存 | 多 state machine | 優先拆 ownership |
| `StockDetailPanel.tsx` | chart/data tab/drawing/quote depth/index/refresh 共存 | 多 state machine | 第二階段拆 ownership |
| `LightweightKLineChart.tsx` | chart lifecycle、geometry、drawing interaction、overlay 共存 | 互動引擎耦合 | 先 characterization，再分 controller/layer |
| `StockDetailDataViews.tsx` | 多個 presentation domain 共存，無 API/effect | 大型 collection | container 穩定後按 view domain 拆 |
| `StockKLineChart.tsx` | indicator math 與 SVG render 共存 | 演算法 + render | 後續拆純計算，不與另一 chart 強行共用 |
| `backend/app/ai/tools.py` | tool catalog 與多個 Taiwan reader 共存 | backend facade 過重 | 保留 facade，reader 分模組 |
| `backend/app/ai/agentic_tools.py` | planning/execution 與跨市場 reader 共存 | backend facade 過重 | 保留 facade，execution/context 分模組 |
| `backend/app/ai/answer_composer.py` | 多 intent、多 locale renderer 集中 | 純 composition 過重 | 依 intent 分 renderer |
| `backend/app/us_market/service.py` | 多 use case 與 transaction owner 集中 | service facade 過重 | 按 use case 分 service，保留 facade |
| `backend/app/db/models.py` | 79 個 ORM declarations | 大型但一致 registry | 不拆；用 migration parity 保護 |
| i18n / tests | 長 message catalog 或完整 fixture | 大型但可連續檢查 | 不按行數拆 |

## Frontend dependency direction

```text
page / route
    |
    v
MarketDashboardClient / StockDetailPanel        composition shell
    |
    +--> domain hooks                           state, effect, cancellation
    |       |
    |       +--> API client + runtime guards    transport only
    |       +--> pure projections               no React side effect
    |
    +--> presentation components                view model + callbacks only
            |
            +--> chart/view layers              no fetch, no market policy
```

### Frontend invariants

- Shell 決定 composition，不實作市場專屬 fetch、polling、timer 或 request race guard。
- Domain hook 只擁有一個可命名 state machine，回傳 `{state, actions}` 或等價 typed contract。
- Hook effect 必須有明確 dependency、AbortController/request sequence 或其他 stale guard，以及對稱 cleanup。
- Presentation component 接收已格式化 view model；不得 import backend freshness policy 或自行補資料。
- Pure projection module 不 import React、router、DOM、API client 或 storage。
- URL selection 與 data loading 分離；切換路由不直接內嵌 refresh policy。
- Shared cross-market abstraction 只能包含真正一致的 transition；symbol、freshness、status wording 與 endpoint 差異留在 typed adapter。

## Dashboard 目標邊界

```text
market-dashboard/
    selection/
        dashboardRoutes.ts
        useMarketSelection.ts
    ranking/
        watchlistRankingRows.ts
        useTaiwanRankingState.ts
        useUsRankingState.ts
        useJpRankingState.ts
        useKrRankingState.ts
        WatchlistRankingPanel.tsx
    radar/
        useTaiwanRadarState.ts
        useRegionalRadarState.ts       only after proven parity
        RadarPanels.tsx
    tape/
        useMarketTape.ts               transport/state boundary
        TaiwanMarketTape.tsx
        RegionalMarketTape.tsx
    dashboardAskContext.ts
    dashboardFormatters.ts
```

`MarketDashboardClient.tsx` 最終只負責：讀取 route props、呼叫 domain hooks、組合 sidebar/header/active market/detail panel，以及把目前 view state 投影給 OMI dock。

不要求檔案低於任意行數，但 root 不應再直接擁有 ranking/radar/tape API call、request sequence ref 或 timer。

## Stock detail 目標邊界

```text
stock-detail/
    hooks/
        useChartDrawingPersistence.ts
        useTaiwanStockChartData.ts
        useTaiwanQuoteDepth.ts
        useTaiwanIndexContext.ts
        useTaiwanDataPanel.ts
    technical/
        buildFallbackTechnicalReport.ts
        buildStockSignalChips.ts
    projections/
        revenueSeries.ts
        shareholdingSeries.ts
        institutionalSeries.ts
    views/
        TechnicalViews.tsx
        IndexViews.tsx
        RevenueViews.tsx
        ShareholdingViews.tsx
        InstitutionalViews.tsx
```

`StockDetailPanel.tsx` 最終只保留 timeframe、focus mode、active tab 等 composition/UI choice；chart/data/refresh/drawing side effects 由各自 hook 擁有。

## Chart 目標邊界

```text
chart/
    core/
        useLightweightChartEngine.ts
        seriesController.ts
        chartCoordinates.ts
    drawing/
        drawingModel.ts
        drawingGeometry.ts
        drawingProjection.ts
        drawingHitTest.ts
        useChartDrawingInteraction.ts
        DrawingLayer.tsx
    indicators/
        indicatorCalculations.ts
        indicatorProjection.ts
        IndicatorLayer.tsx
    projections/
        volumeProfile.ts
        gapZones.ts
        supportResistance.ts
        technicalSignals.ts
        ProjectionLayer.tsx
    ChartCanvas.tsx
```

Chart engine 的 dependency direction 是 pure math -> controller -> projected view model -> layer。Layer 不反向建立 chart instance，interaction hook 不負責 persistence，chart engine 不負責 market fetch。

## Backend dependency direction

```text
routers / jobs / AI callers / dispatch
                |
                v
       public compatibility facade
                |
                v
         use-case service modules
          |       |        |
          v       v        v
      providers  parsers  source-health/calendar
          |                  |
          v                  v
     provider_http        SQLAlchemy models
```

### Backend invariants

- Router 只做 HTTP schema、status/error translation 與 service dispatch。
- Facade 保留 public imports、exception identity、function signatures 與 monkeypatch seam。
- Use-case module 擁有 transaction；provider/parser 不 commit、不 rollback、不 import router。
- Read/query 預設無 network write；refresh 必須 explicit、bounded 且可記錄 provider event/source health。
- 新 implementation 不 import facade，避免 circular dependency；facade wrapper 呼叫 implementation 並傳入 runtime dependencies。
- AI context projection 不在 frontend、MCP 或 Kuro 重做。

## AI 目標邊界

```text
ai/
    tools.py                         compatibility facade
    agentic_tools.py                 compatibility facade
    tool_catalog.py
    tool_planning.py
    tool_execution.py
    market_context/
        common.py
        freshness.py
        tw_market.py
        tw_index.py
        tw_futures.py
        tw_stock.py
        tw_watchlist.py
        us.py
        jp.py
        kr.py
        crypto.py
    answer_composition/
        entry.py
        trend.py
        position.py
        watchlist.py
        digest.py
        llm.py
```

Facade wrapper 範例語意：

```python
def read_stock_context(*, db, stock_id, ...):
    return tw_stock_context.read_stock_context(
        db=db,
        stock_id=stock_id,
        quote_depth_reader=get_taiwan_stock_quote_depth,
        intraday_reader=get_market_intraday_history,
        ...,
    )
```

這讓既有 `patch("app.ai.tools.get_taiwan_stock_quote_depth")` 仍能控制呼叫，同時避免新模組反向 import facade。

## US market 目標邊界

```text
us_market/
    service.py                       compatibility facade
    services/
        master.py
        prices.py
        fundamentals.py
        macro.py
        watchlists.py
        resource_refresh.py
    providers/                       existing provider HTTP adapters
    sources.py                       existing records/parsers; later reassess
    chart_projection.py
    source_health.py
    trading_calendar.py
    schemas.py
    errors.py
```

拆分順序先 read/query 與 watchlist CRUD，再 provider-backed refresh。Provider refresh wrapper 必須傳入 facade 上目前的 fetch callable，保留現有 test patch behavior。Commit/rollback owner、fallback、provider event 與 source-health 更新順序不得改變。

## 明確延後

- `models.py` domain split：目前沒有足夠收益超過 Alembic discovery、foreign-key resolution 與 import registry 風險。
- 新全域 state library：目前 domain hooks 足以建立 ownership；引入 library 會把 refactor 與 dependency migration 混在一起。
- 跨 chart engine 共用全部 indicator math：兩個 chart 的資料取樣、精度與呈現語意需先有 parity evidence。
- JP/KR/crypto service 全面重構：先完成台股核心 shell 與 US context service pattern，再重新評分。
- API v2、schema migration、UI redesign：都不是 behavior-preserving decomposition，需另開規格。
