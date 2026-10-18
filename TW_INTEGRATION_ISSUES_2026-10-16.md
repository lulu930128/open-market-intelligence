# OMI 台股整合問題盤點與待驗收清單 — 2026-10-16

> **用途**：當日正式盤中事故／工程問題紀錄；下一輪修復與驗收的交接基準，不是已封版文件。
>
> **觀察窗口**：2026-10-16 約 09:27–09:40（Asia/Taipei）。市場收據、MCP 查詢時間不同；表格均標示各自的事件時間。
>
> **工程狀態**：Backend/Frontend 服務正常；G5/G6/G7 已通過的 Source Gate 繼承；正式台股全市場即時行情、單股決策現價及部分 1m K 線的 Live/Product 可用性仍未通過。
>
> **本次處置**：只讀 OMI_search.omi_ask、唯讀 Raw/Canonical 診斷與 Workspace 程式／Git 檢查。僅建立工程問題紀錄；未改 Source、未跑大量測試、未刷新 Provider、未重啟、未修改正式 DB、未交易、未 commit/push。

## 1. 核心結論：失敗在哪一層？

這不是整個 OMI 停擺，也不是 MCP 網頁畫錯數字。故障主因有兩條彼此獨立的資料缺口：

1. **Acquisition coverage（Confirmed availability defect，P1）**：TWSE MIS 分批擷取在部分輪次受 20 秒 scan budget／傳輸耗時限制，最後批次 timeout，後續批次 budget_exhausted 而未取得資料。G6 已驗證 scan cursor 在預算耗盡後輪轉，可避免尾段永久餓死，但無法保證當輪完成，也不能改善 Provider I/O 延遲。
2. **Qualified actual price（Confirmed availability failure／Provider limitation，P1）**：即使批次全部完成，大量股票的來源 top-level **z** 仍未提供合格當次成交價，累積量或試撮價不能代替實際成交；正確的 Resolver 拒絕將其冒充即時現價。2026-10-15 的 3324 原始例證為 z=-、v=285；2026-10-16 仍有大量 ACTUAL_TRADE_PRICE_MISSING。Provider 為何如此輸出尚未完全判明，不可直接指控 Parser 丟值。

**結果**：Market Breadth、族群排行、某些單股 Quote 無法滿足決策級品質；這些能力回傳 partial/stale/null 是已確認的品質保護，不等於根因已修復。

G7 只修了本地 timeout 原因識別、worker/caller deadline 混淆與已完成失敗的 timing 證據遺失；**沒有**修改 Provider 來源、改變 20 秒／22 秒 budget、放寬 15 秒 quote freshness，也沒有承諾覆蓋率提升。

## 2. 2026-10-16 正式證據

### 2.1 同輪最新 market.breadth（正式 omi.ask，cache-only）

| 市場 | event as_of | Universe | Received | Directional | actual_trade_unavailable | Provider missing | valid_no_trade | attempted/failed/skipped |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| TWSE | 09:36:06 | 1,080 | 695 | 58 | 574 | 385 | 63 | 8 / 1 / 3 |
| TPEX | 09:36:15 | 887 | 196 | 21 | 150 | 691 | 25 | 3 / 1 / 6 |

- TWSE unavailable 574 = ACTUAL_TRADE_PRICE_MISSING 571 + AUCTION_INDICATIVE_ONLY 3。
- TPEX unavailable 150 = ACTUAL_TRADE_PRICE_MISSING 146 + AUCTION_INDICATIVE_ONLY 4。
- 同輪皆 status=partial、decision_usable=false。分類等式：directional + valid_no_trade + actual_trade_unavailable = received；received + provider_missing = universe。
- 不將「未收到」當作「平盤／停牌／沒成交」，也不跨輪合併覆蓋率。

### 2.2 連續輪次證據：波動並非單輪偶發

下列是 10/16 正式 DB RawFetchResult／TaiwanCurrentBreadthSnapshot 對上同一 receipt 的 **六輪**，不是 09:36 單輪，也不是跨輪合併：

| Venue | event_at | Raw ID | Received / Universe | Qualified directional | Batch attempted / failed / skipped |
| --- | --- | ---: | ---: | ---: | --- |
| TWSE | 09:28:58 | 769531 | 695 / 1080 | 59 | 8 / 1 / 3 |
| TWSE | 09:29:53 | 769551 | 1074 / 1080 | 91 | 11 / 0 / 0 |
| TWSE | 09:30:56 | 769573 | 498 / 1080 | 44 | 6 / 1 / 5 |
| TPEX | 09:28:22 | 769517 | 589 / 887 | 74 | 7 / 1 / 2 |
| TPEX | 09:29:26 | 769553 | 493 / 887 | 70 | 6 / 1 / 3 |
| TPEX | 09:31:17 | 769580 | 493 / 887 | 68 | 6 / 1 / 3 |

六輪中五輪最後 attempted batch 記載 timeout，其後 skipped 為 budget_exhausted；只有 TWSE 769551 acquisition_complete=true。**即使收到 1074／1080，directional 仍只有 91／1080**：此為「掃描完成」與「具備有效成交價」不等價的直接證據。

本輪只讀 Canonical 的 acquisition_diagnostics_json 與 raw metadata。Canonical 只包含摘要／receipt_evidence_id，G7 的內部 batch timeout_origin/timeout_stage 實際儲存在 Raw 的完整 internal evidence，未在本輪解碼 raw_text；所以 **G7 per-batch 正式採用仍未驗證**，不能因 Canonical 缺欄位反推版本未採用。

### 2.3 單股 quote.snapshot（正式 omi.ask）

| 標的 | 已存成交證據（事件時間） | 最新查詢判定 | 核心影響 |
| --- | --- | --- | --- |
| 3324 雙鴻 | 1405 @ 09:23:05；稍後查詢可見 1420 @ 09:36:45 | stale，current_price.value=null | 有歷史合格成交，但沒有當次決策級新價 |
| 2883 凱基金 | 38.65 @ 09:10:31 | stale，current_price.value=null | 歷史成交價不可由更新 receipt 時鐘洗成新現價 |
| 2330 台積電 | 2440 @ 09:28:00 | stale，current_price.value=null | 短時間內的成交價也可能因品質／15秒規則失去 current 資格 |

這是 **單股即時價格可用性問題（P1 Product availability）**，不是「應把 null 強制改成最後一筆成交價」的修復需求。不可拿 bid/ask midpoint、試撮 pz、今日 bar close、昨收或過期最後成交價取代實盤成交。需要沿單股 Source → Normalize → Canonical → Quote Resolver → omi.ask 精確量測 event/received/read time。

### 2.4 1 分鐘 K 線（獨立 nstock lane，不能與 MIS Quote 混用）

以同日 cache-only intraday.bars 驗證：

| 股票 | 預期／已觀測分鐘桶 | materialization_state | 判定 |
| --- | --- | --- | --- |
| 3324 | 38／0（截至約 09:38） | not_materialized | 缺失；repair_recommended=true |
| 2883 | 39／0 | not_materialized | 缺失；repair_recommended=true |
| 2330 | 39／33（缺6） | materialized | partial_prefix；degraded，repair_recommended=true |

- 3324/2883 回報 TW_CHART_SNAPSHOT_MISSING；2330 為 TW_CHART_SNAPSHOT_PARTIAL_PREFIX。
- Provider/Service 擁有者與 MIS Breadth **不同**：當日 intraday.bars 由 nstock_minute_stock_data 及既有 TW bar service／materialization owner 供應。
- **P1/P2 確認產品缺口**：兩檔完全無當日已物化 1m，另一檔缺桶。是否是排程、Provider 遲到、snapshot 入庫、cache 或取樣窗口造成，目前未定位；不得自動將 quote.snapshot 的價格塞進 K 線、也不得因資料不足直接刷新正式 Provider。

### 2.5 族群／篩選／日價（不同粒度，不能混算）

- market.sectors 09:36:01：**received 1947/1967（98.98%）**，但 directional／ranking eligible **220/1967（11.18%）**；actual_trade_unavailable 1494、provider_missing 20、valid_no_trade 233，facts_usable_for_ranking=false。這是 rolling/stock-state 視圖，非 2.1 的單輪 breadth。
- market.sample_ranking：status=partial，依最新本機 completed daily sample；全市場日價抽樣警告為 **1931/1973**，不是完整市場統計，不能宣稱排行榜已全量。
- screening.coverage：**1800/1967**，status=partial，as_of=2026-10-15（已完成交易日）；其意義與 current-session breadth 不同。
- 3324 daily.ohlcv 最新資料日 2026-10-15、coverage_status=complete，這筆個股 completed daily 並未壞；10/16 盤中未有當日日線最終版是正常 release-window 限制。歷史 TPEX 特定日期 official daily 遲到的 G6 風險 **本輪未重驗**。
- **P2 downstream risk**：依部分樣本產出的族群排行、熱門股、漲跌分布及篩選，如果消費端忽略 coverage 會造成看似完整的結論；目前 omi.ask 已如實標 partial，此保護需繼續維持。

### 2.6 已通過／不應誤判為故障的功能

- **正式 Runtime**：Launcher 51376、Backend 42568（啟動 10/15 22:37:40 台灣時間）、Frontend 47688；8400 readyz HTTP 200，Runtime/DB OK。服務有重啟且能讀 DB；不等於所有 G7 source 已逐模組載入驗證。
- **台股指數**：market.indices 約09:38，TAIEX（fugle_indices_stream）與 TPEX（twse_mis_index_snapshot）皆 status=ready、is_current=true、coverage=complete、decision_usable=true。指數 Data Lane 本輪 **PASS**，不應和全市場廣度一起判失敗。較早 Workspace Header 曾出現 Fugle 前收 lineage 警告，但此輪 index items 無對應故障證據，列為觀察不升級 Defect。
- **價格安全**：stale/missing 現價不升格、試撮與有效成交分流、session-close confirmation 的既有 G5/G6 source 契約保持。
- **G7 Source**：四個 provider/internal-contract 檔案 SHA-256 與 G7 測試 checkpoint 完全相符，磁碟修改早於新 Backend 開機；受影響回歸歷史結果為 159 passed、architecture PASS、隔離 HTTP 7 回應 PASS。不得以此宣稱正式 G7 per-batch 行為百分之百驗收。

## 3. 待處理問題分級與 Owner

| ID | 分類／優先序 | 現況 | 正式 Owner／追查位置 |
| --- | --- | --- | --- |
| TW-101 | Confirmed Defect（市場功能可用性）P1 | MIS batch timeout/20s budget exhausted，單輪收到數劇烈波動 | backend/app/market/providers/twse_mis_current_breadth.py；twse_mis_breadth_evidence.py；twse_mis.py |
| TW-102 | Confirmed Defect（有效成交價可用性；上游原因部分已知）P1 | top-level z 大量缺值；有量不能當有價；滿批次也只有少量方向可判 | backend/app/market/twse_mis_observation.py；tw_market_breadth_contract.py；Canonical/Resolver |
| TW-103 | Confirmed Defect（單股即時查價可用性）P1 | 3324/2883/2330 的 current_price=null，安全降級正常但 Live Quote 無法決策 | backend/app/market/quote_depth.py；public_quote_repository.py；AI quote.snapshot |
| TW-104 | Confirmed Defect（本次 1m chart 缺失／部分缺桶）P1/P2 | 3324/2883 缺當日 snapshot，2330 partial_prefix | backend/app/market/tw_intraday_capabilities.py；tw_bar_service.py；nstock provider／materializer |
| TW-105 | Confirmed downstream coverage risk P2 | 族群／排行榜／篩選只覆蓋部分有效價格或 completed daily sample | market.sectors；market.sample_ranking；screening.coverage；tw_intraday_state.py／AI projection |
| TW-106 | Unverified / Architecture Risk P2 | G7 typed timeout_origin/stage 未在 Canonical 摘要暴露，不能證明 runtime in-memory adopted | tw_breadth_acquisition_contract.py；tw_current_market_repository.py；Runtime loaded-source attestation |
| TW-107 | Historical Observation P2 | 10/15 盤前 breadth 可看到 indicative，但單股 quote.auction unavailable；10/16 未重演 | taiwan_quote_evidence.py；quote_depth.py；quote.auction |
| TW-108 | Historical Observation P2 | G6 曾記錄特定 TPEX official daily 延遲／歷史 K 缺口；10/16 個股 daily 已可讀，整體未重驗 | daily_price_repository.py；EOD materializer／provider publication |
| TW-109 | Observation P3 | Runtime Control bundle disk_matches_import=false / loaded_release_identity=UNATTESTED；不是已確認台股 market data bug | Backend runtime-control 及正式 launcher；別將 Control bundle 差異當成 G7 未載入證明 |

優先順序針對可用性影響，而非表示每項均是已證實的本機 Source Bug。TW-102 的 provider 缺 z 是已確認現象，但 upstream 為何不給／是否有官方等價來源仍待調查。TW-104 的缺 materialization 已確認，但根因尚未確診。

## 4. 為何 G6/G7 測試通過，正式盤中還是失敗？

1. **Source PASS ≠ Live 資料充分**：G6 的游標 rotation / session separation、G7 timeout 分類是局部契約；它們既不控制 TWSE MIS 頂層 z，也不消除網路慢批。
2. **Acquisition complete ≠ Market decision-ready**：收到 1074/1080，仍僅 91/1080 有有效方向（09:29:53）。成功收據內可包含缺價／未交易／試撮。
3. **不同 Consumer 來源不同**：market.breadth 單輪、market.sectors rolling state、quote.snapshot 單股、intraday.bars nstock、daily.ohlcv 官方 completed session、market.indices 指數，不可用單一 freshness 指標代替。
4. **讀取保護沒有失效**：omi.ask cache_only／refresh_off 沒有自行補資料；null、partial、stale 是可信的不足揭露。若將缺資料 fallback 為昨天收盤或 midpoint，數字看起來完整反而會破壞 Source of Truth。
5. **版本證據尚有缺口**：G7 磁碟 SHA 相符、PID 已更換，正式 loaded_release_identity 仍 UNATTESTED；本輪 Canonical 摘要沒有內部完整 batches，未讀 Raw raw_text，故不能就 timeout_origin/stage 作 Runtime PASS／FAIL 判斷。

## 5. 下一輪最小修復與驗收方案（尚未授權實作）

**R1：Acquisition（TW-101）**：沿既有 Provider／Guard／Scheduler Owner，從自然產生收據取得 batch 耗時、typed provider/caller timeout、scan 截止前剩餘秒數、transport phase 與每輪 start/next cursor；確認 60 秒實際排程、兩 venue serial lock、queue/DB commit 消耗後，才評估是否需要改 batching/connection lifecycle。不得盲目加大 quota、並行、延長無上限 timeout 或假設 HTTP 200=全部批次成功。

**R2：合法即時成交價（TW-102/103）**：用受限、公開股票樣本精確比對官方事件時間、top-level z、累積量 v、ts、received/fetched、持久化 state/lineage，辨識 Provider 未提供與 Normalize 拒絕的真正比率；如果另有同級權威 Provider 候選，必須經正式 Gateway／Resolver 品質契約採用，不在 MCP 或 Frontend 補假價。維持 15 秒 freshness 和 volume-increase fail-closed，否則回歸風險極高。

**R3：1m bar materialization（TW-104）**：定點查 nstock producer job/queue/provider receipt → normalize/bar store → tw_bar_service → intraday.bars cache-only。確認 3324/2883 09:38 仍為 0 bar 的真正成因，以及 2330 33/39 partial_prefix 缺口屬延遲還是無法補足；只在確認 owner 後使用既有 tw.refresh_intraday_bars 控制流程，不因查詢而隱性補寫。

**R4：Downstream coverage（TW-105/107/108）**：保持 market.sectors 排名不可用條件，驗證 sample_ranking、screening.coverage 的分母與 completed-session release；10/16 收盤發布後再檢驗正式日價與 TPEX publication。另於下次盤前複查 quote.auction（本輪未驗證）。

**R5：G7 Runtime acceptance（TW-106/109）**：核對正式 Backend 載入 source 身分；用既有 internal receipt access 的有界欄位檢查 timeout_origin/stage，保留 Raw Receipt 不外洩至 public MCP。不要只看 Source SHA、PID、readyz 或 Canonical 缺 key 就宣稱通過。非必要不重新啟動或重跑 159 項歷史 PASS 測試。

**R6：驗收標準**：分 Source／Runtime／Live／Product Gate；Live 至少保留三個自然輪次的兩 venue **同輪** coverage、valid trade、unknown、failed/skipped、event/received/fetched；Product 必須使用正式 omi.ask 並驗證 Quote、1m bars、indices、sectors 的顯示與 decision-usable gate。覆蓋率門檻採系統契約／資料需求，不以臨時任意百分比或跨輪 union 偽造 PASS。

## 6. 繼承紀錄與停止條件

- **可繼承**：G5/G6 價格安全、G6 失敗預算後游標輪轉、G7 Source 159 tests／架構／隔離 HTTP 的有效證據。沒有變更相關 dependency 時不重跑。
- **尚未完成**：行情取得穩定、原生 z 品質、quote current usable、當日 1m bar 完整性、sector/screening full-market decision-readiness、完整 loaded release attestation。
- **不應做**：刪庫／重建、亂調 eligibility、以 Bar/試撮代 actual、無限制刷新 MIS、任意增加 Provider concurrency、在讀取路徑偷偷 backfill、直接呼叫券商下單。
- **封版結論**：台股 Index Data Lane 本次可用；台股 Intraday Full-Market／Quote／1m Research **不建議封版**。需先解決 P1 availability 或明確降級產品功能，再執行受影響的 Live/Product Gate。

## 7. 既有相關文件

- [2026-10-12 台股盤中行情缺漏事件](TW_INTRADAY_QUOTE_INCIDENT_2026-10-12.md)
- [G6 Engineering](docs/exec-plans/active/tw-intraday-g6-20261012/Engineering.md)；[G6 Progress](docs/exec-plans/active/tw-intraday-g6-20261012/Progress.md)
- [G7 Engineering](docs/exec-plans/active/tw-acquisition-g7-20261015/Engineering.md)；[G7 Validation](docs/exec-plans/active/tw-acquisition-g7-20261015/Validation.md)；[G7 Progress](docs/exec-plans/active/tw-acquisition-g7-20261015/Progress.md)
- [現行架構](docs/architecture/index.md)；[市場時間契約](docs/architecture/MarketTemporalContract.md)

**本文件是 2026-10-16 的時間點快照。下一輪應以新的正式 Runtime／Live 收據更新，不得將歷史截圖或固定分母當作即時現況。**