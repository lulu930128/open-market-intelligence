# 執行計畫

## Execution model

- 本文件核准前只允許 docs／inspection；不得修改產品程式碼。
- 使用者核准後，以一次連續執行完成所有已核准 milestone。
- 每個 milestone 仍有 acceptance 與 validation gate；失敗時先停下修正，不把失敗累積到最後。
- 只有發現需要破壞 public contract、改 DB schema、擴大外部 quota、改 active Radar 排名或重啟未授權 runtime 時，才返回使用者確認。
- 每完成一個 milestone 更新 `Progress.md`，讓工作可中斷、續跑與稽核。

## Milestones

### 0. Approval、integration base 與 baseline gate

- Scope：使用者核准事項、Git/worktree、public contract snapshot、代表性 fixtures。
- Work：
  - 記錄核准的 Indicator method、週月語意、corporate-action、breakout taxonomy、consumer/runtime/Git 範圍。
  - 核對目前 branch、dirty files、重疊 owner 與可追溯 integration base。
  - 若目前 dirty work 尚未落定，使用安全的 isolated worktree/branch 或等待既有工作收斂；不得把未提交修改遺失或漏入新 base。
  - 修復或明確隔離現有 MCP offline snapshot digest mismatch，建立綠色 baseline。
  - 保存 2408 price/outward、indicator snapshot、週／月 current period 與 corporate-action 代表 fixture。
- Acceptance：
  - 使用者核准決策已寫入 `Progress.md`。
  - 技術任務不會覆寫既有 US SEC、ETF、FX 或其他 dirty work。
  - Backend public manifest 與 MCP snapshot digest 一致。
  - 可以在未改功能前重現 `482.5 -> 482.0` 與 incomplete weekly/monthly 語意缺口。
- Validation：
  - `git status --short --branch`
  - 從 `backend` 執行 contract／MCP baseline tests，使用唯一 repo-local `--basetemp` 與 `-p no:cacheprovider`。
  - 唯讀 DB fixture query；不更新、不 rebuild DB。

### 1. Indicator method inventory 與 independent reference vectors

- Scope：`indicator_service.py`、`technical_parameters.py`、新增 pure method tests；先不切換 production score。
- Work：
  - 為 MA、Volume MA、EMA/MACD、RSI、ATR、DMI/ADX、ROC、MFI、Donchian、Bollinger、KD、Support/Resistance 建立 method inventory。
  - 建立固定 OHLCV reference vectors，分別驗證公式、seed、warm-up、null、gap、zero volume、NaN/inf 與 boundary。
  - 為 legacy v1 加明確 algorithm id；若核准 v2，建立 shadow canonical methods 與差異報告。
  - 決定 RSI Wilder、EMA/MACD seed/warm-up、KD smoothing 的 canonical v2 contract。
- Acceptance：
  - 測試不只確認欄位存在，而能以獨立 expected values 驗證公式。
  - 每個 field 都能回答 method、parameters、required/available bars 與 warm-up status。
  - Legacy v1 既有 output/score 不被無聲改寫。
- Validation：
  - `tests/test_technical_parameters.py`
  - `tests/test_technical_report.py`
  - 新增 focused indicator method/reference tests。

### 2. Price precision、period completeness 與 corporate-action safety

- Scope：`technical_analysis.py`、`evidence_builder.py`、OHLC aggregation／technical report projection、corporate-event guard。
- Work：
  - 分離 raw calculation、display formatting 與 optional tick-aware level projection。
  - 移除 `price >= 100 -> integer round` 對 outward calculation values 的影響。
  - 在 weekly/monthly 聚合加入 completed/current_partial contract；decision 預設使用 completed period。
  - 建立 `price_basis`、corporate-action coverage、known-event window、adjustment applied/method 與 warning/confidence policy。
  - 不在 coverage 不足時偽造 adjusted factor。
- Acceptance：
  - `99.95`、`100.5`、`482.5`、`505.5` 與 1000+ 商品不因 display threshold 改變技術意義。
  - 2026-08-12 的 incomplete weekly/monthly 不會被標為 completed。
  - 已知 corporate action 不會直接變成高信心 breakout/swing/divergence。
  - Raw/adjusted analysis 與 level basis 不混用。
- Validation：
  - price precision invariant tests。
  - weekly/monthly period-completeness tests。
  - corporate-action known/unknown/partial coverage tests。
  - `test_ai_technical_analysis.py`、`test_ai_evidence_builder.py`、`test_technical_report.py`。

### 3. `technical.indicators` canonical capability

- Scope：technical snapshot projection、AI capability registry/resolver、quality/readiness、public v4、MCP snapshot。
- Work：
  - 建立 versioned `technical.indicators` schema。
  - 回傳 daily／weekly／monthly indicator snapshot、method、parameters、warm-up、period status、price basis、freshness、source refs、missing/warnings。
  - Initial scope 僅台股 `stock`；dependency 為 `daily.ohlcv`，read-time derived，不新增 DB table。
  - 投影到 `evidence.data["technical.indicators"]`，並由 canonical quality resolver 產生 `evidence.capability_status`。
  - 保留 `technical.structure` 與 legacy answer；不把 raw indicator capability 混成 signal/decision score。
  - 重新產生 MCP offline snapshot，不手改 adapter contract。
- Acceptance：
  - `omi.ask` 可只選取 `technical.indicators`，不必載入全量 stock context。
  - Online backend schema、stream/non-stream、MCP online 與 offline fallback 一致。
  - Missing/partial/stale/provisional/warm-up 不因有 payload 就變成 ready。
  - 既有 v1 consumer 可忽略新 capability。
- Validation：
  - `test_ai_capability_contract.py`
  - `test_ai_capability_resolution_registry.py`
  - `test_ai_market_payload_contract.py`
  - `test_ai_market_context_projection.py`
  - `test_ai_public_v4_contract.py`
  - `test_ai_freshness_guard.py`
  - `test_omi_mcp_server.py`、`test_mcp_schema_contract.py`
  - `scripts/generate-ai-public-contract-snapshot.py` 產物 digest check。

### 4. Swing/Pivot foundation

- Scope：新增 `technical_swing.py`、parameters、capability/resolver、pure tests。
- Work：
  - 第一版使用 deterministic local extrema/fractal + ATR prominence filter。
  - 每個 pivot 輸出 evidence id、pivot time、confirmed at、left/right bars、prominence、previous move、price basis 與 provisional/confirmed。
  - Corporate-action affected window 依 coverage 降級或排除，不假裝正常 swing。
- Acceptance：
  - 同一組 OHLCV 每次輸出相同結果。
  - 截短資料到任一歷史時點時，不會使用未來 K 棒提前確認 pivot。
  - Provisional 不會升級成 confirmed outward signal。
- Validation：
  - 新增 `test_technical_swing.py`。
  - prefix-truncation／no-look-ahead regression。
  - high-volatility、flat、gap、missing bar、corporate-action fixtures。

### 5. Fibonacci 與 Divergence

- Scope：新增 `technical_fibonacci.py`、`technical_divergence.py`、capabilities、structured evidence tests。
- Work：
  - Fib 只能引用 `technical.swings` anchor/evidence ids；支援 retracement、extension、nearest 與 multi-horizon confluence。
  - Confluence tolerance 明示 ATR／pct method、algorithm version 與 deterministic tie-break。
  - Divergence 第一版只使用 confirmed pivots；明示 price/indicator pivot alignment 與 tolerance。
  - Regular divergence 為必要範圍；hidden divergence 只有在 regular contract 穩定後才啟用。
- Acceptance：
  - Fib anchor 可回溯，不自行猜無來源 anchor。
  - 上升／下降波公式與 extension direction 正確。
  - 沒有 confirmed pivot 不產生 confirmed divergence。
  - Price/indicator alignment、bars apart、strength 與 limitations 可稽核。
- Validation：
  - 新增 `test_technical_fibonacci.py`、`test_technical_divergence.py`。
  - multi-horizon confluence deterministic regression。

### 6. PVO 與 Breakout Quality state machine

- Scope：indicator/parameter/signal service、新增 `technical_breakout.py`、capability tests。
- Work：
  - 新增 PVO fast/slow/signal/histogram，處理 zero volume、warm-up 與 unit discontinuity。
  - Breakout state machine 使用 completed/provisional bar、level evidence id、close distance、wick rejection、volume ratio、PVO、bars held 與 retest。
  - 將 same-bar pierce-and-close-below 分為 `rejected_attempt`；`failed` 只表示 confirmed 後失效。
- Acceptance：
  - 2408 2026-08-12 對 505 壓力，在無先前 confirmed close 時為 rejected/weak attempt，不是 confirmed breakout。
  - Close above + volume/PVO confirmation、low-volume weak、retest held/failed 都有獨立 deterministic case。
  - 盤中未收盤資料不輸出 finalized failed/confirmed。
- Validation：
  - 新增 `test_technical_breakout.py` 與 PVO reference tests。
  - `test_technical_structure.py`、`test_technical_report.py`、`test_watchlist_radar.py` regression；Radar active score 必須保持不變。

### 7. Cost/positioning evidence 與 Relative Strength

- Scope：新增 Volume Profile、Anchored VWAP、Relative Strength modules/capabilities。
- Work：
  - Volume Profile 優先使用 bounded intraday bars；定義 binning、price allocation、value-area expansion、tie-break 與 node detection。
  - 沒有逐筆 aggressor data 時不輸出真實 buy/sell volume；daily fallback 明示 low-confidence approximation。
  - AVWAP 明示 anchor source/id、price input method、source granularity、cumulative volume 與 price basis。
  - Relative Strength 明示 benchmark mapping、aligned trade dates、5D/20D/60D returns、coverage 與 sector availability。
- Acceptance：
  - `VAL <= POC <= VAH`，bin/value-area 結果 deterministic。
  - AVWAP anchor 可回溯，零量／缺量不產生偽值。
  - Relative Strength 不把 RSI 當成相對強弱，且缺 sector coverage 時安全降級。
- Validation：
  - 新增 `test_technical_volume_profile.py`、`test_technical_anchored_vwap.py`、`test_technical_relative_strength.py`。
  - granularity、coverage、approximation、missing/fallback tests。

### 8. `technical.structure` v2 與 decision fusion

- Scope：`technical_structure.py`、`technical_report.py`、AI technical analysis/evidence/answer projection。
- Work：
  - 新增 additive `tw_technical_current_state_v2`，保留 v1。
  - 融合 momentum confirmation、volatility context、breakout context、Fib context、cost context、relative strength、scenarios、invalidation 與 counter-evidence。
  - 避免 RSI/KD/MFI/MACD 等相關 oscillator 重複投票；score 必須透明且可稽核。
  - 缺 advanced capability 時降級回 v1 evidence，不影響既有 MA/ATR/Donchian。
  - Radar 只接 shadow evidence/provenance；active ranking/weight 不切換。
- Acceptance：
  - Answer 可形成趨勢、動能同意/背離、breakout quality、Fib、成本區、relative strength、失效條件、反證與資料限制。
  - Optional advanced data 缺失不污染 unrelated required capability readiness。
  - v1 shape、legacy fields 與既有 Frontend fallback 保持可用。
- Validation：
  - `test_technical_structure.py`、`test_technical_report.py`
  - `test_ai_technical_analysis.py`、`test_ai_answer_composer.py`
  - `test_ai_outward_contract.py`、`test_ai_public_v4_contract.py`
  - Radar v1/v2 scoring、outcome/backtest invariants。

### 9. MCP／Frontend consumer sync

- Scope：MCP snapshot/schema、Frontend types／OMI dock／technical detail／必要 chart overlay。
- Work：
  - MCP 保持 thin，只轉送 selection/request 並呈現 canonical data/status。
  - Frontend 顯示 completed/provisional、method、price basis、confidence、missing/stale/partial 與 source。
  - Backend-auto Fib/AVWAP/Profile 與 user-drawn analysis 分色、分 source；不由 Frontend 重算 backend results。
  - Older-version、absent、partial 與 malformed payload 有安全 fallback。
- Acceptance：
  - Consumer 不以 payload 存在自行判定 ready。
  - 新 capability 缺失不造成 UI crash、`0` 偽值或文字溢出。
  - 手動畫圖維持原功能，且不被標成 AI canonical evidence。
- Validation：
  - Frontend TypeScript、ESLint、production build。
  - Focused Playwright：technical evidence rendering、source distinction、partial/stale/missing、older-version fallback。
  - MCP initialize → tools/list → `omi.ask` representative call。

### 10. Integrated validation、performance 與 runtime adoption

- Scope：完整 backend/frontend regression、API/MCP、response budget、代表性 DB/runtime。
- Work：
  - 執行 safe backend validation；Frontend 有修改才跑 frontend profile/build/E2E。
  - 驗證 2408 rejection/precision、一般多頭、空頭、資料不足、current partial week/month、corporate action、zero volume 與 stale cache。
  - 驗證 selected capability response budget、trimming、source refs 與 status 不被裁掉。
  - 比較單股與 Radar shadow benchmark；若顯著退化，先做 bounded optimization，不直接增加 cache table。
  - 先做 isolated runtime smoke；只有核准包含正式 adoption 時，才用 formal launcher 採用並證明 process lineage。
- Acceptance：
  - 所有 targeted tests 與 safe validation 通過。
  - Backend `/api/ai/tools`、`POST /api/ai/ask`、stream/non-stream 與 MCP 回傳同一 contract digest/semantics。
  - Representative user-visible answer 清楚揭露 dates、methods、freshness、limits 與 invalidation。
  - 若正式 adoption 在 scope，launcher log、source timestamp、PID/executable、listener、health 與 outward behavior 共同證明新 runtime 已採用。
- Validation：
  - `scripts/run-safe-validation.ps1 -Profile backend` 與相關 targeted args。
  - Frontend `npm run lint`、`npm exec tsc -- --noEmit --incremental false`、`npm run build`、focused Playwright（只在有 Frontend diff 時）。
  - Bounded API/MCP smoke；不做大量外部 refresh。
  - `git diff --check`、changed-file audit、private/secret/output artifact audit。

## Stop-and-fix rules

- 若 integration base 不清楚或會覆寫既有 dirty work，停止實作並先解決 worktree ownership。
- 若 legacy v1 output 被無聲改變，先建立 versioned compatibility/shadow path，不直接更新 consumer。
- 若 incomplete week/month、intraday overlay 或 corporate-action affected data 被標成 completed/ready，先修 freshness/coverage 再繼續。
- 若任何 indicator 只能以名稱而無法說明 method、seed、warm-up 或 input completeness，不得公開為 canonical ready evidence。
- 若 corporate-action coverage 不足，不猜 adjustment factor；保留 raw/unadjusted 與 limitation。
- 若 Swing/Fib/Divergence 測試出現 look-ahead，停止所有依賴該 anchor 的後續模組。
- 若 breakout 需要盤中尚未 finalized 的 close 才能成立，只能輸出 provisional。
- 若 Volume Profile／AVWAP 缺 granularity/method，或 daily approximation 被標成 exact，停止 outward projection。
- 若新 advanced evidence 改變 active Radar 排名、score 或交易方向，回到 shadow mode；未經另行核准不 cut over。
- 若 `evidence.data`、`evidence.capability_status`、warnings、missing、source refs 或 provider failure 在 projection/budget trimming 中遺失，停止 consumer sync。
- 若 MCP snapshot digest 不一致，不得宣告 public contract 完成。
- 若 targeted test、compile、typecheck、lint、build、browser 或 smoke 失敗，先修正；不能以其他層通過掩蓋。
- 若實作需要 DB migration、外部大量 refresh、正式 runtime restart、commit/push 或跨 repo Kuro 修改，而核准範圍未包含，停止並請求明確授權。

## Validation matrix

| Surface | 必要證據 |
|---|---|
| Formula | Independent reference vectors、method/version、warm-up、null/finite |
| Time | completed/provisional daily/weekly/monthly、session/date、as-of |
| Price | raw precision、display separation、price basis、corporate-action guard |
| Capability | registry、resolver、fields/limits、dependency、applicability、quality/readiness |
| AI v4 | `evidence.data`、`evidence.capability_status`、answer/decision、limitations |
| MCP | Online schema、offline snapshot digest、protocol smoke、thin adapter |
| Frontend | Types、fallback、status presentation、manual/backend source distinction |
| Radar | Active scoring unchanged、shadow provenance、performance benchmark |
| Runtime | Source/PID/listener/health/schema/outward behavior adoption proof |

## Decisions

- 2026-08-12：先修 price/time/method/corporate-action contract，再公開 raw indicators；不以新增 oscillator 取代結構缺口。
- 2026-08-12：`technical.indicators` 與 advanced capabilities 採拆分的 bounded capability，不合併成單一 `technical.advanced_structure`。
- 2026-08-12：canonical outward data/readiness 固定使用 `evidence.data` 與 `evidence.capability_status`。
- 2026-08-12：same-bar pierce-and-close-below 使用 `rejected_attempt`；confirmed 後失守才是 failed。
- 2026-08-12：advanced evidence 先進 `technical.structure` v2／Radar shadow，不直接改 active Radar score。
- 2026-08-12：使用者已核准完整計畫與 formal runtime adoption；以現有 dirty worktree 作為 integration base，保留其他工作並依 milestone 連續實作。
- 2026-08-13：使用者核准 technical indicator remediation wave；active consumer cutover 改為通過 gate 後的本輪目標，不再永久停在 shadow。

## 2026-08-13 remediation milestones

Status: Milestones 11-16 completed on 2026-08-13 after full regression, official launcher adoption, and live REST/MCP proof.

### 11. Canonical formula and parameter contract

- Scope：`technical_evidence.py`、`technical_parameters.py`、pure reference tests。
- Acceptance：J 值不 clamp；KD smooth period 真正生效；RSI key／overheat／breakout threshold 無 hidden constant；method catalog 與計算一致。
- Validation：independent RSI/MACD/KDJ/ATR/ADX/ROC/MFI/Bollinger/PVO/reference and parameter-change tests。

### 12. Calendar continuity and breakout lifecycle

- Scope：legacy MA continuity seam、Taiwan trading calendar、read-time breakout event reconstruction。
- Acceptance：合法長假不中斷 MA；真正缺交易日可見；inside/weak/confirmed/rejected/retest/failed/continuation 全部可達；GET 不寫 DB。
- Validation：calendar fixtures、state-machine fixtures、corporate-action suppression regression。

### 13. Provisional daily projection

- Scope：新增 pure session projection、canonical daily snapshot 與 technical report integration。
- Acceptance：盤中／盤後未發布正式日 K 時同時保留 completed 與 current_partial；正式日 K 不被覆寫；price/range/volume semantics 可機器判讀。
- Validation：market closed/open/no-trade/after-close/official-release fixtures，以及 volume partial regression。

### 14. Capability routing and per-capability readiness

- Scope：question routing、AI v4 selection、technical coverage projection、MCP schema invariants。
- Acceptance：RSI/KDJ/MACD/Fib/divergence/breakout/volume-profile/AVWAP/relative-strength 問題選取正確 capability；coverage 只限制真正受影響能力。
- Validation：query-plan、capability、quality/readiness、HTTP/MCP schema tests。

### 15. Consumer cutover and rollback

- Scope：technical report、signal、Radar indicator source policy。
- Acceptance：同股票/日期/timeframe 的 RSI/KD/MACD 共用 canonical source/version；legacy rollback 不改 public route/shape；Radar v1 ordering contract 受保護。
- Validation：shadow diff fixtures、technical report/signal/Radar regression、performance benchmark。

### 16. Full validation and runtime adoption

- Scope：safe backend profile、必要 frontend checks、launcher-selected runtime、REST/MCP outward proof。
- Acceptance：source tests、contract digest、runtime identity、representative current/partial payload 全部一致。
- Validation：safe validation、`/api/ai/tools`、bounded `omi.ask`、session-preserving MCP smoke。
