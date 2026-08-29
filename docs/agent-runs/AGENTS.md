# Historical Agent Runs

此目錄是歷史任務紀錄，不是 current product、architecture、runtime 或 capability truth。

- 保留原始 Prompt、Plan、Progress、Acceptance 與 artifact 的歷史語境，不反向改寫成新架構。
- 搜尋 current owner／contract 時預設排除此目錄；只有追查決策 lineage、舊 migration 或驗證證據時才讀取。
- 歷史文件中的 provider priority、service-owned fallback、US context-only、舊 AI contract、port、status 或完成聲明不得覆蓋 repo root AGENTS、`docs/product/`、`docs/architecture/` 與 executable registry。
- Durable 新結論回寫 current architecture／product docs；新的長任務使用 `docs/exec-plans/active/`。
- 不做一次性大量搬移。需要歸檔時以 task folder 為單位移到 `docs/archive/agent-runs/`，並保留 Git history。

若使用者明確要求繼續既有 `docs/agent-runs/<task>`：

- 該 task 的 Prompt／Plan／Progress 可作為 task-local execution context。
- 它不得覆蓋 current executable registry、current architecture／product docs 或 runtime evidence；衝突時以 current truth 為準。
- Durable 新結論完成後回寫 current docs，不把舊 provider priority、fallback、contract inventory 或完成聲明重新升格為 current truth。
