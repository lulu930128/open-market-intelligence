# 台股技術卡「現在狀況」強化

## Goal

- 讓台股日線技術卡能一眼回答目前趨勢、動能、量價與風險狀態。
- 以 2478 的「價格低於 MA5/20/60、放量下跌、短線超賣但尚未止跌」情境作為主要驗收案例。
- 將修復階梯、風險線、證據與下一步確認條件整理成 backend-owned structured contract。
- 前端採摘要優先與 progressive disclosure，詳細指標預設收起。
- 將上方訊號標籤拆成核心技術訊號與背景脈絡，並可直接打開對應證據。

## Non-goals

- 不新增 MA40、不改變現有 MA5/20/60 分析基準。
- 不提供自動交易、買賣指令或保證性漲跌結論。
- 不修改 Radar、其他市場技術卡、DB schema 或 scheduler。
- 不移除既有 technical report 欄位，不讓既有 consumer 發生 breaking change。

## Hard constraints

- Backend 是技術狀態、修復條件、風險條件與 freshness 語意的真相來源。
- Frontend 只做 layout、i18n 與收合互動，不重算技術判斷。
- 盤中價與 finalized daily indicators 保持明確區隔；收盤後若同日 finalized daily indicator 已存在，不再標成 provisional intraday。
- 保留 dirty worktree 中其他任務的修改，不做無關重構或格式化。

## Context

- Repo: `C:\project\Open Market Intelligence`
- Related systems: backend technical report / pure technical structure helper / Taiwan stock detail frontend / Playwright fixture
- Current known state:
  - `technical_report` 主值固定使用 `price_vs_ma20`。
  - `price_position` 列右側固定使用 `price_vs_ma60`。
  - 後端已提供 MA5/20/60、RSI、MACD、ADX/DI、ROC、MFI、ATR、Donchian 與支撐壓力資料。
  - 2478 2026-07-23 實際資料為收盤 138、MA5 139.6、MA20 184.775、MA60 149.2817、RSI 24.8603、MACD histogram -8.5439、ADX 30.0938、20 日低點 128.5。

## Deliverables

- Pure current-state builder 與 backend `data.current_state` 向後相容契約。
- 收盤後 finalized daily / intraday overlay 切換修正。
- 日線右側摘要、均線位置計數、修復階梯、風險線、證據折疊與 context 折疊。
- 核心／背景標籤分組、週期與資料日 metadata、證據導覽互動。
- Backend targeted tests、frontend typecheck/lint/build 與 focused browser smoke。

## Done criteria

- 2478-like fixture 回傳「空方趨勢延續」「超賣但尚未止跌」「3/3 均線下方」。
- 修復階梯同時顯示 MA5、MA60、MA20 的價位與站回所需幅度。
- 20 日低點顯示為風險線，詳細證據與籌碼/外部背景預設收起。
- 技術標籤直接取用 `current_state`，不再以 badge 字串猜測 MA20、MACD 或量價狀態。
- 重複的分類標籤移除；相對大盤使用百分點，融資變化不自動視為正面，隔夜採 backend stance。
- 點擊標籤可展開並聚焦對應證據。
- 同日 finalized daily indicator 在收盤後不再標記為 provisional。
- 舊 technical report fields 與 non-daily UI 保持相容。

## Open questions / assumptions

- 本次沿用現行 MA5/20/60；使用者先前提到 MA40 視為口語誤稱，除非後續明確要求才另案評估。
- RSI 30 以下定義為超賣觀察區；它只作 qualifier，不直接視為反轉。
