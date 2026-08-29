# OMI Execution Plans

新的跨模組、長時間或可中斷任務使用：

- `active/<task>/Prompt.md`
- `active/<task>/Plan.md`
- `active/<task>/Progress.md`

完成後以 task folder 為單位移到 `completed/<task>/`。執行文件記錄 goals、constraints、milestones、acceptance、evidence 與 known issues，但不取代 current product／architecture truth。

任務完成時：

1. Durable product direction 更新到 `docs/product/`。
2. Durable architecture contract 更新到 `docs/architecture/`。
3. 最後已驗證 checkpoint 必要時更新 `docs/architecture/CurrentImplementationState.md`。
4. 一次性進度與 artifacts 留在 completed plan。

既有 `docs/agent-runs/` 是歷史資料，依需要逐步歸檔，不批次改寫。
