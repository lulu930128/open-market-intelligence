# OMI Architecture Index

本頁是架構文件的導航入口，不保存短期 implementation inventory。

## Current Product / Architecture Truth

- [Product Vision](../product/ProductVision.md)：產品定位、市場角色與非目標。
- [Operating Model](../product/OperatingModel.md)：各 plane 的責任與互動方式。
- [Quality Bar](../product/QualityBar.md)：資料、架構、AI、UX 與驗證品質門檻。
- [Backend Architecture](BackendArchitecture.md)：dependency direction、ownership、transaction、health 與 migration 原則。
- [OMI Decision Contract](OmiDecisionContract.md)：唯一 outward AI decision contract。
- [Financial Date Semantics](FinancialDateSemantics.md)：財務期間與日期語意。
- [Market Temporal Contract](MarketTemporalContract.md)：Market Session、item finalization、authority、release、reconciliation 與 freshness 的正交 axes。
- [Radar v2](RadarV2.md)：Radar contract、evaluation 與 legacy audit boundary。

## Planned Direction

- [Roadmap](../product/Roadmap.md)：milestone 與尚未完成的產品方向；planned／target／future 項目不得推定為已支援。

## 最後已記錄的實作狀態

- [Current Implementation State](CurrentImplementationState.md) 只整理最後一次有證據的 source／runtime／live／product checkpoint。
- 它不是即時 health page；實際 runtime 仍以 launcher identity、selected port、migration、API 與正式 session evidence 為準。

## Executable truth

Dataset、capability、owner、refresh operation、projection、health 與 lineage 必須由 source 內 typed registry／catalog／contract提供。文件可以說明理由與讀取方式，不複製完整 inventory 或固定數量。

Architecture constraint 與已接受 debt 應由 machine-readable constraint／debt manifest 與 architecture tests 執法；若尚未建立，文件必須如實標記，不得把文字規則描述成已機械保護。

Source capability truth 由 source registry／typed contract 擁有；running capability truth 由 runtime `/api/ai/tools`、loaded source identity 與 migration 判定。兩者不一致時是 runtime adoption mismatch，不是兩份同時有效的 current truth。

## 歷史與任務文件

- `docs/exec-plans/active/`：新任務的 active Prompt／Plan／Progress。
- `docs/exec-plans/completed/`：已完成任務的執行紀錄。
- `docs/agent-runs/`：既有歷史任務資料，不是 current truth。
- `docs/archive/architecture/`：歷史 architecture review／snapshot。

Durable 結論回寫本目錄或 `docs/product/`；短期進度、單次 acceptance artifact 與 dated rollout state 留在 task／archive surface。
