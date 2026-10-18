# OMI 台股整合 G8 修復規格（方案 A 已核准／依 Gate 實作）

> 日期：2026-10-16，Asia/Taipei
>
> **狀態：APPROVED — G8-0 唯讀證據完成（部分確認）；G8-1 Source Patch 已寫入、動態測試受 ACL 阻擋；G8-2～G8-5 未開始**
>
> 2026-10-16 使用者已接受方案 A 並授權按 Gate 開始修復。授權涵蓋 G8-0 的唯讀取證，以及證據充分後的受影響 Source 定點修復；不代表授權正式 Provider 額外探測、付費訂閱、正式 DB mutation、重啟 Runtime、Commit／Push 或交易。各 Gate 必須逐項驗收，不得一次性全面重構。
>
> 事實基礎：[10/16 台股整合事件紀錄](TW_INTEGRATION_ISSUES_2026-10-16.md)、G5／G6／G7 Source 測試與 2026-10-16 盤中 `omi.ask`／唯讀 Raw+Canonical+JobRun 證據。本文件是計畫，不是即時健康狀態。

## 0. 預期成果與產品邊界（先確認）

**方案 A（建議預設）：「全市場研究 + Tier-A 即時 + 任意股票顯式按需 K 線」。**

| Lane | 服務範圍 | 對外可承諾的事實 | 不承諾的事 |
| --- | --- | --- | --- |
| Whole-market breadth | TWSE/TPEX 登錄股票 Universe | 每份同輪收據的 observed／directional／missing／partial、batch 實際成敗與時效；失敗時輪轉且有證據 | 公開 MIS 一律提供每檔 15 秒內成交價；把不同輪接成一輪 |
| Tier-A live quote | 明確納入、合法授權且串流已正常訂閱的標的 | 符合 event-time / trade / volume / lineage 品質契約的即時決策價，否則降為 research-only 或 null | 未訂閱股票仍顯示 live；把收據時間當成交時間 |
| Other-stock quote | 未在有效 Tier-A 串流範圍的標的 | 已存最近合格交易事實，明確揭露 as_of、freshness 與不可決策原因 | 強制給 current_price 或自動透過 GET 擷取 |
| 1m bars | 有限 Tier-A 背景生產；其他經使用者顯式觸發 bounded JobRun | 明確的 admitted / queued / running / success / partial / unavailable 狀態及逐分鐘 Coverage | 預設把全市場約 2,000 檔每分鐘都完整物化 |
| Index / completed daily | 沿既有正式獨立來源 | 保留 source authority / session / release window；當次已通過者維持 | 為了修 MIS Breadth 把可用 Index 換回舊路線 |
| AI / MCP / Frontend | 唯一 `omi.decision.v4` | 同一份 Canonical+Resolver Truth，忠實回傳 stale/partial/missing | 消費端補價、暗中 refresh、隱藏覆蓋率 |

若需求其實是**所有台股都必須 15 秒以內可供交易級決策**，這不是本提案可透過「調小排程秒數」保證的服務；需先盤點商用行情權限、授權範圍、並行限制及成本，另訂 Provider 容量／契約方案，不得默認公開 MIS 能達成。

## 1. 現有事實（不重驗已通過項目）

**2026-10-16 正式盤中證據：**

- 09:36 TWSE 695/1080 received、58 directional、574 actual-trade unavailable、385 not received、8/1/3 attempted/failed/skipped；TPEX 196/887 received、21 directional、150 unavailable、691 not received、3/1/6。兩市場 `market.breadth` 均 partial / decision_usable=false。
- 09:28–09:31 的六輪正式 Raw/Canonical 收據中，**五輪**包含 timeout 與 budget_exhausted；唯一完整的 TWSE 1074/1080 收據也只有 91/1080 directional。取得與有效價為兩個不同 Gate。
- 已存 MIS 訊息例如 3324 `z="-"` 且 `v>0`；現有 Resolver 拒絕憑成交量推導價格，是正確做法。上游為何不給 `z` 及是否有合法等效實際成交權威來源，仍未證實。
- 3324、2883 的正式 10/16 1m Query 顯示 not_materialized；10:05 限量唯讀 DB 核對當日 exact `JobRun`、`market_intraday_bar`、獨立 Quote Snapshot 均 0 筆。這**不等於**已證明 Tier-A 排除；需核對 Admission 決策。
- 2330 的 10/16 最新三筆 bounded 1m `JobRun` 都成功；nstock 09:00–10:00 有 61 個不同分鐘，Yahoo 同時窗另有重疊候選，不能將兩來源相加。
- 10/16 09:38 正式加權/櫃買指數 `market.indices` ready/current/decision_usable=true；保留該 Lane 已有效之證據。
- Source inheritance：G5/G6 價格安全及游標輪轉已有測試；G7 受影響回歸 159 passed、架構 guard 與隔離 HTTP 7 回應通過。Source PASS 不等於 Runtime/Live/Product PASS；G7完整 loaded identity 仍 UNATTESTED。

**關鍵程式設計：**

- `jobs/scheduler.py` → `market/indices.py::_refresh_current_market_summary` → `tw_current_market_platform.refresh_taiwan_current_breadth` → Gateway / Acquirer → `providers/twse_mis_current_breadth.py` → Canonical Transaction / Repository → `omi.ask`。
- Breadth 正式描述符目前只有 TWSE MIS；每批 100 檔、每 venue 20 秒 scan，22 秒 cooperative finalize。預設排程 60 秒、TWSE→TPEX serial，`coalesce=True/max_instances=1`。正式載入 interval 仍需 runtime 取證。
- `public_quote_platform.py` 需求最多 **15 秒 EVENT_TIME**；Quote 已透過 `public_quote_repository.read_current_stock_price_states` 和 `_merge_price_state` 使用合法 Breadth price-state 候選，非完全沒接上。錯誤通常是合法的候選缺失／舊價被拒，不應另建 Manager。
- `tw_intraday_universe.resolve_taiwan_tier_a_target_plan` 的 configured 來源與 Quote Contract symbols 配置相連，其他來源由獨立 Eligibility/Admission 保護；`taiwan_intraday_bar_scheduler` 每 15 秒 poll admission、預設每 target 300 秒 due、上限 32 targets，背景執行槽為 2；持久化／重試由 `taiwan_intraday_demand` JobRun 擁有。
- `http_client.request` 每次建立/關閉 Session，已確認有此生命週期；尚未證明 Session 反覆建立是 slow batch 的主因，不能先任意共享 Session 或提高並行數。
- `market.indices` 的 Fugle/MIS Owner 與 MIS Breadth 不同，不能合併成一個故障；`intraday.bars` 另有 nstock/Yahoo/Fugle/KGI descriptor 與 Bar owner，不能拿 Bar Close 假裝最新成交。

## 2. G8 Gate 設計與實作順序

### G8-0 — 建立可重播的正式診斷基準（read-only；執行前期先完成）

**目標**：修復前先能說清「哪一批慢、哪個 Provider 欄位缺、哪檔未被 Admission」。

Owner：既有 `twse_mis_current_breadth` / internal receipt、`taiwan_intraday_bar_scheduler`、`public_quote_repository` 及各自診斷。

工作：
1. 從同個正式 Launcher selected DB 與 Runtime 建立只讀基線：live PID、project root、interpreter、migration、source loaded identity；`UNATTESTED` 仍以缺口列示，不能假補 PASS。
2. 每 venue 各取至少三輪自然產生的收據（事件時間、received/fetched、raw_id、attempted/failed/skipped、scan cursor、同輪 received/native `z`/directional/unknown）；G7 `timeout_origin/stage` 只從受控 internal evidence 查，絕不洩漏完整 raw payload 或 Credential。
3. 建立 bounded 比對：Provider batch transport、decode、分類、payload build、queue/start、summary lock、Provider guard、DB transaction、consumer read。缺少 correlation 時先標 UNVERIFIED，且僅在既有 Owner 補最小 instrumentation。
4. 固定公開案例：3324/2883/2330 的非敏感 eligibility/admission reason（如 selected/excluded/due/capacity/active_job）、最近 JobRun 原因、已存 1m coverage、Quote candidate selected/rejected code 與 event age。不可讀或回傳私人持倉/清單內容。
5. 明確區分：Provider `z="-"`、合法交易卻 Parser 拒絕、同 session cache 因 volume change 被拒、真正無成交、競價、DB 來源缺席。

**Gate-0 PASS**：每項 P1 至少能定位是哪層 fail 或有具體可重現的 external blocker，否則不啟動相關範圍的盲改；不要求 Provider 當下變好。

### G8-1 — 縮減 MIS 取得延遲與尾段飢餓（TW-101）

範圍：`backend/app/market/providers/twse_mis.py`、`twse_mis_current_breadth.py`、`twse_mis_breadth_evidence.py`、existing Guard／Control。**先有實測瓶頸才准改。**

決策分支：
- 若 transport phase（連線/代理/TLS/等待回應）確實主導，先比較連線生命週期與不同批次長尾；只有證明安全性與改善效果時，才在原有 IO Owner 做 bounded Session/connection reuse，保留 timeout worker 佔用與 close/idle 邊界。
- 若純 batch size/尾批逾時為主，透過離線 deterministic replay 比較現有 100 檔分批與其他有界方案、剩餘 deadline admission/fairness；不得任意加大 TWSE 外部呼叫或繞過 guard/cooldown。
- 若 Provider 自身長尾不可控，保留 partial 並提供誠實的 Provider availability 診斷；升級 source 能力前需有正式 Provider contract，不能為追求 100% 回復 fallback 到 legacy。
- 不更動 Source of Truth、Market Gateway、價格資格與單輪 Universe 分母。

**Gate-1 PASS**：正常路徑、slow/timeout、HTTP 429、guard-open、late-worker、跨輪 scan cursor、native counts、single-slot negative tests 通過；受影響範圍架構 guard PASS，不能增加無上限 Thread/Session；本地若只改善診斷則標 Source PASS / LIVE 未改善。

### G8-2 — 單股合法即時成交價（TW-102 / TW-103）

範圍：現有 `tw_realtime_capabilities` descriptor、`public_quote_platform/repository`、`twse_mis_observation`、合法 Tier-A lease/subscription owners。

工作：
1. 先核對三檔及受限代表樣本，從 Provider raw 欄位 `d/t/z/v/tv/ts` → Canonical TradeState → selected quote/price-state → Outward `current_price` 的時間與拒絕原因；沒有真實 Authority 證據不升格。
2. 將產品區分 **Tier-A live** 與 **research-only delayed**，沿原 Gateway/Resolver 依 entitlement、subscription、event time、source priority 選擇，**不在 AI/MCP 增加自行 fallback**。
3. 只對確實被選為 Tier-A 且已具授權的標的，確認現有 Fugle/KGI 串流可否提供合法 current trade（權限不足則不自動接入或啟用）；非 Tier-A 仍可回傳 stale/research last trade。
4. 保留 `PUBLIC_QUOTE_MAX_AGE_SECONDS=15`、原交易日／試撮／volume-change fail-closed；若將來要調整產品要求或提供延遲分級，另訂 outward contract，不能靜默放寬。

**Gate-2 PASS**：新鮮合法交易候選可被選、`z=-`/auction/stale/volume increased/lineage mismatch 不可被選；正式 `omi.ask` 對訂閱標的呈現符合來源真相的現價，不可用標的帶明確 degradation 原因。不得將全市場即時需求誤判為 Tier-A 已完成。

### G8-3 — 1m Bars Admission 與物化覆蓋（TW-104）

範圍：既有 `tw_intraday_universe`、`taiwan_intraday_bar_scheduler`、`taiwan_intraday_demand`、`tw_intraday_platform`、`tw_bar_service`。

工作：
1. 先對 3324/2883 的 `no JobRun` 查有限、去識別化 admission decision：配置/有效 lease、target 上限、next due、背景槽、JobRun 重用或 admission 例外。沒有理由碼則在既有 scheduler/JobRun 增加 minimal observable status，不建新 queue。
2. 拆清「Quote Contract canary」與「Tier-A background 1m target」的設定 ownership：避免意外用 Quote 測試標的配置控制研究生產；變更需保持已有 target priority/lease/privacy contract，並以配置相容或 migration 規則交代舊值的處理。
3. 保持 `GET` 與 `omi.ask(cache_only)` 唯讀；其他股票需要 1m 時由**顯式受權的現有** `tw.refresh_intraday_bars` JobRun 對同一 stock/date 去重、保留 quota/backoff，回傳 queued/running/partial/ready 狀態。
4. 驗證 `nstock` 等 provider 到 `market_intraday_bar` 的 target/date/lineage/volume、JobRun `CANONICAL_CURRENT_SESSION_READY`、同時間窗/單一 Provider 的 1m 覆蓋率。2330 的 nstock 與 Yahoo 重疊不能相加；查錯 Provider 不應拿 Quote/Breadth 塞入 Bar。
5. 確認適當的 Snapshot 快取 invalidation 依 canonical storage_revision 與時窗更新，避免已入庫但舊 snapshot 持續 missing；只有看到此缺陷才改 cache。

**Gate-3 PASS**：3324/2883 在被合法 admitted 後可產生 JobRun＋正確的 canonical bar 或正式可追溯拒絕原因；2330 單一 Provider 逐分鐘覆蓋增長可被讀取；正常 GET/ask 0 Provider fetch/DB write，重試與失敗不重複扣 quota 或破壞同一 JobRun。

### G8-4 — 消費端與族群覆蓋率驗收（TW-105、歷史觀察 TW-107/108）

- `market.breadth` 單輪、`market.sectors` rolling state、`market.sample_ranking` completed daily、`screening.coverage` 不同分母及時間需各自顯示。資料不足時排名不可假稱全市場。
- `market.indices` 2026-10-16 有正式 ready 證據，未改依賴前繼承、不重複拆修。
- 單股 auction 在下一個適當盤前窗口定點驗證 indicative-only lane；不將試撮價提升為正式成交價。
- 官方 Daily/EOD 的 TPEX 歷史延遲改以 completed-session publication Gate 在該日公開後檢查，不插入 MIS 盤中修復里程碑。
- 只有前述 Provider/Canonical 實際有效後，才核對 AI/REST/MCP/Frontend 一致性，避免在顯示層掩飾源頭缺口。

**Gate-4 PASS**：各能力有真實 status、as_of、coverage、decision/facts usability；公共 `omi.ask` 不查 private Account、不觸發任何 refresh；同一證據跨 API/MCP 結果一致。

### G8-5 — 正式 Runtime / Live / Product 驗收與封版

四個獨立 Surface：Source → Runtime → Live → Product，不可用一個 PASS 取代全部。

1. **Source**：只跑修改區域的 negative/positive regression、所受影響的 Guard、架構檢查、格式/compile、必要 isolated HTTP。G5/G6/G7 未受影響者沿用 159 passed 等歷史證據；共用模組改變才補受影響項。
2. **Runtime**：先取得 launcher/backend ID、project root/interpreter、selected port、schema/migration、正式 loaded module/version attestation；如需要重啟，需獨立明確授權且經正式 writer-drain/owner approval，拒絕繞過 `ALL_WRITERS_DRAIN_UNAVAILABLE`。
3. **Live**：正式盤中各 venue 至少 3 輪自然收據（如發生長尾應包含故障情境），保留同輪 attempts/failed/skipped、native `z`、方向、unknown、as_of／received／fetched、budget 使用與 Provider reason。若有公平性/穩定性定量目標，須在 G8-0 的來源能力證據後設定並標明取樣限制，不能臨時捏造成功率。
4. **Product**：由 Reviewer **親自呼叫正式 `omi.ask`**，覆蓋 market.breadth、3324/2883/2330 quote.snapshot、intraday.bars、market.sectors、market.indices；負向案例也要驗證「不可決策」正確，並確認沒有 Account fetch/hidden refresh。
5. **封版分範圍**：可接受「Index 已封／Tier-A 已封／Full-market Breadth 仍以 partial 正式降級」等分層結果；**不因某條全市場來源超出 Provider 能力而聲稱所有台股均 Live PASS**。

## 3. 工程邊界與禁止事項

- 不建第二套 Provider Manager、Quote Cache、Scheduler、DB Transaction Owner、MCP 決策路徑。
- 不放寬 15 秒事件 freshness、不用 `pz`、bid/ask midpoint、分鐘 Bar close、昨收或滯後價冒充 current actual trade。
- 不使用不同 receipt 的 observed stock 合成同輪 100% coverage；不把 verified no-trade 算 missing，也不推測停牌狀態。
- 不因 Source 正常便認定正式 Runtime adoption；G7 `timeout_origin/stage` 在 internal raw evidence，Canon summary 沒欄位不足以證明未載入。
- 不因外部 API 慢就盲目增大同時連線、provider quota 或 retry storm；Guard/Backoff 和 bounded workers 維持。
- 不查、列印或擅自操作私人投資部位；不觸發 KGI 交易、SDK 下單或其他 broker side effect。
- 不刪庫、建新旁路、重建全部 market data，不修改未授權的其他市場；不 stage/commit/push。
- Repo 目前是已有大量 dirty worktree 的 `main`；正式開工前先保存影響區域 baseline/hash與既有變更，Patch 不能覆蓋 G5/G6/G7 或 KGI WIP。

## 4. 測試最小化與失敗停止條件

- **回歸設計**：Provider timeout 分類、caller deadline、late worker、guard cooldown、游標公平輪轉、同輪 coverage/分母、合法/不合法 z、Quote freshness/lineage、JobRun dedupe/expiry/priority、Bar exact-session/provider-overlap 與 API/MCP fail-closed。只做改動相關子集。
- **停手而非重試**：同一 Provider I/O 症狀兩輪無新證據時重新評估取證方法；正式服務權限/Drain 拒絕停止重啟；外部來源缺 z 未有合法同級證據不得以新 Provider 名稱或推導價掩飾；資料庫／交易/訂閱變更需要額外授權。
- **每 Gate 保存**：Commit/source SHA、受影響檔案、Source/Runtime/Live/Product 四面結果、測試 exit code、選用 receipt ID、驗收時間、仍未知項、下個最小動作。未影響的舊 Gate 可以繼承。
- **回滾策略**：每小範圍獨立 Patch/Diff，保留現有 G7 Source 和原 Runtime；本地回滾只能針對本輪變更，不使用全 Repo reset。正式更新失敗先保留收據與原來源設定，停用新增路徑或按已授權的版本恢復程序；不做無核准的 Kill/DB rollback。

## 5. 核准項目與執行策略

**建議待使用者確認以下預設後才開始 G8-0：**

1. **產品定位**：接受「全市場 best-effort 研究 + Tier-A 合法即時 + 其餘個股顯式按需 K 線」作為第一版完成條件；若改為全市場 15 秒交易級必須先做商用資料容量規劃。
2. **價格原則**：維持 `PUBLIC_QUOTE_MAX_AGE_SECONDS=15` 作為即時決策價的現有門檻；另外可在 outward 保留 research-only stale last trade，不升格。
3. **授權範圍**：G8-0 首先只讀追證；通過 G8-0 後再按每個 Gate 修改最小 Source。正式 Provider probing、增訂閱、資料庫 migration、Backend restart、Commit/Push 都另行確認，不隨計畫自動授權。
4. **交付判定**：分模組完成，不能用某一輪 99% received 作封版；以真實 decision-grade quality 和 per-capability readiness 為準。

**當前狀態：方案 A 已核准，G8-0 開始取證。尚無 G8 Code、Runtime、Live 或 Product Gate 可宣稱通過。**

## 6. 相關真相與交接

- [事件紀錄](TW_INTEGRATION_ISSUES_2026-10-16.md)
- [G6 Source 與驗收](docs/exec-plans/active/tw-intraday-g6-20261012/Engineering.md)
- [G7 原始修復與已通過驗證](docs/exec-plans/active/tw-acquisition-g7-20261015/Engineering.md)
- [Current Backend Architecture](docs/architecture/BackendArchitecture.md)
- [Market Temporal Contract](docs/architecture/MarketTemporalContract.md)
- [Canonical Registry / Dataset Catalog](backend/app/market/tw_dataset_catalog.py)

下次開始時必須先檢查此計畫是否已核准、Git Diff 是否有新變更、現有 G5-G7 是否仍可繼承。不得因計畫已建立就自行執行 G8-1 至 G8-5。
