# Golden cases 與 reconciliation

## Golden truth 規則

- Golden value 必須能由正式來源文件與保存的 raw payload 重現。
- 人工計算需列出 inputs、公式、期間、單位、股數基準及 as-of。
- 不把現有 OMI output 當作真值。
- 不把規格書候選數字直接寫成測試 expected value。
- 正式來源不一致時，case 狀態為 disputed／blocked，不以 tolerance 強制通過。

## Case inventory

| Case | 目的 | 狀態 |
|---|---|---|
| 2327 國巨 | 混合股本基準、面額 10→2.5、單季／累計 EPS、TTM | v3 clone approved；v2 production 已 superseded，待受控 promotion |
| 2330 台積電 | 一般業、factor=1 控制組 | v2 clone approved；annual difference 0；TTM 74.39 |
| 2801 彰銀 | 銀行 `basi` variant、盈餘轉增資、追溯 EPS | parser v3 + clone evidence approved；TTM 1.58 |
| 2855 統一證 | 證券期貨 `bd` variant、盈餘轉增資、官方追溯 EPS | parser v3 + clone evidence approved；TTM 4.47 |
| 2881 富邦金 | 金控 `fh` variant、IFRS 17 會計基礎轉換 | parser v3 + basis assessment clone approved；TTM／PE 明確 blocked |
| 2867 三商壽 | 保險 `ins` individual variant、IFRS 17 會計基礎轉換 | parser v3 + basis assessment clone approved；TTM／PE 明確 blocked |
| 2207 和泰車 | 異業 `mim` variant、保險子公司 IFRS 17 會計基礎轉換 | parser v3 + basis assessment clone approved；TTM／PE 明確 blocked |
| 2327 月營收 | Interior gap、latest-key false ready | local gap confirmed |
| OpenAPI 1150727 | Provider output date 不得當 filing/release date | confirmed |

## Case 2327：國巨

### Source-reported facts

| Period | Scope | Revenue（新台幣仟元） | Parent NI（新台幣仟元） | EPS（元） | BVPS（元） | Raw result |
|---|---|---:|---:|---:|---:|---:|
| 2025Q1 | 3M/YTD | 31,103,695 | 5,529,604 | 10.77 | 309.90 | 5269 |
| 2025Q2 | 6M/YTD | 63,875,083 | 10,527,349 | 20.51 | 285.78 | 5268 |
| 2025Q3 | 9M/YTD | 96,961,795 | 16,883,453 | 8.22 | 76.48 | 5267 |
| 2025Q4 | 12M/annual | 132,930,016 | 23,634,229 | 11.51 | 83.10 | 5266 |
| 2026Q1 | 3M/YTD | 38,165,648 | 8,000,823 | 3.90 | 81.15 | 50065 |

### 已確認事件

- 2025 年公司股票面額由新台幣 10 元變更為 2.5 元。
- 股份重新發行基準日為 2025-08-22。
- 新股票上市買賣日為 2025-08-25。
- 換股關係為舊 1 股對新 4 股。
- OMI 已有正式 share-basis action record；舊 v1 normalized facts 保留 disputed 稽核狀態，新 v2 normalized facts 綁定核准 parse runs 與 production evidence package。

Filing evidence：

- 國巨 2026Q1 合併財報 `202601_2327_AI1.pdf`，由 MOPS 電子文件目錄取得。
- Note 23：面額由 10 元改為 2.5 元，2025-08-22 為股份重新發行基準日。
- Note 26：2025Q1 basic EPS 由 10.77 追溯調整為 2.69；basic weighted-average shares 為 2,053,044 仟股。
- Note 26 明示 EPS denominator 已就 2025-08-22 的股份分割追溯調整。

Official iXBRL 另提供下列 filing-level contexts：

| Filing | Context | Basic EPS |
|---|---|---:|
| 2025Q2 | `From20250401To20250630` discrete quarter | 9.74 |
| 2025Q2 | `From20250101To20250630` YTD | 20.51 |
| 2025Q3 | `From20250701To20250930` discrete quarter | 3.10 |
| 2025Q3 | `From20250101To20250930` YTD | 8.22 |

### 已撤銷的 M1 current-comparable candidate

本機保存的 2025Q1／Q2 是分割前 filing 的來源揭露值；2025Q3／Q4 與 2026Q1 是分割後基準。依 filing 已確認的 4 倍股數關係：

```text
2025Q1 normalized YTD = 10.77 / 4 = 2.6925
2025Q2 normalized YTD = 20.51 / 4 = 5.1275
2025Q2 discrete       = 5.1275 - 2.6925 = 2.4350
2025Q3 discrete       = 8.22 - 5.1275 = 3.0925
2025Q4 discrete       = 11.51 - 8.22 = 3.2900
2026Q1 discrete       = 3.90
historical TTM candidate = 2.4350 + 3.0925 + 3.2900 + 3.90 = 12.7175
```

這個計算已撤銷，原因不是單純 rounding tolerance：

```text
2025Q2 official discrete after 4x adjustment = 9.74 / 4 = 2.435
2025Q3 official discrete                    = 3.10
2025Q3 YTD delta candidate                  = 8.22 - 5.1275 = 3.0925
```

Q2 剛好一致；Q3 official discrete 與 YTD delta 不一致。現行 parser 只接受
`months == fiscal_quarter * 3`，因此排除了 Q2／Q3 discrete contexts。這使
`12.7175` 的 input lineage 不完整；不能以 display rounding 把 3.0925 視為 3.10。

### V2 production lineage（已由 v3 supersede）

以下區間只保留為歷史 candidate 的 precision 說明，不是 acceptance interval：

```text
12.7175 ± 0.01125
historical candidate interval = [12.70625, 12.72875]
```

V2 使用 official discrete contexts：

```text
2025Q1 normalized discrete = 10.77 / 4 = 2.6925
2025Q2 normalized official discrete = 9.74 / 4 = 2.4350
2025Q3 official discrete = 3.10
2025Q4 annual residual = 11.51 - 2.6925 - 2.4350 - 3.10 = 3.2825
2026Q1 discrete = 3.90
TTM = 2.4350 + 3.10 + 3.2825 + 3.90 = 12.7175
2025 annual reconciliation = 2.6925 + 2.4350 + 3.10 + 3.2825 = 11.51
```

V2 歷史 acceptance（只供稽核，不再是現行 golden truth）：

- Canonical facts 曾來自 approved parser v2 runs `3895`–`3899`；這些 immutable runs 與 package 保留供稽核，但不得再作為現行 decision-facing 選擇。
- TTM exact=`12.7175`、display=`12.72`，2025 annual difference=`0`。
- `semantic_validity=valid`、financial `decision_usable=true`、issue codes 為空。
- PE 只在同一 request 具明確 `price`、`price_as_of`、`price_basis` 時可用；price=`456.5` 的 validation snapshot 為 `35.90`，無有效價格時仍是 unavailable。
- 舊 v1 lineage 不得因 TTM 數值碰巧相同而復權；Q3 的 `+0.0075` 與 Q4 annual residual 的 `-0.0075` 只是加總相抵。
- 實作必須保存 source-restated status，不能對已追溯重編的 2.69 再除以 4。

### V3 current golden truth（clone approved）

V3 同時保存 official discrete 與 YTD contexts，並以正式 2026Q1 比較欄
`2.69` 作為 `official_restated` Q1，不製造來源未支持的 `2.6925` 精度：

```text
2025Q1 official restated discrete = 2.69
2025Q2 normalized official discrete = 9.74 / 4 = 2.435
2025Q2 normalized YTD = 20.51 / 4 = 5.1275
2025Q3 official discrete = 3.10
2025Q3 YTD = 8.22
2025Q4 annual residual = 11.51 - 8.22 = 3.29
2026Q1 discrete = 3.90
TTM = 2.435 + 3.10 + 3.29 + 3.90 = 12.725
2025 discrete sum = 2.69 + 2.435 + 3.10 + 3.29 = 11.515
2025 annual difference = 11.515 - 11.51 = +0.005
```

V3 acceptance：

- Canonical facts 綁定 approved parser v3 runs `3928`–`3932` 與 package hash
  `e46bcaed9dc264f8831ad69531d223ab0808aef60fca82ceb8f2a9c2ba94fe87`。
- Q4 必須由 annual 減 official Q3 YTD 得到 `3.29`，不得再用前三季
  discrete 加總 residual 製造 `3.2825`。
- TTM exact=`12.725`、display=`12.73`；price=`456.5` 且
  `price_basis=official_close` 時 PE=`35.87`。
- 2025 annual difference=`+0.005`，低於來源精度推導 tolerance
  `0.02625`，`within_tolerance=true`；不得為追求 difference=0 而改寫
  official discrete facts。
- Clone 第二次 apply 為 0 create／7 reuse，完整
  `PRAGMA integrity_check=ok`。Production promotion 必須建立新 backup、
  使用 production-scope package，且保留 v2 lineage，不得覆寫。

## Case 2327：月營收 continuity

### Local canonical rows

2026 年目前有：

```text
01 13,030,129
02 11,505,323
03 13,630,196
04 14,039,098
06 15,359,009
```

缺少 05；但 06 row 明示：

```text
previous_month_revenue = 15,058,220
cumulative_revenue = 82,621,975
```

### Expected quality

```json
{
  "freshness": "current",
  "continuity": "interior_gap",
  "semantic_validity": "valid",
  "decision_usable": false,
  "issues": ["monthly_revenue_missing_2026_05"]
}
```

Latest key 存在不得把 continuity 改成 complete。

## Case：OpenAPI 出表日期

Raw result `50065` 的十二個 financial entries、所有公司與全部 variants 都是：

```text
出表日期 = 1150727
年度 = 115
季別 = 1
```

Expected：

```text
provider_generated_at = 2026-07-27
announced_at = null
filed_at = null
```

不得輸出：

```text
released_at = 2026-07-27
```

除非另有 company-specific announcement evidence。

## Case 2801：彰銀

### 正式來源事實

- MOPS 2026Q1 官方 PDF SHA-256：
  `afde1d0241c6e77ef6d22a4570ff573e9cfb9d3441a2c43c26491f6f14a65be0`。
- PDF 第 38 頁：已發行股數由 2025Q1 的 11,205,758 千股增加為
  11,766,046 千股，2025 年 8 月辦理盈餘轉增資。
- PDF 第 44 頁：無償配股基準日為 2025-08-06；2025Q1 基本與稀釋
  EPS 均由追溯調整前 0.37 改為 0.35。
- PDF 第 45 頁：2026Q1 與追溯後 2025Q1 的基本 EPS 加權平均股數均為
  11,766,046 千股。
- 官方 iXBRL：
  - 2025Q2 discrete EPS = 0.42。
  - 2025Q3 discrete EPS = 0.43。
  - 2025Q3 YTD EPS = 1.20。
  - 2025 annual EPS = 1.51。
  - 2026Q1 EPS = 0.44。

### Current-comparable 決策

```text
2025Q1 = 0.35
  使用後續正式財報明列的追溯後比較值；
  不以已四捨五入的 0.37 / 1.05 產生假精度。

2025Q2 discrete = 0.42 / 1.05 = 0.40
2025Q3 discrete = 0.43
2025Q4 discrete = annual 1.51 - Q3 YTD 1.20 = 0.31
2026Q1 = 0.44
TTM = 0.40 + 0.43 + 0.31 + 0.44 = 1.58
```

2025 年單季顯示值合計為 1.49，與 annual 1.51 相差 -0.02。系統不把
Q4 改成硬湊 annual 的殘差，而是以各輸入來源的兩位小數精度推導出
0.02976190476190476190476190476 的最壞情境容差。差異與容差均保留在
public contract：

```text
annual_value = 1.51
discrete_sum = 1.49
difference = -0.02
tolerance = 0.02976190476190476190476190476
within_tolerance = true
status = ready
```

Evidence package：
`fixtures/2801-current-comparable-bank-v3-clone.json`，
hash=`69f48b2dbdb0d6953d0b84ac0efb86fd2ad604fdb05da3c4d3e72ef09cc9edee`。
目前只核准 clone，不得直接視為 production rollout。

## Case 2855：統一證

### 正式來源事實

- MOPS 2026Q1 官方 PDF SHA-256：
  `d36b83d1d47ac58fd204135498e9c43e9b5a174173c685ceb027df2632968360`。
- PDF 第 34 頁：2025-07-14 盈餘轉增資，已發行股數由 1,455,831
  千股增至 1,601,415 千股，比例為 1.10。
- PDF 第 40 頁：2026Q1 EPS=1.43；2025Q1 比較期 EPS 為損失 0.04，
  並明示比較期加權平均股數已按 2025-07-14 盈餘轉增資比例追溯調整。
- MOPS 2025Q2 官方 PDF SHA-256：
  `9591c2417f757dabf96be7a18251732e488a554ae6b0daa8894215d312ababc7`。
- PDF 第 43 頁：2025Q2 discrete EPS=0.37、YTD EPS=0.33、加權平均
  股數 1,601,414 千股；報表已反映增資後股數基準，不得再除以 1.10。
- 官方 iXBRL 另提供 2025Q3 discrete=1.34、Q3 YTD=1.67、
  2025 annual=3.00。

### Current-comparable 決策

```text
2025Q1 official restated = -0.04
2025Q2 official restated discrete = 0.37
2025Q3 discrete = 1.34
2025Q4 discrete = annual 3.00 - Q3 YTD 1.67 = 1.33
2026Q1 = 1.43
TTM = 0.37 + 1.34 + 1.33 + 1.43 = 4.47
```

2025 年四季離散值合計精確等於 annual 3.00，difference=0、
tolerance=0.030、status=ready。price=100 的明確 validation snapshot
產生 PE=22.37。

Parser 對 current-period 欄位的保守 `not_restated` 標記，不足以推翻
官方 PDF 的追溯重編證據。Evidence layer 只在
`normalization_treatment=official_restated`、reviewed status=`confirmed`
且引用確認公司行動文件時允許受限 override；lineage 同時保存 parser
原標記、reviewed 標記與 treatment。

Evidence package：
`fixtures/2855-current-comparable-securities-v3-clone.json`，
hash=`4225da83782cbc99a4b52c67f2fc3e466f5baf873cb02e0e8c63fa9e59baa20e`。
重複 apply 為 0 create／7 reuse，完整 `PRAGMA integrity_check=ok`。
目前只核准 clone，不得直接視為 production rollout。

## Case 2881：富邦金

### 正式來源事實

- MOPS 2026Q1 官方 PDF SHA-256：
  `b45d5f159f1824b138a9d34664846656e1f9cf731afe4fb902414ae41aea8c1d`。
- PDF 第 4 頁（報表頁碼 3-1）：會計師強調富邦人壽等保險子公司自
  2026-01-01 適用 IFRS 17，並對 2025Q1 比較資訊追溯重編。
- PDF 第 6 頁（報表頁碼 5）：2026Q1 basic EPS=2.40，追溯重編後
  2025Q1 comparative basic EPS=-2.09；原 2025Q1 filing basic EPS=3.00。
- PDF 第 105 頁（報表頁碼 103）：兩期加權平均股數均為
  14,007,365 千股；2025-10-01 盈餘轉增資又將已經 IFRS 17 重編的
  2025Q1 EPS 由 -2.15 追溯調整為 -2.09。
- 官方 iXBRL：
  - 原基礎 2025Q2 discrete=0.49、YTD=3.49。
  - 原基礎 2025Q3 discrete=2.82、YTD=6.23。
  - 原基礎 2025 annual=8.37。
  - 新基礎 2026Q1=2.40、2025Q1 comparative=-2.09。

### Current-comparable 決策

2025Q1 同時發生「IFRS 17 會計基礎追溯重編」與「盈餘轉增資股數基礎
追溯調整」。只有新基礎 Q1，不能把舊基礎 Q2／Q3／annual 與它混合成
TTM。這不是 parser 或 rounding error，因此正確結果是明確阻擋：

```text
basis_assessment = accounting_basis_transition
issue = accounting_basis_transition_incomplete_comparatives
normalized = blocked
TTM = null
PE = null
semantic_validity = accounting_basis_transition
decision_usable = false
```

解除阻擋前必須取得同一 IFRS 17 與目前股數基準的 2025Q2 discrete／YTD、
2025Q3 discrete／YTD、2025 annual，以及完整 restatement lineage。不得以
原基礎 EPS 推估或硬接。

Basis assessment package：
`fixtures/2881-ifrs17-basis-transition-clone.json`，
hash=`e251525cf290076d8cdd2ab55df1c4e43b2a792fadd9d50fa3c1b3e9bfd06043`。
套用 migration `20260731_0048` 後重複 apply 會 reuse 同一 assessment；
clone 完整 `PRAGMA integrity_check=ok`。目前只核准 clone，不得直接視為
production rollout。

## Case 2867：三商壽

### 正式來源事實

- 2867 必須使用 individual `REPORT_ID=A`／`AI2` 文件，不得套用
  consolidated `REPORT_ID=C`。
- MOPS 2026Q1 官方 PDF SHA-256：
  `601a2ed80a8e917d7cd9fc6b1790d7911a1f33f740b02a3e16568ebe35bcd96b`。
- PDF 第 4 頁：公司自 2026-01-01 適用 IFRS 17，並追溯重編 2025Q1
  比較期間財務報表。
- PDF 第 7 頁：2026Q1 與重編後 2025Q1 basic／diluted EPS 均為
  虧損 0.03；原 2025Q1 filing basic EPS 為正 0.03。
- PDF 第 8 頁：2025-01-01 追溯適用 IFRS 17 對權益的影響為增加
  122,647,652 仟元，證明這是重大的會計基礎轉換。
- PDF 第 13–14 頁：列出完全追溯法／公允價值法過渡方法，以及
  2025 年資產、負債、權益重編前後差額。
- PDF 第 100 頁：2026Q1 與重編後 2025Q1 加權平均股數分別為
  5,899,501 與 5,699,501 千股；EPS 符號改變不能由股數縮放解釋。
- 官方 iXBRL：
  - 原基礎 2025Q1 basic EPS=+0.03。
  - 原基礎 2025Q2 discrete=-0.15、YTD=-0.12。
  - 原基礎 2025Q3 discrete=0.28、YTD=0.16。
  - 原基礎 2025 annual=0.20。
  - 新基礎 2026Q1=-0.03、2025Q1 comparative=-0.03。

### Current-comparable 決策

2026Q1 filing 只提供新基礎的 2025Q1 比較值，沒有同基礎 2025Q2、
Q3 與 annual。不得把舊基礎 Q2／Q3／annual 與新基礎 Q1 混合：

```text
basis_assessment = accounting_basis_transition
issue = accounting_basis_transition_incomplete_comparatives
normalized = blocked
TTM = null
PE = null
semantic_validity = accounting_basis_transition
decision_usable = false
```

即使 validation request 明確傳入 price=100、`price_as_of` 與
`price_basis`，valuation 仍保持 blocked 且不回顯可被誤用的價格。

Basis assessment package：
`fixtures/2867-ifrs17-basis-transition-clone.json`，
hash=`f3556588accee3f01982cbcf3a181d98b1ad2f70e84bc4cee9dcc359ca73dde8`。
Clone parser v3 runs `3918`–`3922` 已核准；assessment 重複 apply 為
0 create／1 reuse，完整 `PRAGMA integrity_check=ok`。目前只核准 clone，
不得直接視為 production rollout。

## Case 2207：和泰車

### 正式來源事實

- MOPS 2025Q1 官方 PDF SHA-256：
  `c6f54c7922a8a2838ebaf0ff3ee3a92e8be107f967a68e9d9c3d0a6ea4eb190b`。
- 2025Q1 PDF 第 54 頁：原基礎歸屬母公司淨利 4,307,781 仟元、
  加權平均股數 557,103 千股、basic EPS=7.73。
- MOPS 2026Q1 官方 PDF SHA-256：
  `f40534d4044cf73dc2c436ccb72c3cedbebfa9511f8e6fcc29b8149f749e1c5b`。
- 2026Q1 PDF 第 11、73 頁：重編後 2025Q1 歸屬母公司淨利
  3,974,710 仟元、加權平均股數仍為 557,103 千股、
  basic EPS=7.13；2026Q1 basic EPS=7.95。
- 2026Q1 PDF 第 16–17 頁：子公司和泰產險自 2026-01-01 採用
  IFRS 17，並對本報告所有比較期間追溯適用；第 12 頁另列集團
  2025-01-01 權益增加 725,510 仟元，其中母公司業主 725,426 仟元。
- 相同股數下淨利與 EPS 同時改變，已排除股票股利、分割或股數縮放
  是 7.73→7.13 的原因。
- 官方 iXBRL：
  - 原基礎 2025Q1 basic EPS=7.73。
  - 原基礎 2025Q2 discrete=7.10、YTD=14.83。
  - 原基礎 2025Q3 discrete=10.03、YTD=24.86。
  - 原基礎 2025 annual=33.93。
  - 新基礎 2026Q1=7.95、2025Q1 comparative=7.13。

### Current-comparable 決策

2207 的主業雖非保險，合併 EPS 仍受採用 IFRS 17 的保險子公司影響。
會計基礎偵測不能只依公司 variant 或產業標籤；必須以合併報表 evidence
為準。由於沒有同基礎的 2025Q2／Q3／annual：

```text
basis_assessment = accounting_basis_transition
issue = accounting_basis_transition_incomplete_comparatives
normalized = blocked
TTM = null
PE = null
semantic_validity = accounting_basis_transition
decision_usable = false
```

Basis assessment package：
`fixtures/2207-ifrs17-basis-transition-clone.json`，
hash=`875463e282caa15e6e745e933807939cf8bc5f135355cf733116a1f0e977270c`。
Clone parser v3 runs `3923`–`3927` 已核准；assessment 重複 apply 為
0 create／1 reuse，完整 `PRAGMA integrity_check=ok`。price=100 的
validation request 仍不產生 TTM／PE。目前只核准 clone，不得直接視為
production rollout。

## Case 2324：仁寶（ci fast lane pilot）

### 正式來源事實

- MOPS official consolidated iXBRL 期間：2025Q1、Q2、Q3、annual、2026Q1。
- 五份 filing 的 `IssuedCapital` 均為 TWD 44,071,466 thousand。
- 2026Q1 filing 的 comparative 2025Q1 basic EPS=0.50，與 2025Q1
  current-period filing 完全一致。
- 2025Q2 official discrete=0.11、YTD=0.61；2025Q3 official
  discrete=0.45、YTD=1.06；2025 annual=1.38；2026Q1=0.45。
- Q1 0.50 + Q2 discrete 0.11 = Q2 YTD 0.61；Q2 YTD 0.61 +
  Q3 discrete 0.45 = Q3 YTD 1.06；Q4 residual=1.38-1.06=0.32。

### Current-comparable 決策

```text
2025Q1 = 0.50
2025Q2 = 0.11 (official discrete)
2025Q3 = 0.45 (official discrete)
2025Q4 = 0.32 (annual - Q3 YTD)
2026Q1 = 0.45
TTM exact = 1.33
annual difference = 0
semantic_validity = valid
decision_usable = true
```

Share-basis 判定不是從「沒有事件」推論；它只核准這五份 filing 之間
發行資本一致、正式比較欄一致、discrete／YTD／annual 全部互相對帳的
presentation basis。Evidence package：
`fixtures/2324-ci-fast-lane-period-scope-v1-clone.json`，
hash=`71de20065f6a7291e453350c21806240b9bfc09308f10e110df351c8331099df`。
重複 apply 為 0 create／7 reuse，完整 `PRAGMA integrity_check=ok`。
目前只核准 clone；production price freshness 與 promotion gate 尚未通過。

## Variant acceptance

每個 variant 必須驗證：

- Identity mapping。
- Duration／instant field mapping。
- Unit。
- Basic／diluted EPS availability。
- Parent attribution。
- Not-applicable fields。
- Empty／malformed values。
- Source-generated date handling。

不得以一般業 fixture 推論銀行、證券、金控、保險與異業。
