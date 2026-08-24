# 分點行為引擎 V0 狀況／邊界報告

報告日期：2026-08-22（Asia/Taipei）

Evidence as-of：2026-08-21

Report contract：`broker_branch.behavior.readiness_report.v0`

## 結論

V0 的 observation quality、shadow feature materialization、tracked job、migration、測試與唯讀 readiness evaluator 已完成。現有資料只能支持 exploratory feature evidence，promotion 結論為 `shadow_only`；`broker_branch.behavior` 不 advertised，V1 classification、flow-risk、Radar、frontend、MCP 與 Kuro integration 均未開放。

這不是未完成實作的模糊狀態，而是資料與驗證 gate 的可重現 no-go：目前只有 25 個 high-coverage sessions，低於 60-session calibration 與 120-session production-candidate 門檻，也沒有可執行的 OOS split。

## Live evidence

| Evidence | Result |
| --- | ---: |
| Lookback | 120 台股交易日 |
| High-coverage window | 2026-07-20 至 2026-08-21 |
| High-coverage sessions | 25 |
| Materialized profiles | 821 |
| Profile gate eligible | 620 |
| Walk-forward splits | 0（最低要求 2） |
| Coverage consistency issues | 0 |
| Promotion | `shadow_only` |
| Production ready | `false` |

Aggregate diagnostics：1,201,385 個 eligible initial、407,559 個 next-session reobserved、793,826 個 right-censored、159,469 個 observed opposite flow、248,090 個 observed same-direction flow。這些 observation 具有同日、同股票與市場狀態的群聚相關性，不能把 row count 當獨立樣本數；rate 只作診斷，不是未來機率、持倉或已出清推定。

## Frozen readiness policy

- `< 60` high-coverage sessions：只允許 exploratory shadow evidence。
- `60–119`：calibration candidate，仍不可 production classify。
- `>= 120`：production candidate，仍需 walk-forward、分層穩定性、effective-dated universe 與來源權利 gate。
- Profile eligibility：至少 20 sessions、30 stocks、100 reobserved denominator，單一股票 observation share 不高於 20%。
- Walk-forward：60 train／20 validation／20 test、purge 1、embargo 1、step 20；至少 2 個 test splits。
- 這些 threshold 只決定能否進校準，不是 classification weight、score 或 probability mapping。

## Promotion blockers

- `high_coverage_history_below_calibration_minimum`
- `high_coverage_history_below_production_minimum`
- `walk_forward_split_count_below_minimum`
- `walk_forward_validation_not_run`
- `v1_classification_not_implemented`
- `effective_dated_universe_not_available`
- `source_rights_not_verified`

## 已實作邊界

- Provider／raw：沿用既有 bounded latest-only nStock collector；本報告不呼叫 provider。
- Quality：Top15 未上榜固定為 `unknown_not_ranked`；不轉成 0、no trade 或 confirmed unwind。
- Derived：只讀 `broker_branch_behavior_feature_snapshot` 與 `broker_branch_snapshot_quality` 的 bounded selected state。
- Report：只輸出 aggregate、gate、source metadata 與 fingerprint；不輸出 branch code、branch name 或 raw payload。
- Transaction：report 執行 provider fetch=0、DB write=0，結束時明確 rollback read transaction。
- Consumer：沒有新增 public HTTP/AI/MCP projection，沒有 frontend panel，也沒有修改 Radar score/weight。

## 未開放邊界

- 不輸出 `overnight_likely`、`confirmed_unwind`、`remaining_inventory` 或 estimated lots。
- 不建立 V1 primary class；620 個通過 profile minimum 的 rows 仍只是候選 feature profiles，不代表 620 個已驗證分點。
- 不建立 flow-risk 0–100 index；沒有 OOS calibration 時，指數只會造成偽精確。
- 不改 Radar 或 Decision v4；consumer 不得自行套公式或把 diagnostic rates 變成交易建議。
- 不自動採購或串接 TWSE／TPEx 付費分點資料；nStock 的使用、衍生與再散布權利仍需確認。
- 不用目前 active universe 回推成歷史 universe truth；production gate 需要 effective-dated universe evidence。

## 可重現命令

Repo root：

```powershell
.\.venv\Scripts\python.exe -B .\scripts\report-broker-branch-behavior-readiness.py --format json --pretty
.\.venv\Scripts\python.exe -B .\scripts\report-broker-branch-behavior-readiness.py --format markdown
```

Targeted tests（從 `backend`）：

```powershell
..\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider tests\test_database_model_contract.py tests\test_database_migrations.py tests\test_broker_branch_calibration.py tests\test_broker_branch_behavior.py tests\test_broker_branch_snapshot_quality.py
```

最終相關 regression 加上 migration／model contract 共 29 passed、414 個既有 Python sqlite adapter deprecation warnings。Full backend suite 收集 2,012 tests 並跑到 100%，但因既有 Market Data Foundation protected hash drift 與 Windows pytest Temp ACL 問題仍未全綠；本任務沒有改 hash baseline 或 launcher test 來掩蓋它們。

Materialized evidence fingerprint：`b827d0b35464e8aabe2d816761b1ad35a6e0769793f92e55129112e3e161fe1f`

Full report fingerprint：`41e55b2fd78cded32c1c3dd531d22321182f34d2bf0aad4aab0d90bbb4defbdd`（不含 operational `computed_at`，同 evidence rerun 保持穩定）

## 下一個允許進入的 gate

先讓 bounded latest-only collector自然累積新的 high-coverage sessions。到 60 sessions 時可以做第一輪 calibration candidate review；到 120 sessions 後仍需至少 2 個 purged/embargo OOS splits、分層穩定性、effective-dated universe、source-rights verification 與明確 promotion 決策。任一條件未成立，就繼續維持 feature-only shadow。
