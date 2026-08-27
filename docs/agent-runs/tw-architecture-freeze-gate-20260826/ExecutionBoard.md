# Execution Board

| Order | Package | Status | Depends | Next evidence |
|---:|---|---|---|---|
| 0 | BASE-01 | SOURCE_PASS | - | exact source/DB baseline captured |
| 1 | LIFE-01 | SOURCE_PASS | BASE-01 | canonical `quote.auction`; 33 targeted pass |
| 2 | LIFE-02 | SOURCE_PASS | LIFE-01 | registry/catalog/probe; 31 targeted pass |
| 3 | LIFE-03 | SOURCE_PASS | LIFE-02 | non-null DatasetHealth; 38 targeted pass |
| 4 | AIQ-01 | SOURCE_PASS | LIFE-03 | four-result bundle with split read/acquire |
| 5 | AIQ-02 | SOURCE_PASS | AIQ-01 | canonical depth reaches AI; MCP regression green |
| 6 | VAL-01 | SOURCE_PASS | LIFE-03 | canonical daily evidence reaches AI |
| 7 | VAL-02 | SOURCE_PASS | VAL-01 | market-owned valuation; unknown cost preserved |
| 8 | GET-01 | SOURCE_PASS | LIFE-03 | GET inventory + zero-provider guards |
| 9 | GET-02 | SOURCE_PASS | GET-01 | legacy metrics/overnight cache-only |
| 10 | SIDE-01 | SOURCE_PASS | BASE-01 | machine-readable sidecar contracts |
| 11 | GET-03 | SOURCE_PASS | GET-01,SIDE-01 | holding/futures/index command split |
| 12 | FRESH-01 | SOURCE_PASS | LIFE-03 | Registry evaluator + market facts |
| 13 | FRESH-02 | SOURCE_PASS | FRESH-01,VAL-01 | AI consumes canonical daily health |
| 14 | SIDE-02 | SOURCE_PASS | SIDE-01,GET-03 | exact route/classification guard |
| 15 | CROSS-01 | SOURCE_PASS | AIQ-02,VAL-02,GET-03,FRESH-02,SIDE-02 | backend/frontend/source gate green |
| 16 | EOD-01 | DEFERRED | CROSS-01 | risk-budget decision |
| 17 | ADOPT-01 | NOT_STARTED | CROSS-01,user approval | named runtime evidence |
| 18 | LIVE-01 | PENDING | ADOPT-01,official session | live artifacts |
| 19 | CLOSE-01 | SOURCE_PASS | CROSS-01 | source frozen; runtime/live pending |
| 20 | FINAL-01 | SOURCE_PASS | FRESH-02 | canonical daily health reaches source-health projection |
| 21 | FINAL-02 | SOURCE_PASS | SIDE-02 | disposition unknown/malformed fail closed |
| 22 | FINAL-03 | SOURCE_PASS | LIFE-03,FINAL-02 | intraday auction type persist/reread green |
| 23 | FINAL-04 | SOURCE_PASS | FRESH-01 | platform-evidence contract + deprecated alias |
| 24 | FINAL-05 | SOURCE_PASS | AIQ-01 | bounded acquisition scope + formal quote alias |
| 25 | FINAL-06 | SOURCE_PASS | FINAL-01..05 | 422 pass + safe quick + final source artifact |

## Status meanings

- `NOT_STARTED`：無task-owned production diff。
- `IN_PROGRESS`：已有修改，但acceptance未全過。
- `SOURCE_PASS`：source與targeted tests通過，尚未adopt。
- `RUNTIME_PASS`：named runtime載入新source並通過smoke。
- `LIVE_PASS`：合法session evidence完成。
- `BLOCKED`：有明確阻塞與evidence。
- `DEFERRED`：不影響本輪P0/P1 freeze，可後續處理。
