# 台股技術分析證據與對外契約長專案

## 背景

本長專案依據使用者提供的工程計畫與 2026-08-12 repo／DB／contract 審查結果建立：

- `C:\Users\thoma\Downloads\OMI_Technical_Analysis_Repair_Plan_2026-08-12.txt`
- Repo：`C:\project\Open Market Intelligence`
- 核心範圍：台股 technical indicator、technical structure、AI evidence、`omi.decision.v4`、MCP 與必要的 Frontend consumer

目前底層已具備 MA、Volume MA、EMA/MACD、RSI、ATR、DMI/ADX、ROC、MFI、Donchian、Bollinger、KD 與 Support/Resistance。主要問題不是缺少大量 oscillator，而是：

1. 既有 indicator 沒有成為可單獨選取、具完整狀態與方法語意的 canonical outward capability。
2. 技術價位 outward rounding 會讓合法價格失真，例如 `482.5 -> 482.0`。
3. 週／月 K 可能包含尚未完成的 current period，但目前沒有 provisional/completed 語意。
4. RSI、EMA/MACD、KD 的算法、seed 與 warm-up 未版本化，可能和券商／常見實作產生不可解釋差異。
5. 台股技術序列目前缺少完整 corporate-action adjustment contract；不能把機械性跳空當成正常 breakout、swing 或 divergence。
6. Swing/Pivot、Divergence、Breakout Quality、PVO、backend AVWAP、Volume Profile 與 Relative Strength 尚未形成 backend-owned canonical evidence。

## Goal

- 建立台股優先、backend-owned、可追溯、可版本化且可被 `omi.decision.v4`、MCP、Frontend 與 Kuro 安全消費的技術分析證據鏈。
- 修正價格 precision、timeframe completeness、indicator method/warm-up 與 corporate-action 語意，再公開 `technical.indicators`。
- 建立無 look-ahead 的 Swing/Pivot，並以它為基礎實作 Fibonacci、Divergence 與 Breakout Quality。
- 補上 PVO、Anchored VWAP、Volume Profile 與 Relative Strength，但不把近似值包裝成逐筆成交或官方真值。
- 以 additive `technical.structure` v2 融合新 evidence，保留 v1 與既有 consumer 相容性。
- 使用者核准本計畫後，以一次連續執行完成 source、tests、consumer sync 與約定的 runtime 驗證；milestone 之間不要求重複下指令，但任何 stop-and-fix 條件發生時必須先停下修正。

## Non-goals

- 不把 OMI 改成猜漲跌、自動交易或自動下單系統。
- 不用新增 CCI、Williams %R、Supertrend、Parabolic SAR、Ichimoku、Keltner 或大量 candlestick pattern 取代真正缺少的結構證據。
- 不讓 Frontend、MCP 或 Kuro 重算 RSI、KD、Fib、breakout、freshness 或 corporate-action 判斷。
- 不把 Frontend 手動畫線結果冒充 backend canonical evidence；user-drawn 與 backend-auto analysis 必須保留不同 source。
- 不在第一版主動新增 provider、無界全市場 refresh、昂貴 backfill 或付費 quota。
- 不在未證明 corporate-action coverage 前宣稱已有完整 adjusted technical series。
- 不把新高階訊號直接改入 active Radar 排名或既有 technical v1 score；Radar 僅能先接 shadow evidence，active cutover 另受 point-in-time／outcome／walk-forward gate 約束。
- 不在未明確授權時 commit、push、建立 PR、重建 DB、停止正式 runtime 或重啟服務。

## Hard constraints

- 台股是核心市場；第一版新 capability 的 applicable scope 只開台股 `stock`，不得因現有 `technical.structure` 支援多市場就宣稱其他市場已連通。
- Backend 是 indicator method、price basis、freshness、period completeness、advanced structure、decision fusion 與 outward readiness 的唯一真相來源。
- Canonical outward data 放在 `evidence.data[capability_id]`；consumer-facing readiness 由 `evidence.capability_status[capability_id]` 提供。
- `analysis.human_answer`、既有 `technical.structure` v1、public route、request envelope、target types、query aliases 與 slot status 語意必須保持相容。
- Raw calculation、display formatting 與 tick normalization 必須分離。不得在 decision calculation 前做 display rounding。
- 週／月 current period 必須標示 `provisional`，或 decision 預設只使用最後 completed period。
- 每個 indicator 必須有 `method`、`algorithm_version`、parameters、warm-up 與 input completeness；缺值保留 `null`，不得補 `0`，不得外洩 `NaN`／`inf`。
- Swing/Pivot 必須區分 `pivot_time`、`confirmed_at` 與 provisional/confirmed，禁止 look-ahead。
- 同一根 K 棒上穿壓力但 finalized close 收回壓力下方，預設為 `rejected_attempt`；只有先前已 confirmed 後失守才可稱 `failed`。
- Volume Profile、AVWAP 與 Relative Strength 必須公開 method、source granularity、coverage、confidence、price basis、source refs 與 limitations。
- GET/read path 不因請求 technical evidence 隱性啟動昂貴 refresh 或 DB migration。
- 第一版優先 read-time derived；若後續證明需要 persisted cache，必須另建 migration 與明確 transaction owner。
- 保留目前 dirty worktree 中所有既有修改。實作開始前必須確立可追溯 integration base；不得從含未知重疊變更的工作樹直接大範圍施工。

## Capability contract

### 初始 capability

- `technical.indicators`
  - Scope：台股 `stock`
  - Dependency：`daily.ohlcv`
  - Payload：daily／weekly／monthly snapshots、methods、parameters、warm-up、period status、price basis、freshness、source refs、missing/warnings
  - 不包含 `latest_signals` 作為 raw indicator 真值；高階判讀留在 `technical.structure` 或獨立 capability

- `technical.swings`
  - Dependency：`daily.ohlcv`
  - Output：confirmed/provisional pivots、evidence ids、prominence、confirmation time、price basis

- `technical.fibonacci`
  - Dependency：`technical.swings`
  - Output：可追溯 anchors、retracement/extension、nearest levels、confluence zones

- `technical.divergence`
  - Dependency：`technical.swings`、`technical.indicators`
  - Output：confirmed pivot divergence、alignment method、strength、source evidence ids

- `technical.breakout_quality`
  - Dependency：`daily.ohlcv`、`technical.swings`、`technical.indicators`
  - Output：candidate、provisional、confirmed、weak、rejected_attempt、retest_pending、retest_held、retest_failed、failed

- `technical.volume_profile`
  - Dependency：優先 `intraday.bars`
  - Daily fallback：只有 `daily_ohlcv_approximation`／low confidence，不得標示 exact

- `technical.anchored_vwap`
  - Dependency：`intraday.bars` 與可追溯 anchor；若只用日 K，必須明示 approximation method

- `technical.relative_strength`
  - Dependency：stock `daily.ohlcv`、TAIEX／sector benchmark、對齊交易日 coverage

### Canonical status

每個 capability 至少需要：

- applicability、availability、freshness、coverage、usability 與 decision usability
- `as_of`、trade/event/compute/serve time
- source grade、selected provider/source、fallback、reason/warning codes
- `missing`、`partial`、`stale`、`not_applicable` 與 provider/source failure 不得被 payload 存在掩蓋

## Indicator method strategy

建議採雙版本、無聲破壞為零的策略：

1. 保留現有 technical v1 算法與 score 行為，明確標成 legacy method/version。
2. 建立 reference-vector tests，確認現有 RSI、EMA/MACD、KD、ATR/ADX 等實際公式。
3. 若核准 canonical v2 方法，新增 shadow calculation：
   - RSI：Wilder smoothing。
   - EMA/MACD：明示 seed 與 warm-up policy。
   - KD：明示使用 Taiwan recursive KD 或 SMA stochastic；不得只寫 `KD(9,3,3)`。
4. `technical.structure` v1 保留 legacy；v2 才引用核准的 canonical method。
5. 未完成差異對帳前，不切換 Radar active scoring。

## Price and corporate-action strategy

- P0 outward 一律公開實際使用的 `series_basis`，目前若為 raw/unadjusted 則明示：
  - `series_basis=raw_unadjusted`
  - `adjustment_applied=false`
  - corporate-action coverage/status
  - 已知事件窗口 warning／confidence downgrade
- 完整 adjusted series 只有在 action type、factor、effective date、coverage 與 lineage 可證明時才可啟用。
- 若未來同時保留 adjusted analysis 與 raw executable levels，必須分開：
  - `analysis_price_basis`
  - `level_price_basis`
  - adjustment factor／mapping as-of
- 不得把 adjusted historical anchor 直接當成未映射的現行可執行價位。

## Deliverables

- Indicator method/version 與 warm-up contract、reference fixtures 和 regression tests。
- Price precision、weekly/monthly completeness 與 corporate-action guard。
- `technical.indicators` canonical evidence、capability registry、resolver、quality/readiness 與 MCP schema/snapshot。
- Swing/Pivot、Fibonacci、Divergence、Breakout Quality、PVO、Volume Profile、Anchored VWAP、Relative Strength backend modules 與 pure tests。
- Additive `tw_technical_current_state_v2`／`technical.structure` v2 projection，保留 v1。
- Frontend backend-auto evidence presentation，與 user-drawn evidence 分色／分來源；只有實際 UI 範圍需要時修改。
- HTTP `omi.decision.v4`、stream/non-stream、MCP `omi.ask`、offline snapshot 與 consumer fallback regression。
- Targeted、backend safe validation、frontend type/lint/build、focused browser/API/MCP/runtime adoption 證據。
- 持續更新本目錄 `Progress.md`，記錄每個 milestone、決策、測試、known issues 與 runtime adoption 狀態。

## Done criteria

- `2408` 2026-08-12 close `482.5` outward 保持 `482.5`，不再變成 `482.0`。
- `technical.indicators` 可單獨選取，並透過 `evidence.data` 與 `evidence.capability_status` 回傳。
- Daily／weekly／monthly 都具有 method、parameters、as-of、period completeness、price basis、warm-up、freshness 與 source refs。
- Current incomplete week/month 不得被標成 completed 或在沒有警告下進入高信心 decision。
- Legacy technical v1 consumer 不 break；v2 method／structure 使用 additive、versioned contract。
- 已知 corporate-action 事件不得被誤判為普通 breakout、gap、swing、Fib anchor 或 divergence；coverage 不足仍公開限制。
- Swing/Pivot deterministic 且無 look-ahead；anchor 可以 evidence id 回溯。
- Breakout 可區分 same-bar rejection、confirmed、retest 與 post-confirmation failure。
- Volume Profile／AVWAP 不把 daily/5m approximation 宣稱為逐筆真值。
- Relative Strength 公開 benchmark、aligned observations 與 coverage。
- 新 evidence 不造成 oscillator 重複計分；active Radar 排名在未達驗證 gate 前保持不變。
- MCP snapshot digest 與 backend public contract 一致；backend online/offline schema 相容。
- Targeted regressions、safe backend validation、必要 frontend checks、代表性 API/MCP smoke 全部通過。
- 若核准正式 runtime adoption，還要證明 launcher source、PID/process path、listener、health、contract digest 與代表性 outward behavior 都已採用新版本；health 200 本身不算完成。

## Approval decisions

使用者核准後才開始實作。預設建議如下：

1. **Indicator method**：保留 v1；新增 canonical v2 shadow，`technical.structure` v2 採 v2，Radar active 暫不切換。
2. **週／月語意**：decision 預設使用最後 completed period；current partial 另欄公開。
3. **Corporate action**：本專案完成 raw/unadjusted guard 與 coverage contract；只有資料 coverage 經驗證才啟用完整 adjusted series。
4. **Breakout taxonomy**：加入 `rejected_attempt`，不把 same-bar pierce 一律叫 failed breakout。
5. **Consumer scope**：完成 backend v4、MCP 與必要 Frontend；Kuro 只驗證可消費 contract，不在外部 repo 重做邏輯。
6. **Runtime**：預設先完成 isolated source/runtime smoke；正式 launcher restart 需在核准時明示是否包含。
7. **Git**：預設不 commit、不 push、不建立 PR。

## Open questions / assumptions

- 實作開始前，需確認目前 `codex/tw-etf-provider-normalization` dirty worktree 的 integration base；`capability_contract.py` 與 `capability_resolution_registry.py` 已被其他工作修改，不能直接覆寫。
- Taiwan recursive KD 與 SMA stochastic KD 的 canonical 選擇需由使用者核准；未核准前保留 method-explicit legacy v1。
- Corporate-action provider/DB coverage 若無法支援完整 adjustment，本專案以 truthful raw semantics 完成，不以推測 factor 補值。
- Volume Profile 若沒有逐筆／方向成交資料，只提供 bar-derived approximation，不輸出真實 aggressor buy/sell volume。
- Frontend auto overlay 只在 backend capability 與 outward contract 穩定後施工；不先從 Frontend drawing code 反向建立 backend truth。

## 2026-08-13 remediation wave authorization

使用者已核准依 `OMI_Technical_Indicator_Repair_Plan_2026-08-13.txt` 繼續完成
canonical v2 收斂。這一波在原本 additive shadow contract 上增加下列目標：

- 修正 KDJ、KD smooth period、dynamic RSI key、threshold 與 parameter-contract。
- 建立 current-session provisional daily OHLCV 與 price/range/volume partial semantics。
- 修正合法長假 continuity、breakout frozen-level lifecycle 與 per-capability corporate-action coverage。
- 讓自然語言 raw indicator／Fib／divergence／breakout 問題選到對應 capability。
- 在 shadow comparison 與 regression gate 通過後，分階段讓 technical report、signal 與 Radar 使用 canonical indicator source；保留集中式 rollback policy。

原本「active Radar 不在本專案切換」的限制由本次明確授權取代，但仍保留
point-in-time、outward compatibility、freshness、performance 與 rollback gate；
任何 gate 失敗都維持 legacy active，不以完成進度為由強制切換。
