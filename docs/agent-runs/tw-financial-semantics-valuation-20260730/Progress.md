# 進度

## 狀態

- 目前階段：M8 一般產業 `ci` 全市場營運化已收尾；進入受控維運與後續分批擴充
- 最後更新：2026-08-01（Asia/Taipei）
- 實作狀態：M0–M8 已完成。M8 保留既有 reviewed／blocked production 結果，完成全市場 terminal-stage manifest、production canary、正式 public runtime 與資料完整性驗證；未 reviewed 標的仍不得直接 production normalization。

## 已完成

- 完成 M8 production 收尾（詳細證據見 `M8FinalReport.md` 與
  `M8ProductionManifest.json`）：
  - 正式服務停止後建立 13,144,727,552 bytes SQLite 一致性備份，SHA-256=
    `5195a3ecff894b2237edd8a8aca391362ca2b73bed524f897a29a013805cfac1`，
    full `integrity_check=ok`，revision 與主要 row counts 逐項相符。
  - 2324／3528／5902 完成 bounded official ingestion、15 個 parser v4 runs、
    390 個 statement facts、15 個 exact-hash append-only approvals 與三份
    reviewed production package；每檔建立 7 個 normalized facts，重套為
    0 create／7 reuse。
  - 三檔 public financial contract 的 normalized／derived status 均 ready，
    TTM EPS 分別為 1.33／3.11／2.16；正式 daily close 過舊時 valuation 均
    回傳 `valuation_price_expected_close_stale` 與 PE unavailable。
  - Production DB 最終 revision=`20260731_0049`；filings=3,921、parse
    runs=3,934、review events=3,939、statement facts=39,312、normalized
    facts=56；`quick_check=ok`、foreign-key violations=0。
  - 1,928 檔 final planner 分四頁 query-only 重建，stock id 無重複且每檔
    恰有一個 terminal stage：5 `normalized_ready`、1,923
    `missing_official_filings`。後者不是數值為 0，也不是已正規化。
  - Formal launcher 的 backend 8400／frontend 3000 health、readyz、frontend
    proxy、三檔 HTTP `omi.decision.v4`、stdio MCP
    `initialize -> tools/list -> tools/call(omi.ask)` 與 2324 browser 盈餘面板
    均通過；frontend 顯示 TTM EPS 1.33，並以「待有效價格」拒絕 stale PE。

- 完成 M8 第一批 clone 架構驗收（詳細結果見 `Acceptance.md`）：
  - 以固定 seed `omi-ci-acceptance-20260801-v1` 從 1,922 檔未納入既有
    pilot 的 `ci` universe 分層抽出 20 檔；樣本為 TWSE 11、TPEx 9，且
    可由同一 seed 重現。
  - 17 檔取得完整 2025Q1–2026Q1 五期 filing；3 檔因官方缺少同一報表
    scope 的必要期別而整檔 rollback，未留下 partial filing／facts。
  - 85 個 parser v4 runs、2,322 個 statement facts、85 個 current-period
    `IssuedCapital` facts 的 declared／stored count 全數相符；85 個 output
    hashes 均為 64 位且已用 exact hash 建立 append-only approval events。
  - MOPS burst soft-block 暴露後，batch 新增明示 inter-symbol throttling；
    合併報表不存在時新增 `REPORT_ID=AUTO`，只允許全期一致的 C 或 A，
    不得跨期混合 consolidated／individual scope。
  - 3528 驗證 individual A／AI2 完整路徑：第二次 evidence apply 為
    0 create／7 reuse，單季 EPS 為 2.02、-3.33、1.58、2.03、2.83，
    TTM EPS=3.11；驗收價格 31.10 的 PE=10.00。Package hash 為
    `538a4d18a66ee9c6b766394ee894d626acb102615de6515055e259a1d4314532`。
  - 20 檔最終 stage 為：1 `normalized_ready`、9
    `needs_share_basis_review`、7 `needs_action_reconciliation`、3
    `missing_official_filings`。missing／action exception 均未誤標 ready。
  - Clone full `PRAGMA integrity_check=ok`；相關 regression 45 passed。
    Production 仍為 revision `20260731_0049`、parser v4 runs=0、3528
    normalized facts=0，確認本次驗收未寫入 production。

- 建立 `CiRolloutContract.md`：
  - 定義 `ci` universe、provider、period／date semantics、request bounds、
    persistence、failure、transaction、public consumer 與 validation contract。
  - 將資料分成 raw official、machine-checkable candidate、reviewed production，
    明確禁止把 ingestion 成功等同 decision-ready。
  - 定義 missing filing、pending review、filing conflict、parser gap、share-basis
    review、action reconciliation、basis blocked 與 normalized ready 分流。

- 完成一般產業 `ci` 第一階段營運骨架與 clone pilot：
  - 從 production DB 的最新官方 bundle 以 query-only planner 重建 1,928 檔
    universe：TWSE 1,044 檔、TPEx 884 檔；income／balance coverage 均一致。
  - 新增 bounded ingestion service／CLI：單批最多 20 檔、最多 8 periods、
    明示 provider request ceiling、單檔 transaction isolation、dry-run 預設，
    並拒絕非 `ci` variant。
  - Parser 升級為 `mops-ixbrl-v4`，新增官方 `IssuedCapital` instant fact；
    production 既有 v3 lineage 不改寫，v4 只用於新 ingestion／replay。
  - Clone pilot 完成 1815、2303、2317、2324 的五期 filing、parser v4
    immutable facts 與 exact-hash review。1815／2303／2317 因發行資本變動
    自動進入 `needs_action_reconciliation`，未產生 normalized facts。
  - 2324 五期發行資本均為 TWD 44,071,466 thousand，2026Q1 正式比較欄
    的 2025Q1 EPS 0.50 與原 filing 一致；Q2／Q3 official discrete 與 YTD
    逐期對帳，通過 clone-only share-basis evidence package。
  - 2324 normalized 單季 EPS 為 2025Q1=0.50、Q2=0.11、Q3=0.45、
    Q4=0.32、2026Q1=0.45；TTM exact=1.33，annual difference=0，
    semantic／decision contract 為 ready。
  - 2324 package hash：
    `71de20065f6a7291e453350c21806240b9bfc09308f10e110df351c8331099df`；
    第二次 apply 為 0 create／7 reuse，foreign-key check 無列、完整
    `PRAGMA integrity_check=ok`。
  - Clone 的 market close 僅到 2026-07-17，落後 expected 2026-07-31；
    valuation 正確回傳 `valuation_price_expected_close_stale`、PE null，未把
    stale price 與正確 TTM 混成可用估值。

- 完成 2327 parser v3 period-scope／precision re-audit：
  - 核准 clone parser v3 runs `3928`–`3932`，同季保存 official
    `discrete_3m` 與 YTD，並以 2026Q1 正式比較欄 `2.69` 作為
    `official_restated` Q1，避免製造 `2.6925` 的假精度。
  - V3 單季為 Q1=`2.69`、Q2=`2.435`、Q3=`3.10`、
    Q4=`11.51 - 8.22 = 3.29`、2026Q1=`3.90`。
  - 2025 discrete sum=`11.515`、annual difference=`+0.005`，
    tolerance=`0.02625`、`within_tolerance=true`；TTM exact=`12.725`、
    display=`12.73`，price=`456.5` 的 PE=`35.87`。
  - Evidence package hash：
    `e46bcaed9dc264f8831ad69531d223ab0808aef60fca82ceb8f2a9c2ba94fe87`；
    第二次 apply 為 0 create／7 reuse，完整
    `PRAGMA integrity_check=ok`。
  - V2 production 的 Q4=`3.2825`、TTM=`12.7175`、PE=`35.90`
    已被 v3 supersede；immutable v2 lineage 保留稽核，但不得再作為
    現行 golden truth。

- 完成 2207 和泰車 `mim` variant 的跨業 IFRS 17 會計基礎轉換判定：
  - 核准 clone parser v3 runs `3923`–`3927`；最後一次 full
    `PRAGMA integrity_check=ok`。
  - 視覺核對 MOPS 2025Q1 PDF 第 54 頁與 2026Q1 PDF 第 11、16、
    17、73 頁；兩份 EPS note 的 2025Q1 加權平均股數同為 557,103
    千股，但歸屬母公司淨利 4,307,781→3,974,710 仟元、
    EPS 7.73→7.13，排除股數縮放並確認 IFRS 17 重編。
  - 子公司採新準則也能改變集團 EPS；basis assessment 不依主產業
    hardcode，而依合併報表正式 evidence。
  - Price=100 的反例仍輸出 TTM／PE null、
    `semantic_validity=accounting_basis_transition`、
    `decision_usable=false`。
  - Basis assessment package hash：
    `875463e282caa15e6e745e933807939cf8bc5f135355cf733116a1f0e977270c`；
    重複 apply 為 0 create／1 reuse。

- 完成 2867 三商壽 `ins` individual variant 的 IFRS 17 會計基礎轉換判定：
  - 使用 `REPORT_ID=A`／`AI2`，核准 clone parser v3 runs
    `3918`–`3922`；最後一次 full `PRAGMA integrity_check=ok`。
  - 視覺核對 MOPS 2026Q1 PDF 第 4、7、8、13、14、100 頁，確認
    2026-01-01 適用 IFRS 17、追溯重編 2025Q1、原 EPS +0.03 變為
    重編後 -0.03，以及 122,647,652 仟元期初權益轉換影響。
  - 2025Q2／Q3／annual 仍是舊會計基礎，不能與新基礎 Q1 混算
    TTM；price=100 的反例仍輸出 TTM／PE null、
    `semantic_validity=accounting_basis_transition`、
    `decision_usable=false`。
  - Basis assessment package hash：
    `f3556588accee3f01982cbcf3a181d98b1ad2f70e84bc4cee9dcc359ca73dde8`；
    重複 apply 為 0 create／1 reuse。

- 完成 2881 富邦金 `fh` variant 的 IFRS 17 會計基礎轉換判定：
  - 核准 clone parser v3 runs `3913`–`3917`；最後一批 full
    `PRAGMA integrity_check=ok`。
  - 視覺核對 MOPS 2026Q1 PDF 第 4、6、105 頁，確認保險子公司自
    2026-01-01 適用 IFRS 17、2025Q1 比較期由 3.00 重編為 -2.09，
    並另外反映 2025-10-01 盈餘轉增資。
  - 2025Q2／Q3／annual 仍是舊會計基礎，不能與新基礎 Q1 混算 TTM；
    clone contract 明確輸出
    `accounting_basis_transition_incomplete_comparatives`、TTM／PE null、
    `semantic_validity=accounting_basis_transition`、
    `decision_usable=false`。
  - 新增 additive migration `20260731_0048`、
    `TaiwanFinancialBasisAssessment`、reviewed assessment package／CLI，
    並接入 backend financial contract、schema、frontend type 與驗證工具。
  - Basis assessment package hash：
    `e251525cf290076d8cdd2ab55df1c4e43b2a792fadd9d50fa3c1b3e9bfd06043`；
    重複 apply reuse 同一 assessment。
  - Targeted tests 20 passed、72 model-contract subtests passed。

- 完成 2855 統一證 `bd` variant 與官方追溯 EPS reconciliation：
  - 核准 clone parser v3 runs `3908`–`3912`；最後一批 full
    `PRAGMA integrity_check=ok`。
  - 視覺核對 MOPS 2026Q1 PDF 第 34、40 頁與 2025Q2 PDF 第 43 頁，
    確認 2025-07-14 盈餘轉增資、股數 1,455,831 千股增至
    1,601,415 千股，以及 Q1／Q2 EPS 已採追溯後股數基準。
  - Evidence review 只在 `official_restated`、`confirmed` 且引用官方
    action document 時允許覆核 parser 的保守 restatement status；一般
    mismatch 仍嚴格拒絕，lineage 保存 parser／reviewed 狀態與 treatment。
  - Clone contract：2025Q1=-0.04、Q2=0.37、Q3=1.34、Q4=1.33、
    2026Q1=1.43、TTM=4.47；annual difference=0、tolerance=0.030、
    price=100 時 PE=22.37、status=ready。
  - Evidence package hash：
    `4225da83782cbc99a4b52c67f2fc3e466f5baf873cb02e0e8c63fa9e59baa20e`；
    重複 apply 為 0 create／7 reuse。
  - Evidence override regression 8 passed。

- 完成 2801 彰銀銀行模板與官方追溯 EPS reconciliation：
  - 修正 generic HTML DOM 解析會遺失銀行 EPS facts 的根因，parser 升級為
    `mops-ixbrl-v3`，保留 total basic EPS 並排除 continuing-operations
    duplicate。
  - 核准 clone parse runs `3903`–`3907`；舊 v2 runs 維持 rejected，
    不覆寫 immutable facts。
  - 視覺核對 MOPS 2026Q1 PDF 第 38、44、45 頁，確認 2025-08-06
    盈餘轉增資、股數 11,205,758 千股增至 11,766,046 千股，以及
    2025Q1 EPS 0.37 追溯調整為 0.35。
  - 新增 `official_restated` treatment；正式追溯比較值已反映公司行動時，
    adjustment factor 固定為 1 且仍保留 action lineage，避免二次除權。
  - financial contract 改以 `(fiscal_year, fiscal_quarter, metric_code,
    period_scope)` 選取 canonical facts，同季 `discrete_3m` 與 YTD 可共存。
  - 年度核對加入來源精度推導的 rounding tolerance，公開 difference、
    tolerance 與 `within_tolerance`，不再以固定 magic number 或 Q4 硬湊
    annual。
  - Clone contract：2025Q1=0.35、Q2=0.40、Q3=0.43、Q4=0.31、
    2026Q1=0.44、TTM=1.58；annual difference=-0.02、
    tolerance=0.02976190476190476190476190476、status=ready。
  - Evidence package hash：
    `69f48b2dbdb0d6953d0b84ac0efb86fd2ad604fdb05da3c4d3e72ef09cc9edee`；
    重複 apply 為 0 create／6 reuse，完整 `PRAGMA integrity_check=ok`。
  - Targeted regression 55 passed；`git diff --check` 通過。

- 完成 Alembic `20260730_0047` 與 ORM：
  - 新增 immutable `tw_financial_parse_run`，保存 filing、raw result、parser version、status、review status、output hash、fact count 與 diagnostics。
  - `tw_financial_statement_fact` 改由 non-null `parse_run_id` 擁有，unique key 限縮至同一 parse run；legacy facts 以 approved legacy parse run 無損採用。
  - Production migration 後為 3894 parse runs／38338 facts／0 null `parse_run_id`；最終 v2 rollout 後為 3899 parse runs／38466 facts／0 null `parse_run_id`。
- 完成 MOPS iXBRL parser v2：
  - Q2／Q3 同時保存 official `discrete_3m` 與 `ytd_6m`／`ytd_9m`，不再用 YTD delta 取代官方單季 fact。
  - Parse output 採 canonical hash；新結果預設 pending，只有精確 hash、fact count 與 stored facts 重新核對後才能 approved。
  - 新增 bounded、network-free replay CLI 與 explicit review CLI；production apply 皆要求 `--allow-production`。
- 以完整 12.7GB clone 驗證 `0046 -> 0047`、五份 2327 stored filing replay、人工核准、normalized evidence、contract 與 full `integrity_check=ok`。
- 歷史 v2 rollout（已由 v3 supersede）：正式 DB 五份 v2 output hash 與 clone 逐一完全一致，production parse runs 為 `3895`–`3899`；production evidence package hash=`604742e1115be6e8d150c91bbbac727fe3284a8c14c26d1355bd3f63b0040fef`。
- 歷史 v2 current-comparable 結果（只供稽核）：
  - 2025Q1=`2.6925`、Q2 official discrete=`2.435`、Q3 official discrete=`3.10`、Q4 annual residual=`3.2825`、2026Q1=`3.90`。
  - 2025 annual=`11.51`、四季離散合計=`11.51`、difference=`0`。
  - TTM exact=`12.7175`、display=`12.72`；price=`456.5` 的明確 validation snapshot 才產生 PE=`35.90`。
  - 舊 v1 與 v2 TTM 數值碰巧相同，是 Q3 的 `+0.0075` 與 Q4 annual residual 的 `-0.0075` 相抵；舊 lineage 仍維持撤銷，不因結果相同而復權。
- 建立第二層 production data-change backup：
  - `data/backups/open_market_intelligence-before-tw-financial-parse-run-v2-20260731-003629.db`
  - 大小與正式 DB 相同、revision=`20260730_0047`、3894 parse runs、38338 facts、`quick_check=ok`。
- v2 正式 runtime 歷史驗證（source 與 golden truth 已過期，最終需重跑）：
  - Backend health／ready、frontend `/omi-ui-health`、launcher-selected `8400`／`3179` 均正常。
  - HTTP financial contract、public `omi.decision.v4`、HTTP MCP session `initialize -> tools/list -> tools/call(omi.ask)` 均回傳相同 v2 lineage；MCP `isError=false`。
  - Frontend 2327 盈餘頁顯示 TTM `12.72`、最新單季 `3.9`、Q2 `2.44`、Q3 `3.1`、Q4 `3.28`；來源 YTD／FY 表格仍獨立保留，PE 在沒有有效 price snapshot 時顯示「待有效價格」。
- 讀取使用者提供的台股財務語意與估值修正規格。
- 對照 repo product direction、backend architecture 與 market capability contract。
- 盤點 `financial_metric_quarterly`、financial parser、history backfill、service、API schema、AI context 與 frontend earnings projection。
- 以 2327 live API 與 read-only SQLite 查詢確認：
  - 來源 EPS 混合第一季、半年、前三季與全年累計語意。
  - Frontend 季度顯示及年度加總存在錯誤。
  - AI fundamentals 在缺乏期間／股本正規化時仍可能標為 ready／usable。
  - 2026 年 5 月營收為內部缺期，但 latest-key freshness 無法偵測。
  - 台股 corporate events 無法完整表達面額變更。
  - Quote／daily date fusion guard 只覆蓋部分 public contract。
- 建立本長專案的 goal、non-goals、hard constraints、milestones、done criteria 與 stop-and-fix 規則。
- 確認目前 worktree 有大量既有未完成變更，且與未來會修改的 model、AI projection、frontend type 檔案重疊；本階段不觸碰這些變更。
- 建立 `FinancialDataContract.md`，定義 versioned raw facts、日期、期間、單位、公司行動、正規化、衍生指標、品質與 public envelope。
- 建立 `SourceSemanticsMatrix.md`，盤點 TWSE／TPEx OpenAPI bundle、MOPS 歷史頁、月營收、financial variants 與公司行動來源。
- 建立 `GoldenCases.md`，將國巨 `12.7175` 明確列為需通過 filing-level EPS／denominator reconciliation 的候選值。
- 確認 MOPS 2025 歷史財報頁明示財務金額單位為新台幣仟元。
- 確認 TWSE financial OpenAPI raw result `50065` 的十二個 entries、所有公司及 variants 都使用相同 `出表日期=1150727`，不具 company release date 語意。
- 確認國巨 2025 財報 revenue 與月營收 YTD 在 Q1、Q2、Q4 完全相同，Q3 僅差 2 仟元，足以證明來源為 duration cumulative facts。
- 將 IAS 33 對股份分割／反分割的 EPS 追溯調整要求納入 double-adjustment 防護。
- 取得國巨 2026Q1 filing evidence：
  - 2025-08-22 為股份重新發行基準日，面額 10 元改為 2.5 元。
  - 2025Q1 basic EPS 由 10.77 追溯調整為 2.69。
  - 比較期 basic weighted-average shares 為 2,053,044 仟股。
- 曾將國巨候選 TTM EPS 設為 `12.72`、price=456.5 時候選 PE `35.90`；2026-07-30 後續 official discrete-quarter context 證據已推翻其 production golden-truth 資格，現為 disputed historical candidate。
- 建立 `financial_metric_semantics.py`，對 legacy rows 加上 YTD／annual、月份、raw EPS、share-basis、normalization、valuation 與 warning 語意。
- API `FinancialMetricQuarterlyRead` 以 additive fields 維持相容；未正規化資料標為 `raw_only`／`blocked`。
- AI fundamentals 對 source-reported EPS 改為 neutral、partial，明示不可直接推導單季、TTM 或估值。
- Frontend earnings 年度檢視不再加總 Q1/Q2/Q3/Q4；採 Q4 annual 或最新 YTD，並停用未正規化的 YoY、ROE、ROA 比較。
- 新進 OpenAPI financial rows 不再把 `出表日期` 寫入 `report_date/released_at`。
- M2 建立 `tw_financial_filing`、`tw_financial_statement_fact`、`tw_financial_corporate_action`、`tw_financial_normalized_fact` 四個版本化語意資料表。
- 新增 Alembic `20260730_0045_tw_financial_semantic_storage`；不修改或取代 legacy `financial_metric_quarterly`。
- 以 SQLite online backup 建立 production clone，從 migration `0043` 升至 `0045`；主要 legacy row counts 保持一致，`integrity_check=ok`、foreign-key violations=0。
- M3 建立 Decimal 正規化核心：公司行動 adjustment chain、double-adjustment guard、current-comparable、as-reported-as-of/no-lookahead、單季 EPS、四季 TTM、PE snapshot、annual reconciliation 與平均分母 ROE／ROA。
- 正規化引擎曾重現候選 TTM EPS exact=`12.7175`、display=`12.72`、price=`456.5` 時 PE=`35.90`；此項只證明公式可重現，已不代表來源語意正確。
- M4 建立 bounded、dry-run-first、caller-owned transaction backfill；production apply 需額外 `--allow-production`。
- Clone 全量 dry-run 3883 筆 legacy rows：可投影 3883 filings／38148 raw facts；因 known-at、consolidation、share basis、restatement 未知，全部維持 normalization blocked。
- Clone 對七檔代表股套用 raw backfill：87 filings／837 facts；第二次執行新增 0 筆，證明 idempotent。
- 建立 backend-owned 月營收 continuity contract；2327 明示 `monthly_revenue_missing_2026_05`。
- M5 建立 `omi.financial.v1`，包含 `as_reported`、`normalized`、`derived`、`valuation`、`quality`、`source_refs`。
- 新增 `GET /api/market/financials/{stock_id}/contract`；支援 current-comparable 與 as-reported-as-of。
- 價格與 `price_as_of` 必須成對提供；AI 只採用帶時間／來源且非估算的 resolved trade price，拒絕 order-book midpoint estimate。
- AI compact fundamentals 與 frontend earnings panel 已接入版本、blocked 狀態及營收缺期警告。
- 建立 `omi.tw-financial-evidence.v1` 審核證據包與 dry-run-first CLI；來源事實值變動、正規化值不符或 lineage 衝突時會拒絕套用。
- 2327 clone-only 證據包已完成 dry-run、apply 與第二次 apply：
  - 第一次新增 1 source、1 corporate action、5 normalized facts。
  - 第二次新增 0、重用 5 normalized facts，`integrity_check=ok`。
- Clone 內既有 MOPS raw cache 已補回 2026/05 月營收 15,058,220 仟元；未發出額外網路請求。
- Clone HTTP 曾以舊 parser／evidence package 得到 normalized／TTM／valuation ready；該結果已由 stop-and-fix 證據判定失效，不得再作為 production approval 依據。
- AI compact fundamentals slot 在 normalized backend contract 可用時改為 ready；舊 raw row 仍保留 `raw_only` 來源語意。
- `fundamentals.financials` capability 已 additive 公開 `financial_contract`，並以 normalized period limit 保持 payload bounded。
- 已重新產生 MCP public contract snapshot，digest=`1012f22131f59185e0b8e739923196a8e1ff0c007749b308ab4d5b00c25819a5`。
- MCP stdio 曾以舊 evidence package 帶出 TTM 12.72、semantic valid／usable；此為歷史驗證紀錄，2026-07-30 已撤銷，不代表目前 public contract。
- Production DB 全量 raw semantic dry-run：3883 legacy rows 可投影 3883 filings／38148 raw facts；3883 筆均因 known-at、consolidation、share basis 或 restatement 不足而禁止 normalization。
- 寫入 production 前已建立 SQLite online backup：
  - `data/backups/open_market_intelligence-before-tw-financial-semantics-20260730-124324.db`
  - `quick_check=ok`、revision=`20260730_0046`，legacy financial rows=3883、monthly revenue rows=9860。
- Production raw semantic backfill 已套用：3883 filings／38148 raw facts；duplicate filing keys=0、duplicate fact keys=0、normalized facts=0、corporate action facts=0。
- 月營收期間修復新增 cache-first、dry-run-first、bounded fetch、content-hash versioning 與 business-field revision comparison；production apply 仍需 `--allow-production`。
- 修復 2026/05 月營收全市場內部缺期：
  - 第一批由既有／bounded MOPS documents 補 1953 rows。
  - refreshed official documents 再補 7 rows並修正 2 筆來源修訂值。
  - 2026/04→05→06 內部缺期由 1960 降為 0，duplicate rows=0。
  - 重跑 refresh 顯示 documents unchanged、candidate=0，證明內容版本與寫入皆 idempotent。
- 市場轉換案例 5236 同時保留 period market=`TPEX` 與 source provenance=`TWSE`，避免以目前上市市場改寫歷史期間語意。
- 2327、2330、2801、2855、2881、2867、2207 live contract 均顯示營收 continuity complete；normalized／derived 仍依 production evidence 狀態 blocked。
- 修正 AI quality 判定：raw／blocked 財務資料只允許 facts usable，decision usability=false，整體為 partial／limited。
- 修正 formal launcher 對 stale frontend/backend process 的採用判斷；正式 launcher 已重新啟動目前 backend source，backend health 與 frontend dashboard 均正常。
- Formal runtime AI 2327 實測：`omi.decision.v4` completed、`fundamentals.financials` partial／limited、facts usable=true、decision usable=false、revenue continuity complete。
- Formal runtime frontend 盈餘面板實測顯示 `omi.financial.v1` blocked、`3M YTD`／`FY` source scope，且不再顯示 2026/05 缺期警告。
- Formal runtime MCP stdio 實測 `initialize`→`tools/list`→`omi.ask` 成功，`isError=false`；v4、financial capability、blocked normalized state、complete revenue continuity 與 public digest 均保持一致。

## 驗證證據

- Parse-run v2 targeted regression：43 passed、71 subtests passed；僅既有 pytest cache 權限與 SQLite reflection warnings。
- Backend `compileall backend/app`、frontend `tsc --noEmit --incremental false`：passed。
- Production rollout 後 full `PRAGMA integrity_check=ok`、revision=`20260730_0047`、3899 parse runs、38466 facts、0 null `parse_run_id`。
- Production HTTP contract：annual `11.51` = discrete sum `11.51`、TTM exact=`12.7175000000`、semantic validity=`valid`、decision usable=true、source parse runs=`3895`–`3899`。
- Public AI／MCP：`omi.decision.v4`、quality=`ready`、`fundamentals.financials` current／complete／facts usable／decision usable，MCP transport `isError=false`。
- `GET /api/market/financials/2327/history?limit=20&ensure_history=false`：確認來源期間數值。
- `GET /api/market/revenue/2327/history?limit=24&ensure_history=false`：確認 2026/05 內部缺期。
- `GET /api/market/quote-depth/2327?refresh=false` 與 technical API：確認日期融合風險。
- `GET /api/ai/stocks/2327/context?...payload_level=compact`：確認 fundamentals slot 語意缺口。
- `GET /api/market/tw-corporate-events/history/2327?years=3&limit=200`：確認事件類型缺口。
- `pytest` targeted semantics／fusion tests：2 passed。
- Read-only SQLite source inventory：TWSE／TPEx monthly revenue 與十二類 financial bundle endpoints 均已對應 source registry。
- Raw results `5266`–`5269`：各有兩處「單位：新台幣仟元」及 EPS per-share label。
- Raw result `50065`：十二個 financial entries 的 output-date set 均只有 `1150727`。
- 國巨財報／月營收 reconciliation：2025Q1=0、Q2=0、Q3=2、Q4=0 仟元差異。
- 國巨 2026Q1 filing Note 23／26：確認 4 倍股數基準、追溯 EPS 與 denominator。
- Targeted backend regressions：42 passed。
- Frontend `tsc --noEmit --incremental false`：passed。
- Frontend targeted ESLint：passed。
- 實際執行 `buildEarningsSeries`：2025 annual=11.51、2026 latest YTD=3.90、2025Q2 label=`6M YTD`。
- M2 model／migration contract：7 passed、68 subtests passed。
- M3 normalization：8 passed。
- M4 backfill／continuity：7 passed。
- M5 financial contract／normalization／semantics：23 passed。
- M5 AI market projection／API inventory／public v4：38 passed、36 subtests passed。
- M5 frontend typecheck：passed。
- AI capability contract：49 passed、12 subtests passed。
- AI payload／ask stages：16 passed。
- AI answer composer／MCP adapter：55 passed、2 subtests passed。
- Frontend targeted ESLint：passed。
- `git diff --check`：無 whitespace error；僅既有 LF→CRLF warning。
- 完整 migration suite 仍有一項共享 worktree 的 `0044` downgrade 失敗；本任務 `0045` isolated upgrade／downgrade 已通過。
- 月營收 backfill／continuity／job retry：23 passed。
- 月營收最新版／continuity／financial contract：19 passed。
- 新增 backfill scripts 與 modules compile：passed；因既有 `scripts/__pycache__` 權限，使用 `.tmp` `PYTHONPYCACHEPREFIX`，未修改 production data。
- Production DB backfill 前後 `quick_check=ok`；月營收缺期與 duplicate 查詢均為 0。
- Formal launcher log 證明 stale backend 已停止並載入目前 source；backend API 與 frontend root 均回應正常。
- 最終財務契約／正規化／evidence package／storage／月營收 continuity／MCP targeted regression：76 passed、2 subtests passed；僅因既有 `.pytest_cache` 權限產生非功能性 warning。
- 已確認 TWSE 官方說明：台灣自 2010Q2 採 XBRL、2019Q1 採 Inline XBRL。
- 已以 MOPS 官方 2327 2026Q1 iXBRL 驗證：
  - raw bytes SHA-256=`12aa2a875375fb16733e11b313456b7b3ba95e933757402c2656dc838dd22bc9`。
  - current basic／diluted EPS=`3.90`／`3.89`，2025Q1 comparative=`2.69`／`2.69`。
  - context、unit、concept、decimals、scale 與比較期間可機器解析；頁面須依 `big5`／`cp950` 解碼，不能相信內嵌 XML UTF-8 declaration。
- 已確認 MOPS 電子文件目錄 `202601_2327_AI1.pdf` 的公開上傳時間為 2026-05-15 14:25:09 Asia/Taipei；`known_at`／`filed_at` 採此公開時間，不以董事會通過日冒充市場可知時間。
- 已下載並視覺核對官方 PDF，SHA-256=`8493a24d6ef0640b364d92765420340f0c8c29d010026528b13effd6bb1142be`：
  - 附註 23 證實面額 10 元改為 2.5 元、換股基準日 2025-08-22，調整比率 4。
  - 附註 26 證實 2025Q1 basic EPS 由 10.77 追溯調整為 2.69，basic weighted-average shares 為 2,053,044 千股。
  - generic `tifrs-notes:NumberOfShares1` 在 iXBRL 中有多筆，不能靠 concept 名稱猜測 weighted-average shares。
- 建立 MOPS official filing provider、iXBRL parser、caller-owned ingestion service 與 explicit dry-run CLI：
  - iXBRL raw bytes、decoded HTML、content hash、context／unit／scale／decimals、document id、公開上傳時間與 parser version 全數保存。
  - GET/read path 不觸發 filing refresh；CLI 單次最多 8 periods，production apply 需 `--allow-production`。
  - Windows CLI stdout 固定 UTF-8；`correction_status=無` 不再因 console code page 顯示假性亂碼。
- 2327 official filing ingestion 已完成 2025Q1–2026Q1 共 5 filings／100 canonical facts：
  - official evidence package hash=`f3d0d340025d8afaf422e72e91d299dae94d459c7bc7498914bfd7683c15c870`。
  - current-comparable normalized facts 5 筆、corporate action 1 筆；重跑新增 0、全部 reused。
  - SQLite timezone 邊界已修正為 UTC persistence；2026Q1 public `known_at=2026-05-15T06:25:09Z`。
- Production 2327 曾完成 ready 狀態的 public contract／AI／MCP／frontend 驗證，但該 approval 已正式撤銷：
  - 舊結果為 TTM exact=`12.7175000000`／display=`12.72`、price 456.5 時 PE=`35.90`；目前僅保留為失效的歷史證據。
  - Live 盈餘頁仍保留 source-reported YTD／FY 表格；blocked contract 不再渲染正規化摘要。
- 擴大 2026Q1 representative official filing ingestion：
  - 2330、2801、2855、2207 採一般 consolidated `REPORT_ID=C`／`AI1.pdf`。
  - 2881 文件目錄需辨識金融控股 `check2858=Y` 二段式 POST；bounded request count／limit 均為 3。
  - 2867 採 individual `REPORT_ID=A`／`AI2.pdf`；consolidation scope 正確保存為 individual。
  - 隔離 probe DB 共 6 filings／90 canonical facts，`integrity_check=ok`；2881、2867 特殊模板重跑均新增 0、raw／filing／facts 全部 reused。
- Production representative raw-layer 套用前建立並驗證 SQLite online backup：
  - `data/backups/open_market_intelligence-before-mops-representative-filings-20260730-20260730-150007.db`
  - revision=`20260730_0046`、`integrity_check=ok`、套用前 filings=3888／facts=38248。
- Production representative apply 新增 6 official filings／90 canonical facts：
  - 套用後 filings=3894／facts=38338，批次最後一次 full `integrity_check=ok`。
  - 2330／2801／2855／2881／2867／2207 public contract 均維持 normalized／TTM／valuation blocked、`unknown_share_basis`、decision unusable。
  - 2026-07-30 stop-and-fix 後，2327 與六檔代表標的均維持 normalized／TTM／valuation blocked；UI 對 blocked 標的不渲染正規化摘要。
- 最終 targeted regression：132 passed、48 subtests passed；frontend targeted ESLint、TypeScript no-emit 與 live browser 2327／2330 對照均通過。
- 已移除本任務的 12.7GB clone、9.9MB probe DB、下載 PDF 與渲染圖片；production online backup 與已保存的 source hashes／lineage 保留，可重建所有隔離證據。
- 觸發 stop-and-fix 的 official iXBRL 證據：
  - 2327 2025Q2 basic EPS 同時提供 discrete `From20250401To20250630=9.74` 與 YTD `From20250101To20250630=20.51`；`20.51/4 - 10.77/4 = 2.435` 恰與 `9.74/4=2.435` 一致。
  - 2327 2025Q3 basic EPS 同時提供 discrete `From20250701To20250930=3.10` 與 YTD `From20250101To20250930=8.22`；現行 YTD delta 為 `8.22 - 5.1275 = 3.0925`，不等於 official discrete `3.10`。
  - 現行 parser 僅接受 `months == fiscal_quarter * 3`，因此 Q2／Q3 的 discrete contexts 被排除；既有 `12.7175` TTM lineage 不完整。
  - 現行 `tw_financial_filing`／`tw_financial_statement_fact` 無 parse-run identity，同一 immutable filing 無法並存 parser v1／v2 facts；直接改 parser 後重跑會混用或衝突。
- 已完成 production 安全收斂：
  - 精確匹配 2327 normalization version 的 5 rows；原狀態為 2 normalized、3 unchanged、全部 decision usable 且 issues 空白。
  - 僅將這 5 rows 改為 `disputed`、`decision_usable=false`，加入 `official_discrete_eps_reconciliation_required` 與 `financial_parser_version_lineage_required`；filing、raw result、source fact、數值及 lineage 未修改。
  - Production DB full `PRAGMA integrity_check=ok`。
  - Backend contract 新增一般化 disputed semantic guard；targeted `test_financial_contract.py` 10 passed。
  - 正式 launcher 因 `backend source changed` 停止舊 PID 並重新啟動 backend；live health `ok`。
  - Live API 與 MCP `initialize -> tools/list -> omi.ask` 均回傳 `omi.financial.v1` normalized／derived blocked、TTM null、valuation unavailable、semantic disputed、decision unusable；MCP `isError=false`、v4 `decision_ready=false`。
  - 舊 production evidence fixture 已改名為 `fixtures/2327-current-comparable-revoked-v1.json` 並降為 `approval_scope=clone_only`，避免在新的 production DB 被誤套用；原 production package JSON 與 hash 仍保存在既有 `RawFetchResult`／normalized lineage 供稽核。
- 2327 v3 current-comparable re-audit 已完成：
  - clone canonical parse runs=`3928`–`3932`，package hash=`e46bcaed9dc264f8831ad69531d223ab0808aef60fca82ceb8f2a9c2ba94fe87`。
  - 2025Q1=`2.69`、Q2=`2.435`、Q3=`3.10`、Q4=`3.29`、2026Q1=`3.90`；annual discrete sum=`11.515`、TTM exact=`12.725`、display=`12.73`。
  - annual reported `11.51` 與 discrete sum 差異 `+0.005` 落在來源精度 tolerance 內；不改寫官方 fact。
  - clone 重套 package 新增 0、reused 7，`integrity_check=ok`。
- Backend-owned daily-close valuation resolver 已完成：
  - 只接受 `market_daily_price` 的官方、可信、有效收盤價；不使用盤中價或無來源價格。
  - 依台股交易日與 15:15 daily-close release gate 決定 expected trade date，盤後缺少預期交易日資料時不以舊收盤價冒充最新估值。
  - contract 輸出 `price_as_of`、`price_basis`、expected／actual trade date、source id／name／reliability 與 raw result lineage。
  - frontend 僅呈現 backend contract 的價格、日期、來源、basis 與 PE，不在 client 重算估值。
- Daily-close valuation targeted regression：36 passed；相關 AI／public contract regression：105 passed、48 subtests passed；frontend TypeScript no-emit 與 targeted ESLint passed。
- Point-in-time canonical parse-run review history 已完成：
  - 新增 additive migration `20260731_0049` 與 append-only `tw_financial_parse_run_review`；既有 `review_status` 保留為 current snapshot，歷史查詢改用 as-of 時點的最新 review event。
  - approve／reject／revoke 均保存 reviewer、decision time、output hash snapshot 與 reason；revoke 必須提供 reason，相同 decision 重跑不重複新增 event。
  - 後來 parser approval 或 revoke 不再改寫較早 `as_of` 的 canonical selection；current-comparable 仍使用目前核准 snapshot。
  - migration 同時覆蓋 production table-not-exists 與 baseline metadata 預先建表兩種路徑，會補缺少的 snapshot events、補 index 並逐筆驗證 seed。
- 最終財務／normalization／valuation／storage regression：55 passed；migration／model contract：7 passed、73 subtests passed；AI／public v4／MCP regression：135 passed、50 subtests passed。
- 2026-07-31 production v3 promotion 前的第一次 online backup 因正式 backend scheduler 持續寫入而無法推進，已停止該 backup process；production DB `quick_check=ok` 且未 migration／未 promotion。
  - 不完整檔案已明確改名為 `open_market_intelligence-before-tw-financial-v3-promotion-20260731-030130.db.partial-invalid` 及其 journal，禁止作為還原來源。
  - production migration 至 `20260731_0049` 與 v3 promotion 必須等待正式服務停止後重新建立、驗證完整備份。

## 2026-08-01 production promotion 與正式啟用

- 使用者關閉正式 OMI services 後，已確認 `8400`、`3000`、`3179` 無 listener，backend health 不可達，且無 launcher-owned process；備份期間沒有 runtime writer。
- 以 SQLite backup API 建立可還原的一致性備份：
  - 路徑：`data/backups/open_market_intelligence-before-tw-financial-v3-promotion-20260801-030852.db`
  - 大小：13,098,270,720 bytes。
  - SHA-256：`0DA429396349F459D71671E6BD6118AA4FC908F76726F7D48EB08846EBE86A14`。
  - revision=`20260731_0049`、full `PRAGMA integrity_check=ok`、orphan review events=0。
- 已新增 `scripts/promote-tw-financial-package.py`，只將 approved clone-only package 的 production metadata 轉換為 production scope；會重驗 Pydantic contract、輸出 source／production package hashes、拒絕覆寫，且不直接寫 DB。
- 2327 production v3 promotion：
  - parser v3 runs=`3900`–`3904`，output hashes 與 clone golden runs 精確一致；review events=`3900`–`3904` approved。
  - production package hash=`c32725ef7cd8049b8fefa8a90b3719a27f54459e20146ac2896e184c403aee90`。
  - v2 runs=`3895`–`3899` 以 review events=`3905`–`3909` revoke；事實與舊 lineage 未刪除。
  - as-of `2026-07-31T00:00:00Z` 仍選 v2；current canonical 選 v3。
- Representative production packages：
  - 2330 package hash=`78603fad343fbaa63930973c9888080c137fc8919bf4293b706e757ace55dcef`，TTM EPS=`74.39`。
  - 2801 package hash=`6bd6a0d8dcaa028f2fa76db42aefe9d2b1f4441664cebcaa613964264ff41681`，TTM EPS=`1.58`。
  - 2855 package hash=`b607a6f632f950ab589a8bbc565243ca082d3a0dba1b4c43724923ef20414ffa`，TTM EPS=`4.47`。
  - 2327 TTM exact=`12.7250000000`、display=`12.73`；2025 single-quarter EPS=`2.69`／`2.435`／`3.10`／`3.29`，2026Q1=`3.90`。
- IFRS 17 reviewed basis assessments 已 production apply：
  - 2881 hash=`dc799d6322371e0a5b5f525a24db8ecc5cfb9d502c1b1a64a2adc266db989371`。
  - 2867 hash=`2ef34c9373ba96e63761ca294fadebac48131a1d304ebd490bfbd9d88ed91fbd`。
  - 2207 hash=`fb0d25cb79fa8e553ffd91ef56d261884caf2f83d6ef64a485c358d20950af15`。
  - 三檔均為 `accounting_basis_transition_incomplete_comparatives`；normalized／TTM／valuation blocked、decision unusable，未產生猜測值。
- Production DB 最終狀態：filings=3906、parse runs=3919、statement facts=38922、normalized facts=35、review events=3924、basis assessments=3；full `PRAGMA integrity_check=ok`、foreign-key violations=0。
- 價格估值：
  - 2327 使用 2026-07-31 TWSE official close 502，PE TTM=`39.45`。
  - 2330 使用 2026-07-31 TWSE official close 2425，PE TTM=`32.60`。
  - 2801／2855 的最新本機 official close 僅到 2026-07-03；contract 正確回傳 `valuation_price_expected_close_stale` 與 PE null，沒有拿舊價冒充 7/31 估值。
- 驗證：
  - 財務 contract／valuation／basis assessment／evidence package／filing／storage／normalization：55 passed。
  - AI market projection／public v4／MCP：58 passed、8 subtests passed。
  - package promotion CLI `py_compile`、`--help` 與實際 package metadata/hash 比對通過。
- 正式 launcher：
  - `Start-OMI-Launcher.cmd` 啟動 current repo 與 `.venv`；launcher log 顯示 backend `8400`、frontend `3000`，`API OK; UI OK`。
  - `/api/system/health`、`/api/system/readyz`、`/omi-ui-health` 均為 200；readiness 的 runtime／database 均為 `ok`。
  - Live financial API 七檔均與 DB contract 一致；public `omi.decision.v4` 對 2327 為 ready evidence，對 2881 為 partial evidence 且保留 blocked financial contract。
  - MCP stdio `initialize -> tools/list -> tools/call(omi.ask)` 通過，protocol=`2025-06-18`、`isError=false`，2327 回傳 TTM=`12.73`、PE=`39.45`。
  - Browser：2327 盈餘面板顯示正規化完成、TTM 12.73、PE 39.45、官方價格日期／來源與正規化單季表；2881 顯示 blocked 與「累計 EPS 不可相加／不可做 TTM 估值」；console error/warning=0。

## 已做決策

- 將工作視為完整財務能力，而不是國巨單點修補。
- Golden result 必須可由正式來源與人工公式重現。
- 任一最終數據錯誤都觸發模型與來源重新審視，不以 UI 或 tolerance 掩蓋。
- 第一個實作 milestone 必須先做安全止血，避免錯誤資料繼續被 UI 或 AI 當成可信指標。
- Production DB migration／backfill 必須晚於 clone dry-run、API replay 與 reconciliation。
- Legacy backfill 只建立 raw facts，不因「資料有值」推定 known-at、consolidation、share basis 或 restatement。
- 財務總契約與 valuation 子契約各自表達 decision usability；不得因 TTM 可用就暗示價格估值也可用。
- 即時估值只接受具時間、來源及非估算語意的 resolved trade price。
- M7 採 provider/parser 純解析、service 擁有 DB／transaction、explicit dry-run CLI 的邊界；read path 不自動抓 filing。
- iXBRL 原始 bytes hash、解碼後原文、context／unit／scale metadata 與正式文件目錄時間都必須保存；PDF 的 short-lived download URL 不作穩定主鍵。
- parser output 必須以 immutable parse run 保存；修改 parser 行為時建立新 parse run，不得覆寫 filing identity 或在同一 facts namespace 混用版本。

## 已知問題與風險

- 一般產業規模大，不能在單一呼叫或 GET/read path 無邊界抓取；M8 必須採
  明示 batch、provider-call ceiling、單檔 transaction 與可恢復 manifest。
- 「沒有已保存公司行動」不等於「股本沒有變動」；完整 share-basis 自動核准
  前仍缺正式公司行動 coverage，planner 必須將它保留為 review gate。

- 國巨 v1 與 v2 parse lineage 均保留為 immutable 稽核證據；production current
  canonical 已由 v3 runs `3900`–`3904` 與 production package hash 綁定，舊
  as-of 仍可重現 v2。後續 parser 升版仍必須走相同 review／revoke gate。
- MOPS／TWSE 不同報表 variant 的期間、單位與日期欄位需要建立完整 source matrix。
- 台股完整公司行動官方資料源的 coverage 與穩定性尚未確認。
- 現有寬表與 statement-fact 模型採 legacy fallback；只有具完整 lineage 的 normalized rows 才取代 decision-facing 衍生值。
- 目前 branch `codex/taiwan-data-surface-v1` 有大量 dirty changes，且涉及 `backend/app/db/models.py`、AI contract 與 frontend types。
- Formal launcher 已於 2026-08-01 production promotion、full integrity 與 regression 後重新啟動；目前 `8400`／`3000` 的 health、readiness、API、AI、MCP 與 browser 證據可作為本次 rollout 的 runtime proof。
- OpenAPI financial payload 沒有逐列附 unit；正式 adapter contract 需保存 endpoint-derived unit 與 inference provenance。
- Legacy DB 既有 OpenAPI rows 仍保存錯誤的 `report_date/released_at`；目前只新增 warning 並阻止新資料繼續污染，正式清理需走 migration／clone dry-run。
- 2327 舊 disputed／v2 normalized rows 已保留為獨立稽核 records；2330、2801、
  2855 已有 reviewed normalized package，2881、2867、2207 已有 reviewed blocked
  basis assessment。未 reviewed 的其他股票仍只能使用 legacy/raw 或 blocked contract。
- 較寬 AI regression 中 `test_v4_stale_capability_returns_granular_fill_action` 受共享 worktree 其他變更影響，缺少預期 `invoke`；與本次財務／月營收 targeted regressions 隔離，後續由原變更範圍處理。

## 下一步

- M8 已無必要工作。後續擴大 coverage 時，以明示 symbol 清單執行 bounded
  official ingestion、immutable parse、exact-hash review、share-basis／reconciliation
  gate 與 reviewed promotion；不得把 1,923 檔一次變成隱性大量 refresh。
- 優先從 final manifest 的 `missing_official_filings` 依市場與報表 scope 分批，
  每批保留 provider-call ceiling、單檔 rollback、持久 audit output 與正式 runtime
  spot check；公司行動、重編或會計基礎異常仍進 exception queue。
- 另行補齊 2801／2855 的 2026-07-31 official daily close；在資料補齊前維持
  PE unavailable，不降低 stale-price guard。
- 規劃 legacy OpenAPI `report_date/released_at` 清理 migration 與完整 source
  semantics matrix；先 clone dry-run，不直接改寫 production 歷史列。
