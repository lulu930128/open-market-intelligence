# MCP 研究管理與人工執行

2026-11-06 current source：`ProposalVersion.workflow_origin` 為目前工作分類；缺省沿原 frozen nomination evidence 解析。移動只追加版本，不重寫原 evidence/hash。AI API 範圍為 AI_NOMINATION／OMI_SCREEN，台美共用。修訂可調策略與成本，反向 thesis 以新 proposal／新 initial risk 接替舊 proposal；舊歷史仍可查閱。

只有 AI_NOMINATION 可建立 research-linked manual_stage；盤後自動先轉分類。Stage 保留 creation/revision/original origin，使用者確認送出時再核對 current classification。AI 可修改未送 stage，不能呼叫 execution mutation。研究刪除不撤券商單，也不改已生效出場規則。

MCP model 使用固定 `/ai` routes；正式 submit/cancel/protection 透過標準 `_meta.ui.visibility=["app"]` 供 MCP frontend。Host tool visibility 是協定分工，不能說成對任意持有本機權限程序的 OS 隔離。API／Native 不新增第二次人工審批。

人工直接送單不等待研究 eligibility、掃描條件或 AI verdict。Frontend 可調每單 price/quantity/protection，Backend 轉給既有 Native owner，不持有 SDK 或第二份交易帳本。Legacy conditional promotion 保留原 API；新 MCP 使用 stage 路線，避免 TP2 被丟棄。

以下為原研究生命週期說明；現行 MCP 工作分類與人工執行以以上 source 契約為準。

# 研究提案的清單生命週期

台股與美股共用 `trade_journal` 作為 proposal version 的唯一保存 owner。清理候選清單不覆寫或刪除歷史證據，也不取消已採用到 Candidate 的條件候選。

## 刪除指令

`DELETE /api/research/trade-proposals/{creation_id}` 接受 `expected_revision_id`，在明確 transaction 中追加一筆 terminal version：`deleted_at == recorded_at`，保留原始市場、策略、evidence/hash、原始風險與 calendar。`effective_at` 仍是策略時間；刪除可見性由 `deleted_at`／knowledge time 擁有，因此已過期與尚未生效的提案均能立即從現行清單移除。

同一 deletion intent 重送回傳原 receipt；舊版 intent 回 409，不覆蓋其他人的修改。既有 revision／supersedes uniqueness 與 immutability triggers 仲裁競態；失敗 transaction 回滾。不存在回 404；已刪除的現行 detail、monitor、history、revise 與 promote 回 410 `PROPOSAL_DELETED`。刪除前的明確 knowledge time 仍可讀取當時證據與 paper replay。既有 Candidate 保留其已凍結的 provenance，新採用不接受 deleted head。

清單先取得最新已知 version，再排除 deleted head，最後做市場／來源／方向與分頁，不讓舊版頂替刪除版本。TW／US automatic nomination 仍依原 deterministic identity 去重；同筆已刪除提案回 `DELETED`，不產生替代 ID。新的交易日／策略 identity 仍可產生新的研究提案。

## 相容性與介面

清單投影由 Backend Journal HTTP service 擁有。`view=summary` 回傳
`research.proposal_list.summary.v1`，只含原 creation/revision、工作分類、方向、
資料日期、凍結評估限制與 evidence hash；`evidence_included=false`、
`execution_ready=false`。它不是完整 ProposalVersion，不能拿來驗證交易資格或重建 evidence。
Frontend 清單明確選 summary，選取後沿原單筆 detail API 讀取完整凍結內容。
AI `/ai` 清單預設 summary，以避免每頁重送所有 frozen snapshot；MCP 僅轉送投影選項。
既有完整清單仍可明確指定 `view=full`，一般 HTTP 清單缺省維持 full；
單筆 detail／revisions／mutation receipt 形狀與 evidence bytes 不變。台美股共用同一投影。

`ProposalVersion.deleted_at` 為 additive optional field，未刪除版本省略此欄位，既有 payload hash 與研究來源不變。沿用既有 Journal table，不新增 migration、不放寬 UPDATE／DELETE trigger。現行列表和提案讀取不向 consumer 輸出 tombstone；DELETE 使用專用 receipt contract。

發布時先載入支援 deleted_at 的 backend，再開放 UI 刪除。首筆刪除寫入後，不得直接回退到無法解析該欄位的舊 backend；如需回退，須保留此 reader／terminal visibility 能力，不改寫已保存的歷史。

研究頁不呈現美股排程面板、狀態輪詢或手動補掃。背景排程維持原設定；提案旁提供明確刪除確認，成功才更新清單，失敗／未知先重新讀取，不自動重送。清單／監控等 GET 不寫入或觸發 scan。
