# OMI MCP Server

Minimal stdio MCP adapter for Open Market Intelligence.

It exposes read-only OMI tools and forwards calls to the local FastAPI backend:

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
```

OpenAI-backed tools require the OMI backend process to have `OPENAI_API_KEY`,
`OPENAI_LLM_API_KEY`, or `OMI_OPENAI_ENV_FILE` configured. `OMI_OPENAI_ENV_FILE`
may point at another local env file that contains `OPENAI_API_KEY` or
`OPENAI_LLM_API_KEY`. The MCP server does not read, store, or forward API keys.

Initial tools:

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
