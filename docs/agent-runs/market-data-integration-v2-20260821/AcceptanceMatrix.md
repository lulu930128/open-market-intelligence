# 02A Acceptance Matrix

## Status legend

- `pending`：尚未執行。
- `passed`：有可重現驗證證據。
- `failed`：已執行但未滿足，必須stop-and-fix。
- `not_applicable`：有明確理由且不影響02A done criteria。

本矩陣只驗收dark source；不得用來替代Foundation runtime/market-session或02B production acceptance。

## A0 — Baseline and separation

| ID | Requirement | Evidence | Status |
| --- | --- | --- | --- |
| BASE-01 | 原始附件SHA-256已記錄 | `Progress.md` / `artifacts/02a-source-baseline.json` | passed |
| BASE-02 | branch、HEAD、dirty status inventory已記錄 | baseline artifact | passed |
| BASE-03 | Foundation 30-target reference已保存且原artifact未改 | baseline artifact + hash comparison | passed |
| BASE-04 | `99f95233...`不再被描述為closure-eligible | task docs review | passed |
| BASE-05 | closing-auction known failure已列為獨立Foundation blocker | `Prompt.md` / `Plan.md` | passed |
| BASE-06 | 02A與Foundation artifacts/ownership分離 | file inventory | passed |

## A1/A2 — Provider policy

| ID | Requirement | Planned evidence | Status |
| --- | --- | --- | --- |
| POL-01 | `cache_only` routes=0 | unit test | passed |
| POL-02 | `completed_session` routes=0 | unit test | passed |
| POL-03 | `prefer_live` routes deterministic且bounded | unit test | passed |
| POL-04 | `require_live`無可用route時truthful unfillable | unit test | passed |
| POL-05 | unsupported capability fail closed | unit test | passed |
| POL-06 | disabled/auth_failed/plan_restricted預設skip | parameterized unit test | passed |
| POL-07 | failed/rate_limited/unavailable預設skip | parameterized unit test | passed |
| POL-08 | degraded/disconnected/unknown不被當成healthy | parameterized unit test | passed |
| POL-09 | route descriptors由input注入，shared layer無KGI/MIS硬編碼default | source/AST test | passed |
| POL-10 | priority tie以stable provider key排序 | unit test | passed |
| POL-11 | route/attempt/timeout bounds不可overflow | boundary tests | passed |
| POL-12 | policy無network/DB/provider SDK side effect | import guard | passed |

## A3 — Research Lease lifecycle

| ID | Requirement | Planned evidence | Status |
| --- | --- | --- | --- |
| LEASE-01 | success保留acquired outcome並cleanup released | unit test | passed |
| LEASE-02 | unavailable沒有resource leak | unit test | passed |
| LEASE-03 | provider error保留failed outcome並cleanup | unit test | passed |
| LEASE-04 | timeout會cooperative cancel，不只停止外層等待 | controlled fake test | passed |
| LEASE-05 | caller cancellation不啟動下一attempt | controlled fake test | passed |
| LEASE-06 | unexpected exception仍cleanup | unit test | passed |
| LEASE-07 | cleanup failure truthful為`cleanup_failed` | unit test | passed |
| LEASE-08 | duplicate release idempotent | unit test | passed |
| LEASE-09 | 100 sequential runs active handles回baseline | stress-style unit test | passed |
| LEASE-10 | parallel leases owner隔離 | concurrency unit test | passed |
| LEASE-11 | lease A不能release lease B | ownership test | passed |
| LEASE-12 | timeout/cancel後無late callback/reactivation | controlled fake test | passed |
| LEASE-13 | worker/task在bounded時間內terminal | controlled fake test | passed |
| LEASE-14 | route timeout被overall remaining deadline clamp | fake clock test | passed |
| LEASE-15 | outcome與cleanup status正交保存 | contract test | passed |

## A4 — Control Plane

| ID | Requirement | Planned evidence | Status |
| --- | --- | --- | --- |
| CP-01 | requirement與plan mismatch fail closed | unit test | passed |
| CP-02 | first candidate attempt與continue/stop規則deterministic | scenario test | passed |
| CP-03 | unavailable/timeout/error可bounded進下一route | scenario tests | passed |
| CP-04 | cancellation不執行下一route且cleanup | scenario test | passed |
| CP-05 | `cache_only`/`completed_session` port call count=0 | scenario test | passed |
| CP-06 | max provider attempts enforced | boundary test | passed |
| CP-07 | external call/subscription overflow fail closed | boundary tests | passed |
| CP-08 | 不混合不同provider snapshot欄位 | candidate identity test | passed |
| CP-09 | result不含final selected provider/selection reason | contract test | passed |
| CP-10 | all attempts fail仍truthful且bounded | scenario test | passed |
| CP-11 | Control Plane回傳前request-owned handles已cleanup | lifecycle assertion | passed |
| CP-12 | resolver後續failure不造成lease leak | integration-style fake test | passed |
| CP-13 | no real provider import/call | AST/import guard | passed |

## A5 — Observability and sanitization

| ID | Requirement | Planned evidence | Status |
| --- | --- | --- | --- |
| OBS-01 | attempts與safe continue/skip reason可見 | serialization test | passed |
| OBS-02 | acquisition provider與resolver selected provider欄位不混用 | schema test | passed |
| OBS-03 | outcome與cleanup status可見 | serialization test | passed |
| OBS-04 | logical attempts/external calls/subscriptions分開 | schema/count test | passed |
| OBS-05 | unknown count不被壓成0 | contract test | passed |
| OBS-06 | secret-like exception message不被序列化 | adversarial test | passed |
| OBS-07 | raw payload不能進diagnostics | adversarial test | passed |
| OBS-08 | token/cookie/account/person/environment欄位不存在 | schema/serialization test | passed |
| OBS-09 | oversized detail/limitation bounded | validation test | passed |
| OBS-10 | diagnostics serialization failure不造成lease leak | fault-injection test | passed |

## A6 — Dark boundary

| ID | Requirement | Planned evidence | Status |
| --- | --- | --- | --- |
| DARK-01 | production modules不import四個02A modules | AST import graph test | passed |
| DARK-02 | 四個02A modules不得importAI/DB/router/agents | AST import test | passed |
| DARK-03 | 四個02A modules不得importKGI/MIS/quote_depth | AST import test | passed |
| DARK-04 | 不import requests/httpx/sqlalchemy | AST import test | passed |
| DARK-05 | `backend/app/market_data/__init__.py` unchanged | hash/source diff | passed |
| DARK-06 | router/config/runtime/public snapshots unchanged by02A | owned-file diff inventory | passed |
| DARK-07 | frontend/MCP/Kuro unchanged by02A | owned-file diff inventory | passed |
| DARK-08 | Foundation frozen hash drift caused by02A=0 | checkpoint comparison | passed |
| DARK-09 | 不建立real provider lease/network/runtime | fake call ledger + import guard | passed |
| DARK-10 | 不做DB write/migration/backfill/repair | import guard + changed-file inventory | passed |

## A7 — Validation and final state

| ID | Requirement | Planned evidence | Status |
| --- | --- | --- | --- |
| VAL-01 | 四個new modules compileall passed | validation log/artifact | passed |
| VAL-02 | 全部02A targeted tests passed | pytest log/artifact | passed |
| VAL-03 | backend safe validation passed或無關failure精確隔離 | wrapper log/artifact | passed |
| VAL-04 | `git diff --check` passed | command output | passed |
| VAL-05 | 02A source manifest只含owned files | manifest review | passed |
| VAL-06 | artifacts不含secret/raw payload/private identity | sanitization scan | passed |
| VAL-07 | no commit/push without Gate C | git evidence | passed |
| VAL-08 | production wiring=false | final validation artifact | passed |
| VAL-09 | real provider calls=0、DB writes=0 | final validation artifact | passed |
| VAL-10 | final label只有`02A_SOURCE_COMPLETE_DARK` | `Progress.md` | passed |

## Completion rule

- 2026-08-21 final validation時所有列均有source/test/artifact證據且狀態為`passed`。
- `failed` blocking項目=0、`not_applicable`項目=0。
- Machine-readable摘要：`artifacts/02a-validation.json`。
- 本矩陣只支持`02A_SOURCE_COMPLETE_DARK`，不支持production、runtime、Foundation closure或02B cutover宣告。
