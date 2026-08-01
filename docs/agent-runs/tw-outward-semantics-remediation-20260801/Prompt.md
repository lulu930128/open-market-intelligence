# 台股對外數值語意與群族自補修正

## 背景

本長專案依據 2026-07-31 的兩份施工地圖展開：

- `OMI_2026-07-31_群族分析自補機制_工程修正對照.txt`
- `OMI_台股_數值語意與品質問題總表_2026-07-31.txt`

2026-08-01 再納入使用者整理的語意驗收報告：

- `OMI_台股功能語意驗收_2026-08-01.txt`

目前 OMI 已具備台股 market、index、watchlist、AI decision v4 與 MCP 對外表面，但部分欄位仍可能混用不同交易日、錯置 universe/coverage 語意、把複合 payload 誤判為 stale，或把樣本排行當成完整市場資料。這些問題會直接影響 AI、Frontend、MCP 與 Kuro 對同一份資料的解讀。

## 目標

建立 backend-owned、可對帳、可追溯且向下相容的台股對外資料契約，依序修正：

1. 指數 current/previous session 與 candidate 選擇邊界。
2. 市場廣度的 universe、coverage、classified、unknown 對帳。
3. 複合即時 payload 的 freshness 聚合與 sample ranking 單位語意。
4. 群族／產業共用 snapshot，避免多條路徑各算各的。
5. fill resolution、source lineage 與 volume baseline 狀態。
6. `omi.decision.v4`、MCP、Frontend 與 live runtime 的一致性證明。
7. 修正 explicit selection、日期 target、required Top-N、regulation 與
   capability inventory 的 planner／projection 語意。
8. 修正正式收盤、融資融券單位、quote availability、TAIEX bar／daily／auction
   等 public invariant。
9. 將既有 active Radar v2 以 backend-owned `watchlist.radar` 契約接入
   HTTP、AI v4、MCP 與 Frontend，不在 consumer 重算 Radar 邏輯。

## 非目標

- 不改造成自動交易或自動下單系統。
- 不新增無限制全市場 refresh、昂貴 GET side effect 或大量隱性回補。
- 不破壞 `omi.decision.v4` 既有 public envelope。
- 不讓 Frontend、MCP 或 Kuro 重做 backend 市場邏輯。
- 不重建、刪除或覆寫本機 SQLite。
- 不修改 Radar v2 scoring、factor、backtest、outcome 判定或 scheduler 寫入邏輯；
  本輪只處理既有 active v2 的公開輸出接線與契約驗證。
- 不把 EPS、營收、TTM、PE 或其他基本面資料接入 Radar v2；基本面待全市場
  coverage 與 review gate 更成熟後另案對照。
- 不修改或驗收 Kuro；Kuro 將在後續依穩定後的 OMI 契約重新製作。
- 不順手重構海外市場、財報 ingestion／normalization 或其他無關領域。
- 未經使用者明確要求，不 commit、不 push、不發布。

## 硬性限制

- 市場資料、freshness、quality、warnings、missing semantics 與 answer contract 的真相來源留在 backend。
- 現有 public interface 採 additive evolution；舊欄位若需保留，必須清楚標示相容語意。
- current-session 欄位不得混入 previous-session 數值；所有衍生值都要能指出 source 與 trade date。
- breadth 必須保留真實不一致，不能只靠 clamp 掩蓋上游錯置。
- refresh 必須 bounded、可觀測、可回報失敗。
- 目前 worktree 有大量其他在途變更；所有修改採 localized diff，不回退、不覆寫無關工作。

## 交付物

- 7/31 問題的 golden/invariant regression tests。
- canonical Taiwan index session/candidate contract 與日期隔離。
- 正確的 breadth 對帳契約與 TWSE/TPEX universe 定義。
- composite realtime 與 sample ranking 的 public quality 修正。
- market-owned 群族／產業共用 snapshot 與一致 freshness。
- fill plan resolution/source lineage、volume baseline warming/authority 狀態。
- backend API、`omi.decision.v4`、MCP/consumer projection 與正式 launcher runtime 驗證紀錄。
- 2026-08-01 驗收報告 P0/P1 的 focused invariant regressions 與局部修正。
- `watchlist.radar` 的 active v2 engine、item contract、readiness 與 limitations
  跨 HTTP／AI v4／MCP／Frontend 的一致投影。

## 完成條件

- 兩份施工地圖中的高風險數值錯誤都有對應 regression，並在修正後通過。
- current-session 對外欄位不再帶出 previous-session high/low/trade value。
- breadth 滿足 `classified_count <= coverage_count <= universe_count`；不一致時回傳 partial/inconsistent 與 warning。
- composite payload 不因 root metadata 缺失而把全數 live child 誤判 stale。
- sample-derived 能力明示樣本範圍、單位與完整性，不冒充全市場。
- 群族／產業各 consumer 讀取同一 snapshot contract。
- fill/source/volume 狀態可區分 success、no-op、blocked、partial、warming_up。
- targeted regression、safe validation、public consumer projection 與 live runtime smoke 都有可重現證據。
- Explicit required capability 不會被 NLP exclude；日期不會成為股票代號；
  required Top-N 被裁切時不得宣稱完整保留。
- Regulation 與 capability inventory 問句使用 bounded intent allowlist，不加入
  無關 capability，也不因 filter keyword 產生 unsupported target scope。
- 融資融券、quote availability、index bar／daily／auction 的 unit、availability、
  event time 與 applicability invariant 在 public v4 可對帳。
- Radar 對外結果明示 `radar_v2.0`、完整計算 universe、validation readiness
  與 limitations；不得夾帶或推導基本面分數。
