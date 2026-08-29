# Architecture Governance Guard 2026-08-27

## Goal

- 完成 OMI instruction／truth governance 收尾，並建立 deterministic、offline、exact-debt 的 mechanical architecture guard。
- 將 temporal governance 建立在既有正交 canonical axes 上，只對缺少的 release／reconciliation 語意做 additive extension；不得建立 universal `TemporalState`。

## Non-goals

- 不修復或重構既有 production architecture debt。
- 不修改 DB schema、使用者資料、provider 行為、runtime 或 outward product behavior。
- 不 commit、不 push，也不重啟服務。

## Hard constraints

- 保留目前 dirty working tree 的所有既有變更，不 revert、不覆寫無關工作。
- Architecture debt 必須精確對應實際 occurrence；禁止寬鬆 allowlist 或只比對上限。
- Market Session、evidence-object finalization、authority、release、reconciliation、freshness 與 trading status 必須維持正交。
- Public canonical contract 的 breaking change 必須有明確 consumer、版本／migration window 與 removal gate；private legacy seam 不自動永久相容。
- Guard 必須 offline、deterministic、Windows compatible，不連 provider、runtime、browser、network 或 user DB。

## Context

- Repo: `C:\project\Open Market Intelligence`
- Source baseline HEAD: `add7e1fb1e3610b10eacf82db001e40f6e4257c4`
- Working tree: dirty；本次 baseline 明確包含使用者目前未提交的 source work。
- Shared canonical axes 目前由 `backend/app/market_data/contracts.py` 擁有。
- 已知 debt 至少包含 `backend/app/market_data/eod_coverage.py` 的 reverse dependency、DB dependency 與 transaction ownership。

## Deliverables

- 精簡 root／nested instructions 與 current-truth navigation。
- 新增 durable Market Temporal / Evidence Axes contract。
- 結構化 `CurrentImplementationState.md`。
- 新增 `architecture/constraints.toml`、`architecture/debt.toml` 與 `scripts/check-architecture.py`。
- 新增 deterministic architecture tests，整合 quick validation 與 CI architecture job。
- 同步相關 OMI skills。

## Done criteria

- WP-A 與 WP-B acceptance 全部以 source evidence 通過。
- `actual violations == declared debt`，intentional new violation 與 stale debt 都會 fail。
- Quick profile 執行 architecture checker、architecture tests、compileall、frontend tsc 與 diff check。
- 沒有 production behavior、DB、runtime 或 provider side effect。

## Open questions / assumptions

- 目前 dirty working tree 是使用者要保留並作為本次 guard baseline 的 source truth；未宣告其中任何 runtime／live／product adoption。
