# OMI 4.4.0 TW／US Shared Core Source Consolidation

## Goal

- 將目前已完成的 TW、US、Shared Market Data、AI outward、MCP contract 與 Frontend compatibility 工作收斂成可驗證的 OMI 4.4.0 source 基線。
- 修正三個會阻擋封版的 P1：finalized Daily 被 provisional overlay 覆蓋、US INDEX volume 被投影為零、US capability selection limit 未傳入 Daily reader。
- 建立可在本機 `main` 基線上重現的 exact dependency closure 與驗證門檻，不以 dirty checkout 冒充可發布成果。

## Non-goals

- 不增加 `^SOX` 第二個 Daily provider，也不以 ETF 替代 index identity。
- 不啟用 US full-market scheduler、priority rollout 或無界 backfill。
- 不處理 JP／KR、Fundamentals、US Intraday、Quote realtime 或新 UI 功能。
- 不在本任務自動 commit、merge、push、tag 或發布 release。
- 不刪除、重建或覆蓋 production DB，也不把 secrets、local env、logs 或 raw provider payload納入版本控制。

## Hard constraints

- `Provider -> Canonical Observation -> Resolver／Control -> Market／Research -> API／AI -> Frontend／MCP` 依賴方向不變。
- GET／read path保持cache-only；三個修復不得觸發provider I/O、refresh、repair、enqueue或DB write。
- `Unknown`、`missing`、`not_applicable` 與 `0` 維持不同語意。
- `omi.decision.v4` 維持唯一 outward decision contract；selection limit由backend執行，consumer不補資料或重算coverage。
- Source、Runtime、Live、Product acceptance分開；source green不推定runtime已採用。
- 目前dirty worktree中的既有變更視為使用者成果，不revert、不廣泛格式化、不使用`git add .`。

## Context

- Repo：`C:\project\Open Market Intelligence`
- Current checkout：`codex/tw-etf-provider-normalization` at `f8085f5`，與`origin/main`相同。
- Local `main`：`0b7faa8`，另含一筆24-file台股commit；其中`backend/app/db/models.py`與`backend/app/market/daily_price_repository.py`和dirty worktree重疊。
- Baseline：Git index空白；可見dirty entries為114 modified、1 deleted、91 untracked，另有兩個ACL不可讀pytest暫存目錄。
- Current runtime evidence：3711 finalized 2026-08-28仍被同日provisional overlay取代；`^SOX` top-level volume applicability正確但point仍為0；US context只轉送requested capabilities，未轉送Daily selection limit。

## Deliverables

- 三個P1的minimal source fix與negative／positive regressions。
- 4.4.0 version、README與CHANGELOG source基線。
- `CurrentImplementationState.md`及相關active plan的truthful checkpoint。
- exact integration closure、migration／secret／architecture／consumer contract驗證結果。

## Done criteria

- 同日期已finalized台股Daily不再被intraday overlay替換；較新未finalizedsession仍可overlay。
- Yahoo Daily INDEX即使raw volume為0，也輸出`volume=None`、`volume_status=not_applicable`；STOCK／ETF與1m規則不變。
- `selection.limits["daily.ohlcv"] = 260`使US canonical Daily與chart reader實際讀取至少260根，且維持cache-only。
- 相關backend／AI／Shared／architecture／Frontend／MCP驗證通過，沒有新增undeclared debt。
- version surface一致為4.4.0；文件只宣告Source consolidation，不宣告未驗證Runtime／Live／Product或`^SOX` provider coverage完成。
- 最終工作樹仍可能保留未納入的使用者變更，但exact closure與剩餘項目有清楚分類。

## Open questions / assumptions

- 本輪以本機`main`的`0b7faa8`作未來isolated integration base；在未建立staged tree前不改變branch或merge。
- 4.4.0是source consolidation立腳點；runtime adoption與publication需獨立gate。
