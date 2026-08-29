# 美股 OHLCV 連續性與永久修復

## Goal

- 讓美股日 K outward contract 明確揭露最新完整交易日、可見區間缺口、歷史深度與 previous-close reference date。
- 當上一完整交易日缺失時 fail closed，不再用更舊 K 線計算盤中漲跌。
- 由 backend 明示、bounded、可追蹤的 repair job 與 scheduler 擁有 SPX 等指數、持倉、啟用 watchlist 與一般全市場 completed-session EOD 修復。
- 保持圖表 GET cache-only，並讓 frontend 只消費 backend continuity／repair contract。

## Non-goals

- 不建立無界全市場歷史回補，也不保證免費 per-symbol provider 能在固定時間內完成 7,000 多檔全市場。
- 不保存電腦關機期間無法重建的 intraday／depth archive。
- 不新增付費 provider、broker execution、自主交易或 AI decision contract。
- 不重建、清空或覆蓋 `data/open_market_intelligence.db`。
- 不在本任務重寫整個 US canonical/resolver 架構或移除 legacy compatibility。

## Hard constraints

- Repo: `C:\project\Open Market Intelligence`
- 美股是 first-class research market；修正必須對齊共同 Market Data Foundation contract。
- GET/read path 不得啟動 provider I/O、job 或 subscription。
- Provider selection、freshness、continuity、previous-close reference 與 repair policy 由 backend 擁有；frontend/MCP/Kuro 不得重算。
- Refresh 必須有 target、range、timeout、call budget、provider lineage、postcondition 與 truthful partial/error semantics。
- 現有 public route 保持相容；新增欄位必須 additive。
- 盤中 provisional bar 不得掩蓋 completed-session 缺口。
- Existing dirty worktree 內容視為使用者工作；只做 localized diff，不 revert 無關變更。
- Provider HTTP 等待期間不得持有 caller 或 tracked-job 的 SQLite pooled connection；repair read／provider IO／write／postcondition read 必須分段擁有 Session。

## Context

- Live runtime 於 2026-08-24 使用 backend `127.0.0.1:8916`、frontend `3000`。
- 2026-08-24 runtime adoption 後，US 首頁併發 OHLC+intraday 與 priority reconcile 觸發 `QueuePool size 5 overflow 10` timeout；process/listener仍活著，但DB-backed `readyz`與jobs API失去回應，frontend proxy顯示斷線。
- `^GSPC` persisted daily bars 只到 2026-08-19，缺 8/20、8/21，卻接上 8/24 intraday overlay，造成漲跌以 8/19 為基準。
- `UMC` persisted resolved daily bars只到 2026-08-20；Yahoo 已提供 8/21 close 18.34，但 intraday contract 使用 8/20 close 18.00，畫面顯示錯誤的 +4.61%。
- 現有 US full-market checkpoint universe 7,427、coverage 約 71.7%；每 30 分鐘 bounded 250 symbols，cursor ordering 讓 watchlist 後段標的長時間等待。
- 目前 OHLC GET 使用 `ensure_history=false`，符合 cache-only owner 邊界，但缺少等價的 explicit repair owner 與 continuity contract。

## Capability contract

| 項目 | Contract |
|---|---|
| Product scope | 美股 completed-session daily OHLCV reliability；支援獨立 US research，不產生交易建議。 |
| Target | Backend-known US indices、active US holdings、enabled US watchlist；一般 active stock universe仍由 full-market EOD checkpoint處理。 |
| Provider | Yahoo chart為bounded repair provider；既有 Alpha Vantage rows可作cache candidate，但不自動消耗稀缺 quota。 |
| Resource | Finalized daily OHLCV、daily/weekly/monthly chart projection、previous completed-session close reference。 |
| Freshness | America/New_York calendar；regular close加既有 settlement buffer後的 latest completed session。 |
| Request bounds | Per-symbol explicit repair最多2次provider call；priority reconcile掃描bounded universe並受25次provider call、runtime、sleep與consecutive error限制。 |
| Persistence | 既有 `us_daily_price` upsert；priority lifecycle以durable JobRun result保存輪替cursor與postcondition摘要，不重建DB。 |
| Failure | Missing、stale、partial、insufficient_history、provider failure與postcondition failure都如實 outward。 |
| Transaction | US market refresh service擁有 daily-price upsert；coverage/job owner擁有 checkpoint與JobRun transaction。 |
| Public API | OHLC GET additive continuity fields；explicit POST enqueue bounded repair；cache-only EOD GET保持不變。 |
| AI contract | 不新增 outward AI slot；既有 consumer可讀較 truthful 的 daily OHLCV evidence。 |
| Consumer | Frontend使用backend previous-close／continuity；operation detail送共用更新狀態。 |
| Validation | Pure calendar/continuity、service postcondition、job dedupe/bounds、scheduler、API schema、frontend lint/typecheck/build、live cache-only smoke。 |

## Deliverables

- Additive US OHLC chart continuity／history／previous-close schema與service projection。
- Fail-closed intraday previous-close reference semantics。
- Explicit per-symbol OHLC repair job與API，含postcondition evidence。
- Durable priority EOD universe與scheduler/startup catch-up，優先處理指數、US holdings與enabled watchlist，並用JobRun cursor避免永久失敗標的造成飢餓。
- Frontend改用backend previous-close與continuity狀態，並將repair operation送到共用更新狀態。
- Targeted backend/frontend regression與live read-only acceptance evidence。

## Done criteria

- UMC缺8/21時，API `previous_close`為null或明確invalid，frontend不顯示以8/20計算的漲跌；修復後reference date為8/21。
- SPX缺8/20、8/21時，API回報缺口且盤中overlay不會讓dataset看似current。
- 指數不需進入stock master也有backend repair owner。
- Watchlist／holding priority targets不再被全市場alphabetical cursor長時間排在後面。
- Provider request成功但postcondition未達成時，job維持partial/error，不計為完整修復。
- Daily 180、weekly 104、monthly 72深度不足可透過explicit bounded repair升級full，並truthful回報仍不足的new listing。
- GET route測試證明不啟動provider I/O；scheduler/job測試證明bounded與dedupe。
- Targeted backend tests、frontend validation與必要live smoke通過。
- Pool size 1 contention regression證明OHLC intraday overlay與priority repair等待provider時，平行DB probe仍能立即取得connection。

## Open questions / assumptions

- v1 priority universe使用backend index registry、active US portfolio holdings與enabled active US watchlist；recently viewed symbol透過explicit repair job提高優先級，不建立第二套frontend freshness policy。
- 無法由calendar alone確認停牌／無成交資格的缺日仍標為partial/eligibility-unknown，不自動填0或合成bar。
- Provider full-range仍無足夠上市歷史時允許`best_available`，但latest completed session與continuity correctness仍必須獨立驗收。
