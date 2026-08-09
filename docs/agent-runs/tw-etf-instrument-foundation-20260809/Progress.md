# Progress

## Status

- Current phase: source implementation and bounded validation complete
- Last updated: 2026-08-09 Asia/Taipei

## Completed

- 新增 non-mutating Taiwan instrument normalization；watchlist read DTO 現在攜帶 `market` 與 canonical `instrument_type`。
- Taiwan selection 在初始載入、URL route、sidebar click 與 client recovery reconcile 都保留 instrument type。
- ETF 沿用行情、K 線、技術分析與報價深度；公司營收、財報、公司事件與處置資料路徑對 ETF 關閉。
- 新增 `taiwan_etf_profile` 與 `taiwan_etf_nav_daily`，並以 `0054` merge 目前兩個 Alembic heads 後建立單一 head。
- 新增 TWSE OpenAPI profile parser、MOPS 指定交易日盤後 NAV parser、idempotent upsert、provider events、cache-only GET 與最多兩個 provider call 的 POST refresh。
- 新增 ETF UI work surface，顯示盤後 NAV、收盤價、折溢價、追蹤指數、基金基本資料、freshness 與未接入 capability。
- ETF 載入／refresh failure 送入共用「更新狀態」，不增加重複 inline error banner。
- 保留 `stock_master.instrument_type` 既有原值與 casing；本次沒有編輯 AI／MCP／Kuro-facing contract。

## Validation evidence

- Official live probe: TWSE OpenAPI 0050 profile 可解析；MOPS 2026-08-07 的 0050 NAV `102.76000`、收盤 `102.85`、溢價 `0.09%` 可解析。
- `python -m pytest tests/test_tw_etf_capability.py tests/test_database_migrations.py -q -p no:cacheprovider`: 12 passed。
- `python -c "from app.db.migrations import get_head_revision; print(get_head_revision())"`: `20260809_0054`。
- `scripts/run-safe-validation.ps1 -Profile quick`: backend compileall、frontend tsc、git diff check passed。
- `npm run lint -- --max-warnings=0`: passed。
- `npm run build`: Next.js production build passed。
- Focused Playwright smoke: ETF panel、NAV／折溢價／追蹤指數、未接入 capability 與單次 bounded POST refresh passed。

## Known limitations / risks

- 第一版官方 provider coverage 僅涵蓋 TWSE 上市 ETF；TPEx ETF 會明確回傳 coverage warning。
- 盤中 iNAV、成分股／PCF、配息歷史與追蹤差距仍是未接入 capability，不會顯示假資料。
- 尚未對使用者目前執行中的 backend／frontend 做 restart，也未對本機正式 SQLite 執行 migration；source 與隔離驗證已完成，runtime adoption 待既有整合工作統一部署。

## Next step

- 等目前 AI／MCP 介面設計整合完畢後，再決定 ETF 下一階段優先做成分股／PCF，或盤中 iNAV 與更細的 freshness contract。
