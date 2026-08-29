# OMI Agent Adapters

This directory contains external agent adapters for Open Market Intelligence.

Read [`AGENTS.md`](AGENTS.md) before changing an adapter. Current business and
capability truth comes from the backend contract and runtime schema, not this
directory's documentation.

The adapters should stay thin:

- expose OMI capabilities through external protocols such as MCP
- call the backend `/api/ai/...` endpoints
- avoid direct database imports or duplicated market logic

Core AI research logic belongs in `backend/app/ai/`.
