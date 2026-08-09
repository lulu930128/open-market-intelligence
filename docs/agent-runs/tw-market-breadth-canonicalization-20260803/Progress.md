# 台股正式市場廣度與試撮語義根治進度

## 狀態

- 工程狀態：M0–M10 已完成，正式本機 runtime 已 rollout。
- 實盤狀態：盤後與 deterministic session contract 已驗證；2026-08-04 盤前／開盤真實行情待使用者實測。
- 最後更新：2026-08-03 19:20（Asia/Taipei）。
- Repo：`C:\project\Open Market Intelligence`。
- Branch：`main`。
- 建立時 HEAD：`2d0476d`。
- 本任務未 commit、未 push。

## 里程碑狀態

| 里程碑 | 狀態 | 結果 |
| --- | --- | --- |
| M0 | 完成 | 建立可重放 preopen、regular、cache、跨日、reset 與無成交 fixture。 |
| M1 | 完成 | 建立 pure session/price resolver，分離 `snapshot_as_of` 與 `price_as_of`。 |
| M2 | 完成 | 移除 `z or pz` 與 `o/h/l` 正式分類 fallback；cache 與 reset 修正。 |
| M3 | 完成 | canonical intraday state 升級 v2，additive migration `20260803_0050` 已 rollout。 |
| M4 | 完成 | 正式廣度與 `auction_breadth` provisional contract 分離。 |
| M5 | 完成 | persistence、screening、hot groups 共用 v2 actual-trade state。 |
| M6 | 完成 | REST/source-health 暴露 session、provenance、coverage 與 decision usability。 |
| M7 | 完成 | AI/MCP contract 升級並對 pending/partial 限制 stance 與 confidence。 |
| M8 | 完成 | Frontend 顯示 pending、coverage、breadth time 與試撮 provisional 狀態。 |
| M9 | 完成 | Radar 拒絕 legacy、pending、auction 與 decision-unusable state。 |
| M10 | 完成 | Regression、DB backup/copy migration、正式 runtime、REST/AI/MCP/UI smoke 完成。 |

## 核心交付

- `tw.market.breadth.v2` 與 `tw.market_breadth.stock_state.v2` 成為 backend-owned canonical contract。
- `z` 只有在正式 session、價格有效且 cumulative volume 大於零時才是 actual trade。
- `pz/ts` 僅進入 `auction_breadth`，永遠 `decision_usable=false`。
- session cache 只限同交易日與已確認 actual trade，且保留原 `price_as_of`。
- preopen 正式廣度為 `pending_regular_session`，不把 unknown 折成 unchanged。
- 舊 DB 列保留但標記 `legacy_unverified`、不可進 screening/Radar。
- post-close 官方 TWSE/TPEX breadth 正規化為 v2、`official_session_close`、`full_market`。
- AI 合併投影保留 version/session/price semantics，並把試撮廣度維持獨立 provisional 區塊。
- MCP 離線 snapshot 與 backend public digest 已同步為
  `7360b0c5158bdab4546d2277c07a1ad712a167b9c8581d5c01081a938076a103`。

## 驗證證據

### 程式與契約

- deterministic breadth/session contract：7 tests passed。
- focused parser/state/AI/Radar/API/MCP regression：相關批次均通過；最後擴大批次 192 tests、32 subtests passed。
- 完整 backend safe profile：1,443 tests passed、5 個既有 warning；compileall 與 `git diff --check` passed。
- Frontend safe profile：lint、tsc、`git diff --check` passed。
- Frontend production build：sandbox 內因 Windows `spawn EPERM` 受限；在允許的同一環境重跑後完整 passed。
- MCP snapshot generator：55 capabilities、22 targets，snapshot consistency test passed。

### Migration 與資料安全

- 正式 DB 原 revision：`20260731_0049`；原大小約 13.5 GB。
- verified recovery backup：
  `data/backups/open_market_intelligence-before-tw-breadth-v2-20260803-190928.db`
- backup：13,501,435,904 bytes、quick integrity `ok`、SHA-256
  `789e8e08b3fcf5cafb74d5da971f8abfd91b41d7acbdef3e571f35ef390ea6b0`。
- copy migration：`0049 → 0050 → 0049 → 0050` 全通過，兩張表 row counts 始終為 1,959／2,767，quick_check `ok`。
- 正式 migration：revision `20260803_0050`；11 個 stock 欄位與 7 個 minute 欄位齊全；row counts 不變；quick_check `ok`。
- 舊列隔離：1,959 stock rows 與 2,767 minute rows 均為 legacy/non-decision-usable，不做猜測性 actual-trade 回填。

### 正式 runtime

- 舊 launcher PID 12888、backend listener PID 40596、frontend listener PID 43860 已停止。
- 新 launcher PID 43020；backend service runner PID 52408；frontend service runner PID 40220。
- 新 backend listener PID 55648，command 為本 repo venv 的 uvicorn、port 8400。
- 新 frontend listener PID 50532，command 為本 repo Next.js、實際 port 3270；3000 位於 Windows excluded range。
- `/api/system/health`：project root、backend dir、venv Python 與 repo 一致。
- `/api/system/readyz`：runtime/database 均 `ok`。
- Frontend `/omi-ui-health`：HTTP 200。

### 對外介面

- REST `/api/market/indices/summary`：TAIEX/TPEX 均為 `tw.market.breadth.v2`、
  `post_close`、`official_session_close`、`decision_usable=true`、`full_market`。
- Source health：兩市場 breadth trade date 皆為 2026-08-03、status `current`。
- Public `/api/ai/ask`：`omi.decision.v4`、public digest 一致、quality `ready`；合併 breadth
  1,207 上漲／586 下跌／133 持平／1,926 coverage，unknown 0。
- MCP stdio：`initialize → notifications/initialized → tools/list → omi.ask` passed；僅暴露
  `omi.ask` 與 `omi.ask_stream`，tool call `isError=false` 且 evidence 與 REST 一致。

## 決策紀錄

- 沿用既有 registered universe，不在 parser 修復中改變 membership。
- 新欄位 additive；舊 DB row 隔離而不推測 actual trade。
- `evidence.capability_status` 保持 consumer-facing readiness authority。
- online backup 因 live writer 15 分鐘幾乎無進展；精準確認 process ownership 後短暫停止 OMI launcher，再完成 verified offline backup。
- 未以盤後官方 breadth 或 fixture 宣稱真實盤前／開盤已驗證。

## 隔日實盤驗收

1. 08:50–08:59：TAIEX/TPEX 正式 breadth 應為 `pending`／`pending_regular_session`，正式 advance/decline 不得使用 `pz`。
2. 若有試撮：只能出現在 `auction_breadth`，`price_semantics=auction_indicative`、`is_provisional=true`、`decision_usable=false`。
3. 09:00 後：只有 `z` 與 cumulative volume 大於零的股票才進正式分類；coverage 應由低向高增加，unknown 相對下降。
4. 同一股票暫時沒有新 `z` 時：可沿用同交易日 actual-trade cache，但 `price_as_of` 不得被 provider snapshot time 推進。
5. 跨 09:00：正式 breadth 不得沿用前一交易日 cache；`coverage_count + unknown_count = universe_count`。
6. Source health、REST、AI、MCP 應回報相同 status/session/scope/coverage；partial 不得輸出無保留 high-confidence stance。
7. Radar 在 breadth 尚未 ready/decision-usable 前不得消費該 snapshot。

## 未完成但不阻擋 M10 的事項

- 2026-08-04 真實盤前／第一筆正式成交／coverage 收斂仍待使用者實盤觀察；這是 live acceptance，不是本輪可由盤後環境偽造的證據。
- 若實盤發現 provider `ts/pz/z/v` 有未覆蓋組合，保留 raw payload、時間、market、stock id 與 API response 後回到本任務續修。
