# 進度

最後更新：2026-07-28 Asia/Taipei

## 目前狀態

- Milestone 0～3：完成。
- Milestone 4：部分完成；contract correctness 與不需新資料的 P1 已收斂。
- Milestone 5：部分完成；aliases、KR event registry 與 runner reliability 已完成。
- 尚未 commit、尚未 push。

## 基線證據

- 分支：`codex-kr-market-readiness`，追蹤 `origin/codex-kr-market-readiness`。
- HEAD：`eb0423d`。
- 84 個 tracked 修改、15 個 untracked 項目。
- tracked diff：約 84 files changed、9,093 insertions、432 deletions。
- 本輪在既有大型 dirty worktree 上增量施工，沒有 reset、回退或覆寫無關變更。
- 最終正式 launcher：PID `51380`。
- 最終 runtime：backend `127.0.0.1:8400`、frontend `127.0.0.1:3000`，API/UI 均為 `ok`。

## 已完成修正

### P0

- 台股尾盤／盤前試撮：
  - `quote_time`／`snapshot_time` 表示 provider response snapshot。
  - `provider_event_time`／`last_trade_time` 保留成交事件時間。
  - depth-only 改用 `auction_book_*`；provider 未提供 match price/volume 時，
    `auction_indicative_available=false` 且 match 欄位為 `null`。
  - FastAPI response schema 已公開新欄位；legacy replay 在 read path 投影到新版契約，
    不改寫原始 DB snapshot。
- `require_live` 未滿足時，quality/readiness 以
  `live_requirement_not_satisfied` 阻擋，不把昨日收盤冒充 live。
- Crypto OHLCV 對外升冪，latest/event time 取最大時間點，補齊 base/quote volume units。
- TXF 分 K 投影 `volume_contracts`、contracts unit、session 語意；GET intraday
  預設 `refresh=false`。
- US／JP／KR explicit market target 保留 `market` scope；`target.id=US` 與
  `target.market=US` 兩種 public shape 都支援，代表指數僅作 supplemental reference。
- KR 2026-07-28 推定交易暫停由 bounded market event registry 解釋，
  continuity 不再把重疊區段當成 provider missing interval。
- completed-session freshness 改為交易日精確比對；current request observation
  優先於舊 background health。

### P1／P2 本輪已收斂

- US／JP／KR daily OHLC 與 US／JP／KR／Crypto／TXF intraday 增加頂層 volume
  unit、semantics、status，並加入 capability default fields，避免 projection 裁欄位。
- breadth coverage ratio 固定在 0～1；保留 `coverage_ratio_raw`、
  `coverage_overflow` 與 warning，來源矛盾時降為 partial/inconsistent。
- Resource aliases：`GC=F／黃金→GC`、`CL=F／WTI 原油→CL`，並支援其他 registry
  provider symbol／display name。
- 台指期 aliases：`TX／大台→TXF`、`小台→MXF`、`微台→TMF`。
- `run-service-logged.ps1` 修正 Windows PowerShell 對
  `ProcessStartInfo.EnvironmentVariables` 的 lazy initialization，正式 launcher
  已實際重啟驗證。

## 驗證證據

- Focused regression：
  - P0 首批：8 passed、4 subtests；後續 scope/KR、realtime、decision、
    intraday/crypto 與 aliases/volume 組合皆通過。
  - 最終 targeted 組合：73 passed、22 subtests。
- Safe backend profile：
  - `.\scripts\run-safe-validation.ps1 -Profile backend`
  - log：`.tmp/validation/20260728-193334`
  - compileall passed。
  - backend pytest：`1137 passed in 77.65s`。
  - `git diff --check` passed。
  - TXF volume contract follow-up：`.tmp/validation/20260728-213904`，
    `122 passed in 5.12s`，compileall 與 `git diff --check` passed。
- PowerShell runner：
  - parser passed。
  - `ProcessStartInfo.EnvironmentVariables` materialization/write probe passed。
- 正式 runtime smoke：
  - backend health `ok`、frontend `/omi-ui-health` `ok`。
  - OpenAPI：`GET /api/market/tw-futures/{symbol}/intraday` 的
    `refresh` default 為 `false`。
  - `GC=F` 回傳 canonical `GC`；`TX` 回傳 canonical `TXF`。
  - Crypto `BTC-USDT` 最近 3 根 1m bars 為時間升冪。
  - `target={type: market, id: US}` 回傳 target `market/US`。
  - quote depth HTTP 已公開 snapshot/provider event/auction book 欄位。
  - TXF 夜盤 public v4 `intraday.bars` 實際回傳最後五根
    `volume_contracts=391/283/205/329/246`，並帶
    `volume_unit=contracts`、`volume_semantics=interval_contracts`、
    `source=TAIFEX MIS 1-minute chart`、`provider=taifex_mis`。
  - replay 08:50 與 13:28：
    snapshot time 與 provider event time 均為 `+08:00`，
    `auction_book_available=true`、`auction_indicative_available=false`。

## 已知資料限制

- TXF quote refresh 會先建立等待 1-minute chart 回填的 provisional bar，
  該分鐘的 interval volume 可暫為 `null`；官方 chart refresh 後會補成每分鐘口數。
  畫面另有 session cumulative `total_volume`，兩者均存在但語意不可混用。
- US market scope 已正確保留，但完整美股 breadth／volume state 尚無 full-market
  provider payload；目前會清楚列為 missing，不以 `^GSPC` 冒充。
- TPEX breadth／TWSE+TPEX 同分鐘成交值仍依賴官方來源與 persistence 完整度。
- JP／KR 官方日線、法人／財務 refresh job 與 Crypto 常駐 persistence bridge
  尚未在本輪啟用；避免在 read path 或無 budget 情況下做隱性外部抓取。

## 下一步

1. 下一里程碑先做 TPEX breadth 與 TWSE+TPEX minute trade-value persistence，
   用實盤交易日驗證 13:25～13:30 行為。
2. 再做 US／JP／KR full-market breadth provider contract；沒有 coverage 的市場
   維持 partial/missing。
3. 把 JP／KR official refresh 與 Crypto persistence 拆成各自 bounded rollout，
   每項附 heartbeat、source health、quota 與 restart smoke。
