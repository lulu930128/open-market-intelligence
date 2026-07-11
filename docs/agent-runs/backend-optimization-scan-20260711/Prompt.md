# Backend Optimization Scan 2026-07-11

## 目標

掃描 OMI 目前的 backend 與整體產品文件，整理一次大型後端優化的安全落點。這份任務不是直接重寫 backend，而是先建立可驗證、可分批執行、符合產品方向的優化路線。

## 背景

目前 OMI 已經有明確產品方向：台股核心、本機優先、backend 擁有市場資料、freshness、AI reasoning、tool orchestration 與 answer contract。Frontend、MCP、Kuro 與其他 consumer 應只消費 backend contract，不應自行補資料或重做市場判斷。

既有 agent-run 文件顯示，產品基線、payload slot contract 骨架、AI decision contract projection 與部分 frontend navigation hardening 已經完成；後端大優化應接續這些成果，不應重新設計已定義的 contract。

## Non-goals

- 不在目前掃描階段修改 runtime 行為。
- 不重寫 AI decision core、market data service 或 router。
- 不做 DB reset、資料清空、大量 refresh 或 provider live backfill。
- 不改 breaking API response shape；所有 contract 調整預設 additive。
- 不把 backend 邏輯搬到 frontend、MCP adapter 或 Kuro。

## Hard constraints

- 台股仍是核心市場；US/JP/KR/crypto 是 context layer。
- stale、partial、missing、best-effort、provider failure 必須可見。
- read path 不應隱性觸發昂貴 refresh、寫入 report/memory 或大量 quota。
- 大優化要先收斂現有 dirty worktree；避免在 60+ 檔未提交變更上直接做跨模組 refactor。
- 每個 batch 都要有 targeted regression 與 rollback-friendly diff。

## 掃描範圍

- `docs/product/`
- `README.md`
- `AGENTS.md`
- `backend/app/main.py`
- `backend/app/config.py`
- `backend/app/db/`
- `backend/app/ai/`
- `backend/app/routers/`
- `backend/app/market/`
- `backend/app/us_market/`
- `backend/app/jp_market/`
- `backend/app/kr_market/`
- `backend/app/crypto_market/`
- `backend/app/resource_market/`
- `backend/app/jobs/`
- `backend/tests/`
- 既有 `docs/agent-runs/`

## Done criteria

- 明確列出目前後端主要整理點與優先級。
- 每個優化 batch 都有 acceptance criteria 與驗證命令。
- 先保護既有 AI/payload/freshness contract，再安排程式拆分。
- 清楚標示哪些事情不該現在做。
