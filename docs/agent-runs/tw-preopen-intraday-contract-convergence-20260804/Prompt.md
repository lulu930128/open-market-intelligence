# 台股盤前／盤中契約收斂與實盤驗收

## 目標

- 以 2026-08-04 盤前與盤中實測為基線，收斂台股 session、quote、auction、
  1 分 K、市場成交值、指數、freshness、source health、NLU 與 refresh
  telemetry 的 backend-owned 公開契約。
- 修正 `OMI-TW-001`～`OMI-TW-011` 中已確認的 correctness 問題，並把
  `OMI-TW-007`、`OMI-TW-008`、`OMI-TW-011` 的契約歧義拆成可驗證的正交欄位，
  不用單一布林值掩蓋 partial、stale、scope 或 refresh ownership。
- 沿用 2026-07-30 台股盤中契約與 2026-08-03 市場廣度 v2 的既有成果，
  將本任務定位為「live acceptance convergence」，不重做既有資料面。
- 最終以 deterministic regression、safe validation、正式 launcher runtime、
  REST／AI／repo MCP 與真實交易時段證據證明使用者可見行為。

## 來源與基線

- 使用者測試與定位指南：
  `C:\Users\thoma\Downloads\OMI_盤前盤中問題_程式碼定位與修改指南_20260804.txt`。
- 前置任務：
  - `docs/agent-runs/tw-intraday-contract-convergence-20260730/`
  - `docs/agent-runs/tw-market-breadth-canonicalization-20260803/`
- 長期產品與架構：
  - `docs/product/ProductVision.md`
  - `docs/product/OperatingModel.md`
  - `docs/product/QualityBar.md`
  - `docs/product/Roadmap.md`
  - `docs/architecture/BackendArchitecture.md`
- 建立本任務時：
  - Repo：`C:\project\Open Market Intelligence`
  - Branch：`main`
  - HEAD：`2d0476d`
  - Worktree 已包含 2026-08-03 breadth v2、migration、AI、MCP、Radar 與
    Frontend 的未提交修改；它們是本任務的實際基線，不得 reset、revert 或覆寫。

## 已確認的問題分類

### 必須修正的 correctness 問題

- `OMI-TW-001`：`preopen_auction` 未被 realtime contract 視為 active auction
  session，造成盤前 quote facts 被誤判 stale／blocked。
- `OMI-TW-002`：auction capability 未辨識 `preopen_auction`，出現資料可用但
  reason 為 `SESSION_NOT_AUCTION` 的矛盾。
- `OMI-TW-003`：盤前 market-minute persistence 將 previous completed session
  的 daily trade value 回填成當日累計成交值。
- `OMI-TW-004`：1 分 K 使用 quote-like age threshold，31 秒級正常分鐘資料在
  `require_live` 下被誤判 delayed／blocked。
- `OMI-TW-005`：跨交易日的正常隔夜間隔被 continuity contract 計入
  `missing_interval`。
- `OMI-TW-006`：`market.indices` 只讀 completed daily summary，卻在盤中投影成
  ready／current。
- `OMI-TW-009`：NLU 以直接 substring hint 判斷持倉與風險意圖，沒有處理否定
  與欄位語境。
- `OMI-TW-010`：TXF 對 `diagnostics.source_health` 宣告 applicable，但回傳空的
  semantic payload。

### 必須澄清並修正公開契約的問題

- `OMI-TW-007`：真正問題不是禁止 `partial + is_current=true`；partial 可表示
  coverage，而 current 可表示時間。需分離 temporal currency、requested-session
  alignment、completeness、capability-level as-of 與 mixed-date 狀態。
- `OMI-TW-008`：system source-health 已有 row age／stale 欄位，但 AI unified
  projection 沒有重用，且以最新一筆 `checked_at` 代表整體，會被單一新 row
  掩蓋大量過期 row。
- `OMI-TW-011`：`refresh_if_missing=true` 是允許 bounded refresh，不保證同一
  request 執行所有 fill actions。現況的核心缺口是 reader/provider/tool-run
  嘗試狀態沒有分層，不能只看 `attempted=false` 判斷是否完全未嘗試。

### 應保留為正常限制的狀態

- 開盤初期 `actual_trade_only` coverage partial。
- 盤中累積成交值為有明確 authority／method 的 estimate。
- Hot groups／ranking 只使用 scheduler-owned partial universe。
- 5 日／20 日同分鐘基準因歷史樣本不足而 warmup。

這些狀態不得被「修成 ready」；應保留可見的 scope、coverage、sample days、
estimate 與 limitation。

## 不在本任務範圍

- 不重寫 `tw.market.breadth.v2` 或把 `pz` 重新納入 actual-trade breadth。
- 不改變台股核心、其他市場為 context layer 的產品定位。
- 不讓 Frontend、MCP、Kuro 或 adapter 重算 session、freshness、fallback、
  source health 或 readiness。
- 不在 GET／AI read path 啟動全市場 refresh、歷史大量 backfill、source-health
  prune、報告／記憶寫入或付費 quota 行為。
- 不把 previous close、daily turnover、auction indicative price 或 synthetic
  snapshot 偽裝成 current-session actual trade。
- 不為了解決 source-health 歷史 row 而刪除正式 DB 資料。
- 不進行無關重構、dependency upgrade、格式化-only diff。
- 未經使用者明確要求，不 commit、push、publish、更新 repo 外的 standalone
  OMI_search，或執行破壞性 DB 操作。

## 硬性限制

- Backend market／AI contract 是 session、observation semantics、freshness、
  source health、refresh telemetry 與公開 answer 的唯一 owner。
- `evidence.capability_status` 維持 consumer-facing readiness 唯一權威；新增欄位
  只能補足正交事實，不能形成第二套 readiness matrix。
- `omi.decision.v4` 保持 additive、相容演進。若需新增 capability ID，舊
  `market.indices` 必須保留為相容 composite，不可直接破壞現有 caller。
- Raw provider phase、payload time、observation kind 與來源必須保留；canonical
  phase 不覆寫 raw phase。
- Freshness 必須依 observation kind 與 interval 判斷；quote、auction、partial
  1m、finalized 1m、daily close、health snapshot 不共用同一 age threshold。
- `market_session` 與 `observation_mix` 分離；09:00 邊界可有 mixed observations，
  但 authoritative market session 不得因此變成 `mixed`。
- 盤前 current-session trade value 沒有 actual-trade 證據時必須 unavailable；
  不得 fallback 到前一 completed session 的 daily value。
- 歷史錯誤 row 優先以 read-time eligibility／quarantine 隔離，不直接改寫或刪除
  production DB。若真的需要 schema，必須另行提出 additive migration 與副本驗證。
- Source-health read path 保持 read-only；歷史／expired row 可見但不能主導
  current request 的 aggregate status。
- `refresh_if_missing` 只代表允許 refresh。所有 provider／reader／tool run 的
  實際嘗試、cache hit、結果與未嘗試原因必須分開呈現。
- 所有 session 與 continuity 判斷使用 Taiwan trading calendar 與 Asia/Taipei，
  不以相鄰 timestamp 的牆鐘差直接推論遺漏。

## 交付項目

- `OMI-TW-001`～`OMI-TW-011` 的 issue-to-owner、契約決策、里程碑與驗收矩陣。
- 可固定時間、離線重放的 preopen、09:00 handoff、regular intraday、overnight、
  post-close、stale health、TXF 與 NLU fixtures。
- 共用 Taiwan session normalization 與 observation-aware freshness primitive。
- Session-aware trade-value eligibility 與 continuity boundary 修正。
- `market.indices` live／official-close 雙語意與 `data.freshness` 正交欄位。
- AI unified source-health 與 system serializer 的 age／stale 語意收斂。
- TXF `diagnostics.source_health` 明確 supported 或 not-applicable 契約。
- Negation-aware NLU 與 refresh reconciliation telemetry。
- Backend API、public v4、repo MCP snapshot 與必要 Frontend 型別／呈現相容調整。
- Targeted regression、backend safe profile、必要 frontend profile、正式 runtime
  及真實交易時段驗收證據。

## 完成定義

- 11 個 issue 都有「修正完成」或「經契約證明為非 bug 且 telemetry 已澄清」的
  明確結論，沒有以 generic ready/current 掩蓋。
- 盤前 quote／auction facts 可用且不冒充 actual trade；
  `quote.snapshot` 與 `quote.auction` 不再互相矛盾。
- 正常 1 分 K 在 interval-aware tolerance 內可供 intraday research；
  execution-grade 仍由更嚴格 policy 獨立決定。
- 盤前 public API、AI、MCP 與 DB reader 不再揭露前一交易日成交值為當日累計。
- 隔夜、週末、休市與已知 session boundary 不計為 missing interval；同一 session
  內真正缺 bar 仍可被偵測。
- `market.indices` 不把 previous completed close 當 live；沒有 current-session
  index 時明確 fallback／stale／unavailable。
- `data.freshness` 可同時回答資料是否夠新、是否屬 requested session、是否完整、
  是否 mixed-date，以及各 capability 的真實 as-of。
- Unified source health 每筆 row 有 age/stale/lifecycle；aggregate 不被單一最新 row
  掩蓋，且 direct request success 與 persisted expiry 可同時表達。
- 否定語句不再產生持倉／交易意圖；真正的風險詢問仍可被辨識。
- TXF 不再出現 applicable + available + empty semantic payload。
- Refresh response 可區分 permission、primary reader、provider fetch、tool run、
  cache hit、outcome 與 not-attempted reason。
- 現有 breadth v2、Radar、screening、hot groups、跨市場共享 contract 與
  `omi.decision.v4` 無 regression。
- 正式 runtime owner/path、launcher-selected ports、DB revision、registry digest、
  REST、AI 與 repo MCP 均一致，並完成至少一輪盤前、開盤初期、盤中、收盤交界
  與盤後驗收。

## 預設決策與待驗證假設

- 預設不新增 DB migration；先以 pure resolver、projection 與 read-time eligibility
  修正。只有現有欄位無法表達必要真相時才停下重新審議。
- `market.indices` 預設保留相容 ID，內部拆分 `live_snapshot` 與
  `official_close` component；是否新增 `market.indices.live`／
  `market.indices.official_close`，在 registry／consumer audit 後採 additive 決定。
- TXF 預設優先投影既有 futures provider health；若沒有足夠可追溯資料，改為
  `not_applicable`，不合成空 payload。
- Unified source-health 預設不刪舊 row；以 requested scope、canonical active
  scope、row age 與 lifecycle 分層，歷史 row 留在 history/detail。
- 2026-08-04 的固定案例先成為 deterministic regression；正式完成仍需下一個
  可用交易時段的 live evidence，不以 fixture 代替實盤。
