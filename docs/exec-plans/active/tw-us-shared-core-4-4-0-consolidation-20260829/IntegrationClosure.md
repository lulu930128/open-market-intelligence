# OMI 4.4.0 Exact Integration Closure

## Purpose

本文件記錄4.4.0 source立腳點的exact integration範圍與驗證證據。它不代表正式commit／push，也不把Source acceptance升格為Runtime、Live或Product acceptance。

## Integration model

- Base：local `main` commit `0b7faa8`，保留先前TW intraday read index與repository read optimization。
- Overlay：current checkout與本輪TW／US／Shared Core／AI／MCP／Frontend／docs／release變更的exact path集合。
- Mechanism：alternate `GIT_INDEX_FILE`；真正Git index維持空白。
- Source manifest：240 paths（100 added、139 modified、1 rename），以4.4.0 Foundation extension checkpoint與guard更新後的最終alternate index為準。
- Publication：未commit、未merge、未push。

## Dependency closure

- TW finalized Daily bar不再被同日provisional intraday overlay取代。
- Yahoo Daily INDEX的raw zero／null volume在canonical層統一為`None + not_applicable`；Stock／ETF與1m語意不變。
- US AI normalized `daily.ohlcv` selection limit會提高既有reader `bars` bound，260-bar需求不再被200-bar default截斷。
- local `main`的TW intraday composite read index、ORM index宣告與repository `load_only` optimization已納入。
- Alembic保持單一線性head：`20260826_0072 -> 20260829_0073 -> 20260829_0073t`。
- `omi.decision.v4`維持唯一outward decision contract；沒有新增consumer fallback或parallel market semantics。

## Validation

- Isolated Backend／Shared／TW／US／AI／API／migration matrix：`338 passed`。
- Isolated architecture pytest：`18 passed`。
- Architecture checker：PASS，`22 actual / 22 declared`。
- Isolated MCP contract：`32 passed`。
- Foundation dark-boundary guard：歷史artifact保持append-only，4.4.0 extension checkpoint加入後`7 passed`。
- Isolated Frontend：ESLint PASS；TypeScript `--noEmit` PASS。
- Release version：`VERSION`、Frontend package metadata與release checker一致為`4.4.0`。
- Staged diff：`git diff --cached --check` PASS。
- Staged-only safety scan：沒有DB、secret、private path、log、cache、build output或非example `.env`。

## Explicit exclusions

- `data/open_market_intelligence.db`及任何runtime DB mutation。
- 真實provider credential與`.env`；`.env.example`僅保留placeholder contract。
- `^SOX`第二Daily provider與2026-08-28補洞。
- full-market rollout、JP／KR擴張、新execution capability。
- Backend／Frontend／MCP restart、runtime adoption與盤中live acceptance。
- commit、merge、push與tag。

## Remaining gates

1. Publication gate：使用者review exact source集合後，才正式stage／commit／push。
2. Runtime adoption gate：publication或source基線確定後，使用既有launcher lifecycle採用4.4.0。
3. Product readback gate：驗證direct／proxy／MCP／UI與代表性TW／US payload；`^SOX`仍應truthful stale。
