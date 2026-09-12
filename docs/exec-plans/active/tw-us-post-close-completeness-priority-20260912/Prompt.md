# 台美股盤後全市場資料追齊與 MCP 個股優先處理

日期：2026-09-12。狀態：實作進行中；完整度修正及 Daily EOD 優先需求已完成 source／offline checkpoint，整體任務未完成。

## 使用者目標與已確認範圍

盤後確保台股、美股每檔股票資料追到最新；允許分批補齊。MCP 指定股票時應優先處理該股票。

使用者已確認最終範圍為「全部已支援且適用的資料集，行情先實作」，並明確授權開始實作。2026-09-12 使用者另行授權把目前全部變更整合至本機 main 並 commit，以供後續正式環境測試。尚未啟動全市場 acquisition、修改正式 runtime、套用正式 DB migration 或 push。

## 可驗證的目標

1. 台美股每個正式 universe 成員都會被盤後檢查，不依賴開啟個股頁、持倉、watchlist 或 active viewer。
2. 每個適用資料集依自己的交易日、發布時間、申報週期與 revision policy 判定最新；不是全部資料都必須有當日數值。
3. 可補的 missing／stale／partial 經 bounded batches 持續處理，保存 checkpoint，關機或失敗後可續跑。
4. MCP 明示要求取得最新或補資料時，指定 InstrumentKey 的缺口優先進入同一後端 repair control plane，並回傳可追蹤進度。純查詢不能暗中排程。
5. 所有應檢查項目均有結果；只有滿足 canonical postcondition 才標記資料已最新。上游不提供、權限不足、配額不足或不可重建不能被排除後冒充全數完成。
6. Frontend、API、MCP、AI 共用 coverage、freshness、limitations 與任務狀態，保持 `omi.decision.v4` 單一 outward contract。

## 最新資料的定義

| 類別 | 盤後完成條件 | 不得混淆 |
| --- | --- | --- |
| Daily OHLCV、official close | 對齊 market calendar 與 dataset release 所定義的 expected date，OHLCV／lineage／finalization 通過既有規則 | session close 不替代尚未發布的 official daily |
| Regular intraday 1m | 指定交易日的 canonical coverage 通過完整時槽、缺口、重複、順序與 finalization 檢查 | 收盤、有資料、最後一筆到尾盤都不單獨代表完整；不得硬編碼 390 |
| Extended hours | 依該 session 的 expectedness、provider 支援與獨立 coverage policy | Regular 完整不代表 extended 完整；沒有驗證規則時不得宣稱 complete |
| Quote／depth／auction | 保留該 session 最後合法 observation 及其時點／狀態；能否盤後取得或補回由 capability 決定 | 不承諾把盤中未記錄的歷史 depth／tick 重建出來；盤後不宣稱 live |
| 籌碼、財務、SEC、持股、公司事件等 | 對齊各 dataset 最新應發布期間／版本，完成適用性、有效空值與 revision 檢查 | 無新申報不等於 missing；事件無發生不等於 provider 無資料 |
| 技術與研究衍生結果 | 僅在來源 evidence revision 改變後由既有 owner 重算，帶入輸入品質 | 不直接抓 provider，不把 partial 升格 usable |
| 外部系統擁有的資料，例如 OLA 新聞 | 使用既有正式 owner contract；追蹤其更新與可用性，只有其明示提供的 refresh action 才能委派 | OMI 不直接抓另一套新聞來源或寫外部 owner DB |

表格是需求分類，不是 capability inventory。正式資料集、支援能力與適用性必須從 executable registry／catalog 導出；M0 再核定具體納入表。

## Universe 與涵蓋率

- 沿用台股與美股正式 instrument master 的 active／eligibility owner；以 market、venue、instrument type、symbol 的 canonical identity 去重。上市、上櫃、美股交易所與 ADR 不靠 ticker 字串猜測。
- 每輪保存 universe snapshot／revision 與 expected date；新增上市、下市、停牌、代碼變更按生效日期處理。active 的精確判斷由既有 owner 決定。
- 本任務以股票為全市場完成目標；現有 ETF、index 等能力不得回歸，但不可暗中混入股票分母。
- 停牌不代表所有資料集不適用。每個 dataset 分別判定 required／pending release／not applicable。
- 儀表需同時揭露全 universe、適用、到期、最新、partial、stale、missing、blocked、not applicable、pending release，避免縮分母得到假 100%。
- 「所有項目已檢查」與「所有到期資料均已最新」分開驗收。blocked 可以有原因，但不算資料完整。

## 邊界與限制

- 共用流程：Provider → Canonical Observation → Resolver／Control → Market／Research → AI／API → Consumer。
- GET、cache-only MCP 與一般讀取不得 provider IO、DB 市場資料寫入、修復或 enqueue；包含只提升 priority 的 queue mutation 也不能藏在讀取裡。
- MCP 最新資料流程必須經明示有 side effect 的既有 action／execution contract。後端擁有 priority、target、dataset selection、provider policy；adapter 保持 thin。
- 全市場目標擴大的是 coverage 檢查與有界盤後 acquisition；不把既有即時 materializer 改成無界全市場訂閱。
- 全市場 1m 在啟用前必須驗證 provider 歷史範圍、全市場授權、吞吐與本機容量。不可補回的資料保留缺口，不生成假 bars；無法達成時本資料集 gate 未完成。
- 不新增無界歷史 backfill。最新 expected session 優先；停機期間缺口由可設定 horizon 與 provider retention 處理，超界項目明確標記。
- 不覆蓋現有 dirty work；新 schema 走 migration，不刪除、重建或覆蓋本機 DB。
- 實作時同步更新受影響的 current architecture、typed contracts、constraint／debt 與 tests；本計畫不取代 durable truth。

## 交付與完成標準

- 交付可持續運作的全市場檢查與分批 repair、個股優先調度、canonical status projection、觀測與回退設定。
- 台美股均完成至少兩個連續已完成交易日的正式驗收，以及停機續跑、跨日 backlog、provider failure、MCP 搶先且背景不飢餓的驗收。
- 全部支援資料集分批接入；行情完成只算第一階段，不代表總目標完成。
- 無法更新項目須可定位原因、最後嘗試、下次可重試條件；重大未解缺口不能以「排程有跑」結案。
- 不在吞吐實測前承諾固定分鐘內全部完成。M0 產出每市場／資料集的 completion SLO 與容量依據；SLO 不可達需標為風險並調整來源／資源方案。

## 相關文件

- [實作計畫](Plan.md)
- [進度與證據](Progress.md)
- [架構入口](../../../architecture/index.md)
- [市場時間語意](../../../architecture/MarketTemporalContract.md)
- [產品品質門檻](../../../product/QualityBar.md)
