# \# Open Market Intelligence

# 

# Open Market Intelligence is a local-first market intelligence dashboard built with FastAPI and Next.js.

# 

# The project collects, normalizes, and analyzes public market data. Its current focus is to provide a traceable watchlist-based dashboard for stock monitoring, technical indicators, signal summaries, and historical price visualization.

# 

# This project is designed as a research and engineering prototype, not as an automated trading system.

# 

# \## Core Principles

# 

# \- Public data only

# \- Local-first architecture

# \- Raw data preservation

# \- Source traceability

# \- Rule-based analysis before AI summarization

# \- No automated trading

# \- No use of non-public material information

# 

# \## Current Features

# 

# \### Backend

# 

# \- FastAPI backend service

# \- SQLite local database

# \- Source registry

# \- Manual source refresh pipeline

# \- Raw data preservation

# \- TWSE daily market data parser

# \- Stock master sync and search APIs

# \- Historical stock price API

# \- Daily technical indicator API

# \- Watchlist group and item APIs

# \- Nested watchlist tree structure

# \- Recursive watchlist group delete

# \- Watchlist group backfill API

# \- Watchlist latest indicator summary API

# \- Watchlist latest signal summary API

# \- Watchlist latest ranking API

# 

# \### Frontend

# 

# \- Next.js dashboard

# \- Sidebar watchlist explorer

# \- Root and child watchlist group management

# \- Stock item management

# \- Watchlist group backfill trigger

# \- Ranking table

# \- Signal summary

# \- Indicator summary

# \- Stock detail panel

# \- Historical K-line chart

# \- Same-origin API proxy through `/omi-data`

# 

# \## Tech Stack

# 

# \### Backend

# 

# \- Python

# \- FastAPI

# \- SQLAlchemy

# \- SQLite

# \- pandas

# 

# \### Frontend

# 

# \- Next.js

# \- React

# \- TypeScript

# \- Tailwind CSS

# 

# \## Project Structure

# 

# ```text

# Open Market Intelligence/

# ├─ backend/

# │  └─ app/

# │     ├─ db/

# │     ├─ market/

# │     ├─ pipelines/

# │     ├─ routers/

# │     └─ watchlists/

# ├─ frontend/

# │  ├─ src/

# │  │  ├─ app/

# │  │  ├─ components/

# │  │  ├─ lib/

# │  │  └─ types/

# │  ├─ .env.example

# │  └─ next.config.ts

# └─ README.md

# ```

# 

# \## Local Development

# 

# \### 1. Backend

# 

# From the project root:

# 

# ```powershell

# cd "C:\\Open Market Intelligence"

# .\\.venv\\Scripts\\Activate.ps1

# cd backend

# python -m uvicorn app.main:app --reload --port 8000

# ```

# 

# Backend URLs:

# 

# ```text

# http://127.0.0.1:8000

# http://127.0.0.1:8000/docs

# http://127.0.0.1:8000/api/system/health

# ```

# 

# \### 2. Frontend

# 

# Create a local environment file:

# 

# ```powershell

# cd "C:\\Open Market Intelligence\\frontend"

# copy .env.example .env.local

# ```

# 

# Start the frontend:

# 

# ```powershell

# npm run dev

# ```

# 

# Frontend URL:

# 

# ```text

# http://127.0.0.1:3000

# ```

# 

# \## Frontend API Proxy

# 

# The frontend uses a same-origin proxy by default.

# 

# Browser-side requests are sent to:

# 

# ```text

# /omi-data/...

# ```

# 

# Next.js then rewrites them to the FastAPI backend:

# 

# ```text

# http://127.0.0.1:8000/api/...

# ```

# 

# Example:

# 

# ```text

# Frontend request:

# http://127.0.0.1:3000/omi-data/wl/tree

# 

# Rewritten backend request:

# http://127.0.0.1:8000/api/watchlists/tree

# ```

# 

# Frontend environment example:

# 

# ```env

# API\_PROXY\_TARGET=http://127.0.0.1:8000

# API\_PROXY\_PATH=/omi-data

# NEXT\_PUBLIC\_API\_PROXY\_PATH=/omi-data

# NEXT\_PUBLIC\_API\_BASE\_URL=

# ```

# 

# For local proxy mode, `NEXT\_PUBLIC\_API\_BASE\_URL` should stay empty.

# 

# \## Validation

# 

# \### Backend syntax check

# 

# ```powershell

# cd "C:\\Open Market Intelligence"

# .\\.venv\\Scripts\\Activate.ps1

# python -m compileall backend\\app

# ```

# 

# \### Frontend lint

# 

# ```powershell

# cd "C:\\Open Market Intelligence\\frontend"

# npm run lint

# ```

# 

# \### Frontend production build

# 

# ```powershell

# cd "C:\\Open Market Intelligence\\frontend"

# npm run build

# ```

# 

# \### Proxy check

# 

# With both backend and frontend running, open:

# 

# ```text

# http://127.0.0.1:3000/omi-data/wl/tree

# ```

# 

# Expected result:

# 

# ```text

# The request should be proxied to the FastAPI watchlist tree API.

# ```

# 

# \## Current Development Status

# 

# The project currently has a working backend and frontend prototype.

# 

# Completed baseline:

# 

# \- Backend data pipeline foundation

# \- Watchlist API foundation

# \- Indicator / signal / ranking APIs

# \- Frontend dashboard MVP

# \- Sidebar watchlist explorer

# \- Stock detail panel

# \- K-line chart

# \- Frontend proxy setup

# \- Production build stabilization

# 

# \## Roadmap

# 

# \### Near-term

# 

# \- Improve README and project documentation

# \- Add project status document

# \- Add stock search and quick-add UI

# \- Improve K-line chart interaction

# \- Add better empty-state and error-state UI

# \- Add backend tests for disabled source refresh and watchlist APIs

# 

# \### Mid-term

# 

# \- Add richer technical indicator rules

# \- Add source reliability and data quality dashboard

# \- Add report generation

# \- Add pre-market and post-market summary workflow

# \- Add AI-assisted summarization after rule-based analysis

# 

# \### Long-term

# 

# \- Multi-source public data integration

# \- Company event collector

# \- News and RSS collector

# \- International event collector

# \- Traceable research report generator

# \- Private local-first market intelligence assistant

# 

# \## Safety and Usage Notes

# 

# This project is for research, learning, and personal market monitoring.

# 

# It does not perform automated trading.  

# It does not use non-public material information.  

# It does not provide financial advice.  

# All analysis should be verified independently before making investment decisions.

