# Plan

## Milestones

1. Governance setting closure
   - Scope: root／nested `AGENTS.md`、architecture index、compatibility、historical resume、Temporal contract、structured state。
   - Acceptance: precedence 與 axes 無衝突，Roadmap 與 current truth 分離，docs-only checks 通過。
   - Validation: UTF-8 readback、link check、`git diff --check`。

2. Mechanical architecture guard
   - Scope: constraints、exact debt、checker、architecture tests。
   - Acceptance: current violations 精確等於 debt；新增與 stale occurrence 都 fail。
   - Validation: `.venv\Scripts\python.exe scripts\check-architecture.py` 與 targeted pytest。

3. Validation／CI integration
   - Scope: quick profile、CI architecture job、PR evidence。
   - Acceptance: offline／deterministic gate 可由 Windows Python 3.11／3.13 執行。
   - Validation: `scripts\run-safe-validation.ps1 -Profile quick`。

4. Skill synchronization
   - Scope: applicable OMI skills。
   - Acceptance: skills 指向 repo truth、正交 axes 與 guard，不複製 current inventory。
   - Validation: `quick_validate.py` 逐一通過。

## Stop-and-fix rules

- 若 checker 需要寬鬆例外才能 green，停止並修正偵測或建立精確 debt，不擴大 allowlist。
- 若發現變更會改 production behavior、DB、runtime 或 external consumer contract，停止該變更並保留為後續工作。
- 若 quick／architecture tests 失敗，先修正本次治理變更；與既有 dirty work無關的失敗要隔離並記錄。

## Decisions

- 2026-08-27：以現有 canonical axes 為 source truth，不建立 universal `TemporalState`。
- 2026-08-27：`official_final` 若需要 outward convenience label，只能是 authority、dataset semantics、release 與 item finalization 的 derived state。
- 2026-08-27：guard baseline 描述目前 source，不在同一工作包修 production debt。
