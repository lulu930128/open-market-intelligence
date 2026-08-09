# Progress

## Status

- Current phase: frontend consumer completed
- Last updated: 2026-08-09 Asia/Taipei

## Completed

- 已讀取 repo/product/backend architecture 與適用 skills。
- 已盤點現有 MA、support/resistance、daily history、交易日與 release policy。
- 已定義 backend-only capability contract、非目標與 readiness precedence。
- 已新增 pure calculator 與唯讀 DB service，包含 MA20／MA60 transition、flat projection、drift、20 日已知區間與 scenario zones。
- 已新增具名 Pydantic response schema 與 additive GET route。
- 已完成 current／pending／stale／partial／missing／not-applicable lifecycle 與 reason codes。
- 已確認 backend 階段沒有修改 AI、MCP、frontend、Radar、DB schema 或 scheduler。
- 已新增 typed frontend contract 與獨立載入 hook；只有一般台股個股會呼叫新 endpoint。
- 已在「技術證據」下方、「美股隔夜」上方加入 responsive 隔日支撐／壓力欄位。
- 已補齊繁中、英文、日文文案，以及 shared 更新狀態的 warning／error／recovery 事件。
- 已加入 focused E2E，固定驗證欄位順序、MA20／MA60、scenario zones 與 decision usability。

## Validation evidence

- `backend/tests/test_next_session_plan.py`：15 passed。
- `test_next_session_plan.py + test_technical_structure.py + test_technical_report.py + test_api_contract_inventory.py`：49 passed。
- `run-safe-validation.ps1 -Profile backend -BackendPytestArgs backend\tests\test_next_session_plan.py`：backend compileall、15 tests、git diff check passed。
- `run-safe-validation.ps1 -Profile frontend`：frontend lint、tsc、git diff check passed。
- `npm run build`：Next.js 16.2.12 production build passed。
- focused Playwright：`Taiwan next-session levels render between technical evidence and Overnight`，1 passed。
- 實際重用本 repo 所屬 port 3000 dev runtime 與 port 8400 backend；桌面 931px、手機 390px 都完成瀏覽器驗證，無水平 overflow、無 console error。
- 驗證期間未停止或重啟既有 runtime。

## Decisions made

- 使用獨立 service/schema/route，避免未授權接入目前正在修改中的 AI/MCP。
- GET 只讀 local DB，無 provider refresh、DB write 或 migration。
- 前端只呈現 backend 的 level、scenario、freshness 與 usability，不重新推導市場邏輯。
- operational failure 送入 shared 更新狀態；stale／partial／pending／missing 與 limitations 留在欄位內可見。
- corporate-action adjustment 明確延後，v1 contract 保留 limitation。
- transition price 保留數學值、不任意加入 ATR band，也不做台股 tick rounding；contract 顯式揭露。
- 同交易日若存在多來源日 K，以最新本機 row id 做 deterministic selection，並輸出 source IDs 與 duplicate count。

## Known issues / risks

- Worktree 已有大量其他功能變更；本任務必須維持 localized diff。
- v1 使用 raw/unadjusted close，未執行 corporate-action event check；遇除權息附近資料時 consumer 必須保留 limitation。
- v1 是條件轉換位階，不含量價確認、假突破過濾、勝率或 outcome backtest。

## Next step

- 等使用者確認欄位資訊密度與語氣後，再規劃 AI/MCP 的 thin consumer；目前仍不接入。
