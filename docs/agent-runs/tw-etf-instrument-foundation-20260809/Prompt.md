# 台股 ETF Instrument Foundation

## Goal

- 把台股 ETF 從 watchlist 自訂分類提升為正式 `instrument_type=etf` contract。
- 讓 selection 與 detail panel 能依 instrument type 選擇 ETF 專屬工作面，不再載入公司營收、財報等不適用資料。
- 建立 cache-first 的 ETF 基本資料與盤後每日 NAV／折溢價能力，資料缺口與 provider failure 可見。

## Non-goals

- 不修改 AI decision contract、MCP public snapshot、Kuro-facing payload 或外部 adapter。
- 不在本階段建立 ETF 成分股、PCF、配息歷史、追蹤差距或即時 iNAV。
- 不把 watchlist 群組名稱當成 instrument type，也不從前端代號前綴推論 ETF。
- 不做全市場排程或啟動時大量 refresh。

## Hard constraints

- Backend 是 instrument、freshness、provider 與 capability 的真相來源。
- GET 只讀本機 cache；外部資料僅由明示且有界的 POST refresh 取得。
- Provider adapter 不接觸 DB；service 擁有 normalization、upsert、commit／rollback 與 provider event。
- 既有 `ETF` 大小寫資料要向下相容；只在新 read contract canonicalize 為 `etf`，不重寫 `stock_master` 原值，避免間接改動 AI/MCP outward payload。
- 保留 worktree 內既有 AI、Radar、intraday 與 quote-depth 變更。

## Context

- Repo: `C:\project\Open Market Intelligence`
- Related systems: Taiwan stock master, watchlist API, dashboard selection, stock detail UI, SQLite/Alembic, TWSE OpenAPI, MOPS
- Current known state: `stock_master` 已有 ETF 資料，但 watchlist DTO 與 Taiwan selection 未攜帶 `market`／`instrument_type`，因此 ETF 仍進入普通公司 detail path。

## Capability contract

| 項目 | 契約 |
|---|---|
| Product scope | 台股核心市場的 ETF 研究工作面；只做研究資料，不涉及自動交易。 |
| Target | 第一版由 watchlist／ETF API 將既有 instrument type 投影為 canonical `etf`；保留 `stock_master` 原值，provider 資料先涵蓋 TWSE 上市 ETF。 |
| Provider | Profile: TWSE OpenAPI `/v1/opendata/t187ap47_L`；NAV: MOPS `/mops/web/ajax_t78sb35`。皆公開、免 key、每次 refresh 最多各 1 call、timeout 20 秒、不重試。 |
| Resource | 基金基本資料；指定交易日的盤後 NAV、收盤價、折溢價與 benchmark。不是盤中 iNAV。 |
| Freshness | Asia/Taipei；NAV 以每日盤後資料為單位，保守採 21:00 release boundary，和 expected trading date 比較 current/stale/missing。 |
| Request bounds | 單一 stock id；單一 NAV 日期；最多 2 次 provider request；不得由 GET refresh。 |
| Persistence | `taiwan_etf_profile` 以 `stock_id` unique upsert；`taiwan_etf_nav_daily` 以 `(stock_id, nav_date)` unique upsert；Alembic migration；不刪除既有 DB。 |
| Failure | empty/schema drift/provider error 明確記錄；部分成功保留已完成資料並回傳 `partial`／warnings；缺值不轉成 0。 |
| Transaction | Provider 純 IO/parser；service 先提交 market data，再以 best-effort provider events 記錄結果，telemetry 不得回滾已保存資料。 |
| Public API | `GET /api/market/etfs/{stock_id}/overview` cache-only；`POST /api/market/etfs/{stock_id}/refresh` bounded refresh。 |
| AI contract | 本次不投影到 AI evidence，不變更 AI/MCP/Kuro contract。 |
| Consumer | Watchlist/selection 傳遞 canonical instrument；ETF detail 顯示 profile、NAV、折溢價、freshness 與 capability；operation error 送到共用更新狀態。 |
| Validation | Provider parser、service/cache/idempotency、migration、watchlist contract、API route、frontend typecheck/build 與必要的 UI smoke。 |

## Deliverables

- Canonical Taiwan instrument helper、watchlist DTO 與 selection propagation。
- ETF profile/NAV models、migration、provider、service、schemas 與 API routes。
- ETF-specific data panel，保留既有行情／技術面，但移除公司營收／財報面板。
- Targeted backend/frontend tests 與驗證紀錄。

## Done criteria

- 選取 watchlist ETF 時，frontend selection 明確持有 `instrumentType="etf"`。
- ETF 不再自動請求 monthly revenue／financial metrics 等 equity-only company resources。
- 0050 cache miss 可透過單一 bounded POST 保存 profile 與指定交易日 NAV，後續 GET 不發 provider request。
- UI 顯示盤後 NAV、折溢價、日期、來源與 current/stale/missing；錯誤進入共用更新狀態。
- AI/MCP outward files 與 public contract snapshot 無 diff。

## Open questions / assumptions

- 第一版 provider coverage 先明確限定 TWSE；TPEx ETF 會安全顯示 provider coverage 缺口，後續再接 TPEx 官方資料。
- MOPS NAV 以 21:00 作保守 release boundary；若實際公告時間需再細分，可在後續 scheduler/freshness phase 調整。
