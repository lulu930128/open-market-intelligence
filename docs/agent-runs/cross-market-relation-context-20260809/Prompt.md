# 跨市場關聯決策脈絡長專案

## 背景

OMI 目前已具備三個可以承接跨市場關聯的表面：

- 個股詳細頁已有 `OVERNIGHT` 區塊、ADR parity、匯率／外資脈絡與美股因素摘要。
- Active Radar 已是 `radar_v2.0`，並已有獨立的 `context_alignment_score`，但排序仍由技術與風險主體的 `priority_score` 決定。
- 對外主契約已是 `omi.decision.v4`，能力狀態位於 `evidence.capability_status`，能力資料位於 `evidence.data[capability_id]`；MCP 與 Kuro 應只消費這份 backend-owned contract。

現況的主要問題不是「完全沒有跨市場資料」，而是 ADR mapping、個股 profile、factor weight 與 basket selection 仍分散在程式常數或推導邏輯中；關聯缺少有效日期、證據、版本與 review 狀態，也沒有一份可同時供個股頁、Radar 與對外回答使用的 point-in-time context snapshot。

本長專案以 `OMI_Cross_Market_Relation_Architecture_Engineering_Spec_v0.1.md` 為分析基礎，並依目前 repo 現況調整施工順序。核心做法是建立一份 backend-owned 的 `cross_market.context.v1`，再由三個 consumer 做受控投影，不讓任何 consumer 重算關聯、權重、freshness 或方向。

## 最終目標

讓台股個股的海外直接等價、同業代理、產業／題材與總體背景，能以同一份可追溯、可版本化、可回放的跨市場 evidence 供以下表面使用：

1. Radar v2：顯示外部順風、逆風、反證與資料限制；通過 point-in-time 與 walk-forward gate 後，才可能進入排序實驗。
2. 個股詳細說明：延續目前 `OVERNIGHT` 摘要優先的閱讀方式，能展開 direct parity、proxy residual、bucket coverage 與 evidence。
3. 對外輸出：`omi.decision.v4`、MCP、報告與 Kuro 取得一致 structured evidence、freshness、warnings 與 data limits。

## 使用者結果

- 使用者在個股頁看到的隔夜說明、Radar 卡片上的外部脈絡與 OMI 對外回答，不會對同一檔股票給出互相矛盾的來源、日期或方向。
- 「TSM 對 2330」使用 ADR 比例、匯率與對齊後價格計算 parity gap，不以 ADR 原始漲跌幅假裝等價訊號。
- 「MU 對 2408」被明確標示為產業／景氣代理，不能被描述成已證實的供應、客戶或持股關係。
- stale、partial、limited、missing、not applicable 與 provider failure 都可見；缺資料不會被轉成中性零分。
- Radar 技術判斷仍是主體；跨市場 context 初期只做 confirmation／contradiction，不會偷偷改寫技術方向。

## 範圍

### 包含

- `InstrumentRef` 與受控 relation taxonomy。
- 第一階段以美股／USD-TWD 對台股的隔夜脈絡為實作範圍；contract 可擴充日、韓、港市場，但未接資料前不得宣稱 coverage。
- `cross_market_relation`、`cross_market_relation_evidence` 與 point-in-time signal snapshot。
- 既有 ADR mapping 的版本化 migration 與 dual-read 對帳。
- Direct parity、proxy residual、bucket aggregation、coverage 與 freshness contract。
- 個股 `overnight-impact` 的 additive 相容投影。
- Radar v2 的 batch context projection、snapshot lineage 與 display-only integration。
- `omi.decision.v4` capability registry、answer composer、MCP snapshot 與 Kuro-facing contract。
- Bounded refresh、source health、diagnostics、feature flag、shadow diff、rollback 與驗證。
- 後續 event policy、statistics 與 walk-forward promotion gate。

### 不包含

- 不把 OMI 改成猜漲跌或自動交易／自動下單系統。
- 不把美股、日股、韓股或港股提升為與台股平等的產品核心。
- 不讓 LLM、Frontend、MCP 或 Kuro 建立、核准或重算正式 relation。
- 不把新聞共同出現、名稱相似或短期相關性直接當成正式公司關係。
- 不在 GET/read path 做無界全市場下載或 N+1 provider refresh。
- 不在缺乏 point-in-time 證據時改變 Radar `direction_score`、技術 factor family、bucket 或 active 排名。
- 不以本專案順手重構所有海外資料 provider、Watchlist、財報或 dispatch。
- 未經使用者明確要求，不 commit、不 push、不發布，也不刪除或重建本機 SQLite。

## 硬性限制

- Backend 是 relation、calculation、freshness、quality、warnings、missing、source lineage 與 answer contract 的唯一真相來源。
- 台股永遠是 decision target 與產品核心；海外 relation 是 evidence/context，不建立平行的海外核心工作台。
- 對外契約採 additive evolution；保留 `/api/market/overnight-impact/{stock_id}` 與既有欄位至少一個相容週期。
- Direct relation 與 proxy relation 必須分桶；direct ADR source 不得同時以 raw return 重複進 proxy bucket。
- 所有正式 relation 都要有有效日期、evidence、verified/review 狀態與版本；A／B 級缺 primary evidence 時不得進正式計分。
- 價格／FX freshness 與 relation/evidence governance freshness 分開呈現，不得用其中一個代替另一個。
- Signal 必須帶 `decision_at`、source event time、provider fetch time、relation version、methodology version 與可用性判定，確保可回放。
- Radar 全 universe 計算只能讀同一批 snapshot，不得逐檔觸發外部 refresh。
- Missing/stale/blocked context 對 Radar 的影響必須精確等於零，且保留 limitation；不能正規化成偽高信心。
- 正式權重只由受控設定與人工 review 改變；statistics 或 LLM 最多產生候選，不直接寫入 production relation。
- 現有 worktree 有大量其他在途修改；後續施工必須 localized，實作前重查 Alembic head 與重疊檔案，不覆寫使用者變更。

## Consumer hardening 完善目標

既有 Consumer Release 已讓個股頁、AI contract 與 MCP 看得到跨市場 context；下一段工作不是擴大功能面，而是先補齊以下可信度與生命週期 invariant：

- Stock scope 只能推導 `cross_market.overnight`、`cross_market.relations`、`cross_market.parity`；market-only 的 `market.cross_market` 不得因 domain inference 被重新加入並造成 phantom unsupported／blocked。
- Caller 明確要求不適用 capability 時仍要得到 machine-readable unsupported；只有系統自行推導的 scope-invalid capability 應在診斷前被排除。
- 2408／MU 等 proxy relation 只有在可稽核的實際 review／verification 時點之後才可見；不得修改已套用 migration、任意回填過去時間，或把 migration 常數當成事實發生時間。
- `cache_only` 與 GET/read path 永遠不觸發 provider；只有明確 `allow_external_fetch` 的 AI/tool orchestration 可執行 bounded refresh，且必須同時處理所需海外價格與 FX、保留 timeout／dedupe／source-health／partial-failure。
- Latest-cache projection 與 materialized snapshot 必須是兩種明確語意；materialized payload 不得仍宣稱「not materialized」，snapshot 不可原地覆寫，且需保留 materialized time、owner、source cutoff 與 payload hash。
- HTTP、MCP、Frontend 與 Kuro 只消費 backend-owned contract；host schema cache 可要求 reconnect，但 adapter 不新增相容旁路或市場邏輯。
- 完善期間 Radar 仍是 display-only；任何 ranking、direction、priority、bucket 或 universe 影響都留在 M7／M8 的 point-in-time 與 walk-forward promotion gate 之後。

## 交付物

- Canonical `cross_market.context.v1` domain contract 與 schema。
- Relation／evidence registry、migration、maintenance command 與 audit trail。
- Direct parity v2、proxy signal engine、aggregation／coverage 與 point-in-time snapshot。
- Read-only relation/context API、bounded refresh job 與 source-health projection。
- 個股頁 `OVERNIGHT` 相容 facade 與展開式 evidence UI。
- Radar v2 display-only context 接線、shadow validation 與可選排序實驗 gate。
- `cross_market.relations`、`cross_market.parity`、`cross_market.overnight` 的 `omi.decision.v4` 投影。
- MCP/public snapshot、answer composer、報告與 Kuro consumer contract 對齊。
- Unit、migration、contract、frontend、point-in-time、walk-forward、runtime 與 rollback 證據。
- 更新後的 architecture／product 文件與營運 runbook。

## 完成條件

- 個股頁、Radar v2 與 `omi.decision.v4` 對同一 stock／`decision_at` 指向同一 context snapshot ID、relation version 與 methodology version。
- 既有 ADR parity golden cases 在 DB registry dual-read 後數值與狀態一致；比例或有效期衝突會 fail closed。
- 每個 signal 都可追溯 source、target、relation、evidence、market date、freshness、configured/effective/normalized weight 與 contribution。
- 個股 `OVERNIGHT` 仍保留既有摘要、parity、factor／basket 與 warning 語意；新欄位為 additive，舊 consumer 不會中斷。
- Radar 第一個 production release 僅新增 context snapshot、alignment、badge 與 limitation，`direction_score`、`priority_score`、bucket 與排序在 context 缺失時與基線完全一致。
- Radar 排序影響只有在預先固定的 point-in-time dataset、purged walk-forward、最小樣本與非劣化 guardrail 通過後，才可由 feature flag 啟用；預設保持關閉。
- `omi.decision.v4` 的 readiness 與 evidence 分離正確，summary／compact／full projection 不隱藏 stale、partial、limited 或 missing。
- MCP 僅透過 backend API 取得 contract，沒有 DB import 或重算邏輯；Kuro 可用 structured fields 呈現，不依賴特定中文句子解析。
- Bounded refresh、provider failure、relation evidence stale、benchmark missing、validity overlap 與 rollback 都有 regression 或 smoke evidence。
- Stock scope 不再出現 phantom `market.cross_market`；2330／2408 的 blocked、stale 或 unavailable 只可由實際資料限制觸發。
- Proxy relation 的 outward 可見時間與 audit trail 一致；forward-only 修復不改寫歷史、遇到人工異動或 seed fingerprint 不符時 fail closed。
- Materialized snapshot 可由 Radar、個股說明與 outward contract 對帳，且 payload 的 projection source、materialization metadata、hash 與限制文字互相一致。
- 正式 launcher runtime 能證明 API、Frontend 與代表性 outward request 採用新版本；不能只以 unit test 或 HTTP 200 宣稱完成。

## 參考文件

- `C:\Users\thoma\Downloads\OMI_Cross_Market_Relation_Architecture_Engineering_Spec_v0.1.md`
- `docs/architecture/BackendArchitecture.md`
- `docs/architecture/RadarV2.md`
- `docs/product/ProductVision.md`
- `docs/product/OperatingModel.md`
- `docs/product/QualityBar.md`
- `docs/product/Roadmap.md`
- 本目錄的 `Architecture.md`、`Plan.md`、`Progress.md`
