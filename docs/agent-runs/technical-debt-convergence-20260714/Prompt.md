# 技術債收斂與發佈閘門補強

## Goal

- 在不拆大型元件的前提下，修正本輪架構審查確認的 frontend contract、provider observability、runtime ownership、schema migration、dependency 與 CI 技術債。

## Non-goals

- 不拆分 `MarketDashboardClient.tsx`、圖表元件或 AI 大型模組。
- 不改變既有市場 API 路徑、主要 response shape 或台股核心產品定位。
- 不新增遠端服務、付費 API、外部資料刷新或 DB schema migration。

## Hard constraints

- GET/read path 不得為了刷新 source-health 產生昂貴或無界限 side effect。
- Provider fallback 必須保留原降級行為，且不得把觀測事件寫入失敗變成主流程失敗。
- Alembic 必須成為正常啟動的 schema 真相來源；舊資料不得重建或刪除。
- 多程序背景工作只能有一個 leader，lock 必須在 process 結束時由 OS 自動釋放。
- 不提交 `.env`、SQLite、log、cache、build output 或瀏覽器產物。

## Context

- Repo: `C:\project\Open Market Intelligence`
- Related systems: frontend、backend、SQLite/Alembic、scheduler、provider health、GitHub Actions
- Baseline known state: checkpoint `ee91d6e`; backend 606 tests、frontend lint/typecheck/build 通過；兩條 E2E 因未驗證的持股 payload 造成整頁 crash。

## Deliverables

- Frontend runtime payload guard、完整 E2E fixture、malformed payload regression 與 CI E2E gate。
- Provider fallback event helper、台股 intraday/index fallback 接線與 snapshot-age contract。
- Cross-process runtime lock、單一 background leader、Alembic-only startup 與 schema parity test。
- Python direct dependency pins、Python compatibility matrix、更新 README/架構基準。
- 完整 backend/frontend/E2E/live 驗證證據。

## Done criteria

- Backend full regression、frontend lint/typecheck/build、Playwright smoke 全部通過。
- Migration head 與 SQLAlchemy metadata table 集合一致。
- 第二個 runtime coordinator 無法取得 background leader lock，且不啟動 scheduler/collector。
- Malformed portfolio payload 不再讓 dashboard crash。
- Provider HTTP fallback 會留下 provider event；舊 source-health snapshot 明確標記為 stale。

## Open questions / assumptions

- 現行 launcher 仍採單一 backend process；新增 lock 是為防止多 worker、重複啟動與未來開源部署時的重複背景工作。
