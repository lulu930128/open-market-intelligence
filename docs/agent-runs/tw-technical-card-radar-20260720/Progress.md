# 進度紀錄

## 目前狀態

- 狀態：Milestone 1-5 已完成。
- 日期：2026-07-20。

## 已確認

- 日線技術卡 headline 目前只用 `price_vs_ma20`；MA60 只透過 MA20/MA60 排列間接參與評分。
- `daily` technical API 忽略 `include_intraday`；frontend 日線請求也固定關閉盤中資料。
- Radar signals 缺少價格相對 MA60 與 cross MA60。
- Radar 主訊號目前取第一個 strong signal，而不是依技術重要性排序。
- Radar risk key level 先取 resistance，可能選到離現價很遠的歷史高壓。
- Radar 盤中覆蓋依自選股原始順序使用前 `intraday_limit` 檔，且每檔可能觸發 provider I/O。
- Radar UI 已是摘要優先、細節折疊；本次維持此資訊層級。

## 待完成

- 無必要實作待完成；完整全自選股盤中覆蓋仍維持 bounded policy，不在本次擴張。

## 已完成

- 新增共用 `technical_structure`，統一 MA5/20/60 價格位置、MA20/MA60 穿越與 finalized range level 判斷。
- 日線 technical report 支援 current-session intraday overlay，保留盤中價與日線指標各自時間點、provisional 與 warning。
- 日線卡新增價格相對 MA5/20/60、均線排列、Donchian/20 日支撐/布林結構破壞。
- Radar 增加 MA5/MA60 signals、權重、factor 與 price levels；主訊號改採結構優先。
- Radar key level 改為現價最近的回收/失效價位，並標示已失守支撐。
- Radar 先完成全清單日線計算，再依結構訊號與風險排序選擇 bounded intraday candidates。
- Frontend 日線技術卡固定請求盤中 overlay，顯示盤中價時間、日線指標日期與資料限制數。
- Radar 折疊細節加入昨收與 MA60，不改變摘要優先架構。

## 驗證證據

- Backend targeted tests：49 tests，全部通過。
- Frontend `npm exec tsc -- --noEmit --incremental false`：通過。
- Frontend `npm run lint`：通過。
- Frontend `npm run build`：Next.js 16.2.6 production build 通過。
- `git diff --check`：通過，僅既有 Windows LF/CRLF 提示。
- 本機 2327 實際 technical contract：盤中 630；vs MA5/20/60 為 -18.54% / -34.86% / -11.36%；日線指標日期 2026-07-17；盤中時間 2026-07-20 13:30。
- 本機科技股 83 檔完整 Radar：39.46 秒；bounded intraday 30 檔；2327 原始候選順位 73，仍被選入盤中覆蓋並成為 Radar 第 1 名、`stale=false`、key level 699、MA60 710.7667。

## 已知風險

- `ranking_service.py`、frontend types/i18n 與 e2e 目前已有使用者修改；實作必須採局部 patch 並逐段檢查 diff。
- 盤中與日線指標混用容易造成誤讀；任何 overlay 都必須標示 provisional 與各自 as-of。
- Radar 仍只對 30 檔做 provider-backed 盤中覆蓋，其餘 53 檔保留 finalized daily 與 stale 狀態；這是刻意的成本/延遲邊界，不應隱藏。
