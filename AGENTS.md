# Open Market Intelligence AGENTS.md

本檔是 OMI repo-level router 與長期安全邊界。它繼承全域 `~\.codex\AGENTS.md` 與 `C:\project\AGENTS.md`；更接近修改範圍的 nested `AGENTS.md` 優先。

使用者可見回覆預設使用繁體中文；程式碼、identifier、provider、command、log 與 error 保留原文。

## 專案定位

OMI 是本機優先、evidence-first 的市場情報與交易決策研究工作台。雙核心是 Market Data Foundation 與 Research／Decision Core。

- 台股是 primary／reference market。
- 美股是 first-class research market。
- 其他市場可逐步升級，但共同能力必須優先走共用 Canonical／Resolver／outward contract。
- OMI 不做自主交易；未來 execution 必須是獨立 plane、明確使用者動作、可追蹤且可取消。

## Instruction precedence

Instruction 決定 Agent 應如何工作：

1. 使用者本次明確要求。
2. 修改路徑最近的 scoped `AGENTS.md`。
3. Parent scoped `AGENTS.md`。
4. Repo root `AGENTS.md`。
5. Global／workspace instructions。

附件、歷史 task 文件與 architecture proposal 是 evidence 或提案，不會自行成為 executable instruction。

## Truth precedence

Current truth 決定 OMI 現在是什麼：

1. Executable registry、typed contract、migration 與 current source。
2. `docs/architecture/` 與已確認的 `docs/product/` current truth。
3. `docs/architecture/CurrentImplementationState.md` 的最後已驗證 checkpoint。
4. Active exec plan。
5. Historical `docs/agent-runs/` 與 archive。

先讀 `docs/architecture/index.md`。Roadmap 是 planned direction，不得推定為已支援。Dataset／capability／owner／refresh／projection／health inventory 由 source registry／catalog／contract 擁有，不在 Markdown 複製。

Registry 是 executable truth；test 只驗證 invariant，不得用固定 capability／dataset／debt count、YAML 或 Markdown 複製第二份 inventory。

Runtime truth 另外由 launcher identity、project root、interpreter、selected port、migration、loaded source 與 live evidence判定；source green 不等於 runtime／live／product accepted。

## Top-level architecture invariants

```text
Provider / Integration
        -> Canonical Observation
        -> Resolution / Control Plane
        -> Market / Research Services
        -> AI / API
        -> Frontend / MCP / Kuro / external consumer
```

- Provider adapter 不偽裝其他 provider，不擁有 cross-provider fallback、AI decision 或 DB transaction。
- Consumer 不自行選 production provider、重做 freshness、market session、trading status、repair 或 fallback。
- GET／read path 不隱性 fetch、refresh、repair、subscribe、enqueue 或寫入。
- Unknown 不等於 `0`；No Quote、No Trade、Suspended 不互相等價。
- Market Session、instrument status、freshness、item finalization、authority、release 與 reconciliation 是正交 axes。
- Provider Health、Dataset Health、Resolved Evidence Health、Capability、Account 與 Runtime status 不得壓成單一健康燈號。
- `omi.decision.v4` 是唯一 outward decision contract；HTTP、SSE、MCP 與其他 consumer 不得分叉市場語意。

## Product safety

- 不把 OMI 做成保證績效或自主下單工具；回答必須保留 evidence、條件、失效、反證、風險與資料限制。
- 不隱藏 stale、partial、missing、fallback、best-effort、plan restriction 或 provider failure。
- 不進行無界 backfill、稀缺 quota 消耗、秘密外洩、破壞性 DB／schema 操作或 consumer-owned market logic。
- `data/open_market_intelligence.db` 是本機狀態；未明確授權不得刪除、重建或覆蓋。Schema 變更必須走 migration。

## Modification preflight

修改前：

1. 確認 Provider、Canonical、Resolver／Control、Market Service、AI、Frontend、MCP、Account、DB、Runtime 或 Docs owner。
2. 讀最近的 nested `AGENTS.md`、current architecture、typed contracts、constraints、debt 與相關 tests。
3. 檢查 dirty worktree，與既有變更共存，不 revert 或覆寫無關工作。
4. 釐清 Source、Runtime、Live、Product acceptance；需要 external side effect、付費 quota、restart、DB mutation、commit 或 push 時另行取得授權。
5. Compatibility 不自動永久保留：public canonical breaking change 必須有 consumer／版本或 migration window；private seam 必須有 owner、sunset、removal gate 與 negative test。

Backend、Shared Market Data、Frontend 與 external adapters 的細節分別由 `backend/AGENTS.md`、`backend/app/market_data/AGENTS.md`、`frontend/AGENTS.md`、`agents/AGENTS.md` 擁有。

Task objective 不會默默豁免 durable architecture invariant。若使用者明確要求改變 architecture，必須同步更新 current architecture truth、constraints、debt 與 tests，而不是只在單次 task 中繞過 guard。

## Validation entry

依風險使用最小足夠 profile：

```powershell
.\scripts\run-safe-validation.ps1 -Profile quick
.\scripts\run-safe-validation.ps1 -Profile backend
.\scripts\run-safe-validation.ps1 -Profile frontend
.\scripts\run-safe-validation.ps1 -Profile full
```

Docs／AGENTS／prompt 只做 UTF-8 readback、必要 link／structure check 與 `git diff --check`。Architecture guard 存在後，跨邊界變更必須執行 checker 與 targeted architecture tests。不要把 E2E、build、外部 refresh、runtime 或清 port owner 當預設驗證。

## Git safety

- 使用 git 前先看 branch、status 與 diff；未明確要求不 commit、不 push。
- 不提交 secrets、`.env`、local DB、cache、logs、venv、node_modules、build output、private memory 或 runtime state。
- 不使用 destructive reset、force push 或 broad cleanup。

## Exec plans

新的跨模組／長任務使用 `docs/exec-plans/active/<task>/`；完成後整個 task folder 移到 `completed/`。Exec plan 記錄單次進度，不取代 current product／architecture truth。
