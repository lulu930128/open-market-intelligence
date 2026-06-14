# Open Market Intelligence

Open Market Intelligence（OMI）是一套本機優先的市場情報與看盤研究工作台。它把自選股、盤勢脈絡、盤中監控、K 線分析、籌碼資料、基本面資料、美股隔夜訊號，以及 AI/Agent evidence 介面整合在同一個專案中。

目前產品主軸是台股。美股模組已可作為台股研究的領先訊號層，特別適合觀察半導體、AI 基建、雲端、記憶體、ETF 與大型科技股對台股供應鏈的影響。日股、韓股、港股入口先保留，後續再擴充。

<p align="center">
  <img src="docs/assets/readme/omi-stock-workbench.png" alt="Open Market Intelligence stock workbench with watchlist, K-line chart, technical indicators and chip-flow panels" width="960">
</p>

## 目前狀態

這版是台股 v2 基線版，日常本機研究流程已具備可用穩定度：

- 台股 dashboard：大盤脈絡、自選股群組、群組排行、背景更新狀態、資料過期 loading guard。
- 台股個股頁：`今日`、`日K`、`週K`、`月K` 共用一致版型。
- 台指期頁：TXF、MXF、TMF 報價、日內/日週月 K、期現價差、成交量與商品比較。
- 專業 K 線模式：台股、美股、台指期共用同一套全寬圖表 shell，支援壓縮 header、指標分類、畫線工具、量測工具、undo/redo、畫線快照保存。
- 台股籌碼與基本面：法人、融資融券、集保、券商分點 Top15、營收、財報、盈餘。
- 美股市場：主要指數、自選股、OHLC、盤中資料、SEC facts、Alpha Vantage profile/actions、FINRA short volume、FRED macro。
- AI/Agent 入口：`POST /api/ai/ask` 與 MCP `omi.ask`，支援 evidence freshness、warnings、missing data、tool runs。

## 產品原則

- 本機優先：SQLite、cache、jobs、agent evidence 預設都在本機。
- Evidence before narrative：AI 只能讀 bounded local evidence，不應編造不存在的市場資料。
- 新鮮度可見：stale、partial、missing、best-effort 狀態要顯示出來。
- 台股優先：美股是台股研究的 context layer，不是台股資料替代品。
- 讀取路徑保持輕量：昂貴或會改資料的刷新行為走明確 POST/job route。

## 功能地圖

### 台股 Dashboard

- TAIEX 與 TPEx 市場卡片。
- 自選股樹狀群組、群組數量、群組總覽、排序、排行、reload/backfill 控制。
- 背景工作中心，台股與美股工作分開顯示。
- stale-date guard：資料日期不正確時先顯示 loading/empty 狀態，不直接展示舊資料。

### 台股個股頁

- Header 顯示代號、名稱、價格、漲跌點、漲跌幅，並有價格更新 pulse。
- `今日` 使用盤中資料、昨收、VWAP、TWAP、EMA、RSI、MACD、成交量與 hover guide line。
- `日K`、`週K`、`月K` 使用歷史 OHLC 與衍生技術指標。
- Technical summary 依 timeframe 切換盤中、短線、波段、長線觀點。
- 分析區與資料區分離，避免技術解讀和基本面/籌碼資料混在同一層。

### 專業 K 線模式

專業模式會保留左側自選股與目前商品 context，並將 K 線圖最大化。

台股個股、美股個股/指數與台指期都使用共用的 `ProfessionalChartPanel`：

- 台股：支援盤中分鐘線、日 K、週 K、月 K 與台股技術指標資料。
- 美股：支援 Yahoo chart OHLC/intraday、指數與個股 context。
- 台指期：支援 `今日`、`日K`、`週K`、`月K`，成交量以口數顯示，畫線 context 使用 `TW_FUTURES` market。

支援控制：

- 週期：台股與美股支援 `1分`、`5分`、`15分`、`30分`、`1小時`、`4小時`、`日`、`週`、`月`；台指期支援 `今日`、`日K`、`週K`、`月K`。
- 圖表型態：K 線、折線。
- 指標分類：趨勢、均線、通道、波動、動能、成交量、相對強弱、型態、風險。
- 畫線工具：游標、水平線、趨勢線、射線、區間、Fibonacci、anchored VWAP、量價分布、量測、價格百分比。
- 操作工具：undo、redo、刪除選取物件、清除畫線、保存畫線數。

畫線快照會先存本機，並透過以下 route 做 best-effort sync：

```text
/api/market/chart-drawings/{market}/{symbol}/{timeframe}
```

畫線表儲存的是 bounded JSON，定位是使用者註記、AI 可讀圖表 context、未來報告素材，不是下單或交易紀錄。

### 台股資料面板

- 籌碼：TDCC 集保分布、融資融券、大盤籌碼日報。
- 法人：三大法人買賣超、法人持股比例、歷史淨買賣。
- 分點：nStock 券商分點 Top15，支援單日與多日加總。
- 營收：月營收歷史。
- 盈餘與基本面：MOPS/MOPSOV 季度財務指標。

### 台指期

台指期是台股研究的衍生性商品 context，和台股 dashboard 共用同一個市場入口。

目前支援：

- 商品：TXF、MXF、TMF。
- 報價：日盤/夜盤最新價、漲跌、漲跌幅、報價時間、契約月份。
- K 線：日內、日 K、週 K、月 K。
- 重點資訊：開高低、參考/結算、期現價差、振幅、成交量、未平倉、買賣價。
- 專業模式：和台股/美股共用工具列、圖表型態切換、技術指標選單、畫線工具與本機/遠端畫線快照。

### 美股市場

美股定位是台股供應鏈與隔夜市場 context。

目前支援：

- 指數脈絡：S&P 500、Nasdaq Composite、Dow Jones Industrial Average、Philadelphia Semiconductor Index。
- 美股自選股樹與排行。
- 本地主檔缺少新上市股票時，使用 Yahoo chart metadata 做 symbol fallback discovery。
- Yahoo chart OHLC 與 intraday。
- SEC company facts 與 normalized fundamentals。
- Alpha Vantage overview、dividends、splits，需設定 `ALPHAVANTAGE_API_KEY`。
- FINRA daily short sale volume。
- FRED macro observations，需設定 `FRED_API_KEY`。
- 美股自選股資源批次刷新工作。

重要限制：

- 美股採 universe-first，不預設全市場大量回補。
- Yahoo chart 是 best-effort unofficial source。
- Alpha Vantage 與 FRED 受 API key 和 rate limit 影響。
- SEC EDGAR 需要描述清楚的 `US_SEC_USER_AGENT`。
- FINRA short volume 是每日 short sale volume，不是 short interest position。

## 資料來源信任模型

OMI 把每個來源都當作帶有 provenance 與 freshness 的 evidence，而不是單一無條件真相。

| 區域 | 來源 | 信任說明 |
| --- | --- | --- |
| 台股上市價量 | TWSE OpenAPI/RWD、TPEx endpoints | 優先官方來源；顯示前仍檢查日期與筆數。 |
| 台股盤中 | nStock minute data、TWSE MIS volume adjustment | 適合本機監控；盤中可用性會受來源狀態影響。 |
| 台股大盤/指數 | TWSE/TPEx market endpoints、部分 Yahoo fallback | 官方日資料優先；Yahoo 只補官方歷史覆蓋不足處。 |
| 台股籌碼 | TWSE BFI82U、TPEx institutional summary、TDCC | 發布時間很重要，排程需晚於來源發布窗口。 |
| 台股基本面 | MOPS/MOPSOV | 官方來源族群；parser 需用 quality check 防格式變動。 |
| 券商分點 | nStock branch Top15 | 便利型非官方來源；多日模式是已存 Top15 snapshot 加總，不是完整分點帳本。 |
| 美股 OHLC/盤中 | Yahoo chart、Alpha Vantage daily | Yahoo best-effort；Alpha Vantage 受 key/rate limit 影響。 |
| 美股基本面 | SEC EDGAR company facts | 公司申報官方來源；ETF 或非公司資產可能沒有 facts。 |
| 美股 profile/actions | Alpha Vantage | 補充資料，API-key dependent。 |
| 美股 short volume | FINRA CNMS daily short volume | 官方每日 short sale volume，不是 short interest。 |
| Macro | FRED | 官方 FRED API，需 key。 |

設計規則：如果來源 stale、partial 或 unavailable，UI 與 AI response 要透過 `warnings`、`missing`、status chip、loading state 顯示出來。

## 架構

```mermaid
flowchart LR
    user["User"] --> browser["Browser<br/>127.0.0.1:3000"]
    browser --> next["Next.js dashboard"]
    next --> proxy["/omi-data proxy"]
    proxy --> api["FastAPI<br/>127.0.0.1:8300/api"]

    api --> services["Domain services"]
    services --> db[("SQLite<br/>data/open_market_intelligence.db")]
    services --> jobs["Background jobs"]
    jobs --> fetch["Fetch + parse pipelines"]

    fetch --> raw["raw_fetch_result"]
    raw --> quality["data_quality_check"]
    quality --> tables["Market tables"]
    tables --> db

    api --> ai["AI evidence + omi.ask"]
    ai --> tools["Allowlisted refresh/read tools"]
    tools --> services
```

## 專案結構

```text
.
├─ agents/
│  └─ omi_mcp_server/          stdio MCP adapter for external assistants
├─ backend/
│  ├─ alembic/                 schema migrations
│  ├─ app/
│  │  ├─ ai/                   omi.ask, freshness, evidence, tools, LLM calls
│  │  ├─ db/                   SQLAlchemy models/session/migration helpers
│  │  ├─ jobs/                 background job queue and task runners
│  │  ├─ market/               Taiwan market data, indicators, chips, reports
│  │  ├─ parsers/              TWSE/TPEx/MOPS/TDCC parsers
│  │  ├─ routers/              FastAPI routers
│  │  ├─ sources/              source registry seed definitions
│  │  ├─ stocks/               Taiwan stock master/profile
│  │  ├─ us_market/            US symbols, OHLC, SEC facts, profile, macro
│  │  └─ watchlists/           Taiwan watchlist tree/ranking/backfills
│  └─ tests/
├─ frontend/
│  └─ src/
│     ├─ app/                  Next.js App Router
│     ├─ components/           dashboard, shared professional charts, panels, loading UI
│     ├─ lib/                  API client, market-time helpers, job helpers
│     └─ types/                frontend API types
├─ docs/assets/readme/         README screenshots
├─ scripts/                    local launcher and maintenance helpers
├─ data/                       local database; ignored by git
└─ reports/                    local reports; ignored by git
```

## API Map

| Prefix | 用途 |
| --- | --- |
| `/api/system` | Health 與 runtime status |
| `/api/sources` | Source registry、fetch runs、logs |
| `/api/raw-results` | Raw payload inspection 與 quality checks |
| `/api/jobs` | Background job status |
| `/api/ai` | `omi.ask`、tools、strategy profiles、reports |
| `/api/stocks` | 台股 search、master、profile |
| `/api/watchlists` | 台股 watchlists、groups、ranking、backfills |
| `/api/market/ohlc` | 台股日/週/月 OHLC |
| `/api/market/intraday` | 台股盤中 trend |
| `/api/market/technical-report` | timeframe-aware technical reports |
| `/api/market/chart-drawings` | K 線畫線快照保存 |
| `/api/market/broker-branches` | 券商分點 Top15 與 aggregate summaries |
| `/api/market/institutional` | 法人買賣與持股比例 |
| `/api/market/margin` | 融資融券 |
| `/api/market/shareholding` | TDCC 集保分布 |
| `/api/market/revenue` | 月營收 |
| `/api/market/financials` | 季度財務指標 |
| `/api/market/backfill` | 台股 backfill jobs |
| `/api/market/tw-futures` | 台指期 TXF/MXF/TMF 報價、日內與日 K 資料 |
| `/api/us-market` | 美股 symbols、watchlists、OHLC、intraday、SEC facts、profile、actions、macro |

## AI And Agent Contract

AI 是 local evidence 的讀取者與分析者，不是資料真相來源。

外部助理應使用 `POST /api/ai/ask` 或 MCP `omi.ask`。

支援模式：

| Mode | 行為 |
| --- | --- |
| `auto` | 後端依 request 與 trust policy 選擇最安全模式。 |
| `data_only` | 回傳 structured local evidence，不產生敘事。 |
| `brief` | 回傳精簡 evidence summary。 |
| `analysis` | 在 trusted 且允許時呼叫 OpenAI 產生非持久分析。 |
| `report` | 在 trusted、LLM enabled、write enabled 時呼叫 OpenAI 並保存 report。 |

支援 horizon：

| Horizon | 用途 |
| --- | --- |
| `intraday` | 盤中/即時監控。 |
| `short` | 短線日資料與動能。 |
| `swing` | 預設中短線/波段。 |
| `long` | 週/月與基本面 context。 |

Minimal request：

```json
{
  "question": "2330 近況如何？",
  "target_type": "tw_stock",
  "target_id": "2330",
  "mode": "analysis",
  "horizon": "swing",
  "allow_llm": true,
  "allow_external_fetch": false,
  "allow_write": false
}
```

下游 UI 或桌寵應保留這些欄位：

```text
warnings
missing
source_refs
freshness
tool_plan
tool_runs
mode.effective
analysis.human_answer
```

這些欄位屬於 trust 與 freshness model，不只是 debug metadata。

## MCP Adapter

後端啟動後再啟動 MCP adapter：

```powershell
cd "C:\project\Open Market Intelligence"
$env:OMI_API_BASE = "http://127.0.0.1:8300/api"
python agents\omi_mcp_server\server.py
```

可選 trusted-token bridge：

```powershell
$env:OMI_MCP_AI_TRUST_TOKEN = "<same value as backend OMI_AI_TRUST_TOKEN>"
```

`OMI_MCP_EXPOSE_INTERNAL_TOOLS=true` 只應用於 trusted local debugging。

## Local Setup

### Requirements

- Windows PowerShell
- Python 3.10+
- Node.js `>=20.9.0`
- npm `>=10`

### Backend

```powershell
cd "C:\project\Open Market Intelligence"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe -m alembic upgrade head

$env:PYTHONPATH = (Resolve-Path backend).Path
.\.venv\Scripts\python.exe -m app.scripts.seed_sources
```

Run：

```powershell
cd "C:\project\Open Market Intelligence"
$env:PYTHONPATH = (Resolve-Path backend).Path
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8300 --app-dir backend
```

Useful URLs：

- `http://127.0.0.1:8300/api/system/health`
- `http://127.0.0.1:8300/docs`

### Frontend

```powershell
cd "C:\project\Open Market Intelligence\frontend"
npm install
if (-not (Test-Path .env.local)) { Copy-Item .env.example .env.local }
npm run dev
```

Open：

```text
http://127.0.0.1:3000
```

### Launcher

```powershell
cd "C:\project\Open Market Intelligence"
.\Start-OMI-Launcher.cmd
```

Launcher 是本機 convenience wrapper。開發時後端與前端命令仍是 canonical path。

開發模式下 launcher 預期使用 `.\.venv\Scripts\python.exe`。如果 `8300` 被其他 checkout 或其他 Python runtime 的舊 OMI backend 佔用，launcher 會嘗試清掉 stale OMI process 後再啟動目前 checkout。

## Environment

根目錄 `.env.example` 包含 backend settings：

```env
APP_NAME=Open Market Intelligence
APP_ENV=development
DEBUG=true
APP_HOST=127.0.0.1
APP_PORT=8300
TIMEZONE=Asia/Taipei
ENABLE_SCHEDULER=false

ALPHAVANTAGE_API_KEY=
FRED_API_KEY=
US_SEC_USER_AGENT=Open Market Intelligence local research; contact=you@example.com

OPENAI_API_KEY=
OPENAI_LLM_API_KEY=
OMI_OPENAI_ENV_FILE=
OMI_AI_LLM_PROVIDER=openai
OMI_AI_MODEL=gpt-4.1-mini
OMI_AI_REPORT_MODEL=gpt-4.1
OMI_AI_LLM_ENABLED=false
OMI_AI_ALLOW_UNTRUSTED_LLM=false
OMI_AI_TRUSTED_CLIENT_HOSTS=127.0.0.1,::1
OMI_AI_TRUST_TOKEN=
```

Frontend `.env.example`：

```env
NEXT_PUBLIC_OMI_API_BASE=http://127.0.0.1:8300/api
```

OpenAI key resolution order：

1. `OPENAI_API_KEY`
2. `OPENAI_LLM_API_KEY`
3. `OMI_OPENAI_ENV_FILE` 指向的本機 env file

不要提交真實 API keys、tokens 或 private env files。

## Scheduler Notes

`ENABLE_SCHEDULER=true` 時，台股排程以 Asia/Taipei 為準。

相關預設：

```env
SCHEDULER_MARKET_REFRESH_TIME=15:15
SCHEDULER_MARKET_CHIP_REFRESH_TIME=18:35
ENABLE_US_MARKET_SCHEDULER=false
SCHEDULER_US_MARKET_REFRESH_TIME=06:30
SCHEDULER_US_MARKET_REFRESH_DAY_OF_WEEK=tue-sat
```

大盤籌碼日報有發布窗口，排程應晚於 TWSE/TPEx 來源發布時間。

## Database And Migrations

後端啟動時會先跑 Alembic migrations，再打開 application sessions。這能讓舊本機 SQLite database 對齊目前 schema。

手動 migration：

```powershell
cd "C:\project\Open Market Intelligence"
$env:PYTHONPATH = (Resolve-Path backend).Path
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Database path：

```text
data/open_market_intelligence.db
```

## Validation

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
```

API spot checks：

```powershell
Invoke-RestMethod "http://127.0.0.1:8300/api/system/health"
Invoke-RestMethod "http://127.0.0.1:8300/api/market/intraday/2330"
Invoke-RestMethod "http://127.0.0.1:8300/api/market/ohlc/2330?timeframe=daily&limit=120"
Invoke-RestMethod "http://127.0.0.1:8300/api/market/technical-report/2330?timeframe=today"
Invoke-RestMethod "http://127.0.0.1:8300/api/market/broker-branches/2330/daily?days=3&ensure_daily=false"
Invoke-RestMethod "http://127.0.0.1:8300/api/us-market/stocks/search?q=SPCX"
```

Git hygiene：

```powershell
git status --short
git diff --check
```

## Operating Notes

- Frontend API access 應透過 `frontend/src/lib/api.ts` 與 `/omi-data` proxy，除非有明確例外。
- 台股 market time 與 trading-session helpers 放在 `frontend/src/lib/taiwanMarketTime.ts` 與 `frontend/src/lib/taiwanMarketRules.ts`。
- 美股 regular-session helpers 放在 `frontend/src/lib/usMarketTime.ts`。
- 台股、美股與台指期的專業圖表模式應共用 `frontend/src/components/ProfessionalChartPanel.tsx` 與 `frontend/src/components/professionalChartDrawing.ts`；不要在單一 detail panel 重新實作一套工具列。
- Chart dimensions 要穩定；indicator toggle、hover state、label、refresh 不應重置 visible range 或中斷畫線操作。
- 專業 K 線模式要隱藏次要 dashboard panels，但保留左側自選股與目前商品 context。
- 券商分點多日資料是已存 daily Top15 snapshots 的 aggregate，不是完整券商分點帳本。
- 盤中指標由目前 intraday points 計算；早盤 RSI/MACD 可能因資料不足顯示 `-`。
- Agent responses 要明確暴露 stale/partial data，不要隱藏 `warnings` 或 `missing`。

## Current Limitations

- 台股是目前主要 production path；美股可用但仍是 universe-first 且 API-key dependent。
- US-TW supply-chain mapping 還不是完整 semantic layer，先作為 peer、sector、overnight context 使用。
- 日股、韓股、港股目前仍是入口 placeholder。
- 券商分點多日分析取決於已存 daily Top15 snapshots；如果 DB 只有一天，就只能回傳 partial coverage。
- 盤中資料取決於外部來源可用性，必要時會退回 snapshot-only 行為。
- SQLite 適合本機研究與開發；多使用者或長期部署應評估 PostgreSQL 或其他 managed database。

## Production Hygiene

- 不要提交 `.env`、`.env.local`、`.venv`、`node_modules`、`.next`、local SQLite databases、logs、cache directories 或 downloaded private data。
- 不要 hard-code API keys、tokens、passwords、cookies 或 credentials。
- schema 變更要有 explicit migration。
- 新增資料來源時，同步更新 source registry、parser、quality behavior 與 README trust notes。
- 修改 market-data fetch 時，用真實 symbol 檢查日期與筆數。
- 修改 AI 行為時，保留 `omi.ask` envelope，並讓 freshness/partial coverage 對 downstream clients 可見。
