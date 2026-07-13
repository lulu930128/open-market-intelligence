# Plan

## Milestone 1: Scope and save contract

- 將預設 group resolution 改為所有 active groups。
- 增加 snapshot save result，保留既有 public API response。
- 驗證 observed snapshot date 與 expected trade date。

Acceptance: child group 被處理；stale 不落庫；重跑可辨識 existing。

## Milestone 2: Coverage and reconciliation

- 建立 daily coverage summary。
- job result 回報 expected/covered/missing scopes。
- 增加收盤後 reconciliation interval 與完成後短路。

Acceptance: 漏跑可補；完整後不重複寫入或 enqueue。

## Milestone 3: Product surface and documentation

- 調整盤中尚未保存文案，說明收盤後自動處理。
- 更新 `.env.example` 與 README 的 scope、intraday、retry 行為。

Acceptance: 使用者不會把盤中尚未生成誤認為故障。

## Milestone 4: Verification

- 跑 radar automation 與 scheduler targeted tests。
- 跑 backend safe validation。
- 用 isolated runtime 驗證 health、radar、history contract。
- 檢查 git diff、secret、產物與本機 DB 是否有非預期寫入。

Stop-and-fix: 任一 regression、coverage 誤報、DB 重複寫入或 runtime contract 失敗都先修正再完成。
