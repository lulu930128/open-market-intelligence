# 執行計畫

## Milestone 0：基線與契約地圖

狀態：完成。

- 凍結 dirty worktree、branch、HEAD 與正式 runtime 基線。
- 盤點 HTTP、`omi.decision.v4`、MCP／Kuro consumer、dataset freshness 與 source-health 的欄位 ownership。
- 把 P0～P2 修改票映射到 source、tests 與 runtime probe。

驗收：任務文件完整，且不改動任何既有無關成果。

## Milestone 1：P0 失敗基準

狀態：完成。

- 補 closing auction snapshot／last trade／indicative 分離測試。
- 補 `require_live` fallback readiness 測試。
- 補 Crypto 升冪與 latest point 測試。
- 補 TXF interval contracts 投影測試。
- 把既有 US／JP／KR market downgrade 測試改為正確的 market-scope invariants。
- 補 KR market-halt continuity 測試。
- 補 current-request freshness 不受 background stale 覆蓋的測試。

驗收：每個修正點都有直接 contract assertion；舊錯誤語意不再被 regression 固化。

## Milestone 2：P0 局部實作

狀態：完成。

- 在 backend truth source 修正 auction、OHLCV ordering、volume projection、scope resolution、session event 與 freshness selection。
- 公開欄位採 additive、consumer-safe；thin consumers 不重做判斷。
- 對 provider 沒提供的 auction indicative／match 維持 `null + not_provided`。

驗收：focused P0 regression 全數通過，沒有無關檔案的大型重寫。

## Milestone 3：P0 安全驗證與 runtime

狀態：完成。

- compile／syntax。
- focused pytest。
- safe backend validation profile。
- `git diff --check`。
- 正式 launcher health、代表性 v4 request、raw supporting endpoint 與 session/freshness consistency smoke。

驗收：source、test 與正式 runtime 三個層級一致；無法在當下市場時段證明的 case 明確列為待實盤驗收。

## Milestone 4：P1 契約正規化

狀態：部分完成；不依賴新外部資料的 contract correctness 已收斂，
TPEX／完整 market breadth 與跨日 volume baseline 留待下一個資料里程碑。

- 補齊跨市場 volume metadata。
- 統一 US latest completed session 與 JP／KR delayed policy。
- 讓 payload 已存在的 selected capability 產生 canonical `data.freshness`。
- 修正 breadth coverage、TPEX completeness、market volume baseline 與 `selection.include` 語意。

驗收：selected capability 不再因未選 supplemental 或舊 background health 被錯誤阻擋。

## Milestone 5：P2 運行面補強

狀態：部分完成；resource／TXF aliases、KR event registry 與 launcher
runner 已完成，外部資料 refresh／persistence 類工作留待後續 bounded rollout。

- 建立 bounded refresh／persistence health、market event registry、resource／futures aliases 與 timezone 正規化方案。
- 逐項以 provider policy、成本與可重播證據決定是否本輪實作。

驗收：每一項具有明確 owner、budget、failure visibility 與 rollout／rollback 說明。

## Stop-and-fix 規則

- targeted regression 失敗先修正，不帶著未知 failure 進 full validation。
- 若 formal runtime 與 source test 不一致，先驗證 launcher PID、實際 port、interpreter、reload 與 DB revision。
- 若需要外部大量 refresh、昂貴 quota、破壞性資料操作或擴大 trust boundary，暫停並向使用者確認。
- 若發現本輪修改與既有 dirty worktree 衝突，停止該檔修改並先釐清差異，不回退既有內容。
