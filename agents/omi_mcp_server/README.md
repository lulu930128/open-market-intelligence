# OMI MCP Server

Minimal stdio MCP adapter for Open Market Intelligence.

By default it exposes one public OMI tool and forwards calls to the local
FastAPI backend:

```text
MCP client -> agents/omi_mcp_server/server.py -> http://127.0.0.1:8300/api/ai/...
```

Run it after the OMI backend is running:

```powershell
python agents/omi_mcp_server/server.py
```

Optional environment variable:

```powershell
$env:OMI_API_BASE_URL = "http://127.0.0.1:8300"
$env:OMI_API_TIMEOUT_SECONDS = "180"
$env:OMI_MCP_EXPOSE_INTERNAL_TOOLS = "false"
$env:OMI_MCP_AI_TRUST_TOKEN = ""
```

Public tool:

- `omi.ask`

`omi.ask` is read-only by default. It accepts a question plus optional v2
`target` object, then the OMI backend resolves `target.type=auto` into a stock,
watchlist, market, or freshness context and chooses `data_only`, `brief`, `analysis`, or
`report` mode. Analysis mode calls OpenAI for a non-persistent OMI LLM answer,
so it requires a backend server-side trusted request and `allow_llm=true`.
Report mode calls OpenAI and persists an AI report, so it additionally requires
`allow_write=true`.
For US/ADR targets, trusted callers may set `allow_external_fetch=true` and a
small `tool_budget`; OMI's backend may then ask its LLM planner to choose from
allowlisted market-data tools, enforce the budget, execute the tools, and return
`tool_plan` / `tool_runs` evidence. The MCP client does not call those APIs
directly.
For Taiwan stock targets, `refresh_policy.mode=stale_first` with
`before_answer=true` makes OMI check local freshness first and, when trusted
external fetch is allowed, run the backend `tw.refresh_stock_evidence` tool
before rebuilding the evidence pack.
`caller_profile` is only a label and is not trusted for permissions.

OpenAI-backed analysis/report mode requires the OMI backend process to have
`OPENAI_API_KEY`, `OPENAI_LLM_API_KEY`, or `OMI_OPENAI_ENV_FILE` configured.
`OMI_OPENAI_ENV_FILE` may point at another local env file that contains
`OPENAI_API_KEY` or `OPENAI_LLM_API_KEY`. The MCP server does not read, store,
or forward API keys.

Set `OMI_MCP_EXPOSE_INTERNAL_TOOLS=true` only for debugging or a trusted local
agent that needs direct tool selection. If the backend disables local trust or
runs across a non-loopback boundary, configure `OMI_AI_TRUST_TOKEN` on the
backend and pass the same value to the MCP process as `OMI_MCP_AI_TRUST_TOKEN`.
Direct memory writes, brief saves, and LLM analysis/report generation are also
protected by that backend trust policy; regular external callers should go through
`omi.ask`.

Internal tools:

- `omi.read_market_overview`
- `omi.read_stock_context`
- `omi.read_watchlist_context`
- `omi.read_data_freshness`
- `omi.generate_stock_brief`
- `omi.generate_watchlist_brief`
- `omi.generate_stock_llm_report`
- `omi.generate_watchlist_llm_report`
- `omi.read_memories`
- `omi.write_memory`
- `omi.update_memory`
- `omi.archive_memory`
- `omi.read_reports`
- `omi.read_report`
- `omi.save_stock_brief`
- `omi.save_watchlist_brief`

Memory write tools only change AI research memory rows. They do not modify market,
watchlist, or source data. Archive incorrect memories instead of deleting them so
the history remains auditable.
