# Progress

## Status

- Current phase: done
- Last updated: 2026-07-23 Asia/Taipei

## Completed

- 盤點既有 USD/TWD、外資大盤與個股資料覆蓋，確認可用現有 cache-only 資料完成。
- 新增 backend `fx_flow_context` builder，產出 1/5/20 日匯率與外資聚合、freshness、missing、warnings 與確認訊號。
- 將 context 納入 overnight impact API，但不改動既有 score 與 stance。
- 在個股右側 OVERNIGHT 報告加入預設收合的「匯率與外資」區塊，展開後顯示細節與限制說明。
- 補齊繁中、英文、日文文案與 frontend/backend contract types。
- 新增 backend regression 與 focused Playwright 收合/展開測試。

## Validation evidence

- Backend targeted regression: 21 passed.
- API contract inventory: 9 passed, 30 subtests passed.
- Ruff targeted check: passed.
- Frontend targeted ESLint: passed.
- TypeScript `tsc --noEmit --incremental false`: passed.
- Next.js production build: passed.
- Focused Playwright: 1 passed，並重用既有 3000 dev server。
- Isolated runtime HTTP smoke on 18400: 200 OK；2330 回傳 `confirmed_outflow`、USD/TWD 32.375、TWD 5d -0.7447%、market foreign 5d -229,721,067,758 TWD、stock foreign 5d -66,417,787 shares。
- Isolated runtime completed shutdown after smoke；現有 launcher-managed 8400 未被中斷。

## Decisions made

- 不新增 provider、DB table、migration 或 GET-side refresh。
- 5 日作為主要確認週期，20 日只作背景；FX 超過 72 小時視為 stale。
- 「台幣弱／強」與「外資流出／流入」只表達 confirmation，不宣稱直接因果。
- 延用 OMI 既有 light dense report、semantic token 與 native `<details>` progressive disclosure。

## Known issues / risks

- Launcher-managed 8400 backend 使用 `reload=False`，仍需由使用者在 OMI tray 執行 `Restart Services` 後才會載入新 API 欄位。
- 目前 2330 個股外資資料停在 2026-07-21，落後預期交易日 2026-07-22，因此 context 正確標示為 `stale`。
- Yahoo FX 是 best-effort delayed context；缺值或過舊時 UI 會保留 partial/stale 訊號，不會假裝是即時匯率。

## Next step

- 由使用者方便時透過 OMI tray 重啟服務，再以現有 8400 runtime 做一次畫面確認。
