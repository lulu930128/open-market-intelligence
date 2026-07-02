# Open Market Intelligence AGENTS.md

本檔是 Open Market Intelligence repo-level agent instructions。它放在 repo root，並繼承全域 `~\.codex\AGENTS.md` 與 `C:\project\AGENTS.md` 的基本工作準則。

## 專案定位

Open Market Intelligence（OMI）是本機優先的市場情報與交易決策研究工作台。

長期方向：

- 目前優先服務使用者自己的投資研究流程。
- 架構、版面與啟動方式要朝未來可開源、可安裝、可被其他人實用的產品品質前進。
- AI decision core 是產品核心；看盤 UI、資料整理、指標、報告與跨市場 context 都是支援 AI 做出技術決策的基礎設施。
- 台股永遠是核心市場。美股、日股、韓股、港股與其他市場是台股研究的延伸 context layer；除非有市場特性必須因地制宜，資料模型、UI 結構、API contract 與分析流程應盡量對齊台股。

OMI 不是自動交易系統。它只能做研究、情境判斷、技術位階推演、資料補齊與決策輔助；不得設計或暗示自動下單、代替使用者執行交易。

## 方向保護與反駁責任

- 如果需求會把 OMI 變成「猜漲跌」工具，必須反駁。正確方向是根據 evidence、技術位階、情境、回測區、進場條件、失效條件、停損/停利、續抱/減碼與反證來做決策輔助。
- 如果需求會把其他市場提升成與台股平等的核心市場，必須先指出這會偏離產品定位；除非使用者明確改變策略，否則要維持台股核心、其他市場輔助。
- 如果需求要求隱藏 stale、partial、missing、best-effort 或 provider failure，必須反駁。資料新鮮度與缺口要可見。
- 如果需求會繞過 trust policy、直接寫入 report/memory、消耗大量外部 quota、污染本機 DB，或讓 GET/read path 產生昂貴 side effect，必須暫停並提出安全替代方案。
- OMI 可以自主補外部資料，也可以使用外部 API；這是正常能力，不需要每次等待使用者手動批准。實作時仍要維持 bounded refresh：有明確目標、資料範圍、成本/次數/timeout 邊界、來源紀錄與失敗回報，避免無限制全市場抓取或隱性大量回補。
- 如果需求會讓 MCP adapter、frontend 或 Kuro 端重做 OMI backend 的市場邏輯，必須反駁。市場資料、AI reasoning、freshness、tool orchestration 的真相來源應留在 OMI backend。

## 架構邊界

- `backend/app/ai/` 是 AI evidence、question routing、decision core、answer contract 與 OMI AI 行為的主要位置。
- 使用者可見的 OMI 回答文字與 structured answer contract，優先在 backend AI 層處理；frontend 只負責呈現與互動，不應重做判斷邏輯。
- `agents/` 只放外部 agent adapter，例如 MCP。Adapter 要保持 thin：呼叫 backend API，不直接 import database、不複製市場邏輯。
- `frontend/` 是 Next.js UI。修改前先讀 `frontend/AGENTS.md`；此 repo 使用新版 Next.js，不能只靠舊知識猜 API。
- `data/open_market_intelligence.db` 是本機 SQLite 狀態；不得在未確認前刪除、重建或覆蓋。
- DB schema 變更必須走明確 migration，不得用臨時欄位或 silent schema drift 解決。

## Runtime 與 Port

- 目前 backend 預設是 `127.0.0.1:8400`，frontend 預設是 `3000`。
- 不要沿用舊的 `8300` 假設；遇到 README、MCP 文件或 `.codex` 設定還寫 `8300` 時，要先用目前 launcher / README / env-driven config 驗證。
- Backend port 由 `OMI_BACKEND_PORT` 或 `APP_PORT` 決定，預設偏好值是 `8400`；Frontend port 由 `OMI_FRONTEND_PORT` 或 `FRONTEND_PORT` 決定，預設偏好值是 `3000`。
- `8400` / `3000` 是偏好 port，不是保證會使用的 port。Launcher 會偵測 Windows TCP excluded range、既有 listener 與 bind failure，必要時自動選下一個可用 port，並把實際 backend URL 同步到 `APP_PORT`、`OMI_BACKEND_PORT`、`API_PROXY_TARGET` 與 frontend proxy env。
- 若 localhost 行為看起來不一致，要先看 `logs/launcher/<date>/launcher.log` 的 `selected=` 記錄與 tray menu 的 Open API Health / Open Dashboard，不要先假設固定是 `8400` 或 `3000`。

## AI Decision Contract

OMI AI 的回答應優先輸出可行的技術決策結構，而不是單句建議。

回答應盡量包含：

- 目前狀態：價格、趨勢、量價、時間框架、資料日期與 freshness。
- 情境：看多、觀望、風險、失效等 scenario。
- 回測區：可能回測的位置、支撐/壓力、均線、VWAP、量價區、前高低或其他可驗證位階。
- 進場條件：需要看到哪些確認訊號，而不是直接說「會漲所以買」。
- 失效條件：跌破哪裡、量價如何惡化、哪個 evidence 會推翻原判斷。
- 風險與部位：停損、停利、減碼、續抱、等待條件。
- 反證：和主要判斷相反的 evidence。
- 資料限制：缺資料、stale、partial、provider failure、best-effort。

如果 evidence 不足，OMI 可以先用 tool 補資料；tool 仍失敗時，必須清楚回報缺口，不得編造資料。

## 資料新鮮度與 Tool Refresh

- 預設流程是先查本機資料與 freshness；若資料不足或過舊，OMI 可以自行使用外部 API 做 bounded refresh，再重建 evidence。
- 對台股資料，優先維持交易日、休市、日界線與 session awareness 的一致性。
- 外部 API / 資料刷新要有邊界：避免無限制回補、重複消耗 quota、在使用者不知情下啟動大量 job。
- 既有 refresh policy 允許的市場資料 cache/backfill 可以自動寫入；產生報告、寫入 AI memory、呼叫 LLM、消耗付費或稀缺 quota 的操作，必須確認現有 trust/budget/policy。沒有明確政策時，採保守預設。
- source health、provider events、warnings、missing data 要成為 AI 回答與 UI 可見狀態的一部分。

## Kuro / 外部工具整合

- OMI 要提供穩定、可被外部工具呼叫的 AI contract，例如 backend API 與 MCP `omi.ask`。
- Kuro 或其他工具可以向 OMI 提出需求，例如「今天整個市場分析」或「某檔股票技術決策稿」。
- OMI 負責用自己的資料與 tool 產出結構化市場分析；Kuro 負責呈現、語音化、提醒與任務牆，不應在 Kuro 端重做市場分析。
- 外部 adapter 不應直接讀寫 OMI DB。需要資料時走 OMI backend API。

## Frontend / UX 原則

- UI 是交易研究工作台，不是展示用 landing page。
- 優先保持資訊密度、掃描效率、版面穩定、圖表可讀性與操作節奏。
- 台股畫面是其他市場畫面的設計基準；新增市場時先對齊台股的資料結構與 UI pattern。
- 不要把同一個控制重複放在多個位置；如果 sidebar 已有 selection/action row，新增控制要融入既有節奏。
- 專業 K 線、OMI dock、Radar、Watchlist、資料面板都要避免文字溢出、控制重疊、圖表遮擋與 mobile/desktop 版面崩壞。

## 修改前檢查

修改前先確認：

- 需求屬於 backend AI、market data、frontend UI、MCP adapter、database migration、launcher/runtime config 或 docs 哪一層。
- 是否有既有測試覆蓋；先搜尋相關 tests。
- 是否有交易日、freshness、provider fallback、cache 或 DB side effect。
- 是否會影響 Kuro / MCP / external caller 的 API contract。
- 是否有舊 port、舊 checkout、stale process 或錯誤 interpreter 的風險。

## 驗證命令

依修改範圍執行最相關檢查。

預設先用安全驗證工具，避免直接啟動長駐 backend runtime、Next dev server、Playwright browser 或 crypto WebSocket collector 導致 Codex 對話卡住：

```powershell
cd "C:\project\Open Market Intelligence"
.\scripts\run-safe-validation.ps1 -Profile quick
```

常用 profile：

```powershell
.\scripts\run-safe-validation.ps1 -Profile backend
.\scripts\run-safe-validation.ps1 -Profile backend -BackendPytestArgs backend\tests\test_crypto_market.py
.\scripts\run-safe-validation.ps1 -Profile frontend
.\scripts\run-safe-validation.ps1 -Profile full
```

`run-safe-validation.ps1` 會替每個步驟設定 timeout、集中 log 到 `.tmp\validation\<timestamp>`，並提示固定敏感 port（`3000`、`3100`、`8400`、`8427`）與 `.env` / `frontend/.env.local` 目前指定 port 是否已有 listener。`-IncludeE2E`、`-IncludeBuild`、`-StopPortOwners -Force` 都必須明確指定；不要把 e2e、build 或清 port owner 當成預設動作。只有在需要驗證真實 browser/runtime 行為時才加 `-IncludeE2E`，並保留短 timeout。

以下分散命令作為 fallback 或精準除錯使用；不要在不知道 runtime 狀態時直接全量串起來跑。

Backend：

```powershell
cd "C:\project\Open Market Intelligence"
.\.venv\Scripts\python.exe -m compileall backend\app
.\scripts\run-backend-tests.ps1
```

Frontend：

```powershell
cd "C:\project\Open Market Intelligence\frontend"
npm run lint
npm exec tsc -- --noEmit --incremental false
npm run build
npm run test:e2e
```

API spot checks：

```powershell
Invoke-RestMethod "http://127.0.0.1:8400/api/system/health"
Invoke-RestMethod "http://127.0.0.1:8400/api/system/provider-events?limit=20"
Invoke-RestMethod "http://127.0.0.1:8400/api/system/source-health-snapshots?market=tw"
Invoke-RestMethod "http://127.0.0.1:8400/api/market/intraday/2330"
Invoke-RestMethod "http://127.0.0.1:8400/api/market/technical/2330?timeframe=today"
Invoke-RestMethod "http://127.0.0.1:8400/api/watchlists/groups/1/radar?mode=action&max_results=8"
Invoke-RestMethod "http://127.0.0.1:8400/api/market/tw-futures/latest?symbols=TXF&refresh=true&session=auto"
```

如果只改局部，選最小有效驗證；如果碰到 AI answer contract、freshness、database、routing 或 cross-market 邏輯，要加跑相關 regression tests。

## Git Hygiene

- 不要 commit `.env`、`.env.local`、`.venv`、`node_modules`、`.next`、local SQLite database、logs、cache、downloaded private data。
- commit/push 前先檢查 staged diff，避免混入 private data、暫存檔、產物或大型資料。
- 使用者沒有明確要求時，不要 commit 或 push。

## Project Subagents

本 repo 提供 read-only custom subagents，只有在使用者明確要求 subagents、parallel review 或指定 agent 名稱時才使用；不要自動啟動。

- `omi-ai-decision-reviewer`：審查 AI decision core、answer contract、MCP/API 行為、OMI dock 與 Kuro-facing OMI 回答。
- `omi-data-freshness-reviewer`：審查市場資料 freshness、外部 API refresh、provider health、交易日/日界線、cache/backfill 與 stale data bug。

這些 subagents 預設用於讀取、探索、審查與回報 findings。除非 parent task 明確要求它們實作局部修正，否則不應修改檔案。
## 長任務文件

大型任務可建立：

- `docs/agent-runs/<task>/Prompt.md`
- `docs/agent-runs/<task>/Plan.md`
- `docs/agent-runs/<task>/Progress.md`

這些檔案應記錄目標、限制、milestone、驗證與決策。不要把單次任務的進度塞進 repo root `AGENTS.md`。



