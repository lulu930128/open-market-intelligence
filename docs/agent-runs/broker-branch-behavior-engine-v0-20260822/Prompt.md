# Broker Branch Behavior Engine V0

## Goal

- 在既有 `broker_branch.summary` 與 `broker_branch_trade_daily` production path 上，建立可重現、可審計、backend-owned 的分點行為研究層。
- 先把 nStock Top15 的截尾語意、空資料、資料品質、分點身分與 raw/derived freshness 建成明確 contract，再建立 shadow behavior features。
- 只有在歷史長度、coverage、統計不確定性與 walk-forward validation 達標後，才逐步開放 `broker_branch.behavior`、短期 flow-risk 與 Radar 整合。

## Non-goals

- 不把券商分點視為單一投資人、主力、法人或 smart money。
- 不從 Top15 推估真實庫存、完整持倉、已出清或必然隔日賣壓。
- 不在 V0 使用 ML、LLM classification 或網路流傳的分點名單。
- 不回補 nStock 已無法提供的歷史日期，不做無界 provider backfill。
- 不讓 frontend、MCP、Kuro 或 provider adapter 重算 behavior、freshness、fallback 或 decision logic。
- 不在本任務自動購買 TWSE／TPEx 付費資料、變更 provider 授權、發送、發布或加入交易執行。
- 不在 Market Data Foundation 尚未完成 runtime adoption 前，順手改寫整個 legacy broker-branch raw path。

## Hard constraints

- `broker_branch.summary` 的既有 path、schema、projection、query behavior 與 cache-only read semantics 必須保持相容。
- `ranked_top_n` 下未出現只表示 `not_ranked`／`unknown`；不得轉成 0、無交易、已出清或沒有反向交易。
- `observed_opposite_flow` 不得命名為 `confirmed_unwind`；分點聚合資料不能證明同一批客戶或同一部位。
- deterministic composite score 不是機率；未經校準不得乘上張數產生 estimated lots。
- flow-only features 與 price-context features 分開；缺少價格 evidence 時只能讓相關 feature partial，不得污染全部 behavior evidence。
- raw source as-of、derived as-of、computed-at 與 methodology version 分開保存和投影。
- 新 schema 必須使用 Alembic migration，具 downgrade；不得重建、刪除或覆寫本機 SQLite 與既有 raw rows。
- GET／AI cache-only read 不啟動 provider、歷史掃描或 derived recompute。
- 所有 background compute 都有明確 target、session window、timeout、job identity、input fingerprint、partial outcome 與 retry 邊界。
- 新 capability 必須滿足 `advertised => projection exists`；未達資料與校準門檻時保持 disabled、shadow 或 `insufficient_data`。
- nStock 為第三方、未文件化 production API；公開散布、商業使用與 derived data 授權未確認前，不得把資料或衍生成果加入 public release artifact。
- 實作必須保留目前 worktree 的既有修改；開始 migration／models／capability 改動前先確認目前未追蹤的 `20260822_0064` 是否已成為正式 Alembic head。

## Context

- Repo: `C:\project\Open Market Intelligence`
- Related systems: Taiwan market service、SQLite／Alembic、jobs/scheduler、AI capability/quality/projection、HTTP、MCP、frontend、Radar。
- Current raw provider: nStock Broker Branch Top15，repo 中標記為 `third_party`，每檔股票每日最多為買超 Top15 與賣超 Top15 的聯集。
- Current collector:
  - active TWSE／TPEx ordinary-stock universe。
  - 先 probe provider 最新日期，再做 bounded per-stock collection。
  - 已有 skip-existing、partial/no-data/error、retry、startup catch-up 與 reconciliation。
  - provider 只提供最新 snapshot，歷史只能從 collector 啟用後逐日累積。
- Read-only DB baseline at 2026-08-22:
  - `broker_branch_trade_daily`: 1,260,475 rows、59 distinct dates、1,976 stocks、821 branch codes。
  - 接近全市場 coverage（單日至少 1,900 stocks）只有 25 sessions：2026-07-20 至 2026-08-21。
  - 只有 11 stocks 累積至少 30 sessions；0 stocks 達 60 或 120 sessions。
  - 25-session 次日配對：1,204,399 initial observations；33.84% 次日同 stock/branch 再進榜，66.16% censored；`opposite_given_reappearance=39.13%`。
  - `lots=0` 且 avg price 仍非 null 的歷史 rows 很多；其中 `buy_avg_price=0` 約 365k rows、`sell_avg_price=0` 約 383k rows。
- Current implementation gap:
  - 空 rows 在 `RawFetchResult` 保存前返回，無法區分合法空值、provider partial、尚未抓取與 schema 問題。
  - coverage 只以 trade rows 是否存在判斷，沒有 observation-batch quality truth。
  - `broker_branch.summary` 已存在於 capability contract；新的 derived capability 還需要 resolution dependencies、dataset lifecycle、freshness、projection 與 contract inventory。
- Current source/licensing context checked 2026-08-22:
  - nStock service terms: https://www.nstock.tw/app/user-agreement
  - TWSE all-stock broker-branch product: https://eshop.twse.com.tw/zh/category/sub/29
  - TPEx broker-branch products: https://eshop.tpex.org.tw/zh/product/list/1

## Deliverables

- `CapabilityContract.md`：source、coverage、identity、feature、freshness、persistence、outward 與 failure semantics。
- V0 observation-batch quality model、migration、pure normalization 與 regression tests。
- Shadow behavior feature engine、bounded incremental job、methodology registry 與可重現 snapshot。
- Data-readiness／calibration report，決定是否允許正式 classification。
- 若 gate 通過：`broker_branch.behavior` capability、AI/context/projection/query/answer contract 與 thin consumers。
- 若後續 gate 通過：dimensionless `broker_branch.flow_risk` 與 Radar counter-evidence；未通過則保留 disabled 並留下 no-go 證據。
- 每個 milestone 的驗證證據、rollback 方式、limitations 與 runtime adoption 證據。

## Done criteria

- Top15 的 absent/censored、empty、partial、invalid 與 source failure 可在保存層、derived engine、AI/API 與 UI/MCP outward 一致表達。
- 所有 feature 都有明確 numerator、denominator、eligible population、session window、coverage 與不確定性；沒有 look-ahead。
- 未達資料門檻時只回 `insufficient_data`／shadow status，不輸出過度確定的 branch class。
- 正式 behavior classification 只有在至少 120 個高覆蓋 session 與 walk-forward stability gate 通過後才可啟用。
- flow-risk 不宣稱 inventory、必然賣壓或 confirmed unwind；score 保持無量綱並揭露 components。
- Radar 只有在 out-of-sample 證明相對既有 technical/volume baseline 有穩定增益時才可使用；否則不整合也可視為正確完成結果。
- `broker_branch.summary` backward compatibility、cache-only、migration、derived freshness、capability projection、HTTP/MCP parity 與相關 frontend 驗證全部通過。
- Source-only tests、實際 migration adoption、runtime job、代表性 API/MCP 與使用者可見 UI 證據分層記錄，不以 source edit 冒充 runtime completion。

## Open questions / assumptions

- 暫定 V0 以精確 `(source_id, branch_code)` 作 identity；沒有具證據的 effective-dated mapping 前不自動合併 renamed／merged branches。
- 暫定 outward 第二能力使用 `broker_branch.flow_risk`；`pressure` 可作 UI 文案，但不作 inventory-like contract 名稱。
- 20／60／120 高覆蓋 sessions 分別作 exploratory、calibration-candidate、production-candidate gate；這些 gate 可由 calibration evidence 收緊，不可在沒有證據時放寬。
- nStock 本機研究使用沿用既有 source，但任何 public/commercial distribution 在授權確認前保持 out of scope。
- 未來完整來源必須經 provider-neutral observation contract 接入，由 backend 選擇 evidence；不能讓 behavior engine 自行混合 Top15 與 full-daily rows。
