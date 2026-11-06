# 美股觀察名單技術研究

研究頁共用 Journal、版本歷史與呈現，市場政策由各 market owner 負責。台股 discovery 範圍、策略與排程不因美股接入而改變。

美股入口只使用啟用中的 US watchlist，依既有 symbol normalization 去重。手動指定美股也必須在該名單內。掃描凍結成員、紐約已完成交易日、知識截止時間與成員摘要；續掃延續同一範圍，移除的成員會被阻擋，新加入成員留待新掃描。空名單不退回全市場。

## 責任與資料路徑

`USDailyOhlcvPlatform.read`／`build_us_market_research` → US watchlist research policy → append-only trade Journal → HTTP research API → 研究頁。

- Market Data owner 決定 expected session、可用性、finalization、provider 選取與公司行動品質。研究層只加嚴身份、receipt、cutoff 與完整日線一致性檢查，不抓外部資料、不自行 fallback。
- US 策略以兩側各兩個完成交易日確認 pivot，近期 pivot 的實體邊緣作進場、影線邊緣作失效，兩個不同的反向 pivot 作目標。後續收盤已穿越失效點的 pivot 不再使用。不是台股 Price Map 或 F01 的別名。
- 美股金額為 USD、數量為股，預設一股。未知費用、借券、稅費與滑價保留 unknown；不套台股 tick、張數、交易稅或空單價格上限。
- `market` 與市場交易日曆隨 Journal 凍結；TW 的新增 evidence/bar market 預設欄位不序列化，既有 payload/hash 保持相容。Paper replay 驗證市場與代號一致。
- US 監控只評估最新完成日線收盤，保留品質與日曆限制，不宣稱盤中觸發或成交。US promote 在服務層直接阻擋，不進入台股 Candidate／Pending／券商流程。

## 指令與唯讀查詢

`POST /api/research/trade-proposals/us-watchlist-scan` 明確建立背景 JobRun。批次筆數、時間與名單上限由 job source 擁有。每檔獨立 transaction，保存成功後才推進 cursor；自動提案 ID 綁定市場、代號、方向、交易日、策略版本與持有期間。中斷後明確重跑不重複新增原提案。

回傳 `next_cursor` 表示仍有未掃成員；使用 `resume_job_id` 延續凍結名單。失敗不是完成，狀態 GET 不觸發重送。當 expected session 已變更時拒絕舊續掃，改由使用者明確建立新掃描。

`GET /api/research/trade-proposals/us-watchlist-scan` 保留為唯讀診斷 API，讀取最新 JobRun 與 backend-owned 排程設定、時段、狀態、下次檢查時間。研究頁不顯示排程面板或手動補掃，也不輪詢此 API。提案列表的市場、來源與方向篩選在 SQL 分頁前完成。列表、監控、歷史與 Paper GET 均不 enqueue、refresh 或改寫 Journal；前端拒絕呈現市場不符的列表／詳情。台美股候選刪除沿用 [共用 Journal 生命週期](ResearchProposalLifecycle.md)。

`ENABLE_US_WATCHLIST_RESEARCH_SCHEDULER` 預設為 `true`，可明確設為 `false` 關閉；由既有 backend scheduler 執行，與前端頁面是否開啟無關。US research schedule owner 重用交易日曆與日線發布時間，在發布窗口後 10 分鐘開始（一般紐約 16:15、提早收盤 13:15），每 10 分鐘檢查／續掃，至隔日紐約 04:00 關閉。DST、交易假日與提早收盤不在前端重做。

每個已完成交易日的凍結名單掃完後等待下一個交易日；同日失敗或未知結果不自動重播。完成與資料品質分開：有阻擋情境仍可完成名單掃描，不會因排程時刻已到就將日線升為 final。掃描不補抓 provider 資料，也不持續重掃當日已完成名單；資料補齊後由明確維護指令建立新掃描。

## 必須保留的資料限制

目前 `USCorporateActionCoverageRead` 只支援 `unknown`／`not_applicable`，沒有可證明股票或 ETF 歷史區間完整性的 producer checkpoint。因此現有實盤股票／ETF 證據會被阻擋，不能因事件表為空、已有部分事件、或有 OHLC 就升格為可產生交易價位的候選。

本次提供可驗證的市場路徑、掃描與阻擋診斷；qualified-path 測試使用明確 synthetic coverage fixture，不代表 live 市場已能產生 qualified 候選。解鎖需要 producer-owned、具區間、receipt、修訂與價格基準一致性的公司行動完整性證據，再進行 runtime/live 驗收；不得只改掉研究層 gate。

此功能不新增 schema migration 或 provider refresh。排程啟用後會透過既有 JobRun／Journal 保存研究結果；source checks、隔離 UI 驗證、runtime、live、product acceptance 分開記錄於任務執行文件，不由設定預設值推定已在正式環境運作。
