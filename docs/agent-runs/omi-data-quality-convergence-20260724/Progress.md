# Progress

## 狀態

- 目前階段：已完成
- 最後更新：2026-07-24 Asia/Taipei
- Canonical outward contract：`omi.decision.v4`

## 已完成

- 建立 `omi.data.quality.v1` canonical data-quality contract，讓 manifest、
  slots、passport 與 readiness 共用同一份 availability、freshness、
  completeness、release phase、unit、continuity 與 usability 判定。
- 建立 fusion gate：
  - quote、daily OHLCV、technical 價格基準跨日時阻止 decision-ready。
  - 前一交易日法人／融資券只作 context，不直接提升當日決策。
  - cross-market components 日期混用時降級。
  - 市場廣度與成交值日期不一致時阻止合成。
  - volume/trade-value 缺單位時不得 decision-usable。
- `capability_status`、`data_freshness`、`source_health` 已隔離為
  evidence-only diagnostic scope，不再繼承一般 market/chips capabilities，
  也不產生價位、方向或投資操作。
- 全域 source-health 已整合 snapshots、provider events、fallback detail、
  last success/error、consecutive errors 與狀態轉換事件。
- `provider_failures` 現在包含 stale/empty/degraded source health 與
  budget-skipped refresh；`cached_data_returned` 反映實際本地 table/cache 證據。
- 台股市場：
  - 正式 TWSE/TPEX 同日成交值可補入 market volume current value。
  - volume/trade value 明確宣告 TWD 與欄位可用狀態。
  - 廣度公開 universe rule、unknown 與 missing quote policy。
  - 頂層 evidence `as_of` 與本地樣本 `latest_trade_date` 分離。
  - 純廣度／量能 request 可省略未選取排行、跨市場與籌碼大包。
- 台股指數／個股：
  - 5 秒 TAIEX 不再錯標 1 分；point limit、truncation、single-snapshot partial
    與 depth unavailable 語意明確。
  - 1 分／5 分收盤棒 volume reconciliation、provider/source lineage、
    量能樣本與排除日期保留。
  - `2,350` 不再被錯誤格式化成 `2,35`。
- Refresh：
  - 支援按 dataset/step 執行，不再固定整包刷新。
  - `refreshed_count` 只計算真的插入／更新資料的 dataset，另回傳
    completed、unchanged 與 changed row counts。
  - 月營收 backfill 以預期已發布月份為目標，不再停在本地最新月份。
- ADR 與分點：
  - 不變更 deferred 的 ADR 公式；明確區分 aligned reference price 與 latest
    Taiwan comparison price 的角色。
  - 分點明確回傳 aggregation window、included trade dates 與 ingestion time
    非市場 freshness 的語意。
- 日本／韓國：
  - stale daily/intraday 會建立 bounded refresh action。
  - JP index volume 來源不提供時回 `not_provided`，不再冒充 0。
  - JP previous close trade date、delivery status 與 index source health 可查。
  - KR index source health、daily row/chart row 語意、previous close date 與
    intraday continuity gaps 可查；缺口會降級。
- Output/consumer：
  - 繁中輸出不再混入既定英文操作句，缺值不再顯示 `None`。
  - evidence-only request 不輸出 stance、價格層級與 action plan。
  - v4 compact byte budget 先壓縮 metadata，再依 optional/required 順序省略
    evidence；模型明確要求的 required evidence 不會先被 quality metadata 擠掉。
  - realtime 判定使用 backend 內部完整 observation，不受 consumer 選取的
    output fields 影響；對外仍只投影指定欄位。
  - Frontend 與 repo MCP 已改為同一份 backend v4 schema/response；Kuro 不建立
    專用資料 contract。

## 驗證證據

- `20260724-185805`：144 個 focused backend tests、compileall、diff check 通過。
- `20260724-190857`：data-quality、breadth、ADR、broker semantics 與 number
  formatting focused tests 通過。
- `20260724-191002`：完整 backend 初跑 `972 passed / 1 failed`，定位
  `as_of` 被誤投影為 `latest_trade_date`；已修正為兩個獨立欄位。
- `20260724-191301`：上述回歸與完整 AI tool boundary tests 通過。
- `20260724-191312`：Frontend lint、TypeScript 與 diff check 通過；production
  `npm run build` 在 sandbox 外通過。
- `20260724-193041`、`20260724-193051`：required evidence budget priority 與
  field-independent realtime focused regression 通過。
- `20260724-193156`：完整 backend `975 passed`、compileall、diff check 通過。
- Playwright targeted smoke：
  `OMI context payload follows Taiwan and Korea index selection`，`1 passed`。
- Launcher-selected runtime：
  - `127.0.0.1:8400`，listener PID `13344`。
  - health 指向本 checkout 與 `.venv`；readyz 為 runtime/database `ok`。
  - `/api/ai/tools` 當時預設 `omi.decision.v4`、registry v1、21 capabilities，
    包含 `market.volume_state`；後續 v4-only 收斂補齊既有 target context 後為
    38 capabilities。
  - HTTP diagnostic 強制 evidence-only；2330 selected quote 在 32 KiB
    內保留；999999 回 `TARGET_NOT_FOUND`。
  - SSE final 為同一 v4 contract。
  - MCP stdio 已完成 `initialize`、`tools/list`、成功 `omi.ask` 與
    `TARGET_NOT_FOUND` business result；transport 未崩潰。

## 決策紀錄

- 此次驗證當下 v4 仍為新增式 contract；後續已由
  `omi-v4-only-convergence-20260724` 收斂為唯一 public contract，v2/v3 只留
  backend 私有 seam。
- `evidence.quality` 是 outward consumer 唯一資料品質結論；consumer 不得自行
  重算 readiness。
- Provider 沒有提供的資料回傳 capability gap、missing、stale 或 partial，
  不用合成值冒充正式即時資料。
- `answer_ready` 只代表回應可傳輸；`decision_ready` 才代表可形成決策。
- Kuro、Frontend、MCP、OMI 自身模型共用同一份 OMI backend contract。

## 已知限制

- 使用者明確延後：P0-17、P0-25～P0-27、P0-50、P0-69、P1-74。
- TPEX 目前只有交易所收盤快照時，盤中序列能力會明確為 partial/capability
  gap，不宣稱已有完整 intraday。
- JP index intraday/daily price 目前仍只有 Yahoo price provider；已公開
  source-health 與 provider limitation，但本輪不虛構第二來源。
- 歷史同分鐘量能、月營收與其他資料仍取決於 collector 累積與 provider
  release；資料不足時保持 partial。

## 下一步

- 進入使用者明確延後項目的獨立研究；本任務不自動擴張其範圍。
