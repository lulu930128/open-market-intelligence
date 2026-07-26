# 計畫

## 里程碑

1. 契約盤點與基線
   - 範圍：確認 public targets、scope/routing、MCP、backend services、DB tables、source-health 與 dirty worktree。
   - 驗收：建立 capability matrix，標示 existing/projection-needed/provider-needed。
   - 驗證：`git status --short`、live `GET /api/ai/tools`、相關 route/schema 搜尋。

2. 既有資料的 outward targets
   - 範圍：Resource、Portfolio、Macro、US/JP/KR watchlist。
   - 驗收：public `omi.ask` 可使用 additive targets；backend/MCP schema 與 execution 一致。
   - 驗證：AI contract tests、MCP tests、bounded context smoke。

3. 既有 market context 補線
   - 範圍：KR intraday、TW cross-market、unified source-health。
   - 驗收：相應 slots 不再無條件 planned；stale/provider failure 仍可見。
   - 驗證：market context projection tests、freshness tests、read-only API smoke。

4. 台股市場廣度與衍生品趨勢
   - 範圍：市場籌碼 coverage、全市場排行契約、TXF market-chip 歷史趨勢。
   - 驗收：全市場與 OMI 樣本不混用；盤後籌碼不標成夜盤即時。
   - 驗證：market overview、market chip、futures context targeted tests。

5. 新 provider capability contracts
   - 範圍：News、Options、TAIFEX large traders/basis/term structure、TDnet、OpenDART、US options/flows/earnings、HK。
   - 驗收：每項有 target/universe、provider、credential、freshness、bounds、persistence、failure、AI slot 與 consumer 狀態；未接 provider 明確 blocked。
   - 驗證：contract/provider-failure tests，不進行未授權的大量 refresh。

6. Consumer 同步
   - 範圍：MCP、OMI Ask Dock/frontend types、必要 labels/status presentation。
   - 驗收：consumer 不重建 backend 邏輯，舊 payload 可正常呈現。
   - 驗證：MCP tests、frontend lint/typecheck，必要時 build/browser smoke。

7. 收斂驗證與交付
   - 範圍：targeted regression、safe validation、API contract inventory、Progress.md。
   - 驗收：所有完成項目有測試證據；blocked 項目有明確外部依賴與下一步。
   - 驗證：`scripts/run-safe-validation.ps1` 的最小足夠 profiles 與 bounded local smoke。

## Stop-and-fix 規則

- 新 target 若 backend、MCP 或 schema 任一處不一致，先修正再進下一里程碑。
- freshness、coverage、provider failure 或 official release window 若無法可靠判定，不得標成 ready/current。
- 任何 migration、API contract 或 existing consumer regression 必須在當里程碑修復。
- 外部 API 若需要未知憑證、付費 quota、授權或大量 refresh，停止 live fetch，改以 blocked contract 交付並記錄。
- 若 dirty worktree 的既有變更與本任務衝突，先理解並採 additive 整合，不 revert 使用者內容。

## 決策

- 採分層交付：先接 existing-data projection，再做 aggregation，最後才是 provider-dependent capabilities。
- 新 target 使用 additive enum 與既有 `omi.ai.ask.v2` envelope，不另建第二套 public AI entrypoint。
- Resource、Macro 與其他 context market 都是 watch/research-only；不提供下單能力。

## 第二階段里程碑：TAIFEX 衍生品

8. 官方 provider 與 persistence
   - 範圍：TAIFEX OpenAPI adapter、TX/TXO parser、三組資料表與 migration。
   - 驗收：單次最多五個 request、只保存當日 TX/TXO、upsert idempotent、commit failure rollback。
   - 驗證：provider/parser pure tests、migration/model contract tests。

9. Derivatives service 與 public API
   - 範圍：明示 refresh、options chain／large traders／term structure bounded GET routes。
   - 驗收：GET 無外部 side effect；filter/limit 有上限；partial provider failure 與 stale cache 可辨識。
   - 驗證：service tests、OpenAPI contract inventory、router transaction boundary。

10. AI 與 consumer projection
   - 範圍：`tw_futures` additive slots、capability readiness、MCP `market_data_params`。
   - 驗收：舊 consumer 可忽略新欄位；官方與 derived 資料、盤後時點、missing/partial 均可見。
   - 驗證：AI context、MCP schema、frontend lint/typecheck。

11. Bounded live smoke
   - 範圍：五個 TAIFEX endpoint 各最多一次、臨時 backend API smoke。
   - 驗收：資料日期、列數、source refs、freshness 與 calculation coverage 可驗證。
   - 驗證：TAIFEX current-day refresh summary 與 read route spot checks。

## 第二階段決策

- 選擇權 raw chain 與官方 Delta完整保存；AI/GET 預設只投影 ATM 附近 bounded slice。
- Greeks 不冒充 TAIFEX 官方值；只在價格、到期日與 TAIEX close 可用時以 `black_scholes_spot_v1` 衍生，並暴露 `risk_free_rate=0`、`dividend_yield=0` 假設。
- 期限結構使用正規盤月契約結算價；盤後行情不混入盤後發布的官方日結算 curve。
- 大額交易人是集中度資料，不是法人多空方向；對外同時提供 all-trader 與 specific-institution rows。

## 第三階段里程碑：對外契約完整化

12. 契約狀態核心
   - 範圍：freshness severity、slot readiness、failed/missing details、legacy compact projection。
   - 驗收：stale、empty、blocked、provider error 不再標成 ready；不可靠數值不再補零。
   - 驗證：payload contract、freshness guard、projection targeted tests。

13. TXF 語意與 payload
   - 範圍：夜盤最後成交、日 K 收盤、法人 OI、PCR、derivatives slots/compact/human answer。
   - 驗收：不同時間軸有獨立 label/as-of；盤後籌碼限制可見；data-only payload有界。
   - 驗證：futures context、answer composer、runtime `omi.ask` smoke。

14. Resolver 與模式能力
   - 範圍：US index aliases、auto target precedence、contract version validation、brief capability truthfulness。
   - 驗收：`SOX` 與 `^SOX` 等價；未知版本拒絕；無 narrative builder 的 target 不冒充 answer-ready。
   - 驗證：scope resolution、ask policy、API validation tests。

15. 廣度、排行與語意標籤
   - 範圍：TWSE/TPEX/registered/sample scope、gainers/losers filtering、相對抗跌產業、frontend labels。
   - 驗收：全市場與樣本不混稱；非正報酬不列為上漲；全負產業使用相對抗跌語意。
   - 驗證：Taiwan market payload tests、frontend lint/typecheck、必要 DOM smoke。

16. MCP 與獨立 adapter parity
   - 範圍：target enum、compact result、`include_raw`、`structuredContent`、adapter thinness、README。
   - 驗收：backend/repo MCP/外部 adapter target set 完全一致；raw flag 不再裁掉主要 result。
   - 驗證：兩套 MCP tests、live MCP protocol smoke。

17. Read/refresh ownership
   - 範圍：index/breadth cache reader、明示 bounded refresh、frontend polling owner、相容 route。
   - 驗收：純 read path 不直接呼叫 provider 或寫 DB；5–10 秒更新仍有明確 refresh owner。
   - 驗證：provider call-count、transaction boundary、API/frontend runtime smoke。

18. 全面收斂
   - 範圍：21 target contract inventory、unstable-provider failure matrix、安全 validation、Progress.md。
   - 驗收：每個 target 都有成功、partial 或失敗證據；所有 known limitation 有 consumer-visible status。
   - 驗證：最小足夠 backend/frontend profiles、bounded local runtime、diff check。

19. 盤後衍生品排程與自我壓測
   - 範圍：TAIFEX 衍生品 16:20 排程、逐資料集日期判定、SOX／夜盤語意 resolver、HTTP/MCP 反問壓測。
   - 驗收：排程只在交易日與正式發布時點後執行；stale/partial job 明確失敗；夜盤不推論法人即時加空；auto target 可辨識美股指數 alias。
   - 驗證：scheduler/job regression、完整 backend suite、32-request concurrency stress、兩套 MCP tests 與 live protocol smoke。

## 第三階段 Stop-and-fix 規則

- 任一 provider 或 freshness 狀態無法證明 current 時，不得輸出 `ready`、`current` 或數值零作為 fallback。
- 任一 target 在 `brief`、`data_only`、MCP 或 HTTP 間遺失主要 `result`，先修正 contract 再做下一 target。
- adapter 若開始推導 market semantics、target 或 refresh policy，立即移回 backend。
- 移除 GET side effect 前必須先提供等價且明確的 bounded refresh owner，避免犧牲盤中更新能力。

## 完成狀態

- 里程碑 1–19 已完成可由本機資料與既有官方 provider 驗證的部分。
- 需要新 provider、API key、授權或 quota 決策的能力維持 blocked contract，不以假資料或隱性 fallback 冒充完成。
