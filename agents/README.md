# OMI Agent Adapters

This directory contains external agent adapters for Open Market Intelligence.

The adapters should stay thin:

- expose OMI capabilities through external protocols such as MCP
- call the backend `/api/ai/...` endpoints
- avoid direct database imports or duplicated market logic

Core AI research logic belongs in `backend/app/ai/`.
