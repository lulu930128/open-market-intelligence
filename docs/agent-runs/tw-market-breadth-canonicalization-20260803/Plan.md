# 台股正式市場廣度與試撮語義根治計畫

## 執行原則

- 依序執行「證據 → pure semantics → parser/cache → persistence → breadth →
  outward contract → consumer → rollout」。
- 每個里程碑通過 focused regression 後才進下一階段。
- 所有欄位與狀態採 additive 演進；consumer 不自行推論。
- 每完成一個里程碑即更新 `Progress.md`。

## 執行結果

- M0–M10 工程、migration 與正式本機 rollout 已於 2026-08-03 完成。
- 真實盤前／開盤 acceptance 安排於 2026-08-04，由使用者依 `Progress.md` checklist 實測。
- 盤後官方資料與 deterministic fixture 不作為真實盤前／第一筆成交的替代證據。

## 里程碑

### M0：任務基線與可重放案例

- 範圍：固定 08:59 `z=-/pz=110`、09:01 cache、第一筆正式成交、跨日、
  reset 與 `o/h/l` 無成交案例。
- 驗收：測試能明確重現錯誤，fixture 分離 raw snapshot time 與 price event time。
- 驗證：focused parser tests。
- 停止條件：fixture 無法辨識正式成交與試撮時，不進 M1。

### M1：價格、session 與時間語義

- 範圍：建立 actual trade、auction indicative、reference、unavailable 與
  `snapshot_as_of`／`price_as_of` pure contract。
- 驗收：狀態機不做 IO/DB，不覆寫 raw observation。
- 驗證：pure unit tests。
- 停止條件：產生第二套 readiness 權威時，先收斂到既有 capability status。

### M2：MIS parser、正式 cache 與 reset

- 範圍：移除 `z or pz`、`o/h/l` 正式方向 fallback；正式 cache session-aware；
  limit 與 trade value 只使用 actual trade；reset 清完整 state。
- 驗收：盤前正式分類 unknown，第一筆正式成交後才分類，cache 保留 price time。
- 驗證：market-index 與 intraday capability targeted tests。
- 停止條件：任何 `pz` 可進正式分類時停止。

### M3：canonical intraday state v2 與 migration

- 範圍：新增 price semantics/source/time/session/actual-trade/version 欄位；舊列
  legacy quarantine；persistence 只寫 canonical row。
- 驗收：migration additive、可重跑、copy dry-run/integrity 通過。
- 驗證：migration、model、persistence tests。
- 停止條件：需要刪表、重建正式 DB 或猜測性回填時停止。

### M4：正式廣度與試撮狀態分離

- 範圍：preopen official breadth pending；regular breadth 只聚合 actual trade；
  試撮僅 additive provisional contract；post-close official reconciliation 保留。
- 驗收：coverage invariant 成立，TWSE/TPEX component 狀態不被 combined 掩蓋。
- 驗證：breadth status、API projection、session fixture tests。
- 停止條件：unknown 被折入 unchanged 或 partial 被升為 ready 時停止。

### M5：共用 canonical aggregate

- 範圍：breadth、scheduler persistence、screening、hot groups 使用相同 v2 row；
  舊 v1 row 不進 current-session reader。
- 驗收：同一 snapshot 的 per-stock classification 與 aggregate 一致。
- 驗證：market state、screening、hot-groups tests。
- 停止條件：出現兩套不可解釋的 current-session分類時停止。

### M6：REST 與 source-health contract

- 範圍：schema additive 暴露 session、provenance、coverage、price-time 與
  contract version；GET 維持 read-only；source health 使用資料事件時間。
- 驗收：OpenAPI/path/method 相容，stale cache 不會因新 snapshot 偽裝 current。
- 驗證：API inventory、market source-health、schema tests。
- 停止條件：HTTP 200 或 cache hit 被當作 ready 時停止。

### M7：AI decision 與 MCP contract

- 範圍：answer composer 服從 `evidence.capability_status`; partial/pending/mixed
  必須產生 data limits 與 confidence cap；MCP 保持 thin。
- 驗收：`decision_usable=false` 不會輸出無保留高信心市場 stance。
- 驗證：AI composer/outward/freshness、MCP contract tests。
- 停止條件：REST AI 與 MCP evidence 不一致時停止。

### M8：Frontend 呈現

- 範圍：顯示 per-market status/scope/coverage/unknown/session/price time；區分
  正式 pending 與試撮 provisional；不使用 summary `as_of` 冒充 breadth time。
- 驗收：backend contract 是唯一邏輯來源，desktop/mobile 不溢出。
- 驗證：lint、typecheck、必要 component/browser smoke。
- 停止條件：Frontend 必須重算 readiness 才能呈現時，回到 M6/M7。

### M9：Radar 與 legacy state 隔離

- 範圍：拒絕 pending、auction、legacy/untrusted、decision-unusable snapshot；
  歷史列保留但不進新 regime/backtest。
- 驗收：Radar shadow 不消費盤前正式廣度或舊 contract row。
- 驗證：Radar regime/shadow tests。
- 停止條件：需要刪除歷史資料才能保證安全時停止並請示。

### M10：驗證、正式本機 rollout 與隔日實測交接

- 範圍：targeted、migration copy、backend/frontend regression、正式 launcher
  runtime、API/AI/MCP/UI smoke；產出隔日盤前/開盤 checklist。
- 驗收：source、DB revision、PID/path/port/build identity 一致；正式 runtime
  安全降級正確；未驗證的真實開盤數據明確列為隔日實測。
- 驗證：safe validation、bounded HTTP/MCP probes、runtime evidence。
- 停止條件：runtime drift、migration integrity failure 或 public contract divergence。

## 全域 Stop-and-fix 規則

- Focused regression 失敗時先修正，不以 skip、xfail 或放寬 assertion 掩蓋。
- `pz`、previous close 或無成交 `o/h/l` 進入正式 breadth 時立即停止。
- `coverage_count > universe_count`、unknown 被折入 unchanged、component partial
  被 combined ready 掩蓋時立即停止。
- `decision_usable=false` 仍輸出高信心整體 stance 時停止下游 consumer 工作。
- Migration 需要 destructive DB 操作、read path 產生昂貴副作用、consumer
  複製 backend 邏輯或 Radar 需要刪資料才能安全時，暫停並請使用者決策。
- 未經明確要求不 commit、push、publish 或 force 操作不相關 runtime。

## 決策紀錄

- 2026-08-03：沿用 7/30 建立的 `taiwan_intraday_stock_state`，升級為 additive
  v2；不建立第二套全市場 state。
- 2026-08-03：registered-universe membership 維持現有定義，本任務只修價格／
  session／freshness correctness。
- 2026-08-03：rollback 只能降級為 pending/partial/unavailable，不恢復已知錯誤
  的 `pz` 正式分類。
- 2026-08-03：真實盤前／第一筆正式成交證據安排在隔日使用者實測；M10 本輪
  仍須完成 deterministic、migration、regression 與正式 runtime rollout。
