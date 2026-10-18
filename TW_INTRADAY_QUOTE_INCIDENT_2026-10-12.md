# OMI 台股盤中行情／市場廣度缺漏事件紀錄 — 2026-10-12

> **類型**：工程健檢／待修復 Incident Record（非完成驗收報告）
>
> **檢查日期**：2026-10-12（Asia/Taipei，約 08:42–09:47）
>
> **調查範圍**：台股 TWSE／TPEX 盤前試搓切換、正式成交價、五檔快照、盤中市場廣度、族群排行、`omi.ask` 對外投影、一分鐘 K 線
>
> **狀態**：已定位多個具體問題與資料流；**尚未修復、尚未封版**
>
> **影響**：`market.breadth`／`market.sectors` 盤中統計覆蓋不足；部分 `quote.snapshot` 沒有可用最新成交價；空資料的狀態語意不精確

## 1. 結論摘要

本次問題 **不是「本機完全沒有市場資料」或「單純 MCP 畫面渲染失敗」**，而是至少涉及三個不同層次：

1. **Acquisition／Source 部分缺漏（已確認）**：TWSE MIS 全市場分批擷取發生 timeout 與 budget exhaustion，部分股票根本未取得當輪資料。
2. **正式成交價有效性缺口（已確認症狀；原始根因未確認）**：大量股票收到快照與累積量，卻無法取得符合 `actual trade` 契約的最新成交價。程式目前要求 `z` 等實際成交證據，未自動使用五檔中間價、試搓價或舊價格偽造現價；這個保護不應直接移除。
3. **狀態投影不精確（已確認）**：個股完全沒有可用快照時，可能仍透過 `_empty_response()` → `_observation_for_row(None,...)` 輸出 `AWAITING_FIRST_TRADE`，讓「來源未觀測到資料」看起來像「交易所尚未發生第一筆成交」。

另有 **跨 Capability 整合風險（待界定是否為 defect）**：個股 `quote.snapshot` 可為 null，但 `intraday.bars` 已持有同日一分鐘 K 線。兩者具有不同來源與證據語意，不可直接互補為正式即時報價；需檢查原有 Canonical／Resolver contract 是否已有適當的受控候選路徑。

**目前判斷：不建議將台股盤中市場廣度／族群排行視為通過 live acceptance。**

## 2. 2026-10-12 實際 MCP 證據

### 2.1 09:31 market.sectors／intraday rolling state

- 標的 Universe：1,967 檔。
- 本輪累積狀態記錄已接收 1,951 檔（約 99.2%）。
- 有可辨識正式漲跌方向者僅 264 檔（約 13.4%）。
- 其中約 1,485 檔被標記 `actual_trade_unavailable`。
- 金融保險業 41 檔中，收到 40 檔，但僅 4 檔可辨識正式漲跌方向（3 漲、1 平）；**不能把此少量樣本的平均變動當作金融類股指數漲幅**。
- `market.sectors` 回傳 `status=partial`／`facts_usable_for_ranking=false`，屬於正確揭露涵蓋率不足。

### 2.2 09:43 market.breadth／當輪 acquisition（與 2.1 不同快照範圍）

| 指標 | TWSE | TPEX | 合計 |
| --- | ---: | ---: | ---: |
| Universe | 1,080 | 887 | 1,967 |
| 本輪收到行情 | 399 | 491 | 890 |
| 可辨識漲跌方向 | 49 | 106 | 155 |
| 收到但 `actual_trade_unavailable` | 334 | 335 | 669 |
| 未收到 | 681 | 396 | 1,077 |
| `valid_no_trade` | 16 | 50 | 66 |

**注意**：09:31 的 sectors rolling state 與 09:43 的單輪 breadth acquisition **不是同一粒度／同一擷取時間**，不能以 1,951 → 890 推論為「資料庫一次消失 1,061 檔」，也不能混用兩組 coverage 指標。

#### 09:43 擷取診斷

- TWSE：`attempted_batch_count=5`，`failed_batch_count=1`（timeout），`skipped_batch_count=6`（budget exhausted）。
- TPEX：`attempted_batch_count=6`，`failed_batch_count=1`（timeout），`skipped_batch_count=3`（budget exhausted）。
- TWSE missing-z rescue：`candidate_count=334`，`status=skipped`，未進行第二輪補取。
- TPEX missing-z rescue：`candidate_count=335`，`status=backoff`，未進行第二輪補取。
- 此輪 `classification_diagnostics`：TWSE `ACTUAL_TRADE_PRICE_MISSING=331`、`AUCTION_INDICATIVE_ONLY=3`；TPEX 分別為 327 與 8。
- 合計 658 筆 `ACTUAL_TRADE_PRICE_MISSING`；另有 11 筆被辨識為試搓語意，均不應冒充正式成交。
- Raw lineage 例：
  - TWSE：`raw_fetch_result:683741`，snapshot `2026-10-12T09:42:41+08:00`
  - TPEX：`raw_fetch_result:683748`，snapshot `2026-10-12T09:43:06+08:00`
- `reconciliation_status=balanced` 代表分群計數相符，**不代表行情取得完整或價格可用**。

### 2.3 具體個股對照

| 標的／來源 | 觀察結果 | 判讀 |
| --- | --- | --- |
| 3324 雙鴻 `quote.snapshot` | 約 09:18 的快照有開盤 1,480、高 1,485、低 1,455、累積量 681 張；但 `last_trade_price=null`、`ACTUAL_TRADE_PRICE_MISSING`、`live_depth_only` | 收到部分行情，缺最新有效成交價；不可用五檔中間價作為現價 |
| 2881 富邦金 `quote.snapshot` | 查詢得到 `quote_time=null`、成交價／量皆 null、`AWAITING_FIRST_TRADE`，且沒有可確認的 provider attempts | 空快照不應直接被解讀為「尚未發生第一筆成交」 |
| 2883 凱基金 `quote.snapshot` | 曾有正式成交價 37.65，事件時間 09:12:01；後續查詢仍回傳舊事件時間、`delayed_current_session_trade`／stale | 有成交證據，但新鮮度不足；不能用重新查詢時間冒充成交時間 |
| 3324 雙鴻一分鐘 K | `intraday.bars`／`omi.read_tw_stock_chart(timeframe=today)` 已取得 10/12 的 `nstock_minute_stock_data`；09:46 一分鐘 bar 的 close 為 1,475 | 本機「另一資料能力」已有價格型證據，但仍屬不同來源、不同粒度；序列不完整，不可直接升格成交易所即時成交價 |

雙鴻今日一分鐘 K 讀取曾回傳 `partial_prefix`，之後呈現 `sparse`，代表仍有缺漏時間桶，需保存 coverage／revision 作為後續驗收對照。上列所有時間是當時查詢取得的證據，不是現在的即時市場狀態。

## 3. 已檢查程式位置與目前路徑

### A. 全市場 TWSE MIS 擷取

- `backend/app/market/providers/twse_mis_current_breadth.py`
  - `_fetch_messages()`：約 L181–285。分批抓取、timeout、guard、budget／diagnostics。
  - `_classify_message()`：約 L81 起。取 `z`、`v`、`tv`、`ts` 等欄位，呼叫 market-owned breadth price resolver。
  - `_rescue_missing_z()`：約 L579–685。bounded 第二輪補取，當前可見 `_RESCUE_MAX_SYMBOLS=32`、`_RESCUE_TIMEOUT_SECONDS=4`、backoff 60／300 秒。
- `backend/app/market/providers/twse_mis_breadth_evidence.py`
  - `original_message_evidence()`：保留原始訊息摘要／少量 missing-z 範例，以辨識原始欄位是否本來缺失。
- `backend/app/market/providers/twse_mis.py`
  - `fetch_stock_messages()`：TWSE MIS `getStockInfo.jsp` 來源請求。

### B. 正式成交價的 canonical 判定

- `backend/app/market/twse_mis_observation.py`
  - `resolve_twse_mis_actual_trade()`：判斷交易日、時間窗、試撮旗標、成交價與成交量證據。
- `backend/app/market/tw_market_breadth_contract.py`
  - `resolve_twse_mis_breadth_price_state()`：正式成交價與盤前試撮分流；沒有有效價時可檢查同日 cache，但累積量增加或不一致時拒絕冒充最新成交。
  - `breadth_classification_reason()`：將有量無有效價分類為 `actual_trade_unavailable`。
- `backend/app/market/tw_intraday_state.py`
  - `persist_taiwan_intraday_stock_states()`：資料持久化與 lineage／freshness。
  - `_ranking_eligibility()`：只有符合證據條件才可進入有效漲跌方向／排行。

### C. 單檔 Quote → Capability → MCP

- `backend/app/market/quote_depth.py`
  - `_observation_for_row()`：約 L438 起，重用 actual-trade resolver。
  - `_empty_response()`：約 L938 起；**空快照的 `AWAITING_FIRST_TRADE` 語意問題應從此處追查**。
  - `_row_to_response()`、`_price_semantics_contract()`：從已選行情與 freshness 推出 `last_trade_available` 等欄位。
  - `project_taiwan_quote_evidence_bundle()`：約 L2130 起，依已解析的 bundle 統一對外投影。
- `backend/app/ai/market_context/taiwan_projection.py`
  - `quote.snapshot` 的 outward 欄位映射（約 L1720 起）。
- `backend/app/ai/realtime_contract.py`
  - availability／freshness／policy 與實際價格可用性判定。
- `backend/app/ai/capability_contract.py`
  - `quote.snapshot`、`data.freshness` 等公開契約。
- `agents/omi_mcp_server/server.py`
  - Thin adapter；市場語意由 backend 擁有，不應在 MCP 修補假現價。

### D. 獨立的一分鐘 K 能力

- `backend/app/market/tw_intraday_capabilities.py`
  - `intraday.bars` 能力與 `nstock_minute_stock_data` 等 provider descriptors。
- `backend/app/market/tw_bar_service.py`
  - 今日一分鐘 K 的 coverage、缺口、`repair_recommended`；不同於 `quote.snapshot`。

## 4. 問題分類與嚴重程度

| 優先度 | 分類 | 已知證據 | 影響 |
| --- | --- | --- | --- |
| P1 | Confirmed Defect（可用性） | 本輪 TWSE／TPEX batch timeout、budget exhausted、未取得完整 Universe | 市場廣度／盤中排行覆蓋顯著不足 |
| P1 | Confirmed Defect（核心功能症狀） | 669 筆收到快照但 `actual_trade_unavailable`，其中 658 筆缺實際成交價 | 盤中個股現價與市場方向判斷不完整；**z 缺失原始原因尚未確認** |
| P2 | Confirmed Defect（語意） | 無快照路徑可呈現 `AWAITING_FIRST_TRADE` | 消費端可能把來源缺失誤解為尚未成交 |
| P2 | Architecture Risk／待確認是否缺接線 | 同日一分鐘 K 已有值但 Quote 無有效價格 | 各 Capability 證據選擇需重新對齊，**不等於允許跨來源假冒正式交易所成交** |
| P2 | Observation | 舊成交時間與新 receipt 並存且被標成 stale | 現有 freshness 防護正確，但應改善來源更新與診斷可讀性 |

## 5. 尚未驗證的根因（不得提前視為已確認）

1. **TWSE MIS 原始 `msgArray` 的 `z` 是否真的為空**：需要取 2026-10-12 有問題的實際 Raw Receipt／少量 redacted missing-z 範例，比對 `d/t/z/v/tv/ts/o/h/l/y`。
2. **是否在解析／持久化時掉值**：同一 observation 的 raw message、normalized `QuoteObservation`、`TaiwanStockQuoteSnapshot`、resolved candidate 應逐層比較，不能只看 `omi.ask` 的 `null`。
3. **TWSE 與 TPEX 是否同因**：把 timeout、來源確實缺 `z`、trial flag、TTL／backoff、parser 錯誤分開統計。
4. **正式 Runtime 是否與目前 source 一致**：需比對實際 loaded source、執行 port／PID、migration 與 `/api/ai/tools`；本輪沒有執行 runtime identity 驗證。
5. **跨資料源 candidate policy**：若一分鐘 K 可提供參考行情，需先確認 timestamp、成交性質、bar finalization、vendor limitations 及 Resolver contract，避免繞過現有 Source of Truth。
6. **是否出現過度嚴格但不必要的限制**：只有 raw→canonical→resolved 並排比較後，才能判斷是否是質量門檻錯設，不能先鬆綁。

## 6. 建議修正方向（尚未執行）

1. **先做 lineage 對帳**：固定 3324、2881、2883，對照 Raw Receipt → parse → canonical → persistent row → resolver → API → `omi.ask`，涵蓋 source event time／received time／stored time／served time。
2. **改善已存在的 bounded acquisition**：評估 batch deadline、guard、timeout、rescue 對 coverage 的影響；仍由 market/provider acquisition owner 處理，不另建平行抓取服務。
3. **保留價格證據區隔**：未驗證的五檔中間價、試搓價、上一筆成交、Vendor 一分鐘 K 不得直接覆蓋最新正式成交價。若支援替代參考價格，必須明示來源、時間、confidence 與用途。
4. **修正空快照狀態**：區分 `NO_SNAPSHOT`、`ACTUAL_TRADE_PRICE_MISSING`、已證實的 `AWAITING_FIRST_TRADE`、`STALE_LAST_TRADE`；使用既有 typed status／resolver，不在 MCP、前端另加 business logic。
5. **收斂契約測試**：驗證 `market.breadth`、`market.sectors`、`quote.snapshot`、`intraday.bars` 使用一致的事件時間／品質語意；同一來源不得因消費端不同出現兩種互斥的 market truth。

### 不應採用

- 以 bid／ask midpoint、昨收、`pz` 或一分鐘 bar close 無條件補最新 `last_trade_price`。
- 為了讓頁面正常而關閉 freshness／coverage guard 或把 `null` 當作 0。
- 在 `omi_mcp_server`、前端或 `app.ai` 偷偷獨立查 provider／DB、建立另一份 cache 或 fallback。
- 沒有 raw/canonical 對照就刪除／重建本機 DB、無界 backfill、反覆高頻打 TWSE MIS 造成 quota／provider 壓力。
- 將 `GET`／唯讀 `omi.ask` 變成隱性 refresh／資料寫入。

## 7. 後續驗收條件

- [ ] 提供至少一組真實的 2026-10-12 raw `msgArray` 與同 observation 的 canonical／DB／MCP 對照（敏感資訊遮罩）。
- [ ] 確認批次成功／timeout／budget exhausted／guard/backoff 全部可觀察，未收到資料不會誤認成功。
- [ ] 個股測試覆蓋：正常有效成交、有成交量但無成交價、真正未成交、空快照、試撮跨 09:00、stale last trade、不同 provider fallback。
- [ ] 缺成交價時仍能給出 truthful status 與適當資料限制；不得製造可執行的假現價。
- [ ] `market.breadth` 與 `market.sectors` 的 Universe／observation／directional coverage 具備同粒度 reconciliation、正確標明時間。
- [ ] 雙鴻與富邦金等案例重新以正式盤中 session 驗證，並由 `omi.ask` 直接檢查 `evidence`／quality／freshness／lineage。
- [ ] 確認 production runtime loaded source 與目前被驗證的 source／migration 一致。
- [ ] 執行針對性 backend contract、market-data architecture 與 runtime live tests，記錄結果而非僅回報「tests pass」。
- [ ] 完成前獨立 Reviewer 檢查 diff：既有 owners 未被旁路、沒有新 parallel implementation、舊 fallback 沒有留在 production 生效。
- [ ] 依交易時段與市場分別量測可靠的最低可用 coverage 基準，再決定 acceptance threshold；不得拿少量樣本平均漲幅冒充全市場。

## 8. 建議測試與回滾

**測試線索**（現有測試位置）：

- `backend/tests/test_twse_mis_observation.py`：成交價與 trial flag 判定。
- `backend/tests/test_tw_breadth_semantics.py`／`backend/tests/test_tw_breadth_convergence.py`：廣度、coverage、分類與 reconciliation。
- `backend/tests/test_tw_intraday_contract_acceptance.py`：正式成交／五檔與 intraday contract。
- `backend/tests/test_tw_quote_depth_shared_projection.py`：Quote bundle outward projection。
- `backend/tests/test_ai_realtime_contract.py`：AI realtime policy。
- `backend/tests/test_tw_backend_mcp_convergence.py`：Backend／MCP 語意一致性。

需要修改時，請採**最小範圍**並保留上一版的 source／runtime 驗證紀錄。若正式 session 出現 regression，回滾相關 source／config 至已驗證版本，保留 raw receipts 與診斷資料，之後重新測試；不得直接清除歷史資料或破壞 schema。

## 9. 本次操作與 Git 狀態

- 本輪操作只包含實際 MCP 唯讀查詢、Project Workspace 唯讀程式檢查，以及**新增本 Markdown 紀錄**。
- 沒有修改 backend／frontend／MCP 原始程式、沒有重啟 OMI、沒有提交或推送 Git。
- 建檔前 `main` 分支已存在與 KGI execution simulator 相關的既有工作樹修改／未追蹤檔案，本次**不動這些項目**。
- 本文是 **2026-10-12 調查快照**，不是持續更新的 runtime health／canonical inventory。未來以實際 Source、Raw Receipt、Runtime 與再次檢測結果為準。


## 10. 工程修復 checkpoint（2026-10-12 12:35 +08:00，追加）

本節追加於原始調查紀錄；原文保留，不將先前「未修改程式」的操作範圍當成本節範圍。

- **G0 PASS（樣本範圍）**：4 筆歷史 breadth receipts 的 81 個 parsed-original missing-z samples，以及代表股 9 筆 quote 完成 offline replay，exit 0。頂層 z 缺失在 provider parsed-original 已存在，沒有 parser 丟掉正數 z 的證據；receipt 與成交時間分離。3324／2883 nested trade 保留為待 qualification 線索，不用來補 current exchange last trade。2881 無 snapshot。
- **G1 PASS（source／隔離）**：保留最後確認成交的原始 price_as_of／lineage，分開 current_price_verified。量增加／缺量仍拒絕 current price；session_cache 即使 verified=True 也不取得新時間。Negative tests 證明 stale price_decision_usable／execution_grade_usable 為 false。
- **G2 PARTIAL**：既有 provider cache 保存有界 rolling scan cursor；TWSE／TPEX 各三輪 600-symbol fake-clock 測試通過，每輪僅 200 收到，沒有把累計覆蓋假裝成單輪完整。維持 deadline／slot／guard／backoff；真實 session 的全市場改善尚未驗證。
- **G3 PASS（source／隔離）**：NO_SNAPSHOT／unknown 由 observation owner 提供，known-zero-trade 與 auction 保持不同。market/API／AI 同步 cap stale price；合法 session-final／official close usability 由 market owner 保留，不以 price_available 泛用 fallback。Breadth job 的 derived market-minute／stock-state 原子提交，index job 保持原提交，rollback negative tests 通過。
- **G4 PARTIAL**：完整 targeted 241 passed／exit 0，追加 lineage 20 passed／exit 0；architecture PASS（15 actual／15 declared）／exit 0，syntax／diff check exit 0。修補 candidate 使用獨立 DB，5 GET＋4 ask HTTP 200，語意斷言與 4 組 adapter AST forwarding mock 通過，程序 exit 0 並已停止。兩個原始 quote-components regression tests 未修改。另一個額外 Query Planner test 失敗已證實 HEAD 與 current 相同，未延伸修改。

四軸狀態：

| 軸 | 狀態 |
| --- | --- |
| Source | 本次 targeted source 驗證 PASS；main 保持 dirty，沒有 commit／push。 |
| Runtime | 修補隔離 candidate PASS、有 loaded source hashes；正式 8400 仍 PID 67220，未重啟／未採用修補，不能宣稱封版。 |
| Live | BLOCKED：两次限量 MIS 呼叫 transport_error；一次後續 DNS/TCP 診斷為 DNS resolved／WinError10013，沒有 HTTP retry。這是本機網路存取 blocker，不能當成 vendor latency 證據。 |
| Product | PARTIAL：隔離 HTTP/API 契約已驗證；真實既有 MCP 僅與舊 production API 做 cache-only parity。未完成 patched MCP SDK session／全市場產品驗收。 |

Evidence 改為 bounded redacted fixture：三檔 quote＋兩個 latest breadth receipt，最多 32 raw IDs、單筆 1.8 MB／總 raw 4 MB／輸出 1.5 MB、唯讀 SQLite 與 15 秒 deadline。實際輸出 902,920 bytes；歷史兩份大 evidence 已縮為 103,029／80,995 bytes。沒有 production DB 寫入或使用者資料刪除。KGI WIP 11 檔 SHA-256 未變，本文原始 bytes prefix 保留。

完整 Gate、失敗收據、source patch／manifest 與剩餘 blocker：[`docs/exec-plans/active/tw-intraday-20261012/Progress.md`](docs/exec-plans/active/tw-intraday-20261012/Progress.md)。此 task 目錄受既有 git ignore 規則涵蓋，證據已留在本機，未 force-add。任務仍標為 active／partial。
