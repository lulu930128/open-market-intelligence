# OMI 台股盤前 ChatGPT MCP App 進度紀錄

## 目前狀態

- 任務狀態：`m12_mobile_v2_technical_validation_complete`
- Production implementation：`backend_mcp_widget_added`
- Runtime adoption：`backend_and_omi_search_adopted`
- ChatGPT Developer Mode 驗收：`not_started`
- 真實盤前驗收：`not_observed`
- M9 改版：`technical_validation_complete_but_scope_rejected`
- M10 修正：`technical_validation_complete_user_validation_pending`
- M11 自選股 Tree：`technical_validation_complete_user_validation_pending`
- M12 Mobile V2：`technical_validation_complete_user_chatgpt_mobile_validation_pending`
- 最後更新：2026-08-16 02:00 +08:00

Backend 已新增 cache-only dashboard、symbol search 與 stock detail contract，並將既有 scheduler live gate 提前至 08:30。`OMI_search` MCP Apps resources/tools 與 React widget 已完成 isolated implementation/validation，正式 OMI backend 與 `omi_search` local runtime 亦已採用新 contract；Git commit、ChatGPT Developer Mode 與真實盤前驗收仍未完成。

2026-08-15 已依使用者要求完成 M9 技術實作與隔離驗證。改版先修正 watchlist scope、async ordering 與熱門族群／自選群組語意，再重排桌機與行動版資訊架構並收斂視覺；正式 ChatGPT host 主觀驗收、component restart、commit 與 push 仍保持獨立閘門。

使用者主觀驗收否決 M9 的 layout scope：原始版面與底部委託草稿不得刪除，自選必須使用既有 OMI 台股自選樹；使用者只要色票、字型與按鈕內容的局部修改。M10 已凍結以改版前備份還原完整 layout，保留 M9 correctness 修正並撤銷移除 `OrderShell` 的決策。

M10 已完成 isolated technical validation：原始雙欄 workbench、個股研究、technical evidence、`OrderShell` 與 footer 均已恢復；watchlist selector 直接使用 backend `watchlist.groups` 完整樹，preview 改用目前 SQLite 的真實 root ids/names。尚未執行 `omi_search` component restart，因此正式 ChatGPT host 仍維持上一個已採用 build，等待使用者先驗證本機 preview。

M11 已依使用者要求完成自選股 frontend formalization。Backend flat group hierarchy 經 pure tree helper 機械投影為可遞迴展開的 read-only Tree Explorer；每次選取固定使用 direct-group scope，adapter 只轉送 bounded parameters，未新增 tool、DB access、管理或寫入能力。正式 ChatGPT host 尚未採用此 build，等待使用者先驗證前端後再決定是否執行 component-scoped restart。

使用者已確認 ChatGPT fullscreen request 成功，M12 正式啟動 Mobile V2。第一階段只修改 widget presentation：compact backend-owned market summary、手機移除 Radar、M11.5 Tree 與 focused stock K 線並排、底部 fullscreen／disabled order actions；backend、tool schema、DB 與 market semantics 均不變。

M12 Mobile V2 已完成 source、bundle、isolated browser 與正式 local runtime 採用。360／430／560／768px 均使用左側遞迴自選 Tree、右側 focused OHLC K 線的雙欄工作區，手機 Radar 不占位；1280px 桌機仍保留 Radar、direct items、technical evidence 與 disabled `OrderShell`。目前只待使用者在 ChatGPT 手機 fullscreen host 做最後主觀驗收。

## 本次已完成

- 2026-08-16 依 OpenAI 官方文件重新核對 fullscreen、composer overlay、`requestDisplayMode` 與 host viewport context。
- 讀取使用者 Mobile V2 HTML／計畫與 768px 參考圖；附件只作視覺參考，沒有採用其中示意數值或示意 chart。
- 對齊非空 `docs/product/` 與既有 M9–M11.5 長專案決策，確認沿用同一個 `interactive-decoupled` React widget。
- 凍結 widget `App.tsx`／`styles.css` SHA-256 與 dirty-worktree baseline，建立隔離 staging；第一版 JSX/CSS syntax parse 與 staged diff check 通過。
- 新增 compact index／breadth、truth／warning disclosure、500px 雙欄研究工作區、stock leaf price／change 與 focused K 線 presentation；資料只投影既有 dashboard/detail tool response。
- 手機 Radar、direct-items duplicate、完整 technical cards、桌機 OrderShell 與 footer 只在 mobile presentation 隱藏；桌機 DOM／功能未刪除。
- 移除已完成任務的 fullscreen diagnostic UI，保留 bridge initialization、auto fullscreen 與手動 `requestFullscreen`。
- 手機「下單介面」只 toggle 原有 disabled／disconnected `OrderShell`；沒有新增 tool、broker、order write 或自動交易能力。

- 讀取使用者提供的 v2 engineering spec。
- 對齊 OMI `ProductVision.md`、`OperatingModel.md`、`QualityBar.md`、`Roadmap.md` 與 `BackendArchitecture.md`。
- 檢視既有台股 market breadth、preopen intraday、opening handoff、quote depth 長任務成果。
- 檢視 backend indices、intraday state、screening、watchlist、stock search、technical 與 stock-profile shares 的現況。
- 檢視 `C:\GPT_MCPtool\OMI_search` 的 Python MCP server、HTTP session transport、tools-only initialize contract 與 tests。
- 依官方 MCP Apps 文件凍結 `interactive-decoupled` 方向、UI resource MIME、resource URI metadata、bridge 與 tool schema原則。
- 建立 `Prompt.md`、`Plan.md`、`Progress.md`。
- 完成 M0 runtime/storage/watchlist/detail/index 邊界決策，新增 `ContractDecision.md`。
- 新增 `omi.tw_market_dashboard.v1` Pydantic contract 與 dedicated cache-only route。
- 新增 bounded 本機台股 symbol search 與 cache-only 個股 K 線／技術報告 projection。
- 以既有 `taiwan_intraday_stock_state` 建立盤前 breadth、族群、watchlist 與 provisional index proxy projection。
- 將既有 scheduler-owned Taiwan market-index collector 的 live gate 從 08:55 提前至 canonical 08:30 preopen。
- 補上盤前 `not_observed`、breadth accounting、no-renormalization、search、detail 與 route tests。
- 新增 backend-generated dashboard MCP output-schema snapshot 與 SHA-256 digest parity。
- 在 `OMI_search` 新增 resources capability、`resources/list`、`resources/read` 與四個 focused tools。
- 只有 `omi.open_tw_market_dashboard` 綁定 `ui://omi/tw-market-dashboard/v1.html`；data/search/detail tools 維持 decoupled。
- 新增 React/TypeScript widget、bridge-first `ui/*` flow、30 秒 single-flight polling、hidden pause、bounded backoff、monotonic adoption、搜尋、watchlist drill-down、backend K 線與 MA5/20/60。
- 以 480px isolated browser fixture 驗證窄版首屏、partial warnings、watchlist click 與個股 chart。
- 依使用者提供的 terminal prototype 完成暗色高密度市場工作台重整；沿用頂部狀態列、行情色、資料格與 chart toolbar 的視覺語言，但未帶入 mock trading core 或隨機行情邏輯。
- 新增明確的委託草稿空殼，保留方向、價格、數量、風險條件與送出按鈕版位；所有控制固定 disabled、`DISCONNECTED`，不呼叫 MCP tool、不寫資料、不連券商。
- M9 backend additive contract 新增 active watchlist group metadata；selection/items contract 保持相容，inactive group 不暴露。
- 熱門族群保留 raw industry key 作穩定 identity，並由 backend 對已知台股產業代碼提供繁中顯示名稱；未知代碼與既有文字值採 truthful fallback。
- Widget dashboard request 現在會帶 explicit `watchlist_group_id`、`include_watchlist_children=true`、`watchlist_limit=40`；舊 scope response 不得覆蓋目前 selection。
- 重整為「市場／自選／個股研究」三段工作流；desktop 保留高密度研究視野，mobile 以 sticky tabs 切換單一工作區，避免無限長單欄堆疊。
- 移除 M7 的 disabled 委託空殼；未新增交易 tool、broker 連線、資料寫入或自動交易能力。
- 補上 search、group、detail 各自 loading/error 邊界、active selection、skeleton、focus-visible 與 reduced-motion；stale/partial/cache-only/warnings 仍可見。
- Preview fixture 支援三個群組、child group 與依選取 stock 回傳正確 detail，作為使用者主觀前端驗收入口。
- M10 以改版前 `App.tsx`／`styles.css` 為 baseline，恢復市場雷達、原 workbench、個股工作台、technical evidence、底部 disabled 委託草稿與 footer；未刪除其他原始區塊。
- 保留 M9 的 explicit watchlist scope、late-response guard、selected stock、poll/search/detail error separation 與 retry，不把 correctness 修正一起回退。
- Watchlist selector 直接 render backend `watchlist.groups` 並依 `parent_id` 縮排；正式 payload 可呈現目前 77 個 active groups，preview 使用真實 12 個 root 及代表性 child groups，不再使用「核心持股／動能觀察」示意資料。
- 視覺修改限制在既有 CSS geometry 上的暗色 token、UI／data font、focus／hover 與繁中按鈕文案；沒有新增 UI library、交易 tool、broker 連線或寫入 side effect。
- M11 新增 typed `buildWatchlistTree()`、stable ordering、orphan／duplicate／cycle fail-open、selected path helper 與 optional backend count projection；frontend 不推算 direct/subtree count。
- Dashboard request 固定 `include_watchlist_children=false`、`watchlist_limit=40`、`group_limit=10`；任何 aggregated descendant snapshot 都不得覆蓋目前 selection。
- 以遞迴 `treeitem`／`group`、獨立 expand/collapse 與 selection button 取代 flat selector；切換期間隱藏舊群組 items，空父群組明確提示展開子群組。
- Watchlist Tree 與熱門族群各自有 bounded vertical scroll；原市場雷達、個股研究、K 線、technical evidence、disabled `OrderShell` 與 footer 全部保留。
- Preview 改為目前 backend／SQLite 的完整 77 個 active groups、349 個 direct items、Top 10 熱門族群與可稽核 dashboard request log；沒有示意自選群組名稱。

## 目前證據摘要

### Backend

- 現有 live breadth cache 已有約 30 秒 TTL，可作為 widget polling 下限的依據。
- 既有 scheduler interval collector 已具 `coalesce=true`、`max_instances=1` 並持久化到 SQLite；live/target-date gate 已調整為 08:30。
- 新 dashboard route 只讀 `StockMaster`、`StockProfile`、`MarketIndexDailyStat`、`taiwan_intraday_stock_state` 與 watchlist tables，不呼叫 provider。
- 現有 preopen indicative facts 與 regular actual-trade decision state 有基本隔離；M2 必須保留此 boundary。
- watchlist、group、symbol search、technical 與 issued-shares 已形成初版 dashboard-focused contract；正式 index component/divisor evidence 仍未完成。

### MCP / ChatGPT App

- `OMI_search` 目前維持 thin adapter，未直接擁有 OMI 市場語意。
- MCP initialize 已 additive 宣告 resources capability，並保留既有 streamable HTTP session ownership。
- `resources/list/read` 已提供 `text/html;profile=mcp-app` resource，standard CSP network allowlist 為空。
- tool surface 已新增 dashboard data/render/search/detail；adapter 只機械呼叫 focused backend routes。

### 前置專案

- `tw.market.breadth.v2` 已建立 coverage/unknown accounting 方向。
- preopen intraday 與 opening handoff 已完成正式 rollout，但真實各時點證據仍需重新驗證本次新 contract。
- 本任務與既有 market-data reliability/self-healing 工作可能同時碰觸 indices、scheduler、AI/MCP snapshot；實作前必須做 hunk-level ownership 檢查。

## 已凍結的方向

| 決策 | 狀態 | 內容 |
| --- | --- | --- |
| Truth owner | 已凍結 | session、freshness、breadth、group、watchlist、index estimate 全由 backend 擁有 |
| MCP architecture | 已凍結 | Python `OMI_search` 維持 thin adapter，不重寫成 Node server |
| App archetype | 已凍結 | `interactive-decoupled`，data tool 與 render tool 分離 |
| UI location | 已凍結 | `C:\GPT_MCPtool\OMI_search\ui\tw-market-dashboard\` |
| UI resource | 初步凍結 | `ui://omi/tw-market-dashboard/v1.html`，`text/html;profile=mcp-app` |
| Read path | 已凍結 | dashboard、search、detail 必須 bounded；dashboard read 不得 provider refresh |
| Preopen semantics | 已凍結 | indicative/provisional 可顯示，但 `official=false`、`decision_usable=false` |
| Public scope | 已凍結 | 先做 private Developer Mode；public App submission 不在本任務 |
| Runtime topology | 已凍結 | API runtime 啟動同一 scheduler；snapshot truth 使用既有 SQLite persistence |
| Migration | 已凍結 | `not_required`；沿用既有 canonical intraday state tables |
| Watchlist scope | 已凍結 | explicit `group_id`；未指定時取 sort order 最前的 active root，含 children、enabled-only、最多 40 檔 |
| Stock detail | 已凍結 | 新增 focused cache-only projection，不沿用過重的通用 AI context envelope |
| Index estimate | 部分凍結 | 先提供明確標示的 active-stock proxy；正式 constituent/divisor 證據完成前一律 partial/non-official/non-decision-usable |

## M0 必須解決的決策閘門

| 決策 | 目前建議 | 完成證據 |
| --- | --- | --- |
| Dashboard backend surface | dedicated `omi.tw_market_dashboard.v1` cache-only projection | schema、route/capability call graph、compatibility review |
| Snapshot storage | 依 scheduler/API process topology 決定 | runtime owner/process evidence；必要時 migration proposal |
| Watchlist scope | 明確 `group_id` 或可稽核 active-group policy | service call contract、fixture 與 UI label |
| Stock detail tool | 先評估 `omi.read_stock_context`；過重才新增 focused tool | payload size/schema/side-effect comparison |
| Index authoritative inputs | 官方 methodology + dated constituents/shares/divisor/corporate actions | source matrix、as-of fields、fail-closed thresholds |
| Widget asset strategy | 優先可版本化、CSP 最小化的 bundle | build output、resource read 與 CSP smoke |

## Milestone 狀態

| Milestone | 狀態 | 完成條件摘要 |
| --- | --- | --- |
| M0 整合基線與 contract freeze | 已完成 | 決策記錄、runtime/storage/watchlist/detail/source 邊界已固化 |
| M1 08:30 scheduler-owned collector | 部分完成 | 沿用既有 single-flight persisted collector並提前 gate；live evidence 待補 |
| M2 盤前 facts 與 breadth | 部分完成 | 初版 invariants/session semantics 已通過 targeted tests；更多 malformed fixtures 待補 |
| M3 族群與 watchlist | 部分完成 | deterministic ranking、scope 與 missing row 已實作；更多 child/order fixtures 待補 |
| M4 TAIEX/TPEx estimator | 阻擋於正式來源 | pure no-renormalization proxy 已實作；official constituents/divisor/corporate-action 尚未完成 |
| M5 Backend focused contract | 已完成初版 | dashboard/search/detail、exact schema generator 與 OpenAPI inventory 已通過 full suite |
| M6 MCP Apps protocol/resource | 已完成並採用 | resources、11-tool surface、schema digest、CSP、retained-session tests 與正式 local runtime outward smoke 通過 |
| M7 ChatGPT widget | 已完成並採用 | bridge、polling、search/detail、K 線/MA、terminal redesign、disabled 委託空殼、responsive/error UX 已 build/test/browser/runtime 驗證 |
| M8 整合與正式驗收 | local runtime 已完成 | Developer Mode、remote connector 與四時點 live evidence 待驗收 |
| M9 Dashboard 互動與視覺改版 | 技術驗證完成 | additive backend contract、widget state、desktop/mobile layout、visual 與 isolated browser smoke 已完成；使用者 ChatGPT host 主觀驗收待辦 |
| M10 原始版面驗收修正 | 技術驗證完成 | 原 layout、真實 watchlist selector、disabled OrderShell、typecheck/tests/build 與 desktop/mobile browser smoke 已完成；使用者 preview 驗收待辦 |
| M11 自選股 Tree Explorer | 技術驗證完成 | arbitrary-depth group recursion、lazy direct stock leaves、direct-group scope、Top 10、race guard、typecheck/tests/build 與 desktop/mobile browser smoke 已完成；使用者 preview 驗收待辦 |
| M12 ChatGPT Mobile V2 | 技術驗證完成並採用 | compact truthful market summary、mobile Tree／actual K-line 雙欄、Radar mobile hide、disabled order disclosure、typecheck/tests/build/browser/live resource hash 已通過；使用者 ChatGPT 手機 host 驗收待辦 |
| M12.1 Mobile host 驗收修正 | Widget 已採用／backend runtime 待採用 | 市場概況字級提高 2px、窄版 meta 防裁切與正式 resource hash 已通過；自選 0 群組已證實為正式 backend runtime 尚未載入 source 的 `watchlist.groups` contract，禁止在 frontend／adapter 補假資料 |

## 驗證狀態

- 規劃文件 UTF-8 嚴格讀回：通過，三份文件皆可用 strict UTF-8 decoder 讀取。
- 必要標題與內容存在檢查：通過，缺少標題數為 0。
- trailing whitespace / final newline：通過，三份文件皆有 final newline，trailing whitespace 行數為 0。
- `git diff --check`：通過；現有 dirty worktree 僅輸出既有 LF/CRLF conversion warnings，沒有 whitespace error。
- Git 範圍檢查：本任務只有 `docs/agent-runs/tw-preopen-chatgpt-mcp-dashboard-20260814/` 為新未追蹤路徑。
- Backend targeted tests：`55 passed`，涵蓋新 dashboard、盤中狀態與市場指數 daily stats regression。
- 新 dashboard tests：`9 passed`；已驗證 provider 零呼叫、breadth invariants、08:00 not-observed、no-renormalization、bounded search、cache-only detail、backend MA series 與 route registration。
- `py_compile` 首次因既有 `tests\\__pycache__` 檔案寫入權限失敗；改用 `python -B -m pytest` 完成無 bytecode 驗證，未刪除既有 cache。
- Backend safe validation：compileall 通過、完整 pytest `1820 passed`、`git diff --check` 通過；log 位於 `.tmp/validation/20260814-232010`。
- `OMI_search` adapter tests：`36 passed`，包含 retained-session resources/tools protocol。
- Widget：TypeScript typecheck 通過、state/backoff tests `4 passed`、production build 成功，單檔 resource 為 167891 bytes。
- Terminal redesign widget：TypeScript typecheck 通過、state/backoff tests `4 passed`、adapter regression `36 passed`、production build 成功；單檔 resource 更新為 187107 bytes。
- Responsive browser：480px 與 1200px 皆無水平溢出；desktop workbench 為雙欄，窄版為單欄；watchlist selection、單一 chart adoption 與 disabled 委託空殼均通過。
- 委託空殼 browser assertion：`DISCONNECTED`、8 個 order controls 全部 disabled、沒有 order/broker tool 呼叫或產品端 `MutationObserver`。
- Schema parity：OMI 與 adapter snapshot file SHA-256 相同，且內部 contract digest 相同。
- Isolated browser：480px viewport 無水平溢出（`scrollWidth=clientWidth=450`）；watchlist click 後 chart SVG 數為 1。
- Browser console 有一筆測試瀏覽器注入的 `MutationObserver` error；widget source/bundle 搜尋不到該 API，無證據顯示來自產品 bundle。
- `omi_search` lifecycle build gate：第一次 restart 因 controller 仍只 hash 舊三個 artifacts 而回 `SERVER_NOT_READY`；已讓 controller 與 server 一致納入 dashboard schema 與 widget bundle，PowerShell parse、diff check 與隔離 runtime controller `30 assertions` 通過。
- `omi_search` 正式 runtime：Control Center 僅重啟該 component；最終六個 components 皆為 `Ready`，MCP listener PID `21564`、tunnel PID `42232`，實際與預期 buildId 均為 `301c3f9edfed3269`。
- Terminal redesign 正式 runtime：Control Center 再次只重啟 `omi_search`；最終六個 components 仍為 `Ready`，MCP listener／managed PID 均為 `52200`、tunnel PID `49260`，實際與預期 buildId 均為 `e58ec5974fdcdbfe`。
- 正式 resource adoption：retained-session `initialize -> resources/list -> resources/read -> tools/list -> tools/call` 通過；resource SHA-256 與 187107-byte production dist 完全一致，11-tool surface 與唯一 UI-bound render tool 未改變。
- OMI backend 正式 runtime：透過官方 launcher `Restart Services` 採用 source；OpenAPI 已包含 `/api/market/tw-dashboard/snapshot`，正式 route 回傳 `omi.tw_market_dashboard.v1` 且誠實標示 `freshness.status=stale`、`cache_only=true`。
- Retained-session outward smoke：`initialize -> resources/list -> resources/read -> tools/list -> tools/call` 全部通過；resource 為 `text/html;profile=mcp-app`、11 tools 僅 render tool 綁 UI，dashboard/render/search/detail 均為 `HTTP 200` 且 `isError=false`。
- Launcher UI automation 在第一次 services restart 完成後誤觸 `Exit Launcher`；startup mechanism 17 秒後自動恢復，最終 launcher PID `44672`、backend listener PID `50292`、frontend listener PID `35168` 且狀態為 `API OK; UI OK`。此後未再執行 GUI 動作。
- M9 backend dashboard targeted tests：`11 passed`；涵蓋 active group hierarchy、inactive exclusion、industry code normalization 與 unknown/text fallback。
- M9 schema snapshot：OMI 重新產生 contract digest `b5c8646b15007f5c08a48b182a414517c85042ad8cbe6f3d8c3e6e9cd7f07fd3`；OMI 與 `OMI_search` snapshot file SHA-256 相同。
- M9 widget：TypeScript typecheck 通過、scope/order/backoff tests `7 passed`、production build 成功；單檔 resource 為 `191565 bytes`。
- M9 `OMI_search` adapter regression：`36 passed`。
- M9 browser：desktop 1280px 與 mobile 390px capability 均無水平溢出；資料品質展開、搜尋、自選 root/child group、stock selection、detail/chart identity 與 mobile 三工作區切換均通過。
- M9 寫入外部未追蹤 widget 前已逐檔建立 SHA-256 備份並做 precondition check；只同步 4 個 widget source、preview fixture 與 generated contract snapshot，未碰既有 `server.py` hunk。
- 本回合未重啟 OMI backend／`omi_search`、未 commit、未 push、未執行 Developer Mode 或 remote connector 驗收。
- M10 read-only SQLite 驗證：目前仍為 `77` 個 active groups、`349` 個 active items；12 個 root 與使用者截圖一致，預設第一群組為 id `36` 的 `ETF／市場指標`。
- M10 baseline：改版前 `App.tsx`／`styles.css`／state／preview 與 contract snapshot 備份仍完整；`OrderShell`、原 workbench 與所有底部區塊可直接還原，不需猜測重建。
- M10 外部同步：先確認 `C:\GPT_MCPtool\OMI_search\ui\tw-market-dashboard` 三個目標檔仍符合 M9 備份 SHA-256 前置條件，再只同步 `src/App.tsx`、`src/styles.css`、`dist/preview.html`；`state.ts`／`state.test.ts` 與 M9 validated 版本雜湊相同。
- M10 widget：TypeScript typecheck 通過、scope/order/backoff tests `7 passed`、production build 成功；單檔 resource 為 `192976 bytes`，SHA-256 `4db0a72b0a1e4da85ecf54b1b24638a242c2ee48a3b60b19080a05e3966f3b2b`。
- M10 `OMI_search` adapter regression：`36 passed`。
- M10 desktop browser（1280×900）：`scrollWidth=clientWidth=1250`；市場雷達、個股工作台、OrderShell 各 1 個；7 個委託控制全部 disabled；selector 無示意群組且可切換 `科技／電子`，items 更新為 2330／3105／3661／5274，點選 2330 後 chart 1 個且 OrderShell identity 同步。
- M10 mobile browser（390×844）：`scrollWidth=clientWidth=360`；原始單欄順序保留，市場雷達、個股工作台、watchlist selector、OrderShell 各 1 個，沒有 M9 mobile tabs；底部委託草稿可捲動到達且未啟用。
- M10 browser console 仍只見測試瀏覽器注入的既有 `MutationObserver` error；產品 source／dist 搜尋不到該 API，無產品 bundle 歸因證據。
- M10 預覽伺服器只暫時綁定 `127.0.0.1:43117`，驗證後已關閉；viewport override 已 reset，臨時 tab 已關閉。
- M11 外部同步：先以 M10 備份做五個目標檔 SHA-256 前置條件，符合後才只同步 `src/App.tsx`、`src/state.ts`、`src/state.test.ts`、`src/styles.css` 與 `dist/preview.html`；未修改 backend、adapter server 或 tool schema。
- M11 widget：TypeScript typecheck 通過、tree／scope／late-response／backoff tests `10 passed`、production build 成功；單檔 resource 為 `197031 bytes`，SHA-256 `2fa33f010006aafe32dc4a6c9416a9009f3351834a49bf8ed68e63b931bf6cb9`。
- M11 `OMI_search` adapter regression：`36 passed`。
- M11 desktop browser（1280×900）：`scrollWidth=clientWidth=1250`；12 個 root、Top 10 熱門族群、Tree 300px bounded scroll 與 hot-list 218px bounded scroll；flat selector 為 0，ETF child 可展開／收合，快速切換 37／45／59 後最後 selection 與 direct items 一致。
- M11 browser request evidence：選取 group id `59` 的 request 為 `include_watchlist_children=false`、`watchlist_limit=40`、`group_limit=10`；直接標的為 2317／2382／3231／6669，點選 2317 後 detail/chart／OrderShell identity 一致。
- M11 mobile browser（390×844）：`scrollWidth=clientWidth=360`；Tree 260px bounded scroll 且可展開／選取，市場雷達、個股工作台與 OrderShell 各 1 個，7 個委託控制全部 disabled。
- M11 source／bundle 未使用 `MutationObserver`；預覽伺服器只暫時綁定 `127.0.0.1:43118`，驗證後 listener／parent process 均不存在，viewport 已 reset，臨時 tab 已關閉。
- M11 staged five-file `git diff --no-index --check`、三份任務文件 strict UTF-8 讀回與 repo `git diff --check` 均通過；dirty worktree 的既有變更未被回退或納入本工作包。
- M11 preview regression 根因：第一版 fixture 只有 17 個 groups，導致 `金融` 等後續 root 被錯誤呈現為 leaf；formal frontend/backend contract 本身未失效。
- M11 preview regression 修正：只更新 `dist/preview.html` fixture 為目前 77 groups／349 direct items，production source、bundle、API、adapter 與 tool schema 均未修改。
- M11 preview regression browser：完整展開為 12 root＋65 child＝77 treeitems；390×844 下 `金融` 可展開 5 個 child，選取 `銀行／票券` 後顯示 10 個 direct items，`scrollWidth=clientWidth=360`，Tree 仍為 260px bounded scroll。
- M11 regression 預覽伺服器只暫時綁定 `127.0.0.1:43119`，驗證後已結束；viewport 已 reset，臨時 tab 已關閉。
- M11 深層群組可見性根因：Tree 內容存在且可捲動，但原 260px／300px viewport 搭配 overlay scrollbar 缺少明確 affordance，後段 child 在使用者畫面中看似被截斷。
- M11 深層群組完善：Tree 改為 viewport-aware 320–480px（mobile 340–460px）、常駐高對比 scrollbar、stable gutter、overscroll containment、`77 群組`標示、`上一段／下一段`控制與 top/middle/bottom 狀態文字。
- M11 展開 root 會自動對齊 Tree 頂端；選取 child 會維持在可視範圍，不改 direct-group request、backend truth 或資料語意。
- M11 深層群組 widget：TypeScript typecheck 通過、state regression `10 passed`、production build 成功；單檔 resource 更新為 `200888 bytes`。
- M11 深層群組 mobile browser（390×844）：Tree `clientHeight=439`、`scrollHeight=1310`，常駐 scrollbar 生效；`下一段` 後可見 AI伺服器／ODM、散熱、電源、連接器、記憶體、工業電腦，選取 AI 後 4 個 direct items 正確，無水平溢出，7 個委託控制仍 disabled。
- M11 深層群組 bottom state：可走到 `scrollTop=maxScrollTop=932`，狀態顯示「已到最下方」，下移 disabled、上移可用，最後六個 root 均可見。
- M11 深層群組 desktop browser（1280×900）：雙欄 workbench 保留，Tree `clientHeight=378`／`scrollHeight=1310`，個股研究與 `OrderShell` 各 1 個，7 個委託控制仍 disabled，無水平溢出。
- M11 深層群組預覽伺服器只暫時綁定 `127.0.0.1:43120`，驗證後已結束；viewport 已 reset，臨時 tab 已關閉。
- M11.5 根因：先前 Tree 只遞迴 backend group metadata，卻把 group selection 後的股票留在下方面板；視覺上 child group 容易被誤解為終端層，沒有明確走到股票本體。
- M11.5 群組／股票邊界：任何 group child 都繼續使用遞迴 group component；只有 exact direct-group response 的 item 才會產生終端股票 `treeitem`，frontend 不從名稱、深度或目前 child 數量猜測 leaf。
- M11.5 lazy read：展開任何群組時沿用 `omi.read_tw_market_dashboard`，固定 direct-group scope，加入 per-group single-flight、cache、error、empty 與 truncated 狀態；沒有新增 backend route、tool schema、DB read 或市場語意。
- M11.5 widget：TypeScript typecheck 通過、tree／exact-scope／late-response／backoff tests `11 passed`、production build 成功；單檔 resource 為 `205818 bytes`，SHA-256 `90e694176f900b5a1275308a3d426e742ba110b62cadff185113ddd10989f876`。
- M11.5 mobile browser（390×844）：`ETF／市場指標 → 大型權值／市值型` 展開後顯示 5 個 level 3 股票葉節點；`科技／電子 → 半導體製造／晶圓代工` 顯示 2330／2303／5347／6770，點選 0050 後 detail identity 為 `元大台灣50 0050`，無水平溢出。
- M11.5 desktop browser（1280×900）：群組 Tree、股票葉節點、個股工作台與 disabled `OrderShell` 均保留；點選 0050 後 detail identity 同步，無水平溢出，8 個目前可見委託相關控制均 disabled。
- M11.5 預覽伺服器只暫時綁定 `127.0.0.1:43121`，驗證後已結束且 listener 不存在；viewport override 已 reset，臨時 tab 已關閉。
- M12 widget：TypeScript typecheck 通過、bridge／tree／scope／late-response／backoff tests `12 passed`、production build 成功；單檔 resource 為 `231251 bytes`，SHA-256 `762b2317a860db831f2eeca38479ea8976998d60f771b8d41fa51c5cb33fcf12`。
- M12 `OMI_search` adapter regression：`36 passed`；沒有修改 backend、adapter server、tool schema、watchlist DB 或 market semantics。
- M12 responsive browser：360／430／560／768px 均為 mobile 雙欄、Radar／desktop market panels 不占位、bottom actions 可見且 `scrollWidth=clientWidth`；1280px 回到 desktop layout，Radar／desktop market panels 可見、mobile actions 隱藏。
- M12 Tree／K-line browser：展開 `科技／電子 → AI伺服器／ODM` 後，4 個 level 3 股票葉節點顯示 tool-returned price／change；點選 2317 後右欄 identity 為 `鴻海 2317`、preview fixture 產生 30 根 OHLC candles／MA 線，Tree 維持內部捲動。
- M12 live detail smoke：正式 `omi.read_tw_stock_dashboard_detail` 回傳 `鴻海 2317`、33 points／33 moving-average rows，最新 OHLC 為 `262／264.5／257.5／259.5`、freshness `current`，與 watchlist leaf 價格一致；正式 K 線不是 prototype／preview 示意線。
- M12 order safety browser：手機「下單介面」展開後 7 個 controls 全部 disabled、enabled trade controls 為 0，gate 明確顯示尚未連接券商、模擬撮合或寫入 tool。
- M12 preview server 只暫時綁定 `127.0.0.1:43126`；驗證後 exact PID 已停止、listener 不存在，viewport override 已 reset，臨時 tab 已關閉。
- M12 正式 runtime：Control Center 只重載 `omi_search`，listener PID 更新為 `6664`、tunnel PID 更新為 `56108`、buildId 從 `934c9c758705d521` 更新為 `881d4d58137240b6`；整體仍為 `Ready 6/6`。
- M12 live MCP adoption：retained-session `initialize -> resources/list -> resources/read -> tools/list` 通過；`ui://omi/tw-market-dashboard/v2.html` MIME 正確、11-tool surface 未改，live resource bytes／SHA-256 與 production dist 完全一致。
- M12.1 自選 0 群組根因：正式 `8400` snapshot 與 live OpenAPI 的 watchlist schema 均沒有 `groups`；同一 repo source 的 dashboard builder、Pydantic schema、generated adapter snapshot 與 targeted tests 都已包含 `groups`。問題位於 OMI backend runtime adoption，不是 Tree click／recursive leaf 邏輯。
- M12.1 backend targeted regression：從 `backend` 目錄執行 `..\.venv\Scripts\python.exe -B -m pytest tests\test_tw_market_dashboard.py -q`，結果 `11 passed`；首次從 repo root 執行因 Python import root 不符而失敗，已依 repo 規則更正，未修改環境或測試。
- M12.1 市場概況：title、timestamp、index label/value/change、meta 與 breadth label/value 各提高 2px；小於等於 430px 時 meta label/value 改為分行，避免提高字級後裁切。
- M12.1 widget：TypeScript typecheck 通過、bridge／tree／scope／late-response／backoff tests `12 passed`、production build 成功；單檔 resource 為 `231435 bytes`。
- M12.1 responsive browser：360px 與 768px 均無水平溢出或 clipped element；360px 實測市場 title 10px、timestamp 8px、index label 8px、index value 14px、change/meta 7.5px、breadth label 8px/value 9px，768px index value 為 16px。
- M12.1 正式 runtime：Control Center 只重載 `omi_search`；新 buildId `155f55617eac266d`、listener PID `49624`、tunnel 與 upstream probes 均 Ready，整體仍為 `Ready 6/6`。
- M12.1 live resource adoption：retained-session `initialize -> resources/read` 讀取 `ui://omi/tw-market-dashboard/v2.html`；served resource 與 production dist 均為 `231435 bytes`、SHA-256 `205C454F36F77BE302D2739670839DBDA3FC3F3CFBE0F6B17E35C9500937E4C9`。

## Known limitations

- 本次規劃時 OpenAI Developer Docs MCP 尚未能在本機成功加入；MCP Apps 契約依官方 developers.openai.com 文件核對。實作 M6 前應再次檢查官方文件是否有更新。
- 目前沒有真實 08:30 至 09:00 的新 dashboard contract evidence。
- index estimate 的正式 component/divisor/corporate-action source尚未完成；目前僅為 truthful proxy 且固定 non-official/non-decision-usable。
- runtime/storage 已決定沿用同 API runtime scheduler 與既有 SQLite tables，不需要 DB migration。
- Local tunnel health 為 `Ready`，但 remote registration 與 ChatGPT connector 仍是 `NotChecked`；尚未執行 Developer Mode 驗收、commit 或 push。
- Widget `dist/` 與 `node_modules/` 依 repo 規則保持 ignored；正式 restart 前必須先完成 production build，resource 缺失時 fail closed。
- M10 已恢復既有 disabled 委託草稿版位；未定義券商／模擬交易 trust policy、write contract、風險控管與審計前，所有控制必須保持 disabled，且不得新增送單 side effect。
- Backend 目前尚未提供 direct／subtree count 欄位；M11 只在 response 明確提供 optional count 時顯示，沒有在 frontend 以不完整 items 或 hierarchy 推算。若需要截圖中的群組數量，應另做 backend additive contract milestone。
- 正式 OMI backend runtime 目前仍是舊 schema，尚未 outward 回傳 source 已具備的 `watchlist.groups`；在官方 launcher 執行 `Restart Services` 並驗證 live OpenAPI／snapshot 前，ChatGPT host 會持續誠實顯示 0 群組。

## 下一步

下一步由使用者透過正式 OMI launcher 執行一次 `Restart Services`，再驗證 live OpenAPI 與 dashboard snapshot 已 outward 提供 `watchlist.groups`（目前 read-only DB 基線為 77 groups／349 items）。通過後才在 ChatGPT 手機 fullscreen host 驗證 Tree 遞迴、實際 K 線與 composer 遮擋；若 host 仍持有舊 resource，再重新連線或開新對話。remote registration、commit 與 push仍維持獨立工作包／授權閘門。

## 變更紀錄

### 2026-08-16

- 完成 M12.1 host 驗收修正：市場概況各層級字級提高 2px並加入窄版防裁切；typecheck、12 widget tests、231435-byte build、360／768 browser smoke、正式 resource hash 與 Ready 6/6 均通過。
- 證實自選 0 群組是正式 OMI backend runtime drift：live OpenAPI／snapshot 缺少 source 已存在且 11 tests 通過的 `watchlist.groups`；未在 frontend 或 thin adapter 重建 backend truth，等待官方 launcher `Restart Services` 採用。
- 完成 M12 Mobile V2：手機使用 truthful compact market summary、左 Tree／右 actual K-line 雙欄、mobile Radar hide、fullscreen／disabled order actions；桌機原 Radar、technical evidence 與 OrderShell 保留。
- 完成 12 widget tests、36 adapter tests、231251-byte production build、五種 responsive browser smoke、order disabled assertion 與 live resource hash adoption。
- Control Center 只重載 `omi_search`；Ready 6/6 與新 buildId 已確認。未修改 backend／DB／tool schema，未 commit、未 push。

### 2026-08-15

- 完善 M11.5 群組／股票 boundary：任意深度群組遞迴、展開時 lazy direct-item read、股票終端 treeitem、per-group cache/error/truncation 與 detail 連動；11 tests、build 與 390／1280 browser smoke 通過。
- 完善 M11 深層群組瀏覽：新增常駐 scrollbar、viewport-aware 高度、群組總數、上下分段控制、展開自動對齊與 bottom state；390／1280 browser regression 通過且原始底部介面保留。
- 修正 M11 preview fixture 不完整造成的「後續群組無法展開」假象；以 read-only DB evidence 補齊 77 groups／349 direct items，窄版 `金融 → 銀行／票券` browser regression 通過。
- 完成 M11：正式 Tree Explorer 跟隨 backend group hierarchy，固定 direct-group selection、Top 10、race isolation 與 bounded scroll；typecheck、10 widget tests、36 adapter tests、build 與 1280／390 browser smoke 全部通過。
- M11 未重啟 backend／`omi_search`、未 commit、未 push、未新增 tool 或 DB read；交由使用者先驗證前端。
- 啟動 M11 自選股 Tree frontend formalization；確認 backend／adapter contract 足以支援 Tree selection 與 direct-group request，本階段不新增 tool、不改 DB。
- 使用者驗收否決 M9 layout deletion；確認自選必須對應既有 OMI 台股自選樹，並要求恢復底下全部原始操作介面。
- 啟動 M10 保守修正：以改版前備份為 layout baseline，撤銷移除 `OrderShell`，只保留 state correctness、色票、字型與按鈕內容修改。
- 完成 M10：恢復原始 layout 與 disabled OrderShell，接回 backend 真實 watchlist tree，移除 preview 示意群組；typecheck、7 widget tests、36 adapter tests、build 與 1280／390 browser smoke 全部通過。
- M10 未執行 component restart、commit、push 或 remote connector 變更；交由使用者先驗證前端。
- 啟動 M9 Dashboard 互動與視覺改版長專案；新增 goals、non-goals、hard constraints、deliverables、done criteria、五階段施工與 stop-and-fix rules。
- 完成 source／產品文件／desktop detail／390px mobile preview 稽核；決定保留既有 stack、分離熱門族群與自選群組、移除 disabled 委託空殼，並由使用者負責最終 ChatGPT host 主觀驗收。
- 完成 M9 additive watchlist-group／industry-label contract、scope-aware async state、desktop/mobile 工作流與 OMI dark visual system。
- 修正 preview stock identity 與群組切換 polling 等待風險，完成 backend `11 passed`、widget `7 passed`、adapter `36 passed`、typecheck/build 與 isolated browser 驗證。
- M9 technical validation 已完成；未執行 component restart、commit、push 或 remote connector 變更。
- 依使用者提供的暗色交易 terminal prototype 重整 ChatGPT widget 視覺，保留 backend-owned session、freshness、breadth、index 與 technical evidence。
- 新增固定 disabled 的委託草稿空殼；沒有新增 order tool、broker 連線、資料寫入或自動交易行為。
- 完成 typecheck、widget tests、adapter regression、production build、480px／1200px browser validation 與 component-scoped runtime adoption。

### 2026-08-14

- 因電腦中斷後重建長專案規劃。
- 新增完整任務規格、九階段實作計畫、風險、驗證與 rollback 策略。
- 新增 backend dashboard/search/detail contract 與 08:30 collector gate；未修改 database、runtime 或 Git history。
- Targeted backend regression 為 55/55 通過。
- 完成 MCP Apps resource/tools、React widget、isolated browser validation 與 full backend safe validation。
- 修正 `OMI_search` controller 與 server 的 source build artifact 集合不一致，並完成 component-scoped restart、buildId/owner/listener 驗證。
- 透過 OMI launcher 採用 backend route，完成正式 retained-session MCP resources/tools/dashboard/search/detail outward smoke。
