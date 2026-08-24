# Open Market Intelligence AGENTS.md

本檔是 Open Market Intelligence（OMI）repo-level agent instructions。它繼承全域 `~\.codex\AGENTS.md` 與 `C:\project\AGENTS.md`；若規則衝突，以更具體、更新且已確認的 repo / product 文件為準。

使用者可見的 Codex 回覆、交付摘要與固定欄位標題預設使用繁體中文；程式碼、指令、log、error、identifier 與 provider 名稱保留原文。

## 專案定位

OMI 是本機優先、evidence-first 的市場情報與交易決策研究工作台。

長期方向：

- 目前優先服務使用者自己的實際投資研究流程，同時維持可開源、可安裝、可長期維護的產品品質。
- OMI 的雙核心是：
  1. **Market Data Foundation**：可信市場資料、Canonical Observation、Resolver、freshness、repair、source health 與資料 lineage。
  2. **Research / Decision Core**：技術、籌碼、基本面、跨市場關係、情境、風險、反證與 AI decision。
- 台股是 OMI 的 **primary / reference market**：資料完整度、UI pattern、市場語意與驗證標準優先以台股建立。
- 美股是 OMI 的 **first-class research market**：可以獨立進行行情、技術、基本面、跨市場與持倉研究，不再被限制成只服務台股 context。
- 日股、韓股、Crypto、Resource 與其他市場預設是 secondary / context markets；可以逐步升級，但不得因擴充而建立互不相容的市場資料架構。
- 不同市場可以有不同 microstructure、session、provider、depth 與 regulation，但共同市場資料必須優先走共用 Canonical / Resolver contract。

OMI 不做自主交易。任何未來 broker execution 若存在，必須是獨立 Execution Plane、明確使用者動作、可追蹤、可取消，且不得讓 AI 自主下單或以研究結果直接觸發交易。

## Current Truth 文件

非平凡功能、產品判斷、重大 UI/API/資料邊界調整開始前，依序讀取：

- `docs/product/ProductVision.md`
- `docs/product/OperatingModel.md`
- `docs/product/QualityBar.md`
- `docs/product/Roadmap.md`
- `docs/architecture/BackendArchitecture.md`
- 若涉及 outward AI contract，再讀 `docs/architecture/OmiDecisionContract.md`

`docs/agent-runs/*` 是歷史任務紀錄，不是 current product truth。舊文件中的「US 只能是台股 context layer」、「service 直接擁有 fallback」或其他過時假設，不得覆蓋上述 current truth。

空白模板不是產品事實。若當次需求與已填寫的 current truth 衝突，要先指出衝突、影響與較穩定方案。

## 架構憲法

以下 invariant 長期有效，除非使用者明確重新定義產品架構。

### Market Data

- Provider 不得偽裝成其他 Provider。
- Provider adapter 只負責 IO、登入/訂閱、payload parsing、provider-specific error normalization 與產生 Canonical Observation。
- Consumer 不得自行選 provider、重做 fallback、freshness 或 trading status。
- Cross-provider fallback、selection、realtime policy、lease lifecycle、freshness 與 dataset health 由 backend Control / Resolution Plane 擁有。
- Market Data 的依賴方向是：

```text
Provider / Integration
        ↓
Canonical Observation
        ↓
Resolution / Control Plane
        ↓
Market / Research Services
        ↓
AI / API
        ↓
Frontend / MCP / Kuro / external consumer
```

- `KGI -> 假 MIS payload -> MIS semantic owner` 只能作 legacy compatibility，不得作新功能方向。
- 新增 KGI US、Yahoo、AlphaVantage、TWSE MIS 或未來 provider 時，都先轉成 provider-neutral observation，再進 Resolver。
- Unknown 不得默認成零。
- No Quote 不代表 No Trade。
- No Trade 不代表 Suspended。
- Market Session 與 Instrument Trading Status 必須分開。
- Freshness 必須考慮 instrument trading eligibility。
- 所有 selected evidence 必須保留 provider、source、event time、fetched/received time、fallback 與 selection reason。
- Provider Health、Dataset Health、Resolved Evidence Health 是三種不同狀態，不得混成一個「來源正常/異常」。

### Dataset Lifecycle

- Dataset 的 expected date、eligibility、owner、refresh operation、postcondition 與 stale rule 應由明確 registry / contract 擁有。
- 能發現 stale 不等於已具備 repair path；不得把「可偵測」描述成「可自癒」。
- Bounded refresh 必須有 target、range、timeout、call budget、provider lineage、結果摘要與失敗回報。
- `cache_only` read path 不得偷偷啟動 provider fetch 或 subscription。
- `require_live` 可在 policy 與 budget 允許時建立 bounded research lease，但不得擴成無界全市場 subscription。
- 背景 collector 只能服務明確 bounded universe。

### Capability

- Advertised capability 必須真的有對應 projection。
- 若 capability 宣告 refreshable，必須存在可執行 refresh operation 與 bounded policy。
- CI / contract test 應保護 `advertised => projection exists`。
- Planned、missing、not_applicable、unavailable、plan_restricted、rate_limited 等狀態必須如實 outward，不得用 placeholder 假裝 supported。

### Account / Portfolio

- KGI Quote、KGI Data、KGI Account 是不同 capability，即使共用 SDK/runtime 也不得共用單一健康燈號。
- Account / Portfolio 是獨立 Account Plane，不屬於 Market Data Provider path。
- Position / Cost / Cash 來自 Account Plane；市場價格與 FX 來自 Market Data Resolver。
- Account 503 不代表 Quote 故障。
- Account refresh 失敗不得把既有持倉 destructive replace 成空。
- Unknown cost basis 不得轉成 0；cost unknown 時 unrealized PnL 也應 unknown。

## 產品方向保護

- 如果需求會把 OMI 變成「猜漲跌」或保證績效工具，必須反駁。正確方向是 evidence、情境、回測區、進場條件、失效條件、風險、反證與資料限制。
- 如果需求要求隱藏 stale、partial、missing、provider failure、best-effort 或 fallback，必須反駁。
- 如果需求讓 frontend、MCP、Kuro 或其他 consumer 重做 backend 市場邏輯，必須反駁。
- 如果需求讓 provider adapter 直接決定跨 provider fallback、寫 DB 或承擔 AI decision logic，必須反駁。
- 如果需求會造成無界 backfill、稀缺 quota 浪費、資料污染、不可逆 schema/data 操作或秘密外洩，必須先停止並提出安全方案。
- 不因「台股是 reference market」而阻止美股成為正式研究市場；但新增市場仍應優先對齊共同 Canonical / Resolver / outward contract。

## Backend 邊界

- Backend dependency、Market Data Foundation、provider HTTP、source health 與 transaction ownership 以 `docs/architecture/BackendArchitecture.md` 為準。
- `backend/app/ai/` 擁有 AI evidence、question routing、decision core、answer contract 與 capability orchestration。
- `backend/app/market/` 保留台股 market-specific services / policies。
- `backend/app/us_market/` 保留美股 market-specific services / policies。
- 共通 Canonical Observation、Resolver、provider policy、dataset registry 與 shared freshness primitives 應放在穩定的 shared market-data boundary，不反向依賴單一市場 service。
- `agents/` 只放 thin external adapter，例如 MCP；不得直接 import DB、provider 或複製市場邏輯。
- `frontend/` 是研究工作台呈現與互動層；修改前先讀 `frontend/AGENTS.md`。
- `data/open_market_intelligence.db` 是本機狀態；未確認前不得刪除、重建或覆蓋。
- DB schema 變更必須走 migration，不得 silent schema drift。

## Runtime 與 Port

- Backend 偏好 `127.0.0.1:8400`，Frontend 偏好 `3000`。
- `8400` / `3000` 是 preferred port，不是永久保證。
- Launcher 會處理 Windows excluded range、既有 listener 與 bind failure，必要時選下一個可用 port。
- 遇到 localhost 行為不一致時，先看 launcher log 的實際 `selected=` 與 runtime env，不要沿用舊 `8300` 假設。

## AI Decision Contract

OMI AI 回答優先輸出可驗證的研究決策結構，而不是單句建議。

應盡量包含：

- 目前狀態：價格、趨勢、量價、時間框架、資料日期、session、freshness。
- 情境：偏多、偏空、觀望、風險、失效。
- 回測區：支撐/壓力、均線、VWAP、量價區、前高低或其他可驗證位階。
- 進場/確認條件：需要看到哪些 evidence 成立。
- 失效條件與反證。
- 風險與部位處理。
- provider、missing、partial、stale、fallback 與 best-effort 限制。

`omi.decision.v4` 是 outward decision contract。底層 Market Data Foundation 可以重構，但不得讓 HTTP / SSE / MCP 各自長出不同業務語意。

## 資料刷新與 Realtime Policy

統一使用 backend policy：

- `cache_only`：禁止為即時性啟動 provider fetch/subscription。
- `prefer_live`：優先 live，失敗可 fallback，但必須揭露 semantics。
- `require_live`：允許 bounded live acquisition / research lease；未達 live 必須明確標記 policy 未滿足。
- completed-session 類需求不得無意義地啟動 KGI subscription。

Frontend viewer lease、AI/MCP research lease、background collector lease 是不同 lifecycle，但 provider selection 仍由 Control Plane 擁有。

## Kuro / MCP / External Consumer

- OMI 提供穩定 backend API 與 MCP `omi.ask` / read tools。
- MCP 保持 thin，不自行判斷 market semantics、freshness、provider fallback 或 repair。
- Kuro 負責 persona、語音、提醒與工作流；市場分析 truth 留在 OMI backend。
- Consumer 若需要更多資料，只能提高 bounded selection / policy 再問 backend，不自行 call provider。

## Frontend / UX

- UI 是高密度研究工作台，不是 landing page。
- 台股仍是 UI reference implementation；美股可有等級相同的正式研究體驗，但共用資訊架構與 contract。
- 市場特有差異應由 backend contract 明確暴露，不靠 frontend 猜。
- 不要重複 selection/action control。
- K 線、Radar、Watchlist、Decision Dock、資料面板要維持 desktop/mobile 可讀、可掃描與穩定。

## 修改前檢查

修改前先確認：

- 任務屬於 Provider、Canonical、Resolver/Control、Market Service、Research/AI、Frontend、MCP、Account/Portfolio、DB、Runtime 或 Docs 哪一層。
- 是否存在 nested `AGENTS.md`、product docs、architecture contract 與相關 tests。
- 是否影響 Market Session、Trading Status、freshness、provider fallback、dataset repair、source health 或 Account state。
- 是否影響 outward `omi.decision.v4`、MCP snapshot、Kuro 或 frontend public contract。
- worktree 是否有既有修改，需與其共存而不是 revert。
- 是否存在舊 port、stale runtime、錯 interpreter、KGI isolated runtime 或 provider entitlement 風險。

## 驗證

依修改範圍選最小足夠驗證。

- Docs / prompt / AGENTS / template：UTF-8 讀回與 `git diff --check`。
- 局部 backend：compile/syntax + targeted tests。
- Market Data Foundation、API contract、freshness、DB、scheduler、MCP、cross-market、Account/Portfolio：相關 regression、API/data smoke 與安全 validation profile。
- Frontend：lint/typecheck/build；只有實際 UI 風險時再加 browser/screenshot/e2e。
- 外部大量 refresh、付費/稀缺 quota、發布、發送、交易或破壞性操作：先確認。

預設使用：

```powershell
cd "C:\project\Open Market Intelligence"
.\scripts\run-safe-validation.ps1 -Profile quick
```

常用：

```powershell
.\scripts\run-safe-validation.ps1 -Profile backend
.\scripts\run-safe-validation.ps1 -Profile frontend
.\scripts\run-safe-validation.ps1 -Profile full
```

不要把 E2E、build、長駐 runtime、全量外部 refresh 或清 port owner 當預設動作。

## Git Hygiene

- 不 commit `.env`、secret、local DB、cache、logs、venv、node_modules、build output、private memory 或 runtime state。
- 使用 git 前先看 branch/status/diff。
- 使用者沒有明確要求時，不 commit、不 push。
- 不 revert 未經要求的既有 worktree 變更。

## Project Subagents

只有使用者明確要求 subagents、parallel review 或指定 agent 名稱時才使用。

- `omi-ai-decision-reviewer`
- `omi-data-freshness-reviewer`

Subagent 預設用於讀取、探索與 review；不要讓多個 agent 未協調地修改同一批檔案。

## 長任務文件

大型任務可以建立：

- `docs/agent-runs/<task>/Prompt.md`
- `docs/agent-runs/<task>/Plan.md`
- `docs/agent-runs/<task>/Progress.md`

它們記錄單次任務；不可取代 current truth，也不要把任務進度塞回 repo root `AGENTS.md`。

完成後回報 changed files、驗證結果、剩餘風險與必要的下一步。