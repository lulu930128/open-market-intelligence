# 台股盤中價格與前端工作面一致性修正

## Goal

- 讓台股個股 Header、Today 圖與 Quote Depth 在存在同交易日 canonical actual-trade price 時，於既有輪詢週期內收斂到同一成交價。
- 當 TWSE MIS 缺少 `z`、只有 `pz`、provider failure 或來源時間落後時，保留 unavailable／stale／lag 與來源差異，不用委買賣、試撮價或 OHLC 製造成交價。
- 將 TPEX Today 圖表收斂到台股 Today 共用研究工作面，同時保留 `bar_type`、`finalized`、`is_partial`、`indicator_eligible` 與 volume unavailable 語意。
- 將 TAIEX／TPEX 官方 5 秒序列投影成共用 Today 1 分鐘 public contract；Header、最後畫線點與官方收盤 observation 必須一致。
- 讓 Technical 在中寬桌面仍可被直接發現與操作，不因 `xl` breakpoint 被排到數千像素下方。
- 以 backend replay coverage 為邊界提供「即時／試撮快照」檢視；無 capture 時明確顯示 missing，不使用 frontend 假行情。

## Non-goals

- 不把 MIS `pz`、bid、ask、OHLC 或正累計量單獨解讀成 actual-trade price。
- 不建立 tick history、全市場無界限快照收集或 on-demand 歷史回補。
- 不把 backend 市場語意、freshness 或資料整併搬到 frontend。
- 不改動 AI decision contract、MCP adapter、DB schema、正式 launcher 或 production runtime。
- 不重做 2026-08-06 已完成的盤中成交量雙軌契約。
- 不 commit、push 或發布；需另由使用者明確要求。

## Hard constraints

- Backend 是 actual trade、session、freshness、provider provenance 與 replay coverage 的唯一真相來源。
- 只有 stock identity、trade date、session 與 canonical actual-trade evidence 一致的 MIS `z` 可以成為 current actual-trade price。
- Intraday 歷史 points 可保留 nStock／Yahoo；current observation 必須以 additive metadata 表達，不得改寫無法證明的歷史成交。
- 所有 public contract 變更須 additive，既有 consumer 與成交量雙軌欄位保持相容。
- Raw provider parser 與 daily OHLC 計算保持不變；5 秒到 1 分鐘的轉換只發生在 index intraday public projection。
- TPEX post-close summary 與不具 indicator eligibility 的點不可因 UI 統一而混入盤中指標或偽裝成成交量。
- Frontend Today 的 Volume、VWAP、漲跌停與 Quote Depth 能力只能依 backend capabilities，不能依 `TPEX`／`TAIEX` 代號建立模板分支。
- Replay toggle 只能讀取已保存、bounded capture 的快照；coverage `0` 或 slot missing 必須可見。
- Dirty worktree 中既有變更屬於使用者或其他任務；不得 revert、重排或格式化無關內容。
- Deterministic tests、post-close probes 與 HTTP 200 不得標記成真實盤中 acceptance。

## Context

- Repo: `C:\project\Open Market Intelligence`
- Engineering report: `C:\Users\thoma\Downloads\OMI_TW_Frontend_Intraday_Issue_Engineering_20260807.txt`
- Related systems: Taiwan intraday service、TWSE MIS observation、quote-depth replay、REST schema、Next.js stock detail、TPEX intraday、frontend E2E。
- 2026-08-07 source/runtime inspection confirmed：
  - Today Header／chart consume intraday；Quote Depth consumes a separate endpoint；兩者都持續 polling，HTTP 200 不是 freshness 證明。
  - Intraday 的 MIS adjustment 只有條件式更新，public schema 未暴露 current-price provenance 與 lag。
  - 保存的 `2344` 12:07 checkpoint 兩條路徑同為 `164.5`；下午另有 MIS provider failures，因此早上特定延遲無法事後完整重建。
  - `1256px` 下 Technical 實際被堆疊到約 `3126px`；直接把 `xl` 改成 `lg` 會讓圖表過窄。
  - TPEX Today 目前走獨立 `StockKLineChart` 分支；backend point contract 比一般股票多 session/bar semantics。
  - Quote preview 是標示清楚的 frontend 假資料；`2330` replay 有大部分 coverage，`2344` coverage 為 `0`。
- Existing related task: `docs/agent-runs/tw-intraday-volume-contract-20260806/` 已完成 source implementation，formal runtime adoption 與 next-session acceptance 仍 pending。
- 2026-08-08 follow-up inspection confirmed：TPEX 已改用共用 `IntradayTrendChart`，但仍有 `isTpexToday` 能力分支；TAIEX／TPEX API 仍直接公開約 3,242 個 5 秒點，1m 控制實際未聚合；TPEX Header 使用 13:33 summary，畫線最後點則是 13:30 raw value，兩者不一致。

## Deliverables

- 本任務 `Prompt.md`、`Plan.md`、`Progress.md` 與可續跑決策紀錄。
- Additive intraday current-price provenance／availability／lag contract 與 focused backend tests。
- Frontend types 與 Header／Today 可見的來源／lag／unavailable 呈現，不在 browser 端重算 actual trade。
- TPEX Today 共用呈現與相應 E2E contract 更新。
- Index Today canonical minute projection、source/effective interval metadata、capabilities、current observation 與 post-close observation audit。
- 中寬桌面 Technical 可發現的 responsive interaction。
- 以 replay coverage 驅動的真實試撮快照檢視與 missing state。
- 分層 backend/frontend validation 與下一交易時段 live acceptance checklist。

## Done criteria

- 有 canonical actual-trade price 時，intraday response 暴露來源、事件時間、history time 與 lag，且 latest Today point／Header 可依 backend contract 收斂。
- MIS 缺 `z`、preopen `pz`、日期不一致、time skew、provider failure 與 cache fallback 都有 deterministic coverage，且不製造成交價。
- TPEX Today 使用共用 Today surface，13:30 official close 保留、13:33 post-close summary 不污染 regular-session plot／indicator；volume unavailable 有明確狀態。
- 2330／TAIEX／TPEX 都使用同一 Today test surface；官方 5 秒 index series 對外為最多 271 個 1 分鐘點，closing-auction 點不進指標，無 volume capability 時不建立空量柱。
- 在 1024、1256、1280、1440 與 1920 viewport，Technical 可發現且圖表不因強制雙欄過窄。
- Replay 有 coverage 時可查看已保存的試撮 slot；沒有 coverage 時顯示 unavailable，且正常模式不使用 preview transform。
- Targeted backend tests、frontend lint/typecheck/build、必要 E2E/browser checks 與 `git diff --check` 通過。
- 真實開盤與穩定盤中 ≤10 秒收斂若尚未觀察，Progress 明確保留 `not_observed`，不得把任務標成完整 live acceptance。

## Open questions / assumptions

- 本次預設以 additive metadata + canonical observation helper 修正，不將 Quote Depth payload 直接合併進 intraday endpoint。
- 中寬版面預設採可展開／可快速跳到 Technical 的 single-column 互動，只有內容寬度足夠時維持雙欄。
- Replay UI 預設使用既有固定 slot endpoint；不因目前選到未 capture 股票而擴大 scheduler universe。
