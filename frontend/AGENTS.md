<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

# OMI Frontend invariants

修改前先讀 repo root `AGENTS.md`、`docs/architecture/index.md`、相關 backend outward contract 與現有 component／API client pattern。

Frontend 擁有：

- Layout、interaction、responsive behavior、display density 與 accessibility。
- Selected view state、loading／empty／retry UX 與 viewer intent。
- Backend 明確允許的 presentation compatibility 與格式化。

Frontend 不擁有：

- Provider priority、production provider selection 或 cross-provider fallback。
- Freshness、market session、trading status、dataset repair 或 evidence finalization truth。
- AI decision、capability readiness、portfolio valuation 或 market-specific research calculation。

規則：

- Production request 不以 provider 參數繞過 backend Resolver。Diagnostic selector 必須明確標示且限於 diagnostics surface。
- GET 不作 refresh command；refresh、backfill、repair 使用 backend 明示且 bounded 的 operation。
- 不把 stale、partial、missing、fallback、warning 或 provider failure 顯示成正常值，也不把 daily／cached evidence 說成 live。
- Backend 已提供 authoritative value 時直接呈現；local calculation 只能是有明確 metadata 的 presentation fallback。
- Operational error、Dataset／Resolved Evidence health 與 blocking UI request state 必須分開。共用更新狀態可以承接 operation detail，但不得隱藏頁面需要立即呈現的資料限制或操作阻塞。

完成前依 UI 風險執行 lint、TypeScript、build 與必要的 browser／focused E2E。若只有 docs、copy 或 instruction 變更，只做 UTF-8 readback、相關靜態搜尋與 `git diff --check`，不跑不必要的 build、browser、E2E 或 runtime。
