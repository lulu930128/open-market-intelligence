# Progress

## Status

- Current phase: completed
- Last updated: 2026-08-27 Asia/Taipei

## Completed

- 完成 root／nested instructions、truth navigation、current implementation matrix 與 Roadmap/current truth 分離。
- 確認 shared `MarketSession`、`BarFinalization`、`AuthorityClass` 已是不同 canonical axes，新增 Market Temporal / Evidence Axes contract。
- 建立 10 條 mechanical constraints、26 個 exact debt occurrence、offline checker 與 17 個 architecture tests。
- 將 guard 接入 safe validation、Windows CI architecture job 與 PR evidence checklist。
- 同步 6 個 OMI skills 與 3 份 reference checklist。

## Validation evidence

- UTF-8 readback：PASS；root `AGENTS.md` 101 行。
- Changed-document relative links：PASS。
- Retired wording scan：PASS。
- `.venv\Scripts\python.exe scripts\check-architecture.py`：PASS，actual 26／declared 26。
- `.venv\Scripts\python.exe -m pytest -p no:cacheprovider backend\tests\architecture`：17 passed。
- 6 個 OMI skills 經 `quick_validate.py` 驗證：6/6 valid（使用 `PYTHONUTF8=1`）。
- CI YAML parse：PASS。
- `scripts\run-safe-validation.ps1 -Profile quick`：PASS；architecture checker、architecture pytest、backend compileall、frontend tsc、git diff check 全部通過。

## Decisions made

- Temporal governance 採 axes contract；缺少的 release／reconciliation semantics 優先 additive typed extension，不預設 migration。
- `official_final` 只允許由 dataset semantics、authority、release 與 item finalization 推導。
- Debt occurrence 使用 rule、path、symbol／call-site fingerprint，不以行號或 occurrence 上限放寬。

## Known issues / risks

- Working tree 含大量使用者既有未提交變更；本工作包只驗證治理／guard／skill 範圍，不宣稱其他 source 已完成 runtime／live／product adoption。
- 26 個 exact debt 是被凍結的現況，不代表架構債已清除；後續每次 owner-boundary migration 應同步移除對應 debt。

## Next step

- 依 owner 與 closure gate 分批消除 exact debt；每批保留 consumer parity、negative regression 與 runtime adoption evidence。
