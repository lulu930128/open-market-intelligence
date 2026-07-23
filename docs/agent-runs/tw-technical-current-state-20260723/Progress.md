# 進度紀錄

## Status

- Current phase: complete
- Last updated: 2026-07-23 20:42 Asia/Taipei

## Completed

- 已核對 2478 實際 technical API 與右側呈現。
- 已確認 backend 主值 MA20、價格列主值 MA60 的資訊層級衝突。
- 已讀取產品方向、既有 technical-card agent run、相關 tests 與 Next.js client/accessibility 文件。
- 已鎖定向後相容的 `data.current_state` v1 contract。
- 已完成 backend-owned headline、qualifier、均線位置、修復/風險階梯、四組 evidence 與 next conditions。
- 已修正收盤後已有同日 finalized indicator 時仍套用 provisional intraday price 的問題。
- 已完成日 K summary-first UI；技術證據與籌碼/隔夜/市場 context 均預設收起。
- 已補齊繁中、英文、日文文案與 focused Playwright fixture。
- 已盤點上方標籤 projection：classification 與 headline 重複、trend/momentum 優先抓 MA20/MACD badge、volume fallback 產生重複文案。
- 已確認隔夜 backend 已提供含中性區間的 stance；相對大盤目前為兩個漲跌幅相減，應以百分點呈現。
- 已將標籤分成「核心判讀」與「背景脈絡」，移除重複的 classification 標籤。
- 已讓結構、動能、量價、風險四個核心標籤直接映射 `current_state`，避免由 frontend 各自猜測結論。
- 已補上單日、資料日與百分點語意；融資餘額變化維持中性色，隔夜判讀沿用 backend stance。
- 已加入標籤至證據區的導覽：點擊核心標籤展開對應技術指標，點擊背景標籤展開外部背景。

## Validation evidence

- `GET /api/market/technical/2478?timeframe=daily&include_intraday=true`：取得 2026-07-23 指標與 MA5/20/60 完整結構。
- Current dirty worktree 已記錄；本任務不會 revert 其他修改。
- Backend targeted regression：`23 passed`。
- Frontend `npx tsc --noEmit`：通過（含標籤 projection 與互動修改）。
- Frontend targeted ESLint：通過（含元件、projection、i18n 與 focused E2E）。
- Frontend `npm run build`：通過（Next.js production build）。
- Focused Playwright：`1 passed`，驗證核心／背景分組、標籤數值與色彩語意，以及點擊展開對應證據。
- 2478 本機資料 business call：`daily` / `high` / 非 provisional；結論為「空方趨勢延續、超賣但尚未止跌、放量下跌」。
- `git diff --check`：通過；僅顯示 repo 既有 LF/CRLF 提示。

## Decisions made

- 分析語意放 backend；frontend 只映射、排版與收合。
- 日線使用新 current-state view；today/weekly/monthly 保留既有呈現。
- 詳細指標與籌碼/隔夜/市場 context 預設收起。

## Known issues / risks

- 目前 8400 runtime 仍可能是舊 process；本次以同一資料庫的直接 business call 驗證新 contract，未重啟既有服務。
- Frontend 技術卡、technical report 與 i18n 檔原本已有其他未提交修改；本任務只追加局部內容，未覆寫或 revert。
- Pytest 全數通過，但因 sandbox 無法建立 `.pytest_cache` 而有 1 個非功能性 warning。

## Next step

- 如要進一步提升掃讀效率，可在實際 runtime 重啟後，以 2478 與一檔多頭股票做並排視覺驗收。
