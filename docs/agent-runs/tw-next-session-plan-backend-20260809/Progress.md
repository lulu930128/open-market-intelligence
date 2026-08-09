# Progress

## Status

- Current phase: frontend implementation
- Last updated: 2026-08-09 Asia/Taipei

## Completed

- 已讀取 repo/product/backend architecture 與適用 skills。
- 已盤點現有 MA、support/resistance、daily history、交易日與 release policy。
- 已定義 backend-only capability contract、非目標與 readiness precedence。
- 已新增 pure calculator 與唯讀 DB service，包含 MA20／MA60 transition、flat projection、drift、20 日已知區間與 scenario zones。
- 已新增具名 Pydantic response schema 與 additive GET route。
- 已完成 current／pending／stale／partial／missing／not-applicable lifecycle 與 reason codes。
- 已確認沒有修改 AI、MCP、frontend、Radar、DB schema 或 scheduler。
- 使用者已授權 frontend 第二階段；完成插入點、資料 hook、i18n、更新狀態與 E2E seam 盤點。

## Validation evidence

- `backend/tests/test_next_session_plan.py`：15 passed。
- `test_next_session_plan.py + test_technical_structure.py + test_technical_report.py + test_api_contract_inventory.py`：49 passed。
- `run-safe-validation.ps1 -Profile backend -BackendPytestArgs backend\tests\test_next_session_plan.py`：backend compileall、15 tests、git diff check passed。
- 驗證期間偵測到既有 port 3000 node listener；未停止或重啟該 runtime，且本任務不需 browser/runtime 驗證。

## Decisions made

- 使用獨立 service/schema/route，避免未授權接入目前正在修改中的 AI/MCP。
- GET 只讀 local DB，無 provider refresh、DB write 或 migration。
- corporate-action adjustment 明確延後，v1 contract 保留 limitation。
- transition price 保留數學值、不任意加入 ATR band，也不做台股 tick rounding；contract 顯式揭露。
- 同交易日若存在多來源日 K，以最新本機 row id 做 deterministic selection，並輸出 source IDs 與 duplicate count。

## Known issues / risks

- Worktree 已有大量其他功能變更；本任務必須維持 localized diff。
- v1 使用 raw/unadjusted close，未執行 corporate-action event check；遇除權息附近資料時 consumer 必須保留 limitation。
- v1 是條件轉換位階，不含量價確認、假突破過濾、勝率或 outcome backtest。

## Next step

- 實作 typed frontend contract、獨立載入 hook、responsive panel 與 focused E2E；AI/MCP 仍不接。
