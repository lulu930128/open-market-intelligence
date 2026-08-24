# Progress

## Status

- Current phase：第二塊implementation、consumer convergence與本機runtime acceptance完成；等待使用者後續外部檢查。
- Last updated：2026-08-23 Asia/Taipei
- Authorization：backend／frontend source、targeted tests、safe validation、OMI services restart與本機UI／MCP acceptance；不含external refresh、DB write／migration、commit、push或release。
- Upstream dependency：Foundation／Outward AAPL neutral quote／intraday／daily contract與runtime canary已完成並由第二塊cache-only research consumer使用。

## Completed

- 建立`app.research.technical` pure boundary與US/TW versioned MarketAnalysisProfile；TW compatibility wrapper與US engine共用EMA／RSI／MACD／KD／PVO numerical primitives。
- 建立US data-usability gate：minimum bars、warm-up、freshness、raw price basis、corporate-action completeness直接控制facts／decision usability。
- 建立cache-only `omi.us_market.research.v1`，從resolved daily OHLCV輸出MA／EMA／RSI／MACD／ATR／volume state與backend-owned structure/current state。
- `technical.indicators`與`technical.structure`已加入US capability、projection、default selection與Decision v4 budget summary。
- 新增`GET /api/us-market/research/{symbol}`；read path不做provider IO或DB write。
- 美股intraday interval由backend依session anchor聚合1m／5m／15m／30m／1h／4h；regular／extended不混桶，DST、missing minute、early-close形狀與partial bar都有tests。
- Frontend已移除`aggregateUsProfessionalIntradayBars`、MA5／20／60、volume MA20、price-vs-MA20與`technicalTitle` canonical計算，改讀backend research；OHLC GET改為`ensure_history=false`。
- Versioned local universe與provider-reported classification coverage gate已加入；full-market expected universe、standard taxonomy與effective date未證明，因此US breadth／sectors／hot groups保持truthful unsupported。
- Architecture與Decision v4 docs已同步已完成與仍受限的truth。

## Validation evidence

- B0 baseline：52 passed，24 subtests passed；target files原有dirty work已保留。
- Shared/TW regression：50 passed，24 subtests passed；既有TW technical vectors與parameter tests未變。
- AI/API／US targeted suite：242 passed，314 subtests passed（新增route/capability後的inventory與catalog snapshot已同步）。
- Frontend：safe profile的lint、TypeScript與`git diff --check`通過；Next.js 16.2.12 production build通過。
- Actual cache-only AAPL proof：260 resolved daily bars，selected provider `yahoo_chart`，technical facts usable，trend為`below_ma20`；因corporate-action coverage unknown，`decision_usable=false`。
- Actual coverage gate：active local symbols 12,710、expected full universe unknown、fresh symbols 3,178、classification mapped 3且並非standard taxonomy；`full_market_ready=false`。這取代舊7,427 snapshot，不將local symbol master冒充full market。
- Backend full regression：排除已隔離的Windows launcher ACL test與本任務前既有Foundation checkpoint drift test後，2,062 passed；本次相關registry／MCP／US outward targeted suite另為52 passed、2 subtests passed。
- Repo backend safe profile中的2,071項tests全部執行完，但`test_runtime_launcher_recovery`使pytest basetemp在Windows sandbox失去列舉權限，session cleanup以WinError 5結束；另有四個本任務前既有Foundation checkpoint drift，不擴大allowlist掩蓋。
- 正式launcher於18:38精準停止舊frontend PID 54784／backend PID 52064，啟動service owners 14596／24392；listeners為3000/node PID 48644與8400/python PID 56092，最終log為`API OK; UI OK`。Backend health確認repo `.venv` Python 3.13.9。
- Runtime AAPL research與frontend proxy皆回`omi.us_market.research.v1`；status `partial`、facts usable、decision blocked、reason `CORPORATE_ACTION_COVERAGE_INCOMPLETE`、trend `below_ma20`，public contract digest為`30aca205187140d8a119ce53dad7d50a2d9f660c21c91ffca9ae0ee62d3ae3db`。
- HTTP ask、SSE final與MCP `omi.ask`皆回`omi.decision.v4`、`data_available=true`、`quality_status=partial`，evidence keys一致包含`daily.ohlcv`、`technical.indicators`、`technical.structure`與`data.freshness`。
- Browser visible proof：AAPL右側顯示backend-owned「弱於MA20」、MA／量能／價格相對位置與corporate-action decision block；共用更新狀態揭露公司事件coverage限制，browser console無warning／error。

## Decisions made

- Shared core採抽離＋TW compatibility wrapper，不複製算法。
- US第一個research outward capability是daily technical.indicators。
- technical.structure、multi-timeframe、breadth／sectors／hot groups後置。
- adjusted／raw、corporate actions、minimum bars與warm-up會直接控制decision usability。
- Frontend與MCP只消費backend evidence；不保留client-side canonical fallback。
- Full-market aggregates不以placeholder啟用；完成的是可稽核coverage gate，outward capability保持unsupported。
- Relative strength benchmark不硬編碼SPY；US v1 profile標記`benchmark_status=not_configured`並在structure limitations揭露。

## Known issues / risks

- Corporate-action completeness checkpoint仍不存在；US technical保持raw-unadjusted且decision blocked，直到coverage contract成立。
- Advanced swing／Fibonacci／divergence／relative-strength capabilities仍只對已驗證TW scopes宣告；US v1 structure不冒充這些capability ready。
- Full-market expected universe、standard sector taxonomy與effective membership date未驗證；US breadth／sectors／hot groups保持unsupported。
- KGI US source readiness仍未通過；本工作流不繞過第一塊fail-closed provider gate。
- 本機runtime acceptance已完成；尚未做外部provider entitlement／coverage稽核、外部consumer inspection或release，這些不屬於本輪授權。

## Next step

- 由使用者進行外部檢查；若要開啟full-market breadth／sectors／hot groups，先補齊expected universe、standard taxonomy、effective membership與corporate-action completeness gate，不從目前partial狀態直接升級。
